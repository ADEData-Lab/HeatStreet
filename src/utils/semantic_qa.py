"""Run-scoped semantic QA and publication gating."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

from src.modeling.contracts import (
    DIAGNOSTIC_FULL_FABRIC_PATHWAY,
    STOCK_SCENARIO,
    payback_summary,
    require_property_identifier,
    validate_hn_readiness,
    validate_hybrid_assignments,
)
from src.utils.run_integrity import ArtifactManifest, RunContext


PERCENTAGE_RECONCILIATION_TOLERANCE_PP = 0.1
COST_RECONCILIATION_ABS_TOLERANCE_GBP = 1.0
COST_RECONCILIATION_REL_TOLERANCE = 1e-9
PAYBACK_RECONCILIATION_ABS_TOLERANCE = 1e-10
PAYBACK_RECONCILIATION_REL_TOLERANCE = 1e-10

_PAYBACK_COUNT_FIELDS = (
    "payback_valid_denominator_count",
    "payback_non_positive_savings_count",
    "payback_missing_input_count",
    "payback_non_finite_input_count",
    "payback_infinite_count",
)
_HYBRID_COMPARISON_FIELDS = (
    "capital_cost_total",
    "post_measure_bill_total",
    "annual_bill_savings",
    "post_measure_co2_total_kg",
    "annual_co2_reduction_kg",
    "aggregate_simple_payback_years",
    "property_simple_payback_median_years",
)


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
    outputs = root / "outputs"

    _check(checks, "utc_timing_chronology", lambda: context.validate_timing() or "within 2 second tolerance")
    _check(checks, "manifest_current_run", lambda: _validate_manifest_identity(context, manifest))
    _check(checks, "required_artifact_provenance", lambda: _validate_registered_artifacts(manifest))

    enriched = pd.read_parquet(root / "processed" / "epc_london_adjusted_spatial.parquet")
    scenario_properties = pd.read_parquet(outputs / "scenario_results_by_property.parquet")
    scenarios = pd.read_csv(outputs / "scenario_results_summary.csv")
    diagnostic = pd.read_parquet(outputs / "pathway_results_by_property.parquet")
    diagnostic_summary = pd.read_csv(outputs / "pathway_results_summary.csv")
    diagnostic_comparison = pd.read_csv(outputs / "comparisons" / "hn_vs_hp_comparison.csv")
    public_comparison = pd.read_csv(outputs / "stock_scenario_comparison.csv")
    readiness = pd.read_csv(outputs / "retrofit_readiness_analysis.csv", low_memory=False)
    spatial = pd.read_csv(outputs / "pathway_suitability_by_tier.csv")
    subsidy = pd.read_csv(outputs / "subsidy_sensitivity_analysis.csv")
    windows = pd.read_csv(outputs / "window_economics.csv")
    tenure = pd.read_csv(outputs / "reports" / "tenure_segmentation.csv")
    archetype = json.loads((outputs / "archetype_analysis_results.json").read_text(encoding="utf-8"))
    one_stop = json.loads((outputs / "one_stop_output.json").read_text(encoding="utf-8"))
    run_metadata = json.loads((outputs / "run_metadata.json").read_text(encoding="utf-8"))
    dashboard = json.loads((outputs / "dashboard" / "dashboard-data.json").read_text(encoding="utf-8"))
    cohort = int(context.authoritative_cohort or len(enriched))

    _check(checks, "authoritative_unique_key", lambda: require_property_identifier(enriched).size)
    _check(checks, "spatial_tier_consistency", lambda: _validate_spatial_tiers(enriched))
    _check(checks, "authoritative_cohort", lambda: _require_equal(len(enriched), cohort))
    _check(checks, "scenario_property_cohorts", lambda: _validate_scenario_cohorts(scenario_properties, cohort))
    _check(checks, "diagnostic_property_cohorts", lambda: _validate_scenario_cohorts(diagnostic, cohort, key="pathway_id"))
    _check(checks, "epc_band_distribution_reconciliation", lambda: _validate_epc_distribution(archetype, cohort))
    _check(checks, "readiness_tier_distribution_reconciliation", lambda: _validate_readiness_distribution(readiness, cohort))
    _check(checks, "spatial_tier_distribution_reconciliation", lambda: _validate_spatial_distribution(spatial, cohort))
    _check(checks, "percentage_distribution_reconciliation", lambda: _validate_percentage_distributions(scenarios, archetype, readiness, spatial))
    _check(checks, "hybrid_assignment_exclusivity", lambda: _validate_hybrid(scenario_properties, cohort))
    _check(
        checks,
        "full_deployment_technology_contract",
        lambda: _validate_full_deployment_technology_contract(
            scenario_properties,
            scenarios,
            cohort,
        ),
    )
    _check(
        checks,
        "scenario_readiness_reconciliation",
        lambda: _validate_scenario_readiness_reconciliation(
            scenario_properties,
            scenarios,
        ),
    )
    _check(
        checks,
        "tenure_category_reconciliation",
        lambda: _validate_tenure_category_reconciliation(
            tenure,
            cohort,
        ),
    )
    _check(checks, "hybrid_pathway_distinction", lambda: _validate_hybrid_distinction(scenarios, scenario_properties, enriched))
    _check(checks, "model_family_scope", lambda: _validate_model_scopes(
        scenarios, scenario_properties, diagnostic, diagnostic_summary, diagnostic_comparison, public_comparison
    ))
    _check(checks, "scenario_cost_reconciliation", lambda: _validate_scenario_costs(scenarios))
    _check(checks, "readiness_cost_reconciliation", lambda: _validate_readiness_costs(readiness))
    _check(checks, "payback_contract", lambda: _validate_payback_columns(scenarios, subsidy, public_comparison))
    _check(checks, "aggregate_payback_arithmetic", lambda: _validate_payback_arithmetic(scenarios, scenario_properties))
    _check(checks, "zero_subsidy_payback_reconciliation", lambda: _validate_zero_subsidy_payback(scenarios, subsidy))
    _check(checks, "payback_exclusion_reconciliation", lambda: _validate_payback_exclusions(scenarios))
    _check(checks, "one_stop_json_integrity", lambda: _validate_one_stop_json(one_stop, context, root))
    _check(
        checks,
        "energy_price_profile_consistency",
        lambda: _validate_energy_price_metadata(context, run_metadata, one_stop, dashboard),
    )
    _check(checks, "window_source_traceability", lambda: _validate_windows(windows))
    _check(checks, "removed_step_subsidy_artifact", lambda: _require_absent(outputs / "subsidy_sensitivity_analysis_simple_gbp.csv"))
    _check(checks, "diagnostic_excluded_from_public_comparison", lambda: _validate_public_comparison(public_comparison))

    critical_failures = [item for item in checks if item["critical"] and item["status"] != "pass"]
    payload = {
        "schema_version": "1.2",
        "run_id": context.run_id,
        "dataset_fingerprint": context.dataset_fingerprint,
        "authoritative_cohort": cohort,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if not critical_failures else "fail",
        "critical_failure_count": len(critical_failures),
        "tolerances": {
            "percentage_reconciliation_pp": PERCENTAGE_RECONCILIATION_TOLERANCE_PP,
            "cost_absolute_gbp": COST_RECONCILIATION_ABS_TOLERANCE_GBP,
            "cost_relative": COST_RECONCILIATION_REL_TOLERANCE,
            "payback_absolute": PAYBACK_RECONCILIATION_ABS_TOLERANCE,
            "payback_relative": PAYBACK_RECONCILIATION_REL_TOLERANCE,
        },
        "checks": checks,
    }
    path = Path(output_path or (outputs / "qa_checks.json"))
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
        # The QA result cannot validate its own pre-existing manifest record;
        # publication validates the freshly written result immediately after this pass.
        if record.required and name != "qa_checks":
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


def _validate_epc_distribution(archetype: dict[str, Any], cohort: int) -> dict[str, float]:
    epc = archetype.get("epc_bands", {})
    counts = epc.get("frequency", {})
    percentages = epc.get("percentage", {})
    _require_equal(int(sum(counts.values())), cohort)
    _require_percentage_sum(percentages.values(), "EPC band")
    return {"count": int(sum(counts.values())), "percentage": float(sum(percentages.values()))}


def _validate_readiness_distribution(frame: pd.DataFrame, cohort: int) -> dict[str, float]:
    if "hp_readiness_tier" not in frame:
        raise ValueError("readiness tier column missing")
    tiers = pd.to_numeric(frame["hp_readiness_tier"], errors="coerce")
    if tiers.isna().any() or not tiers.isin(range(1, 6)).all():
        raise ValueError("readiness tiers contain missing or invalid values")
    counts = tiers.value_counts().reindex(range(1, 6), fill_value=0)
    _require_equal(int(counts.sum()), cohort)
    percentages = counts / cohort * 100 if cohort else counts.astype(float)
    _require_percentage_sum(percentages, "readiness tier")
    return {"count": int(counts.sum()), "percentage": float(percentages.sum())}


def _validate_spatial_distribution(frame: pd.DataFrame, cohort: int) -> dict[str, float]:
    required = {"Property Count", "Percentage"}
    if required.difference(frame.columns):
        raise ValueError("spatial tier distribution columns missing")
    count = int(pd.to_numeric(frame["Property Count"], errors="raise").sum())
    _require_equal(count, cohort)
    percentage = pd.to_numeric(frame["Percentage"], errors="raise")
    _require_percentage_sum(percentage, "spatial tier")
    return {"count": count, "percentage": float(percentage.sum())}


def _require_percentage_sum(values: Iterable[Any], label: str) -> float:
    total = float(pd.to_numeric(pd.Series(list(values)), errors="raise").sum())
    if not np.isclose(total, 100.0, atol=PERCENTAGE_RECONCILIATION_TOLERANCE_PP, rtol=0):
        raise ValueError(
            f"{label} percentages sum to {total:.6f}, expected 100 within "
            f"{PERCENTAGE_RECONCILIATION_TOLERANCE_PP} percentage points"
        )
    return total


def _validate_percentage_distributions(
    scenarios: pd.DataFrame, archetype: dict[str, Any], readiness: pd.DataFrame, spatial: pd.DataFrame
) -> int:
    checked = 0
    for frame in (scenarios, readiness, spatial):
        for column in (c for c in frame.columns if c.endswith("_pct") or c.endswith("_percentage") or c == "Percentage"):
            values = pd.to_numeric(frame[column], errors="coerce").dropna()
            if ((values < 0) | (values > 100)).any():
                raise ValueError(f"percentage out of range: {column}")
            checked += 1
    _require_percentage_sum(archetype.get("epc_bands", {}).get("percentage", {}).values(), "EPC band")
    _require_percentage_sum(spatial["Percentage"], "spatial tier")
    counts = readiness["hp_readiness_tier"].value_counts()
    _require_percentage_sum(counts / counts.sum() * 100, "readiness tier")
    ce_fields = ["cost_effective_pct", "marginal_pct", "not_cost_effective_pct"]
    if set(ce_fields).issubset(scenarios.columns):
        for _, row in scenarios.iterrows():
            _require_percentage_sum((row[field] for field in ce_fields), f"{row.get('scenario_id')} cost-effectiveness")
            checked += 1
    return checked

def _measure_mask(frame: pd.DataFrame, measure: str) -> pd.Series:
    """Return a Boolean mask for rows containing a modelled measure."""
    if "measures_applied" not in frame.columns:
        raise ValueError("scenario property output lacks measures_applied")

    def contains_measure(value: Any) -> bool:
        if value is None:
            return False

        if isinstance(value, str):
            values = {
                item.strip()
                for item in value.split("|")
                if item.strip()
            }
            return measure in values

        if isinstance(value, (list, tuple, set, np.ndarray, pd.Series)):
            return measure in list(value)

        try:
            if pd.isna(value):
                return False
        except (TypeError, ValueError):
            return False

        return value == measure

    return frame["measures_applied"].map(contains_measure).astype(bool)


def _scenario_summary_index(scenarios: pd.DataFrame) -> pd.DataFrame:
    """Return scenario summary rows indexed by their stable identifier."""
    key = "scenario_id" if "scenario_id" in scenarios.columns else "scenario"

    if key not in scenarios.columns:
        raise ValueError("scenario summary lacks scenario identifier")

    if scenarios[key].duplicated().any():
        duplicates = scenarios.loc[scenarios[key].duplicated(), key].tolist()
        raise ValueError(f"duplicate scenario summary rows: {duplicates}")

    return scenarios.set_index(key)


def _validate_full_deployment_technology_contract(
    properties: pd.DataFrame,
    scenarios: pd.DataFrame,
    cohort: int,
) -> dict[str, dict[str, int]]:
    """Verify that full-deployment scenarios actually deploy their technology."""
    required_property_columns = {
        "scenario",
        "measures_applied",
        "heat_pump_removed",
        "hybrid_pathway",
    }
    missing = required_property_columns.difference(properties.columns)
    if missing:
        raise ValueError(
            f"missing technology-contract property fields: {sorted(missing)}"
        )

    summary = _scenario_summary_index(scenarios)
    required_summary_columns = {
        "ashp_installed_properties",
        "ashp_removed_properties",
        "hn_assigned_properties",
        "ashp_assigned_properties",
    }
    missing = required_summary_columns.difference(summary.columns)
    if missing:
        raise ValueError(
            f"missing technology-contract summary fields: {sorted(missing)}"
        )

    result: dict[str, dict[str, int]] = {}

    for scenario_id in ("heat_pump", "minimum_fabric_hp_ready"):
        if scenario_id not in summary.index:
            raise ValueError(f"missing scenario summary: {scenario_id}")

        subset = properties[properties["scenario"].eq(scenario_id)].copy()
        if len(subset) != cohort:
            raise ValueError(
                f"{scenario_id} contains {len(subset)} properties, expected {cohort}"
            )

        ashp_mask = _measure_mask(subset, "ashp_installation")
        emitter_mask = _measure_mask(subset, "emitter_upgrades")
        removed = subset["heat_pump_removed"].fillna(False).astype(bool)

        if int(ashp_mask.sum()) != cohort:
            raise ValueError(
                f"{scenario_id} installs ASHPs at "
                f"{int(ashp_mask.sum())} of {cohort} properties"
            )

        if int(emitter_mask.sum()) != cohort:
            raise ValueError(
                f"{scenario_id} applies emitter upgrades at "
                f"{int(emitter_mask.sum())} of {cohort} properties"
            )

        if removed.any():
            raise ValueError(
                f"{scenario_id} removes {int(removed.sum())} heat pumps"
            )

        row = summary.loc[scenario_id]
        if int(row["ashp_installed_properties"]) != cohort:
            raise ValueError(
                f"{scenario_id} summary reports "
                f"{row['ashp_installed_properties']} installations, "
                f"expected {cohort}"
            )

        if int(row["ashp_removed_properties"]) != 0:
            raise ValueError(
                f"{scenario_id} summary reports heat-pump removals"
            )

        result[scenario_id] = {
            "properties": int(len(subset)),
            "ashp_installations": int(ashp_mask.sum()),
            "emitter_upgrades": int(emitter_mask.sum()),
            "heat_pumps_removed": int(removed.sum()),
        }

    if "hybrid" not in summary.index:
        raise ValueError("missing hybrid scenario summary")

    hybrid = properties[properties["scenario"].eq("hybrid")].copy()
    if len(hybrid) != cohort:
        raise ValueError(
            f"hybrid contains {len(hybrid)} properties, expected {cohort}"
        )

    assigned_ashp = hybrid["hybrid_pathway"].eq("ashp")
    assigned_hn = hybrid["hybrid_pathway"].eq("heat_network")
    ashp_mask = _measure_mask(hybrid, "ashp_installation")
    emitter_mask = _measure_mask(hybrid, "emitter_upgrades")
    hn_mask = _measure_mask(hybrid, "district_heating_connection")
    removed = hybrid["heat_pump_removed"].fillna(False).astype(bool)

    if not (assigned_ashp | assigned_hn).all():
        raise ValueError("hybrid contains unassigned properties")

    if (assigned_ashp & assigned_hn).any():
        raise ValueError("hybrid contains dual technology assignments")

    if not ashp_mask.equals(assigned_ashp):
        mismatches = int((ashp_mask != assigned_ashp).sum())
        raise ValueError(
            f"hybrid ASHP measures disagree with assignments for "
            f"{mismatches} properties"
        )

    if not emitter_mask.equals(assigned_ashp):
        mismatches = int((emitter_mask != assigned_ashp).sum())
        raise ValueError(
            f"hybrid emitter upgrades disagree with ASHP assignments for "
            f"{mismatches} properties"
        )

    if not hn_mask.equals(assigned_hn):
        mismatches = int((hn_mask != assigned_hn).sum())
        raise ValueError(
            f"hybrid heat-network measures disagree with assignments for "
            f"{mismatches} properties"
        )

    if removed.any():
        raise ValueError(
            f"hybrid removes {int(removed.sum())} heat pumps"
        )

    hybrid_row = summary.loc["hybrid"]
    expected_ashp = int(assigned_ashp.sum())
    expected_hn = int(assigned_hn.sum())

    if int(hybrid_row["ashp_installed_properties"]) != expected_ashp:
        raise ValueError("hybrid ASHP installation summary does not reconcile")

    if int(hybrid_row["ashp_assigned_properties"]) != expected_ashp:
        raise ValueError("hybrid ASHP assignment summary does not reconcile")

    if int(hybrid_row["hn_assigned_properties"]) != expected_hn:
        raise ValueError(
            "hybrid heat-network assignment summary does not reconcile"
        )

    if int(hybrid_row["ashp_removed_properties"]) != 0:
        raise ValueError("hybrid summary reports heat-pump removals")

    result["hybrid"] = {
        "properties": int(len(hybrid)),
        "ashp_assignments": expected_ashp,
        "heat_network_assignments": expected_hn,
        "heat_pumps_removed": int(removed.sum()),
    }

    return result


def _validate_scenario_readiness_reconciliation(
    properties: pd.DataFrame,
    scenarios: pd.DataFrame,
) -> dict[str, dict[str, float]]:
    """Recalculate ASHP readiness metrics from property-level results."""
    required_property_columns = {
        "scenario",
        "measures_applied",
        "ashp_ready",
        "ashp_ready_after_applied_measures",
        "fabric_inserted_for_hp",
        "heat_pump_removed",
        "baseline_energy_kwh",
        "heat_pump_electricity_kwh",
    }
    missing = required_property_columns.difference(properties.columns)
    if missing:
        raise ValueError(
            f"missing ASHP readiness property fields: {sorted(missing)}"
        )

    required_summary_columns = {
        "ashp_installed_properties",
        "ashp_ready_before_installation_properties",
        "ashp_ready_after_applied_measures_properties",
        "ashp_residual_readiness_gap_properties",
        "ashp_ready_after_applied_measures_pct",
        "ashp_fabric_applied_properties",
        "ashp_zero_baseline_energy_properties",
        "ashp_positive_demand_properties",
        "ashp_positive_electricity_properties",
        "ashp_removed_properties",
    }
    missing = required_summary_columns.difference(scenarios.columns)
    if missing:
        raise ValueError(
            f"missing ASHP readiness summary fields: {sorted(missing)}"
        )

    summary = _scenario_summary_index(scenarios)
    result: dict[str, dict[str, float]] = {}

    for scenario_id, row in summary.iterrows():
        reported_installed = int(
            pd.to_numeric(
                pd.Series([row["ashp_installed_properties"]]),
                errors="raise",
            ).iloc[0]
        )

        subset = properties[properties["scenario"].eq(scenario_id)].copy()
        installed_mask = _measure_mask(subset, "ashp_installation")
        installed = subset.loc[installed_mask].copy()

        actual_installed = int(len(installed))
        if reported_installed != actual_installed:
            raise ValueError(
                f"{scenario_id} reports {reported_installed} ASHP installations "
                f"but property results contain {actual_installed}"
            )

        if actual_installed == 0:
            continue

        ready_before = int(
            installed["ashp_ready"].fillna(False).astype(bool).sum()
        )
        ready_after = int(
            installed["ashp_ready_after_applied_measures"]
            .fillna(False)
            .astype(bool)
            .sum()
        )
        residual_gap = actual_installed - ready_after
        fabric_applied = int(
            installed["fabric_inserted_for_hp"]
            .fillna(False)
            .astype(bool)
            .sum()
        )

        baseline = pd.to_numeric(
            installed["baseline_energy_kwh"],
            errors="coerce",
        )
        electricity = pd.to_numeric(
            installed["heat_pump_electricity_kwh"],
            errors="coerce",
        )

        zero_baseline = int(baseline.fillna(0).le(0).sum())
        positive_demand = int(baseline.gt(0).sum())
        positive_electricity = int(electricity.gt(0).sum())
        removed = int(
            installed["heat_pump_removed"]
            .fillna(False)
            .astype(bool)
            .sum()
        )
        ready_pct = ready_after / actual_installed * 100

        expected = {
            "ashp_installed_properties": actual_installed,
            "ashp_ready_before_installation_properties": ready_before,
            "ashp_ready_after_applied_measures_properties": ready_after,
            "ashp_residual_readiness_gap_properties": residual_gap,
            "ashp_fabric_applied_properties": fabric_applied,
            "ashp_zero_baseline_energy_properties": zero_baseline,
            "ashp_positive_demand_properties": positive_demand,
            "ashp_positive_electricity_properties": positive_electricity,
            "ashp_removed_properties": removed,
        }

        for field, recalculated in expected.items():
            reported = int(
                pd.to_numeric(
                    pd.Series([row[field]]),
                    errors="raise",
                ).iloc[0]
            )
            if reported != recalculated:
                raise ValueError(
                    f"{scenario_id} {field}={reported}, "
                    f"recalculated={recalculated}"
                )

        reported_pct = float(row["ashp_ready_after_applied_measures_pct"])
        if not np.isclose(
            reported_pct,
            ready_pct,
            atol=1e-9,
            rtol=1e-9,
        ):
            raise ValueError(
                f"{scenario_id} readiness percentage={reported_pct}, "
                f"recalculated={ready_pct}"
            )

        if ready_after + residual_gap != actual_installed:
            raise ValueError(
                f"{scenario_id} readiness categories do not reconcile"
            )

        if zero_baseline + positive_demand != actual_installed:
            raise ValueError(
                f"{scenario_id} baseline-demand categories do not reconcile"
            )

        if positive_electricity > positive_demand:
            raise ValueError(
                f"{scenario_id} has more positive-electricity properties "
                f"than positive-demand properties"
            )

        result[str(scenario_id)] = {
            "ashp_installed": actual_installed,
            "ready_before": ready_before,
            "ready_after": ready_after,
            "residual_gap": residual_gap,
            "ready_after_pct": ready_pct,
            "zero_baseline": zero_baseline,
            "positive_demand": positive_demand,
            "positive_electricity": positive_electricity,
            "removed": removed,
        }

    if not result:
        raise ValueError("no ASHP deployment scenarios were checked")

    return result


def _validate_tenure_category_reconciliation(
    tenure: pd.DataFrame,
    cohort: int,
) -> dict[str, Any]:
    """Verify tenure categories, counts and percentages."""
    required = {
        "tenure_group",
        "property_count",
        "share_pct",
    }
    missing = required.difference(tenure.columns)
    if missing:
        raise ValueError(
            f"missing tenure reconciliation fields: {sorted(missing)}"
        )

    if tenure["tenure_group"].isna().any():
        raise ValueError("tenure report contains missing category names")

    if tenure["tenure_group"].duplicated().any():
        duplicates = tenure.loc[
            tenure["tenure_group"].duplicated(),
            "tenure_group",
        ].tolist()
        raise ValueError(f"duplicate tenure categories: {duplicates}")

    allowed = {
        "owner_occupied",
        "private_rented_sector",
        "social_affordable",
        "unknown",
    }
    categories = set(tenure["tenure_group"].astype(str))
    unexpected = categories.difference(allowed)
    if unexpected:
        raise ValueError(
            f"unexpected tenure categories: {sorted(unexpected)}"
        )

    counts = pd.to_numeric(
        tenure["property_count"],
        errors="raise",
    )
    shares = pd.to_numeric(
        tenure["share_pct"],
        errors="raise",
    )

    if (counts < 0).any():
        raise ValueError("tenure report contains negative property counts")

    total_count = int(counts.sum())
    if total_count != cohort:
        raise ValueError(
            f"tenure categories total {total_count}, expected {cohort}"
        )

    total_share = float(shares.sum())
    if not np.isclose(
        total_share,
        100.0,
        atol=PERCENTAGE_RECONCILIATION_TOLERANCE_PP,
        rtol=0,
    ):
        raise ValueError(
            f"tenure shares sum to {total_share}, expected 100"
        )

    calculated_shares = counts / cohort * 100 if cohort else counts.astype(float)
    differences = (shares - calculated_shares).abs()

    if (
        differences
        > PERCENTAGE_RECONCILIATION_TOLERANCE_PP
    ).any():
        bad = tenure.loc[
            differences
            > PERCENTAGE_RECONCILIATION_TOLERANCE_PP,
            ["tenure_group", "property_count", "share_pct"],
        ]
        raise ValueError(
            "tenure shares do not reconcile with counts: "
            f"{bad.to_dict(orient='records')}"
        )

    return {
        "categories": sorted(categories),
        "property_count": total_count,
        "share_pct": total_share,
    }
def _validate_hybrid(frame: pd.DataFrame, cohort: int | None = None) -> dict[str, int]:
    hybrid = frame[frame["scenario"].eq("hybrid")].copy()
    hybrid["assigned_heat_network"] = hybrid["hybrid_pathway"].eq("heat_network")
    hybrid["assigned_ashp"] = hybrid["hybrid_pathway"].eq("ashp")
    validate_hybrid_assignments(hybrid)
    counts = {"heat_network": int(hybrid.assigned_heat_network.sum()), "ashp": int(hybrid.assigned_ashp.sum())}
    if cohort is not None and sum(counts.values()) != cohort:
        raise ValueError(f"hybrid assignments total {sum(counts.values())}, expected {cohort}")
    return counts


def _validate_hybrid_distinction(scenarios: pd.DataFrame, properties: pd.DataFrame, enriched: pd.DataFrame) -> str:
    readiness = enriched["hn_ready"].astype(bool)
    if not readiness.any() or readiness.all():
        return "single-technology cohort; equality invariant not applicable"
    hybrid = properties[properties["scenario"].eq("hybrid")]
    assignments = set(hybrid["hybrid_pathway"].dropna())
    if assignments != {"heat_network", "ashp"}:
        raise ValueError(f"mixed HN-ready cohort hybrid assignments are {sorted(assignments)}")
    indexed = scenarios.set_index("scenario_id" if "scenario_id" in scenarios else "scenario")
    for pure in ("heat_pump", "heat_network"):
        equal_fields = []
        for field in _HYBRID_COMPARISON_FIELDS:
            hybrid_value = indexed.at["hybrid", field]
            pure_value = indexed.at[pure, field]
            equal_fields.append(_values_close(hybrid_value, pure_value))
        pure_path = "ashp" if pure == "heat_pump" else "heat_network"
        assignment_equal = hybrid["hybrid_pathway"].eq(pure_path).all()
        if assignment_equal or all(equal_fields):
            raise ValueError(f"hybrid is identical to pure {pure.replace('_', ' ')} for a mixed HN-ready cohort")
    return "hybrid differs from both pure pathways"


def _validate_model_scopes(
    scenarios: pd.DataFrame,
    scenario_properties: pd.DataFrame,
    diagnostic: pd.DataFrame,
    diagnostic_summary: pd.DataFrame,
    diagnostic_comparison: pd.DataFrame,
    public_comparison: pd.DataFrame,
) -> str:
    for label, frame in (
        ("public scenario", scenarios),
        ("public scenario property", scenario_properties),
        ("public comparison", public_comparison),
    ):
        if "model_family" not in frame or set(frame["model_family"].dropna()) != {STOCK_SCENARIO.model_family}:
            raise ValueError(f"{label} model family mismatch")
    for label, frame in (
        ("diagnostic property", diagnostic),
        ("diagnostic summary", diagnostic_summary),
        ("diagnostic comparison", diagnostic_comparison),
    ):
        if "model_family" not in frame or set(frame["model_family"].dropna()) != {DIAGNOSTIC_FULL_FABRIC_PATHWAY.model_family}:
            raise ValueError(f"{label} model family mismatch")
        if "publication_scope" not in frame or set(frame["publication_scope"].dropna()) != {"internal"}:
            raise ValueError(f"{label} publication scope is not internal")
        if "headline_reporting_eligible" not in frame or _as_bool(frame["headline_reporting_eligible"]).any():
            raise ValueError(f"{label} rows are headline eligible")
    return "public and internal model scopes separated"


def _validate_scenario_costs(scenarios: pd.DataFrame) -> int:
    required = {"capital_cost_total", "capital_cost_per_property", "total_properties"}
    if required.difference(scenarios.columns):
        raise ValueError(f"missing scenario cost fields: {sorted(required.difference(scenarios.columns))}")
    for _, row in scenarios.iterrows():
        values = [float(row[field]) for field in required]
        if not np.isfinite(values).all() or any(value < 0 for value in values):
            raise ValueError(f"non-finite or negative scenario costs for {row.get('scenario_id')}")
        expected = float(row["capital_cost_per_property"]) * int(row["total_properties"])
        if not np.isclose(
            float(row["capital_cost_total"]), expected,
            rtol=COST_RECONCILIATION_REL_TOLERANCE,
            atol=COST_RECONCILIATION_ABS_TOLERANCE_GBP,
        ):
            raise ValueError(
                f"scenario total cost does not reconcile for {row.get('scenario_id')}: "
                f"{row['capital_cost_total']} != {expected}"
            )
    return len(scenarios)


def _validate_readiness_costs(readiness: pd.DataFrame) -> dict[str, float]:
    required = {
        "fabric_prerequisite_cost", "system_cost_full_ashp", "total_cost_full_ashp",
        "system_cost_hybrid_ashp_sensitivity", "total_cost_hybrid_ashp_sensitivity",
    }
    missing = required.difference(readiness.columns)
    if missing:
        raise ValueError(f"missing explicit readiness costs: {sorted(missing)}")
    label_column = "ashp_plus_boiler_sensitivity_label"
    qualification_column = "ashp_plus_boiler_sensitivity_qualifications"
    if label_column not in readiness or not readiness[label_column].eq(
        "Tier 4 ASHP-plus-boiler capital-cost sensitivity"
    ).all():
        raise ValueError("supporting ASHP-plus-boiler sensitivity label is missing or ambiguous")
    required_caveats = (
        "not the spatial heat-network/ASHP hybrid scenario",
        "not part of the readiness classification",
        "not a recommended pathway",
        "retains boiler backup",
        "not the modelled net-zero endpoint",
        "operating-cost and carbon implications are not established",
    )
    caveats = readiness.get(qualification_column, pd.Series(dtype=str)).fillna("").str.casefold()
    if caveats.empty or any(not caveats.str.contains(text.casefold(), regex=False).all() for text in required_caveats):
        raise ValueError("supporting ASHP-plus-boiler sensitivity qualifications are incomplete")
    forbidden = {"system_cost", "total_cost", "total_retrofit_cost"}.intersection(readiness.columns)
    if forbidden:
        raise ValueError(f"ambiguous readiness costs remain: {sorted(forbidden)}")
    numeric = readiness[list(required)].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric.to_numpy()).all() or (numeric < 0).any().any():
        raise ValueError("readiness costs contain non-finite or negative values")
    if not np.allclose(
        numeric["total_cost_full_ashp"],
        numeric["fabric_prerequisite_cost"] + numeric["system_cost_full_ashp"],
        rtol=COST_RECONCILIATION_REL_TOLERANCE,
        atol=COST_RECONCILIATION_ABS_TOLERANCE_GBP,
    ):
        raise ValueError("canonical full-ASHP readiness costs do not reconcile property-by-property")
    if not np.allclose(
        numeric["total_cost_hybrid_ashp_sensitivity"],
        numeric["fabric_prerequisite_cost"] + numeric["system_cost_hybrid_ashp_sensitivity"],
        rtol=COST_RECONCILIATION_REL_TOLERANCE,
        atol=COST_RECONCILIATION_ABS_TOLERANCE_GBP,
    ):
        raise ValueError("ASHP-plus-boiler capital-cost sensitivity does not reconcile property-by-property")
    return {
        "canonical_full_ashp_total_gbp": float(numeric["total_cost_full_ashp"].sum()),
        "hybrid_ashp_sensitivity_total_gbp": float(numeric["total_cost_hybrid_ashp_sensitivity"].sum()),
    }


def _validate_payback_columns(*frames: pd.DataFrame) -> int:
    required = {
        "aggregate_simple_payback_years", "property_simple_payback_mean_years",
        "property_simple_payback_median_years", *_PAYBACK_COUNT_FIELDS,
        "truncation_threshold_years", "excluded_by_truncation_count",
    }
    for frame in frames:
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"missing payback fields: {sorted(missing)}")
        if frame["truncation_threshold_years"].notna().any() or frame["excluded_by_truncation_count"].fillna(0).ne(0).any():
            raise ValueError("property paybacks were truncated")
        legacy = {"average_payback_years", "median_payback_years"}.intersection(frame.columns)
        if legacy and "payback_compatibility_note" not in frame.columns:
            raise ValueError(f"ambiguous legacy payback fields lack compatibility note: {sorted(legacy)}")
    return sum(len(frame) for frame in frames)


def _validate_payback_arithmetic(scenarios: pd.DataFrame, properties: pd.DataFrame) -> int:
    scenario_key = "scenario_id" if "scenario_id" in scenarios else "scenario"
    for _, row in scenarios.iterrows():
        scenario = row[scenario_key]
        annual_savings = float(row["annual_bill_savings"])
        expected_aggregate = float(row["capital_cost_total"]) / annual_savings if annual_savings > 0 else None
        _require_close_or_both_null(row["aggregate_simple_payback_years"], expected_aggregate, f"{scenario} aggregate payback")
        subset = properties[properties["scenario"].eq(scenario)]
        summary = payback_summary(subset["capital_cost"], subset["annual_bill_savings"])
        for field in ("property_simple_payback_mean_years", "property_simple_payback_median_years"):
            _require_close_or_both_null(row[field], summary[field], f"{scenario} {field}")
        for field in _PAYBACK_COUNT_FIELDS:
            if int(row[field]) != int(summary[field]):
                raise ValueError(f"{scenario} {field}={row[field]}, recalculated={summary[field]}")
        if int(row["excluded_by_truncation_count"]) != 0 or not pd.isna(row["truncation_threshold_years"]):
            raise ValueError(f"{scenario} finite property paybacks were truncated")
    return len(scenarios)


def _validate_zero_subsidy_payback(scenarios: pd.DataFrame, subsidy: pd.DataFrame) -> int:
    scenario_key = "scenario_id" if "scenario_id" in scenarios else "scenario"
    canonical = scenarios.set_index(scenario_key)
    zero = subsidy[pd.to_numeric(subsidy["subsidy_percentage"], errors="coerce").eq(0)]
    if zero.empty or not set(zero["scenario"]).issubset(set(canonical.index)):
        raise ValueError("zero-subsidy rows do not resolve to canonical public scenarios")
    for _, row in zero.iterrows():
        source = canonical.loc[row["scenario"]]
        for field in (
            "aggregate_simple_payback_years", "property_simple_payback_mean_years",
            "property_simple_payback_median_years", *_PAYBACK_COUNT_FIELDS,
            "excluded_by_truncation_count", "truncation_threshold_years",
        ):
            if not _values_close(row[field], source[field], exact=True):
                raise ValueError(f"zero-subsidy {field} does not exactly match canonical scenario {row['scenario']}")
    return len(zero)


def _validate_payback_exclusions(scenarios: pd.DataFrame) -> int:
    for _, row in scenarios.iterrows():
        categorised = sum(int(row[field]) for field in _PAYBACK_COUNT_FIELDS)
        if categorised != int(row["total_properties"]):
            raise ValueError(
                f"payback exclusion categories sum to {categorised}, expected {row['total_properties']} "
                f"for {row.get('scenario_id')}"
            )
    return len(scenarios)


def _validate_one_stop_json(payload: dict[str, Any], context: RunContext, root: Path) -> dict[str, int]:
    metadata = payload.get("metadata", {})
    if metadata.get("run_id") != context.run_id or metadata.get("dataset_fingerprint") != context.dataset_fingerprint:
        raise ValueError("one-stop metadata does not match active run")
    sections = payload.get("sections", {})
    identifiers = []
    titles = []
    datapoint_count = 0
    recognized_config_sources = {
        "Configuration / run definition", "Configuration / analysis phase", "Tipping point analysis phase"
    }
    for section_key, section in sections.items():
        section_id = section.get("section_id")
        if section_id != section_key:
            raise ValueError(f"section identifier missing or mismatched: {section_key}")
        identifiers.append(section_id)
        titles.append(section.get("title"))
        datapoints = section.get("datapoints", [])
        keys = [item.get("key") for item in datapoints]
        if len(keys) != len(set(keys)):
            raise ValueError(f"duplicate one-stop datapoint keys in {section_key}")
        datapoint_count += len(datapoints)
        for item in datapoints:
            source = str(item.get("source") or "").split(" ->", 1)[0]
            if "comparisons/hn_vs_hp_comparison.csv" in source.replace("\\", "/"):
                raise ValueError("diagnostic comparison artifact referenced by public one-stop output")
            if source.startswith("config/") or source == "src/modeling/contracts.py" or source in recognized_config_sources:
                continue
            artifact = _resolve_public_source(root, source)
            if not artifact.is_file():
                raise ValueError(f"one-stop source artifact does not exist: {source}")
            provenance_path = artifact.with_name(artifact.name + ".provenance.json")
            if not provenance_path.is_file():
                raise ValueError(f"one-stop source artifact lacks current-run provenance: {source}")
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            if provenance.get("run_id") != context.run_id:
                raise ValueError(f"one-stop source artifact has wrong run ID: {source}")
            if context.dataset_fingerprint is not None and provenance.get("dataset_fingerprint") != context.dataset_fingerprint:
                raise ValueError(f"one-stop source artifact has wrong dataset fingerprint: {source}")
        for table in section.get("tables", []):
            for row in table.get("data", []):
                if row.get("publication_scope") == "internal" or _is_false(row.get("headline_reporting_eligible")):
                    raise ValueError(f"internal or headline-ineligible row appears in public {section_key}")
                if row.get("model_family") == DIAGNOSTIC_FULL_FABRIC_PATHWAY.model_family:
                    raise ValueError(f"diagnostic row appears in public {section_key}")
        if section_key == "section_7":
            for table in section.get("tables", []):
                for row in table.get("data", []):
                    if row.get("model_family") != STOCK_SCENARIO.model_family:
                        raise ValueError("Section 7 is not based exclusively on the public stock-scenario comparison")
    if len(identifiers) != len(set(identifiers)) or None in identifiers:
        raise ValueError("one-stop section identifiers are not unique")
    if len(titles) != len(set(titles)) or None in titles:
        raise ValueError("one-stop section titles are not unique")

    readiness_datapoints = {item["key"]: item.get("value") for item in sections.get("section_4", {}).get("datapoints", [])}
    readiness = pd.read_csv(root / "outputs" / "retrofit_readiness_analysis.csv", low_memory=False)
    for field in ("total_cost_full_ashp",):
        key = f"{field}_gbp"
        expected = float(pd.to_numeric(readiness[field], errors="raise").sum())
        if key not in readiness_datapoints or not np.isclose(
            float(readiness_datapoints[key]), expected,
            rtol=COST_RECONCILIATION_REL_TOLERANCE,
            atol=COST_RECONCILIATION_ABS_TOLERANCE_GBP,
        ):
            raise ValueError(f"one-stop readiness total does not reconcile for {field}")
    serialized = json.dumps(payload).casefold()
    if "hybrid_ashp_sensitivity" in serialized or "hybrid-ashp sensitivity" in serialized:
        raise ValueError("ASHP-plus-boiler sensitivity appears in primary one-stop output")
    return {"sections": len(sections), "datapoints": datapoint_count}


def _validate_energy_price_metadata(
    context: RunContext,
    run_metadata: dict[str, Any],
    one_stop: dict[str, Any],
    dashboard: dict[str, Any],
) -> str:
    expected = (context.energy_price_profile or {}).get("profile_id")
    if not expected:
        raise ValueError("active run lacks an energy price profile ID")
    observed = {
        "run metadata": (run_metadata.get("energy_price_profile") or {}).get("profile_id"),
        "one-stop metadata": (one_stop.get("metadata", {}).get("energy_price_profile") or {}).get("profile_id"),
        "dashboard metadata": (dashboard.get("runMetadata", {}).get("energy_price_profile") or {}).get("profile_id"),
    }
    mismatched = {name: value for name, value in observed.items() if value != expected}
    if mismatched:
        raise ValueError(f"client-facing energy price profile metadata mismatch: {mismatched}; expected {expected}")
    return expected


def _resolve_public_source(root: Path, source: str) -> Path:
    normalized = source.replace("\\", "/")
    if normalized.startswith("data/outputs/"):
        return root / "outputs" / normalized.removeprefix("data/outputs/")
    if normalized.startswith("data/processed/"):
        return root / "processed" / normalized.removeprefix("data/processed/")
    raise ValueError(f"unrecognised one-stop source reference: {source}")


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


def _require_close_or_both_null(actual: Any, expected: Any, label: str) -> None:
    if not _values_close(actual, expected):
        raise ValueError(f"{label} does not reconcile: published={actual}, recalculated={expected}")


def _values_close(left: Any, right: Any, *, exact: bool = False) -> bool:
    left_null = left is None or pd.isna(left)
    right_null = right is None or pd.isna(right)
    if left_null or right_null:
        return left_null and right_null
    if exact:
        return float(left) == float(right)
    return bool(np.isclose(
        float(left), float(right),
        rtol=PAYBACK_RECONCILIATION_REL_TOLERANCE,
        atol=PAYBACK_RECONCILIATION_ABS_TOLERANCE,
    ))


def _as_bool(series: pd.Series) -> pd.Series:
    return series.map(lambda value: value is True or str(value).strip().casefold() == "true")


def _is_false(value: Any) -> bool:
    return value is False or str(value).strip().casefold() == "false"


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    return str(value)
