from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from src.modeling.contracts import TIER_READINESS_LABELS, payback_summary
from src.reporting.dashboard_data_builder import DashboardDataBuilder
from src.reporting.one_stop_report import OneStopReportGenerator
from src.utils.run_integrity import RunContext
from src.utils.semantic_qa import (
    _validate_epc_distribution,
    _validate_hybrid_distinction,
    _validate_one_stop_json,
    _validate_payback_arithmetic,
    _validate_payback_exclusions,
    _validate_percentage_distributions,
    _validate_readiness_distribution,
    _validate_scenario_costs,
    _validate_spatial_distribution,
    _validate_zero_subsidy_payback,
    _validate_energy_price_metadata,
)


@pytest.fixture
def four_property_semantic_fixture():
    enriched = pd.DataFrame({"hn_ready": [True, True, False, False]})
    properties = []
    inputs = {
        "heat_pump": ([1000, 20_000, 500, np.nan], [100, 100, 0, 10]),
        "heat_network": ([600, 800, 900, np.inf], [60, -10, 9, 10]),
        "hybrid": ([600, 800, 500, np.nan], [60, -10, 0, 10]),
    }
    summaries = []
    for scenario, (capital, savings) in inputs.items():
        for index, (cost, saving) in enumerate(zip(capital, savings)):
            properties.append({
                "scenario": scenario,
                "capital_cost": cost,
                "annual_bill_savings": saving,
                "hybrid_pathway": (
                    "heat_network" if index < 2 else "ashp"
                ) if scenario == "hybrid" else None,
            })
        payback = payback_summary(pd.Series(capital), pd.Series(savings))
        finite_cost = pd.Series(capital).replace([np.inf, -np.inf], np.nan).fillna(0)
        total_cost = float(finite_cost.sum())
        summaries.append({
            "scenario_id": scenario,
            "total_properties": 4,
            "capital_cost_total": total_cost,
            "capital_cost_per_property": total_cost / 4,
            "annual_bill_savings": float(pd.Series(savings).replace([np.inf, -np.inf], np.nan).fillna(0).sum()),
            "post_measure_bill_total": {"heat_pump": 1000, "heat_network": 900, "hybrid": 950}[scenario],
            "annual_co2_reduction_kg": {"heat_pump": 300, "heat_network": 500, "hybrid": 400}[scenario],
            "post_measure_co2_total_kg": {"heat_pump": 700, "heat_network": 500, "hybrid": 600}[scenario],
            **payback,
        })
    return enriched, pd.DataFrame(properties), pd.DataFrame(summaries)


def test_canonical_readiness_labels_match_csv_one_stop_and_dashboard(tmp_path):
    frame = pd.DataFrame({
        "hp_readiness_tier": range(1, 6),
        "hp_readiness_label": [TIER_READINESS_LABELS[tier] for tier in range(1, 6)],
        "fabric_prerequisite_cost": [0, 1, 2, 3, 4],
        "system_cost_full_ashp": [10] * 5,
        "total_cost_full_ashp": [10, 11, 12, 13, 14],
        "system_cost_hybrid_ashp_sensitivity": [8] * 5,
        "total_cost_hybrid_ashp_sensitivity": [8, 9, 10, 11, 12],
    })
    report = OneStopReportGenerator(output_dir=tmp_path, processed_dir=tmp_path)
    report._sections["section_4"] = report._build_section_4(frame)
    glossary = report._build_section_13()["definitions"]["heat_pump_readiness_tiers"]
    dashboard = DashboardDataBuilder(tmp_path)._format_readiness_tiers({
        "total_properties": 5,
        "tier_distribution": {tier: 1 for tier in range(1, 6)},
        "tier_percentages": {tier: 20 for tier in range(1, 6)},
    })
    assert frame["hp_readiness_label"].tolist() == list(TIER_READINESS_LABELS.values())
    assert [glossary[f"tier_{tier}"]["label"] for tier in range(1, 6)] == list(TIER_READINESS_LABELS.values())
    assert [row["readinessLabel"] for row in dashboard] == list(TIER_READINESS_LABELS.values())
    section_text = str(report._sections["section_4"])
    assert "total_cost_full_ashp_gbp" in section_text
    assert "hybrid_ashp_sensitivity" not in section_text


def test_primary_dashboard_exposes_only_canonical_full_ashp_total(tmp_path):
    summary = DashboardDataBuilder(tmp_path)._format_summary_stats(
        None,
        {
            "total_properties": 2,
            "total_cost_full_ashp": 100,
            "total_cost_hybrid_ashp_sensitivity": 80,
            "mean_total_cost_hybrid_ashp_sensitivity": 40,
        },
        None,
        None,
        None,
        None,
    )
    assert summary["totalCostFullAshp"] == 100
    assert all("HybridAshpSensitivity" not in key for key in summary)


def test_energy_price_profile_metadata_mismatch_fails(tmp_path):
    profile = {"profile_id": "january_client_report_provisional"}
    context = RunContext(
        "run-1", dataset_fingerprint="fingerprint", run_root=tmp_path,
        authoritative_cohort=4, energy_price_profile=profile,
    )
    run_metadata = {"energy_price_profile": profile}
    one_stop = {"metadata": {"energy_price_profile": profile}}
    dashboard = {"runMetadata": {"energy_price_profile": {"profile_id": "wrong"}}}
    with pytest.raises(ValueError, match="profile metadata mismatch"):
        _validate_energy_price_metadata(context, run_metadata, one_stop, dashboard)


