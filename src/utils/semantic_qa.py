"""Run-scoped semantic QA and publication gating."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from src.modeling.contracts import (
    DIAGNOSTIC_FULL_FABRIC_PATHWAY,
    PROPERTY_ID_COLUMN,
    STOCK_SCENARIO,
    require_property_identifier,
    validate_hn_readiness,
    validate_hybrid_assignments,
)
from src.utils.run_integrity import ArtifactManifest, RunContext


def _check(checks: list[dict[str, Any]], name: str, fn: Callable[[], Any], *, critical: bool = True) -> None:
    try:
        detail = fn()
        checks.append({"name": name, "status": "pass", "critical": critical, "detail": detail})
    except Exception as exc:
        checks.append({"name": name, "status": "fail", "critical": critical, "detail": str(exc)})


def run_semantic_qa(context: RunContext, manifest: ArtifactManifest, output_path: Path | None = None) -> dict[str, Any]:
    """Execute cross-artifact checks and write a machine-readable QA result."""
    checks: list[dict[str, Any]] = []
    root = Path(context.run_root)

    _check(checks, "utc_timing_chronology", lambda: context.validate_timing() or "within 2 second tolerance")
    _check(checks, "manifest_current_run", lambda: _validate_manifest_identity(context, manifest))
    _check(checks, "required_artifact_provenance", lambda: _validate_registered_artifacts(manifest))

    enriched_path = root / "processed" / "epc_london_adjusted_spatial.parquet"
    scenario_properties_path = root / "outputs" / "scenario_results_by_property.parquet"
    scenario_summary_path = root / "outputs" / "scenario_results_summary.csv"
    diagnostic_path = root / "outputs" / "pathway_results_by_property.parquet"
    public_comparison_path = root / "outputs" / "stock_scenario_comparison.csv"
    readiness_path = root / "outputs" / "retrofit_readiness_analysis.csv"
    window_path = root / "outputs" / "window_economics.csv"

    enriched = pd.read_parquet(enriched_path)
    scenario_properties = pd.read_parquet(scenario_properties_path)
    scenarios = pd.read_csv(scenario_summary_path)
    diagnostic = pd.read_parquet(diagnostic_path)
    public_comparison = pd.read_csv(public_comparison_path)
    readiness = pd.read_csv(readiness_path, low_memory=False)
    windows = pd.read_csv(window_path)

    _check(checks, "authoritative_unique_key", lambda: require_property_identifier(enriched).size)
    _check(checks, "spatial_tier_consistency", lambda: _validate_spatial_tiers(enriched))
    _check(checks, "authoritative_cohort", lambda: _require_equal(len(enriched), context.authoritative_cohort))
    _check(checks, "scenario_property_cohorts", lambda: _validate_scenario_cohorts(scenario_properties, context.authoritative_cohort))
    _check(checks, "diagnostic_property_cohorts", lambda: _validate_scenario_cohorts(diagnostic, context.authoritative_cohort, key="pathway_id"))
    _check(checks, "hybrid_assignment_exclusivity", lambda: _validate_hybrid(scenario_properties))
    _check(checks, "model_family_scope", lambda: _validate_model_scopes(scenarios, diagnostic, public_comparison))
    _check(checks, "payback_contract", lambda: _validate_payback_columns(scenarios))
    _check(checks, "percentage_ranges", lambda: _validate_percentages(scenarios, readiness))
    _check(checks, "explicit_readiness_costs", lambda: _validate_readiness_costs(readiness))
    _check(checks, "window_source_traceability", lambda: _validate_windows(windows))
    _check(checks, "removed_step_subsidy_artifact", lambda: _require_absent(root / "outputs" / "subsidy_sensitivity_analysis_simple_gbp.csv"))
    _check(checks, "diagnostic_excluded_from_public_comparison", lambda: _validate_public_comparison(public_comparison))

    critical_failures = [item for item in checks if item["critical"] and item["status"] != "pass"]
    payload = {
        "schema_version": "1.0",
        "run_id": context.run_id,
        "dataset_fingerprint": context.dataset_fingerprint,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if not critical_failures else "fail",
        "critical_failure_count": len(critical_failures),
        "checks": checks,
    }
    path = Path(output_path or (root / "outputs" / "qa_checks.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")
    return payload


def require_passing_qa(path: Path, *, run_id: str, dataset_fingerprint: str | None = None) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise RuntimeError("Current-run semantic QA result is missing; refusing publication")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("run_id") != run_id:
        raise RuntimeError("Semantic QA result belongs to a different run")
    if dataset_fingerprint is not None and payload.get("dataset_fingerprint") != dataset_fingerprint:
        raise RuntimeError("Semantic QA result has a different dataset fingerprint")
    if payload.get("status") != "pass" or payload.get("critical_failure_count") != 0:
        raise RuntimeError("Semantic QA has critical failures; refusing publication")
    return payload


def _validate_manifest_identity(context: RunContext, manifest: ArtifactManifest) -> str:
    if manifest.context.run_id != context.run_id:
        raise ValueError("manifest run mismatch")
    return context.run_id


def _validate_registered_artifacts(manifest: ArtifactManifest) -> int:
    for name, record in manifest.artifacts.items():
        if record.required:
            manifest.resolve(name)
    return len(manifest.artifacts)


def _require_equal(actual: Any, expected: Any) -> Any:
    if actual != expected:
        raise ValueError(f"actual={actual}, expected={expected}")
    return actual


def _validate_spatial_tiers(frame: pd.DataFrame) -> int:
    validate_hn_readiness(frame)
    return int(frame["hn_ready"].sum())


def _validate_scenario_cohorts(frame: pd.DataFrame, cohort: int | None, *, key: str = "scenario") -> dict[str, int]:
    counts = frame.groupby(key).size().to_dict()
    bad = {name: count for name, count in counts.items() if cohort is not None and count != cohort}
    if bad:
        raise ValueError(f"cohort mismatches: {bad}")
    return {str(k): int(v) for k, v in counts.items()}


def _validate_hybrid(frame: pd.DataFrame) -> dict[str, int]:
    hybrid = frame[frame["scenario"].eq("hybrid")].copy()
    hybrid["assigned_heat_network"] = hybrid["hybrid_pathway"].eq("heat_network")
    hybrid["assigned_ashp"] = hybrid["hybrid_pathway"].eq("ashp")
    validate_hybrid_assignments(hybrid)
    return {"heat_network": int(hybrid.assigned_heat_network.sum()), "ashp": int(hybrid.assigned_ashp.sum())}


def _validate_model_scopes(scenarios: pd.DataFrame, diagnostic: pd.DataFrame, comparison: pd.DataFrame) -> str:
    if set(scenarios["model_family"]) != {STOCK_SCENARIO.model_family}:
        raise ValueError("public scenario model family mismatch")
    if set(comparison["model_family"]) != {STOCK_SCENARIO.model_family}:
        raise ValueError("public comparison contains non-stock model family")
    if set(diagnostic["model_family"]) != {DIAGNOSTIC_FULL_FABRIC_PATHWAY.model_family}:
        raise ValueError("diagnostic model family mismatch")
    if diagnostic["headline_reporting_eligible"].astype(bool).any():
        raise ValueError("diagnostic rows are headline eligible")
    return "public and internal scopes separated"


def _validate_payback_columns(scenarios: pd.DataFrame) -> int:
    required = {
        "aggregate_simple_payback_years", "property_simple_payback_mean_years",
        "property_simple_payback_median_years", "payback_valid_denominator_count",
        "payback_non_positive_savings_count", "payback_infinite_count",
        "truncation_threshold_years", "excluded_by_truncation_count",
    }
    missing = required.difference(scenarios.columns)
    if missing:
        raise ValueError(f"missing payback fields: {sorted(missing)}")
    if scenarios["truncation_threshold_years"].notna().any() or scenarios["excluded_by_truncation_count"].fillna(0).ne(0).any():
        raise ValueError("property paybacks were truncated")
    return len(scenarios)


def _validate_percentages(*frames: pd.DataFrame) -> int:
    count = 0
    for frame in frames:
        for column in (c for c in frame.columns if c.endswith("_pct") or c.endswith("_percentage")):
            values = pd.to_numeric(frame[column], errors="coerce").dropna()
            if ((values < 0) | (values > 100)).any():
                raise ValueError(f"percentage out of range: {column}")
            count += 1
    return count


def _validate_readiness_costs(readiness: pd.DataFrame) -> int:
    required = {"system_cost_full_ashp", "total_cost_full_ashp", "system_cost_hybrid_ashp_sensitivity", "total_cost_hybrid_ashp_sensitivity"}
    missing = required.difference(readiness.columns)
    if missing:
        raise ValueError(f"missing explicit readiness costs: {sorted(missing)}")
    forbidden = {"system_cost", "total_cost", "total_retrofit_cost"}.intersection(readiness.columns)
    if forbidden:
        raise ValueError(f"ambiguous readiness costs remain: {sorted(forbidden)}")
    return len(readiness)


def _validate_windows(windows: pd.DataFrame) -> int:
    required = {"capital_cost_gbp", "energy_saving_fraction", "energy_price_gbp_per_kwh", "simple_payback_years", "assumption_source"}
    if required.difference(windows.columns) or windows["assumption_source"].fillna("").str.strip().eq("").any():
        raise ValueError("window economics are not fully traceable")
    return len(windows)


def _require_absent(path: Path) -> str:
    if path.exists():
        raise ValueError(f"removed artifact exists: {path.name}")
    return "absent"


def _validate_public_comparison(frame: pd.DataFrame) -> int:
    if "pathway_id" in frame.columns or frame["model_family"].ne(STOCK_SCENARIO.model_family).any():
        raise ValueError("diagnostic pathways leaked into public comparison")
    return len(frame)


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    return str(value)
