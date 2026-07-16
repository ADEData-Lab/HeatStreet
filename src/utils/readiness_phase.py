"""Atomic, retryable contract for the required retrofit-readiness phase."""

from __future__ import annotations

import gc
import hashlib
import json
import os
import shutil
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

from src.utils.run_integrity import (
    ArtifactManifest,
    RunContext,
    provenance_path,
    stamp_artifact_tree,
)


MANIFEST_NAMES = {
    "readiness": "readiness",
    "summary": "readiness_summary",
}

REQUIRED_COLUMNS = {
    "hp_readiness_tier",
    "hp_readiness_label",
    "fabric_prerequisite_cost",
    "system_technology",
    "system_cost",
    "total_cost",
    "total_retrofit_cost",
}


class RetrofitReadinessPhaseError(RuntimeError):
    """Raised after both required readiness attempts fail."""

    def __init__(self, failures: list[dict[str, Any]]):
        self.failures = failures
        causes = "; ".join(
            f"attempt {item['attempt']}: {item['exception_type']}: {item['message']}"
            for item in failures
        )
        super().__init__(f"Retrofit readiness failed after two attempts ({causes})")


def output_paths(root: Path) -> dict[str, Path]:
    return {
        "readiness": Path(root) / "retrofit_readiness_analysis.csv",
        "summary": Path(root) / "reports" / "retrofit_readiness_summary.txt",
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_provenance(path: Path, context: RunContext) -> None:
    sidecar = provenance_path(path)
    if not sidecar.is_file():
        raise RuntimeError(f"Readiness artifact has no provenance: {path}")
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    expected = {
        "run_id": context.run_id,
        "dataset_fingerprint": context.dataset_fingerprint,
        "authoritative_cohort": context.authoritative_cohort,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise RuntimeError(
                f"Readiness artifact provenance mismatch for {path}: "
                f"{key}={payload.get(key)!r}, expected {value!r}"
            )
    if payload.get("artifact_sha256") != _sha256(path):
        raise RuntimeError(f"Readiness artifact hash mismatch: {path}")


def validate_artifacts(
    paths: dict[str, Path], *, cohort_size: int, context: Optional[RunContext]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    missing_files = [name for name, path in paths.items() if not path.is_file()]
    if missing_files:
        raise RuntimeError(f"Readiness artifacts are missing: {missing_files}")

    readiness = pd.read_csv(paths["readiness"])
    if len(readiness) != cohort_size:
        raise RuntimeError(
            f"Readiness cohort mismatch: rows={len(readiness)}, expected={cohort_size}"
        )
    missing_columns = REQUIRED_COLUMNS.difference(readiness.columns)
    if missing_columns:
        raise RuntimeError(f"Readiness columns are missing: {sorted(missing_columns)}")
    tiers = pd.to_numeric(readiness["hp_readiness_tier"], errors="coerce")
    if tiers.isna().any() or not tiers.isin(range(1, 6)).all():
        invalid = sorted(set(readiness.loc[~tiers.isin(range(1, 6)), "hp_readiness_tier"].astype(str)))
        raise RuntimeError(f"Readiness contains invalid tiers: {invalid}")

    summary_text = paths["summary"].read_text(encoding="utf-8")
    expected_total = f"Total Properties Analyzed: {cohort_size:,}"
    if expected_total not in summary_text:
        raise RuntimeError("Readiness summary cohort does not match the active cohort")

    if context is not None:
        for path in paths.values():
            _validate_provenance(path, context)
    summary = {
        "total_properties": cohort_size,
        "tier_distribution": tiers.astype(int).value_counts().sort_index().to_dict(),
        "tier_percentages": (tiers.astype(int).value_counts(normalize=True).sort_index() * 100).to_dict(),
    }
    return readiness, summary


def _record_failure(
    context: Optional[RunContext], outputs_dir: Path, candidate: Path, attempt: int, exc: Exception
) -> dict[str, Any]:
    log_dir = context.log_dir if context is not None and context.run_root else outputs_dir.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    failure = {
        "attempt": attempt,
        "exception_type": type(exc).__name__,
        "message": str(exc),
        "traceback": traceback.format_exc(),
        "candidate_directory": str(candidate),
        "existing_artifact_paths": [
            str(path) for path in sorted(candidate.rglob("*")) if path.is_file()
        ],
    }
    failure_path = log_dir / f"retrofit_readiness_attempt_{attempt}_failure.json"
    failure_path.write_text(json.dumps(failure, indent=2), encoding="utf-8")
    failure["failure_log"] = str(failure_path)
    return failure


def _promote(candidate: Path, outputs_dir: Path) -> None:
    files = [path for path in sorted(candidate.rglob("*")) if path.is_file()]
    backup_dir = candidate / ".promotion-backup"
    promoted: list[Path] = []
    backups: list[tuple[Path, Path]] = []
    try:
        for source in files:
            destination = outputs_dir / source.relative_to(candidate)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                backup = backup_dir / source.relative_to(candidate)
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(destination, backup)
                backups.append((backup, destination))
            os.replace(source, destination)
            promoted.append(destination)
    except Exception:
        for destination in reversed(promoted):
            destination.unlink(missing_ok=True)
        for backup, destination in reversed(backups):
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(backup, destination)
        raise
    finally:
        shutil.rmtree(backup_dir, ignore_errors=True)


def _cleanup_candidate(candidate: Path) -> None:
    """Remove attempt trees reliably on Windows/OneDrive-backed workspaces."""
    for attempt in range(5):
        shutil.rmtree(candidate, ignore_errors=True)
        if not candidate.exists():
            return
        for directory in sorted(
            (path for path in candidate.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            try:
                directory.rmdir()
            except OSError:
                pass
        try:
            candidate.rmdir()
        except OSError:
            time.sleep(0.1 * (attempt + 1))
    if candidate.exists():
        raise RuntimeError(f"Could not remove readiness candidate directory: {candidate}")


def run_readiness_phase(
    df,
    *,
    context: Optional[RunContext],
    outputs_dir: Path,
    processed_dir: Path,
    analyzer_class,
    on_attempt_failure: Optional[Callable[[int, Exception], None]] = None,
) -> dict[str, Any]:
    """Generate, validate, promote, and register readiness, retrying once."""
    cohort_size = int(context.authoritative_cohort) if context and context.authoritative_cohort is not None else len(df)
    failures: list[dict[str, Any]] = []
    attempt_df = df

    for attempt in (1, 2):
        candidate = Path(outputs_dir) / f".readiness-candidate-attempt-{attempt}"
        _cleanup_candidate(candidate)
        candidate.mkdir(parents=True, exist_ok=True)
        try:
            if attempt_df is None or len(attempt_df) == 0:
                raise ValueError("No source dataframe available for retrofit readiness")
            analyzer = analyzer_class()
            readiness = analyzer.assess_heat_pump_readiness(attempt_df)
            summary = analyzer.generate_readiness_summary(readiness)
            paths = output_paths(candidate)
            paths["summary"].parent.mkdir(parents=True, exist_ok=True)
            analyzer.save_readiness_results(
                readiness, summary, output_path=paths["readiness"], summary_path=paths["summary"]
            )
            if context is not None:
                stamp_artifact_tree([candidate], context)
            validate_artifacts(paths, cohort_size=cohort_size, context=context)
            _promote(candidate, Path(outputs_dir))
            _cleanup_candidate(candidate)

            final = output_paths(Path(outputs_dir))
            if context is not None:
                manifest = ArtifactManifest.load(context)
                for key, logical_name in MANIFEST_NAMES.items():
                    manifest.register(
                        logical_name,
                        final[key],
                        phase="retrofit_readiness",
                        required=True,
                        publication_scope="client",
                        cohort=cohort_size,
                    )
            return {**final, "readiness_frame": readiness, "summary": summary, "attempt": attempt}
        except Exception as exc:
            failures.append(_record_failure(context, Path(outputs_dir), candidate, attempt, exc))
            if on_attempt_failure is not None:
                on_attempt_failure(attempt, exc)
            _cleanup_candidate(candidate)
            attempt_df = None
            gc.collect()
            if attempt == 1:
                try:
                    attempt_df = pd.read_parquet(Path(processed_dir) / "epc_london_adjusted.parquet")
                except Exception as reload_exc:
                    retry_candidate = Path(outputs_dir) / ".readiness-candidate-attempt-2"
                    retry_candidate.mkdir(parents=True, exist_ok=True)
                    failures.append(_record_failure(context, Path(outputs_dir), retry_candidate, 2, reload_exc))
                    _cleanup_candidate(retry_candidate)
                    break

    raise RetrofitReadinessPhaseError(failures)
