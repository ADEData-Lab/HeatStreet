"""Tests for report headline dataframe schema coverage."""

from pathlib import Path
import sys

import pandas as pd

sys.path.append(str(Path(__file__).parent.parent))

from src.reporting.report_headline_data import build_report_headline_dataframe
from src.reporting.report_headline_schema import (
    REPORT_HEADLINE_COLUMNS,
    REQUIRED_BASE_METRIC_KEYS,
    REQUIRED_SCENARIO_METRIC_KEYS,
)


def test_report_headline_dataframe_includes_required_keys():
    archetype_results = {
        "epc_bands": {"total": 100, "frequency": {"C": 40, "D": 60}},
        "sap_scores": {"mean": 55.5, "median": 54.0},
        "wall_construction": {
            "insulation_rate": 25.0,
            "insulated_count": 25,
            "uninsulated_count": 75,
        },
    }
    scenario_results = {
        "baseline": {
            "total_properties": 100,
            "capital_cost_total": 1000000,
            "capital_cost_per_property": 10000,
            "annual_co2_reduction_kg": 500000,
            "annual_bill_savings": 250000,
            "average_payback_years": 12.5,
            "cost_effective_pct": 40.0,
            "cost_effective_count": 40,
            "carbon_abatement_cost_median": 150,
        },
        "enhanced": {
            "total_properties": 100,
            "capital_cost_total": 1200000,
            "capital_cost_per_property": 12000,
            "annual_co2_reduction_kg": 650000,
            "annual_bill_savings": 300000,
            "average_payback_years": 11.0,
            "cost_effective_pct": 55.0,
            "cost_effective_count": 55,
            "carbon_abatement_cost_median": 140,
        },
    }

    dataframe = build_report_headline_dataframe(archetype_results, scenario_results)

    assert list(dataframe.columns) == REPORT_HEADLINE_COLUMNS

    metric_keys = set(dataframe["metric_key"].dropna())
    assert REQUIRED_BASE_METRIC_KEYS.issubset(metric_keys)

    scenarios = set(dataframe["scenario"].dropna())
    assert set(scenario_results.keys()).issubset(scenarios)

    for scenario_name in scenario_results:
        scenario_keys = set(
            dataframe.loc[dataframe["scenario"] == scenario_name, "metric_key"].dropna()
        )
        assert REQUIRED_SCENARIO_METRIC_KEYS.issubset(scenario_keys)
