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
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def _render_datapoint(datapoint: AnnotatedDatapoint) -> List[str]:
    lines = [f"- **{datapoint.name}** (`{datapoint.key}`)"]
    lines.append(f"  - Value: {_format_value(datapoint.value)}")
    lines.append(f"  - Definition + unit: {datapoint.definition}")
    lines.append(f"  - Denominator: {datapoint.denominator}")
    lines.append(f"  - Source: {datapoint.source}")
    if datapoint.usage:
        lines.append(f"  - Report usage: {datapoint.usage}")
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


def _parse_key_value_lines(text: str) -> Dict[str, str]:
    data: Dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            if key.strip() and value.strip():
                data[_snake_case(key.strip())] = value.strip()
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
        joined = " ".join(lines).strip()
        if joined.startswith("{") or joined.startswith("["):
            try:
                parsed[section] = ast.literal_eval(joined)
                continue
            except (ValueError, SyntaxError):
                pass
        parsed[section] = joined
    return parsed


def _extract_readiness_summary(output_dir: Path) -> Dict[str, Any]:
    summary_path = output_dir / "reports" / "retrofit_readiness_summary.txt"
    summary_text = _read_text(summary_path)
    if summary_text:
        parsed = _parse_key_value_lines(summary_text)
        tier_counts = {}
        for line in summary_text.splitlines():
            match = re.match(r"Tier\s+(\d+)\s*:\s*([\d,]+)", line)
            if match:
                tier_counts[int(match.group(1))] = int(match.group(2).replace(",", ""))
        if tier_counts:
            parsed["tier_distribution"] = tier_counts
        return parsed

    readiness_csv = output_dir / "retrofit_readiness_analysis.csv"
    df = _read_csv(readiness_csv)
    if df is None:
        return {}

    summary = {
        "total_properties": len(df),
        "needs_radiator_upsizing": int(df.get("needs_radiator_upsizing", pd.Series(dtype=int)).sum()),
        "needs_glazing_upgrade": int(df.get("needs_glazing_upgrade", pd.Series(dtype=int)).sum()),
        "mean_fabric_cost": float(df.get("fabric_prerequisite_cost", pd.Series(dtype=float)).mean())
        if "fabric_prerequisite_cost" in df.columns
        else None,
    }
    return summary


