"""
One-Stop Report Generator

Compiles all required sections (1–13) into a single markdown file by
summarizing existing analysis outputs. The report is intended to be the
single definitive output artifact for downstream consumers.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
from loguru import logger

from config.config import DATA_OUTPUTS_DIR, load_config


@dataclass
class AnnotatedDatapoint:
    name: str
    key: str
    definition: str
    denominator: str
    source: str
    value: Any = None
    usage: Optional[str] = None


def _snake_case(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_")
    return cleaned.lower()


def _format_value(value: Any) -> str:
    if value is None:
        return "Not available"
    if isinstance(value, float) and pd.isna(value):
        return "Not available"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def _render_datapoint(datapoint: AnnotatedDatapoint) -> List[str]:
    lines = [f"- **{datapoint.name}** (`{datapoint.key}`)"]
    lines.append(f"  - Value: {_format_value(datapoint.value)}")
    lines.append(f"  - Definition + unit: {datapoint.definition}")
    lines.append(f"  - Denominator: {datapoint.denominator}")
    lines.append(f"  - Source: {datapoint.source}")
    lines.append(f"  - Report usage: {datapoint.usage or 'Not available'}")
    return lines


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.warning(f"Could not parse JSON from {path}: {exc}")
        return {}


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _read_csv(path: Path) -> Optional[pd.DataFrame]:
    if not path.exists():
        return None
    try:
        return pd.read_csv(path)
    except Exception as exc:
        logger.warning(f"Could not read CSV {path}: {exc}")
        return None


def _parse_numeric_value(value: str) -> Optional[float]:
    cleaned = value.strip()
    if not cleaned:
        return None
    simple_match = re.match(r"^[£$]?\s*[-\d,]+(\.\d+)?%?$", cleaned)
    if not simple_match:
        return None
    cleaned = cleaned.replace("£", "").replace("$", "").replace("%", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_key_value_lines(text: str) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    for line in text.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            if key.strip() and value.strip():
                raw_value = value.strip()
                numeric_value = _parse_numeric_value(raw_value)
                data[_snake_case(key.strip())] = numeric_value if numeric_value is not None else raw_value
    return data


def _parse_archetype_results(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}

    sections: Dict[str, List[str]] = {}
    current_section: Optional[str] = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or set(stripped) == {"="} or set(stripped) == {"-"}:
            continue
        if stripped.isupper():
            current_section = stripped
            sections[current_section] = []
            continue
        if current_section:
            sections[current_section].append(stripped)

    parsed: Dict[str, Any] = {}
    for section, lines in sections.items():
        if not lines:
            continue
        district_match = None
        for line in lines:
            match = re.search(
                r"District/communal heating:\s*([\d,]+)\s*properties\s*\(([\d.]+)%\)",
                line,
                re.IGNORECASE,
            )
            if match:
                district_match = {
                    "count": int(match.group(1).replace(",", "")),
                    "pct": float(match.group(2)),
                }
                break
        parsed_dict = None
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("{") or stripped.startswith("["):
                try:
                    parsed_dict = ast.literal_eval(stripped)
                    break
                except (ValueError, SyntaxError):
                    continue
        if parsed_dict is None:
            joined = " ".join(lines).strip()
            if joined.startswith("{") or joined.startswith("["):
                try:
                    parsed_dict = ast.literal_eval(joined)
                except (ValueError, SyntaxError):
                    parsed_dict = None
        parsed[section] = parsed_dict if parsed_dict is not None else " ".join(lines).strip()
        if district_match:
            parsed[f"{section}__district"] = district_match
    return parsed


def _parse_readiness_summary_text(summary_text: str) -> Dict[str, Any]:
    parsed = _parse_key_value_lines(summary_text)
    if "mean_fabric_pre_requisite_cost" in parsed and "mean_fabric_cost" not in parsed:
        parsed["mean_fabric_cost"] = parsed["mean_fabric_pre_requisite_cost"]
    if "median_fabric_pre_requisite_cost" in parsed and "median_fabric_cost" not in parsed:
        parsed["median_fabric_cost"] = parsed["median_fabric_pre_requisite_cost"]
    total_fabric_match = re.search(r"Total fabric investment needed:\s*£([\d.,]+)M", summary_text)
    if total_fabric_match:
        parsed["total_fabric_cost"] = float(total_fabric_match.group(1).replace(",", "")) * 1_000_000
    total_retrofit_match = re.search(r"Total retrofit investment needed:\s*£([\d.,]+)M", summary_text)
    if total_retrofit_match:
        parsed["total_retrofit_cost"] = float(total_retrofit_match.group(1).replace(",", "")) * 1_000_000
    tier_counts: Dict[int, int] = {}
    tier_percentages: Dict[int, float] = {}
    for line in summary_text.splitlines():
        match = re.match(r"Tier\s+(\d+)\s*:\s*([\d,]+)\s*properties\s*\(([\d.]+)%\)", line)
        if match:
            tier = int(match.group(1))
            tier_counts[tier] = int(match.group(2).replace(",", ""))
            tier_percentages[tier] = float(match.group(3))
    if tier_counts:
        parsed["tier_distribution"] = tier_counts
        parsed["tier_percentages"] = tier_percentages

    needs_patterns = {
        "needs_loft_insulation": r"Need loft insulation:\s*([\d,]+)",
        "needs_wall_insulation": r"Need wall insulation:\s*([\d,]+)",
        "needs_glazing_upgrade": r"Need glazing upgrade:\s*([\d,]+)",
        "needs_radiator_upsizing": r"Need radiator upsizing:\s*([\d,]+)",
    }
    for key, pattern in needs_patterns.items():
        match = re.search(pattern, summary_text)
        if match:
            parsed[key] = int(match.group(1).replace(",", ""))

    pct_patterns = {
        "needs_loft_insulation_pct_all": r"Need loft insulation:\s*[\d,]+\s*\(([\d.]+)% of all properties\)",
        "needs_wall_insulation_pct_all": r"Need wall insulation:\s*[\d,]+\s*\(([\d.]+)% of all properties\)",
        "needs_glazing_upgrade_pct_all": r"Need glazing upgrade:\s*[\d,]+\s*\(([\d.]+)% of all properties\)",
        "needs_radiator_upsizing_pct_all": r"Need radiator upsizing:\s*[\d,]+\s*\(([\d.]+)% of all properties\)",
    }
    for key, pattern in pct_patterns.items():
        match = re.search(pattern, summary_text)
        if match:
            parsed[key] = float(match.group(1))

    non_ready_patterns = {
        "needs_loft_insulation_pct_non_ready": r"Need loft insulation:.*\(([\d.]+)% of non-ready properties\)",
        "needs_wall_insulation_pct_non_ready": r"Need wall insulation:.*\(([\d.]+)% of non-ready properties\)",
        "needs_glazing_upgrade_pct_non_ready": r"Need glazing upgrade:.*\(([\d.]+)% of non-ready properties\)",
        "needs_radiator_upsizing_pct_non_ready": r"Need radiator upsizing:.*\(([\d.]+)% of non-ready properties\)",
    }
    for key, pattern in non_ready_patterns.items():
        match = re.search(pattern, summary_text)
        if match:
            parsed[key] = float(match.group(1))

    solid_match = re.search(r"-\s*Solid wall:\s*([\d,]+)", summary_text)
    cavity_match = re.search(r"-\s*Cavity wall:\s*([\d,]+)", summary_text)
    if solid_match:
        parsed["needs_solid_wall_insulation"] = int(solid_match.group(1).replace(",", ""))
    if cavity_match:
        parsed["needs_cavity_wall_insulation"] = int(cavity_match.group(1).replace(",", ""))

    return parsed


def _extract_readiness_summary(output_dir: Path) -> Dict[str, Any]:
    readiness_csv = output_dir / "retrofit_readiness_analysis.csv"
    df = _read_csv(readiness_csv)
    if df is not None:
        total_properties = len(df)
        tier_counts = df.get("hp_readiness_tier", pd.Series(dtype=int)).value_counts().sort_index()
        tier_distribution = {int(k): int(v) for k, v in tier_counts.to_dict().items()}
        tier_percentages = {
            int(k): float(v / total_properties * 100)
            for k, v in tier_counts.to_dict().items()
        } if total_properties else {}
        tier1_count = tier_distribution.get(1, 0)
        non_ready_count = total_properties - tier1_count

        summary = {
            "total_properties": total_properties,
            "tier_distribution": tier_distribution,
            "tier_percentages": tier_percentages,
            "non_ready_properties": non_ready_count,
            "needs_loft_insulation": int(df.get("needs_loft_topup", pd.Series(dtype=int)).sum()),
            "needs_wall_insulation": int(df.get("needs_wall_insulation", pd.Series(dtype=int)).sum()),
            "needs_solid_wall_insulation": int(
                (df.get("wall_insulation_type", pd.Series(dtype=str)) == "solid_wall_ewi").sum()
            ),
            "needs_cavity_wall_insulation": int(
                (df.get("wall_insulation_type", pd.Series(dtype=str)) == "cavity_wall").sum()
            ),
            "needs_glazing_upgrade": int(df.get("needs_glazing_upgrade", pd.Series(dtype=int)).sum()),
            "needs_radiator_upsizing": int(df.get("needs_radiator_upsizing", pd.Series(dtype=int)).sum()),
            "mean_fabric_cost": float(df["fabric_prerequisite_cost"].mean()) if "fabric_prerequisite_cost" in df.columns else None,
            "median_fabric_cost": float(df["fabric_prerequisite_cost"].median()) if "fabric_prerequisite_cost" in df.columns else None,
            "total_fabric_cost": float(df["fabric_prerequisite_cost"].sum()) if "fabric_prerequisite_cost" in df.columns else None,
            "mean_total_retrofit_cost": float(df["total_retrofit_cost"].mean()) if "total_retrofit_cost" in df.columns else None,
            "median_total_retrofit_cost": float(df["total_retrofit_cost"].median()) if "total_retrofit_cost" in df.columns else None,
            "total_retrofit_cost": float(df["total_retrofit_cost"].sum()) if "total_retrofit_cost" in df.columns else None,
        }
        return summary

    summary_path = output_dir / "reports" / "retrofit_readiness_summary.txt"
    summary_text = _read_text(summary_path)
    if summary_text:
        parsed = _parse_readiness_summary_text(summary_text)
        total_properties = parsed.get("total_properties_analyzed") or parsed.get("total_properties")
        if total_properties is not None:
            parsed["total_properties"] = int(total_properties)
            tier1_count = 0
            tier_distribution = parsed.get("tier_distribution", {})
            if isinstance(tier_distribution, dict):
                tier1_count = tier_distribution.get(1, 0)
            parsed["non_ready_properties"] = max(int(total_properties) - int(tier1_count), 0)
        return parsed

    return {}


def _extract_scenario_results(output_dir: Path) -> Optional[pd.DataFrame]:
    csv_path = output_dir / "scenario_results_summary.csv"
    if csv_path.exists():
        df = _read_csv(csv_path)
        if df is None:
            return None
        scenario_text = _parse_scenario_modeling_results(_read_text(output_dir / "scenario_modeling_results.txt"))
        if scenario_text:
            df = _enrich_scenario_dataframe(df, scenario_text)
        return df

    text_path = output_dir / "scenario_modeling_results.txt"
    if not text_path.exists():
        return None

    scenario_text = _parse_scenario_modeling_results(_read_text(text_path))
    if not scenario_text:
        return None

    df = pd.DataFrame(scenario_text.values())
    if "scenario" not in df.columns:
        df["scenario"] = list(scenario_text.keys())
    return df


def _parse_scenario_modeling_results(text: str) -> Dict[str, Dict[str, Any]]:
    scenarios: Dict[str, Dict[str, Any]] = {}
    current_scenario: Optional[str] = None
    for line in text.splitlines():
        if line.startswith("SCENARIO:"):
            current_scenario = line.split("SCENARIO:", 1)[1].strip()
            scenarios[current_scenario] = {"scenario": current_scenario}
            continue
        if current_scenario and ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            if not key:
                continue
            numeric_value = _parse_numeric_value(value.strip())
            scenarios[current_scenario][_snake_case(key)] = numeric_value if numeric_value is not None else value.strip()
    return scenarios


def _enrich_scenario_dataframe(df: pd.DataFrame, scenario_text: Dict[str, Dict[str, Any]]) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    missing_columns = {"baseline_bill_total", "post_measure_bill_total", "baseline_co2_total_kg", "post_measure_co2_total_kg"}
    missing_columns |= {"baseline_bill_total_low", "baseline_bill_total_high"}
    for col in missing_columns:
        if col not in df.columns:
            df[col] = None
    scenario_lookup = {key: value for key, value in scenario_text.items()}
    for idx, row in df.iterrows():
        scenario_label = row.get("scenario")
        if not scenario_label or scenario_label not in scenario_lookup:
            continue
        text_row = scenario_lookup[scenario_label]
        for col in missing_columns:
            if pd.isna(row.get(col)) and col in text_row:
                df.at[idx, col] = text_row[col]
    return df


class OneStopReportGenerator:
    """Generate a one-stop markdown report from analysis outputs."""

    SECTION_TITLES = [
        "Section 1: Fabric Detail Granularity",
        "Section 2: Retrofit Measures & Packages",
        "Section 3: Radiator Upsizing",
        "Section 4: Window Upgrades (Double vs Triple Glazing)",
        "Section 5: Payback Times",
        "Section 6: Pathways & Hybrid Scenarios",
        "Section 7: EPC Data Robustness (Anomalies & Uncertainty)",
        "Section 8: Fabric Tipping Point Curve",
        "Section 9: Load Profiles & System Impacts",
        "Section 10: Heat Network Penetration & Price Sensitivity",
        "Section 11: Tenure Filtering",
        "Section 12: Documentation & Tests",
        "Section 13: Metadata Notes & Caveats",
    ]

    SCENARIO_FIELD_METADATA: Dict[str, Dict[str, str]] = {
        "scenario_id": {
            "definition": "Scenario identifier from config (string).",
            "denominator": "N/A",
            "usage": "Scenario reference",
        },
        "scenario": {
            "definition": "Scenario label (string).",
            "denominator": "N/A",
            "usage": "Scenario reference",
        },
        "total_properties": {
            "definition": "Total properties modeled (count).",
            "denominator": "All properties in scenario",
            "usage": "Scenario scale",
        },
        "capital_cost_total": {
            "definition": "Total capital expenditure (GBP).",
            "denominator": "All properties in scenario",
            "usage": "CAPEX totals",
        },
        "capital_cost_per_property": {
            "definition": "Average capital expenditure per property (GBP).",
            "denominator": "All properties in scenario",
            "usage": "CAPEX intensity",
        },
        "annual_energy_reduction_kwh": {
            "definition": "Total annual energy reduction (kWh).",
            "denominator": "All properties in scenario",
            "usage": "Energy impact",
        },
        "annual_co2_reduction_kg": {
            "definition": "Total annual CO₂ reduction (kg).",
            "denominator": "All properties in scenario",
            "usage": "Carbon impact",
        },
        "cost_per_tco2_20yr_gbp": {
            "definition": "Cost per tonne of CO₂ abated over 20-year horizon (GBP/tCO₂).",
            "denominator": "Total CO₂ abatement over horizon",
            "usage": "Cost-effectiveness",
        },
        "annual_bill_savings": {
            "definition": "Total annual bill savings (GBP).",
            "denominator": "All properties in scenario",
            "usage": "Bill impact",
        },
        "annual_bill_savings_low": {
            "definition": "Low estimate of annual bill savings (GBP).",
            "denominator": "All properties in scenario",
            "usage": "Bill impact (low)",
        },
        "annual_bill_savings_high": {
            "definition": "High estimate of annual bill savings (GBP).",
            "denominator": "All properties in scenario",
            "usage": "Bill impact (high)",
        },
        "baseline_bill_total": {
            "definition": "Baseline annual bill total before measures (GBP).",
            "denominator": "All properties in scenario",
            "usage": "Baseline bill total",
        },
        "post_measure_bill_total": {
            "definition": "Post-measure annual bill total (GBP).",
            "denominator": "All properties in scenario",
            "usage": "Post-measure bill total",
        },
        "post_measure_bill_total_low": {
            "definition": "Low estimate of post-measure annual bill total (GBP).",
            "denominator": "All properties in scenario",
            "usage": "Post-measure bill total (low)",
        },
        "post_measure_bill_total_high": {
            "definition": "High estimate of post-measure annual bill total (GBP).",
            "denominator": "All properties in scenario",
            "usage": "Post-measure bill total (high)",
        },
        "baseline_co2_total_kg": {
            "definition": "Baseline annual CO₂ total before measures (kg).",
            "denominator": "All properties in scenario",
            "usage": "Baseline CO₂ total",
        },
        "post_measure_co2_total_kg": {
            "definition": "Post-measure annual CO₂ total (kg).",
            "denominator": "All properties in scenario",
            "usage": "Post-measure CO₂ total",
        },
        "post_measure_co2_total_kg_low": {
            "definition": "Low estimate of post-measure annual CO₂ total (kg).",
            "denominator": "All properties in scenario",
            "usage": "Post-measure CO₂ total (low)",
        },
        "post_measure_co2_total_kg_high": {
            "definition": "High estimate of post-measure annual CO₂ total (kg).",
            "denominator": "All properties in scenario",
            "usage": "Post-measure CO₂ total (high)",
        },
        "heat_pump_electricity_total_kwh": {
            "definition": "Total electricity consumption for heat pumps (kWh).",
            "denominator": "All properties with heat pumps",
            "usage": "Heat pump load",
        },
        "heat_pump_electricity_total_kwh_low": {
            "definition": "Low estimate of heat pump electricity consumption (kWh).",
            "denominator": "All properties with heat pumps",
            "usage": "Heat pump load (low)",
        },
        "heat_pump_electricity_total_kwh_high": {
            "definition": "High estimate of heat pump electricity consumption (kWh).",
            "denominator": "All properties with heat pumps",
            "usage": "Heat pump load (high)",
        },
        "average_payback_years": {
            "definition": "Average simple payback time for cost-effective homes (years).",
            "denominator": "Cost-effective properties in scenario",
            "usage": "Payback analysis",
        },
        "median_payback_years": {
            "definition": "Median simple payback time for cost-effective homes (years).",
            "denominator": "Cost-effective properties in scenario",
            "usage": "Payback analysis",
        },
        "upgrade_recommended_count": {
            "definition": "Count of properties recommended for upgrade (count).",
            "denominator": "All properties in scenario",
            "usage": "Upgrade recommendation",
        },
        "upgrade_recommended_pct": {
            "definition": "Share of properties recommended for upgrade (percent).",
            "denominator": "All properties in scenario",
            "usage": "Upgrade recommendation",
        },
        "cost_effective_count": {
            "definition": "Count of cost-effective properties (count).",
            "denominator": "All properties in scenario",
            "usage": "Cost-effectiveness",
        },
        "cost_effective_pct": {
            "definition": "Share of cost-effective properties (percent).",
            "denominator": "All properties in scenario",
            "usage": "Cost-effectiveness",
        },
        "not_cost_effective_count": {
            "definition": "Count of non cost-effective properties (count).",
            "denominator": "All properties in scenario",
            "usage": "Cost-effectiveness",
        },
        "not_cost_effective_pct": {
            "definition": "Share of non cost-effective properties (percent).",
            "denominator": "All properties in scenario",
            "usage": "Cost-effectiveness",
        },
        "carbon_abatement_cost_mean": {
            "definition": "Mean carbon abatement cost (GBP/tCO₂).",
            "denominator": "Cost-effective properties in scenario",
            "usage": "Carbon cost",
        },
        "carbon_abatement_cost_median": {
            "definition": "Median carbon abatement cost (GBP/tCO₂).",
            "denominator": "Cost-effective properties in scenario",
            "usage": "Carbon cost",
        },
        "band_c_or_better_before_pct": {
            "definition": "Share of properties at EPC band C or better before intervention (percent).",
            "denominator": "All properties in scenario",
            "usage": "EPC shift",
        },
        "band_c_or_better_after_pct": {
            "definition": "Share of properties at EPC band C or better after intervention (percent).",
            "denominator": "All properties in scenario",
            "usage": "EPC shift",
        },
        "ashp_ready_properties": {
            "definition": "Count of properties already ASHP-ready (count).",
            "denominator": "All properties in scenario",
            "usage": "HP readiness",
        },
        "ashp_ready_pct": {
            "definition": "Share of properties already ASHP-ready (percent).",
            "denominator": "All properties in scenario",
            "usage": "HP readiness",
        },
        "ashp_fabric_required_properties": {
            "definition": "Count of properties requiring fabric upgrades for ASHP (count).",
            "denominator": "All properties in scenario",
            "usage": "HP readiness",
        },
        "ashp_not_ready_properties": {
            "definition": "Count of properties not suitable for ASHP (count).",
            "denominator": "All properties in scenario",
            "usage": "HP readiness",
        },
        "ashp_fabric_applied_properties": {
            "definition": "Count of properties where fabric was applied to enable ASHP (count).",
            "denominator": "All properties in scenario",
            "usage": "HP readiness",
        },
        "ashp_not_eligible_properties": {
            "definition": "Count of properties where ASHP was removed after fabric (count).",
            "denominator": "All properties in scenario",
            "usage": "HP readiness",
        },
        "hn_ready_properties": {
            "definition": "Count of properties flagged as heat-network ready (count).",
            "denominator": "All properties in scenario",
            "usage": "Heat network readiness",
        },
        "hn_assigned_properties": {
            "definition": "Count of properties assigned to heat networks in hybrid scenario (count).",
            "denominator": "All properties in scenario",
            "usage": "Hybrid routing split",
        },
        "ashp_assigned_properties": {
            "definition": "Count of properties assigned to ASHPs in hybrid scenario (count).",
            "denominator": "All properties in scenario",
            "usage": "Hybrid routing split",
        },
    }

    def __init__(
        self,
        output_dir: Optional[Path] = None,
        config: Optional[Dict[str, Any]] = None,
        archetype_results: Optional[Dict[str, Any]] = None,
    ):
        self.output_dir = Path(output_dir) if output_dir else DATA_OUTPUTS_DIR
        self.config = config or load_config()
        self.header_text = self.config.get("reporting", {}).get("one_stop_header_text", "")
        if not self.header_text:
            self.header_text = "Heat Street — One-Stop Report"
        self.output_path = self.output_dir / "one_stop_output.md"
        self.archetype_results = archetype_results
        self._collected_datapoints: List[AnnotatedDatapoint] = []

    def generate(self) -> Path:
        logger.info("Generating one-stop report...")

        lines: List[str] = []
        if self.header_text:
            lines.append(self.header_text)
            lines.append("")

        lines.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
        lines.append("")

        run_metadata = _read_json(self.output_dir / "run_metadata.json")
        archetype_results = self.archetype_results
        if archetype_results is None:
            archetype_json = _read_json(self.output_dir / "archetype_analysis_results.json")
            archetype_results = archetype_json if archetype_json else _parse_archetype_results(
                self.output_dir / "archetype_analysis_results.txt"
            )
        readiness_summary = _extract_readiness_summary(self.output_dir)
        scenario_df = _extract_scenario_results(self.output_dir)

        lines.extend(self._build_section_1(archetype_results))
        lines.extend(self._build_section_2(readiness_summary))
        lines.extend(self._build_section_3(readiness_summary))
        lines.extend(self._build_section_4(readiness_summary))
        lines.extend(self._build_section_5(scenario_df))
        lines.extend(self._build_section_6(scenario_df))
        lines.extend(self._build_section_7(run_metadata))
        lines.extend(self._build_section_8())
        lines.extend(self._build_section_9())
        lines.extend(self._build_section_10())
        lines.extend(self._build_section_11())
        lines.extend(self._build_section_12(run_metadata))
        lines.extend(self._build_section_13())

        self._validate_datapoints()

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        logger.info(f"One-stop report written to {self.output_path}")
        return self.output_path

    def _render_section(self, title: str, datapoints: Iterable[AnnotatedDatapoint]) -> List[str]:
        lines = [f"## {title}", ""]
        datapoints_list = list(datapoints)
        if datapoints_list:
            self._collected_datapoints.extend(datapoints_list)
        if not datapoints_list:
            lines.append("_No datapoints available from current outputs._")
            lines.append("")
            return lines
        for datapoint in datapoints_list:
            lines.extend(_render_datapoint(datapoint))
        lines.append("")
        return lines

    def _validate_datapoints(self) -> None:
        missing_keys = [
            dp.key
            for dp in self._collected_datapoints
            if dp.value is None or (isinstance(dp.value, float) and pd.isna(dp.value))
        ]
        if missing_keys:
            logger.warning(
                "Missing required datapoints in one-stop report: "
                + ", ".join(sorted(set(missing_keys)))
            )

    @staticmethod
    def _get_archetype_section(archetype_results: Dict[str, Any], *keys: str) -> Any:
        if not isinstance(archetype_results, dict):
            return {}
        for key in keys:
            if key in archetype_results:
                return archetype_results[key]
        return {}

    @staticmethod
    def _percentage_of_total(
        numerator: Optional[float],
        denominator: Optional[float],
        fallback: Optional[float] = None,
    ) -> Optional[float]:
        if fallback is not None:
            return float(fallback)
        if numerator is None or denominator in (None, 0):
            return None
        return float(numerator) / float(denominator) * 100

    @staticmethod
    def _clean_value(value: Any) -> Any:
        if isinstance(value, float) and pd.isna(value):
            return None
        return value

    @staticmethod
    def _is_hybrid_scenario(scenario_id: Optional[str], scenario_label: str) -> bool:
        if scenario_id and "hybrid" in str(scenario_id).lower():
            return True
        return "hybrid" in str(scenario_label).lower()

    def _build_section_1(self, archetype_results: Dict[str, Any]) -> List[str]:
        epc_bands = self._get_archetype_section(archetype_results, "EPC BANDS", "epc_bands")
        sap_scores = self._get_archetype_section(archetype_results, "SAP SCORES", "sap_scores")
        wall_data = self._get_archetype_section(archetype_results, "WALL CONSTRUCTION", "wall_construction")
        loft_data = self._get_archetype_section(archetype_results, "LOFT INSULATION", "loft_insulation")
        glazing_data = self._get_archetype_section(archetype_results, "GLAZING", "glazing")
        heating_data = self._get_archetype_section(archetype_results, "HEATING SYSTEMS", "heating_systems")
        district_line = (
            archetype_results.get("HEATING SYSTEMS__district")
            if isinstance(archetype_results, dict)
            else None
        )

        epc_distribution = None
        if isinstance(epc_bands, dict):
            counts = epc_bands.get("frequency", {})
            pcts = epc_bands.get("percentage", {})
            if counts or pcts:
                epc_distribution = {
                    band: {
                        "count": counts.get(band),
                        "pct": pcts.get(band),
                    }
                    for band in sorted(set(counts.keys()) | set(pcts.keys()))
                }

        sap_range = None
        if isinstance(sap_scores, dict) and sap_scores.get("min") is not None and sap_scores.get("max") is not None:
            sap_range = {"min": sap_scores.get("min"), "max": sap_scores.get("max")}

        wall_types = wall_data.get("wall_types") if isinstance(wall_data, dict) else None
        loft_distribution = None
        if isinstance(loft_data, dict):
            loft_distribution = {
                "categories": loft_data.get("categories"),
                "percentages": loft_data.get("percentages"),
            }
        glazing_distribution = None
        if isinstance(glazing_data, dict):
            glazing_distribution = {
                "types": glazing_data.get("types"),
                "percentages": glazing_data.get("percentages"),
            }
        heating_distribution = None
        if isinstance(heating_data, dict):
            heating_distribution = {
                "types": heating_data.get("types"),
                "percentages": heating_data.get("percentages"),
            }
            if district_line and isinstance(district_line, dict):
                types = heating_distribution.get("types", {}) or {}
                pcts = heating_distribution.get("percentages", {}) or {}
                district_label = "District/Communal/Heat Network"
                if district_label not in types:
                    types = dict(types)
                    pcts = dict(pcts)
                    types[district_label] = district_line.get("count")
                    pcts[district_label] = district_line.get("pct")
                    heating_distribution["types"] = types
                    heating_distribution["percentages"] = pcts

        datapoints = [
            AnnotatedDatapoint(
                name="EPC band distribution",
                key="epc_band_distribution",
                value=epc_distribution,
                definition="EPC band distribution with counts and percentages (dict).",
                denominator="All properties in archetype analysis",
                source="data/outputs/archetype_analysis_results.txt|json -> EPC BANDS.frequency/percentage",
                usage="Baseline EPC profiling",
            ),
            AnnotatedDatapoint(
                name="SAP score mean",
                key="sap_score_mean",
                value=sap_scores.get("mean") if isinstance(sap_scores, dict) else None,
                definition="Mean SAP score (score).",
                denominator="All properties in archetype analysis",
                source="data/outputs/archetype_analysis_results.txt|json -> SAP SCORES.mean",
                usage="Energy efficiency baseline",
            ),
            AnnotatedDatapoint(
                name="SAP score median",
                key="sap_score_median",
                value=sap_scores.get("median") if isinstance(sap_scores, dict) else None,
                definition="Median SAP score (score).",
                denominator="All properties in archetype analysis",
                source="data/outputs/archetype_analysis_results.txt|json -> SAP SCORES.median",
                usage="Energy efficiency baseline",
            ),
            AnnotatedDatapoint(
                name="SAP score range",
                key="sap_score_range",
                value=sap_range,
                definition="SAP score range (min/max).",
                denominator="All properties in archetype analysis",
                source="data/outputs/archetype_analysis_results.txt|json -> SAP SCORES.min/max",
                usage="Energy efficiency spread",
            ),
            AnnotatedDatapoint(
                name="Wall type distribution",
                key="wall_type_distribution",
                value=wall_types,
                definition="Wall construction type counts (dict).",
                denominator="All properties in archetype analysis",
                source="data/outputs/archetype_analysis_results.txt|json -> WALL CONSTRUCTION.wall_types",
                usage="Fabric typology",
            ),
            AnnotatedDatapoint(
                name="Wall insulation rate",
                key="wall_insulation_rate_pct",
                value=wall_data.get("insulation_rate") if isinstance(wall_data, dict) else None,
                definition="Share of properties with insulated walls (percent).",
                denominator="All properties in archetype analysis",
                source="data/outputs/archetype_analysis_results.txt|json -> WALL CONSTRUCTION.insulation_rate",
                usage="Fabric upgrade targeting",
            ),
            AnnotatedDatapoint(
                name="Loft/roof status distribution",
                key="loft_status_distribution",
                value=loft_distribution,
                definition="Loft insulation categories and percentages (dict).",
                denominator="All properties in archetype analysis",
                source="data/outputs/archetype_analysis_results.txt|json -> LOFT INSULATION.categories/percentages",
                usage="Roof retrofit readiness",
            ),
            AnnotatedDatapoint(
                name="Glazing distribution",
                key="glazing_distribution",
                value=glazing_distribution,
                definition="Window glazing types and percentages (dict).",
                denominator="All properties in archetype analysis",
                source="data/outputs/archetype_analysis_results.txt|json -> GLAZING.types/percentages",
                usage="Window upgrade planning",
            ),
            AnnotatedDatapoint(
                name="Heating system distribution",
                key="heating_system_distribution",
                value=heating_distribution,
                definition="Primary heating system types and percentages (dict).",
                denominator="All properties in archetype analysis",
                source="data/outputs/archetype_analysis_results.txt|json -> HEATING SYSTEMS.types/percentages",
                usage="Heating system baseline",
            ),
        ]
        return self._render_section(self.SECTION_TITLES[0], datapoints)

    def _build_section_2(self, readiness_summary: Dict[str, Any]) -> List[str]:
        total_properties = readiness_summary.get("total_properties")
        non_ready_properties = readiness_summary.get("non_ready_properties")
        datapoints = [
            AnnotatedDatapoint(
                name="Total properties assessed",
                key="readiness_total_properties",
                value=total_properties,
                definition="Total properties in retrofit readiness assessment (count).",
                denominator="All properties assessed for readiness",
                source="data/outputs/retrofit_readiness_analysis.csv -> rows (fallback: data/outputs/reports/retrofit_readiness_summary.txt)",
                usage="Readiness cohort size",
            ),
            AnnotatedDatapoint(
                name="Non-ready properties",
                key="readiness_non_ready_properties",
                value=non_ready_properties,
                definition="Total non-ready properties (Tier 2-5) (count).",
                denominator="All properties assessed for readiness",
                source="data/outputs/retrofit_readiness_analysis.csv -> hp_readiness_tier (fallback: data/outputs/reports/retrofit_readiness_summary.txt)",
                usage="Readiness denominator for interventions",
            ),
            AnnotatedDatapoint(
                name="Mean fabric prerequisite cost",
                key="mean_fabric_prerequisite_cost_gbp",
                value=readiness_summary.get("mean_fabric_cost"),
                definition="Average fabric prerequisite cost before heat pump readiness (GBP per property).",
                denominator="All properties assessed for readiness",
                source="data/outputs/retrofit_readiness_analysis.csv -> fabric_prerequisite_cost (fallback: data/outputs/reports/retrofit_readiness_summary.txt)",
                usage="Retrofit package economics",
            ),
            AnnotatedDatapoint(
                name="Median fabric prerequisite cost",
                key="median_fabric_prerequisite_cost_gbp",
                value=readiness_summary.get("median_fabric_cost"),
                definition="Median fabric prerequisite cost before heat pump readiness (GBP per property).",
                denominator="All properties assessed for readiness",
                source="data/outputs/retrofit_readiness_analysis.csv -> fabric_prerequisite_cost (fallback: data/outputs/reports/retrofit_readiness_summary.txt)",
                usage="Retrofit package economics",
            ),
            AnnotatedDatapoint(
                name="Total fabric prerequisite cost",
                key="total_fabric_prerequisite_cost_gbp",
                value=readiness_summary.get("total_fabric_cost"),
                definition="Total fabric prerequisite cost across all properties (GBP).",
                denominator="All properties assessed for readiness",
                source="data/outputs/retrofit_readiness_analysis.csv -> fabric_prerequisite_cost (fallback: data/outputs/reports/retrofit_readiness_summary.txt)",
                usage="Capital requirement",
            ),
            AnnotatedDatapoint(
                name="Mean total retrofit cost",
                key="mean_total_retrofit_cost_gbp",
                value=readiness_summary.get("mean_total_retrofit_cost"),
                definition="Average total retrofit cost including heat pump measures (GBP per property).",
                denominator="All properties assessed for readiness",
                source="data/outputs/retrofit_readiness_analysis.csv -> total_retrofit_cost (fallback: data/outputs/reports/retrofit_readiness_summary.txt)",
                usage="Retrofit package economics",
            ),
            AnnotatedDatapoint(
                name="Median total retrofit cost",
                key="median_total_retrofit_cost_gbp",
                value=readiness_summary.get("median_total_retrofit_cost"),
                definition="Median total retrofit cost including heat pump measures (GBP per property).",
                denominator="All properties assessed for readiness",
                source="data/outputs/retrofit_readiness_analysis.csv -> total_retrofit_cost (fallback: data/outputs/reports/retrofit_readiness_summary.txt)",
                usage="Retrofit package economics",
            ),
            AnnotatedDatapoint(
                name="Total retrofit cost",
                key="total_retrofit_cost_gbp",
                value=readiness_summary.get("total_retrofit_cost"),
                definition="Total retrofit cost across all properties (GBP).",
                denominator="All properties assessed for readiness",
                source="data/outputs/retrofit_readiness_analysis.csv -> total_retrofit_cost (fallback: data/outputs/reports/retrofit_readiness_summary.txt)",
                usage="Capital requirement",
            ),
            AnnotatedDatapoint(
                name="Properties needing loft insulation (count)",
                key="needs_loft_insulation_count",
                value=readiness_summary.get("needs_loft_insulation"),
                definition="Count of properties needing loft insulation (count).",
                denominator="All properties assessed for readiness",
                source="data/outputs/retrofit_readiness_analysis.csv -> needs_loft_topup (fallback: data/outputs/reports/retrofit_readiness_summary.txt)",
                usage="Fabric intervention scope",
            ),
            AnnotatedDatapoint(
                name="Properties needing loft insulation (% of all)",
                key="needs_loft_insulation_pct_all",
                value=self._percentage_of_total(
                    readiness_summary.get("needs_loft_insulation"),
                    total_properties,
                    readiness_summary.get("needs_loft_insulation_pct_all"),
                ),
                definition="Share of properties needing loft insulation (percent of all).",
                denominator="All properties assessed for readiness",
                source="data/outputs/retrofit_readiness_analysis.csv -> needs_loft_topup (fallback: data/outputs/reports/retrofit_readiness_summary.txt)",
                usage="Fabric intervention share",
            ),
            AnnotatedDatapoint(
                name="Properties needing loft insulation (% of non-ready)",
                key="needs_loft_insulation_pct_non_ready",
                value=self._percentage_of_total(
                    readiness_summary.get("needs_loft_insulation"),
                    non_ready_properties,
                    readiness_summary.get("needs_loft_insulation_pct_non_ready"),
                ),
                definition="Share of non-ready properties needing loft insulation (percent of non-ready).",
                denominator="Non-ready properties (Tier 2-5)",
                source="data/outputs/retrofit_readiness_analysis.csv -> needs_loft_topup (fallback: data/outputs/reports/retrofit_readiness_summary.txt)",
                usage="Fabric intervention share (non-ready)",
            ),
            AnnotatedDatapoint(
                name="Properties needing wall insulation (count)",
                key="needs_wall_insulation_count",
                value=readiness_summary.get("needs_wall_insulation"),
                definition="Count of properties needing wall insulation (count).",
                denominator="All properties assessed for readiness",
                source="data/outputs/retrofit_readiness_analysis.csv -> needs_wall_insulation (fallback: data/outputs/reports/retrofit_readiness_summary.txt)",
                usage="Fabric intervention scope",
            ),
            AnnotatedDatapoint(
                name="Properties needing wall insulation (% of all)",
                key="needs_wall_insulation_pct_all",
                value=self._percentage_of_total(
                    readiness_summary.get("needs_wall_insulation"),
                    total_properties,
                    readiness_summary.get("needs_wall_insulation_pct_all"),
                ),
                definition="Share of properties needing wall insulation (percent of all).",
                denominator="All properties assessed for readiness",
                source="data/outputs/retrofit_readiness_analysis.csv -> needs_wall_insulation (fallback: data/outputs/reports/retrofit_readiness_summary.txt)",
                usage="Fabric intervention share",
            ),
            AnnotatedDatapoint(
                name="Properties needing wall insulation (% of non-ready)",
                key="needs_wall_insulation_pct_non_ready",
                value=self._percentage_of_total(
                    readiness_summary.get("needs_wall_insulation"),
                    non_ready_properties,
                    readiness_summary.get("needs_wall_insulation_pct_non_ready"),
                ),
                definition="Share of non-ready properties needing wall insulation (percent of non-ready).",
                denominator="Non-ready properties (Tier 2-5)",
                source="data/outputs/retrofit_readiness_analysis.csv -> needs_wall_insulation (fallback: data/outputs/reports/retrofit_readiness_summary.txt)",
                usage="Fabric intervention share (non-ready)",
            ),
            AnnotatedDatapoint(
                name="Solid wall insulation needs",
                key="needs_solid_wall_insulation",
                value=readiness_summary.get("needs_solid_wall_insulation"),
                definition="Count of properties needing solid wall insulation (count).",
                denominator="Properties needing wall insulation",
                source="data/outputs/retrofit_readiness_analysis.csv -> wall_insulation_type (fallback: data/outputs/reports/retrofit_readiness_summary.txt)",
                usage="Wall insulation targeting",
            ),
            AnnotatedDatapoint(
                name="Cavity wall insulation needs",
                key="needs_cavity_wall_insulation",
                value=readiness_summary.get("needs_cavity_wall_insulation"),
                definition="Count of properties needing cavity wall insulation (count).",
                denominator="Properties needing wall insulation",
                source="data/outputs/retrofit_readiness_analysis.csv -> wall_insulation_type (fallback: data/outputs/reports/retrofit_readiness_summary.txt)",
                usage="Wall insulation targeting",
            ),
        ]
        return self._render_section(self.SECTION_TITLES[1], datapoints)

    def _build_section_3(self, readiness_summary: Dict[str, Any]) -> List[str]:
        total_properties = readiness_summary.get("total_properties")
        non_ready_properties = readiness_summary.get("non_ready_properties")
        datapoints = [
            AnnotatedDatapoint(
                name="Properties needing radiator upsizing",
                key="needs_radiator_upsizing",
                value=readiness_summary.get("needs_radiator_upsizing"),
                definition="Count of properties flagged for radiator upsizing (count).",
                denominator="All properties assessed for readiness",
                source="data/outputs/retrofit_readiness_analysis.csv -> needs_radiator_upsizing (fallback: data/outputs/reports/retrofit_readiness_summary.txt)",
                usage="Emitter readiness diagnostics",
            ),
            AnnotatedDatapoint(
                name="Radiator upsizing (% of all properties)",
                key="needs_radiator_upsizing_pct_all",
                value=self._percentage_of_total(
                    readiness_summary.get("needs_radiator_upsizing"),
                    total_properties,
                    readiness_summary.get("needs_radiator_upsizing_pct_all"),
                ),
                definition="Share of properties needing radiator upsizing (percent of all).",
                denominator="All properties assessed for readiness",
                source="data/outputs/retrofit_readiness_analysis.csv -> needs_radiator_upsizing (fallback: data/outputs/reports/retrofit_readiness_summary.txt)",
                usage="Emitter readiness share",
            ),
            AnnotatedDatapoint(
                name="Radiator upsizing (% of non-ready properties)",
                key="needs_radiator_upsizing_pct_non_ready",
                value=self._percentage_of_total(
                    readiness_summary.get("needs_radiator_upsizing"),
                    non_ready_properties,
                    readiness_summary.get("needs_radiator_upsizing_pct_non_ready"),
                ),
                definition="Share of non-ready properties needing radiator upsizing (percent of non-ready).",
                denominator="Non-ready properties (Tier 2-5)",
                source="data/outputs/retrofit_readiness_analysis.csv -> needs_radiator_upsizing (fallback: data/outputs/reports/retrofit_readiness_summary.txt)",
                usage="Emitter readiness share (non-ready)",
            ),
        ]
        return self._render_section(self.SECTION_TITLES[2], datapoints)

    def _build_section_4(self, readiness_summary: Dict[str, Any]) -> List[str]:
        total_properties = readiness_summary.get("total_properties")
        non_ready_properties = readiness_summary.get("non_ready_properties")
        datapoints = [
            AnnotatedDatapoint(
                name="Properties needing glazing upgrade",
                key="needs_glazing_upgrade",
                value=readiness_summary.get("needs_glazing_upgrade"),
                definition="Count of properties flagged for glazing upgrade (count).",
                denominator="All properties assessed for readiness",
                source="data/outputs/retrofit_readiness_analysis.csv -> needs_glazing_upgrade (fallback: data/outputs/reports/retrofit_readiness_summary.txt)",
                usage="Window upgrade planning",
            ),
            AnnotatedDatapoint(
                name="Glazing upgrades (% of all properties)",
                key="needs_glazing_upgrade_pct_all",
                value=self._percentage_of_total(
                    readiness_summary.get("needs_glazing_upgrade"),
                    total_properties,
                    readiness_summary.get("needs_glazing_upgrade_pct_all"),
                ),
                definition="Share of properties needing glazing upgrade (percent of all).",
                denominator="All properties assessed for readiness",
                source="data/outputs/retrofit_readiness_analysis.csv -> needs_glazing_upgrade (fallback: data/outputs/reports/retrofit_readiness_summary.txt)",
                usage="Window upgrade share",
            ),
            AnnotatedDatapoint(
                name="Glazing upgrades (% of non-ready properties)",
                key="needs_glazing_upgrade_pct_non_ready",
                value=self._percentage_of_total(
                    readiness_summary.get("needs_glazing_upgrade"),
                    non_ready_properties,
                    readiness_summary.get("needs_glazing_upgrade_pct_non_ready"),
                ),
                definition="Share of non-ready properties needing glazing upgrade (percent of non-ready).",
                denominator="Non-ready properties (Tier 2-5)",
                source="data/outputs/retrofit_readiness_analysis.csv -> needs_glazing_upgrade (fallback: data/outputs/reports/retrofit_readiness_summary.txt)",
                usage="Window upgrade share (non-ready)",
            ),
        ]
        return self._render_section(self.SECTION_TITLES[3], datapoints)

    def _build_section_5(self, scenario_df: Optional[pd.DataFrame]) -> List[str]:
        datapoints: List[AnnotatedDatapoint] = []
        if scenario_df is not None:
            for _, row in scenario_df.iterrows():
                scenario_label = row.get("scenario") or row.get("scenario_id") or "scenario"
                datapoints.extend(
                    [
                        AnnotatedDatapoint(
                            name=f"Average payback years ({scenario_label})",
                            key=f"average_payback_years_{_snake_case(str(scenario_label))}",
                            value=self._clean_value(row.get("average_payback_years")),
                            definition=self.SCENARIO_FIELD_METADATA["average_payback_years"]["definition"],
                            denominator=self.SCENARIO_FIELD_METADATA["average_payback_years"]["denominator"],
                            source="data/outputs/scenario_results_summary.csv -> average_payback_years",
                            usage=self.SCENARIO_FIELD_METADATA["average_payback_years"]["usage"],
                        ),
                        AnnotatedDatapoint(
                            name=f"Median payback years ({scenario_label})",
                            key=f"median_payback_years_{_snake_case(str(scenario_label))}",
                            value=self._clean_value(row.get("median_payback_years")),
                            definition=self.SCENARIO_FIELD_METADATA["median_payback_years"]["definition"],
                            denominator=self.SCENARIO_FIELD_METADATA["median_payback_years"]["denominator"],
                            source="data/outputs/scenario_results_summary.csv -> median_payback_years",
                            usage=self.SCENARIO_FIELD_METADATA["median_payback_years"]["usage"],
                        ),
                    ]
                )
        return self._render_section(self.SECTION_TITLES[4], datapoints)

    def _build_section_6(self, scenario_df: Optional[pd.DataFrame]) -> List[str]:
        datapoints: List[AnnotatedDatapoint] = []
        if scenario_df is not None:
            for _, row in scenario_df.iterrows():
                scenario_label = row.get("scenario") or row.get("scenario_id") or "scenario"
                scenario_id = row.get("scenario_id")
                is_hybrid = self._is_hybrid_scenario(scenario_id, scenario_label)
                for field in scenario_df.columns:
                    metadata = self.SCENARIO_FIELD_METADATA.get(field, {})
                    definition = metadata.get("definition", "Scenario summary metric.")
                    denominator = metadata.get("denominator", "All properties in scenario")
                    usage = metadata.get("usage", "Scenario summary")
                    value = self._clean_value(row.get(field))
                    if field in {"hn_assigned_properties", "ashp_assigned_properties"} and not is_hybrid:
                        value = "N/A (not hybrid)"
                    datapoints.append(
                        AnnotatedDatapoint(
                            name=f"{field.replace('_', ' ').title()} ({scenario_label})",
                            key=f"{field}_{_snake_case(str(scenario_label))}",
                            value=value,
                            definition=definition,
                            denominator=denominator,
                            source=f"data/outputs/scenario_results_summary.csv -> {field}",
                            usage=usage,
                        )
                    )
        return self._render_section(self.SECTION_TITLES[5], datapoints)

    def _build_section_7(self, run_metadata: Dict[str, Any]) -> List[str]:
        warning_count = len(run_metadata.get("warnings", [])) if run_metadata else 0
        datapoints = [
            AnnotatedDatapoint(
                name="Metadata warnings",
                key="metadata_warning_count",
                value=warning_count,
                definition="Number of warnings recorded during processing (count).",
                denominator="All pipeline stages",
                source="data/outputs/run_metadata.json -> warnings",
                usage="Data robustness monitoring",
            )
        ]
        return self._render_section(self.SECTION_TITLES[6], datapoints)

    def _build_section_8(self) -> List[str]:
        curve_path = self.output_dir / "fabric_tipping_point_curve.csv"
        df = _read_csv(curve_path)
        datapoints = []
        if df is not None and not df.empty:
            datapoints.append(
                AnnotatedDatapoint(
                    name="Tipping point curve steps",
                    key="tipping_point_curve_steps",
                    value=len(df),
                    definition="Number of steps in the fabric tipping point curve (count).",
                    denominator="Fabric measures modeled",
                    source="data/outputs/fabric_tipping_point_curve.csv -> rows",
                    usage="Fabric investment curve",
                )
            )
        return self._render_section(self.SECTION_TITLES[7], datapoints)

    def _build_section_9(self) -> List[str]:
        summary_path = self.output_dir / "pathway_load_profile_summary.csv"
        df = _read_csv(summary_path)
        datapoints = []
        if df is not None and not df.empty:
            row = df.iloc[0]
            datapoints.append(
                AnnotatedDatapoint(
                    name="Peak kW per home",
                    key="peak_kw_per_home",
                    value=row.get("peak_kw_per_home"),
                    definition="Peak heating load per home (kW).",
                    denominator="Homes in pathway",
                    source="data/outputs/pathway_load_profile_summary.csv -> peak_kw_per_home",
                    usage="System peak sizing",
                )
            )
        return self._render_section(self.SECTION_TITLES[8], datapoints)

    def _build_section_10(self) -> List[str]:
        sensitivity_path = self.output_dir / "hn_penetration_sensitivity.csv"
        df = _read_csv(sensitivity_path)
        datapoints = []
        if df is not None and not df.empty:
            datapoints.append(
                AnnotatedDatapoint(
                    name="Penetration sensitivity scenarios",
                    key="hn_penetration_sensitivity_scenarios",
                    value=len(df),
                    definition="Number of penetration × price scenarios modeled (count).",
                    denominator="Penetration sensitivity grid",
                    source="data/outputs/hn_penetration_sensitivity.csv -> rows",
                    usage="HN sensitivity",
                )
            )
        return self._render_section(self.SECTION_TITLES[9], datapoints)

    def _build_section_11(self) -> List[str]:
        tenure_path = self.output_dir / "epc_fabric_breakdown_by_tenure.csv"
        df = _read_csv(tenure_path)
        datapoints = []
        if df is not None and not df.empty:
            datapoints.append(
                AnnotatedDatapoint(
                    name="Tenure categories reported",
                    key="tenure_categories_reported",
                    value=len(df),
                    definition="Number of tenure categories represented in output (count).",
                    denominator="Tenure breakdown table",
                    source="data/outputs/epc_fabric_breakdown_by_tenure.csv -> rows",
                    usage="Tenure filtering coverage",
                )
            )
        return self._render_section(self.SECTION_TITLES[10], datapoints)

    def _build_section_12(self, run_metadata: Dict[str, Any]) -> List[str]:
        datapoints = [
            AnnotatedDatapoint(
                name="Pipeline version",
                key="pipeline_version",
                value=run_metadata.get("pipeline_version") if run_metadata else None,
                definition="Version identifier stored in run metadata (string).",
                denominator="N/A",
                source="data/outputs/run_metadata.json -> pipeline_version",
                usage="Provenance",
            ),
            AnnotatedDatapoint(
                name="Report config version",
                key="report_config_version",
                value=self.config.get("project", {}).get("version"),
                definition="Project configuration version (string).",
                denominator="N/A",
                source="config/config.yaml -> project.version",
                usage="Documentation & tests",
            ),
        ]
        return self._render_section(self.SECTION_TITLES[11], datapoints)

    def _build_section_13(self) -> List[str]:
        datapoints = [
            AnnotatedDatapoint(
                name="Final energy definition",
                key="final_energy_definition",
                value=(
                    "All energy figures refer to annual delivered (final) energy unless explicitly stated otherwise; "
                    "primary energy is not used in these totals."
                ),
                definition="Clarifies energy accounting basis (text).",
                denominator="N/A",
                source="reporting requirement",
                usage="Metadata note",
            ),
            AnnotatedDatapoint(
                name="Cost exclusions",
                key="cost_exclusions",
                value=(
                    "Costs exclude major heat-network backbone capex and electricity grid upgrade costs unless explicitly modeled."
                ),
                definition="Clarifies excluded cost elements (text).",
                denominator="N/A",
                source="reporting requirement",
                usage="Metadata note",
            ),
            AnnotatedDatapoint(
                name="Hybrid label clarity",
                key="hybrid_label_clarity",
                value=(
                    "Hybrid pathway routing is mutually exclusive: homes connect to heat networks where ready, with others "
                    "receiving ASHPs to avoid double-counting benefits."
                ),
                definition="Explains hybrid pathway labeling (text).",
                denominator="N/A",
                source="reporting requirement",
                usage="Metadata note",
            ),
            AnnotatedDatapoint(
                name="Subsidy cost-uplift caveat",
                key="subsidy_cost_uplift_caveat",
                value=(
                    "Subsidy sensitivity uses the configured cost uplift percentage for sensitivity runs only; "
                    "interpret public expenditure totals accordingly."
                ),
                definition="Clarifies subsidy cost uplift assumption (text).",
                denominator="N/A",
                source="config/config.yaml -> financial.subsidy_sensitivity_cost_uplift_pct",
                usage="Metadata note",
            ),
        ]
        return self._render_section(self.SECTION_TITLES[12], datapoints)

    def _build_tier_section(self, tier_df: Optional[pd.DataFrame]) -> List[str]:
        if tier_df is None or tier_df.empty:
            return []
        datapoints = [
            AnnotatedDatapoint(
                name="Heat network tiers reported",
                key="heat_network_tiers_reported",
                value=len(tier_df),
                definition="Number of heat network tiers in summary (count).",
                denominator="Tier summary rows",
                source="data/outputs/pathway_suitability_by_tier.csv -> rows",
                usage="Tier distribution",
            )
        ]
        return self._render_section("Supplement: Heat Network Tier Summary", datapoints)

    def _build_borough_section(self, borough_df: Optional[pd.DataFrame]) -> List[str]:
        if borough_df is None or borough_df.empty:
            return []
        datapoints = [
            AnnotatedDatapoint(
                name="Boroughs reported",
                key="boroughs_reported",
                value=len(borough_df),
                definition="Number of boroughs in breakdown (count).",
                denominator="Borough breakdown rows",
                source="data/outputs/borough_breakdown.csv -> rows",
                usage="Borough summary",
            )
        ]
        return self._render_section("Supplement: Borough Summary", datapoints)


if __name__ == "__main__":
    generator = OneStopReportGenerator()
    generator.generate()
