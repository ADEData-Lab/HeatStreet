"""Create a complete, auditable review bundle for a Heat Street run."""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


BUNDLE_FILENAME = "heatstreet_run_review_bundle.zip"
BUNDLE_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class BundleFile:
    """A source file and its stable location inside the review archive."""

    source: Path
    archive_path: str
    required: bool
    logical_name: str


_REQUIRED_RUN_FILES: tuple[tuple[str, str], ...] = (
    ("run_metadata", "outputs/run_metadata.json"),
    ("semantic_qa", "outputs/qa_checks.json"),
    ("one_stop_output", "outputs/one_stop_output.json"),
    ("scenario_summary", "outputs/scenario_results_summary.csv"),
    ("scenario_properties", "outputs/scenario_results_by_property.parquet"),
    ("stock_scenario_comparison", "outputs/stock_scenario_comparison.csv"),
    ("implementation_summary", "outputs/implementation_results_summary.csv"),
    ("implementation_properties", "outputs/implementation_results_by_property.parquet"),
    ("implementation_qa", "outputs/implementation_qa.json"),
    ("tenure_segmentation", "outputs/reports/tenure_segmentation.csv"),
    ("spatial_tier_summary", "outputs/pathway_suitability_by_tier.csv"),
    ("spatial_enrichment_summary", "outputs/spatial_enrichment_summary.json"),
    ("validation_report", "processed/validation_report.json"),
    ("methodological_adjustments", "processed/methodological_adjustments_summary.json"),
    ("run_manifest", "manifest.json"),
)

_OPTIONAL_RUN_FILES: tuple[tuple[str, str], ...] = (
    ("readiness_results", "outputs/retrofit_readiness_analysis.csv"),
    ("archetype_results", "outputs/archetype_analysis_results.json"),
    ("subsidy_sensitivity", "outputs/subsidy_sensitivity_analysis.csv"),
    ("borough_breakdown", "outputs/borough_breakdown.csv"),
    ("borough_priority", "outputs/reports/borough_priority_ranking.csv"),
    ("network_thresholds", "outputs/heat_network_connection_thresholds.csv"),
    ("old_vs_corrected", "outputs/old_vs_corrected_comparison.csv"),
    ("analysis_log", "outputs/analysis_log.txt"),
)

_STORED_SUFFIXES = {
    ".parquet",
    ".xlsx",
    ".xls",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".zip",
}


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 digest for a file without loading it into memory."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_latest_run(runs_dir: Path = Path("data/runs")) -> Path:
    """Find the most recent run that contains run metadata."""
    runs_dir = Path(runs_dir)
    if not runs_dir.is_dir():
        raise FileNotFoundError(f"Runs directory not found: {runs_dir}")

    candidates: list[tuple[float, Path]] = []
    for run_root in runs_dir.iterdir():
        metadata_path = run_root / "outputs" / "run_metadata.json"
        if not run_root.is_dir() or not metadata_path.is_file():
            continue
        candidates.append((_run_sort_key(metadata_path), run_root))

    if not candidates:
        raise FileNotFoundError(
            f"No completed Heat Street runs with outputs/run_metadata.json were found in {runs_dir}"
        )
    candidates.sort(key=lambda item: (item[0], item[1].name))
    return candidates[-1][1]


