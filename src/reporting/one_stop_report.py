"""
One-Stop Report Generator

Compiles all required sections (1-13) into a single JSON file by
extracting data from existing analysis outputs. This report is the
single definitive output artifact containing all analysis results.

All datapoints include comprehensive metadata:
- Human-readable name
- Machine-readable key (snake_case)
- Definition and unit
- Denominator
- Source output file and field
- Report usage sections
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
from loguru import logger

from config.config import DATA_OUTPUTS_DIR, DATA_PROCESSED_DIR, load_config


@dataclass
class AnnotatedDatapoint:
    """Structured datapoint with full metadata."""
    name: str
    key: str
    definition: str
    denominator: str
    source: str
    value: Any = None
    usage: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "key": self.key,
            "value": self._serialize_value(self.value),
            "definition": self.definition,
            "denominator": self.denominator,
            "source": self.source,
            "usage": self.usage or "General analysis",
        }

    def _serialize_value(self, value: Any) -> Any:
        """Serialize value for JSON output."""
        if value is None:
            return None
        if isinstance(value, float) and pd.isna(value):
            return None
        # Handle numpy/pandas numeric types
        if isinstance(value, (np.integer, np.int64, np.int32)):
            return int(value)
        if isinstance(value, (np.floating, np.float64, np.float32)):
            return float(value)
        if isinstance(value, np.bool_):
            return bool(value)
        if isinstance(value, (pd.Timestamp, datetime)):
            return value.isoformat()
        if isinstance(value, pd.Series):
            return value.to_dict()
        if isinstance(value, pd.DataFrame):
            return value.to_dict(orient="records")
        return value


def _snake_case(value: str) -> str:
    """Convert string to snake_case."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_")
    return cleaned.lower()