@pytest.mark.parametrize("validator,bad", [
    (_validate_epc_distribution, {"epc_bands": {"frequency": {"D": 3}, "percentage": {"D": 100}}}),
    (_validate_readiness_distribution, pd.DataFrame({"hp_readiness_tier": [1, 2, 3]})),
    (_validate_spatial_distribution, pd.DataFrame({"Property Count": [2, 1], "Percentage": [50, 50]})),
])
def test_distribution_counts_must_sum_to_authoritative_cohort(validator, bad):
    with pytest.raises(ValueError):
        validator(bad, 4)


def test_percentage_distributions_must_sum_to_100():
    scenarios = pd.DataFrame({
        "scenario_id": ["heat_pump"],
        "cost_effective_pct": [30], "marginal_pct": [30], "not_cost_effective_pct": [30],
    })
    archetype = {"epc_bands": {"percentage": {"C": 50, "D": 50}}}
    readiness = pd.DataFrame({"hp_readiness_tier": [1, 2, 3, 4]})
    spatial = pd.DataFrame({"Percentage": [50, 50]})
    with pytest.raises(ValueError, match="sum to"):
        _validate_percentage_distributions(scenarios, archetype, readiness, spatial)


def test_scenario_total_cost_must_reconcile():
    scenarios = pd.DataFrame({"scenario_id": ["heat_pump"], "capital_cost_total": [398.9], "capital_cost_per_property": [100], "total_properties": [4]})
    with pytest.raises(ValueError, match="does not reconcile"):
        _validate_scenario_costs(scenarios)


def test_aggregate_and_property_payback_must_reconcile(four_property_semantic_fixture):
    _, properties, scenarios = four_property_semantic_fixture
    scenarios.loc[scenarios.scenario_id.eq("heat_pump"), "aggregate_simple_payback_years"] = 999
    with pytest.raises(ValueError, match="aggregate payback"):
        _validate_payback_arithmetic(scenarios, properties)


def test_zero_subsidy_payback_must_match_canonical(four_property_semantic_fixture):
    _, _, scenarios = four_property_semantic_fixture
    zero = scenarios.rename(columns={"scenario_id": "scenario"}).copy()
    zero["subsidy_percentage"] = 0
    zero.loc[zero.scenario.eq("hybrid"), "aggregate_simple_payback_years"] += 1
    with pytest.raises(ValueError, match="zero-subsidy"):
        _validate_zero_subsidy_payback(scenarios, zero)


def _minimal_one_stop(context, datapoints=None, tables=None):
    return {
        "metadata": {"run_id": context.run_id, "dataset_fingerprint": context.dataset_fingerprint},
        "sections": {
            "section_1": {
                "section_id": "section_1", "title": "Section 1",
                "datapoints": datapoints or [], "tables": tables or [],
            }
        },
    }


def _context(tmp_path):
    return RunContext(
        "run-1", dataset_fingerprint="fingerprint", run_root=tmp_path,
        authoritative_cohort=4, analysis_start=datetime.now(timezone.utc).isoformat(),
    )


def test_duplicate_one_stop_datapoint_keys_fail(tmp_path):
    context = _context(tmp_path)
    datapoint = {"key": "duplicate", "source": "config/config.yaml -> x"}
    with pytest.raises(ValueError, match="duplicate"):
        _validate_one_stop_json(_minimal_one_stop(context, [datapoint, datapoint]), context, tmp_path)


def test_missing_one_stop_source_artifact_fails(tmp_path):
    context = _context(tmp_path)
    datapoint = {"key": "missing", "source": "data/outputs/missing.csv -> value"}
    with pytest.raises(ValueError, match="does not exist"):
        _validate_one_stop_json(_minimal_one_stop(context, [datapoint]), context, tmp_path)


def test_diagnostic_artifact_in_public_one_stop_fails(tmp_path):
    context = _context(tmp_path)
    datapoint = {"key": "diagnostic", "source": "data/outputs/comparisons/hn_vs_hp_comparison.csv -> value"}
    with pytest.raises(ValueError, match="diagnostic comparison"):
        _validate_one_stop_json(_minimal_one_stop(context, [datapoint]), context, tmp_path)


@pytest.mark.parametrize("pure_assignment", ["ashp", "heat_network"])
def test_hybrid_equality_with_pure_pathway_fails_for_mixed_cohort(four_property_semantic_fixture, pure_assignment):
    enriched, properties, scenarios = four_property_semantic_fixture
    pure = "heat_pump" if pure_assignment == "ashp" else "heat_network"
    pure_row = scenarios.loc[scenarios.scenario_id.eq(pure)].iloc[0]
    for field in (
        "capital_cost_total", "post_measure_bill_total", "annual_bill_savings",
        "post_measure_co2_total_kg", "annual_co2_reduction_kg",
        "aggregate_simple_payback_years", "property_simple_payback_median_years",
    ):
        scenarios.loc[scenarios.scenario_id.eq("hybrid"), field] = pure_row[field]
    properties.loc[properties.scenario.eq("hybrid"), "hybrid_pathway"] = pure_assignment
    with pytest.raises(ValueError, match="mixed HN-ready cohort|identical"):
        _validate_hybrid_distinction(scenarios, properties, enriched)


def test_payback_exclusion_categories_are_distinct_and_reconcile():
    summary = payback_summary(
        pd.Series([20_000.0, 500.0, np.nan, np.inf, 1e308]),
        pd.Series([100.0, 0.0, 10.0, 10.0, 1e-308]),
    )
    assert summary["property_simple_payback_median_years"] == 200
    assert summary["payback_valid_denominator_count"] == 1
    assert summary["payback_non_positive_savings_count"] == 1
    assert summary["payback_missing_input_count"] == 1
    assert summary["payback_non_finite_input_count"] == 1
    assert summary["payback_infinite_count"] == 1
    assert summary["excluded_by_truncation_count"] == 0
    row = {"scenario_id": "heat_pump", "total_properties": 5, **summary}
    assert _validate_payback_exclusions(pd.DataFrame([row])) == 1
