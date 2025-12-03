"""
Reporting and Visualization Module

Creates charts, figures, and summary reports for the project.
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from typing import Dict, List, Optional
from loguru import logger

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import load_config, DATA_OUTPUTS_DIR


class ReportGenerator:
    """
    Generates visualizations and reports for the analysis.
    """

    def __init__(self):
        """Initialize the report generator."""
        self.config = load_config()
        self.output_dir = DATA_OUTPUTS_DIR / "figures"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Set visualization style
        sns.set_style("whitegrid")
        sns.set_palette("husl")
        plt.rcParams['figure.figsize'] = (12, 8)
        plt.rcParams['font.size'] = 11

        logger.info("Initialized Report Generator")

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
        metrics = {
            'Capital Cost (£M)': [scenario_results[s]['capital_cost_total']/1_000_000 for s in scenarios],
            'Annual CO2 Savings (tonnes)': [scenario_results[s]['annual_co2_reduction_kg']/1000 for s in scenarios],
            'Payback (years)': [scenario_results[s].get('average_payback_years', 0) for s in scenarios]
        }

        fig, axes = plt.subplots(1, 3, figsize=(16, 5))

        for idx, (metric, values) in enumerate(metrics.items()):
            ax = axes[idx]
            bars = ax.bar(scenarios, values, color='steelblue', edgecolor='black', linewidth=1.2)

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

        with open(output_path, 'w') as f:
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
                f.write(f"\n{scenario.upper()}:\n")
                f.write(f"  Total capital cost: £{results['capital_cost_total']:,.0f}\n")
                f.write(f"  Cost per property: £{results['capital_cost_per_property']:,.0f}\n")
                f.write(f"  Annual CO2 reduction: {results['annual_co2_reduction_kg']/1000:,.0f} tonnes\n")
                f.write(f"  Annual bill savings: £{results['annual_bill_savings']:,.0f}\n")
                if 'average_payback_years' in results:
                    f.write(f"  Average payback: {results['average_payback_years']:.1f} years\n")

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

        logger.info(f"Summary report saved to: {output_path}")

    def export_to_excel(
        self,
        archetype_results: Dict,
        scenario_results: Dict,
        subsidy_results: Optional[Dict] = None,
        df_properties: Optional[pd.DataFrame] = None,
        output_path: Optional[Path] = None
    ):
        """
        Export all results to a formatted Excel workbook.

        Args:
            archetype_results: Results from archetype analysis
            scenario_results: Results from scenario modeling
            subsidy_results: Results from subsidy sensitivity analysis
            df_properties: Property-level DataFrame
            output_path: Path to save Excel file
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
                self._export_basic_excel(writer, archetype_results, scenario_results,
                                        subsidy_results, df_properties)
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

            # Sheet 5: Property Details (sample)
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
            summary_data.append([f'{scenario.upper()}'])
            summary_data.append(['Capital Cost (total)', f"£{results['capital_cost_total']:,.0f}"])
            summary_data.append(['Cost per Property', f"£{results['capital_cost_per_property']:,.0f}"])
            summary_data.append(['Annual CO2 Reduction (kg)', f"{results['annual_co2_reduction_kg']:,.0f}"])
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
            scenarios.append({
                'Scenario': scenario_name,
                'Capital Cost (Total)': results['capital_cost_total'],
                'Cost per Property': results['capital_cost_per_property'],
                'Annual Energy Reduction (kWh)': results['annual_energy_reduction_kwh'],
                'Annual CO2 Reduction (kg)': results['annual_co2_reduction_kg'],
                'Annual Bill Savings (£)': results['annual_bill_savings'],
                'Average Payback (years)': results.get('average_payback_years', 0),
                'Median Payback (years)': results.get('median_payback_years', 0)
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

    def _export_basic_excel(self, writer, archetype_results, scenario_results,
                           subsidy_results, df_properties):
        """Basic Excel export without openpyxl formatting."""
        # Summary
        pd.DataFrame([{'Analysis': 'Heat Street Project', 'Status': 'Complete'}]).to_excel(
            writer, sheet_name='Summary', index=False
        )

        # Scenarios
        if scenario_results:
            scenarios = []
            for name, results in scenario_results.items():
                scenarios.append({
                    'Scenario': name,
                    'Cost': results['capital_cost_per_property'],
                    'CO2 Reduction': results['annual_co2_reduction_kg']
                })
            pd.DataFrame(scenarios).to_excel(writer, sheet_name='Scenarios', index=False)


def main():
    """Main execution for report generation."""
    logger.info("Starting report generation...")

    # This would be called with actual results from the analysis pipeline
    # For now, just initialize
    generator = ReportGenerator()
    logger.info("Report generator ready!")


if __name__ == "__main__":
    main()
