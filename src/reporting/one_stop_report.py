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
import math
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
from loguru import logger

# Ensure project root is on sys.path so `config.*` imports work when running as a script
sys.path.append(str(Path(__file__).parent.parent.parent))

from config.config import DATA_OUTPUTS_DIR, DATA_PROCESSED_DIR, load_config, get_scenario_policy
from src.modeling.contracts import TIER_READINESS_INTERPRETATIONS, TIER_READINESS_LABELS
from src.utils.run_integrity import (
    RunContext,
    require_current_artifact,
    stamp_artifact,
    validate_scenario_invariants,
)


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
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    if isinstance(obj, (np.floating, np.float64, np.float32)):
        value = float(obj)
        if math.isnan(value) or math.isinf(value):
            return None
        return value
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


def _explicit_int(value: Any, label: str) -> int:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        raise RuntimeError(f"Missing explicit current-run metric for {label}")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Invalid count for {label}: {value!r}") from exc
    if not numeric.is_integer() or numeric < 0:
        raise RuntimeError(f"Invalid count for {label}: {value!r}")
    return int(numeric)


def _sum_explicit_counts(values: Iterable[Any], label: str) -> int:
    return sum(_explicit_int(value, label) for value in values)


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
        run_id: Optional[str] = None,
        dataset_fingerprint: Optional[str] = None,
        authoritative_cohort_size: Optional[int] = None,
        run_context: Optional[RunContext] = None,
    ):
        self.output_dir = Path(output_dir) if output_dir else DATA_OUTPUTS_DIR
        self.processed_dir = Path(processed_dir) if processed_dir else DATA_PROCESSED_DIR
        self.config = config or load_config()
        self.output_path = self.output_dir / "one_stop_output.json"
        self._sections: Dict[str, Any] = {}
        supplied_context = run_context is not None or run_id is not None or dataset_fingerprint is not None
        if supplied_context and not (run_id and dataset_fingerprint):
            if run_context is None:
                raise ValueError("run_id and dataset_fingerprint must be supplied together")
        self.run_context = run_context or (
            RunContext(run_id, dataset_fingerprint) if supplied_context else None
        )
        self.authoritative_cohort_size = authoritative_cohort_size
        if self.run_context and authoritative_cohort_size is None:
            raise ValueError("authoritative_cohort_size is required for a provenance-gated report")

    def generate(self) -> Path:
        """Generate the complete one-stop JSON report."""
        logger.info("Generating comprehensive one-stop JSON report...")

        paths = {
            "run_metadata": self.output_dir / "run_metadata.json",
            "validation_report": self.processed_dir / "validation_report.json",
            "adjustment_summary": self.processed_dir / "methodological_adjustments_summary.json",
            "archetype": self.output_dir / "archetype_analysis_results.json",
            "readiness": self.output_dir / "retrofit_readiness_analysis.csv",
            "scenario": self.output_dir / "scenario_results_summary.csv",
            "spatial": self.output_dir / "pathway_suitability_by_tier.csv",
            "comparison": self.output_dir / "stock_scenario_comparison.csv",
            "tipping": self.output_dir / "fabric_tipping_point_curve.csv",
            "subsidy": self.output_dir / "subsidy_sensitivity_analysis.csv",
            "borough": self.output_dir / "borough_breakdown.csv",
            "borough_priority": self.output_dir / "reports" / "borough_priority_ranking.csv",
            "tenure": self.output_dir / "reports" / "tenure_segmentation.csv",
            "network_threshold": self.output_dir / "heat_network_connection_thresholds.csv",
            "case_street": self.output_dir / "shakespeare_crescent_extract.csv",
            "window_economics": self.output_dir / "window_economics.csv",
        }
        if self.run_context:
            required = {
                "run_metadata", "validation_report", "adjustment_summary", "archetype",
                "readiness", "scenario", "spatial", "borough", "tenure",
            }
            for name, path in paths.items():
                if name in required or path.exists():
                    require_current_artifact(path, self.run_context)

        # Load all data sources only after provenance has passed.
        run_metadata = _read_json(paths["run_metadata"])
        validation_report = _read_json(paths["validation_report"])
        adjustment_summary = _read_json(paths["adjustment_summary"])
        archetype_json = _read_json(paths["archetype"])
        readiness_df = _read_csv(paths["readiness"])
        scenario_df = _read_csv(paths["scenario"])
        spatial_tier_df = _read_csv(paths["spatial"])
        hn_vs_hp_df = _read_csv(paths["comparison"])
        tipping_point_df = (
            _read_csv(paths["tipping"])
            if 'fabric_to_tipping_point' in set(get_scenario_policy()['publish'])
            else None
        )
        subsidy_df = _read_csv(paths["subsidy"])
        borough_df = _read_csv(paths["borough"])
        borough_priority_df = _read_csv(paths["borough_priority"])
        tenure_segmentation_df = _read_csv(paths["tenure"])
        heat_network_threshold_df = _read_csv(paths["network_threshold"])
        case_street_df = _read_csv(paths["case_street"])
        window_economics_df = _read_csv(paths["window_economics"])
        lodgements_by_year_band_df = self._build_epc_lodgements_by_year_band()

        if self.run_context:
            self._assert_run_metadata(run_metadata)
            self._assert_cohort_integrity(
                validation_report=validation_report,
                archetype_json=archetype_json,
                readiness_df=readiness_df,
                scenario_df=scenario_df,
                spatial_tier_df=spatial_tier_df,
                borough_df=borough_df,
                tenure_df=tenure_segmentation_df,
            )

        # Build all 13 sections
        self._sections["section_1"] = self._build_section_1(run_metadata)
        self._sections["section_2"] = self._build_section_2(validation_report, adjustment_summary)
        self._sections["section_3"] = self._build_section_3(archetype_json, lodgements_by_year_band_df)
        self._sections["section_4"] = self._build_section_4(readiness_df, window_economics_df)
        self._sections["section_5"] = self._build_section_5(spatial_tier_df)
        self._sections["section_6"] = self._build_section_6(scenario_df)
        self._sections["section_7"] = self._build_section_7(hn_vs_hp_df)
        self._sections["section_8"] = self._build_section_8(tipping_point_df)
        self._sections["section_9"] = self._build_section_9(subsidy_df)
        self._sections["section_10"] = self._build_section_10(
            borough_df,
            borough_priority_df,
            tenure_segmentation_df,
            heat_network_threshold_df,
        )
        self._sections["section_11"] = self._build_section_11(case_street_df)
        self._sections["section_12"] = self._build_section_12(adjustment_summary)
        self._sections["section_13"] = self._build_section_13()
        for section_id, section in self._sections.items():
            section["section_id"] = section_id

        # Build final JSON structure
        output = {
            "metadata": {
                "title": "Heat Street — One-Stop Report",
                "subtitle": "Low-Carbon Heating Potential for London's Edwardian Terraced Housing",
                "generated": datetime.now().isoformat(),
                "version": "2.0",
                "run_id": self.run_context.run_id if self.run_context else run_metadata.get("run_id"),
                "dataset_fingerprint": (
                    self.run_context.dataset_fingerprint
                    if self.run_context else run_metadata.get("dataset_fingerprint")
                ),
                **(self.run_context.to_dict() if self.run_context else {}),
            },
            "sections": self._sections
        }

        # Convert any remaining numpy types before JSON serialization
        output = _convert_numpy_types(output)

        # Write output
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
        if self.run_context:
            stamp_artifact(
                self.output_path,
                self.run_context,
                record_count=self.authoritative_cohort_size,
            )

        total_datapoints = sum(len(s.get("datapoints", [])) for s in self._sections.values())
        logger.info(f"One-stop JSON report written to {self.output_path}")
        logger.info(f"Total datapoints: {total_datapoints}")
        return self.output_path

    def _assert_run_metadata(self, run_metadata: Dict[str, Any]) -> None:
        # Report generation validates complete provenance and timing, while the
        # pipeline marks the run complete only after every required report and
        # package has passed its own contract.
        self.run_context.validate_production_report(require_complete=False)
        expected = self.run_context.to_dict()
        for key, value in expected.items():
            if run_metadata.get(key) != value:
                raise RuntimeError(
                    f"Run metadata provenance mismatch: {key}={run_metadata.get(key)!r}, "
                    f"expected {value!r}"
                )

    def _assert_cohort_integrity(
        self,
        *,
        validation_report: Dict[str, Any],
        archetype_json: Dict[str, Any],
        readiness_df: Optional[pd.DataFrame],
        scenario_df: Optional[pd.DataFrame],
        spatial_tier_df: Optional[pd.DataFrame],
        borough_df: Optional[pd.DataFrame],
        tenure_df: Optional[pd.DataFrame],
    ) -> None:
        """Reconcile every report cohort before one-stop serialization."""
        cohort = int(self.authoritative_cohort_size)
        required_validation = (
            "total_records", "records_passed", "duplicates_removed", "invalid_records"
        )
        missing = [key for key in required_validation if key not in validation_report]
        if missing:
            raise RuntimeError(f"Validation report is missing explicit metrics: {missing}")

        total = int(validation_report["total_records"])
        passed = int(validation_report["records_passed"])
        duplicates = int(validation_report["duplicates_removed"])
        invalid = int(validation_report["invalid_records"])
        if total != passed + duplicates + invalid:
            raise RuntimeError(
                "Validation arithmetic mismatch: total_records must equal "
                "records_passing_validation + duplicates_removed + invalid_records"
            )

        checks: list[tuple[str, int]] = [("Section 2 records passing validation", passed)]
        epc_frequency = archetype_json.get("epc_bands", {}).get("frequency")
        heating_types = archetype_json.get("heating_systems", {}).get("types")
        if not isinstance(epc_frequency, dict) or not isinstance(heating_types, dict):
            raise RuntimeError("Archetype output lacks explicit EPC band or heating-system totals")
        checks.extend([
            ("archetype band totals", _sum_explicit_counts(epc_frequency.values(), "archetype bands")),
            ("heating-system totals", _sum_explicit_counts(heating_types.values(), "heating systems")),
        ])

        if readiness_df is None or "hp_readiness_tier" not in readiness_df.columns:
            raise RuntimeError("Readiness output lacks hp_readiness_tier")
        readiness_tiers = readiness_df["hp_readiness_tier"]
        readiness_tier_counts = readiness_tiers.value_counts()
        checks.extend([
            ("readiness row count", len(readiness_df)),
            (
                "readiness tier totals",
                sum(int(readiness_tier_counts.get(tier, 0)) for tier in range(1, 6)),
            ),
        ])

        if scenario_df is None or scenario_df.empty or "total_properties" not in scenario_df.columns:
            raise RuntimeError("Scenario output lacks explicit total_properties values")
        if 'model_family' not in scenario_df or 'headline_reporting_eligible' not in scenario_df:
            raise RuntimeError("Client scenario output lacks model-family metadata")
        eligible = scenario_df['headline_reporting_eligible'].astype(str).str.casefold().isin(['true', '1'])
        if not eligible.all():
            raise RuntimeError("Client headline table contains ineligible model rows")
        if scenario_df['model_family'].dropna().nunique() != 1:
            raise RuntimeError("Client headline table mixes model families")
        for index, row in scenario_df.iterrows():
            label = row.get("scenario", row.get("scenario_id", index))
            checks.append((f"scenario {label!r} total_properties", _explicit_int(row["total_properties"], "scenario total_properties")))
        if self.run_context.mode == 'production' or cohort == 168_051:
            if int(validation_report["total_records"]) != 183_376 or (
                int(validation_report["duplicates_removed"]) + int(validation_report["invalid_records"]) + cohort
                != 183_376
            ):
                raise RuntimeError("Volume identity must equal 183,376 = 168,051 + 14,432 + 893")
            validate_scenario_invariants(
                scenario_df,
                authoritative_cohort=cohort,
                analysis_horizon_years=int(self.config['financial']['analysis_horizon_years']),
            )

        if spatial_tier_df is None or "Property Count" not in spatial_tier_df.columns:
            raise RuntimeError("Spatial output lacks Property Count")
        checks.append(("spatial tier totals", _sum_explicit_counts(spatial_tier_df["Property Count"], "spatial tiers")))

        if borough_df is None or "property_count" not in borough_df.columns:
            raise RuntimeError("Borough output lacks property_count")
        checks.append(("borough totals", _sum_explicit_counts(borough_df["property_count"], "boroughs")))

        if tenure_df is None or "property_count" not in tenure_df.columns:
            raise RuntimeError("Tenure output lacks property_count")
        checks.append(("tenure totals", _sum_explicit_counts(tenure_df["property_count"], "tenure")))

        if "scenario" in scenario_df.columns:
            scenario_labels = scenario_df["scenario"]
        elif "scenario_id" in scenario_df.columns:
            scenario_labels = scenario_df["scenario_id"]
        else:
            raise RuntimeError("Scenario output lacks scenario identifiers")
        hybrid_mask = scenario_labels.astype(str).str.contains("hybrid", case=False, na=False)
        hybrid_rows = scenario_df[hybrid_mask]
        if hybrid_rows.empty:
            raise RuntimeError("Scenario output lacks an explicit hybrid pathway allocation")
        for _, row in hybrid_rows.iterrows():
            if "hn_assigned_properties" not in row or "ashp_assigned_properties" not in row:
                raise RuntimeError("Hybrid scenario lacks explicit pathway allocation fields")
            allocated = _explicit_int(row["hn_assigned_properties"], "hybrid HN allocation") + _explicit_int(
                row["ashp_assigned_properties"], "spatial hybrid ASHP allocation"
            )
            checks.append(("hybrid pathway allocations", allocated))

        mismatches = [f"{name}={actual:,}" for name, actual in checks if actual != cohort]
        if mismatches:
            raise RuntimeError(
                f"Cohort integrity failure; authoritative final adjusted cohort={cohort:,}; "
                + "; ".join(mismatches)
            )

    def _build_epc_lodgements_by_year_band(self) -> Optional[pd.DataFrame]:
        """
        Build a wide-format table of EPC lodgements by year and EPC band.

        This is used by the HTML dashboard to render a stacked bar chart without
        relying on additional output files.
        """
        parquet_path = self.processed_dir / "epc_london_validated.parquet"
        csv_path = self.processed_dir / "epc_london_validated.csv"
        cols = ["LODGEMENT_DATE", "INSPECTION_DATE", "CURRENT_ENERGY_RATING"]

        df: Optional[pd.DataFrame] = None
        try:
            if self.run_context and csv_path.is_file():
                require_current_artifact(csv_path, self.run_context)
                df = pd.read_csv(csv_path, usecols=cols)
            elif self.run_context:
                logger.info("Skipping lodgement table: no provenance-carrying validated CSV")
                return None
            elif parquet_path.exists():
                df = pd.read_parquet(parquet_path, columns=cols)
            elif csv_path.exists():
                df = pd.read_csv(csv_path, usecols=cols)
        except Exception as exc:
            logger.warning(f"Could not load validated EPC data for lodgement table: {exc}")
            return None

        if df is None or df.empty:
            return None

        lodgement = pd.to_datetime(df.get("LODGEMENT_DATE"), errors="coerce")
        inspection = pd.to_datetime(df.get("INSPECTION_DATE"), errors="coerce")
        effective = lodgement.fillna(inspection)
        years = effective.dt.year

        band = df.get("CURRENT_ENERGY_RATING")
        if band is None:
            return None
        band = band.astype("string").fillna("Unknown").str.strip().str.upper()
        band = band.replace({"": "Unknown"})
        band = band.where(band.isin(list("ABCDEFG")), other="Unknown")

        tmp = pd.DataFrame({"year": years, "band": band}).dropna(subset=["year"])
        if tmp.empty:
            return None

        tmp["year"] = tmp["year"].astype(int)
        wide = (
            tmp.groupby(["year", "band"])
            .size()
            .unstack(fill_value=0)
            .sort_index()
        )
        wide.index.name = "year"

        ordered_cols = list("ABCDEFG") + ["Unknown"]
        for c in ordered_cols:
            if c not in wide.columns:
                wide[c] = 0

        wide = wide[ordered_cols].reset_index()
        return wide

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
                value=self.config.get("resolved_energy_price_profile", {}),
                definition="Energy prices used in analysis (£/kWh for gas and electricity).",
                denominator="N/A",
                source="Configuration / run definition",
                usage="Financial calculations",
            ),
            AnnotatedDatapoint(
                name="Energy price profile ID",
                key="energy_price_profile_id",
                value=(run_metadata.get("energy_price_profile") or {}).get("profile_id", "Not available"),
                definition="Stable ID of the run-resolved domestic unit-rate profile; standing charges are excluded.",
                denominator="N/A",
                source="data/outputs/run_metadata.json -> energy_price_profile.profile_id",
                usage="Reproducibility and semantic QA",
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

    def _build_section_3(self, archetype_json: Dict[str, Any], lodgements_by_year_band_df: Optional[pd.DataFrame]) -> Dict[str, Any]:
        """Section 3: Housing stock archetype characteristics."""
        epc_bands = archetype_json.get("epc_bands", {})
        sap_scores = archetype_json.get("sap_scores", {})
        wall_data = archetype_json.get("wall_construction", {})
        floor_data = archetype_json.get("floor_insulation", {})
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
                name="Floor insulation distribution",
                key="floor_insulation_distribution",
                value={
                    "insulated": floor_data.get("insulated", 0),
                    "uninsulated": floor_data.get("uninsulated", 0),
                    "unknown": floor_data.get("unknown", 0),
                },
                definition="Canonical floor-insulation counts, retaining unknown separately.",
                denominator="All properties in archetype analysis",
                source="data/outputs/archetype_analysis_results.json -> floor_insulation",
                usage="Fabric upgrade targeting without treating unknown as insulated",
            ),
            AnnotatedDatapoint(
                name="Floor insulation percentages",
                key="floor_insulation_percentages",
                value={
                    "insulated": floor_data.get("insulated_pct", 0),
                    "uninsulated": floor_data.get("uninsulated_pct", 0),
                    "unknown": floor_data.get("unknown_pct", 0),
                },
                definition="Canonical floor-insulation percentages, including unknown.",
                denominator="All properties in archetype analysis",
                source="data/outputs/archetype_analysis_results.json -> floor_insulation",
                usage="Fabric upgrade targeting and data-quality interpretation",
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
        tables: List[Tuple[pd.DataFrame, str]] = []
        if lodgements_by_year_band_df is not None and not lodgements_by_year_band_df.empty:
            tables.append((
                lodgements_by_year_band_df,
                "EPC lodgements by year and EPC band (counts; year from LODGEMENT_DATE, fallback INSPECTION_DATE)",
            ))

        return self._render_section(self.SECTION_TITLES[2], datapoints, tables=tables)

    def _build_section_4(
        self,
        readiness_df: Optional[pd.DataFrame],
        window_economics_df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
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
            tier_names = TIER_READINESS_LABELS
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

        tier_cost_fields = {
            "fabric_prerequisite_cost": ("Fabric prerequisite cost", "Average fabric prerequisite cost by readiness tier (GBP per property)."),
            "system_cost_full_ashp": ("Full-ASHP system cost", "Average full-ASHP system cost by readiness tier (GBP per property)."),
            "total_cost_full_ashp": ("Total full-ASHP cost", "Average fabric plus full-ASHP system cost by readiness tier (GBP per property)."),
        }
        for tier in range(1, 6):
            tier_df = readiness_df[readiness_df["hp_readiness_tier"] == tier] if "hp_readiness_tier" in readiness_df.columns else pd.DataFrame()
            if tier_df.empty:
                continue

            for field, (label, definition) in tier_cost_fields.items():
                if field in tier_df.columns:
                    datapoints.append(AnnotatedDatapoint(
                        name=f"Readiness Tier {tier} {label}",
                        key=f"tier_{tier}_{field}_mean_gbp",
                        value=tier_df[field].mean(),
                        definition=definition,
                        denominator=f"Readiness Tier {tier} properties",
                        source=f"data/outputs/retrofit_readiness_analysis.csv -> mean({field}) where hp_readiness_tier == {tier}",
                        usage="Readiness tier cost interpretation",
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

        for field, label, usage in (
            ("total_cost_full_ashp", "Canonical full-ASHP readiness total", "Sole headline readiness capital requirement"),
        ):
            if field in readiness_df.columns:
                datapoints.append(AnnotatedDatapoint(
                    name=label,
                    key=f"{field}_gbp",
                    value=readiness_df[field].sum(),
                    definition=f"Sum of property-level {field} values (GBP).",
                    denominator="All properties assessed",
                    source=f"data/outputs/retrofit_readiness_analysis.csv -> {field}.sum()",
                    usage=usage,
                ))

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

        tables = []
        if window_economics_df is not None and not window_economics_df.empty:
            tables.append((window_economics_df, "Configuration-backed window economics"))
        return self._render_section(self.SECTION_TITLES[3], datapoints, tables=tables)

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
                "cost_per_tco2_20yr_gbp": (
                    "Cost per tCO2 over analysis horizon",
                    str(row.get("cost_per_tco2_20yr_definition") or "capital_cost_total / ((annual_co2_reduction_kg / 1000) * configured analysis_horizon_years)."),
                    "Total tCO2 abated over configured analysis horizon",
                ),
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
                    "aggregate_simple_payback_years": "Aggregate simple payback years",
                    "property_simple_payback_mean_years": "Property simple payback mean years",
                    "property_simple_payback_median_years": "Property simple payback median years",
                    "payback_valid_denominator_count": "Valid property payback denominator",
                    "payback_non_positive_savings_count": "Properties with non-positive savings",
                    "payback_missing_input_count": "Properties with missing payback inputs",
                    "payback_non_finite_input_count": "Properties with non-finite payback inputs",
                    "payback_infinite_count": "Properties with mathematically infinite payback",
                    "excluded_by_truncation_count": "Finite paybacks excluded by truncation",
                    "truncation_threshold_years": "Property payback truncation threshold years",
                }
                for field, label in payback_fields.items():
                    value = row.get(field)
                    if field == "truncation_threshold_years" and pd.isna(value):
                        value = None
                    if value is not None or field == "truncation_threshold_years":
                        datapoints.append(AnnotatedDatapoint(
                            name=f"{label} ({scenario_label})",
                            key=f"{field}_{scenario_suffix}",
                            value=value,
                            definition=(
                                f"{label}; property statistics include every finite payback with finite capital cost and strictly positive finite savings."
                            ),
                            denominator="All scenario properties, categorised explicitly by payback eligibility",
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
                    "carbon_abatement_cost_property_mean": ("Diagnostic property carbon abatement cost (mean)", "Diagnostic mean of property-level carbon abatement cost; use cost_per_tco2_20yr_gbp for headline reporting.", "Properties with finite property-level abatement cost"),
                    "carbon_abatement_cost_property_median": ("Diagnostic property carbon abatement cost (median)", "Diagnostic median of property-level carbon abatement cost; use cost_per_tco2_20yr_gbp for headline reporting.", "Properties with finite property-level abatement cost"),
                    "carbon_abatement_cost_property_p10": ("Diagnostic property carbon abatement cost (p10)", "Diagnostic p10 of property-level carbon abatement cost; use cost_per_tco2_20yr_gbp for headline reporting.", "Properties with finite property-level abatement cost"),
                    "carbon_abatement_cost_property_p90": ("Diagnostic property carbon abatement cost (p90)", "Diagnostic p90 of property-level carbon abatement cost; use cost_per_tco2_20yr_gbp for headline reporting.", "Properties with finite property-level abatement cost"),
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
                    "ashp_not_ready_properties": "Currently unsuitable for a standard ASHP",
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

    def _build_retrofit_cost_envelopes(self, hn_vs_hp_df: pd.DataFrame) -> pd.DataFrame:
        """Build a pathway cost-envelope table from HN vs HP comparison outputs."""
        pathway_notes = {
            "fabric_only": "Fabric measures only; no heat technology capex in this pathway row.",
            "fabric_plus_hp_only": "Fabric plus individual ASHP pathway.",
            "fabric_plus_hn_only": "Fabric plus heat network connection pathway.",
            "fabric_plus_hp_plus_hn": "Hybrid routing: HN where available, ASHP elsewhere.",
        }
        pathway_names = {
            "fabric_only": "Fabric only",
            "fabric_plus_hp_only": "Fabric + ASHP",
            "fabric_plus_hn_only": "Fabric + HN",
            "fabric_plus_hp_plus_hn": "Hybrid",
        }

        rows = []
        if hn_vs_hp_df is None or hn_vs_hp_df.empty:
            return pd.DataFrame(rows)
        if "pathway_id" not in hn_vs_hp_df.columns:
            return pd.DataFrame(rows)

        for pathway_id in pathway_notes:
            matches = hn_vs_hp_df[hn_vs_hp_df["pathway_id"].astype(str) == pathway_id]
            if matches.empty:
                continue
            row = matches.iloc[0]
            required = ["capex_p10", "capex_p90", "capex_median"]
            if not all(field in hn_vs_hp_df.columns and not pd.isna(row.get(field)) for field in required):
                continue
            note = row.get("payback_note")
            rows.append(
                {
                    "pathway_id": pathway_id,
                    "pathway_name": row.get("pathway_name") or pathway_names[pathway_id],
                    "capex_p10": row.get("capex_p10"),
                    "capex_p90": row.get("capex_p90"),
                    "capex_median": row.get("capex_median"),
                    "note": note if isinstance(note, str) and note.strip() else pathway_notes[pathway_id],
                }
            )

        return pd.DataFrame(rows)

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

        datapoints = [
            AnnotatedDatapoint(
                name="Pathways compared",
                key="hn_vs_hp_pathways_compared",
                value=hn_vs_hp_df.get("scenario", pd.Series(dtype=str)).dropna().astype(str).tolist(),
                definition="Pathway names included in the HP vs HN comparison table (list of strings).",
                denominator="N/A",
                source="data/outputs/stock_scenario_comparison.csv -> scenario",
                usage="HN vs HP pathway comparison coverage",
            ),
            AnnotatedDatapoint(
                name="Comparison pathways count",
                key="hn_vs_hp_pathway_count",
                value=len(hn_vs_hp_df),
                definition="Number of pathway rows included in the HP vs HN comparison table (count).",
                denominator="Pathways in comparison table",
                source="data/outputs/stock_scenario_comparison.csv -> row count",
                usage="HN vs HP pathway comparison coverage",
            ),
        ]

        for _, row in hn_vs_hp_df.iterrows():
            pathway_id = _snake_case(str(row.get("scenario_id", row.get("scenario", "scenario"))))
            pathway_name = str(row.get("scenario", row.get("scenario_id", "Scenario")))
            field_labels = {
                "capital_cost_per_property": "Mean capital cost",
                "annual_bill_savings": "Total annual bill saving",
                "annual_co2_reduction_kg": "Total annual CO2 saving",
                "aggregate_simple_payback_years": "Aggregate simple payback",
                "property_simple_payback_mean_years": "Property mean simple payback",
            }
            for field, label in field_labels.items():
                if field in hn_vs_hp_df.columns and not pd.isna(row.get(field)):
                    datapoints.append(
                        AnnotatedDatapoint(
                            name=f"{pathway_name} {label}",
                            key=f"{pathway_id}_{field}",
                            value=row.get(field),
                            definition=f"{label} for {pathway_name}.",
                            denominator="Per pathway row",
                            source=f"data/outputs/stock_scenario_comparison.csv -> {field}",
                            usage="HN vs HP pathway comparison",
                        )
                    )

        # Include full comparison table
        tables = [(hn_vs_hp_df, "Heat Network vs Heat Pump Comparison")]
        envelope_df = self._build_retrofit_cost_envelopes(hn_vs_hp_df)
        if not envelope_df.empty:
            tables.append((envelope_df, "Retrofit Cost Envelopes"))

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

        df = subsidy_df.copy()

        # Normalise historical/alternate column names so Section 9 remains robust.
        rename_map = {
            "subsidy_pct": "subsidy_percentage",
            "subsidy_level_pct": "subsidy_percentage",
            "uptake_rate": "estimated_uptake_rate",
            "uptake_rate_pct": "estimated_uptake_rate",
        }
        df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

        scenario_col = "scenario" if "scenario" in df.columns else "scenario_id"
        if scenario_col not in df.columns:
            # No scenario column -> treat as single scenario for backwards compatibility.
            scenario_col = "scenario"
            df[scenario_col] = "unknown"

        scenarios = sorted(str(s) for s in df[scenario_col].dropna().unique().tolist() if s)
        subsidy_levels = sorted(
            float(s) for s in df.get("subsidy_percentage", pd.Series(dtype=float)).dropna().unique().tolist()
        )
        uptake_models = sorted(
            str(s) for s in df.get("uptake_model", pd.Series(dtype=str)).dropna().unique().tolist() if s
        )
        cost_uplift_values = sorted(
            float(s) for s in df.get("cost_uplift_pct", pd.Series(dtype=float)).dropna().unique().tolist()
        )

        datapoints = [
            AnnotatedDatapoint(
                name="Subsidy sensitivity scenarios modeled",
                key="subsidy_sensitivity_scenarios",
                value=scenarios,
                definition="Scenario IDs included in the subsidy sensitivity table (list of strings).",
                denominator="N/A",
                source="data/outputs/subsidy_sensitivity_analysis.csv -> scenario unique values",
                usage="Subsidy sensitivity coverage",
            ),
            AnnotatedDatapoint(
                name="Subsidy levels modeled (%)",
                key="subsidy_levels_modeled_pct",
                value=subsidy_levels,
                definition="Subsidy levels modeled (percent of capital cost, list).",
                denominator="N/A",
                source="data/outputs/subsidy_sensitivity_analysis.csv -> subsidy_percentage unique values",
                usage="Subsidy sensitivity parameters",
            ),
        ]

        if uptake_models:
            datapoints.append(AnnotatedDatapoint(
                name="Uptake model(s) used",
                key="subsidy_uptake_models",
                value=uptake_models,
                definition="Uptake model identifier(s) used to map payback to adoption (list of strings).",
                denominator="N/A",
                source="data/outputs/subsidy_sensitivity_analysis.csv -> uptake_model unique values",
                usage="Subsidy sensitivity methodology",
            ))

        if cost_uplift_values:
            datapoints.append(AnnotatedDatapoint(
                name="Cost uplift applied for subsidy sensitivity (%)",
                key="subsidy_cost_uplift_pct",
                value=cost_uplift_values[0] if len(cost_uplift_values) == 1 else cost_uplift_values,
                definition="Temporary cost uplift applied during subsidy sensitivity (percent).",
                denominator="N/A",
                source="data/outputs/subsidy_sensitivity_analysis.csv -> cost_uplift_pct",
                usage="Subsidy sensitivity assumptions",
            ))

        # Per-scenario headline datapoints (policy-facing shortcuts)
        for scenario_id in scenarios:
            sdf = df[df[scenario_col].astype(str) == str(scenario_id)].copy()
            if sdf.empty:
                continue

            scenario_label = None
            if "scenario_label" in sdf.columns:
                labels = sdf["scenario_label"].dropna().astype(str).unique().tolist()
                if labels:
                    scenario_label = labels[0]
            scenario_label = scenario_label or str(scenario_id)
            suffix = _snake_case(str(scenario_id))

            # Max uptake (fraction 0-1 in the CSV)
            if "estimated_uptake_rate" in sdf.columns:
                uptake_series = pd.to_numeric(sdf["estimated_uptake_rate"], errors="coerce")
                if uptake_series.notna().any():
                    idx = int(uptake_series.idxmax())
                    row = sdf.loc[idx]
                    datapoints.extend([
                        AnnotatedDatapoint(
                            name=f"Max uptake rate ({scenario_label})",
                            key=f"subsidy_max_uptake_rate_{suffix}",
                            value=row.get("estimated_uptake_rate"),
                            definition="Maximum modeled uptake rate across subsidy levels (fraction 0-1).",
                            denominator="All properties",
                            source="data/outputs/subsidy_sensitivity_analysis.csv -> max(estimated_uptake_rate)",
                            usage="Subsidy sensitivity summary",
                        ),
                        AnnotatedDatapoint(
                            name=f"Subsidy level for max uptake ({scenario_label})",
                            key=f"subsidy_level_for_max_uptake_pct_{suffix}",
                            value=row.get("subsidy_percentage"),
                            definition="Subsidy percentage associated with maximum modeled uptake (percent).",
                            denominator="N/A",
                            source="data/outputs/subsidy_sensitivity_analysis.csv -> subsidy_percentage at max uptake",
                            usage="Subsidy sensitivity summary",
                        ),
                    ])

            # Minimum payback
            if "payback_years" in sdf.columns:
                payback_series = pd.to_numeric(sdf["payback_years"], errors="coerce")
                if payback_series.notna().any():
                    idx = int(payback_series.idxmin())
                    row = sdf.loc[idx]
                    datapoints.extend([
                        AnnotatedDatapoint(
                            name=f"Minimum payback ({scenario_label})",
                            key=f"subsidy_min_payback_years_{suffix}",
                            value=row.get("payback_years"),
                            definition="Minimum modeled payback across subsidy levels (years).",
                            denominator="N/A",
                            source="data/outputs/subsidy_sensitivity_analysis.csv -> min(payback_years)",
                            usage="Subsidy sensitivity summary",
                        ),
                        AnnotatedDatapoint(
                            name=f"Subsidy level for minimum payback ({scenario_label})",
                            key=f"subsidy_level_for_min_payback_pct_{suffix}",
                            value=row.get("subsidy_percentage"),
                            definition="Subsidy percentage associated with minimum modeled payback (percent).",
                            denominator="N/A",
                            source="data/outputs/subsidy_sensitivity_analysis.csv -> subsidy_percentage at min payback",
                            usage="Subsidy sensitivity summary",
                        ),
                    ])

            # Maximum public expenditure
            if "public_expenditure_total" in sdf.columns:
                spend_series = pd.to_numeric(sdf["public_expenditure_total"], errors="coerce")
                if spend_series.notna().any():
                    idx = int(spend_series.idxmax())
                    row = sdf.loc[idx]
                    datapoints.extend([
                        AnnotatedDatapoint(
                            name=f"Maximum public expenditure ({scenario_label})",
                            key=f"subsidy_max_public_expenditure_total_{suffix}",
                            value=row.get("public_expenditure_total"),
                            definition="Maximum total public expenditure across subsidy levels (GBP).",
                            denominator="All upgraded properties",
                            source="data/outputs/subsidy_sensitivity_analysis.csv -> max(public_expenditure_total)",
                            usage="Subsidy sensitivity summary",
                        ),
                        AnnotatedDatapoint(
                            name=f"Subsidy level for maximum public expenditure ({scenario_label})",
                            key=f"subsidy_level_for_max_public_expenditure_pct_{suffix}",
                            value=row.get("subsidy_percentage"),
                            definition="Subsidy percentage associated with maximum public expenditure (percent).",
                            denominator="N/A",
                            source="data/outputs/subsidy_sensitivity_analysis.csv -> subsidy_percentage at max public expenditure",
                            usage="Subsidy sensitivity summary",
                        ),
                    ])

        # Include full subsidy sensitivity table
        tables = [(df, "Subsidy Sensitivity Analysis - Full Results")]

        return self._render_section(self.SECTION_TITLES[8], datapoints, tables=tables)

    def _build_section_10(
        self,
        borough_df: Optional[pd.DataFrame],
        borough_priority_df: Optional[pd.DataFrame],
        tenure_segmentation_df: Optional[pd.DataFrame],
        heat_network_threshold_df: Optional[pd.DataFrame],
    ) -> Dict[str, Any]:
        """Section 10: Borough-level breakdown and prioritisation."""
        if all(
            df is None or df.empty
            for df in [borough_df, borough_priority_df, tenure_segmentation_df, heat_network_threshold_df]
        ):
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

        datapoints = []
        tables = []

        if borough_df is not None and not borough_df.empty:
            datapoints.append(
                AnnotatedDatapoint(
                    name="Boroughs analyzed",
                    key="boroughs_analyzed",
                    value=len(borough_df),
                    definition="Number of London boroughs in breakdown (count).",
                    denominator="London boroughs",
                    source="data/outputs/borough_breakdown.csv -> row count",
                    usage="Borough coverage",
                )
            )
            tables.append((borough_df, "Borough-Level Breakdown - Full Data"))

        if borough_priority_df is not None and not borough_priority_df.empty:
            top_borough = borough_priority_df.sort_values("rank").iloc[0]
            datapoints.append(
                AnnotatedDatapoint(
                    name="Highest-priority borough",
                    key="top_priority_borough",
                    value=top_borough.get("borough"),
                    definition="Top-ranked borough under the composite priority score (text).",
                    denominator="Borough priority table",
                    source="data/outputs/reports/borough_priority_ranking.csv -> borough",
                    usage="Borough prioritisation summary",
                )
            )
            tables.append((borough_priority_df, "Borough Priority Ranking"))

        if tenure_segmentation_df is not None and not tenure_segmentation_df.empty:
            largest_tenure = tenure_segmentation_df.sort_values("property_count", ascending=False).iloc[0]
            datapoints.append(
                AnnotatedDatapoint(
                    name="Largest tenure group",
                    key="largest_tenure_group",
                    value=largest_tenure.get("tenure_group"),
                    definition="Tenure group with the largest property count in the segmentation table (text).",
                    denominator="Tenure segmentation table",
                    source="data/outputs/reports/tenure_segmentation.csv -> tenure_group",
                    usage="Tenure targeting summary",
                )
            )
            tables.append((tenure_segmentation_df, "Tenure Segmentation"))

        if heat_network_threshold_df is not None and not heat_network_threshold_df.empty:
            viable_df = heat_network_threshold_df[
                heat_network_threshold_df["viable_25yr_threshold"].fillna(False).astype(bool)
            ]
            if not viable_df.empty:
                min_viable = viable_df.sort_values(["tier", "connection_rate"]).iloc[0]
                datapoints.append(
                    AnnotatedDatapoint(
                        name="Minimum viable heat-network connection rate",
                        key="minimum_viable_heat_network_connection_rate_pct",
                        value=float(min_viable.get("connection_rate", 0)) * 100,
                        definition="Lowest modeled connection rate achieving a sub-25-year network payback (percent).",
                        denominator="Heat network threshold scenarios",
                        source="data/outputs/heat_network_connection_thresholds.csv -> connection_rate",
                        usage="Heat network threshold summary",
                    )
                )
            tables.append((heat_network_threshold_df, "Heat Network Connection Thresholds"))

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
                value=self.config.get("resolved_energy_price_profile", {}),
                definition="Current energy prices (£/kWh, dict: {fuel: price}).",
                denominator="N/A",
                source="Configuration / run definition",
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
        for section_id, section_data in self._sections.items():
            for datapoint in section_data.get("datapoints", []):
                glossary_datapoint = dict(datapoint)
                glossary_datapoint["origin_section_id"] = section_id
                glossary_datapoint["key"] = f"{section_id}__{datapoint['key']}"
                all_datapoints.append(glossary_datapoint)

        return {
            "title": self.SECTION_TITLES[12],
            "description": "Comprehensive glossary of all metrics, tier definitions, and thresholds used in Sections 1-12",
            "definitions": {
                "heat_pump_readiness_tiers": {
                    f"tier_{tier}": {
                        "label": TIER_READINESS_LABELS[tier],
                        "interpretation": TIER_READINESS_INTERPRETATIONS[tier],
                    }
                    for tier in range(1, 6)
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
