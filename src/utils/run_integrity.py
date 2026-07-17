"""Run-scoped provenance and dataset integrity helpers."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd

from src.utils.staged_dataset import DatasetReference, parquet_dataset_source


PROVENANCE_SUFFIX = ".provenance.json"


@dataclass(frozen=True)
class RunContext:
    run_id: str
    dataset_fingerprint: Optional[str] = None
    mode: str = "development"
    analysis_start: Optional[str] = None
    git_commit: Optional[str] = None
    configuration_sha256: Optional[str] = None
    sample_start_date: Optional[str] = None
    sample_end_date: Optional[str] = None
    run_root: Optional[Path] = None
    source_identifier: Optional[str] = None
    source_fingerprint: Optional[str] = None
    authoritative_cohort: Optional[int] = None
    analysis_end: Optional[str] = None
    runtime_seconds: Optional[float] = None
    run_status: str = "running"

    @classmethod
    def create(cls, **kwargs: Any) -> "RunContext":
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        kwargs.setdefault("analysis_start", datetime.now(timezone.utc).isoformat())
        return cls(run_id=f"{timestamp}-{uuid.uuid4().hex[:12]}", **kwargs)

    def with_dataset_fingerprint(self, fingerprint: str) -> "RunContext":
        return replace(self, dataset_fingerprint=fingerprint)

    def with_run_root(self, run_root: Path) -> "RunContext":
        return replace(self, run_root=Path(run_root))

    def with_cohort(self, cohort: int) -> "RunContext":
        return replace(self, authoritative_cohort=int(cohort))

    def finalize(self, *, analysis_end: Optional[str] = None, runtime_seconds: float) -> "RunContext":
        return replace(
            self,
            analysis_end=analysis_end or datetime.now(timezone.utc).isoformat(),
            runtime_seconds=float(runtime_seconds),
            run_status="complete",
        )

    def with_timing(
        self,
        *,
        analysis_end: Optional[str] = None,
        runtime_seconds: Optional[float] = None,
    ) -> "RunContext":
        """Attach report timing while keeping the run explicitly unfinalized."""
        end_value = analysis_end or datetime.now(timezone.utc).isoformat()
        runtime_value = runtime_seconds
        if runtime_value is None:
            if self.analysis_start is None:
                raise ValueError("Run start time is missing")
            start = datetime.fromisoformat(self.analysis_start.replace("Z", "+00:00"))
            end = datetime.fromisoformat(end_value.replace("Z", "+00:00"))
            runtime_value = (end - start).total_seconds()
        return replace(
            self,
            analysis_end=end_value,
            runtime_seconds=float(runtime_value),
            run_status="running",
        )

    def fail(self) -> "RunContext":
        return replace(self, run_status="failed")

    @property
    def finalized(self) -> bool:
        return (
            self.run_status == "complete"
            and self.analysis_end is not None
            and self.runtime_seconds is not None
        )

    @property
    def processed_dir(self) -> Path:
        return self._run_path("processed")

    @property
    def output_dir(self) -> Path:
        return self._run_path("outputs")

    @property
    def log_dir(self) -> Path:
        return self._run_path("logs")

    @property
    def manifest_path(self) -> Path:
        if self.run_root is None:
            raise ValueError("Run root has not been established")
        return Path(self.run_root) / "manifest.json"

    def _run_path(self, name: str) -> Path:
        if self.run_root is None:
            raise ValueError("Run root has not been established")
        return Path(self.run_root) / name

    def validate_production_report(self, *, require_complete: bool = True) -> None:
        if self.mode != "production":
            return
        required = {
            "dataset_fingerprint": self.dataset_fingerprint,
            "authoritative_cohort": self.authoritative_cohort,
            "source_fingerprint": self.source_fingerprint,
            "git_commit": self.git_commit,
            "configuration_sha256": self.configuration_sha256,
            "analysis_end": self.analysis_end,
            "runtime_seconds": self.runtime_seconds,
        }
        missing = [name for name, value in required.items() if value in (None, "")]
        if require_complete and not self.finalized:
            missing.append("finalized_context")
        if missing:
            raise ValueError(f"Production report context is incomplete: {sorted(set(missing))}")
        self.validate_timing()

    def validate_timing(self, *, tolerance_seconds: float = 2.0) -> None:
        """Validate UTC chronology and reconcile runtime to wall clock."""
        if self.analysis_start is None or self.analysis_end is None or self.runtime_seconds is None:
            raise ValueError("Run timing is incomplete")
        start = datetime.fromisoformat(self.analysis_start.replace("Z", "+00:00"))
        end = datetime.fromisoformat(self.analysis_end.replace("Z", "+00:00"))
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("Run timestamps must be timezone-aware UTC values")
        if start.utcoffset() != timezone.utc.utcoffset(start) or end.utcoffset() != timezone.utc.utcoffset(end):
            raise ValueError("Run timestamps must be expressed in UTC")
        wall_clock = (end - start).total_seconds()
        if wall_clock < 0 or float(self.runtime_seconds) < 0:
            raise ValueError("Run chronology and runtime must be non-negative")
        if abs(wall_clock - float(self.runtime_seconds)) > float(tolerance_seconds):
            raise ValueError(
                f"Runtime does not reconcile to UTC wall clock within {tolerance_seconds:g} seconds"
            )

    def to_dict(self) -> dict[str, Any]:
        if not self.dataset_fingerprint:
            raise ValueError("Dataset fingerprint has not been established")
        payload = asdict(self)
        payload.pop("run_status", None)
        if payload.get("run_root") is not None:
            payload["run_root"] = str(payload["run_root"])
        return {key: value for key, value in payload.items() if value is not None}


@dataclass(frozen=True)
class ArtifactRecord:
    logical_name: str
    path: str
    phase: str
    run_id: str
    dataset_fingerprint: str
    cohort: Optional[int]
    created_at: str
    required: bool
    publication_scope: str
    sha256: str
    schema_version: str
    validation_status: str


@dataclass
class ArtifactManifest:
    context: RunContext
    artifacts: dict[str, ArtifactRecord] = field(default_factory=dict)
    schema_version: str = "1.0"

    @classmethod
    def load(cls, context: RunContext) -> "ArtifactManifest":
        manifest = cls(context)
        if not context.manifest_path.exists():
            return manifest
        payload = json.loads(context.manifest_path.read_text(encoding="utf-8"))
        if payload.get("run_id") != context.run_id:
            raise RuntimeError("Manifest belongs to a different run")
        manifest.artifacts = {
            name: ArtifactRecord(**record) for name, record in payload.get("artifacts", {}).items()
        }
        return manifest

    def register(
        self,
        logical_name: str,
        artifact_path: Path,
        *,
        phase: str,
        required: bool = True,
        publication_scope: str = "client",
        cohort: Optional[int] = None,
        schema_version: str = "1.0",
        validation_status: str = "valid",
    ) -> ArtifactRecord:
        path = Path(artifact_path).resolve()
        root = Path(self.context.run_root).resolve() if self.context.run_root else None
        if root is None or path != root and root not in path.parents:
            raise ValueError(f"Artifact is outside the active run: {path}")
        if not path.is_file():
            raise FileNotFoundError(path)
        record = ArtifactRecord(
            logical_name=logical_name,
            path=path.relative_to(root).as_posix(),
            phase=phase,
            run_id=self.context.run_id,
            dataset_fingerprint=str(self.context.dataset_fingerprint),
            cohort=int(cohort) if cohort is not None else self.context.authoritative_cohort,
            created_at=datetime.now(timezone.utc).isoformat(),
            required=required,
            publication_scope=publication_scope,
            sha256=_file_sha256(path),
            schema_version=schema_version,
            validation_status=validation_status,
        )
        self.artifacts[logical_name] = record
        self.save()
        return record

    def resolve(self, logical_name: str, *, require_valid: bool = True) -> Path:
        if logical_name not in self.artifacts:
            raise RuntimeError(f"Artifact is not registered: {logical_name}")
        record = self.artifacts[logical_name]
        path = Path(self.context.run_root) / record.path
        if not path.is_file() or _file_sha256(path) != record.sha256:
            raise RuntimeError(f"Registered artifact is missing or changed: {logical_name}")
        if require_valid and record.validation_status != "valid":
            raise RuntimeError(f"Registered artifact is not valid: {logical_name}")
        return path

    def require(self, logical_names: Iterable[str]) -> None:
        for name in logical_names:
            self.resolve(name)

    def save(self) -> None:
        self.context.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.schema_version,
            "run_id": self.context.run_id,
            "run_status": self.context.run_status,
            "context": self.context.to_dict(),
            "artifacts": {name: asdict(record) for name, record in sorted(self.artifacts.items())},
        }
        temp = self.context.manifest_path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(temp, self.context.manifest_path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.1 * (attempt + 1))


def fingerprint_dataset(dataset: pd.DataFrame | DatasetReference) -> str:
    """Return a deterministic SHA-256 fingerprint for the final adjusted dataset."""
    digest = hashlib.sha256()
    if isinstance(dataset, DatasetReference):
        sources = parquet_dataset_source(dataset.parquet_path)
        source_paths = [sources] if isinstance(sources, str) else sources
        for source in source_paths:
            path = Path(source)
            digest.update(path.name.encode("utf-8"))
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        digest.update(str(dataset.row_count).encode("ascii"))
        return digest.hexdigest()

    digest.update(json.dumps(list(dataset.columns), ensure_ascii=False).encode("utf-8"))
    digest.update(json.dumps([str(dtype) for dtype in dataset.dtypes]).encode("utf-8"))
    row_hashes = pd.util.hash_pandas_object(dataset, index=True, categorize=True).values
    digest.update(row_hashes.tobytes())
    digest.update(str(len(dataset)).encode("ascii"))
    return digest.hexdigest()


def provenance_path(artifact_path: Path) -> Path:
    path = Path(artifact_path)
    return path.with_name(path.name + PROVENANCE_SUFFIX)


def stamp_artifact(
    artifact_path: Path,
    context: RunContext,
    *,
    record_count: Optional[int] = None,
) -> Path:
    """Write a provenance sidecar for an existing current-run artifact."""
    artifact_path = Path(artifact_path)
    if not artifact_path.is_file():
        raise FileNotFoundError(f"Cannot stamp missing artifact: {artifact_path}")
    payload: dict[str, Any] = {
        **context.to_dict(),
        "artifact": artifact_path.name,
        "artifact_sha256": _file_sha256(artifact_path),
        "stamped_at": datetime.now(timezone.utc).isoformat(),
    }
    if record_count is not None:
        payload["record_count"] = int(record_count)
    sidecar = provenance_path(artifact_path)
    sidecar.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return sidecar


def stamp_artifact_tree(roots: Iterable[Path], context: RunContext) -> list[Path]:
    """Stamp every analytical file under the supplied run-scoped roots."""
    stamped: list[Path] = []
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.name.endswith(PROVENANCE_SUFFIX):
                continue
            stamped.append(stamp_artifact(path, context))
    return stamped


def require_current_artifact(artifact_path: Path, context: RunContext) -> dict[str, Any]:
    """Reject missing, stale, fingerprint-mismatched, or modified artifacts."""
    artifact_path = Path(artifact_path)
    if not artifact_path.is_file():
        raise RuntimeError(f"Required current-run artifact is missing: {artifact_path}")
    sidecar = provenance_path(artifact_path)
    if not sidecar.is_file():
        raise RuntimeError(f"Artifact has no current-run provenance: {artifact_path}")
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    expected = context.to_dict()
    for key, value in expected.items():
        if payload.get(key) != value:
            raise RuntimeError(
                f"Artifact provenance mismatch for {artifact_path}: "
                f"{key}={payload.get(key)!r}, expected {value!r}"
            )
    actual_hash = _file_sha256(artifact_path)
    if payload.get("artifact_sha256") != actual_hash:
        raise RuntimeError(f"Artifact changed after provenance was stamped: {artifact_path}")
    return payload


def publish_run_outputs(
    run_output_dir: Path,
    public_output_dir: Path,
    run_id: str,
    *,
    archive_root: Optional[Path] = None,
) -> Path:
    """Atomically replace public outputs with a validated run snapshot."""
    run_output_dir = Path(run_output_dir)
    public_output_dir = Path(public_output_dir)
    if not (run_output_dir / "one_stop_output.json").is_file():
        raise RuntimeError("Validated one-stop output is missing; refusing publication")
    from src.utils.semantic_qa import require_passing_qa
    require_passing_qa(run_output_dir / "qa_checks.json", run_id=run_id)
    temp_dir = public_output_dir.parent / f".{public_output_dir.name}.publish-{run_id}"
    rollback_dir = public_output_dir.parent / f".{public_output_dir.name}.rollback-{run_id}"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    shutil.copytree(run_output_dir, temp_dir)
    if rollback_dir.exists():
        shutil.rmtree(rollback_dir)
    had_publication = public_output_dir.exists()
    if had_publication:
        archive_root = Path(archive_root or public_output_dir.parent / "output_archives")
        archive = archive_root / run_id
        archive.mkdir(parents=True, exist_ok=False)
        shutil.copytree(public_output_dir, archive / "previous_publication")
        os.replace(public_output_dir, rollback_dir)
    try:
        os.replace(temp_dir, public_output_dir)
    except Exception:
        if had_publication and rollback_dir.exists() and not public_output_dir.exists():
            os.replace(rollback_dir, public_output_dir)
        raise
    if rollback_dir.exists():
        shutil.rmtree(rollback_dir)
    return public_output_dir


def validate_scenario_invariants(
    scenarios: pd.DataFrame,
    *,
    authoritative_cohort: int,
    analysis_horizon_years: int,
) -> None:
    """Enforce exact cohort/count identities and tolerance-bound model arithmetic."""
    required = {
        "total_properties", "capital_cost_total", "capital_cost_per_property",
        "baseline_bill_total", "post_measure_bill_total", "annual_bill_savings",
        "baseline_co2_total_kg", "post_measure_co2_total_kg", "annual_co2_reduction_kg",
        "cost_per_tco2_20yr_gbp",
    }
    missing = required.difference(scenarios.columns)
    if missing:
        raise RuntimeError(f"Scenario invariant inputs are missing: {sorted(missing)}")
    for index, row in scenarios.iterrows():
        label = row.get("scenario_id", index)
        if int(row["total_properties"]) != int(authoritative_cohort):
            raise RuntimeError(f"Scenario {label} cohort mismatch")
        _assert_numeric_identity(
            float(row["capital_cost_total"]),
            float(row["capital_cost_per_property"]) * int(row["total_properties"]),
            kind="money", label=f"{label} capital cost",
        )
        _assert_numeric_identity(
            float(row["annual_bill_savings"]),
            float(row["baseline_bill_total"]) - float(row["post_measure_bill_total"]),
            kind="money", label=f"{label} bill savings",
        )
        co2_reduction = float(row["annual_co2_reduction_kg"])
        _assert_numeric_identity(
            co2_reduction,
            float(row["baseline_co2_total_kg"]) - float(row["post_measure_co2_total_kg"]),
            kind="co2", label=f"{label} CO2 reduction",
        )
        if co2_reduction > 0:
            expected_abatement = float(row["capital_cost_total"]) / (
                co2_reduction / 1000 * analysis_horizon_years
            )
            _assert_numeric_identity(
                float(row["cost_per_tco2_20yr_gbp"]), expected_abatement,
                kind="money", label=f"{label} carbon abatement cost",
            )


def _assert_numeric_identity(actual: float, expected: float, *, kind: str, label: str) -> None:
    magnitude = max(abs(actual), abs(expected))
    floor = 0.01
    tolerance = max(floor, 1e-9 * magnitude)
    if abs(actual - expected) > tolerance:
        unit = "kg" if kind == "co2" else "GBP"
        raise RuntimeError(
            f"{label} identity failed: actual={actual}, expected={expected}, "
            f"tolerance={tolerance} {unit}"
        )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
