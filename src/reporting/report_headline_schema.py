"""Schema definitions for report headline exports."""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence

import pandas as pd

REPORT_HEADLINE_COLUMNS = [
    "metric_key",
    "metric_label",
    "scenario",
    "value",
    "unit",
    "source",
]

REQUIRED_BASE_METRIC_KEYS = {
    "total_properties_analyzed",
    "mean_sap_score",
    "median_sap_score",
    "wall_insulation_rate_pct",
    "wall_insulated_count",
    "wall_total_properties",
}

REQUIRED_SCENARIO_METRIC_KEYS = {
    "scenario_total_properties",
    "scenario_capital_cost_total",
    "scenario_capital_cost_per_property",
    "scenario_annual_co2_reduction_kg",
    "scenario_annual_bill_savings",
    "scenario_average_payback_years",
    "scenario_cost_effective_pct",
    "scenario_cost_effective_count",
    "scenario_carbon_abatement_cost_median",
}

REQUIRED_SUBSIDY_METRIC_KEYS = {
    "subsidy_max_uptake_pct",
    "subsidy_level_for_max_uptake_pct",
    "subsidy_min_payback_years",
    "subsidy_level_for_min_payback",
    "subsidy_max_public_expenditure_total",
    "subsidy_max_uptake_properties_upgraded",
    "subsidy_max_uptake_total_properties",
}

REQUIRED_BOROUGH_METRIC_KEYS = {
    "top_borough_code",
    "top_borough_property_count",
    "top_borough_modal_epc_band",
}

REQUIRED_CASE_STREET_METRIC_KEYS = {
    "case_street_property_count",
    "case_street_mean_energy_consumption",
    "case_street_mean_co2_emissions",
    "case_street_mean_floor_area",
    "case_street_mean_epc_rating",
}

PERCENT_METRIC_REQUIREMENTS: Mapping[str, Mapping[str, str]] = {
    "wall_insulation_rate_pct": {
        "numerator_key": "wall_insulated_count",
        "denominator_key": "wall_total_properties",
    },
    "scenario_cost_effective_pct": {
        "numerator_key": "scenario_cost_effective_count",
        "denominator_key": "scenario_total_properties",
    },
    "subsidy_max_uptake_pct": {
        "numerator_key": "subsidy_max_uptake_properties_upgraded",
        "denominator_key": "subsidy_max_uptake_total_properties",
    },
}


def validate_report_headline_dataframe(
    dataframe: pd.DataFrame,
    *,
    scenario_names: Sequence[str] = (),
    include_boroughs: bool = False,
    include_case_street: bool = False,
    include_subsidy: bool = False,
) -> None:
    """Validate headline dataframe columns and required metric keys."""
    missing_columns = [col for col in REPORT_HEADLINE_COLUMNS if col not in dataframe]
    extra_columns = [col for col in dataframe.columns if col not in REPORT_HEADLINE_COLUMNS]
    if missing_columns or extra_columns:
        raise ValueError(
            "Headline dataframe columns mismatch. "
            f"Missing: {missing_columns or 'none'}, extra: {extra_columns or 'none'}."
        )

    metric_keys = set(dataframe["metric_key"].dropna())
    _raise_if_missing(metric_keys, REQUIRED_BASE_METRIC_KEYS, "base metrics")

    if scenario_names:
        scenario_keys = _keys_by_scenario(dataframe, scenario_names)
        for scenario, keys in scenario_keys.items():
            _raise_if_missing(
                keys, REQUIRED_SCENARIO_METRIC_KEYS, f"scenario metrics for '{scenario}'"
            )

    if include_subsidy:
        _raise_if_missing(metric_keys, REQUIRED_SUBSIDY_METRIC_KEYS, "subsidy metrics")

    if include_boroughs:
        _raise_if_missing(metric_keys, REQUIRED_BOROUGH_METRIC_KEYS, "borough metrics")

    if include_case_street:
        _raise_if_missing(
            metric_keys, REQUIRED_CASE_STREET_METRIC_KEYS, "case street metrics"
        )

    _validate_percent_metrics(dataframe)


def _raise_if_missing(
    available_keys: Iterable[str],
    required_keys: Iterable[str],
    label: str,
) -> None:
    missing = set(required_keys) - set(available_keys)
    if missing:
        raise ValueError(f"Missing required {label}: {sorted(missing)}.")


def _keys_by_scenario(
    dataframe: pd.DataFrame, scenario_names: Sequence[str]
) -> dict[str, set[str]]:
    scenario_keys: dict[str, set[str]] = {}
    for scenario in scenario_names:
        scenario_keys[scenario] = set(
            dataframe.loc[dataframe["scenario"] == scenario, "metric_key"].dropna()
        )
    return scenario_keys


def _validate_percent_metrics(dataframe: pd.DataFrame) -> None:
    for metric_key, requirements in PERCENT_METRIC_REQUIREMENTS.items():
        numerator_key = requirements.get("numerator_key")
        denominator_key = requirements.get("denominator_key")
        if not numerator_key or not denominator_key:
            raise ValueError(
                f"Percent metric '{metric_key}' must define numerator_key and denominator_key."
            )

        metric_rows = dataframe.loc[dataframe["metric_key"] == metric_key]
        if metric_rows.empty:
            continue

        for scenario in metric_rows["scenario"].unique().tolist():
            scenario_keys = set(
                dataframe.loc[dataframe["scenario"] == scenario, "metric_key"].dropna()
            )
            if numerator_key not in scenario_keys:
                raise ValueError(
                    f"Percent metric '{metric_key}' missing numerator metric '{numerator_key}' "
                    f"for scenario '{scenario}'."
                )
            if denominator_key not in scenario_keys:
                raise ValueError(
                    f"Percent metric '{metric_key}' missing denominator metric "
                    f"'{denominator_key}' for scenario '{scenario}'."
                )