def _convert_numpy_types(obj: Any) -> Any:
    """Recursively convert numpy types to native Python types for JSON serialization."""
    if obj is None:
        return None
    if isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    if isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {key: _convert_numpy_types(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_convert_numpy_types(item) for item in obj]
    return obj


def _serialize_dataframe(df: pd.DataFrame, caption: str = "") -> Dict[str, Any]:
    """Serialize DataFrame to JSON-compatible dict."""
    if df is None or df.empty:
        return {"caption": caption, "data": []}

    # Convert DataFrame to dict and handle numpy types
    data_dict = df.to_dict(orient="records")
    converted_data = _convert_numpy_types(data_dict)

    return {
        "caption": caption,
        "columns": df.columns.tolist(),
        "data": converted_data
    }


def _read_json(path: Path) -> Dict[str, Any]:
    """Read JSON file safely."""
    if not path.exists():
        logger.debug(f"JSON file not found: {path}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.warning(f"Could not parse JSON from {path}: {exc}")
        return {}


def _read_csv(path: Path) -> Optional[pd.DataFrame]:
    """Read CSV file safely."""
    if not path.exists():
        logger.debug(f"CSV file not found: {path}")
        return None
    try:
        return pd.read_csv(path)
    except Exception as exc:
        logger.warning(f"Could not read CSV {path}: {exc}")
        return None


class OneStopReportGenerator:
    """
    Generate a comprehensive one-stop JSON report from analysis outputs.

    This report contains 13 sections with complete data extraction:
    1. Run metadata and provenance
    2. Dataset volumes and data quality
    3. Housing stock archetype characteristics
    4. Retrofit readiness (heat pump readiness and prerequisites)
    5. Spatial heat network classification
    6. Scenario modelling outputs
    7. Heat network vs heat pump comparison module
    8. Fabric tipping-point and cost-performance analysis
    9. Subsidy sensitivity analysis
    10. Borough-level breakdown and prioritisation
    11. Case street / exemplar outputs
    12. Uncertainty and sensitivity datapoints
    13. Structure of the one-stop output document
    """

    SECTION_TITLES = [
        "Section 1: Run Metadata and Provenance",
        "Section 2: Dataset Volumes and Data Quality",
        "Section 3: Housing Stock Archetype Characteristics",
        "Section 4: Retrofit Readiness (Heat Pump Readiness and Prerequisites)",
        "Section 5: Spatial Heat Network Classification",
        "Section 6: Scenario Modelling Outputs",
        "Section 7: Heat Network vs Heat Pump Comparison Module",
        "Section 8: Fabric Tipping-Point and Cost-Performance Analysis",
        "Section 9: Subsidy Sensitivity Analysis",
        "Section 10: Borough-Level Breakdown and Prioritisation",
        "Section 11: Case Street / Exemplar Outputs",
        "Section 12: Uncertainty and Sensitivity Datapoints",
        "Section 13: Structure of the One-Stop Output Document",
    ]

    def __init__(
        self,
        output_dir: Optional[Path] = None,
        processed_dir: Optional[Path] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.output_dir = Path(output_dir) if output_dir else DATA_OUTPUTS_DIR
        self.processed_dir = Path(processed_dir) if processed_dir else DATA_PROCESSED_DIR
        self.config = config or load_config()
        self.output_path = self.output_dir / "one_stop_output.json"
        self._sections: Dict[str, Any] = {}

    def generate(self) -> Path:
        """Generate the complete one-stop JSON report."""
        logger.info("Generating comprehensive one-stop JSON report...")

        # Load all data sources
        run_metadata = _read_json(self.output_dir / "run_metadata.json")
        validation_report = _read_json(self.processed_dir / "validation_report.json")
        adjustment_summary = _read_json(self.processed_dir / "methodological_adjustments_summary.json")
        archetype_json = _read_json(self.output_dir / "archetype_analysis_results.json")
        readiness_df = _read_csv(self.output_dir / "retrofit_readiness_analysis.csv")
        scenario_df = _read_csv(self.output_dir / "scenario_results_summary.csv")
        spatial_tier_df = _read_csv(self.output_dir / "pathway_suitability_by_tier.csv")
        hn_vs_hp_df = _read_csv(self.output_dir / "comparisons" / "hn_vs_hp_comparison.csv")
        tipping_point_df = _read_csv(self.output_dir / "fabric_tipping_point_curve.csv")
        subsidy_df = _read_csv(self.output_dir / "subsidy_sensitivity_analysis.csv")
        borough_df = _read_csv(self.output_dir / "borough_breakdown.csv")
        case_street_df = _read_csv(self.output_dir / "shakespeare_crescent_extract.csv")

        # Build all 13 sections
        self._sections["section_1"] = self._build_section_1(run_metadata)
        self._sections["section_2"] = self._build_section_2(validation_report, adjustment_summary)
        self._sections["section_3"] = self._build_section_3(archetype_json)
        self._sections["section_4"] = self._build_section_4(readiness_df)
        self._sections["section_5"] = self._build_section_5(spatial_tier_df)
        self._sections["section_6"] = self._build_section_6(scenario_df)
        self._sections["section_7"] = self._build_section_7(hn_vs_hp_df)
        self._sections["section_8"] = self._build_section_8(tipping_point_df)
        self._sections["section_9"] = self._build_section_9(subsidy_df)
        self._sections["section_10"] = self._build_section_10(borough_df)
        self._sections["section_11"] = self._build_section_11(case_street_df)
        self._sections["section_12"] = self._build_section_12(adjustment_summary)
        self._sections["section_13"] = self._build_section_13()

        # Build final JSON structure
        output = {
            "metadata": {
                "title": "Heat Street — One-Stop Report",
                "subtitle": "Low-Carbon Heating Potential for London's Edwardian Terraced Housing",
                "generated": datetime.now().isoformat(),
                "version": "2.0"
            },
            "sections": self._sections
        }

        # Convert any remaining numpy types before JSON serialization
        output = _convert_numpy_types(output)

        # Write output
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

        total_datapoints = sum(len(s.get("datapoints", [])) for s in self._sections.values())
        logger.info(f"One-stop JSON report written to {self.output_path}")
        logger.info(f"Total datapoints: {total_datapoints}")
        return self.output_path

    def _render_section(
        self,
        title: str,
        datapoints: Iterable[AnnotatedDatapoint],
        tables: Optional[List[Tuple[pd.DataFrame, str]]] = None
    ) -> Dict[str, Any]:
        """Render a section as a JSON-compatible dictionary."""
        datapoints_list = list(datapoints)

        section = {
            "title": title,
            "datapoints": [dp.to_dict() for dp in datapoints_list],
            "tables": []
        }

        if tables:
            for df, caption in tables:
                section["tables"].append(_serialize_dataframe(df, caption))

        return section

    def _build_section_1(self, run_metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Section 1: Run metadata and provenance."""
        datapoints = [
            AnnotatedDatapoint(
                name="Run identifier",
                key="run_identifier",
                value=run_metadata.get("run_id", "Not available"),
                definition="Unique ID or timestamp for this analysis run (string).",
                denominator="N/A",
                source="data/outputs/run_metadata.json -> run_id",
                usage="Provenance and version control",
            ),
            AnnotatedDatapoint(
                name="Analysis start time",
                key="analysis_start_time",
                value=run_metadata.get("start_time", "Not available"),
                definition="Timestamp when analysis started (ISO format).",
                denominator="N/A",
                source="data/outputs/run_metadata.json -> start_time",
                usage="Provenance and version control",
            ),
            AnnotatedDatapoint(
                name="Analysis end time",
                key="analysis_end_time",
                value=run_metadata.get("end_time", "Not available"),
                definition="Timestamp when analysis completed (ISO format).",
                denominator="N/A",
                source="data/outputs/run_metadata.json -> end_time",
                usage="Provenance and version control",
            ),
            AnnotatedDatapoint(
                name="Total runtime",
                key="total_runtime_seconds",
                value=run_metadata.get("runtime_seconds", "Not available"),
                definition="Total elapsed time for analysis (seconds).",
                denominator="N/A",
                source="data/outputs/run_metadata.json -> runtime_seconds",
                usage="Performance monitoring",
            ),
            AnnotatedDatapoint(
                name="Analysis scope / archetype label",
                key="archetype_label",
                value="London Edwardian Terraced Housing",
                definition="Archetype being analyzed (text label).",
                denominator="N/A",
                source="Configuration / run definition",
                usage="Report context",
            ),
            AnnotatedDatapoint(
                name="Primary data source(s)",
                key="primary_data_sources",
                value="EPC API (UK Government Open Data)",
                definition="Primary data sources used for analysis (text).",
                denominator="N/A",
                source="Configuration / run definition",
                usage="Data provenance",
            ),
            AnnotatedDatapoint(
                name="Key configuration snapshot - Energy prices",
                key="config_energy_prices",
                value=self.config.get("energy_prices", {}).get("current", {}),
                definition="Energy prices used in analysis (£/kWh for gas and electricity).",
                denominator="N/A",
                source="config/config.yaml -> energy_prices.current",
                usage="Financial calculations",
            ),
            AnnotatedDatapoint(
                name="Key configuration snapshot - Heat pump COP",
                key="config_heat_pump_scop",
                value=self.config.get("heat_pump", {}).get("scop", "Not available"),
                definition="Seasonal Coefficient of Performance for heat pumps (dimensionless).",
                denominator="N/A",
                source="config/config.yaml -> heat_pump.scop",
                usage="Heat pump performance calculations",
            ),
            AnnotatedDatapoint(
                name="Key configuration snapshot - Appraisal horizon",
                key="config_appraisal_horizon_years",
                value=self.config.get("financial", {}).get("analysis_horizon_years", "Not available"),
                definition="Project lifetime for NPV calculations (years).",
                denominator="N/A",
                source="config/config.yaml -> financial.analysis_horizon_years",
                usage="Financial appraisal",
            ),
            AnnotatedDatapoint(
                name="Key configuration snapshot - EPC recency filter",
                key="config_epc_recency_years",
                value=self.config.get("property_filters", {}).get("certificate_recency_years", "Not available"),
                definition="Maximum age of EPC certificates included in analysis (years).",
                denominator="N/A",
                source="config/config.yaml -> property_filters.certificate_recency_years",
                usage="Data quality filtering",
            ),
        ]
        return self._render_section(self.SECTION_TITLES[0], datapoints)

    def _build_section_2(self, validation_report: Dict[str, Any], adjustment_summary: Dict[str, Any]) -> Dict[str, Any]:
        """Section 2: Dataset volumes and data quality."""
        total_raw = validation_report.get("total_records", 0)
        duplicates = validation_report.get("duplicates_removed", 0)
        invalid = validation_report.get("invalid_records", 0)
        final_count = total_raw - duplicates - invalid

        datapoints = [
            AnnotatedDatapoint(
                name="Total raw records loaded",
                key="total_raw_records",
                value=total_raw,
                definition="Total records downloaded from EPC API before any filtering (count).",
                denominator="All downloaded records",
                source="data/processed/validation_report.json -> total_records",
                usage="Data volume context",
            ),
            AnnotatedDatapoint(
                name="Records passing validation (final analytic dataset size)",
                key="records_passing_validation",
                value=final_count,
                definition="Records remaining after validation and deduplication (count).",
                denominator="Total raw records",
                source="data/processed/validation_report.json -> calculated (total - duplicates - invalid)",
                usage="Final dataset size",
            ),
            AnnotatedDatapoint(
                name="Records excluded",
                key="records_excluded_total",
                value=duplicates + invalid,
                definition="Total records removed during validation (count).",
                denominator="Total raw records",
                source="data/processed/validation_report.json -> duplicates_removed + invalid_records",
                usage="Data quality assessment",
            ),
            AnnotatedDatapoint(
                name="Exclusion reasons - Duplicates",
                key="duplicates_removed",
                value=duplicates,
                definition="Duplicate records removed (count).",
                denominator="Total raw records",
                source="data/processed/validation_report.json -> duplicates_removed",
                usage="Data quality assessment",
            ),
            AnnotatedDatapoint(
                name="Exclusion reasons - Invalid records",
                key="invalid_records",
                value=invalid,
                definition="Records failing validation checks (count).",
                denominator="Total raw records",
                source="data/processed/validation_report.json -> invalid_records",
                usage="Data quality assessment",
            ),
            AnnotatedDatapoint(
                name="Exclusion reasons - Negative energy values",
                key="negative_energy_values",
                value=validation_report.get("negative_energy_values", 0),
                definition="Records with negative ENERGY_CONSUMPTION_CURRENT flagged (count).",
                denominator="Total raw records",
                source="data/processed/validation_report.json -> negative_energy_values",
                usage="Data anomaly detection",
            ),
            AnnotatedDatapoint(
                name="Exclusion reasons - Negative CO2 values",
                key="negative_co2_values",
                value=validation_report.get("negative_co2_values", 0),
                definition="Records with negative CO2_EMISSIONS_CURRENT flagged (count).",
                denominator="Total raw records",
                source="data/processed/validation_report.json -> negative_co2_values",
                usage="Data anomaly detection",
            ),
            AnnotatedDatapoint(
                name="Methodological adjustments - Prebound effect applied",
                key="prebound_adjustment_applied",
                value=adjustment_summary.get("prebound_adjustment", {}).get("applied", False),
                definition="Whether prebound effect correction was applied (boolean).",
                denominator="N/A",
                source="data/processed/methodological_adjustments_summary.json -> prebound_adjustment.applied",
                usage="Methodological transparency",
            ),
            AnnotatedDatapoint(
                name="Methodological adjustments - Prebound properties adjusted",
                key="prebound_properties_adjusted",
                value=adjustment_summary.get("prebound_adjustment", {}).get("properties_adjusted", 0),
                definition="Count of properties with prebound adjustment applied (count).",
                denominator="Final validated records",
                source="data/processed/methodological_adjustments_summary.json -> prebound_adjustment.properties_adjusted",
                usage="Adjustment coverage",
            ),
            AnnotatedDatapoint(
                name="Methodological adjustments - Flow temperature model applied",
                key="flow_temperature_model_applied",
                value=adjustment_summary.get("flow_temperature", {}).get("applied", False),
                definition="Whether flow temperature estimation was applied (boolean).",
                denominator="N/A",
                source="data/processed/methodological_adjustments_summary.json -> flow_temperature.applied",
                usage="Methodological transparency",
            ),
            AnnotatedDatapoint(
                name="Methodological adjustments - Uncertainty bounds applied",
                key="uncertainty_bounds_applied",
                value=adjustment_summary.get("uncertainty", {}).get("applied", False),
                definition="Whether measurement uncertainty ranges were calculated (boolean).",
                denominator="N/A",
                source="data/processed/methodological_adjustments_summary.json -> uncertainty.applied",
                usage="Methodological transparency",
            ),
        ]
        return self._render_section(self.SECTION_TITLES[1], datapoints)

    def _build_section_3(self, archetype_json: Dict[str, Any]) -> Dict[str, Any]:
        """Section 3: Housing stock archetype characteristics."""
        epc_bands = archetype_json.get("epc_bands", {})
        sap_scores = archetype_json.get("sap_scores", {})
        wall_data = archetype_json.get("wall_construction", {})
        loft_data = archetype_json.get("loft_insulation", {})
        glazing_data = archetype_json.get("glazing", {})
        heating_data = archetype_json.get("heating_systems", {})

        datapoints = [
            AnnotatedDatapoint(
                name="EPC band distribution",
                key="epc_band_distribution",
                value=epc_bands.get("frequency", {}),
                definition="EPC band distribution with counts by band (dict: {band: count}).",
                denominator="All properties in archetype analysis",
                source="data/outputs/archetype_analysis_results.json -> epc_bands.frequency",
                usage="Baseline EPC profiling",
            ),
            AnnotatedDatapoint(
                name="EPC band percentages",
                key="epc_band_percentages",
                value=epc_bands.get("percentage", {}),
                definition="EPC band distribution with percentages by band (dict: {band: %}).",
                denominator="All properties in archetype analysis",
                source="data/outputs/archetype_analysis_results.json -> epc_bands.percentage",
                usage="Baseline EPC profiling",
            ),
            AnnotatedDatapoint(
                name="SAP score mean",
                key="sap_score_mean",
                value=sap_scores.get("mean"),
                definition="Mean SAP score across all properties (score, 1-100 scale).",
                denominator="All properties in archetype analysis",
                source="data/outputs/archetype_analysis_results.json -> sap_scores.mean",
                usage="Energy efficiency baseline",
            ),
            AnnotatedDatapoint(
                name="SAP score median",
                key="sap_score_median",
                value=sap_scores.get("median"),
                definition="Median SAP score across all properties (score, 1-100 scale).",
                denominator="All properties in archetype analysis",
                source="data/outputs/archetype_analysis_results.json -> sap_scores.median",
                usage="Energy efficiency baseline",
            ),
            AnnotatedDatapoint(
                name="SAP score range (min)",
                key="sap_score_min",
                value=sap_scores.get("min"),
                definition="Minimum SAP score observed (score, 1-100 scale).",
                denominator="All properties in archetype analysis",
                source="data/outputs/archetype_analysis_results.json -> sap_scores.min",
                usage="Energy efficiency spread",
            ),
            AnnotatedDatapoint(
                name="SAP score range (max)",
                key="sap_score_max",
                value=sap_scores.get("max"),
                definition="Maximum SAP score observed (score, 1-100 scale).",
                denominator="All properties in archetype analysis",
                source="data/outputs/archetype_analysis_results.json -> sap_scores.max",
                usage="Energy efficiency spread",
            ),
            AnnotatedDatapoint(
                name="Wall type distribution",
                key="wall_type_distribution",
                value=wall_data.get("wall_types", {}),
                definition="Wall construction type counts (dict: {type: count}).",
                denominator="All properties in archetype analysis",
                source="data/outputs/archetype_analysis_results.json -> wall_construction.wall_types",
                usage="Fabric typology",
            ),
            AnnotatedDatapoint(
                name="Wall insulation rate",
                key="wall_insulation_rate_pct",
                value=wall_data.get("insulation_rate"),
                definition="Share of properties with insulated walls (percent).",
                denominator="All properties in archetype analysis",
                source="data/outputs/archetype_analysis_results.json -> wall_construction.insulation_rate",
                usage="Fabric upgrade targeting",
            ),
            AnnotatedDatapoint(
                name="Loft/roof insulation status distribution",
                key="loft_status_distribution",
                value=loft_data.get("categories", {}),
                definition="Loft insulation categories and counts (dict).",
                denominator="All properties in archetype analysis",
                source="data/outputs/archetype_analysis_results.json -> loft_insulation.categories",
                usage="Roof retrofit readiness",
            ),
            AnnotatedDatapoint(
                name="Glazing type distribution",
                key="glazing_distribution",
                value=glazing_data.get("types", {}),
                definition="Window glazing types and counts (dict: {type: count}).",
                denominator="All properties in archetype analysis",
                source="data/outputs/archetype_analysis_results.json -> glazing.types",
                usage="Window upgrade planning",
            ),
            AnnotatedDatapoint(
                name="Heating system distribution",
                key="heating_system_distribution",
                value=heating_data.get("types", {}),
                definition="Primary heating system types and counts (dict: {type: count}).",
                denominator="All properties in archetype analysis",
                source="data/outputs/archetype_analysis_results.json -> heating_systems.types",
                usage="Heating system baseline",
            ),
            AnnotatedDatapoint(
                name="District/communal/heat network heating prevalence (count)",
                key="district_heating_count",
                value=heating_data.get("types", {}).get("District/Communal/Heat Network", 0),
                definition="Explicit count of properties on district/communal/heat network heating (count).",
                denominator="All properties in archetype analysis",
                source="data/outputs/archetype_analysis_results.json -> heating_systems.types['District/Communal/Heat Network']",
                usage="Existing heat network baseline",
            ),
            AnnotatedDatapoint(
                name="District/communal/heat network heating prevalence (%)",
                key="district_heating_pct",
                value=heating_data.get("percentages", {}).get("District/Communal/Heat Network", 0),
                definition="Share of properties on district/communal/heat network heating (percent).",
                denominator="All properties in archetype analysis",
                source="data/outputs/archetype_analysis_results.json -> heating_systems.percentages['District/Communal/Heat Network']",
                usage="Existing heat network baseline",
            ),
        ]
        return self._render_section(self.SECTION_TITLES[2], datapoints)

    def _build_section_4(self, readiness_df: Optional[pd.DataFrame]) -> Dict[str, Any]:
        """Section 4: Retrofit readiness (heat pump readiness and prerequisites)."""
        if readiness_df is None or readiness_df.empty:
            return self._render_section(self.SECTION_TITLES[3], [])

        total_properties = len(readiness_df)
        tier_counts = readiness_df["hp_readiness_tier"].value_counts().sort_index() if "hp_readiness_tier" in readiness_df.columns else pd.Series(dtype=int)
        tier_1_count = tier_counts.get(1, 0)
        non_ready_count = total_properties - tier_1_count

        datapoints = [
            AnnotatedDatapoint(
                name="Total properties assessed",
                key="readiness_total_properties",
                value=total_properties,
                definition="Total properties in retrofit readiness assessment (count).",
                denominator="All properties assessed for readiness",
                source="data/outputs/retrofit_readiness_analysis.csv -> row count",
                usage="Readiness cohort size",
            ),
        ]

        # Tier distribution
        for tier in range(1, 6):
            count = tier_counts.get(tier, 0)
            pct = (count / total_properties * 100) if total_properties > 0 else 0
            tier_names = {
                1: "Ready now (Tier 1)",
                2: "Minor work required (Tier 2)",
                3: "Major work required (Tier 3)",
                4: "Challenging (Tier 4)",
                5: "Not suitable (Tier 5)",
            }
            datapoints.append(AnnotatedDatapoint(
                name=f"Readiness tier distribution - {tier_names[tier]}",
                key=f"tier_{tier}_count",
                value=count,
                definition=f"Properties in {tier_names[tier]} (count).",
                denominator="Total properties assessed",
                source=f"data/outputs/retrofit_readiness_analysis.csv -> hp_readiness_tier == {tier}",
                usage="Readiness tier breakdown",
            ))
            datapoints.append(AnnotatedDatapoint(
                name=f"Readiness tier distribution - {tier_names[tier]} (%)",
                key=f"tier_{tier}_pct",
                value=pct,
                definition=f"Share of properties in {tier_names[tier]} (percent).",
                denominator="Total properties assessed",
                source=f"data/outputs/retrofit_readiness_analysis.csv -> hp_readiness_tier == {tier}",
                usage="Readiness tier breakdown",
            ))

        # Costs
        if "fabric_prerequisite_cost" in readiness_df.columns:
            datapoints.extend([
                AnnotatedDatapoint(
                    name="Mean fabric prerequisite cost",
                    key="mean_fabric_prerequisite_cost_gbp",
                    value=readiness_df["fabric_prerequisite_cost"].mean(),
                    definition="Average fabric prerequisite cost before heat pump readiness (GBP per property).",
                    denominator="All properties assessed",
                    source="data/outputs/retrofit_readiness_analysis.csv -> fabric_prerequisite_cost.mean()",
                    usage="Retrofit package economics",
                ),
                AnnotatedDatapoint(
                    name="Median fabric prerequisite cost",
                    key="median_fabric_prerequisite_cost_gbp",
                    value=readiness_df["fabric_prerequisite_cost"].median(),
                    definition="Median fabric prerequisite cost before heat pump readiness (GBP per property).",
                    denominator="All properties assessed",
                    source="data/outputs/retrofit_readiness_analysis.csv -> fabric_prerequisite_cost.median()",
                    usage="Retrofit package economics",
                ),
                AnnotatedDatapoint(
                    name="Total fabric prerequisite cost",
                    key="total_fabric_prerequisite_cost_gbp",
                    value=readiness_df["fabric_prerequisite_cost"].sum(),
                    definition="Total fabric prerequisite cost across all properties (GBP).",
                    denominator="All properties assessed",
                    source="data/outputs/retrofit_readiness_analysis.csv -> fabric_prerequisite_cost.sum()",
                    usage="Capital requirement",
                ),
            ])

        if "total_retrofit_cost" in readiness_df.columns:
            datapoints.extend([
                AnnotatedDatapoint(
                    name="Mean total retrofit cost",
                    key="mean_total_retrofit_cost_gbp",
                    value=readiness_df["total_retrofit_cost"].mean(),
                    definition="Average total retrofit cost including heat pump measures (GBP per property).",
                    denominator="All properties assessed",
                    source="data/outputs/retrofit_readiness_analysis.csv -> total_retrofit_cost.mean()",
                    usage="Retrofit package economics",
                ),
                AnnotatedDatapoint(
                    name="Median total retrofit cost",
                    key="median_total_retrofit_cost_gbp",
                    value=readiness_df["total_retrofit_cost"].median(),
                    definition="Median total retrofit cost including heat pump measures (GBP per property).",
                    denominator="All properties assessed",
                    source="data/outputs/retrofit_readiness_analysis.csv -> total_retrofit_cost.median()",
                    usage="Retrofit package economics",
                ),
                AnnotatedDatapoint(
                    name="Total retrofit cost",
                    key="total_retrofit_cost_gbp",
                    value=readiness_df["total_retrofit_cost"].sum(),
                    definition="Total retrofit cost across all properties (GBP).",
                    denominator="All properties assessed",
                    source="data/outputs/retrofit_readiness_analysis.csv -> total_retrofit_cost.sum()",
                    usage="Capital requirement",
                ),
            ])

        # Intervention requirements
        measures = {
            "needs_loft_topup": ("loft insulation", "Loft insulation top-up"),
            "needs_wall_insulation": ("wall insulation", "Wall insulation"),
            "needs_glazing_upgrade": ("glazing upgrade", "Glazing upgrade"),
            "needs_radiator_upsizing": ("radiator upsizing", "Radiator/emitter upsizing"),
        }

        for col, (measure, label) in measures.items():
            if col in readiness_df.columns:
                count = int(readiness_df[col].sum())
                # BUG FIX: Filter count to only include non-ready properties (Tier 2-5)
                # to prevent percentages exceeding 100%
                count_non_ready = int(readiness_df[readiness_df["hp_readiness_tier"] > 1][col].sum()) if "hp_readiness_tier" in readiness_df.columns else count
                pct_all = (count / total_properties * 100) if total_properties > 0 else 0
                pct_non_ready = (count_non_ready / non_ready_count * 100) if non_ready_count > 0 else 0

                datapoints.extend([
                    AnnotatedDatapoint(
                        name=f"Properties needing {measure} (count)",
                        key=f"{_snake_case(measure)}_count",
                        value=count,
                        definition=f"Count of properties needing {measure} (count).",
                        denominator="All properties assessed",
                        source=f"data/outputs/retrofit_readiness_analysis.csv -> {col}.sum()",
                        usage="Fabric intervention scope",
                    ),
                    AnnotatedDatapoint(
                        name=f"Properties needing {measure} (% of all)",
                        key=f"{_snake_case(measure)}_pct_all",
                        value=pct_all,
                        definition=f"Share of properties needing {measure} (percent of all).",
                        denominator="All properties assessed",
                        source=f"data/outputs/retrofit_readiness_analysis.csv -> {col}.sum() / total",
                        usage="Fabric intervention share",
                    ),
                    AnnotatedDatapoint(
                        name=f"Properties needing {measure} (% of non-ready)",
                        key=f"{_snake_case(measure)}_pct_non_ready",
                        value=pct_non_ready,
                        definition=f"Share of non-ready properties needing {measure} (percent of non-ready).",
                        denominator="Non-ready properties (Tier 2-5)",
                        source=f"data/outputs/retrofit_readiness_analysis.csv -> {col}[hp_readiness_tier > 1].sum() / (total - tier_1)",
                        usage="Fabric intervention share (non-ready)",
                    ),
                ])

        # Wall insulation split
        if "wall_insulation_type" in readiness_df.columns:
            solid_count = int((readiness_df["wall_insulation_type"] == "solid_wall_ewi").sum())
            cavity_count = int((readiness_df["wall_insulation_type"] == "cavity_wall").sum())
            datapoints.extend([
                AnnotatedDatapoint(
                    name="Solid wall insulation needs",
                    key="needs_solid_wall_insulation",
                    value=solid_count,
                    definition="Count of properties needing solid wall insulation (count).",
                    denominator="Properties needing wall insulation",
                    source="data/outputs/retrofit_readiness_analysis.csv -> wall_insulation_type == 'solid_wall_ewi'",
                    usage="Wall insulation targeting",
                ),
                AnnotatedDatapoint(
                    name="Cavity wall insulation needs",
                    key="needs_cavity_wall_insulation",
                    value=cavity_count,
                    definition="Count of properties needing cavity wall insulation (count).",
                    denominator="Properties needing wall insulation",
                    source="data/outputs/retrofit_readiness_analysis.csv -> wall_insulation_type == 'cavity_wall'",
                    usage="Wall insulation targeting",
                ),
            ])

        return self._render_section(self.SECTION_TITLES[3], datapoints)

    def _build_section_5(self, spatial_tier_df: Optional[pd.DataFrame]) -> Dict[str, Any]:
        """Section 5: Spatial heat network classification."""
        if spatial_tier_df is None or spatial_tier_df.empty:
            datapoints = [
                AnnotatedDatapoint(
                    name="Spatial analysis status",
                    key="spatial_analysis_status",
                    value="Not run (GDAL not available or analysis skipped)",
                    definition="Status of spatial heat network tier classification (text).",
                    denominator="N/A",
                    source="Spatial analysis phase",
                    usage="Spatial classification availability",
                )
            ]
            return self._render_section(self.SECTION_TITLES[4], datapoints)

        total_geocoded = spatial_tier_df["Property Count"].sum() if "Property Count" in spatial_tier_df.columns else 0

        datapoints = [
            AnnotatedDatapoint(
                name="Properties successfully geocoded / spatially classified",
                key="properties_geocoded",
                value=total_geocoded,
                definition="Total properties with successful geocoding and heat network tier assignment (count).",
                denominator="All properties in dataset",
                source="data/outputs/pathway_suitability_by_tier.csv -> Property Count.sum()",
                usage="Spatial classification coverage",
            ),
        ]

        # Extract tier-specific data
        tier_mapping = {
            "Tier 1": ("tier_1", "Adjacent to existing network"),
            "Tier 2": ("tier_2", "Within heat network zone"),
            "Tier 3": ("tier_3", "High heat density"),
            "Tier 4": ("tier_4", "Medium heat density"),
            "Tier 5": ("tier_5", "Low heat density"),
        }

        for tier_label, (tier_key, tier_desc) in tier_mapping.items():
            tier_row = spatial_tier_df[spatial_tier_df["Tier"].str.startswith(tier_label)] if "Tier" in spatial_tier_df.columns else pd.DataFrame()
            if not tier_row.empty:
                count = tier_row["Property Count"].iloc[0] if "Property Count" in tier_row.columns else 0
                pct = tier_row["Percentage"].iloc[0] if "Percentage" in tier_row.columns else 0
                pathway = tier_row["Recommended Pathway"].iloc[0] if "Recommended Pathway" in tier_row.columns else "Unknown"

                datapoints.extend([
                    AnnotatedDatapoint(
                        name=f"Heat network tier distribution - {tier_desc} (count)",
                        key=f"{tier_key}_count",
                        value=count,
                        definition=f"Properties in {tier_desc} classification (count).",
                        denominator="Properties successfully geocoded",
                        source=f"data/outputs/pathway_suitability_by_tier.csv -> Tier == '{tier_label}'",
                        usage="Tier distribution",
                    ),
                    AnnotatedDatapoint(
                        name=f"Heat network tier distribution - {tier_desc} (%)",
                        key=f"{tier_key}_pct",
                        value=pct,
                        definition=f"Share of properties in {tier_desc} classification (percent).",
                        denominator="Properties successfully geocoded",
                        source=f"data/outputs/pathway_suitability_by_tier.csv -> Tier == '{tier_label}'",
                        usage="Tier distribution",
                    ),
                    AnnotatedDatapoint(
                        name=f"Heat network tier - {tier_desc} recommended pathway",
                        key=f"{tier_key}_recommended_pathway",
                        value=pathway,
                        definition=f"Recommended decarbonization pathway for {tier_desc} properties (text).",
                        denominator="N/A",
                        source=f"data/outputs/pathway_suitability_by_tier.csv -> Recommended Pathway for Tier '{tier_label}'",
                        usage="Pathway allocation logic",
                    ),
                ])

        # Include the full tier table
        tables = [(spatial_tier_df, "Heat Network Tier Classification Summary")]

        return self._render_section(self.SECTION_TITLES[4], datapoints, tables=tables)

    def _build_section_6(self, scenario_df: Optional[pd.DataFrame]) -> Dict[str, Any]:
        """Section 6: Scenario modelling outputs."""
        if scenario_df is None or scenario_df.empty:
            return self._render_section(self.SECTION_TITLES[5], [])

        datapoints = []

        # Process each scenario
        for _, row in scenario_df.iterrows():
            scenario_id = row.get("scenario_id", row.get("scenario", "unknown"))
            scenario_label = row.get("scenario", scenario_id)
            scenario_suffix = _snake_case(str(scenario_label))

            # Determine if baseline or hybrid
            is_baseline = any(hint in str(scenario_label).lower() for hint in ["baseline", "no_intervention", "no intervention"])
            is_hybrid = "hybrid" in str(scenario_label).lower()

            # Core metrics (always present)
            core_metrics = {
                "scenario_id": ("Scenario ID", f"Scenario identifier: {scenario_label} (string).", "N/A"),
                "total_properties": ("Total properties", "Total properties modeled in scenario (count).", "All properties in scenario"),
                "capital_cost_total": ("Capital cost total", "Total capital expenditure for scenario (GBP).", "All properties in scenario"),
                "capital_cost_per_property": ("Capital cost per property (mean)", "Average capital expenditure per property (GBP).", "All properties in scenario"),
                "annual_energy_reduction_kwh": ("Annual energy reduction", "Total annual energy reduction (kWh).", "All properties in scenario"),
                "annual_co2_reduction_kg": ("Annual CO2 reduction", "Total annual CO₂ reduction (kg).", "All properties in scenario"),
                "annual_bill_savings": ("Annual bill savings", "Total annual bill savings (GBP).", "All properties in scenario"),
                "baseline_bill_total": ("Baseline bill total", "Baseline annual bill total before measures (GBP).", "All properties in scenario"),
                "post_measure_bill_total": ("Post-measure bill total", "Post-measure annual bill total (GBP).", "All properties in scenario"),
                "baseline_co2_total_kg": ("Baseline CO2 total", "Baseline annual CO₂ total before measures (kg).", "All properties in scenario"),
                "post_measure_co2_total_kg": ("Post-measure CO2 total", "Post-measure annual CO₂ total (kg).", "All properties in scenario"),
            }

            for field, (label, definition, denominator) in core_metrics.items():
                value = row.get(field)
                if value is not None and not (isinstance(value, float) and pd.isna(value)):
                    datapoints.append(AnnotatedDatapoint(
                        name=f"{label} ({scenario_label})",
                        key=f"{field}_{scenario_suffix}",
                        value=value,
                        definition=definition,
                        denominator=denominator,
                        source=f"data/outputs/scenario_results_summary.csv -> {field} for scenario '{scenario_label}'",
                        usage=f"Scenario {scenario_label} results",
                    ))

            # Heat pump electricity (if not baseline)
            if not is_baseline:
                hp_elec_fields = {
                    "heat_pump_electricity_total_kwh": "Heat pump electricity total",
                    "heat_pump_electricity_total_kwh_low": "Heat pump electricity (low estimate)",
                    "heat_pump_electricity_total_kwh_high": "Heat pump electricity (high estimate)",
                }
                for field, label in hp_elec_fields.items():
                    value = row.get(field)
                    if value is not None and not (isinstance(value, float) and pd.isna(value)):
                        datapoints.append(AnnotatedDatapoint(
                            name=f"{label} ({scenario_label})",
                            key=f"{field}_{scenario_suffix}",
                            value=value,
                            definition=f"{label} consumption (kWh).",
                            denominator="Properties with heat pumps",
                            source=f"data/outputs/scenario_results_summary.csv -> {field}",
                            usage=f"Scenario {scenario_label} HP electricity demand",
                        ))

            # Payback metrics (if not baseline)
            if not is_baseline:
                payback_fields = {
                    "average_payback_years": "Average payback years",
                    "median_payback_years": "Median payback years",
                }
                for field, label in payback_fields.items():
                    value = row.get(field)
                    if value is not None and not (isinstance(value, float) and pd.isna(value)):
                        datapoints.append(AnnotatedDatapoint(
                            name=f"{label} ({scenario_label})",
                            key=f"{field}_{scenario_suffix}",
                            value=value,
                            definition=f"{label} for cost-effective homes (years).",
                            denominator="Cost-effective properties in scenario",
                            source=f"data/outputs/scenario_results_summary.csv -> {field}",
                            usage=f"Scenario {scenario_label} payback analysis",
                        ))

            # Cost-effectiveness metrics (if not baseline)
            if not is_baseline:
                # BUG FIX: Add marginal_count to explain the gap between cost_effective + not_cost_effective and total
                ce_fields = {
                    "cost_effective_count": ("Cost-effective properties (count)", "Count of cost-effective properties (payback ≤15 years) (count).", "All properties in scenario"),
                    "cost_effective_pct": ("Cost-effective properties (%)", "Share of cost-effective properties (payback ≤15 years) (percent).", "All properties in scenario"),
                    "marginal_count": ("Marginally cost-effective properties (count)", "Count of marginally cost-effective properties (payback 15-25 years) (count).", "All properties in scenario"),
                    "marginal_pct": ("Marginally cost-effective properties (%)", "Share of marginally cost-effective properties (payback 15-25 years) (percent).", "All properties in scenario"),
                    "not_cost_effective_count": ("Not cost-effective (count)", "Count of non cost-effective properties (payback >25 years or no savings) (count).", "All properties in scenario"),
                    "not_cost_effective_pct": ("Not cost-effective (%)", "Share of non cost-effective properties (payback >25 years or no savings) (percent).", "All properties in scenario"),
                    "carbon_abatement_cost_mean": ("Carbon abatement cost (mean)", "Mean carbon abatement cost (GBP/tCO₂).", "Cost-effective properties"),
                    "carbon_abatement_cost_median": ("Carbon abatement cost (median)", "Median carbon abatement cost (GBP/tCO₂).", "Cost-effective properties"),
                }
                for field, (label, definition, denominator) in ce_fields.items():
                    value = row.get(field)
                    if value is not None and not (isinstance(value, float) and pd.isna(value)):
                        datapoints.append(AnnotatedDatapoint(
                            name=f"{label} ({scenario_label})",
                            key=f"{field}_{scenario_suffix}",
                            value=value,
                            definition=definition,
                            denominator=denominator,
                            source=f"data/outputs/scenario_results_summary.csv -> {field}",
                            usage=f"Scenario {scenario_label} cost-effectiveness",
                        ))

            # EPC band shift
            epc_fields = {
                "band_c_or_better_before_pct": "EPC Band C+ before (%)",
                "band_c_or_better_after_pct": "EPC Band C+ after (%)",
            }
            for field, label in epc_fields.items():
                value = row.get(field)
                if value is not None and not (isinstance(value, float) and pd.isna(value)):
                    datapoints.append(AnnotatedDatapoint(
                        name=f"{label} ({scenario_label})",
                        key=f"{field}_{scenario_suffix}",
                        value=value,
                        definition=f"{label} intervention (percent).",
                        denominator="All properties in scenario",
                        source=f"data/outputs/scenario_results_summary.csv -> {field}",
                        usage=f"Scenario {scenario_label} EPC shift",
                    ))

            # ASHP readiness (if not baseline)
            if not is_baseline:
                ashp_fields = {
                    "ashp_ready_properties": "ASHP-ready properties",
                    "ashp_fabric_required_properties": "ASHP fabric required",
                    "ashp_not_ready_properties": "ASHP not suitable",
                }
                for field, label in ashp_fields.items():
                    value = row.get(field)
                    if value is not None and not (isinstance(value, float) and pd.isna(value)):
                        datapoints.append(AnnotatedDatapoint(
                            name=f"{label} ({scenario_label})",
                            key=f"{field}_{scenario_suffix}",
                            value=value,
                            definition=f"{label} (count).",
                            denominator="All properties in scenario",
                            source=f"data/outputs/scenario_results_summary.csv -> {field}",
                            usage=f"Scenario {scenario_label} HP readiness",
                        ))

            # Hybrid allocation (hybrid scenarios only)
            if is_hybrid:
                hybrid_fields = {
                    "hn_assigned_properties": "Heat network allocation",
                    "ashp_assigned_properties": "ASHP allocation",
                }
                for field, label in hybrid_fields.items():
                    value = row.get(field)
                    if value is not None and not (isinstance(value, float) and pd.isna(value)):
                        datapoints.append(AnnotatedDatapoint(
                            name=f"{label} ({scenario_label})",
                            key=f"{field}_{scenario_suffix}",
                            value=value,
                            definition=f"Properties assigned to {label.lower()} in hybrid scenario (count).",
                            denominator="All properties in scenario",
                            source=f"data/outputs/scenario_results_summary.csv -> {field}",
                            usage=f"Scenario {scenario_label} hybrid routing",
                        ))

        # Include full scenario summary table
        tables = [(scenario_df, "Complete Scenario Results Summary")]

        return self._render_section(self.SECTION_TITLES[5], datapoints, tables=tables)

    def _build_section_7(self, hn_vs_hp_df: Optional[pd.DataFrame]) -> Dict[str, Any]:
        """Section 7: Heat network vs heat pump comparison module."""
        if hn_vs_hp_df is None or hn_vs_hp_df.empty:
            datapoints = [
                AnnotatedDatapoint(
                    name="Comparison status",
                    key="hn_vs_hp_comparison_status",
                    value="Not available (comparison file not generated)",
                    definition="Status of heat network vs heat pump comparison analysis (text).",
                    denominator="N/A",
                    source="Comparison analysis phase",
                    usage="Comparison availability",
                )
            ]
            return self._render_section(self.SECTION_TITLES[6], datapoints)

        # Extract comparison datapoints
        datapoints = []

        # General comparison metrics (if available in the file)
        comparison_fields = {
            "hn_capital_cost_mean": "Heat network mean capital cost (GBP)",
            "hp_capital_cost_mean": "Heat pump mean capital cost (GBP)",
            "hn_operating_cost_annual": "Heat network annual operating cost (GBP)",
            "hp_operating_cost_annual": "Heat pump annual operating cost (GBP)",
            "hn_carbon_emissions_kg": "Heat network annual carbon emissions (kg)",
            "hp_carbon_emissions_kg": "Heat pump annual carbon emissions (kg)",
            "hn_lifecycle_cost_20yr": "Heat network 20-year lifecycle cost (GBP)",
            "hp_lifecycle_cost_20yr": "Heat pump 20-year lifecycle cost (GBP)",
        }

        for field, label in comparison_fields.items():
            if field in hn_vs_hp_df.columns and not hn_vs_hp_df[field].isna().all():
                value = hn_vs_hp_df[field].iloc[0] if len(hn_vs_hp_df) > 0 else None
                datapoints.append(AnnotatedDatapoint(
                    name=label,
                    key=field,
                    value=value,
                    definition=f"{label}.",
                    denominator="Per property",
                    source=f"data/outputs/comparisons/hn_vs_hp_comparison.csv -> {field}",
                    usage="HN vs HP pathway comparison",
                ))

        # Include full comparison table
        tables = [(hn_vs_hp_df, "Heat Network vs Heat Pump Comparison")]

        return self._render_section(self.SECTION_TITLES[6], datapoints, tables=tables)

    def _build_section_8(self, tipping_point_df: Optional[pd.DataFrame]) -> Dict[str, Any]:
        """Section 8: Fabric tipping-point and cost-performance analysis."""
        if tipping_point_df is None or tipping_point_df.empty:
            datapoints = [
                AnnotatedDatapoint(
                    name="Tipping point analysis status",
                    key="tipping_point_analysis_status",
                    value="Not available (curve file not generated)",
                    definition="Status of fabric tipping point curve analysis (text).",
                    denominator="N/A",
                    source="Tipping point analysis phase",
                    usage="Tipping point availability",
                )
            ]
            return self._render_section(self.SECTION_TITLES[7], datapoints)

        datapoints = [
            AnnotatedDatapoint(
                name="Tipping point curve steps",
                key="tipping_point_curve_steps",
                value=len(tipping_point_df),
                definition="Number of measures in the fabric tipping point curve (count).",
                denominator="Fabric measures modeled",
                source="data/outputs/fabric_tipping_point_curve.csv -> row count",
                usage="Fabric investment curve granularity",
            ),
        ]

        # Identify tipping point (if derivable from data)
        # This would require analyzing the marginal cost per kWh saved
        # For now, include as summary datapoint

        # Include full tipping point table
        tables = [(tipping_point_df, "Fabric Tipping Point Curve - Full Data")]

        return self._render_section(self.SECTION_TITLES[7], datapoints, tables=tables)

    def _build_section_9(self, subsidy_df: Optional[pd.DataFrame]) -> Dict[str, Any]:
        """Section 9: Subsidy sensitivity analysis."""
        if subsidy_df is None or subsidy_df.empty:
            datapoints = [
                AnnotatedDatapoint(
                    name="Subsidy sensitivity status",
                    key="subsidy_sensitivity_status",
                    value="Not available (subsidy file not generated)",
                    definition="Status of subsidy sensitivity analysis (text).",
                    denominator="N/A",
                    source="Subsidy sensitivity analysis phase",
                    usage="Subsidy sensitivity availability",
                )
            ]
            return self._render_section(self.SECTION_TITLES[8], datapoints)

        datapoints = []

        # Process each subsidy level
        for _, row in subsidy_df.iterrows():
            subsidy_pct = row.get("subsidy_pct", row.get("subsidy_level_pct", "unknown"))
            subsidy_suffix = _snake_case(f"subsidy_{subsidy_pct}pct")

            fields = {
                "subsidy_amount_gbp": ("Subsidy amount", "Subsidy amount per property (GBP).", "Per property"),
                "resulting_payback_years": ("Resulting payback", "Payback period after subsidy (years).", "Cost-effective properties"),
                "uptake_rate_pct": ("Uptake rate", "Assumed uptake rate at this subsidy level (percent).", "All properties"),
                "properties_upgraded": ("Properties upgraded", "Count of properties upgraded at this uptake (count).", "All properties"),
                "total_public_expenditure": ("Total public expenditure", "Total subsidy cost (GBP).", "All properties upgraded"),
                "co2_reduction_achieved": ("CO2 reduction achieved", "Total CO₂ reduction achieved (tonnes).", "All properties upgraded"),
                "cost_per_tonne_co2": ("Cost per tonne CO2", "Public expenditure per tonne CO₂ abated (GBP/tCO₂).", "Total CO₂ reduction"),
            }

            for field, (label, definition, denominator) in fields.items():
                value = row.get(field)
                if value is not None and not (isinstance(value, float) and pd.isna(value)):
                    datapoints.append(AnnotatedDatapoint(
                        name=f"{label} (subsidy {subsidy_pct}%)",
                        key=f"{field}_{subsidy_suffix}",
                        value=value,
                        definition=definition,
                        denominator=denominator,
                        source=f"data/outputs/subsidy_sensitivity_analysis.csv -> {field} at subsidy {subsidy_pct}%",
                        usage=f"Subsidy sensitivity {subsidy_pct}%",
                    ))

        # Include full subsidy sensitivity table
        tables = [(subsidy_df, "Subsidy Sensitivity Analysis - Full Results")]

        return self._render_section(self.SECTION_TITLES[8], datapoints, tables=tables)

    def _build_section_10(self, borough_df: Optional[pd.DataFrame]) -> Dict[str, Any]:
        """Section 10: Borough-level breakdown and prioritisation."""
        if borough_df is None or borough_df.empty:
            datapoints = [
                AnnotatedDatapoint(
                    name="Borough breakdown status",
                    key="borough_breakdown_status",
                    value="Not available (borough file not generated)",
                    definition="Status of borough-level breakdown analysis (text).",
                    denominator="N/A",
                    source="Borough breakdown analysis phase",
                    usage="Borough breakdown availability",
                )
            ]
            return self._render_section(self.SECTION_TITLES[9], datapoints)

        datapoints = [
            AnnotatedDatapoint(
                name="Boroughs analyzed",
                key="boroughs_analyzed",
                value=len(borough_df),
                definition="Number of London boroughs in breakdown (count).",
                denominator="London boroughs",
                source="data/outputs/borough_breakdown.csv -> row count",
                usage="Borough coverage",
            ),
        ]

        # Include full borough breakdown table
        tables = [(borough_df, "Borough-Level Breakdown - Full Data")]

        return self._render_section(self.SECTION_TITLES[9], datapoints, tables=tables)

    def _build_section_11(self, case_street_df: Optional[pd.DataFrame]) -> Dict[str, Any]:
        """Section 11: Case street / exemplar outputs."""
        if case_street_df is None or case_street_df.empty:
            datapoints = [
                AnnotatedDatapoint(
                    name="Case street status",
                    key="case_street_status",
                    value="Not available (case street file not generated)",
                    definition="Status of case street exemplar analysis (text).",
                    denominator="N/A",
                    source="Case street analysis phase",
                    usage="Case street availability",
                )
            ]
            return self._render_section(self.SECTION_TITLES[10], datapoints)

        # Extract summary statistics from case street data
        datapoints = [
            AnnotatedDatapoint(
                name="Case street name",
                key="case_street_name",
                value="Shakespeare Crescent",
                definition="Name of case street used for exemplar analysis (text).",
                denominator="N/A",
                source="Configuration / analysis phase",
                usage="Case street context",
            ),
            AnnotatedDatapoint(
                name="Case street property count",
                key="case_street_property_count",
                value=len(case_street_df),
                definition="Number of properties in case street sample (count).",
                denominator="Case street properties",
                source="data/outputs/shakespeare_crescent_extract.csv -> row count",
                usage="Sample size",
            ),
        ]

        # Calculate summary statistics
        if "CURRENT_ENERGY_EFFICIENCY" in case_street_df.columns:
            datapoints.append(AnnotatedDatapoint(
                name="Case street mean SAP score",
                key="case_street_mean_sap",
                value=case_street_df["CURRENT_ENERGY_EFFICIENCY"].mean(),
                definition="Mean SAP score for case street properties (score).",
                denominator="Case street properties",
                source="data/outputs/shakespeare_crescent_extract.csv -> CURRENT_ENERGY_EFFICIENCY.mean()",
                usage="Case street energy efficiency",
            ))

        if "CURRENT_ENERGY_RATING" in case_street_df.columns:
            mode_band = case_street_df["CURRENT_ENERGY_RATING"].mode()
            datapoints.append(AnnotatedDatapoint(
                name="Case street modal EPC band",
                key="case_street_modal_epc_band",
                value=mode_band.iloc[0] if len(mode_band) > 0 else "Not available",
                definition="Most common EPC band for case street properties (band).",
                denominator="Case street properties",
                source="data/outputs/shakespeare_crescent_extract.csv -> CURRENT_ENERGY_RATING.mode()",
                usage="Case street EPC profile",
            ))

        # Include case street sample table
        tables = [(case_street_df.head(20), "Case Street Sample (first 20 properties)")]

        return self._render_section(self.SECTION_TITLES[10], datapoints, tables=tables)

    def _build_section_12(self, adjustment_summary: Dict[str, Any]) -> Dict[str, Any]:
        """Section 12: Uncertainty and sensitivity datapoints."""
        # Extract uncertainty parameters from config and adjustment summary
        prebound_data = adjustment_summary.get("prebound_adjustment", {})

        datapoints = [
            AnnotatedDatapoint(
                name="Prebound effect - Central factors by band",
                key="prebound_effect_central",
                value=self.config.get("methodological_adjustments", {}).get("prebound_effect", {}).get("performance_gap_factors", {}).get("central", {}),
                definition="Central prebound effect multipliers by EPC band (dict: {band: factor}).",
                denominator="EPC-predicted energy",
                source="config/config.yaml -> methodological_adjustments.prebound_effect.performance_gap_factors.central",
                usage="Baseline energy adjustment",
            ),
            AnnotatedDatapoint(
                name="Prebound effect - Low factors by band",
                key="prebound_effect_low",
                value=self.config.get("methodological_adjustments", {}).get("prebound_effect", {}).get("performance_gap_factors", {}).get("low", {}),
                definition="Low (conservative) prebound effect multipliers by EPC band (dict: {band: factor}).",
                denominator="EPC-predicted energy",
                source="config/config.yaml -> methodological_adjustments.prebound_effect.performance_gap_factors.low",
                usage="Sensitivity analysis (low)",
            ),
            AnnotatedDatapoint(
                name="Prebound effect - High factors by band",
                key="prebound_effect_high",
                value=self.config.get("methodological_adjustments", {}).get("prebound_effect", {}).get("performance_gap_factors", {}).get("high", {}),
                definition="High (aggressive) prebound effect multipliers by EPC band (dict: {band: factor}).",
                denominator="EPC-predicted energy",
                source="config/config.yaml -> methodological_adjustments.prebound_effect.performance_gap_factors.high",
                usage="Sensitivity analysis (high)",
            ),
            AnnotatedDatapoint(
                name="Flow temperature range",
                key="flow_temperature_range_c",
                value=self.config.get("heat_pump", {}).get("design_flow_temps", []),
                definition="Heat pump design flow temperatures modeled (°C, list).",
                denominator="N/A",
                source="config/config.yaml -> heat_pump.design_flow_temps",
                usage="Heat pump performance modeling",
            ),
            AnnotatedDatapoint(
                name="COP/SPF vs flow temperature - Central",
                key="cop_sensitivity_central",
                value=self.config.get("heat_pump", {}).get("cop_vs_flow_temp", {}).get("central_spf", []),
                definition="Central SPF values by flow temperature (list).",
                denominator="Heat pump performance curve",
                source="config/config.yaml -> heat_pump.cop_vs_flow_temp.central_spf",
                usage="Heat pump COP modeling",
            ),
            AnnotatedDatapoint(
                name="COP/SPF vs flow temperature - Low",
                key="cop_sensitivity_low",
                value=self.config.get("heat_pump", {}).get("cop_vs_flow_temp", {}).get("low_spf", []),
                definition="Low SPF values by flow temperature (list).",
                denominator="Heat pump performance curve",
                source="config/config.yaml -> heat_pump.cop_vs_flow_temp.low_spf",
                usage="Sensitivity analysis (low HP performance)",
            ),
            AnnotatedDatapoint(
                name="COP/SPF vs flow temperature - High",
                key="cop_sensitivity_high",
                value=self.config.get("heat_pump", {}).get("cop_vs_flow_temp", {}).get("high_spf", []),
                definition="High SPF values by flow temperature (list).",
                denominator="Heat pump performance curve",
                source="config/config.yaml -> heat_pump.cop_vs_flow_temp.high_spf",
                usage="Sensitivity analysis (high HP performance)",
            ),
            AnnotatedDatapoint(
                name="Energy price sensitivity - Current",
                key="energy_price_current",
                value=self.config.get("energy_prices", {}).get("current", {}),
                definition="Current energy prices (£/kWh, dict: {fuel: price}).",
                denominator="N/A",
                source="config/config.yaml -> energy_prices.current",
                usage="Bill calculations baseline",
            ),
            AnnotatedDatapoint(
                name="Energy price sensitivity - 2030 projection",
                key="energy_price_2030",
                value=self.config.get("energy_prices", {}).get("projected_2030", {}),
                definition="2030 projected energy prices (£/kWh, dict: {fuel: price}).",
                denominator="N/A",
                source="config/config.yaml -> energy_prices.projected_2030",
                usage="Bill calculations 2030",
            ),
            AnnotatedDatapoint(
                name="Energy price sensitivity - 2040 projection",
                key="energy_price_2040",
                value=self.config.get("energy_prices", {}).get("projected_2040", {}),
                definition="2040 projected energy prices (£/kWh, dict: {fuel: price}).",
                denominator="N/A",
                source="config/config.yaml -> energy_prices.projected_2040",
                usage="Bill calculations 2040",
            ),
            AnnotatedDatapoint(
                name="Carbon factor - Current",
                key="carbon_factor_current",
                value=self.config.get("carbon_factors", {}).get("current", {}),
                definition="Current carbon emission factors (kgCO2/kWh, dict: {fuel: factor}).",
                denominator="N/A",
                source="config/config.yaml -> carbon_factors.current",
                usage="Carbon calculations baseline",
            ),
            AnnotatedDatapoint(
                name="Carbon factor - 2030 projection",
                key="carbon_factor_2030",
                value=self.config.get("carbon_factors", {}).get("projected_2030", {}),
                definition="2030 projected carbon emission factors (kgCO2/kWh, dict: {fuel: factor}).",
                denominator="N/A",
                source="config/config.yaml -> carbon_factors.projected_2030",
                usage="Carbon calculations 2030",
            ),
            AnnotatedDatapoint(
                name="Carbon factor - 2040 projection",
                key="carbon_factor_2040",
                value=self.config.get("carbon_factors", {}).get("projected_2040", {}),
                definition="2040 projected carbon emission factors (kgCO2/kWh, dict: {fuel: factor}).",
                denominator="N/A",
                source="config/config.yaml -> carbon_factors.projected_2040",
                usage="Carbon calculations 2040",
            ),
            AnnotatedDatapoint(
                name="Measurement uncertainty - Demand error range (low)",
                key="measurement_uncertainty_demand_low",
                value=self.config.get("uncertainty", {}).get("demand_error_low", -0.20),
                definition="Lower bound of demand measurement uncertainty (fraction).",
                denominator="Nominal demand",
                source="config/config.yaml -> uncertainty.demand_error_low",
                usage="Uncertainty bounds",
            ),
            AnnotatedDatapoint(
                name="Measurement uncertainty - Demand error range (high)",
                key="measurement_uncertainty_demand_high",
                value=self.config.get("uncertainty", {}).get("demand_error_high", 0.20),
                definition="Upper bound of demand measurement uncertainty (fraction).",
                denominator="Nominal demand",
                source="config/config.yaml -> uncertainty.demand_error_high",
                usage="Uncertainty bounds",
            ),
            AnnotatedDatapoint(
                name="Measurement uncertainty - SAP score error by rating",
                key="measurement_uncertainty_sap",
                value=self.config.get("uncertainty", {}).get("sap_uncertainty", {}),
                definition="SAP score measurement error ranges by rating band (dict: {rating: error_points}).",
                denominator="SAP score",
                source="config/config.yaml -> uncertainty.sap_uncertainty",
                usage="EPC data uncertainty",
            ),
        ]
        return self._render_section(self.SECTION_TITLES[11], datapoints)

    def _build_section_13(self) -> Dict[str, Any]:
        """Section 13: Structure of the one-stop output document (glossary)."""
        cost_eff = self.config.get("financial", {}).get("cost_effectiveness", {})

        # Collect all datapoints from all sections
        all_datapoints = []
        for section_data in self._sections.values():
            all_datapoints.extend(section_data.get("datapoints", []))

        return {
            "title": self.SECTION_TITLES[12],
            "description": "Comprehensive glossary of all metrics, tier definitions, and thresholds used in Sections 1-12",
            "definitions": {
                "heat_pump_readiness_tiers": {
                    "tier_1": "Ready now - Properties that can install heat pump immediately without fabric upgrades",
                    "tier_2": "Minor work - Properties requiring minor fabric improvements (e.g., loft top-up)",
                    "tier_3": "Major work - Properties requiring major fabric work (e.g., wall insulation)",
                    "tier_4": "Challenging - Properties with multiple fabric issues requiring substantial investment",
                    "tier_5": "Not suitable - Properties not suitable for heat pump without extensive retrofit"
                },
                "heat_network_spatial_tiers": {
                    "tier_1": "Adjacent to existing heat network (within 250m)",
                    "tier_2": "Within planned heat network zone (HNZ boundary)",
                    "tier_3": "High heat density area (≥20 GWh/km²)",
                    "tier_4": "Medium heat density area (5-20 GWh/km²)",
                    "tier_5": "Low heat density area (<5 GWh/km²)"
                },
                "epc_bands": {
                    "A": {"sap_min": 92, "sap_max": 100},
                    "B": {"sap_min": 81, "sap_max": 91},
                    "C": {"sap_min": 69, "sap_max": 80},
                    "D": {"sap_min": 55, "sap_max": 68},
                    "E": {"sap_min": 39, "sap_max": 54},
                    "F": {"sap_min": 21, "sap_max": 38},
                    "G": {"sap_min": 1, "sap_max": 20}
                },
                "cost_effectiveness_thresholds": {
                    "cost_effective": f"Payback ≤ {cost_eff.get('max_payback_years', 15)} years AND positive NPV",
                    "marginally_cost_effective": f"Payback {cost_eff.get('max_payback_years', 15)}-{cost_eff.get('max_payback_marginal', 25)} years AND positive NPV",
                    "not_cost_effective": f"Payback > {cost_eff.get('max_payback_marginal', 25)} years OR negative NPV"
                }
            },
            "datapoints": all_datapoints,
            "datapoint_count": len(all_datapoints),
            "tables": []
        }


if __name__ == "__main__":
    generator = OneStopReportGenerator()
    generator.generate()