def create_run_review_bundle(
    run_root: Path,
    *,
    output_path: Path | None = None,
    require_passing_qa: bool = True,
    include_optional: bool = True,
) -> Path:
    """Create an atomic ZIP containing the files required for report review.

    The function refuses to create a partial bundle when any required file is
    missing. By default, it also requires semantic QA and Route A QA to pass.
    """
    run_root = Path(run_root).resolve()
    if not run_root.is_dir():
        raise FileNotFoundError(f"Run root not found: {run_root}")

    metadata_path = run_root / "outputs" / "run_metadata.json"
    metadata = _read_json(metadata_path, "run metadata")
    qa_path = run_root / "outputs" / "qa_checks.json"
    qa = _read_json(qa_path, "semantic QA")
    implementation_qa_path = run_root / "outputs" / "implementation_qa.json"
    implementation_qa = _read_json(implementation_qa_path, "Route A QA")

    if require_passing_qa:
        _require_qa_pass(qa, label="semantic QA")
        _require_qa_pass(implementation_qa, label="Route A QA")

    files = _collect_bundle_files(
        run_root,
        metadata=metadata,
        include_optional=include_optional,
    )
    missing_required = [
        item for item in files if item.required and not item.source.is_file()
    ]
    if missing_required:
        detail = ", ".join(
            f"{item.logical_name}: {item.source}" for item in missing_required
        )
        raise FileNotFoundError(
            "Cannot create a complete run review bundle. Missing required files: "
            + detail
        )

    selected = [item for item in files if item.source.is_file()]
    _assert_unique_archive_paths(selected)

    output_path = Path(
        output_path or (run_root / "outputs" / BUNDLE_FILENAME)
    ).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary_path.unlink(missing_ok=True)

    entries = [_manifest_entry(item) for item in selected]
    bundle_manifest = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_id": metadata.get("run_id"),
        "dataset_fingerprint": metadata.get("dataset_fingerprint"),
        "authoritative_cohort": metadata.get(
            "authoritative_cohort",
            metadata.get("authoritative_cohort_size"),
        ),
        "source_run_root": str(run_root),
        "semantic_qa_status": qa.get("status"),
        "implementation_qa_status": implementation_qa.get("status"),
        "required_file_count": sum(1 for item in selected if item.required),
        "optional_file_count": sum(1 for item in selected if not item.required),
        "files": entries,
    }

    readme = _bundle_readme(bundle_manifest)
    try:
        with zipfile.ZipFile(
            temporary_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            for item in selected:
                archive.write(
                    item.source,
                    arcname=item.archive_path,
                    compress_type=_compression_for(item.source),
                )
            archive.writestr(
                "bundle_manifest.json",
                json.dumps(bundle_manifest, indent=2, ensure_ascii=False),
            )
            archive.writestr("REVIEW_README.txt", readme)
        os.replace(temporary_path, output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    return output_path


def _collect_bundle_files(
    run_root: Path,
    *,
    metadata: dict[str, Any],
    include_optional: bool,
) -> list[BundleFile]:
    files = [
        BundleFile(
            source=run_root / relative_path,
            archive_path=relative_path.replace("\\", "/"),
            required=True,
            logical_name=logical_name,
        )
        for logical_name, relative_path in _REQUIRED_RUN_FILES
    ]

    config_snapshot = _resolve_config_snapshot(run_root, metadata)
    files.append(
        BundleFile(
            source=config_snapshot,
            archive_path="config_snapshot.yaml",
            required=True,
            logical_name="configuration_snapshot",
        )
    )

    if include_optional:
        files.extend(
            BundleFile(
                source=run_root / relative_path,
                archive_path=relative_path.replace("\\", "/"),
                required=False,
                logical_name=logical_name,
            )
            for logical_name, relative_path in _OPTIONAL_RUN_FILES
        )

    existing_sources = {item.source.resolve() for item in files if item.source.exists()}
    sidecars: list[BundleFile] = []
    for item in list(files):
        if not item.source.is_file():
            continue
        sidecar = item.source.with_name(item.source.name + ".provenance.json")
        if sidecar.is_file() and sidecar.resolve() not in existing_sources:
            sidecars.append(
                BundleFile(
                    source=sidecar,
                    archive_path=item.archive_path + ".provenance.json",
                    required=False,
                    logical_name=item.logical_name + "_provenance",
                )
            )
            existing_sources.add(sidecar.resolve())
    files.extend(sidecars)
    return files


def _resolve_config_snapshot(run_root: Path, metadata: dict[str, Any]) -> Path:
    configured = metadata.get("configuration_snapshot")
    candidates: list[Path] = []
    if configured:
        configured_path = Path(str(configured))
        if configured_path.is_absolute():
            candidates.append(configured_path)
        else:
            candidates.append(run_root / configured_path)
    candidates.extend(
        (
            run_root / "config_snapshot.yaml",
            run_root / "outputs" / "config_snapshot.yaml",
            run_root / "processed" / "config_snapshot.yaml",
        )
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return candidates[0].resolve() if candidates else (run_root / "config_snapshot.yaml")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"{label.capitalize()} file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label.capitalize()} is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label.capitalize()} must contain a JSON object: {path}")
    return payload


def _require_qa_pass(payload: dict[str, Any], *, label: str) -> None:
    if payload.get("status") != "pass":
        raise RuntimeError(
            f"{label.capitalize()} status is {payload.get('status')!r}; refusing to package a review bundle"
        )
    critical_failures = payload.get("critical_failure_count")
    if critical_failures not in (None, 0):
        raise RuntimeError(
            f"{label.capitalize()} has {critical_failures} critical failures; refusing to package"
        )
    contracts = payload.get("contracts")
    if isinstance(contracts, dict):
        failed = sorted(name for name, passed in contracts.items() if passed is not True)
        if failed:
            raise RuntimeError(
                f"{label.capitalize()} contracts failed: {failed}; refusing to package"
            )


def _run_sort_key(metadata_path: Path) -> float:
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return metadata_path.stat().st_mtime
    for field in ("analysis_end", "end_time", "analysis_start", "start_time"):
        value = metadata.get(field)
        if not value:
            continue
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
    return metadata_path.stat().st_mtime


def _manifest_entry(item: BundleFile) -> dict[str, Any]:
    return {
        "logical_name": item.logical_name,
        "archive_path": item.archive_path,
        "source_path": str(item.source),
        "required": item.required,
        "size_bytes": item.source.stat().st_size,
        "sha256": sha256_file(item.source),
    }


def _assert_unique_archive_paths(files: Iterable[BundleFile]) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for item in files:
        if item.archive_path in seen:
            duplicates.add(item.archive_path)
        seen.add(item.archive_path)
    if duplicates:
        raise RuntimeError(f"Duplicate archive paths: {sorted(duplicates)}")


def _compression_for(path: Path) -> int:
    return zipfile.ZIP_STORED if path.suffix.lower() in _STORED_SUFFIXES else zipfile.ZIP_DEFLATED


def _bundle_readme(manifest: dict[str, Any]) -> str:
    return (
        "Heat Street run review bundle\n"
        "=============================\n\n"
        f"Run ID: {manifest.get('run_id')}\n"
        f"Dataset fingerprint: {manifest.get('dataset_fingerprint')}\n"
        f"Authoritative cohort: {manifest.get('authoritative_cohort')}\n"
        f"Semantic QA: {manifest.get('semantic_qa_status')}\n"
        f"Route A QA: {manifest.get('implementation_qa_status')}\n\n"
        "This archive contains the final one-stop report, scenario outputs, Route A\n"
        "property and summary outputs, both QA payloads, tenure and spatial summaries,\n"
        "validation and adjustment records, the run manifest, and the configuration\n"
        "snapshot. bundle_manifest.json records each source path, file size, and SHA-256.\n"
    )