def _extract_scenario_results(output_dir: Path) -> Optional[pd.DataFrame]:
    csv_path = output_dir / "scenario_results_summary.csv"
    if csv_path.exists():
        return _read_csv(csv_path)

    text_path = output_dir / "scenario_modeling_results.txt"
    if not text_path.exists():
        return None

    text_data = _parse_key_value_lines(_read_text(text_path))
    if not text_data:
        return None

    df = pd.DataFrame([text_data])
    df["scenario"] = text_data.get("scenario", "scenario_modeling_results")
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

    def __init__(self, output_dir: Optional[Path] = None, config: Optional[Dict[str, Any]] = None):
        self.output_dir = Path(output_dir) if output_dir else DATA_OUTPUTS_DIR
        self.config = config or load_config()
        self.header_text = self.config.get("reporting", {}).get("one_stop_header_text", "")
        self.output_path = self.output_dir / "one_stop_output.md"

    def generate(self) -> Path:
        logger.info("Generating one-stop report...")

        lines: List[str] = []
        if self.header_text:
            lines.append(self.header_text)
            lines.append("")

        lines.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
        lines.append("")

        run_metadata = _read_json(self.output_dir / "run_metadata.json")
        archetype_results = _parse_archetype_results(self.output_dir / "archetype_analysis_results.txt")
        readiness_summary = _extract_readiness_summary(self.output_dir)
        scenario_df = _extract_scenario_results(self.output_dir)
        tier_df = _read_csv(self.output_dir / "pathway_suitability_by_tier.csv")
        borough_df = _read_csv(self.output_dir / "borough_breakdown.csv")

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
        lines.extend(self._build_tier_section(tier_df))
        lines.extend(self._build_borough_section(borough_df))

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        logger.info(f"One-stop report written to {self.output_path}")
        return self.output_path

    def _render_section(self, title: str, datapoints: Iterable[AnnotatedDatapoint]) -> List[str]:
        lines = [f"## {title}", ""]
        datapoints_list = list(datapoints)
        if not datapoints_list:
            lines.append("_No datapoints available from current outputs._")
            lines.append("")
            return lines
        for datapoint in datapoints_list:
            lines.extend(_render_datapoint(datapoint))
        lines.append("")
        return lines

    def _build_section_1(self, archetype_results: Dict[str, Any]) -> List[str]:
        epc_bands = archetype_results.get("EPC BANDS", {}) if archetype_results else {}
        wall_data = archetype_results.get("WALL CONSTRUCTION", {}) if archetype_results else {}
        datapoints = [
            AnnotatedDatapoint(
                name="EPC band total properties",
                key="epc_band_total_properties",
                value=epc_bands.get("total") if isinstance(epc_bands, dict) else None,
                definition="Total properties captured in EPC band distribution (count).",
                denominator="All properties in archetype analysis",
                source="data/outputs/archetype_analysis_results.txt -> EPC BANDS.total",
                usage="Fabric baseline sizing",
            ),
            AnnotatedDatapoint(
                name="Wall insulation rate",
                key="wall_insulation_rate_pct",
                value=wall_data.get("insulation_rate") if isinstance(wall_data, dict) else None,
                definition="Share of properties with insulated walls (percent of properties).",
                denominator="All properties in archetype analysis",
                source="data/outputs/archetype_analysis_results.txt -> WALL CONSTRUCTION.insulation_rate",
                usage="Fabric upgrade targeting",
            ),
        ]
        return self._render_section(self.SECTION_TITLES[0], datapoints)

    def _build_section_2(self, readiness_summary: Dict[str, Any]) -> List[str]:
        datapoints = [
            AnnotatedDatapoint(
                name="Mean fabric prerequisite cost",
                key="mean_fabric_prerequisite_cost_gbp",
                value=readiness_summary.get("mean_fabric_cost"),
                definition="Average fabric prerequisite cost before heat pump readiness (GBP per property).",
                denominator="All properties assessed for readiness",
                source="data/outputs/reports/retrofit_readiness_summary.txt -> Mean fabric cost",
                usage="Retrofit package economics",
            )
        ]
        return self._render_section(self.SECTION_TITLES[1], datapoints)

    def _build_section_3(self, readiness_summary: Dict[str, Any]) -> List[str]:
        datapoints = [
            AnnotatedDatapoint(
                name="Properties needing radiator upsizing",
                key="needs_radiator_upsizing",
                value=readiness_summary.get("needs_radiator_upsizing"),
                definition="Count of properties flagged for radiator upsizing (count).",
                denominator="All properties assessed for readiness",
                source="data/outputs/retrofit_readiness_analysis.csv -> needs_radiator_upsizing",
                usage="Emitter readiness diagnostics",
            )
        ]
        return self._render_section(self.SECTION_TITLES[2], datapoints)

    def _build_section_4(self, readiness_summary: Dict[str, Any]) -> List[str]:
        datapoints = [
            AnnotatedDatapoint(
                name="Properties needing glazing upgrade",
                key="needs_glazing_upgrade",
                value=readiness_summary.get("needs_glazing_upgrade"),
                definition="Count of properties flagged for glazing upgrade (count).",
                denominator="All properties assessed for readiness",
                source="data/outputs/retrofit_readiness_analysis.csv -> needs_glazing_upgrade",
                usage="Window upgrade planning",
            )
        ]
        return self._render_section(self.SECTION_TITLES[3], datapoints)

    def _build_section_5(self, scenario_df: Optional[pd.DataFrame]) -> List[str]:
        datapoints: List[AnnotatedDatapoint] = []
        if scenario_df is not None:
            for _, row in scenario_df.iterrows():
                scenario_label = row.get("scenario") or row.get("scenario_id") or "scenario"
                datapoints.extend([
                    AnnotatedDatapoint(
                        name=f"Average payback years ({scenario_label})",
                        key=f"average_payback_years_{_snake_case(str(scenario_label))}",
                        value=row.get("average_payback_years"),
                        definition="Average simple payback time for cost-effective homes (years).",
                        denominator="Cost-effective properties in scenario",
                        source="data/outputs/scenario_results_summary.csv -> average_payback_years",
                        usage="Payback analysis",
                    ),
                    AnnotatedDatapoint(
                        name=f"Median payback years ({scenario_label})",
                        key=f"median_payback_years_{_snake_case(str(scenario_label))}",
                        value=row.get("median_payback_years"),
                        definition="Median simple payback time for cost-effective homes (years).",
                        denominator="Cost-effective properties in scenario",
                        source="data/outputs/scenario_results_summary.csv -> median_payback_years",
                        usage="Payback analysis",
                    ),
                ])
        return self._render_section(self.SECTION_TITLES[4], datapoints)

    def _build_section_6(self, scenario_df: Optional[pd.DataFrame]) -> List[str]:
        datapoints: List[AnnotatedDatapoint] = []
        if scenario_df is not None:
            for _, row in scenario_df.iterrows():
                scenario_label = row.get("scenario") or row.get("scenario_id") or "scenario"
                datapoints.extend([
                    AnnotatedDatapoint(
                        name=f"Hybrid heat network assignments ({scenario_label})",
                        key=f"hn_assigned_properties_{_snake_case(str(scenario_label))}",
                        value=row.get("hn_assigned_properties"),
                        definition="Properties routed to heat networks in hybrid scenario (count).",
                        denominator="Total properties in scenario",
                        source="data/outputs/scenario_results_summary.csv -> hn_assigned_properties",
                        usage="Hybrid routing split",
                    ),
                    AnnotatedDatapoint(
                        name=f"Hybrid ASHP assignments ({scenario_label})",
                        key=f"ashp_assigned_properties_{_snake_case(str(scenario_label))}",
                        value=row.get("ashp_assigned_properties"),
                        definition="Properties routed to ASHPs in hybrid scenario (count).",
                        denominator="Total properties in scenario",
                        source="data/outputs/scenario_results_summary.csv -> ashp_assigned_properties",
                        usage="Hybrid routing split",
                    ),
                ])
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
