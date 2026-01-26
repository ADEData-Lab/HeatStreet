"""
Reporting and Visualization Module

Creates charts, figures, and summary reports for the project.
"""

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from loguru import logger

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import (
    load_config,
    DATA_OUTPUTS_DIR,
    get_scenario_label_map,
    get_analysis_horizon_years,
)
from src.reporting.report_headline_data import build_report_headline_dataframe


class ReportGenerator:
    """
    Generates visualizations and reports for the analysis.
    """

    def __init__(self):
        """Initialize the report generator."""
        self.config = load_config()
        self.scenario_labels = get_scenario_label_map()
        self.analysis_horizon_years = get_analysis_horizon_years()
        self.output_dir = DATA_OUTPUTS_DIR / "figures"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Set visualization style
        sns.set_style("whitegrid")
        sns.set_palette("husl")
        plt.rcParams['figure.figsize'] = (12, 8)
        plt.rcParams['font.size'] = 11

        logger.info("Initialized Report Generator")

    def _scenario_label(self, scenario_id: str, results: Optional[Dict] = None) -> str:
        """Return the configured label for a scenario, if available."""
        if isinstance(results, dict):
            scenario_label = results.get("scenario_label")
            if scenario_label:
                return scenario_label
        return self.scenario_labels.get(scenario_id, scenario_id)

    def _cost_per_tco2_20yr_gbp(self, results: Dict) -> Optional[float]:
        """Calculate cost per tCO2 using total abatement over the analysis horizon."""
        annual_co2_reduction_kg = results.get("annual_co2_reduction_kg")
        capital_cost_total = results.get("capital_cost_total")
        if capital_cost_total is None or not annual_co2_reduction_kg:
            return None
        tco2_over_horizon = (annual_co2_reduction_kg / 1000) * self.analysis_horizon_years
        if not tco2_over_horizon:
            return None
        return capital_cost_total / tco2_over_horizon

    def plot_epc_band_distribution(
        self,
        epc_data: Dict,
        save_path: Optional[Path] = None
    ):
        """
        Create histogram of EPC band distribution.

        Args:
            epc_data: Dictionary with EPC band frequency data
            save_path: Path to save figure
        """
        logger.info("Creating EPC band distribution chart...")

        if save_path is None:
            save_path = self.output_dir / "epc_band_distribution.png"

        bands = ['A', 'B', 'C', 'D', 'E', 'F', 'G']
        frequencies = [epc_data['frequency'].get(band, 0) for band in bands]
        percentages = [epc_data['percentage'].get(band, 0) for band in bands]

        fig, ax = plt.subplots(figsize=(10, 6))

        colors = ['#2ecc71', '#27ae60', '#f1c40f', '#f39c12', '#e67e22', '#e74c3c', '#c0392b']
        bars = ax.bar(bands, frequencies, color=colors, edgecolor='black', linewidth=1.2)

        # Add percentage labels on bars
        for bar, pct in zip(bars, percentages):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{pct:.1f}%',
                   ha='center', va='bottom', fontsize=10, fontweight='bold')

        ax.set_xlabel('EPC Band', fontsize=12, fontweight='bold')
        ax.set_ylabel('Number of Properties', fontsize=12, fontweight='bold')
        ax.set_title('Current EPC Band Distribution\nEdwardian Terraced Housing, London',
                    fontsize=14, fontweight='bold', pad=20)

        # Add grid
        ax.yaxis.grid(True, alpha=0.3)
        ax.set_axisbelow(True)

        # Format y-axis
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{int(x):,}'))

        plt.tight_layout()
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        plt.close()

        logger.info(f"Saved EPC band distribution to: {save_path}")

    def plot_epc_lodgements_by_year_band(
        self,
        df: pd.DataFrame,
        save_counts_path: Optional[Path] = None,
        save_share_path: Optional[Path] = None,
        include_share_chart: bool = True,
    ):
        """
        Create stacked bar chart of EPC lodgements by year, broken down by band.

        The y-axis is counts, while the A/B, C, and D bar segments are labelled as
        percentages of the yearly total (to highlight the shift toward higher ratings).

        Args:
            df: EPC dataframe (expects LODGEMENT_DATE/INSPECTION_DATE and CURRENT_ENERGY_RATING).
            save_counts_path: Output path for the stacked counts PNG.
            save_share_path: Output path for the stacked share PNG (optional).
            include_share_chart: Whether to also write the share chart.
        """
        logger.info("Creating EPC lodgements-by-year stacked bar chart...")

        if save_counts_path is None:
            save_counts_path = self.output_dir / "epc_lodgement_year_band_stacked_counts.png"
        if save_share_path is None:
            save_share_path = self.output_dir / "epc_lodgement_year_band_stacked_share.png"

        if df is None or df.empty:
            logger.warning("No data provided for EPC lodgements-by-year chart; skipping.")
            return

        # Dates: prefer LODGEMENT_DATE, fallback to INSPECTION_DATE
        lodgement = pd.to_datetime(df.get("LODGEMENT_DATE"), errors="coerce")
        inspection = pd.to_datetime(df.get("INSPECTION_DATE"), errors="coerce")
        effective = lodgement.fillna(inspection)
        years = effective.dt.year

        band = df.get("CURRENT_ENERGY_RATING")
        if band is None:
            logger.warning("CURRENT_ENERGY_RATING missing; cannot create EPC lodgements-by-year chart.")
            return
        band = band.astype("string").fillna("Unknown").str.strip().str.upper()
        band = band.replace({"": "Unknown"})
        band = band.where(band.isin(list("ABCDEFG")), other="Unknown")
        band = band.replace({"A": "A/B", "B": "A/B"})

        tmp = pd.DataFrame({"year": years, "band": band}).dropna(subset=["year"])
        if tmp.empty:
            logger.warning("No valid dates found for EPC lodgements-by-year chart; skipping.")
            return
        tmp["year"] = tmp["year"].astype(int)

        wide = (
            tmp.groupby(["year", "band"])
            .size()
            .unstack(fill_value=0)
            .sort_index()
        )
        wide.index.name = "year"

        cols = [c for c in ["A/B", "C", "D", "E", "F", "G", "Unknown"] if c in wide.columns]
        label_cols = [c for c in ["A/B", "C", "D"] if c in cols]
        colors = {
            "A/B": "#2ca02c",
            "C": "#8bc34a",
            "D": "#ffeb3b",
            "E": "#ff9800",
            "F": "#f44336",
            "G": "#b71c1c",
            "Unknown": "#9e9e9e",
        }

        # Stacked counts chart
        fig, ax = plt.subplots(figsize=(12, 6))
        wide[cols].plot(kind="bar", stacked=True, ax=ax, color=[colors[c] for c in cols], width=0.9)
        ax.set_title("EPC lodgements by year (counts; A-D segments labelled % of year)")
        ax.set_xlabel("Lodgement year (LODGEMENT_DATE; fallback INSPECTION_DATE)")
        ax.set_ylabel("Number of EPCs")
        ax.tick_params(axis="x", rotation=0)
        ax.get_yaxis().set_major_formatter(plt.FuncFormatter(lambda x, _: f"{int(x):,}"))
        ax.legend(title="EPC band", bbox_to_anchor=(1.02, 1), loc="upper left")

        # Add percentage labels for A/B, C, D segments while keeping y-axis in counts.
        totals = wide[cols].sum(axis=1).values
        for col, container in zip(cols, ax.containers):
            if col not in label_cols:
                continue
            text_color = "white" if col == "A/B" else "black"
            for rect, total in zip(container, totals):
                height = rect.get_height()
                if height <= 0 or total <= 0:
                    continue
                pct = (height / total) * 100.0
                label = "<1%" if 0 < pct < 1 else f"{pct:.0f}%"
                x = rect.get_x() + rect.get_width() / 2
                y = rect.get_y() + height / 2
                ax.text(
                    x,
                    y,
                    label,
                    ha="center",
                    va="center",
                    fontsize=8,
                    fontweight="bold",
                    color=text_color,
                )

        fig.tight_layout()
        fig.savefig(save_counts_path, dpi=300, bbox_inches="tight")
        plt.close(fig)
        logger.info(f"Saved EPC lodgements-by-year chart to: {save_counts_path}")

        # Optional share chart
        if include_share_chart:
            share = wide[cols].div(wide[cols].sum(axis=1), axis=0) * 100.0
            fig, ax = plt.subplots(figsize=(12, 6))
            share.plot(kind="bar", stacked=True, ax=ax, color=[colors[c] for c in cols], width=0.9)
            ax.set_title("EPC lodgements by year (share, stacked by EPC band)")
            ax.set_xlabel("Lodgement year (LODGEMENT_DATE; fallback INSPECTION_DATE)")
            ax.set_ylabel("% of EPCs (within each year)")
            ax.tick_params(axis="x", rotation=0)
            ax.set_ylim(0, 100)
            ax.legend(title="EPC band", bbox_to_anchor=(1.02, 1), loc="upper left")
            fig.tight_layout()
            fig.savefig(save_share_path, dpi=300, bbox_inches="tight")
            plt.close(fig)
            logger.info(f"Saved EPC lodgements-by-year share chart to: {save_share_path}")

    def plot_sap_score_distribution(
        self,
        sap_data: pd.Series,
        save_path: Optional[Path] = None
    ):
        """
        Create histogram of SAP score distribution.

        Args:
            sap_data: Series of SAP scores
            save_path: Path to save figure
        """
        logger.info("Creating SAP score distribution chart...")

        if save_path is None:
            save_path = self.output_dir / "sap_score_distribution.png"

        fig, ax = plt.subplots(figsize=(12, 6))

        # Histogram
        n, bins, patches = ax.hist(sap_data, bins=30, edgecolor='black', alpha=0.7, color='steelblue')

        # Color bars by EPC band thresholds
        band_thresholds = [0, 21, 39, 55, 69, 81, 92, 100]
        band_colors = ['#c0392b', '#e74c3c', '#e67e22', '#f39c12', '#f1c40f', '#27ae60', '#2ecc71']

        for i in range(len(patches)):
            bin_center = (bins[i] + bins[i+1]) / 2
            for j in range(len(band_thresholds)-1):
                if band_thresholds[j] <= bin_center < band_thresholds[j+1]:
                    patches[i].set_facecolor(band_colors[j])
                    break

        # Add mean line
        mean_sap = sap_data.mean()
        ax.axvline(mean_sap, color='red', linestyle='--', linewidth=2, label=f'Mean: {mean_sap:.1f}')

        # Add median line
        median_sap = sap_data.median()
        ax.axvline(median_sap, color='darkred', linestyle=':', linewidth=2, label=f'Median: {median_sap:.1f}')

        ax.set_xlabel('SAP Score', fontsize=12, fontweight='bold')
        ax.set_ylabel('Number of Properties', fontsize=12, fontweight='bold')
        ax.set_title('SAP Score Distribution\nEdwardian Terraced Housing, London',
                    fontsize=14, fontweight='bold', pad=20)

        ax.legend(loc='upper right', fontsize=10)
        ax.yaxis.grid(True, alpha=0.3)
        ax.set_axisbelow(True)

        plt.tight_layout()
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        plt.close()

        logger.info(f"Saved SAP score distribution to: {save_path}")

    def plot_scenario_comparison(
        self,
        scenario_results: Dict,
        save_path: Optional[Path] = None
    ):
        """
        Create comparison chart of different scenarios.

        Args:
            scenario_results: Dictionary of scenario modeling results
            save_path: Path to save figure
        """
        logger.info("Creating scenario comparison chart...")

        if save_path is None:
            save_path = self.output_dir / "scenario_comparison.png"

        scenarios = list(scenario_results.keys())
        scenario_labels = [self._scenario_label(s, scenario_results[s]) for s in scenarios]
        metrics = {
            'Capital Cost (£M)': [scenario_results[s]['capital_cost_total']/1_000_000 for s in scenarios],
            'Annual CO2 Savings (tonnes)': [scenario_results[s]['annual_co2_reduction_kg']/1000 for s in scenarios],
            'Payback (years)': [scenario_results[s].get('average_payback_years', 0) for s in scenarios]
        }

        fig, axes = plt.subplots(1, 3, figsize=(16, 5))

        for idx, (metric, values) in enumerate(metrics.items()):
            ax = axes[idx]
            bars = ax.bar(scenario_labels, values, color='steelblue', edgecolor='black', linewidth=1.2)

            # Add value labels
            for bar in bars:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height,
                       f'{height:.1f}',
                       ha='center', va='bottom', fontsize=10, fontweight='bold')

            ax.set_ylabel(metric, fontsize=11, fontweight='bold')
            ax.set_title(metric, fontsize=12, fontweight='bold', pad=10)
            ax.tick_params(axis='x', rotation=45)
            ax.yaxis.grid(True, alpha=0.3)
            ax.set_axisbelow(True)

        plt.suptitle('Decarbonization Scenario Comparison', fontsize=14, fontweight='bold', y=1.02)
        plt.tight_layout()
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        plt.close()

        logger.info(f"Saved scenario comparison to: {save_path}")

    def plot_subsidy_sensitivity(
        self,
        subsidy_results: Dict,
        save_path: Optional[Path] = None
    ):
        """
        Create chart showing subsidy sensitivity analysis.

        Args:
            subsidy_results: Dictionary of subsidy sensitivity results
            save_path: Path to save figure
        """
        logger.info("Creating subsidy sensitivity chart...")

        if save_path is None:
            save_path = self.output_dir / "subsidy_sensitivity.png"

        subsidy_levels = []
        uptake_rates = []
        payback_years = []
        carbon_costs = []

        for level, data in subsidy_results.items():
            subsidy_levels.append(data['subsidy_percentage'])
            uptake_rates.append(data['estimated_uptake_rate'] * 100)
            payback_years.append(data['payback_years'])
            carbon_costs.append(data['carbon_abatement_cost_per_tonne'])

        fig, axes = plt.subplots(2, 2, figsize=(14, 10))

        # Uptake rate vs subsidy
        axes[0, 0].plot(subsidy_levels, uptake_rates, marker='o', linewidth=2, markersize=8, color='steelblue')
        axes[0, 0].set_xlabel('Subsidy Level (%)', fontweight='bold')
        axes[0, 0].set_ylabel('Estimated Uptake Rate (%)', fontweight='bold')
        axes[0, 0].set_title('Uptake Rate vs Subsidy Level', fontweight='bold', pad=10)
        axes[0, 0].grid(True, alpha=0.3)
        axes[0, 0].set_ylim(0, 100)

        # Payback vs subsidy
        axes[0, 1].plot(subsidy_levels, payback_years, marker='s', linewidth=2, markersize=8, color='coral')
        axes[0, 1].set_xlabel('Subsidy Level (%)', fontweight='bold')
        axes[0, 1].set_ylabel('Payback Period (years)', fontweight='bold')
        axes[0, 1].set_title('Payback Period vs Subsidy Level', fontweight='bold', pad=10)
        axes[0, 1].grid(True, alpha=0.3)

        # Carbon abatement cost
        axes[1, 0].plot(subsidy_levels, carbon_costs, marker='^', linewidth=2, markersize=8, color='green')
        axes[1, 0].set_xlabel('Subsidy Level (%)', fontweight='bold')
        axes[1, 0].set_ylabel('Carbon Abatement Cost (£/tCO₂)', fontweight='bold')
        axes[1, 0].set_title('Carbon Abatement Cost vs Subsidy Level', fontweight='bold', pad=10)
        axes[1, 0].grid(True, alpha=0.3)

        # Public expenditure
        public_exp = [subsidy_results[level]['public_expenditure_total']/1_000_000
                     for level in subsidy_results.keys()]
        axes[1, 1].bar(subsidy_levels, public_exp, color='purple', edgecolor='black', alpha=0.7)
        axes[1, 1].set_xlabel('Subsidy Level (%)', fontweight='bold')
        axes[1, 1].set_ylabel('Public Expenditure (£M)', fontweight='bold')
        axes[1, 1].set_title('Total Public Expenditure vs Subsidy Level', fontweight='bold', pad=10)
        axes[1, 1].grid(True, alpha=0.3, axis='y')

        plt.suptitle('Subsidy Sensitivity Analysis', fontsize=14, fontweight='bold', y=1.00)
        plt.tight_layout()
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        plt.close()

        logger.info(f"Saved subsidy sensitivity to: {save_path}")

    def plot_epc_band_shifts(
        self,
        band_shift_data: Dict,
        scenario_name: str = 'Scenario',
        save_path: Optional[Path] = None
    ):
        """
        Create chart showing EPC band distribution before and after intervention.

        Args:
            band_shift_data: Dictionary with 'before' and 'after' band distributions
            scenario_name: Name of the scenario for title
            save_path: Path to save figure
        """
        logger.info("Creating EPC band shift chart...")

        if save_path is None:
            save_path = self.output_dir / "epc_band_shifts.png"

        bands = ['A', 'B', 'C', 'D', 'E', 'F', 'G']
        before_counts = [band_shift_data.get('before', {}).get(b, 0) for b in bands]
        after_counts = [band_shift_data.get('after', {}).get(b, 0) for b in bands]

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
        fig.suptitle(f'EPC Band Distribution: {scenario_name}', fontsize=14, fontweight='bold')

        # Colors from A (green) to G (red)
        colors = ['#2ecc71', '#27ae60', '#f1c40f', '#f39c12', '#e67e22', '#e74c3c', '#c0392b']

        x = np.arange(len(bands))
        width = 0.35

        # Grouped bar chart
        bars1 = ax1.bar(x - width/2, before_counts, width, label='Before',
                       color='lightgray', edgecolor='black', linewidth=1.2)
        bars2 = ax1.bar(x + width/2, after_counts, width, label='After',
                       color=colors, edgecolor='black', linewidth=1.2)

        ax1.set_xlabel('EPC Band', fontsize=12, fontweight='bold')
        ax1.set_ylabel('Number of Properties', fontsize=12, fontweight='bold')
        ax1.set_title('Band Distribution Before vs After', fontsize=13, fontweight='bold')
        ax1.set_xticks(x)
        ax1.set_xticklabels(bands)
        ax1.legend()
        ax1.yaxis.grid(True, alpha=0.3)
        ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{int(x):,}'))

        # Net change chart
        changes = [after - before for before, after in zip(before_counts, after_counts)]
        change_colors = ['#2ecc71' if c > 0 else '#e74c3c' for c in changes]

        bars3 = ax2.bar(bands, changes, color=change_colors, edgecolor='black', linewidth=1.2)

        # Add value labels
        for bar, change in zip(bars3, changes):
            height = bar.get_height()
            va = 'bottom' if change >= 0 else 'top'
            ax2.text(bar.get_x() + bar.get_width()/2., height,
                    f'{change:+,}',
                    ha='center', va=va, fontsize=10, fontweight='bold')

        ax2.axhline(y=0, color='black', linewidth=1)
        ax2.set_xlabel('EPC Band', fontsize=12, fontweight='bold')
        ax2.set_ylabel('Net Change in Properties', fontsize=12, fontweight='bold')
        ax2.set_title('Net Change by Band', fontsize=13, fontweight='bold')
        ax2.yaxis.grid(True, alpha=0.3)
        ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{int(x):+,}'))

        # Calculate and display Band C or better metrics
        total = sum(before_counts)
        band_c_or_better_before = sum(before_counts[:3])
        band_c_or_better_after = sum(after_counts[:3])
        pct_before = band_c_or_better_before / total * 100 if total > 0 else 0
        pct_after = band_c_or_better_after / total * 100 if total > 0 else 0

        textstr = (f'Band C or better:\n'
                  f'Before: {band_c_or_better_before:,} ({pct_before:.1f}%)\n'
                  f'After: {band_c_or_better_after:,} ({pct_after:.1f}%)\n'
                  f'Change: +{pct_after - pct_before:.1f}pp')

        ax2.text(0.98, 0.98, textstr, transform=ax2.transAxes,
                fontsize=11, verticalalignment='top', horizontalalignment='right',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

        plt.tight_layout()
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        plt.close()

        logger.info(f"Saved EPC band shifts to: {save_path}")

    def plot_cost_effectiveness_summary(
        self,
        ce_summary: Dict,
        scenario_name: str = 'Scenario',
        save_path: Optional[Path] = None
    ):
        """
        Create chart showing cost-effectiveness summary.

        Args:
            ce_summary: Cost-effectiveness summary dictionary
            scenario_name: Name of the scenario for title
            save_path: Path to save figure
        """
        logger.info("Creating cost-effectiveness summary chart...")

        if save_path is None:
            save_path = self.output_dir / "cost_effectiveness_summary.png"

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
        fig.suptitle(f'Cost-Effectiveness Analysis: {scenario_name}', fontsize=14, fontweight='bold')

        # Pie chart of cost-effectiveness categories
        categories = ['Cost-effective', 'Marginal', 'Not cost-effective']
        counts = [
            ce_summary.get('cost_effective_count', 0),
            ce_summary.get('marginal_count', 0),
            ce_summary.get('not_cost_effective_count', 0)
        ]
        colors = ['#2ecc71', '#f39c12', '#e74c3c']

        # Only include non-zero categories
        labels_filtered = []
        counts_filtered = []
        colors_filtered = []
        for label, count, color in zip(categories, counts, colors):
            if count > 0:
                labels_filtered.append(label)
                counts_filtered.append(count)
                colors_filtered.append(color)

        if counts_filtered:
            wedges, texts, autotexts = ax1.pie(
                counts_filtered, labels=labels_filtered,
                autopct=lambda pct: f'{pct:.1f}%\n({int(pct/100*sum(counts_filtered)):,})',
                colors=colors_filtered, startangle=90,
                textprops={'fontsize': 10}
            )
            ax1.set_title('Upgrade Recommendation Distribution', fontsize=13, fontweight='bold')

        # Bar chart of key metrics
        metrics = {
            'Payback\nThreshold': ce_summary.get('payback_threshold_years', 20),
            'Cost-effective\n(%)': ce_summary.get('cost_effective_pct', 0),
            'Avg Payback\n(cost-eff)': ce_summary.get('avg_payback_cost_effective', 0) or 0,
        }

        bars = ax2.bar(metrics.keys(), metrics.values(), color='steelblue', edgecolor='black')
        ax2.set_ylabel('Value', fontsize=12, fontweight='bold')
        ax2.set_title('Cost-Effectiveness Metrics', fontsize=13, fontweight='bold')
        ax2.yaxis.grid(True, alpha=0.3)

        # Add value labels
        for bar in bars:
            height = bar.get_height()
            ax2.text(bar.get_x() + bar.get_width()/2., height,
                    f'{height:.1f}',
                    ha='center', va='bottom', fontsize=10, fontweight='bold')

        plt.tight_layout()
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        plt.close()

        logger.info(f"Saved cost-effectiveness summary to: {save_path}")

    def plot_fabric_tipping_point_analysis(
        self,
        curve_csv: Optional[Path] = None,
        save_png: Optional[Path] = None,
        save_svg: Optional[Path] = None,
    ):
        """
        Recreate the "Fabric Investment Tipping Point Analysis" chart from the pipeline curve CSV.

        Args:
            curve_csv: Path to fabric_tipping_point_curve.csv. If omitted, uses the latest run in
                data/outputs/bin/run_*/ or falls back to data/outputs/.
            save_png: Output PNG path (defaults to data/outputs/figures/tipping_point.png).
            save_svg: Output SVG path (defaults to data/outputs/figures/tipping_point.svg).
        """
        logger.info("Creating fabric tipping point chart...")

        if save_png is None:
            save_png = self.output_dir / "tipping_point.png"
        if save_svg is None:
            save_svg = self.output_dir / "tipping_point.svg"

        if curve_csv is None:
            candidates: List[Path] = []
            bin_dir = DATA_OUTPUTS_DIR / "bin"
            if bin_dir.exists():
                run_dirs = [p for p in bin_dir.iterdir() if p.is_dir() and p.name.startswith("run_")]
                run_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                if run_dirs:
                    candidates.append(run_dirs[0] / "fabric_tipping_point_curve.csv")
            candidates.append(DATA_OUTPUTS_DIR / "fabric_tipping_point_curve.csv")
            for c in candidates:
                if c.exists():
                    curve_csv = c
                    break

        if curve_csv is None or not curve_csv.exists():
            logger.warning("Could not find fabric_tipping_point_curve.csv; skipping tipping point chart.")
            return

        df = pd.read_csv(curve_csv)
        required = {
            "step",
            "measure_id",
            "measure_name",
            "cumulative_capex",
            "marginal_kwh_saved",
            "marginal_capex",
            "remaining_demand_pct",
            "is_beyond_tipping_point",
        }
        missing = required.difference(df.columns)
        if missing:
            logger.warning(f"fabric_tipping_point_curve.csv missing columns {sorted(missing)}; skipping chart.")
            return

        df = df[df["step"] > 0].reset_index(drop=True).copy()
        if df.empty:
            logger.warning("fabric_tipping_point_curve.csv contains no measure rows; skipping chart.")
            return

        df["marginal_efficiency_kwh_per_1k"] = (
            df["marginal_kwh_saved"].astype(float) / df["marginal_capex"].astype(float) * 1000.0
        )

        def _wrap_label(text: str, width: int = 14) -> str:
            words = str(text).split()
            lines: List[str] = []
            current: List[str] = []
            for w in words:
                if not current:
                    current = [w]
                    continue
                if len(" ".join(current + [w])) <= width:
                    current.append(w)
                else:
                    lines.append(" ".join(current))
                    current = [w]
            if current:
                lines.append(" ".join(current))
            if len(lines) <= 2:
                return "\n".join(lines)
            return "\n".join(lines[:2]) + "\n..."

        def _format_gbp(value: float) -> str:
            return f"£{value:,.0f}"

        label_map = {
            "loft_insulation": "Loft\ninsulation\n(top-up)",
            "draught_proofing": "Draught-\nproofing",
            "cavity_wall_insulation": "Cavity wall\ninsulation",
            "floor_insulation": "Floor\ninsulation",
            "solid_wall_insulation_ewi": "External wall\ninsulation",
            "solid_wall_insulation_iwi": "Internal wall\ninsulation",
            "triple_glazing_upgrade": "Triple\nglazing",
            "double_glazing_upgrade": "Double glazing\nupgrade",
        }

        x_labels = []
        for mid, mname in zip(df["measure_id"], df["measure_name"]):
            mid_str = str(mid)
            if mid_str in label_map:
                x_labels.append(label_map[mid_str])
            else:
                x_labels.append(_wrap_label(str(mname)))

        efficiency = df["marginal_efficiency_kwh_per_1k"].astype(float).tolist()
        cumulative_capex = df["cumulative_capex"].astype(float).tolist()

        threshold_eff = 2500.0
        moderate_eff = 1000.0

        colors = {
            "high": "#2e7d32",
            "moderate": "#ffa726",
            "low": "#ef5350",
            "threshold": "#1e88e5",
            "line": "#4e342e",
            "grid": "#e0e0e0",
        }

        bar_colors: List[str] = []
        for v in efficiency:
            if v >= threshold_eff:
                bar_colors.append(colors["high"])
            elif v >= moderate_eff:
                bar_colors.append(colors["moderate"])
            else:
                bar_colors.append(colors["low"])

        n = len(df)
        x = list(range(n))

        y_max = max(3500.0, max(efficiency) * 1.8 if efficiency else 3500.0)
        right_max = max(cumulative_capex) * 1.15 if cumulative_capex else 1.0

        fig, ax = plt.subplots(figsize=(16, 7))
        ax.set_axisbelow(True)
        ax.yaxis.grid(True, color=colors["grid"], linewidth=1)

        bars = ax.bar(x, efficiency, color=bar_colors, width=0.7, edgecolor="white")

        ax.set_title(
            "Fabric Investment Tipping Point Analysis\nDiminishing Returns from Sequential Retrofit Measures",
            fontsize=16,
            fontweight="bold",
            pad=15,
        )
        ax.set_xlabel("Retrofit Measure (sequential application)", fontsize=12, fontweight="bold")
        ax.set_ylabel(
            "Marginal Efficiency (kWh saved per £1,000 invested)",
            fontsize=12,
            fontweight="bold",
            color=colors["high"],
        )
        ax.tick_params(axis="y", labelcolor=colors["high"])
        ax.set_ylim(0, y_max)
        ax.set_xticks(x)
        ax.set_xticklabels(x_labels, rotation=0)

        ax.axhline(threshold_eff, linestyle="--", color=colors["threshold"], linewidth=2, alpha=0.8)
        threshold_y_frac = threshold_eff / y_max if y_max > 0 else 0.0
        ax.text(
            0.98,
            min(threshold_y_frac + 0.03, 0.98),
            "Cost-effective threshold\n(2,500 kWh/£1k)",
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=10,
            color=colors["threshold"],
            fontweight="bold",
        )

        # Bar value labels
        for rect, v in zip(bars, efficiency):
            ax.text(
                rect.get_x() + rect.get_width() / 2,
                rect.get_height() + y_max * 0.02,
                f"{v:,.0f}",
                ha="center",
                va="bottom",
                fontsize=11,
                fontweight="bold",
            )

        # Secondary axis for cumulative capex
        ax2 = ax.twinx()
        ax2.plot(x, cumulative_capex, color=colors["line"], marker="o", linewidth=3)
        ax2.set_ylabel("Cumulative Investment (£)", fontsize=12, fontweight="bold", color=colors["line"])
        ax2.tick_params(axis="y", labelcolor=colors["line"])
        ax2.set_ylim(0, right_max)
        ax2.get_yaxis().set_major_formatter(plt.FuncFormatter(lambda v, _: f"{int(v):,}"))

        # Cumulative capex labels near markers (avoid top overlap)
        capex_offset = right_max * 0.02
        for xi, capex in zip(x, cumulative_capex):
            y = capex + capex_offset
            va = "bottom"
            if y >= right_max * 0.97:
                y = capex - capex_offset * 1.2
                va = "top"
            ax2.text(
                xi,
                y,
                _format_gbp(capex),
                ha="center",
                va=va,
                fontsize=10,
                fontweight="bold",
                color=colors["line"],
            )

        # Tipping point callouts
        pre_tipping = df[~df["is_beyond_tipping_point"] & (df["step"] > 0)]
        if not pre_tipping.empty:
            tp1 = pre_tipping.iloc[-1]
            tp1_x = int(pre_tipping.index[-1])
            tp1_cost = float(tp1["cumulative_capex"])
            tp1_reduction = 100.0 - float(tp1["remaining_demand_pct"])
            ax.annotate(
                f"TIPPING POINT 1\n{_format_gbp(tp1_cost)} cumulative\n{tp1_reduction:.0f}% demand reduction",
                xy=(tp1_x, threshold_eff),
                xytext=(min(tp1_x + 0.8, n - 0.2), y_max * 0.88),
                ha="left",
                va="top",
                fontsize=10,
                fontweight="bold",
                color=colors["threshold"],
                bbox=dict(boxstyle="round,pad=0.35", fc="#e3f2fd", ec=colors["threshold"], lw=1.5),
                arrowprops=dict(arrowstyle="->", color=colors["threshold"], lw=2),
            )

        post_tipping = df[df["is_beyond_tipping_point"] & (df["step"] > 0)]
        if not post_tipping.empty:
            tp2 = post_tipping.iloc[0]
            tp2_x = int(post_tipping.index[0])
            tp2_cost = float(tp2["cumulative_capex"])
            ax.annotate(
                f"TIPPING POINT 2\n{_format_gbp(tp2_cost)} cumulative\nMarginal returns collapse",
                xy=(tp2_x, float(tp2["marginal_efficiency_kwh_per_1k"])),
                xytext=(min(tp2_x + 2.0, n - 0.2), y_max * 0.62),
                ha="left",
                va="top",
                fontsize=10,
                fontweight="bold",
                color="#e65100",
                bbox=dict(boxstyle="round,pad=0.35", fc="#fff3e0", ec="#fb8c00", lw=1.5),
                arrowprops=dict(arrowstyle="->", color="#fb8c00", lw=2),
            )

        handles = [
            Patch(color=colors["high"], label="High efficiency (>2,500 kWh/£1k)"),
            Patch(color=colors["moderate"], label="Moderate efficiency (1,000–2,500 kWh/£1k)"),
            Patch(color=colors["low"], label="Low efficiency (<1,000 kWh/£1k)"),
            Line2D([0], [0], color=colors["line"], marker="o", lw=3, label="Cumulative investment (£)"),
        ]
        ax.legend(handles=handles, loc="upper left", frameon=True)

        fig.text(
            0.99,
            0.02,
            "Source: Energy Saving Trust (2024) costs; Heat Street EPC analysis",
            ha="right",
            va="bottom",
            fontsize=9,
            style="italic",
            color="#757575",
        )

        fig.tight_layout(rect=[0, 0.03, 1, 1])
        fig.savefig(save_png, dpi=300, bbox_inches="tight")
        fig.savefig(save_svg, bbox_inches="tight")
        plt.close(fig)

        logger.info(f"Saved tipping point chart to: {save_png}")
        logger.info(f"Saved tipping point chart (SVG) to: {save_svg}")

    def plot_heat_network_tiers(
        self,
        tier_data: pd.DataFrame,
        save_path: Optional[Path] = None
    ):
        """
        Create chart showing heat network tier distribution.

        Args:
            tier_data: DataFrame with tier classification counts
            save_path: Path to save figure
        """
        logger.info("Creating heat network tier chart...")

        if save_path is None:
            save_path = self.output_dir / "heat_network_tiers.png"

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

        # Pie chart
        colors = ['#8B0000', '#DC143C', '#FF8C00', '#FFD700', '#90EE90']
        explode = (0.05, 0.05, 0, 0, 0)

        if 'Property Count' in tier_data.columns:
            ax1.pie(tier_data['Property Count'], labels=tier_data['Tier'],
                   autopct='%1.1f%%', startangle=90, colors=colors, explode=explode,
                   textprops={'fontsize': 10, 'fontweight': 'bold'})
            ax1.set_title('Heat Network Tier Distribution', fontsize=12, fontweight='bold', pad=20)

            # Bar chart with recommended pathways
            ax2.barh(tier_data['Tier'], tier_data['Property Count'], color=colors, edgecolor='black')
            ax2.set_xlabel('Number of Properties', fontsize=11, fontweight='bold')
            ax2.set_title('Properties by Heat Network Tier', fontsize=12, fontweight='bold', pad=20)
            ax2.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{int(x):,}'))
            ax2.grid(True, alpha=0.3, axis='x')

        plt.tight_layout()
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        plt.close()

        logger.info(f"Saved heat network tiers to: {save_path}")

    def generate_summary_report(
        self,
        archetype_results: Dict,
        scenario_results: Dict,
        tier_summary: pd.DataFrame,
        output_path: Optional[Path] = None
    ):
        """
        Generate a comprehensive text summary report.

        Args:
            archetype_results: Results from archetype analysis
            scenario_results: Results from scenario modeling
            tier_summary: Heat network tier summary
            output_path: Path to save report
        """
        logger.info("Generating summary report...")

        if output_path is None:
            output_path = DATA_OUTPUTS_DIR / "reports" / "executive_summary.txt"

        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("="*80 + "\n")
            f.write("HEAT STREET PROJECT: EXECUTIVE SUMMARY\n")
            f.write("Edwardian Terraced Housing - London EPC Analysis\n")
            f.write("="*80 + "\n\n")

            # Archetype Summary
            f.write("1. PROPERTY ARCHETYPE CHARACTERISTICS\n")
            f.write("-"*80 + "\n")
            if 'epc_bands' in archetype_results:
                f.write("\nCurrent EPC Band Distribution:\n")
                for band, count in archetype_results['epc_bands']['frequency'].items():
                    pct = archetype_results['epc_bands']['percentage'][band]
                    f.write(f"  Band {band}: {count:,} properties ({pct:.1f}%)\n")

            if 'sap_scores' in archetype_results:
                f.write(f"\nSAP Score Statistics:\n")
                f.write(f"  Mean: {archetype_results['sap_scores']['mean']:.1f}\n")
                f.write(f"  Median: {archetype_results['sap_scores']['median']:.1f}\n")
                f.write(f"  Range: {archetype_results['sap_scores']['min']:.0f} - {archetype_results['sap_scores']['max']:.0f}\n")

            if 'wall_construction' in archetype_results:
                f.write(f"\nWall Insulation:\n")
                f.write(f"  Insulation rate: {archetype_results['wall_construction']['insulation_rate']:.1f}%\n")

        # Scenario Results
        f.write("\n\n2. DECARBONIZATION SCENARIO ANALYSIS\n")
        f.write("-"*80 + "\n")
        for scenario, results in scenario_results.items():
            scenario_label = self._scenario_label(scenario, results)
            f.write(f"\n{scenario_label}:\n")
            f.write(f"  Total capital cost: £{results['capital_cost_total']:,.0f}\n")
            f.write(f"  Cost per property: £{results['capital_cost_per_property']:,.0f}\n")
            f.write(f"  Annual CO2 reduction: {results['annual_co2_reduction_kg']/1000:,.0f} tonnes\n")
            f.write(f"  Annual bill savings: £{results['annual_bill_savings']:,.0f}\n")
            if 'average_payback_years' in results:
                f.write(f"  Average payback: {results['average_payback_years']:.1f} years\n")

            # EPC band shift summary
            band_summary = results.get('epc_band_shift_summary', {})
            if band_summary:
                before_pct = band_summary.get('band_c_or_better_before_pct', 0)
                after_pct = band_summary.get('band_c_or_better_after_pct', 0)
                f.write(f"  EPC Band C or better: {before_pct:.1f}% -> {after_pct:.1f}% (+{after_pct - before_pct:.1f}pp)\n")

            # Cost-effectiveness summary
            ce_summary = results.get('cost_effectiveness_summary', {})
            if ce_summary:
                ce_pct = ce_summary.get('cost_effective_pct', 0)
                f.write(f"  Cost-effective upgrades: {ce_pct:.1f}%\n")

            # Carbon abatement cost
            if 'carbon_abatement_cost_median' in results:
                f.write(f"  Carbon abatement cost (median): £{results['carbon_abatement_cost_median']:.0f}/tCO2\n")

            # Heat Network Tiers
            f.write("\n\n3. HEAT NETWORK ZONE CLASSIFICATION\n")
            f.write("-"*80 + "\n")
            for _, row in tier_summary.iterrows():
                f.write(f"\n{row['Tier']}:\n")
                f.write(f"  Properties: {row['Property Count']:,} ({row['Percentage']:.1f}%)\n")
                f.write(f"  Recommendation: {row['Recommended Pathway']}\n")

            f.write("\n\n" + "="*80 + "\n")
            f.write("END OF REPORT\n")
            f.write("="*80 + "\n")

        self._export_report_datapoints(archetype_results, scenario_results, tier_summary)

        logger.info(f"Summary report saved to: {output_path}")

    def generate_markdown_summary(
        self,
        archetype_results: Dict,
        scenario_results: Dict,
        tier_summary: pd.DataFrame,
        output_path: Optional[Path] = None,
    ):
        """
        Generate a Markdown executive summary mirroring the text report content.

        Args:
            archetype_results: Results from archetype analysis
            scenario_results: Results from scenario modeling
            tier_summary: Heat network tier summary
            output_path: Path to save Markdown report
        """

        logger.info("Generating Markdown summary report...")

        if output_path is None:
            output_path = DATA_OUTPUTS_DIR / "reports" / "executive_summary.md"

        output_path.parent.mkdir(parents=True, exist_ok=True)

        lines: List[str] = []

        dashboard_tabs = [
            ("Overview", "Key KPIs across the whole dataset including stock size and carbon impacts."),
            ("Housing Stock", "EPC band mix, wall/roof construction, glazing, and heating system breakdowns."),
            ("Scenarios", "Capital costs, CO₂ reductions, bill savings, and payback timing for the main pathways."),
            ("Retrofit Readiness", "Insulation readiness, fabric-first findings, and emitter suitability insights."),
            ("Cost-Benefit", "Cost curves, sensitivity bands, and tier-by-tier cost-benefit summaries."),
            ("Boroughs", "Borough-level comparisons, including EPC band and readiness differences."),
            ("Case Street", "Worked example street with micro-segmentation of homes and measures."),
            ("Uncertainty", "Confidence bands and key modelling uncertainties to monitor."),
            ("Grid & Climate", "Grid peak impacts, climate considerations, and load profiles."),
            ("Policy", "Policy levers, data limitations, and recommended next steps."),
        ]

        # Header
        lines.append("# Heat Street Project: Executive Summary")
        lines.append("Edwardian Terraced Housing - London EPC Analysis")
        lines.append("")

        # Archetype Summary
        lines.append("## 1. Property Archetype Characteristics")
        if "epc_bands" in archetype_results:
            lines.append("### Current EPC Band Distribution")
            for band, count in archetype_results["epc_bands"]["frequency"].items():
                pct = archetype_results["epc_bands"]["percentage"][band]
                lines.append(f"- **Band {band}:** {count:,} properties ({pct:.1f}%)")
            lines.append("")

        if "sap_scores" in archetype_results:
            lines.append("### SAP Score Statistics")
            lines.append(f"- **Mean:** {archetype_results['sap_scores']['mean']:.1f}")
            lines.append(f"- **Median:** {archetype_results['sap_scores']['median']:.1f}")
            lines.append(
                f"- **Range:** {archetype_results['sap_scores']['min']:.0f} – {archetype_results['sap_scores']['max']:.0f}"
            )
            lines.append("")

        if "wall_construction" in archetype_results:
            lines.append("### Wall Insulation")
            lines.append(
                f"- **Insulation rate:** {archetype_results['wall_construction']['insulation_rate']:.1f}%"
            )
            lines.append("")

        # Scenario Results
        lines.append("## 2. Decarbonization Scenario Analysis")
        for scenario, results in scenario_results.items():
            scenario_label = self._scenario_label(scenario, results)
            lines.append(f"### {scenario_label}")
            lines.append(f"- **Total capital cost:** £{results['capital_cost_total']:,.0f}")
            lines.append(f"- **Cost per property:** £{results['capital_cost_per_property']:,.0f}")
            lines.append(
                f"- **Annual CO₂ reduction:** {results['annual_co2_reduction_kg']/1000:,.0f} tonnes"
            )
            lines.append(f"- **Annual bill savings:** £{results['annual_bill_savings']:,.0f}")
            if "average_payback_years" in results:
                lines.append(f"- **Average payback:** {results['average_payback_years']:.1f} years")
            lines.append("")

        # Heat Network Tiers
        lines.append("## 3. Heat Network Zone Classification")
        if not tier_summary.empty:
            lines.append("| Tier | Property Count | Percentage | Recommended Pathway |")
            lines.append("| --- | ---: | ---: | --- |")
            for _, row in tier_summary.iterrows():
                lines.append(
                    f"| {row['Tier']} | {int(row['Property Count']):,} | {row['Percentage']:.1f}% | {row['Recommended Pathway']} |"
                )
        else:
            lines.append("No heat network tier data available.")

        lines.append("")
        lines.append("## 4. React Dashboard Coverage")
        lines.append("This report aligns with the interactive dashboard. Each tab is represented below:")
        for tab_name, description in dashboard_tabs:
            lines.append(f"- **{tab_name}:** {description}")

        lines.append("")
        lines.append("---")
        lines.append("Report generated automatically by the Heat Street analysis pipeline.")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        self._export_report_datapoints(archetype_results, scenario_results, tier_summary)

        logger.info(f"Markdown summary report saved to: {output_path}")

    def _export_report_datapoints(
        self,
        archetype_results: Dict,
        scenario_results: Dict,
        tier_summary: pd.DataFrame,
    ) -> Path:
        """Export all datapoints used in the summary report to Excel."""
        output_path = DATA_OUTPUTS_DIR / "reports" / "executive_summary_datapoints.xlsx"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        dashboard_tabs = [
            ("Overview", "Key KPIs across the whole dataset including stock size and carbon impacts."),
            ("Housing Stock", "EPC band mix, wall/roof construction, glazing, and heating system breakdowns."),
            ("Scenarios", "Capital costs, CO₂ reductions, bill savings, and payback timing for the main pathways."),
            ("Retrofit Readiness", "Insulation readiness, fabric-first findings, and emitter suitability insights."),
            ("Cost-Benefit", "Cost curves, sensitivity bands, and tier-by-tier cost-benefit summaries."),
            ("Boroughs", "Borough-level comparisons, including EPC band and readiness differences."),
            ("Case Street", "Worked example street with micro-segmentation of homes and measures."),
            ("Uncertainty", "Confidence bands and key modelling uncertainties to monitor."),
            ("Grid & Climate", "Grid peak impacts, climate considerations, and load profiles."),
            ("Policy", "Policy levers, data limitations, and recommended next steps."),
        ]

        with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
            pd.DataFrame([{
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "report_title": "Heat Street Project: Executive Summary",
            }]).to_excel(writer, sheet_name="Report Metadata", index=False)

            if "epc_bands" in archetype_results:
                epc_rows = []
                for band, count in archetype_results["epc_bands"]["frequency"].items():
                    pct = archetype_results["epc_bands"]["percentage"][band]
                    epc_rows.append({
                        "epc_band": band,
                        "properties": count,
                        "percentage": pct,
                    })
                pd.DataFrame(epc_rows).to_excel(writer, sheet_name="EPC Bands", index=False)

            if "sap_scores" in archetype_results:
                sap_scores = archetype_results["sap_scores"]
                pd.DataFrame([{
                    "mean": sap_scores.get("mean"),
                    "median": sap_scores.get("median"),
                    "min": sap_scores.get("min"),
                    "max": sap_scores.get("max"),
                }]).to_excel(writer, sheet_name="SAP Scores", index=False)

            if "wall_construction" in archetype_results:
                pd.DataFrame([{
                    "insulation_rate_pct": archetype_results["wall_construction"].get("insulation_rate"),
                }]).to_excel(writer, sheet_name="Wall Insulation", index=False)

            scenario_rows = []
            band_shift_rows = []
            cost_effectiveness_rows = []
            carbon_abatement_rows = []
            for scenario, results in scenario_results.items():
                scenario_label = self._scenario_label(scenario, results)
                scenario_rows.append({
                    "scenario_id": scenario,
                    "scenario": scenario_label,
                    "capital_cost_total": results.get("capital_cost_total"),
                    "capital_cost_per_property": results.get("capital_cost_per_property"),
                    "annual_co2_reduction_tonnes": results.get("annual_co2_reduction_kg", 0) / 1000,
                    "cost_per_tco2_20yr_gbp": self._cost_per_tco2_20yr_gbp(results),
                    "annual_bill_savings": results.get("annual_bill_savings"),
                    "average_payback_years": results.get("average_payback_years"),
                })

                band_summary = results.get("epc_band_shift_summary", {})
                if band_summary:
                    before_pct = band_summary.get("band_c_or_better_before_pct", 0)
                    after_pct = band_summary.get("band_c_or_better_after_pct", 0)
                    band_shift_rows.append({
                        "scenario_id": scenario,
                        "scenario": scenario_label,
                        "band_c_or_better_before_pct": before_pct,
                        "band_c_or_better_after_pct": after_pct,
                        "band_c_or_better_change_pp": after_pct - before_pct,
                    })

                ce_summary = results.get("cost_effectiveness_summary", {})
                if ce_summary:
                    cost_effectiveness_rows.append({
                        "scenario_id": scenario,
                        "scenario": scenario_label,
                        "cost_effective_pct": ce_summary.get("cost_effective_pct"),
                    })

                if "carbon_abatement_cost_median" in results:
                    carbon_abatement_rows.append({
                        "scenario_id": scenario,
                        "scenario": scenario_label,
                        "carbon_abatement_cost_median": results.get("carbon_abatement_cost_median"),
                    })

            if scenario_rows:
                pd.DataFrame(scenario_rows).to_excel(writer, sheet_name="Scenario Summary", index=False)
            if band_shift_rows:
                pd.DataFrame(band_shift_rows).to_excel(writer, sheet_name="EPC Band Shifts", index=False)
            if cost_effectiveness_rows:
                pd.DataFrame(cost_effectiveness_rows).to_excel(
                    writer, sheet_name="Cost Effectiveness", index=False
                )
            if carbon_abatement_rows:
                pd.DataFrame(carbon_abatement_rows).to_excel(
                    writer, sheet_name="Carbon Abatement", index=False
                )

            if not tier_summary.empty:
                tier_rows = []
                for _, row in tier_summary.iterrows():
                    tier_rows.append({
                        "tier": row["Tier"],
                        "property_count": row["Property Count"],
                        "percentage": row["Percentage"],
                        "recommended_pathway": row["Recommended Pathway"],
                    })
                pd.DataFrame(tier_rows).to_excel(writer, sheet_name="Heat Network Tiers", index=False)

            pd.DataFrame(dashboard_tabs, columns=["tab", "description"]).to_excel(
                writer, sheet_name="Dashboard Coverage", index=False
            )

        logger.info(f"Summary report datapoints saved to: {output_path}")
        return output_path

    def export_to_excel(
        self,
        archetype_results: Dict,
        scenario_results: Dict,
        subsidy_results: Optional[Dict] = None,
        df_properties: Optional[pd.DataFrame] = None,
        output_path: Optional[Path] = None,
        borough_breakdown: Optional[pd.DataFrame] = None,
        case_street_summary: Optional[Dict] = None,
    ):
        """
        Export all results to a formatted Excel workbook.

        Args:
            archetype_results: Results from archetype analysis
            scenario_results: Results from scenario modeling
            subsidy_results: Results from subsidy sensitivity analysis
            df_properties: Property-level DataFrame
            output_path: Path to save Excel file
            borough_breakdown: Borough-level breakdown DataFrame
            case_street_summary: Case street summary dictionary
        """
        logger.info("Exporting results to Excel...")

        if output_path is None:
            output_path = DATA_OUTPUTS_DIR / "heat_street_analysis_results.xlsx"

        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            import openpyxl
            from openpyxl.styles import Font, Alignment, PatternFill
            from openpyxl.utils.dataframe import dataframe_to_rows
        except ImportError:
            logger.warning("openpyxl not installed. Using basic Excel export...")
            # Fallback to basic pandas export
            with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:
                self._export_basic_excel(
                    writer,
                    archetype_results,
                    scenario_results,
                    subsidy_results,
                    df_properties,
                    borough_breakdown,
                    case_street_summary,
                )
            logger.info(f"Basic Excel export saved to: {output_path}")
            return

        # Create workbook with formatted sheets
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:

            # Sheet 1: Executive Summary
            self._write_summary_sheet(writer, archetype_results, scenario_results)

            # Sheet 2: EPC Band Distribution
            if 'epc_bands' in archetype_results:
                self._write_epc_bands_sheet(writer, archetype_results['epc_bands'])

            # Sheet 3: Scenario Comparison
            if scenario_results:
                self._write_scenarios_sheet(writer, scenario_results)

            # Sheet 4: Subsidy Sensitivity
            if subsidy_results:
                self._write_subsidy_sheet(writer, subsidy_results)

            # Sheet 5: Report Headline Data
            headline_df = build_report_headline_dataframe(
                archetype_results=archetype_results,
                scenario_results=scenario_results,
                subsidy_results=subsidy_results,
                borough_breakdown=borough_breakdown,
                case_street_summary=case_street_summary,
            )
            headline_df.to_excel(writer, sheet_name="report_headline_data", index=False)

            # Sheet 6: Property Details (sample)
            if df_properties is not None and not df_properties.empty:
                # Export first 1000 properties to avoid huge files
                sample_df = df_properties.head(1000).copy()
                sample_df.to_excel(writer, sheet_name='Property Sample', index=False)

        logger.info(f"Excel workbook saved to: {output_path}")

    def _write_summary_sheet(self, writer, archetype_results: Dict, scenario_results: Dict):
        """Write executive summary sheet."""
        summary_data = []

        summary_data.append(['HEAT STREET PROJECT - EXECUTIVE SUMMARY'])
        summary_data.append([''])
        summary_data.append(['1. PROPERTY ARCHETYPE CHARACTERISTICS'])
        summary_data.append([''])

        # EPC Bands
        if 'epc_bands' in archetype_results:
            summary_data.append(['EPC Band Distribution:'])
            for band in ['A', 'B', 'C', 'D', 'E', 'F', 'G']:
                if band in archetype_results['epc_bands']['frequency']:
                    count = archetype_results['epc_bands']['frequency'][band]
                    pct = archetype_results['epc_bands']['percentage'][band]
                    summary_data.append([f'Band {band}', count, f'{pct:.1f}%'])

        # SAP Scores
        if 'sap_scores' in archetype_results:
            summary_data.append([''])
            summary_data.append(['SAP Score Statistics:'])
            summary_data.append(['Mean', archetype_results['sap_scores']['mean']])
            summary_data.append(['Median', archetype_results['sap_scores']['median']])

        # Wall Construction
        if 'wall_construction' in archetype_results:
            summary_data.append([''])
            summary_data.append(['Wall Construction:'])
            summary_data.append(['Insulation Rate (%)', archetype_results['wall_construction']['insulation_rate']])

        summary_data.append([''])
        summary_data.append(['2. SCENARIO ANALYSIS SUMMARY'])
        summary_data.append([''])

        # Scenarios
        for scenario, results in scenario_results.items():
            scenario_label = self._scenario_label(scenario, results)
            summary_data.append([scenario_label])
            summary_data.append(['Capital Cost (total)', f"£{results['capital_cost_total']:,.0f}"])
            summary_data.append(['Cost per Property', f"£{results['capital_cost_per_property']:,.0f}"])
            summary_data.append(['Annual CO2 Reduction (kg)', f"{results['annual_co2_reduction_kg']:,.0f}"])
            cost_per_tco2_20yr = self._cost_per_tco2_20yr_gbp(results)
            if cost_per_tco2_20yr is not None:
                summary_data.append(['Cost per tCO2 (20yr, £)', f"£{cost_per_tco2_20yr:,.0f}"])
            summary_data.append(['Annual Bill Savings', f"£{results['annual_bill_savings']:,.0f}"])
            if 'average_payback_years' in results:
                summary_data.append(['Average Payback (years)', f"{results['average_payback_years']:.1f}"])
            summary_data.append([''])

        df_summary = pd.DataFrame(summary_data)
        df_summary.to_excel(writer, sheet_name='Executive Summary', index=False, header=False)

    def _write_epc_bands_sheet(self, writer, epc_data: Dict):
        """Write EPC bands sheet."""
        bands = ['A', 'B', 'C', 'D', 'E', 'F', 'G']
        frequencies = [epc_data['frequency'].get(band, 0) for band in bands]
        percentages = [epc_data['percentage'].get(band, 0) for band in bands]

        df_epc = pd.DataFrame({
            'EPC Band': bands,
            'Number of Properties': frequencies,
            'Percentage': [f'{p:.2f}%' for p in percentages]
        })

        df_epc.to_excel(writer, sheet_name='EPC Bands', index=False)

    def _write_scenarios_sheet(self, writer, scenario_results: Dict):
        """Write scenario comparison sheet."""
        scenarios = []

        for scenario_name, results in scenario_results.items():
            # Extract nested summaries
            ce_summary = results.get('cost_effectiveness_summary', {})
            band_summary = results.get('epc_band_shift_summary', {})
            scenario_label = self._scenario_label(scenario_name, results)

            scenarios.append({
                'Scenario': scenario_label,
                'Capital Cost (Total)': results['capital_cost_total'],
                'Cost per Property': results['capital_cost_per_property'],
                'Annual Energy Reduction (kWh)': results['annual_energy_reduction_kwh'],
                'Annual CO2 Reduction (kg)': results['annual_co2_reduction_kg'],
                'Cost per tCO2 (20yr, £)': self._cost_per_tco2_20yr_gbp(results),
                'Annual Bill Savings (£)': results['annual_bill_savings'],
                'Baseline Bill (£)': results.get('baseline_bill_total', 0),
                'Post-Measure Bill (£)': results.get('post_measure_bill_total', 0),
                'Baseline CO2 (kg)': results.get('baseline_co2_total_kg', 0),
                'Post-Measure CO2 (kg)': results.get('post_measure_co2_total_kg', 0),
                'Average Payback (years)': results.get('average_payback_years', 0),
                'Median Payback (years)': results.get('median_payback_years', 0),
                # Cost-effectiveness metrics
                'Cost-effective Count': ce_summary.get('cost_effective_count', 0),
                'Cost-effective (%)': ce_summary.get('cost_effective_pct', 0),
                'Not Cost-effective Count': ce_summary.get('not_cost_effective_count', 0),
                'Carbon Abatement Cost (£/tCO2)': results.get('carbon_abatement_cost_median', 0),
                # EPC band metrics
                'Band C+ Before (%)': band_summary.get('band_c_or_better_before_pct', 0),
                'Band C+ After (%)': band_summary.get('band_c_or_better_after_pct', 0),
                # HP readiness
                'ASHP Ready Properties': results.get('ashp_ready_properties', 0),
                'ASHP Fabric Applied': results.get('ashp_fabric_applied_properties', 0),
                'ASHP Not Eligible': results.get('ashp_not_ready_properties', 0),
                'HN Ready Properties': results.get('hn_ready_properties', 0),
                'HN Assigned (Hybrid)': results.get('hn_assigned_properties', 0),
                'ASHP Assigned (Hybrid)': results.get('ashp_assigned_properties', 0),
            })

        df_scenarios = pd.DataFrame(scenarios)
        df_scenarios.to_excel(writer, sheet_name='Scenario Comparison', index=False)

    def _write_subsidy_sheet(self, writer, subsidy_results: Dict):
        """Write subsidy sensitivity sheet."""
        subsidy_data = []

        for level, data in subsidy_results.items():
            subsidy_data.append({
                'Subsidy Level (%)': data['subsidy_percentage'],
                'Cost per Property (£)': data['capital_cost_per_property'],
                'Payback (years)': data['payback_years'],
                'Estimated Uptake (%)': data['estimated_uptake_rate'] * 100,
                'Properties Upgraded': data['properties_upgraded'],
                'Public Expenditure (£)': data['public_expenditure_total'],
                'Carbon Abatement Cost (£/tCO2)': data['carbon_abatement_cost_per_tonne']
            })

        df_subsidy = pd.DataFrame(subsidy_data)
        df_subsidy.to_excel(writer, sheet_name='Subsidy Sensitivity', index=False)

    def _export_basic_excel(
        self,
        writer,
        archetype_results,
        scenario_results,
        subsidy_results,
        df_properties,
        borough_breakdown,
        case_street_summary,
    ):
        """Basic Excel export without openpyxl formatting."""
        # Summary
        pd.DataFrame([{'Analysis': 'Heat Street Project', 'Status': 'Complete'}]).to_excel(
            writer, sheet_name='Summary', index=False
        )

        # Scenarios
        if scenario_results:
            scenarios = []
            for name, results in scenario_results.items():
                scenario_label = self._scenario_label(name, results)
                scenarios.append({
                    'Scenario': scenario_label,
                    'Cost': results['capital_cost_per_property'],
                    'CO2 Reduction': results['annual_co2_reduction_kg'],
                    'Cost per tCO2 (20yr, £)': self._cost_per_tco2_20yr_gbp(results),
                })
            pd.DataFrame(scenarios).to_excel(writer, sheet_name='Scenarios', index=False)

        headline_df = build_report_headline_dataframe(
            archetype_results=archetype_results,
            scenario_results=scenario_results,
            subsidy_results=subsidy_results,
            borough_breakdown=borough_breakdown,
            case_street_summary=case_street_summary,
        )
        headline_df.to_excel(writer, sheet_name="report_headline_data", index=False)

    def plot_retrofit_readiness_dashboard(
        self,
        df_readiness: pd.DataFrame,
        summary: Dict,
        save_path: Optional[Path] = None
    ):
        """
        Create comprehensive heat pump readiness dashboard.

        Args:
            df_readiness: DataFrame with readiness assessment
            summary: Summary statistics dictionary
            save_path: Path to save figure
        """
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle('Heat Pump Retrofit Readiness Dashboard', fontsize=16, fontweight='bold')

        # 1. Readiness Tier Distribution (top left)
        tier_labels = [
            'Tier 1\nReady Now',
            'Tier 2\nMinor Work',
            'Tier 3\nMajor Work',
            'Tier 4\nChallenging',
            'Tier 5\nNot Suitable'
        ]
        tier_counts = [summary['tier_distribution'].get(i, 0) for i in range(1, 6)]
        tier_colors = ['#2ecc71', '#3498db', '#f39c12', '#e74c3c', '#95a5a6']

        bars1 = ax1.bar(tier_labels, tier_counts, color=tier_colors, edgecolor='black', linewidth=1.5)
        ax1.set_ylabel('Number of Properties', fontsize=12)
        ax1.set_title('Heat Pump Readiness Distribution', fontsize=13, fontweight='bold')
        ax1.grid(axis='y', alpha=0.3)

        # Add value labels on bars
        for bar in bars1:
            height = bar.get_height()
            ax1.text(bar.get_x() + bar.get_width()/2., height,
                    f'{int(height):,}\n({height/sum(tier_counts)*100:.1f}%)',
                    ha='center', va='bottom', fontsize=10)

        # 2. Intervention Requirements (top right)
        interventions = [
            'Loft\nInsulation',
            'Solid Wall\nInsulation',
            'Cavity Wall\nInsulation',
            'Glazing\nUpgrade',
            'Radiator\nUpsizing'
        ]
        intervention_counts = [
            summary['needs_loft_insulation'],
            summary['needs_solid_wall_insulation'],
            summary['needs_cavity_wall_insulation'],
            summary['needs_glazing_upgrade'],
            summary['needs_radiator_upsizing']
        ]

        bars2 = ax2.barh(interventions, intervention_counts, color='#e74c3c', edgecolor='black', linewidth=1.5)
        ax2.set_xlabel('Number of Properties', fontsize=12)
        ax2.set_title('Required Interventions Before Heat Pump', fontsize=13, fontweight='bold')
        ax2.grid(axis='x', alpha=0.3)

        # Add value labels
        for i, (bar, count) in enumerate(zip(bars2, intervention_counts)):
            width = bar.get_width()
            pct = count / summary['total_properties'] * 100
            ax2.text(width, bar.get_y() + bar.get_height()/2.,
                    f' {int(count):,} ({pct:.0f}%)',
                    ha='left', va='center', fontsize=10)

        # 3. Cost Distribution by Tier (bottom left)
        tiers = list(range(1, 6))
        fabric_costs = [summary['fabric_cost_by_tier'].get(i, 0)/1000 for i in tiers]  # Convert to £k
        total_costs = [summary['total_cost_by_tier'].get(i, 0)/1000 for i in tiers]

        x = np.arange(len(tiers))
        width = 0.35

        bars3a = ax3.bar(x - width/2, fabric_costs, width, label='Fabric Pre-requisites',
                        color='#3498db', edgecolor='black', linewidth=1.5)
        bars3b = ax3.bar(x + width/2, total_costs, width, label='Total Retrofit Cost',
                        color='#e67e22', edgecolor='black', linewidth=1.5)

        ax3.set_xlabel('Readiness Tier', fontsize=12)
        ax3.set_ylabel('Average Cost (£k)', fontsize=12)
        ax3.set_title('Retrofit Costs by Readiness Tier', fontsize=13, fontweight='bold')
        ax3.set_xticks(x)
        ax3.set_xticklabels([f'Tier {i}' for i in tiers])
        ax3.legend(fontsize=10)
        ax3.grid(axis='y', alpha=0.3)

        # 4. Heat Demand Before/After (bottom right)
        demand_data = {
            'Current': summary['mean_current_heat_demand'],
            'After Fabric\nImprovements': summary['mean_post_fabric_heat_demand']
        }

        bars4 = ax4.bar(demand_data.keys(), demand_data.values(),
                       color=['#e74c3c', '#2ecc71'], edgecolor='black', linewidth=1.5)
        ax4.set_ylabel('Heat Demand (kWh/m²/year)', fontsize=12)
        ax4.set_title('Mean Heat Demand Reduction', fontsize=13, fontweight='bold')
        ax4.grid(axis='y', alpha=0.3)

        # Add value labels and reduction %
        for bar, (label, value) in zip(bars4, demand_data.items()):
            height = bar.get_height()
            ax4.text(bar.get_x() + bar.get_width()/2., height,
                    f'{value:.0f}',
                    ha='center', va='bottom', fontsize=11, fontweight='bold')

        # Add reduction annotation
        reduction = summary['heat_demand_reduction_percent']
        ax4.text(0.5, summary['mean_current_heat_demand'] * 0.5,
                f'{reduction:.0f}% reduction',
                ha='center', va='center', fontsize=14, fontweight='bold',
                bbox=dict(boxstyle='round', facecolor='white', edgecolor='black', linewidth=2))

        plt.tight_layout()

        if save_path is None:
            save_path = self.output_dir / "retrofit_readiness_dashboard.png"

        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        logger.info(f"✓ Saved retrofit readiness dashboard to {save_path}")
        plt.close()

    def plot_fabric_cost_distribution(
        self,
        df_readiness: pd.DataFrame,
        save_path: Optional[Path] = None
    ):
        """
        Create histogram of fabric pre-requisite costs.

        Args:
            df_readiness: DataFrame with readiness assessment
            save_path: Path to save figure
        """
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
        fig.suptitle('Fabric Pre-Requisite Cost Distribution', fontsize=14, fontweight='bold')

        # Histogram of costs
        costs = df_readiness['fabric_prerequisite_cost'] / 1000  # Convert to £k

        ax1.hist(costs, bins=30, color='#3498db', edgecolor='black', alpha=0.7)
        ax1.axvline(costs.median(), color='#e74c3c', linestyle='--', linewidth=2, label=f'Median: £{costs.median():.1f}k')
        ax1.axvline(costs.mean(), color='#2ecc71', linestyle='--', linewidth=2, label=f'Mean: £{costs.mean():.1f}k')
        ax1.set_xlabel('Fabric Pre-requisite Cost (£k)', fontsize=12)
        ax1.set_ylabel('Number of Properties', fontsize=12)
        ax1.set_title('Cost Distribution', fontsize=13)
        ax1.legend(fontsize=11)
        ax1.grid(axis='y', alpha=0.3)

        # Cumulative distribution
        sorted_costs = np.sort(costs)
        cumulative = np.arange(1, len(sorted_costs) + 1) / len(sorted_costs) * 100

        ax2.plot(sorted_costs, cumulative, color='#3498db', linewidth=2)
        ax2.axhline(50, color='#e74c3c', linestyle='--', linewidth=1.5, label='50%')
        ax2.axhline(80, color='#f39c12', linestyle='--', linewidth=1.5, label='80%')
        ax2.set_xlabel('Fabric Pre-requisite Cost (£k)', fontsize=12)
        ax2.set_ylabel('Cumulative Percentage (%)', fontsize=12)
        ax2.set_title('Cumulative Distribution', fontsize=13)
        ax2.legend(fontsize=11)
        ax2.grid(True, alpha=0.3)

        # Add cost thresholds
        cost_5k = (costs <= 5).sum() / len(costs) * 100
        cost_10k = (costs <= 10).sum() / len(costs) * 100
        cost_15k = (costs <= 15).sum() / len(costs) * 100

        textstr = f'Cost Thresholds:\n' \
                 f'≤ £5k: {cost_5k:.0f}%\n' \
                 f'≤ £10k: {cost_10k:.0f}%\n' \
                 f'≤ £15k: {cost_15k:.0f}%'

        ax2.text(0.98, 0.02, textstr, transform=ax2.transAxes,
                fontsize=11, verticalalignment='bottom', horizontalalignment='right',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

        plt.tight_layout()

        if save_path is None:
            save_path = self.output_dir / "fabric_cost_distribution.png"

        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        logger.info(f"✓ Saved fabric cost distribution to {save_path}")
        plt.close()

    def plot_heat_demand_scatter(
        self,
        df_readiness: pd.DataFrame,
        save_path: Optional[Path] = None
    ):
        """
        Create scatter plot of current vs post-fabric heat demand.

        Args:
            df_readiness: DataFrame with readiness assessment
            save_path: Path to save figure
        """
        fig, ax = plt.subplots(figsize=(12, 10))

        # Create scatter plot colored by readiness tier
        tier_colors = {
            1: '#2ecc71',
            2: '#3498db',
            3: '#f39c12',
            4: '#e74c3c',
            5: '#95a5a6'
        }

        tier_labels = {
            1: 'Tier 1: Ready Now',
            2: 'Tier 2: Minor Work',
            3: 'Tier 3: Major Work',
            4: 'Tier 4: Challenging',
            5: 'Tier 5: Not Suitable'
        }

        for tier in range(1, 6):
            mask = df_readiness['hp_readiness_tier'] == tier
            ax.scatter(
                df_readiness.loc[mask, 'heat_demand_kwh_m2'],
                df_readiness.loc[mask, 'heat_demand_after_fabric'],
                c=tier_colors[tier],
                label=tier_labels[tier],
                alpha=0.6,
                s=50,
                edgecolors='black',
                linewidth=0.5
            )

        # Add diagonal line (no improvement)
        max_demand = max(df_readiness['heat_demand_kwh_m2'].max(),
                        df_readiness['heat_demand_after_fabric'].max())
        ax.plot([0, max_demand], [0, max_demand], 'k--', linewidth=1, alpha=0.5, label='No improvement')

        # Add threshold lines
        ax.axhline(100, color='#2ecc71', linestyle=':', linewidth=2, alpha=0.7, label='HP Ready (<100)')
        ax.axhline(150, color='#f39c12', linestyle=':', linewidth=2, alpha=0.7, label='HP Viable (<150)')
        ax.axvline(100, color='#2ecc71', linestyle=':', linewidth=2, alpha=0.7)
        ax.axvline(150, color='#f39c12', linestyle=':', linewidth=2, alpha=0.7)

        ax.set_xlabel('Current Heat Demand (kWh/m²/year)', fontsize=12)
        ax.set_ylabel('Post-Fabric Heat Demand (kWh/m²/year)', fontsize=12)
        ax.set_title('Heat Demand: Current vs After Fabric Improvements', fontsize=14, fontweight='bold')
        ax.legend(fontsize=10, loc='upper left')
        ax.grid(True, alpha=0.3)

        plt.tight_layout()

        if save_path is None:
            save_path = self.output_dir / "heat_demand_scatter.png"

        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        logger.info(f"✓ Saved heat demand scatter plot to {save_path}")
        plt.close()


def main():
    """Main execution for report generation."""
    logger.info("Starting report generation...")

    # This would be called with actual results from the analysis pipeline
    # For now, just initialize
    generator = ReportGenerator()
    logger.info("Report generator ready!")


if __name__ == "__main__":
    main()
