"""
Additional Analysis and Reporting Module

Provides specialized reports and extracts for client presentations:
- Case street (Shakespeare Crescent) extract
- Borough-level aggregations
- Data quality reports
- Subsidy sensitivity analysis
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Optional, Tuple
from loguru import logger
from datetime import datetime


class AdditionalReports:
    """Generate specialized reports and analysis extracts."""

    def __init__(self):
        """Initialize additional reports generator."""
        logger.info("Initialized Additional Reports Generator")

    def extract_case_street(
        self,
        df: pd.DataFrame,
        street_name: str = "Shakespeare Crescent",
        output_path: Optional[Path] = None
    ) -> pd.DataFrame:
        """
        Extract and analyze data for a specific case street.

        Args:
            df: Full dataset
            street_name: Street name to extract
            output_path: Optional path to save extract

        Returns:
            DataFrame containing case street properties
        """
        logger.info(f"Extracting data for case street: {street_name}")

        # Search for properties on the street
        street_mask = df['ADDRESS1'].str.contains(street_name, case=False, na=False) | \
                      df['ADDRESS2'].str.contains(street_name, case=False, na=False) | \
                      df['ADDRESS3'].str.contains(street_name, case=False, na=False)

        case_street_df = df[street_mask].copy()

        if len(case_street_df) == 0:
            logger.warning(f"No properties found on {street_name}")
            return pd.DataFrame()

        logger.info(f"Found {len(case_street_df):,} properties on {street_name}")

        # Calculate summary statistics
        summary = self._calculate_case_street_summary(case_street_df, df)

        # Save extract if path provided
        if output_path:
            case_street_df.to_csv(output_path, index=False)
            logger.info(f"Saved case street extract to {output_path}")

            # Save summary
            summary_path = output_path.parent / f"{output_path.stem}_summary.txt"
            self._save_case_street_summary(summary, summary_path)

        return case_street_df

    def _calculate_case_street_summary(
        self,
        case_df: pd.DataFrame,
        full_df: pd.DataFrame
    ) -> Dict:
        """Calculate comparison statistics for case street vs full dataset."""
        summary = {
            'case_street': {},
            'london_wide': {},
            'comparison': {}
        }

        # Case street stats
        summary['case_street'] = {
            'property_count': len(case_df),
            'mean_energy_consumption': case_df['ENERGY_CONSUMPTION_CURRENT'].mean(),
            'mean_co2_emissions': case_df['CO2_EMISSIONS_CURRENT'].mean(),
            'mean_floor_area': case_df['TOTAL_FLOOR_AREA'].mean(),
            'mean_epc_rating': case_df['CURRENT_ENERGY_EFFICIENCY'].mean(),
            'epc_band_distribution': case_df['CURRENT_ENERGY_RATING'].value_counts().to_dict(),
        }

        # London-wide stats
        summary['london_wide'] = {
            'property_count': len(full_df),
            'mean_energy_consumption': full_df['ENERGY_CONSUMPTION_CURRENT'].mean(),
            'mean_co2_emissions': full_df['CO2_EMISSIONS_CURRENT'].mean(),
            'mean_floor_area': full_df['TOTAL_FLOOR_AREA'].mean(),
            'mean_epc_rating': full_df['CURRENT_ENERGY_EFFICIENCY'].mean(),
        }

        # Comparison (case street as % difference from London average)
        summary['comparison'] = {
            'energy_consumption_diff_pct': (
                (summary['case_street']['mean_energy_consumption'] -
                 summary['london_wide']['mean_energy_consumption']) /
                summary['london_wide']['mean_energy_consumption'] * 100
            ),
            'co2_emissions_diff_pct': (
                (summary['case_street']['mean_co2_emissions'] -
                 summary['london_wide']['mean_co2_emissions']) /
                summary['london_wide']['mean_co2_emissions'] * 100
            ),
            'floor_area_diff_pct': (
                (summary['case_street']['mean_floor_area'] -
                 summary['london_wide']['mean_floor_area']) /
                summary['london_wide']['mean_floor_area'] * 100
            ),
        }

        return summary

    def _save_case_street_summary(self, summary: Dict, path: Path):
        """Save case street summary to text file."""
        with open(path, 'w') as f:
            f.write("=" * 80 + "\n")
            f.write("CASE STREET ANALYSIS SUMMARY\n")
            f.write("=" * 80 + "\n\n")

            f.write("CASE STREET PROPERTIES\n")
            f.write("-" * 80 + "\n")
            f.write(f"Property Count: {summary['case_street']['property_count']:,}\n")
            f.write(f"Mean Energy Consumption: {summary['case_street']['mean_energy_consumption']:.1f} kWh/m²/year\n")
            f.write(f"Mean CO₂ Emissions: {summary['case_street']['mean_co2_emissions']:.1f} tonnes/year\n")
            f.write(f"Mean Floor Area: {summary['case_street']['mean_floor_area']:.1f} m²\n")
            f.write(f"Mean EPC Rating: {summary['case_street']['mean_epc_rating']:.1f}\n\n")

            f.write("LONDON-WIDE AVERAGE (Edwardian Terraces)\n")
            f.write("-" * 80 + "\n")
            f.write(f"Property Count: {summary['london_wide']['property_count']:,}\n")
            f.write(f"Mean Energy Consumption: {summary['london_wide']['mean_energy_consumption']:.1f} kWh/m²/year\n")
            f.write(f"Mean CO₂ Emissions: {summary['london_wide']['mean_co2_emissions']:.1f} tonnes/year\n")
            f.write(f"Mean Floor Area: {summary['london_wide']['mean_floor_area']:.1f} m²\n\n")

            f.write("COMPARISON (Case Street vs London Average)\n")
            f.write("-" * 80 + "\n")
            f.write(f"Energy Consumption: {summary['comparison']['energy_consumption_diff_pct']:+.1f}%\n")
            f.write(f"CO₂ Emissions: {summary['comparison']['co2_emissions_diff_pct']:+.1f}%\n")
            f.write(f"Floor Area: {summary['comparison']['floor_area_diff_pct']:+.1f}%\n")

        logger.info(f"Saved case street summary to {path}")

    def generate_borough_breakdown(
        self,
        df: pd.DataFrame,
        output_path: Optional[Path] = None
    ) -> pd.DataFrame:
        """
        Generate borough-level aggregated statistics.

        Args:
            df: Full dataset with LOCAL_AUTHORITY column
            output_path: Optional path to save breakdown

        Returns:
            DataFrame with borough-level aggregations
        """
        logger.info("Generating borough-level breakdown...")

        borough_breakdown = df.groupby('LOCAL_AUTHORITY').agg({
            'LMK_KEY': 'count',  # Property count
            'CURRENT_ENERGY_EFFICIENCY': 'mean',
            'ENERGY_CONSUMPTION_CURRENT': 'mean',
            'CO2_EMISSIONS_CURRENT': 'mean',
            'TOTAL_FLOOR_AREA': 'mean',
            'CURRENT_ENERGY_RATING': lambda x: x.mode()[0] if len(x.mode()) > 0 else 'Unknown',
        }).round(1)

        borough_breakdown.columns = [
            'property_count',
            'mean_epc_rating',
            'mean_energy_kwh_m2_year',
            'mean_co2_tonnes_year',
            'mean_floor_area_m2',
            'modal_epc_band',
        ]

        # Sort by property count descending
        borough_breakdown = borough_breakdown.sort_values('property_count', ascending=False)

        logger.info(f"Generated breakdown for {len(borough_breakdown)} boroughs")

        # Save if path provided
        if output_path:
            borough_breakdown.to_csv(output_path)
            logger.info(f"Saved borough breakdown to {output_path}")

        return borough_breakdown

    def generate_data_quality_report(
        self,
        df_raw: pd.DataFrame,
        df_validated: pd.DataFrame,
        validation_report: Dict,
        output_path: Optional[Path] = None
    ) -> str:
        """
        Generate comprehensive data quality report.

        Args:
            df_raw: Raw downloaded data
            df_validated: Validated/cleaned data
            validation_report: Validation statistics from EPCDataValidator
            output_path: Optional path to save report

        Returns:
            Report text
        """
        logger.info("Generating data quality report...")

        report_lines = []
        report_lines.append("=" * 80)
        report_lines.append("DATA QUALITY REPORT")
        report_lines.append("=" * 80)
        report_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append("")

        # Data volumes
        report_lines.append("DATA VOLUMES")
        report_lines.append("-" * 80)
        report_lines.append(f"Total records downloaded:     {len(df_raw):,}")
        report_lines.append(f"Records passed validation:    {len(df_validated):,}")
        report_lines.append(f"Records excluded:             {len(df_raw) - len(df_validated):,}")
        report_lines.append(f"Retention rate:               {len(df_validated)/len(df_raw)*100:.1f}%")
        report_lines.append("")

        # Exclusion reasons
        report_lines.append("EXCLUSION REASONS")
        report_lines.append("-" * 80)
        if validation_report:
            report_lines.append(f"Duplicates removed:           {validation_report.get('duplicates_removed', 0):,}")
            report_lines.append(f"Implausible floor areas:      {validation_report.get('implausible_floor_areas', 0):,}")
            report_lines.append(f"Inconsistent built form:      {validation_report.get('inconsistent_built_form', 0):,}")
            report_lines.append(f"Missing critical fields:      {validation_report.get('missing_critical_fields', 0):,}")
            report_lines.append(f"Construction date mismatches: {validation_report.get('construction_date_mismatches', 0):,}")
        report_lines.append("")

        # Field completeness
        report_lines.append("FIELD COMPLETENESS (Validated Data)")
        report_lines.append("-" * 80)

        key_fields = [
            'TOTAL_FLOOR_AREA',
            'CURRENT_ENERGY_EFFICIENCY',
            'ENERGY_CONSUMPTION_CURRENT',
            'CO2_EMISSIONS_CURRENT',
            'WALLS_DESCRIPTION',
            'ROOF_DESCRIPTION',
            'MAINHEAT_DESCRIPTION',
            'POSTCODE',
        ]

        for field in key_fields:
            if field in df_validated.columns:
                completeness = (1 - df_validated[field].isna().sum() / len(df_validated)) * 100
                report_lines.append(f"{field:35s} {completeness:5.1f}%")

        report_lines.append("")

        # Value ranges (sanity checks)
        report_lines.append("VALUE RANGE CHECKS")
        report_lines.append("-" * 80)

        if 'TOTAL_FLOOR_AREA' in df_validated.columns:
            report_lines.append(f"Floor Area:         {df_validated['TOTAL_FLOOR_AREA'].min():.0f} - {df_validated['TOTAL_FLOOR_AREA'].max():.0f} m²")

        if 'ENERGY_CONSUMPTION_CURRENT' in df_validated.columns:
            report_lines.append(f"Energy Consumption: {df_validated['ENERGY_CONSUMPTION_CURRENT'].min():.0f} - {df_validated['ENERGY_CONSUMPTION_CURRENT'].max():.0f} kWh/m²/year")

        if 'CO2_EMISSIONS_CURRENT' in df_validated.columns:
            report_lines.append(f"CO₂ Emissions:      {df_validated['CO2_EMISSIONS_CURRENT'].min():.1f} - {df_validated['CO2_EMISSIONS_CURRENT'].max():.1f} tonnes/year")

        report_lines.append("")

        # Duplicate handling
        if 'LMK_KEY' in df_validated.columns:
            unique_uprns = df_validated['LMK_KEY'].nunique()
            total_records = len(df_validated)
            report_lines.append("DUPLICATE HANDLING")
            report_lines.append("-" * 80)
            report_lines.append(f"Unique properties (UPRN):     {unique_uprns:,}")
            report_lines.append(f"Total records:                {total_records:,}")
            if unique_uprns < total_records:
                report_lines.append(f"Properties with multiple EPCs: {total_records - unique_uprns:,}")

        report_lines.append("")
        report_lines.append("=" * 80)

        report_text = "\n".join(report_lines)

        # Save if path provided
        if output_path:
            with open(output_path, 'w') as f:
                f.write(report_text)
            logger.info(f"Saved data quality report to {output_path}")

        return report_text

    def subsidy_sensitivity_analysis(
        self,
        df: pd.DataFrame,
        scenario_results: Dict,
        subsidy_levels: list = None,
        output_path: Optional[Path] = None
    ) -> pd.DataFrame:
        """
        Analyze impact of varying subsidy levels on uptake and costs.

        Args:
            df: Validated dataset
            scenario_results: Results from ScenarioModeler
            subsidy_levels: List of subsidy amounts to test (£)
            output_path: Optional path to save results

        Returns:
            DataFrame with sensitivity analysis results
        """
        if subsidy_levels is None:
            subsidy_levels = [0, 5000, 7500, 10000, 15000]

        logger.info(f"Running subsidy sensitivity analysis for {len(subsidy_levels)} levels...")

        results = []

        for subsidy in subsidy_levels:
            # Get base scenario capital costs
            heat_pump_cost = scenario_results.get('HEAT_PUMP', {}).get('capital_cost_per_property', 20000)
            fabric_cost = scenario_results.get('FABRIC_ONLY', {}).get('capital_cost_per_property', 12000)

            # Net cost after subsidy
            net_heat_pump_cost = max(0, heat_pump_cost - subsidy)
            net_fabric_cost = max(0, fabric_cost - subsidy)

            # Annual savings
            heat_pump_savings = scenario_results.get('HEAT_PUMP', {}).get('annual_bill_savings', 0) / \
                               scenario_results.get('HEAT_PUMP', {}).get('total_properties', 1)
            fabric_savings = scenario_results.get('FABRIC_ONLY', {}).get('annual_bill_savings', 0) / \
                           scenario_results.get('FABRIC_ONLY', {}).get('total_properties', 1)

            # Payback periods
            hp_payback = net_heat_pump_cost / heat_pump_savings if heat_pump_savings > 0 else 999
            fabric_payback = net_fabric_cost / fabric_savings if fabric_savings > 0 else 999

            # Estimate uptake (simple model based on payback)
            hp_uptake_rate = self._estimate_uptake_rate(hp_payback)
            fabric_uptake_rate = self._estimate_uptake_rate(fabric_payback)

            # Total costs and properties
            total_properties = len(df)
            hp_properties_upgraded = int(total_properties * hp_uptake_rate)
            fabric_properties_upgraded = int(total_properties * fabric_uptake_rate)

            # Public expenditure
            hp_public_cost = hp_properties_upgraded * subsidy
            fabric_public_cost = fabric_properties_upgraded * subsidy

            # Carbon abatement
            hp_co2_reduction_per_property = scenario_results.get('HEAT_PUMP', {}).get('annual_co2_reduction_kg', 0) / \
                                           scenario_results.get('HEAT_PUMP', {}).get('total_properties', 1)
            fabric_co2_reduction_per_property = scenario_results.get('FABRIC_ONLY', {}).get('annual_co2_reduction_kg', 0) / \
                                               scenario_results.get('FABRIC_ONLY', {}).get('total_properties', 1)

            hp_total_co2_reduction = hp_properties_upgraded * hp_co2_reduction_per_property / 1000  # tonnes
            fabric_total_co2_reduction = fabric_properties_upgraded * fabric_co2_reduction_per_property / 1000  # tonnes

            # Cost per tonne CO2 abated
            hp_cost_per_tonne = hp_public_cost / hp_total_co2_reduction if hp_total_co2_reduction > 0 else 999999
            fabric_cost_per_tonne = fabric_public_cost / fabric_total_co2_reduction if fabric_total_co2_reduction > 0 else 999999

            results.append({
                'subsidy_level': subsidy,
                'hp_payback_years': hp_payback,
                'hp_uptake_rate': hp_uptake_rate * 100,
                'hp_properties_upgraded': hp_properties_upgraded,
                'hp_public_cost_millions': hp_public_cost / 1_000_000,
                'hp_co2_reduction_tonnes': hp_total_co2_reduction,
                'hp_cost_per_tonne_co2': hp_cost_per_tonne,
                'fabric_payback_years': fabric_payback,
                'fabric_uptake_rate': fabric_uptake_rate * 100,
                'fabric_properties_upgraded': fabric_properties_upgraded,
                'fabric_public_cost_millions': fabric_public_cost / 1_000_000,
                'fabric_co2_reduction_tonnes': fabric_total_co2_reduction,
                'fabric_cost_per_tonne_co2': fabric_cost_per_tonne,
            })

        sensitivity_df = pd.DataFrame(results)

        # Save if path provided
        if output_path:
            sensitivity_df.to_csv(output_path, index=False)
            logger.info(f"Saved subsidy sensitivity analysis to {output_path}")

        logger.info(f"✓ Completed subsidy sensitivity analysis")
        return sensitivity_df

    def _estimate_uptake_rate(self, payback_years: float) -> float:
        """
        Estimate uptake rate based on payback period.

        Simple model: uptake decreases as payback increases.
        """
        if payback_years <= 5:
            return 0.80
        elif payback_years <= 10:
            return 0.60
        elif payback_years <= 15:
            return 0.40
        elif payback_years <= 20:
            return 0.20
        else:
            return 0.05
