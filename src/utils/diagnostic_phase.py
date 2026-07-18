"""Atomic, run-scoped diagnostic pathway generation and validation."""

from __future__ import annotations

import gc
import hashlib
import json
import os
import shutil
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


PATHWAY_IDS = (
    "baseline",
    "fabric_only",
    "fabric_plus_hp_only",
    "fabric_plus_hn_only",
    "fabric_plus_hp_plus_hn",
)
COMPARISON_IDS = PATHWAY_IDS[1:]
MANIFEST_NAMES = {
    "property_results": "diagnostic_pathway_properties",
    "summary": "diagnostic_pathways",
    "comparison_csv": "diagnostic_hp_hn_comparison",
}


class DiagnosticPathwayPhaseError(RuntimeError):
    """Both attempts at the required diagnostic phase failed."""

    def __init__(self, failures: list[dict[str, Any]]):
        self.failures = failures
        detail = "; ".join(
            f"attempt {item['attempt']}: {item['exception_type']}: {item['message']}"
            for item in failures
        )
        super().__init__(f"Diagnostic pathway phase failed after two attempts ({detail})")


def output_paths(root: Path) -> dict[str, Path]:
    return {
        "property_results": root / "pathway_results_by_property.parquet",
        "summary": root / "pathway_results_summary.csv",
        "comparison_csv": root / "comparisons" / "hn_vs_hp_comparison.csv",
        "comparison_snippet": root / "comparisons" / "hn_vs_hp_report_snippet.md",
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
        raise RuntimeError(f"Diagnostic artifact has no provenance: {path}")
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    expected = {
        "run_id": context.run_id,
        "dataset_fingerprint": context.dataset_fingerprint,
        "authoritative_cohort": context.authoritative_cohort,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise RuntimeError(
                f"Diagnostic artifact provenance mismatch for {path}: "
                f"{key}={payload.get(key)!r}, expected {value!r}"
            )
    if payload.get("artifact_sha256") != _sha256(path):
        raise RuntimeError(f"Diagnostic artifact hash mismatch: {path}")


def validate_artifacts(
    paths: dict[str, Path],
    *,
    cohort_size: int,
    context: Optional[RunContext],
) -> None:
    """Enforce diagnostic model-family, cohort, row, and provenance invariants."""
    mandatory = ("property_results", "summary", "comparison_csv")
    missing = [name for name in mandatory if not paths[name].is_file()]
    if missing:
        raise RuntimeError(f"Diagnostic artifacts are missing: {missing}")

    properties = pd.read_parquet(paths["property_results"])
    summary = pd.read_csv(paths["summary"])
    comparison = pd.read_csv(paths["comparison_csv"])

    if "pathway_id" not in properties:
        raise RuntimeError("Diagnostic property results have no pathway_id column")
    counts = properties.groupby("pathway_id", dropna=False).size().to_dict()
    if set(counts) != set(PATHWAY_IDS):
        raise RuntimeError(f"Diagnostic property pathway IDs mismatch: {sorted(map(str, counts))}")
    wrong_counts = {str(key): int(value) for key, value in counts.items() if int(value) != cohort_size}
    expected_rows = cohort_size * len(PATHWAY_IDS)
    if wrong_counts or len(properties) != expected_rows:
        raise RuntimeError(
            "Diagnostic property row-count reconciliation failed: "
            f"rows={len(properties)}, expected={expected_rows}, pathway_counts={wrong_counts}"
        )

    required = {
        "pathway_id", "model_family", "intended_reporting_use",
        "headline_reporting_eligible", "n_properties",
    }
    missing_columns = required.difference(summary.columns)
    if missing_columns:
        raise RuntimeError(f"Diagnostic summary columns are missing: {sorted(missing_columns)}")
    if set(summary["pathway_id"].astype(str)) != set(PATHWAY_IDS):
        raise RuntimeError("Diagnostic summary pathway IDs do not match configured pathways")
    if not summary["model_family"].eq("diagnostic_full_fabric_pathway").all():
        raise RuntimeError("Diagnostic summary contains an invalid model_family")
    if not summary["intended_reporting_use"].eq("diagnostic_distributional_only").all():
        raise RuntimeError("Diagnostic summary contains a non-diagnostic reporting use")
    headline = summary["headline_reporting_eligible"].astype(str).str.casefold()
    if headline.isin({"true", "1", "yes"}).any():
        raise RuntimeError("Diagnostic summary contains headline-eligible rows")
    summary_counts = pd.to_numeric(summary["n_properties"], errors="coerce")
    if summary_counts.isna().any() or not summary_counts.eq(cohort_size).all():
        raise RuntimeError("Diagnostic summary cohort does not match the active cohort")

    if "pathway_id" not in comparison:
        raise RuntimeError("HP/HN comparison has no pathway_id column")
    comparison_ids = set(comparison["pathway_id"].astype(str))
    if comparison_ids != set(COMPARISON_IDS):
        raise RuntimeError(f"HP/HN comparison pathway rows mismatch: {sorted(comparison_ids)}")
    if "n_homes" not in comparison:
        raise RuntimeError("HP/HN comparison has no n_homes column")
    comparison_counts = pd.to_numeric(comparison["n_homes"], errors="coerce")
    if comparison_counts.isna().any() or not comparison_counts.eq(cohort_size).all():
        raise RuntimeError("HP/HN comparison cohort does not match the active cohort")

    if context is not None:
        for name in mandatory:
            _validate_provenance(paths[name], context)


def registered_result(context: Optional[RunContext]) -> Optional[dict[str, Any]]:
    """Reuse only manifest-registered artifacts whose hashes and context still match."""
    if context is None or context.run_root is None:
        return None
    try:
        manifest = ArtifactManifest.load(context)
        paths = {key: manifest.resolve(name) for key, name in MANIFEST_NAMES.items()}
        paths["comparison_snippet"] = context.output_dir / "comparisons" / "hn_vs_hp_report_snippet.md"
        for name in MANIFEST_NAMES.values():
            record = manifest.artifacts[name]
            if (
                record.run_id != context.run_id
                or record.dataset_fingerprint != context.dataset_fingerprint
                or record.cohort != context.authoritative_cohort
            ):
                raise RuntimeError(f"Diagnostic manifest context mismatch: {name}")
        validate_artifacts(
            paths,
            cohort_size=int(context.authoritative_cohort),
            context=context,
        )
        return {
            **paths,
            "comparison_snippet": paths["comparison_snippet"] if paths["comparison_snippet"].is_file() else None,
            "rebuilt": False,
        }
    except Exception:
        return None


def _record_failure(
    context: Optional[RunContext],
    outputs_dir: Path,
    candidate_dir: Path,
    attempt: int,
    exc: Exception,
) -> dict[str, Any]:
    log_dir = context.log_dir if context is not None and context.run_root else outputs_dir.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    failure = {
        "attempt": attempt,
        "exception_type": type(exc).__name__,
        "message": str(exc),
        "traceback": traceback.format_exc(),
        "candidate_directory": str(candidate_dir),
        "artifact_paths": {
            name: str(path)
            for name, path in output_paths(candidate_dir).items()
        },
        "existing_artifact_paths": [
            str(path) for path in sorted(candidate_dir.rglob("*")) if path.is_file()
        ],
    }
    path = log_dir / f"diagnostic_pathway_attempt_{attempt}_failure.json"
    path.write_text(json.dumps(failure, indent=2), encoding="utf-8")
    failure["failure_log"] = str(path)
    return failure


def _promote(candidate_dir: Path, outputs_dir: Path) -> None:
    """Move all validated candidate files with rollback if any replacement fails."""
    files = [path for path in sorted(candidate_dir.rglob("*")) if path.is_file()]
    backup_dir = candidate_dir / ".promotion-backup"
    promoted: list[Path] = []
    backups: list[tuple[Path, Path]] = []
    try:
        for source in files:
            destination = outputs_dir / source.relative_to(candidate_dir)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                backup = backup_dir / source.relative_to(candidate_dir)
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


def run_diagnostic_phase(
    df,
    *,
    context: Optional[RunContext],
    outputs_dir: Path,
    processed_dir: Path,
    pathway_modeler_class,
    comparison_reporter_class,
    progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
    on_attempt_failure: Optional[Callable[[int, Exception], None]] = None,
) -> dict[str, Any]:
    """Generate, validate, promote, and register diagnostics, retrying exactly once."""
    cached = registered_result(context)
    if cached is not None:
        return cached

    cohort_size = int(context.authoritative_cohort) if context and context.authoritative_cohort is not None else len(df)
    failures: list[dict[str, Any]] = []
    attempt_df = df

    for attempt in (1, 2):
        candidate = outputs_dir / f".diagnostic-candidate-attempt-{attempt}"
        shutil.rmtree(candidate, ignore_errors=True)
        candidate.mkdir(parents=True, exist_ok=True)
        modeler = results = summary = reporter = None
        try:
            if attempt_df is None or len(attempt_df) == 0:
                raise ValueError("No source dataframe available for diagnostic pathway modeling")
            modeler = pathway_modeler_class(output_dir=candidate)
            if progress_callback is None:
                results = modeler.model_all_pathways(attempt_df)
            else:
                results = modeler.model_all_pathways(attempt_df, progress_callback=progress_callback)
            summary = modeler.generate_pathway_summary(results)
            modeler.export_results(results, summary)
            reporter = comparison_reporter_class(outputs_dir=candidate)
            reporter.generate_comparisons(results_path=candidate / "pathway_results_by_property.parquet")
            if context is not None:
                stamp_artifact_tree([candidate], context)
            validate_artifacts(output_paths(candidate), cohort_size=cohort_size, context=context)
            _promote(candidate, outputs_dir)
            shutil.rmtree(candidate, ignore_errors=True)

            final = output_paths(outputs_dir)
            if context is not None:
                manifest = ArtifactManifest.load(context)
                for key, logical_name in MANIFEST_NAMES.items():
                    manifest.register(
                        logical_name,
                        final[key],
                        phase="diagnostic_pathways",
                        publication_scope="internal",
                        cohort=cohort_size,
                    )
            return {
                **final,
                "comparison_snippet": final["comparison_snippet"] if final["comparison_snippet"].is_file() else None,
                "rebuilt": True,
                "attempt": attempt,
            }
        except Exception as exc:
            failures.append(_record_failure(context, outputs_dir, candidate, attempt, exc))
            if on_attempt_failure is not None:
                on_attempt_failure(attempt, exc)
            shutil.rmtree(candidate, ignore_errors=True)
            modeler = results = summary = reporter = None
            attempt_df = None
            gc.collect()
            if attempt == 1:
                try:
                    attempt_df = pd.read_parquet(processed_dir / "epc_london_adjusted_spatial.parquet")
                except Exception as reload_exc:
                    retry_candidate = outputs_dir / ".diagnostic-candidate-attempt-2"
                    retry_candidate.mkdir(parents=True, exist_ok=True)
                    failures.append(_record_failure(context, outputs_dir, retry_candidate, 2, reload_exc))
                    shutil.rmtree(retry_candidate, ignore_errors=True)
                    break

    raise DiagnosticPathwayPhaseError(failures)
