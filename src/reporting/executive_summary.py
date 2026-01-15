"""
Executive Summary Generator

Generates markdown executive summaries that pull data from:
- run_metadata.json (stage counts)
- scenario_results_summary.csv
- pathway_results_summary.csv
- pathway_suitability_by_tier.csv

AUDIT FIX: All numbers are now derived from the actual output files,
not hard-coded. This ensures consistency between reports and analysis.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
from loguru import logger

from config.config import DATA_OUTPUTS_DIR
from src.utils.run_metadata import get_total_properties_from_metadata, RunMetadataManager


class ExecutiveSummaryGenerator:
    """
    Generates executive summaries with data derived from analysis outputs.

    AUDIT FIX: Property counts and scenario results are pulled from actual
    output files, not hard-coded values. This addresses the finding that
    different pipeline stages were producing different totals.
    """

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = Path(output_dir) if output_dir else DATA_OUTPUTS_DIR
        self.reports_dir = self.output_dir / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def generate_summary(self) -> Path:
        """
        Generate the executive summary from current analysis outputs.

        Returns:
            Path to the generated markdown file
        """
        logger.info("Generating executive summary from analysis outputs...")

        # Load data from output files
        metadata = self._load_run_metadata()
        scenario_results = self._load_scenario_results()
        tier_results = self._load_tier_results()

        # Build the summary
        content = self._build_summary_content(metadata, scenario_results, tier_results)

        # Write to file
        output_path = self.reports_dir / "executive_summary.md"
        output_path.write_text(content, encoding="utf-8")

        # Also write a plain text version
        txt_path = self.reports_dir / "executive_summary.txt"
        txt_content = self._strip_markdown(content)
        txt_path.write_text(txt_content, encoding="utf-8")

        logger.info(f"Executive summary written to: {output_path}")
        return output_path

    def _load_run_metadata(self) -> Dict[str, Any]:
        """Load run metadata from run_metadata.json."""
        metadata_path = self.output_dir / "run_metadata.json"
        if metadata_path.exists():
            with open(metadata_path, "r", encoding="utf-8") as f:
                return json.load(f)
        logger.warning(f"run_metadata.json not found at {metadata_path}")
        return {}

    def _load_scenario_results(self) -> Optional[pd.DataFrame]:
        """Load scenario results from CSV."""
        csv_path = self.output_dir / "scenario_results_summary.csv"
        if csv_path.exists():
            return pd.read_csv(csv_path)

        # Try the JSON format
        json_path = self.output_dir / "scenario_modeling_results.json"
        if json_path.exists():
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return pd.DataFrame([
                        {"scenario": k, **v}
                        for k, v in data.items()
                        if isinstance(v, dict)
                    ])
        logger.warning("No scenario results found")
        return None

    def _load_tier_results(self) -> Optional[pd.DataFrame]:
        """Load heat network tier results."""
        csv_path = self.output_dir / "pathway_suitability_by_tier.csv"
        if csv_path.exists():
            return pd.read_csv(csv_path)
        logger.warning("No tier results found")
        return None

    def _get_stage_count(self, metadata: Dict, stage: str, default: int = 0) -> int:
        """Extract count from metadata for a specific stage."""
        stage_counts = metadata.get("stage_counts", {})
        return stage_counts.get(stage, {}).get("count", default)

    def _build_summary_content(
        self,
        metadata: Dict[str, Any],
        scenario_results: Optional[pd.DataFrame],
        tier_results: Optional[pd.DataFrame],
    ) -> str:
        """Build the executive summary markdown content."""
        lines = []

        # Header
        lines.extend([
            "# Heat Street Executive Summary",
            "",
            f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
            "",
            "---",
            "",
        ])

        # Analysis Universe section with reconciliation
        lines.extend(self._build_analysis_universe_section(metadata))

        # Scenario Results section
        if scenario_results is not None:
            lines.extend(self._build_scenario_section(scenario_results, metadata))

        # Heat Network Tiers section
        if tier_results is not None:
            lines.extend(self._build_tier_section(tier_results))

        # Explanatory Notes
        lines.extend(self._build_explanatory_notes(metadata))

        # Footer
        lines.extend([
            "",
            "---",
            "",
            "*This summary was automatically generated from analysis outputs. "
            "All figures are derived from the corresponding data files.*",
        ])

        return "\n".join(lines)

    def _build_analysis_universe_section(self, metadata: Dict) -> list:
        """Build the Analysis Universe section with stage count reconciliation."""
        lines = [
            "## Analysis Universe",
            "",
        ]

        # Get counts from metadata
        raw_count = self._get_stage_count(metadata, "raw_loaded_count")
        validation_count = self._get_stage_count(metadata, "after_validation_count")
        scenario_count = self._get_stage_count(metadata, "scenario_input_count")
        final_count = self._get_stage_count(metadata, "final_modeled_count")
        geocoded_count = self._get_stage_count(metadata, "after_geocoding_count")

        # Use the most appropriate count for headline
        headline_count = final_count or scenario_count or validation_count or raw_count

        if headline_count > 0:
            lines.extend([
                f"**Total properties analyzed: {headline_count:,}**",
                "",
            ])

        # Stage reconciliation table
        lines.extend([
            "### Stage Count Reconciliation",
            "",
            "| Stage | Count | Drop from Previous | Notes |",
            "|-------|-------|-------------------|-------|",
        ])

        stages = [
            ("Raw Loaded", "raw_loaded_count", "Initial EPC data load"),
            ("After Validation", "after_validation_count", "Passed validation rules"),
            ("After Geocoding", "after_geocoding_count", "Valid coordinates (spatial only)"),
            ("Scenario Input", "scenario_input_count", "Entered scenario modeling"),
            ("Final Modeled", "final_modeled_count", "Completed analysis"),
        ]

        prev_count = None
        for label, key, notes in stages:
            count = self._get_stage_count(metadata, key)
            if count > 0:
                drop_str = "-"
                if prev_count is not None and prev_count > 0:
                    drop = prev_count - count
                    drop_pct = (drop / prev_count * 100) if prev_count > 0 else 0
                    if drop > 0:
                        drop_str = f"{drop:,} ({drop_pct:.1f}%)"
                    elif drop == 0:
                        drop_str = "0"
                lines.append(f"| {label} | {count:,} | {drop_str} | {notes} |")
                prev_count = count

        lines.append("")

        # Add warnings if any
        warnings = metadata.get("warnings", [])
        if warnings:
            lines.extend([
                "### Warnings",
                "",
            ])
            for warning in warnings:
                lines.append(f"- {warning.get('message', str(warning))}")
            lines.append("")

        return lines

    def _build_scenario_section(
        self,
        scenario_results: pd.DataFrame,
        metadata: Dict
    ) -> list:
        """Build the Scenario Results section."""
        lines = [
            "## Scenario Modeling Results",
            "",
        ]

        # Get total properties for per-property calculations
        total_props = self._get_stage_count(metadata, "final_modeled_count") or \
                     self._get_stage_count(metadata, "scenario_input_count") or 1

        # Summary table
        lines.extend([
            "### Key Scenarios Comparison",
            "",
            "| Scenario | Capital Cost (Total) | Cost/Property | Annual Bill Savings | Payback (Years) | CO2 Reduction |",
            "|----------|---------------------|---------------|---------------------|-----------------|---------------|",
        ])

        for _, row in scenario_results.iterrows():
            scenario_name = row.get("scenario", row.get("scenario_name", "Unknown"))
            capital_total = row.get("capital_cost_total", 0)
            capital_per_prop = row.get("capital_cost_per_property", 0)
            bill_savings = row.get("annual_bill_savings_total", row.get("annual_bill_savings", 0))
            payback = row.get("average_payback_years", row.get("median_payback_years", "-"))
            co2_reduction = row.get("annual_co2_reduction_total_kg", row.get("annual_co2_reduction_kg", 0))

            # Format numbers
            capital_str = f"\u00a3{capital_total/1e9:.2f}B" if capital_total > 1e9 else f"\u00a3{capital_total/1e6:.1f}M"
            per_prop_str = f"\u00a3{capital_per_prop:,.0f}"
            savings_str = f"\u00a3{bill_savings/1e6:.1f}M" if bill_savings > 1e6 else f"\u00a3{bill_savings:,.0f}"
            payback_str = f"{payback:.1f}" if isinstance(payback, (int, float)) and payback < 100 else "-"
            co2_str = f"{co2_reduction/1e6:.2f}M kg" if co2_reduction > 1e6 else f"{co2_reduction:,.0f} kg"

            lines.append(
                f"| {scenario_name} | {capital_str} | {per_prop_str} | {savings_str} | {payback_str} | {co2_str} |"
            )

        lines.append("")

        # Add assigned properties info if available
        has_assignments = "hn_assigned_properties" in scenario_results.columns or \
                        "ashp_assigned_properties" in scenario_results.columns

        if has_assignments:
            lines.extend([
                "### Technology Assignments by Scenario",
                "",
                "| Scenario | Heat Network Assigned | Heat Pump Assigned | Notes |",
                "|----------|----------------------|-------------------|-------|",
            ])

            for _, row in scenario_results.iterrows():
                scenario_name = row.get("scenario", "Unknown")
                hn_assigned = row.get("hn_assigned_properties", 0)
                ashp_assigned = row.get("ashp_assigned_properties", 0)

                # Determine notes based on assignments
                if hn_assigned > 0 and ashp_assigned > 0:
                    notes = "Hybrid scenario"
                elif hn_assigned > 0:
                    notes = "Heat network only"
                elif ashp_assigned > 0:
                    notes = "Heat pump only"
                else:
                    notes = "Fabric-only or baseline"

                hn_str = f"{hn_assigned:,}" if hn_assigned else "0"
                ashp_str = f"{ashp_assigned:,}" if ashp_assigned else "0"

                lines.append(f"| {scenario_name} | {hn_str} | {ashp_str} | {notes} |")

            lines.append("")

        return lines

    def _build_tier_section(self, tier_results: pd.DataFrame) -> list:
        """Build the Heat Network Tier section."""
        lines = [
            "## Heat Network Tier Classification",
            "",
            "Properties classified by suitability for district heating connection:",
            "",
            "| Tier | Properties | Percentage | Recommended Pathway |",
            "|------|------------|------------|---------------------|",
        ]

        for _, row in tier_results.iterrows():
            tier = row.get("Tier", row.get("tier", "Unknown"))
            count = row.get("Property Count", row.get("properties", 0))
            pct = row.get("Percentage", row.get("percentage", 0))
            pathway = row.get("Recommended Pathway", row.get("recommendation", "-"))

            count_str = f"{count:,}" if count else "0"
            lines.append(f"| {tier} | {count_str} | {pct:.1f}% | {pathway} |")

        lines.extend([
            "",
            "*Note: All 5 tiers are shown even if some have 0 properties.*",
            "",
        ])

        return lines

    def _build_explanatory_notes(self, metadata: Dict) -> list:
        """Build explanatory notes section."""
        lines = [
            "## Explanatory Notes",
            "",
            "### Why Some Pathways Have Counterintuitive Results",
            "",
            "**Lower CAPEX but longer payback:**",
            "A pathway with lower capital expenditure may have a longer payback period if:",
            "- The associated tariff structure results in lower annual bill savings",
            "- Energy savings are smaller due to less comprehensive measures",
            "- The pathway relies on technologies with higher operating costs",
            "",
            "**Tipping-point fabric outperforming minimum fabric:**",
            "The 'tipping-point' fabric package can have better economics than 'minimum fabric' because:",
            "- Additional insulation measures reduce heat pump sizing requirements",
            "- Lower flow temperatures enable higher heat pump efficiency (COP)",
            "- The combined savings from smaller equipment + higher efficiency offset extra fabric cost",
            "",
            "### Properties Not Cost-Effective",
            "",
            "A small number of properties may show as 'not cost-effective' across all scenarios. ",
            "These typically have:",
            "- Baseline energy consumption already very low (minimal savings potential)",
            "- Data anomalies causing zero or negative calculated savings",
            "- Special characteristics making standard measures ineffective",
            "",
            "These properties are included in the analysis but flagged for further investigation.",
            "",
        ]

        # Add notes from metadata if any
        notes = metadata.get("notes", [])
        if notes:
            lines.extend([
                "### Analysis Notes",
                "",
            ])
            for note in notes:
                note_text = note.get("note", str(note)) if isinstance(note, dict) else str(note)
                lines.append(f"- {note_text}")
            lines.append("")

        return lines

    def _strip_markdown(self, content: str) -> str:
        """Convert markdown to plain text."""
        import re

        # Remove headers but keep text
        content = re.sub(r'^#+\s*', '', content, flags=re.MULTILINE)

        # Remove bold/italic markers
        content = re.sub(r'\*\*([^*]+)\*\*', r'\1', content)
        content = re.sub(r'\*([^*]+)\*', r'\1', content)

        # Remove link formatting
        content = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', content)

        # Convert tables to simple format
        content = re.sub(r'\|', ' | ', content)
        content = re.sub(r'\s*\|\s*-+\s*', ' | ', content)

        return content


def generate_executive_summary(output_dir: Optional[Path] = None) -> Path:
    """
    Convenience function to generate executive summary.

    Args:
        output_dir: Optional output directory path

    Returns:
        Path to generated summary file
    """
    generator = ExecutiveSummaryGenerator(output_dir)
    return generator.generate_summary()
