from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from src.modeling.contracts import (
    PROPERTY_ID_COLUMN,
    join_spatial_enrichment,
    payback_summary,
    validate_hybrid_assignments,
)
from src.reporting.comparisons import build_stock_scenario_comparison
from src.reporting.window_economics import generate_window_economics
from src.utils.run_integrity import RunContext
from src.utils.run_integrity import publish_run_outputs
from src.utils.semantic_qa import _validate_spatial_tiers


@pytest.fixture
def four_property_cohort():
    authoritative = pd.DataFrame({
        PROPERTY_ID_COLUMN: ["P3", "P1", "P4", "P2"],
        "TOTAL_FLOOR_AREA": [80, 90, 100, 110],
    })
    spatial = pd.DataFrame({
        PROPERTY_ID_COLUMN: ["P1", "P2", "P3", "P4"],
        "tier_number": [1, 2, 4, 5],
        "hn_ready": [True, True, False, False],
    })
    return authoritative, spatial


def test_spatial_join_preserves_authoritative_identifier_order_and_cohort(four_property_cohort):
    authoritative, spatial = four_property_cohort
    enriched, summary = join_spatial_enrichment(authoritative, spatial)
    assert enriched[PROPERTY_ID_COLUMN].tolist() == ["P3", "P1", "P4", "P2"]
    assert len(enriched) == 4
    assert summary["hn_ready_properties"] == 2
    assert summary["unmatched_properties"] == 0
    assert _validate_spatial_tiers(enriched) == 2


def test_spatial_join_rejects_duplicate_or_missing_classification(four_property_cohort):
    authoritative, spatial = four_property_cohort
    with pytest.raises(ValueError, match="must be unique"):
        join_spatial_enrichment(authoritative, pd.concat([spatial, spatial.iloc[:1]]))
    with pytest.raises(RuntimeError, match="lost required classifications"):
        join_spatial_enrichment(authoritative, spatial.iloc[:-1])


def test_payback_contract_keeps_finite_values_over_100_years():
    summary = payback_summary(
        pd.Series([1000, 20_000, 500, 500]),
        pd.Series([100, 100, 0, -10]),
    )
    assert summary["aggregate_simple_payback_years"] == pytest.approx(22_000 / 190)
    assert summary["property_simple_payback_mean_years"] == 105
    assert summary["property_simple_payback_median_years"] == 105
    assert summary["payback_valid_denominator_count"] == 2
    assert summary["payback_non_positive_savings_count"] == 2
    assert summary["truncation_threshold_years"] is None
    assert summary["excluded_by_truncation_count"] == 0


def test_hybrid_assignments_are_exclusive_and_complete():
    frame = pd.DataFrame({
        "assigned_heat_network": [True, True, False, False],
        "assigned_ashp": [False, False, True, True],
        "hn_ready": [True, True, False, False],
    })
    validate_hybrid_assignments(frame)
    with pytest.raises(ValueError, match="double"):
        validate_hybrid_assignments(frame.assign(assigned_ashp=[True, False, True, True]))
    with pytest.raises(ValueError, match="unassigned"):
        validate_hybrid_assignments(frame.assign(assigned_heat_network=[False, True, False, False]))


def test_public_comparison_uses_stock_scenario_family_and_both_hybrid_technologies():
    property_rows = []
    for scenario, costs in {
        "heat_pump": [12, 12, 12, 12],
        "heat_network": [5, 5, 5, 5],
        "hybrid": [12, 5, 12, 5],
    }.items():
        for index, cost in enumerate(costs):
            property_rows.append({
                "scenario": scenario,
                "capital_cost": cost,
                "annual_bill_savings": cost / 2,
                "annual_energy_reduction_kwh": cost * 10,
                "annual_co2_reduction_kg": cost * 3,
                "hybrid_pathway": ("heat_network" if index in {1, 3} else "ashp") if scenario == "hybrid" else None,
            })
    properties = pd.DataFrame(property_rows)
    results = {}
    for scenario in ("heat_pump", "heat_network", "hybrid"):
        subset = properties[properties.scenario.eq(scenario)]
        results[scenario] = {
            "scenario_label": scenario,
            "total_properties": 4,
            "capital_cost_total": subset.capital_cost.sum(),
            "capital_cost_per_property": subset.capital_cost.mean(),
            "annual_bill_savings": subset.annual_bill_savings.sum(),
            "annual_energy_reduction_kwh": subset.annual_energy_reduction_kwh.sum(),
            "annual_co2_reduction_kg": subset.annual_co2_reduction_kg.sum(),
            "aggregate_simple_payback_years": 2,
            "property_simple_payback_mean_years": 2,
            "property_simple_payback_median_years": 2,
            "hn_assigned_properties": 2 if scenario == "hybrid" else (4 if scenario == "heat_network" else 0),
            "ashp_assigned_properties": 2 if scenario == "hybrid" else (4 if scenario == "heat_pump" else 0),
        }
    comparison = build_stock_scenario_comparison(results, properties)
    assert set(comparison.model_family) == {"stock_scenario"}
    assert set(comparison.scenario_id) == {"heat_pump", "heat_network", "hybrid"}


def test_run_context_rejects_non_utc_and_runtime_mismatch():
    start = datetime.now(timezone.utc)
    valid = RunContext(
        "run",
        analysis_start=start.isoformat(),
        analysis_end=(start + timedelta(seconds=10)).isoformat(),
        runtime_seconds=10,
    )
    valid.validate_timing()
    derived = RunContext("run", analysis_start=start.isoformat()).with_timing(
        analysis_end=(start + timedelta(seconds=10)).isoformat()
    )
    assert derived.runtime_seconds == 10
    derived.validate_timing()
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        RunContext("run", analysis_start=start.replace(tzinfo=None).isoformat(), analysis_end=start.isoformat(), runtime_seconds=0).validate_timing()
    with pytest.raises(ValueError, match="reconcile"):
        RunContext("run", analysis_start=start.isoformat(), analysis_end=(start + timedelta(seconds=10)).isoformat(), runtime_seconds=30).validate_timing()


def test_window_economics_is_config_backed_and_traceable(tmp_path):
    result = generate_window_economics(tmp_path / "window_economics.csv")
    assert result["assumption_source"].str.len().gt(0).all()
    assert result["simple_payback_years"].notna().all()
    assert (tmp_path / "window_economics.csv").is_file()


def test_failed_qa_gate_preserves_previous_public_snapshot(tmp_path):
    run_outputs = tmp_path / "run" / "outputs"
    public = tmp_path / "public"
    run_outputs.mkdir(parents=True)
    public.mkdir()
    (run_outputs / "one_stop_output.json").write_text("{}", encoding="utf-8")
    (run_outputs / "qa_checks.json").write_text(
        '{"run_id":"new-run","status":"fail","critical_failure_count":1}',
        encoding="utf-8",
    )
    (public / "snapshot.txt").write_text("previous", encoding="utf-8")
    with pytest.raises(RuntimeError, match="critical failures"):
        publish_run_outputs(run_outputs, public, "new-run")
    assert (public / "snapshot.txt").read_text(encoding="utf-8") == "previous"
