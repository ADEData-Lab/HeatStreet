"""Utilities for exporting dashboard-ready datasets from analysis outputs."""

from pathlib import Path
from typing import Dict, List, Optional, Tuple
import json
import pandas as pd
from loguru import logger

from config.config import DATA_OUTPUTS_DIR
from src.utils.analysis_logger import convert_to_json_serializable


class DashboardDataBuilder:
    """Builds a JSON payload that mirrors the React dashboard data schema."""

    EPC_COLORS = {
        "A": "#1a472a",
        "B": "#2d6a4f",
        "C": "#40916c",
        "D": "#f4a261",
        "E": "#e76f51",
        "F": "#d62828",
        "G": "#9d0208",
    }

    def __init__(self, output_dir: Path = DATA_OUTPUTS_DIR):
        self.output_dir = Path(output_dir) / "dashboard"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def build_dataset(
        self,
        archetype_results: Optional[Dict],
        scenario_results: Optional[Dict],
        readiness_summary: Optional[Dict],
        pathway_summary: Optional[pd.DataFrame] = None,
        borough_breakdown: Optional[pd.DataFrame] = None,
        case_street_summary: Optional[Dict] = None,
        subsidy_results: Optional[Dict] = None,
        df_validated: Optional[pd.DataFrame] = None,
    ) -> Dict:
        """Create a dashboard dataset from analysis artifacts."""

        dataset = {
            "epcBandData": self._format_epc_bands(archetype_results),
            "epcComparisonData": self._format_epc_comparison(archetype_results, case_street_summary),
            "wallTypeData": self._format_wall_types(archetype_results),
            "heatingSystemData": self._format_heating(archetype_results),
            "glazingData": self._format_glazing(archetype_results),
            "scenarioData": self._format_scenarios(scenario_results),
            "tierData": self._format_heat_network_tiers(pathway_summary),
            "retrofitReadinessData": self._format_readiness_tiers(readiness_summary),
            "interventionData": self._format_interventions(readiness_summary),
            "boroughData": self._format_boroughs(borough_breakdown),
            "confidenceBandsData": self._format_confidence_bands(readiness_summary),
            "sensitivityData": self._format_sensitivity(subsidy_results),
            "summaryStats": self._format_summary_stats(
                archetype_results,
                readiness_summary,
                scenario_results,
                pathway_summary,
                df_validated,
            ),
        }

        return convert_to_json_serializable(dataset)

    def write_dataset(self, dataset: Dict) -> Path:
        """Persist the dataset to the outputs directory."""
        output_path = self.output_dir / "dashboard-data.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(dataset, f, indent=2)

        logger.info(f"✓ Dashboard dataset written to {output_path}")
        return output_path

    def _format_epc_bands(self, archetype_results: Optional[Dict]) -> List[Dict]:
        if not archetype_results or "epc_bands" not in archetype_results:
            return []

        band_results = archetype_results.get("epc_bands", {})
        freq = band_results.get("frequency", {})
        pct = band_results.get("percentage", {})

        bands = []
        for band in ["A", "B", "C", "D", "E", "F", "G"]:
            if band in freq or band in pct:
                bands.append(
                    {
                        "band": band,
                        "count": int(freq.get(band, 0)),
                        "percentage": round(float(pct.get(band, 0)), 2),
                        "color": self.EPC_COLORS.get(band),
                    }
                )
        return bands

    def _format_epc_comparison(
        self,
        archetype_results: Optional[Dict],
        case_street_summary: Optional[Dict],
    ) -> List[Dict]:
        band_results = archetype_results.get("epc_bands", {}) if archetype_results else {}
        london_pct = band_results.get("percentage", {})
        case_dist = None
        if case_street_summary and case_street_summary.get("case_street"):
            case_dist = case_street_summary["case_street"].get("epc_band_distribution", {})
            case_total = case_street_summary["case_street"].get("property_count", 0) or 0
            if case_total:
                case_dist = {k: v / case_total * 100 for k, v in case_dist.items()}

        comparison = []
        for band in ["A", "B", "C", "D", "E", "F", "G"]:
            comparison.append(
                {
                    "band": band,
                    "shakespeareCrescent": round(case_dist.get(band, 0), 2) if case_dist else 0,
                    "londonAverage": round(float(london_pct.get(band, 0)), 2),
                }
            )
        return comparison

    def _format_wall_types(self, archetype_results: Optional[Dict]) -> List[Dict]:
        wall_results = archetype_results.get("wall_construction", {}) if archetype_results else {}
        wall_types = wall_results.get("wall_types", {}) or {}
        crosstab = wall_results.get("crosstab", {}) or {}
        total = sum(wall_types.values()) or 1

        wall_data = []
        for wall_type, count in wall_types.items():
            insulated_pct = 0.0
            if wall_type in crosstab and isinstance(crosstab[wall_type], dict):
                insulated_pct = float(crosstab[wall_type].get(True, 0))
                if insulated_pct <= 1:
                    insulated_pct *= 100

            wall_data.append(
                {
                    "type": wall_type.title(),
                    "count": int(count),
                    "percentage": round(count / total * 100, 2),
                    "insulated": round(insulated_pct, 2),
                }
            )
        return wall_data

    def _format_heating(self, archetype_results: Optional[Dict]) -> List[Dict]:
        heat_results = archetype_results.get("heating_systems", {}) if archetype_results else {}
        counts = heat_results.get("types", {})
        pct = heat_results.get("percentages", {})

        heating = []
        for name, count in counts.items():
            heating.append(
                {
                    "name": name,
                    "value": round(float(pct.get(name, 0)), 2),
                    "count": int(count),
                }
            )
        return heating

    def _format_glazing(self, archetype_results: Optional[Dict]) -> List[Dict]:
        glazing_results = archetype_results.get("glazing", {}) if archetype_results else {}
        types = glazing_results.get("types", {})
        pct = glazing_results.get("percentages", {})
        glazing = []
        for name, count in types.items():
            glazing.append(
                {
                    "type": name,
                    "count": int(count),
                    "percentage": round(float(pct.get(name, 0) * 100), 2) if pct else 0,
                }
            )
        return glazing

    def _format_scenarios(self, scenario_results: Optional[Dict]) -> List[Dict]:
        if not scenario_results:
            return []

        scenarios = []
        for scenario, results in scenario_results.items():
            scenarios.append(
                {
                    "scenario": scenario.replace("_", " ").title(),
                    "capitalCost": float(results.get("capital_cost_total", 0)),
                    "costPerProperty": float(results.get("capital_cost_per_property", 0)),
                    "co2Reduction": float(results.get("annual_co2_reduction_kg", 0)),
                    "billSavings": float(results.get("annual_bill_savings", 0)),
                    "paybackYears": results.get("average_payback_years")
                    or results.get("median_payback_years")
                    or 0,
                }
            )
        return scenarios

    def _format_heat_network_tiers(
        self, pathway_summary: Optional[pd.DataFrame]
    ) -> List[Dict]:
        if pathway_summary is None or len(pathway_summary) == 0:
            return []

        tier_data = []
        for _, row in pathway_summary.iterrows():
            tier_data.append(
                {
                    "tier": row.get("Tier"),
                    "properties": int(row.get("Property Count", 0)),
                    "percentage": float(row.get("Percentage", 0)),
                    "recommendation": row.get("Recommended Pathway"),
                }
            )
        return tier_data

    def _format_readiness_tiers(self, readiness_summary: Optional[Dict]) -> List[Dict]:
        if not readiness_summary:
            return []

        tiers = []
        total = readiness_summary.get("total_properties", 1)
        pct_map = readiness_summary.get("tier_percentages", {})
        fabric_map = readiness_summary.get("fabric_cost_by_tier", {})
        for tier, count in readiness_summary.get("tier_distribution", {}).items():
            tiers.append(
                {
                    "tier": f"Tier {int(tier)}",
                    "properties": int(count),
                    "percentage": round(float(pct_map.get(tier, 0)), 2),
                    "avgCost": float(fabric_map.get(tier, 0)),
                }
            )
        return tiers

    def _format_interventions(self, readiness_summary: Optional[Dict]) -> List[Dict]:
        if not readiness_summary:
            return []

        total = readiness_summary.get("total_properties", 1)
        interventions = {
            "Radiator Upsizing": readiness_summary.get("needs_radiator_upsizing", 0),
            "Loft Insulation": readiness_summary.get("needs_loft_insulation", 0),
            "Wall Insulation": readiness_summary.get("needs_wall_insulation", 0),
            "Glazing Upgrade": readiness_summary.get("needs_glazing_upgrade", 0),
            "Solid Wall Insulation": readiness_summary.get("needs_solid_wall_insulation", 0),
            "Cavity Wall Insulation": readiness_summary.get("needs_cavity_wall_insulation", 0),
        }

        data = []
        for name, count in interventions.items():
            data.append(
                {
                    "intervention": name,
                    "percentage": round((count / total) * 100, 2) if total else 0,
                    "count": int(count),
                }
            )
        return data

    def _format_boroughs(self, borough_breakdown: Optional[pd.DataFrame]) -> List[Dict]:
        if borough_breakdown is None or len(borough_breakdown) == 0:
            return []

        borough_data = []
        df = borough_breakdown.reset_index()
        for _, row in df.iterrows():
            borough_data.append(
                {
                    "borough": row.get("LOCAL_AUTHORITY") or row.get("index"),
                    "code": row.get("LOCAL_AUTHORITY") or row.get("index"),
                    "count": int(row.get("property_count", 0)),
                    "meanEPC": float(row.get("mean_epc_rating", 0)),
                    "energy": float(row.get("mean_energy_kwh_m2_year", 0)),
                }
            )
        return borough_data

    def _format_confidence_bands(self, readiness_summary: Optional[Dict]) -> List[Dict]:
        if not readiness_summary:
            return []

        baseline = float(readiness_summary.get("mean_current_heat_demand", 0))
        post_fabric = float(readiness_summary.get("mean_post_fabric_heat_demand", 0))
        reduction = float(readiness_summary.get("heat_demand_reduction_percent", 0))

        bands = []
        for label, estimate in [
            ("Baseline", baseline),
            ("After Fabric", post_fabric),
        ]:
            bands.append(
                {
                    "stage": label,
                    "estimate": round(estimate, 2),
                    "lower": round(estimate * 0.85, 2),
                    "upper": round(estimate * 1.15, 2),
                }
            )

        # Include a full retrofit projection if reduction is available
        if reduction and baseline:
            final_estimate = baseline * (1 - reduction / 100)
            bands.append(
                {
                    "stage": "Full Retrofit",
                    "estimate": round(final_estimate, 2),
                    "lower": round(final_estimate * 0.9, 2),
                    "upper": round(final_estimate * 1.1, 2),
                }
            )
        return bands

    def _format_sensitivity(self, subsidy_results: Optional[Dict]) -> List[Dict]:
        if not subsidy_results:
            return []

        costs = [v.get("capital_cost_per_property", 0) for v in subsidy_results.values()]
        paybacks = [v.get("payback_years", 0) for v in subsidy_results.values()]
        uptake = [v.get("estimated_uptake_rate", 0) * 100 for v in subsidy_results.values()]

        def _range(values: List[float]) -> Tuple[float, float, float]:
            if not values:
                return 0, 0, 0
            low = float(min(values))
            high = float(max(values))
            return low, high, high - low

        cost_low, cost_high, cost_range = _range(costs)
        payback_low, payback_high, payback_range = _range(paybacks)
        uptake_low, uptake_high, uptake_range = _range(uptake)

        return [
            {
                "parameter": "Capital cost per property",
                "lowImpact": round(cost_low, 2),
                "highImpact": round(cost_high, 2),
                "range": round(cost_range, 2),
            },
            {
                "parameter": "Payback (years)",
                "lowImpact": round(payback_low, 2),
                "highImpact": round(payback_high, 2),
                "range": round(payback_range, 2),
            },
            {
                "parameter": "Uptake rate (%)",
                "lowImpact": round(uptake_low, 2),
                "highImpact": round(uptake_high, 2),
                "range": round(uptake_range, 2),
            },
        ]

    def _format_summary_stats(
        self,
        archetype_results: Optional[Dict],
        readiness_summary: Optional[Dict],
        scenario_results: Optional[Dict],
        pathway_summary: Optional[pd.DataFrame],
        df_validated: Optional[pd.DataFrame],
    ) -> Dict:
        summary = {}

        if readiness_summary:
            summary.update(
                {
                    "totalProperties": int(readiness_summary.get("total_properties", 0)),
                    "meanFabricCost": float(readiness_summary.get("mean_fabric_cost", 0)),
                    "meanTotalRetrofitCost": float(readiness_summary.get("mean_total_retrofit_cost", 0)),
                    "heatDemandReduction": float(readiness_summary.get("heat_demand_reduction_percent", 0)),
                    "readyOrNearReady": float(
                        readiness_summary.get("tier_percentages", {}).get(1, 0)
                        + readiness_summary.get("tier_percentages", {}).get(2, 0)
                    ),
                }
            )

        if archetype_results:
            epc_bands = archetype_results.get("epc_bands", {}).get("percentage", {})
            below_c = sum(
                epc_bands.get(band, 0) for band in ["D", "E", "F", "G"]
            )
            heat_pct = archetype_results.get("heating_systems", {}).get("percentages", {})
            summary.update(
                {
                    "belowBandC": float(round(below_c, 2)),
                    "gasBoilerDependency": float(heat_pct.get("Gas Boiler", 0)),
                    "meanSAPScore": float(
                        archetype_results.get("sap_scores", {}).get("mean", 0)
                    ),
                }
            )

        if pathway_summary is not None and len(pathway_summary) > 0:
            if "Property Count" in pathway_summary.columns and pathway_summary["Property Count"].sum() > 0:
                hp_tiers = pathway_summary[
                    pathway_summary["Recommended Pathway"].str.contains("Heat Pump", na=False)
                ]["Property Count"].sum()
                total = pathway_summary["Property Count"].sum()
                summary["dhViableProperties"] = int(total - hp_tiers)

        if scenario_results:
            first_scenario = next(iter(scenario_results.values()))
            summary["optimalInvestmentPoint"] = float(
                first_scenario.get("capital_cost_per_property", 0)
            )

        if df_validated is not None and len(df_validated) > 0:
            summary.setdefault("totalProperties", int(len(df_validated)))

        return summary
