"""Build report headline data for Excel export."""

from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple

import pandas as pd

from src.reporting.report_headline_schema import (
    REPORT_HEADLINE_COLUMNS,
    validate_report_headline_dataframe,
)


def build_report_headline_dataframe(
    archetype_results: Optional[Dict],
    scenario_results: Optional[Dict],
    subsidy_results: Optional[Dict] = None,
    borough_breakdown: Optional[pd.DataFrame] = None,
    case_street_summary: Optional[Dict] = None,
) -> pd.DataFrame:
    """Construct a dataframe of headline metrics for report exports."""
    rows = []

    def add_row(
        metric_key: str,
        value,
        metric_label: str,
        scenario: str = "overall",
        unit: Optional[str] = None,
        source: Optional[str] = None,
    ) -> None:
        rows.append(
            {
                "metric_key": metric_key,
                "metric_label": metric_label,
                "scenario": scenario,
                "value": value,
                "unit": unit,
                "source": source,
            }
        )

    epc_bands = archetype_results.get("epc_bands", {}) if archetype_results else {}
    epc_freq = epc_bands.get("frequency", {}) or {}
    total_properties = epc_bands.get("total")
    if total_properties is None and epc_freq:
        total_properties = sum(epc_freq.values())

    add_row(
        "total_properties_analyzed",
        total_properties,
        "Total properties analyzed",
        unit="count",
        source="archetype_results",
    )

    if epc_freq:
        modal_band = max(epc_freq, key=epc_freq.get)
        add_row(
            "modal_epc_band",
            modal_band,
            "Most common EPC band",
            source="archetype_results",
        )

    sap_scores = archetype_results.get("sap_scores", {}) if archetype_results else {}
    add_row(
        "mean_sap_score",
        sap_scores.get("mean"),
        "Mean SAP score",
        unit="score",
        source="archetype_results",
    )
    add_row(
        "median_sap_score",
        sap_scores.get("median"),
        "Median SAP score",
        unit="score",
        source="archetype_results",
    )

    wall_construction = (
        archetype_results.get("wall_construction", {}) if archetype_results else {}
    )
    add_row(
        "wall_insulation_rate_pct",
        wall_construction.get("insulation_rate"),
        "Wall insulation rate",
        unit="percent",
        source="archetype_results",
    )
    insulated_count = wall_construction.get("insulated_count")
    uninsulated_count = wall_construction.get("uninsulated_count")
    wall_total_properties = None
    if insulated_count is not None and uninsulated_count is not None:
        wall_total_properties = insulated_count + uninsulated_count
    add_row(
        "wall_insulated_count",
        insulated_count,
        "Insulated wall count",
        unit="count",
        source="archetype_results",
    )
    add_row(
        "wall_total_properties",
        wall_total_properties,
        "Total properties with wall data",
        unit="count",
        source="archetype_results",
    )

    if borough_breakdown is not None and not borough_breakdown.empty:
        top_borough = borough_breakdown.sort_values(
            "property_count", ascending=False
        ).iloc[0]
        borough_code = (
            top_borough.name if top_borough.name is not None else "unknown"
        )
        add_row(
            "top_borough_code",
            borough_code,
            "Borough with most properties (code)",
            scenario="boroughs",
            source="borough_breakdown",
        )
        add_row(
            "top_borough_property_count",
            top_borough.get("property_count"),
            "Property count in top borough",
            scenario="boroughs",
            unit="count",
            source="borough_breakdown",
        )
        add_row(
            "top_borough_modal_epc_band",
            top_borough.get("modal_epc_band"),
            "Modal EPC band in top borough",
            scenario="boroughs",
            source="borough_breakdown",
        )

    if case_street_summary and case_street_summary.get("case_street"):
        case_street = case_street_summary["case_street"]
        add_row(
            "case_street_property_count",
            case_street.get("property_count"),
            "Case street property count",
            scenario="case_street",
            unit="count",
            source="case_street_summary",
        )
        add_row(
            "case_street_mean_energy_consumption",
            case_street.get("mean_energy_consumption"),
            "Case street mean energy consumption",
            scenario="case_street",
            unit="kwh_per_m2_year",
            source="case_street_summary",
        )
        add_row(
            "case_street_mean_co2_emissions",
            case_street.get("mean_co2_emissions"),
            "Case street mean CO2 emissions",
            scenario="case_street",
            unit="tonnes_per_year",
            source="case_street_summary",
        )
        add_row(
            "case_street_mean_floor_area",
            case_street.get("mean_floor_area"),
            "Case street mean floor area",
            scenario="case_street",
            unit="m2",
            source="case_street_summary",
        )
        add_row(
            "case_street_mean_epc_rating",
            case_street.get("mean_epc_rating"),
            "Case street mean EPC rating",
            scenario="case_street",
            unit="score",
            source="case_street_summary",
        )

    if subsidy_results:
        subsidy_values = list(subsidy_results.values())
        max_uptake = max(
            subsidy_values, key=lambda item: item.get("estimated_uptake_rate", 0)
        )
        min_payback = min(
            subsidy_values, key=lambda item: item.get("payback_years", float("inf"))
        )
        max_public_spend = max(
            subsidy_values, key=lambda item: item.get("public_expenditure_total", 0)
        )

        add_row(
            "subsidy_max_uptake_pct",
            max_uptake.get("estimated_uptake_rate", 0) * 100,
            "Max uptake rate under subsidy sensitivity",
            scenario="subsidy_sensitivity",
            unit="percent",
            source="subsidy_results",
        )
        add_row(
            "subsidy_max_uptake_properties_upgraded",
            max_uptake.get("properties_upgraded"),
            "Properties upgraded at max uptake",
            scenario="subsidy_sensitivity",
            unit="count",
            source="subsidy_results",
        )
        subsidy_uptake_rate = max_uptake.get("estimated_uptake_rate", 0)
        subsidy_total_properties = None
        if subsidy_uptake_rate:
            subsidy_total_properties = round(
                max_uptake.get("properties_upgraded", 0) / subsidy_uptake_rate
            )
        add_row(
            "subsidy_max_uptake_total_properties",
            subsidy_total_properties,
            "Total properties for max uptake calculation",
            scenario="subsidy_sensitivity",
            unit="count",
            source="subsidy_results",
        )
        add_row(
            "subsidy_level_for_max_uptake_pct",
            max_uptake.get("subsidy_percentage"),
            "Subsidy level for max uptake rate",
            scenario="subsidy_sensitivity",
            unit="percent",
            source="subsidy_results",
        )
        add_row(
            "subsidy_min_payback_years",
            min_payback.get("payback_years"),
            "Minimum payback under subsidy sensitivity",
            scenario="subsidy_sensitivity",
            unit="years",
            source="subsidy_results",
        )
        add_row(
            "subsidy_level_for_min_payback",
            min_payback.get("subsidy_percentage"),
            "Subsidy level for minimum payback",
            scenario="subsidy_sensitivity",
            unit="percent",
            source="subsidy_results",
        )
        add_row(
            "subsidy_max_public_expenditure_total",
            max_public_spend.get("public_expenditure_total"),
            "Maximum public expenditure under subsidy sensitivity",
            scenario="subsidy_sensitivity",
            unit="gbp",
            source="subsidy_results",
        )

    for scenario_name, results in _iter_scenario_items(scenario_results):
        cost_effective_pct = None
        cost_effective_count = None
        if isinstance(results.get("cost_effectiveness_summary"), dict):
            cost_effective_summary = results["cost_effectiveness_summary"]
            cost_effective_pct = cost_effective_summary.get("cost_effective_pct")
            cost_effective_count = cost_effective_summary.get("cost_effective_count")
        if cost_effective_pct is None:
            cost_effective_pct = results.get("cost_effective_pct")
        if cost_effective_count is None:
            cost_effective_count = results.get("cost_effective_count")

        scenario_metrics = [
            (
                "scenario_total_properties",
                results.get("total_properties"),
                "Scenario total properties",
                "count",
            ),
            (
                "scenario_capital_cost_total",
                results.get("capital_cost_total"),
                "Scenario total capital cost",
                "gbp",
            ),
            (
                "scenario_capital_cost_per_property",
                results.get("capital_cost_per_property"),
                "Scenario capital cost per property",
                "gbp",
            ),
            (
                "scenario_annual_co2_reduction_kg",
                results.get("annual_co2_reduction_kg"),
                "Scenario annual CO2 reduction",
                "kg",
            ),
            (
                "scenario_annual_bill_savings",
                results.get("annual_bill_savings"),
                "Scenario annual bill savings",
                "gbp",
            ),
            (
                "scenario_average_payback_years",
                results.get("average_payback_years"),
                "Scenario average payback",
                "years",
            ),
            (
                "scenario_cost_effective_pct",
                cost_effective_pct,
                "Scenario cost-effective share",
                "percent",
            ),
            (
                "scenario_cost_effective_count",
                cost_effective_count,
                "Scenario cost-effective count",
                "count",
            ),
            (
                "scenario_carbon_abatement_cost_median",
                results.get("carbon_abatement_cost_median"),
                "Scenario median carbon abatement cost",
                "gbp_per_tco2",
            ),
        ]

        for metric_key, value, label, unit in scenario_metrics:
            add_row(
                metric_key,
                value,
                label,
                scenario=scenario_name,
                unit=unit,
                source="scenario_results",
            )

    dataframe = pd.DataFrame(rows, columns=REPORT_HEADLINE_COLUMNS)
    scenario_names = [
        scenario for scenario, _ in _iter_scenario_items(scenario_results)
    ]
    validate_report_headline_dataframe(
        dataframe,
        scenario_names=scenario_names,
        include_boroughs=borough_breakdown is not None and not borough_breakdown.empty,
        include_case_street=bool(
            case_street_summary and case_street_summary.get("case_street")
        ),
        include_subsidy=bool(subsidy_results),
    )
    return dataframe


def _iter_scenario_items(
    scenario_results: Optional[Dict],
) -> Iterable[Tuple[str, Dict]]:
    if scenario_results is None:
        return []
    if isinstance(scenario_results, pd.DataFrame):
        if "scenario" in scenario_results.columns:
            for _, row in scenario_results.iterrows():
                scenario_name = row.get("scenario") or "scenario"
                yield scenario_name, row.to_dict()
        return []
    for scenario_name, results in scenario_results.items():
        scenario_label = None
        if isinstance(results, dict):
            scenario_label = results.get("scenario_label")
        yield scenario_label or scenario_name, results
