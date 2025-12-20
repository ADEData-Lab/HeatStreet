"""
Additional Analysis and Reporting Module

Provides specialized reports and extracts for client presentations:
- Case street (Shakespeare Crescent) extract
- Constituency-level aggregations
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
    ) -> Tuple[pd.DataFrame, Dict]:
        """
        Extract and analyze data for a specific case street.

        Args:
            df: Full dataset
            street_name: Street name to extract
            output_path: Optional path to save extract

        Returns:
            Tuple of (case street DataFrame, summary dictionary)
        """
        logger.info(f"Extracting data for case street: {street_name}")

        # Search for properties on the street
        street_mask = df['ADDRESS1'].str.contains(street_name, case=False, na=False) | \
                      df['ADDRESS2'].str.contains(street_name, case=False, na=False) | \
                      df['ADDRESS3'].str.contains(street_name, case=False, na=False)

        case_street_df = df[street_mask].copy()

        if len(case_street_df) == 0:
            logger.warning(f"No properties found on {street_name}")
            return pd.DataFrame(), {}

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

        return case_street_df, summary

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
        with open(path, 'w', encoding='utf-8') as f:
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

            f.write("LONDON-WIDE AVERAGE (Study Sample)\n")
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

    def generate_constituency_breakdown(
        self,
        df: pd.DataFrame,
        output_path: Optional[Path] = None
    ) -> pd.DataFrame:
        """
        Generate constituency-level aggregated statistics.

        Args:
            df: Full dataset with constituency column
            output_path: Optional path to save breakdown

        Returns:
            DataFrame with constituency-level aggregations
        """
        logger.info("Generating constituency-level breakdown...")

        constituency_column = None
        for candidate in [
            "CONSTITUENCY_NAME",
            "CONSTITUENCY",
            "WESTMINSTER_PARLIAMENTARY_CONSTITUENCY",
            "PCON_NAME",
        ]:
            if candidate in df.columns:
                constituency_column = candidate
                break

        if constituency_column is None:
            logger.warning("No constituency column found; skipping constituency breakdown.")
            return pd.DataFrame()

        constituency_breakdown = df.groupby(constituency_column).agg({
            'LMK_KEY': 'count',  # Property count
            'CURRENT_ENERGY_EFFICIENCY': 'mean',
            'ENERGY_CONSUMPTION_CURRENT': 'mean',
            'CO2_EMISSIONS_CURRENT': 'mean',
            'TOTAL_FLOOR_AREA': 'mean',
            'CURRENT_ENERGY_RATING': lambda x: x.mode()[0] if len(x.mode()) > 0 else 'Unknown',
        }).round(1)

        constituency_breakdown.columns = [
            'property_count',
            'mean_epc_rating',
            'mean_energy_kwh_m2_year',
            'mean_co2_tonnes_year',
            'mean_floor_area_m2',
            'modal_epc_band',
        ]

        # Sort by property count descending
        constituency_breakdown = constituency_breakdown.sort_values('property_count', ascending=False)

        logger.info(f"Generated breakdown for {len(constituency_breakdown)} constituencies")

        # Save if path provided
        if output_path:
            constituency_breakdown.to_csv(output_path)
            logger.info(f"Saved constituency breakdown to {output_path}")

        return constituency_breakdown

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
        report_lines.append("HEAT STREET PROJECT: DATA QUALITY REPORT")
        report_lines.append("=" * 80)
        report_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append(f"Report Version: 2.0")
        report_lines.append("")

        # Data volumes
        report_lines.append("DATA VOLUMES")
        report_lines.append("-" * 80)
        report_lines.append(f"Total records downloaded:     {len(df_raw):,}")
        report_lines.append(f"Records passed validation:    {len(df_validated):,}")
        report_lines.append(f"Records excluded:             {len(df_raw) - len(df_validated):,}")
        retention_rate = len(df_validated)/len(df_raw)*100 if len(df_raw) > 0 else 0
        report_lines.append(f"Retention rate:               {retention_rate:.1f}%")
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
            report_lines.append(f"Negative energy values:       {validation_report.get('negative_energy_values', 0):,}")
            report_lines.append(f"Negative CO₂ values:          {validation_report.get('negative_co2_values', 0):,}")
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
            'WALLS_ENERGY_EFF',
            'ROOF_DESCRIPTION',
            'ROOF_ENERGY_EFF',
            'WINDOWS_DESCRIPTION',
            'MAINHEAT_DESCRIPTION',
            'MAINHEAT_CONT_DESCRIPTION',
            'POSTCODE',
        ]

        for field in key_fields:
            if field in df_validated.columns:
                completeness = (1 - df_validated[field].isna().sum() / len(df_validated)) * 100
                report_lines.append(f"{field:35s} {completeness:5.1f}%")
            else:
                report_lines.append(f"{field:35s} (not available)")

        report_lines.append("")

        # Value ranges (sanity checks)
        report_lines.append("VALUE RANGE CHECKS")
        report_lines.append("-" * 80)

        if 'TOTAL_FLOOR_AREA' in df_validated.columns:
            report_lines.append(f"Floor Area:         {df_validated['TOTAL_FLOOR_AREA'].min():.0f} - {df_validated['TOTAL_FLOOR_AREA'].max():.0f} m²")
            report_lines.append(f"  Mean:             {df_validated['TOTAL_FLOOR_AREA'].mean():.1f} m²")

        if 'energy_kwh_per_m2_year' in df_validated.columns:
            report_lines.append(f"Energy (normalised): {df_validated['energy_kwh_per_m2_year'].min():.0f} - {df_validated['energy_kwh_per_m2_year'].max():.0f} kWh/m²/year")
            report_lines.append(f"  Mean:             {df_validated['energy_kwh_per_m2_year'].mean():.1f} kWh/m²/year")
        elif 'ENERGY_CONSUMPTION_CURRENT' in df_validated.columns:
            report_lines.append(f"Energy (raw):       {df_validated['ENERGY_CONSUMPTION_CURRENT'].min():.0f} - {df_validated['ENERGY_CONSUMPTION_CURRENT'].max():.0f}")

        if 'co2_kg_per_m2_year' in df_validated.columns:
            report_lines.append(f"CO₂ (normalised):   {df_validated['co2_kg_per_m2_year'].min():.1f} - {df_validated['co2_kg_per_m2_year'].max():.1f} kgCO₂/m²/year")
            report_lines.append(f"  Mean:             {df_validated['co2_kg_per_m2_year'].mean():.1f} kgCO₂/m²/year")
        elif 'CO2_EMISSIONS_CURRENT' in df_validated.columns:
            report_lines.append(f"CO₂ (raw):          {df_validated['CO2_EMISSIONS_CURRENT'].min():.2f} - {df_validated['CO2_EMISSIONS_CURRENT'].max():.2f} tonnes/year")

        if 'CURRENT_ENERGY_EFFICIENCY' in df_validated.columns:
            report_lines.append(f"SAP Score:          {df_validated['CURRENT_ENERGY_EFFICIENCY'].min():.0f} - {df_validated['CURRENT_ENERGY_EFFICIENCY'].max():.0f}")
            report_lines.append(f"  Mean:             {df_validated['CURRENT_ENERGY_EFFICIENCY'].mean():.1f}")

        report_lines.append("")

        # Duplicate handling
        if 'LMK_KEY' in df_validated.columns:
            unique_uprns = df_validated['LMK_KEY'].nunique()
            total_records = len(df_validated)
            report_lines.append("DUPLICATE HANDLING")
            report_lines.append("-" * 80)
            report_lines.append(f"Unique properties (LMK_KEY):  {unique_uprns:,}")
            report_lines.append(f"Total records:                {total_records:,}")
            if unique_uprns < total_records:
                report_lines.append(f"Properties with multiple EPCs: {total_records - unique_uprns:,}")

        report_lines.append("")

        # Methodological adjustments applied
        report_lines.append("METHODOLOGICAL ADJUSTMENTS APPLIED")
        report_lines.append("-" * 80)

        if 'prebound_factor' in df_validated.columns:
            mean_factor = df_validated['prebound_factor'].mean()
            report_lines.append(f"1. Prebound effect adjustment (Few et al., 2023)")
            report_lines.append(f"   Mean adjustment factor: {mean_factor:.2f}")
            report_lines.append(f"   Impact: Reduces baseline consumption estimates by ~{(1-mean_factor)*100:.0f}%")
        else:
            report_lines.append("1. Prebound effect adjustment: Not applied")

        if 'estimated_flow_temp' in df_validated.columns:
            mean_flow_temp = df_validated['estimated_flow_temp'].mean()
            report_lines.append(f"2. Heat pump flow temperature model")
            report_lines.append(f"   Mean estimated flow temp: {mean_flow_temp:.1f}°C")
        else:
            report_lines.append("2. Heat pump flow temperature model: Not applied")

        if 'sap_uncertainty' in df_validated.columns:
            mean_uncertainty = df_validated['sap_uncertainty'].mean()
            report_lines.append(f"3. Measurement uncertainty (Crawley et al., 2019)")
            report_lines.append(f"   Mean SAP uncertainty: ±{mean_uncertainty:.1f} points")
        else:
            report_lines.append("3. Measurement uncertainty: Not applied")

        report_lines.append("")

        # Known limitations
        report_lines.append("KNOWN LIMITATIONS")
        report_lines.append("-" * 80)

        known_limitations = [
            "1. EPC measurement error: ±8 SAP points at lower ratings, ±2.4 at higher "
            "ratings (Crawley et al., 2019)",
            "2. Performance gap: EPCs systematically overpredict energy consumption by "
            "8-48% depending on band (Few et al., 2023). Prebound effect adjustment applied.",
            "3. Heating controls data incomplete for majority of records - field often missing "
            "or non-standardised in EPC database",
            "4. Emitter sizing not recorded in EPC data - heat pump radiator upgrade needs "
            "estimated from fabric performance",
            "5. Conservation area status not identified in EPC data - some wall insulation "
            "recommendations (particularly EWI) may be impractical in listed buildings",
            "6. Hot water cylinder size not reliably recorded - cylinder upgrade needs assumed "
            "for all combi boiler replacements",
            "7. Loft insulation thickness often unspecified (recorded as efficiency rating only) "
            "- top-up needs estimated from rating where possible",
            "8. Solid floor insulation rarely feasible in some properties - excluded from "
            "cost estimates despite potential benefits",
            "9. EPC data represents modelled (SAP) consumption, not actual metered usage - "
            "savings estimates should be treated as indicative",
            "10. Heat network viability depends on local factors (existing infrastructure, "
            "anchor loads) not captured in property-level EPC data",
        ]

        for limitation in known_limitations:
            report_lines.append(limitation)
            report_lines.append("")

        report_lines.append("=" * 80)
        report_lines.append("END OF DATA QUALITY REPORT")
        report_lines.append("=" * 80)

        report_text = "\n".join(report_lines)

        # Save if path provided
        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
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

        scenario_lookup = {str(key).lower(): value for key, value in scenario_results.items()}
        heat_pump_results = scenario_lookup.get('heat_pump', {})
        fabric_results = scenario_lookup.get('fabric_only', {})

        results = []

        for subsidy in subsidy_levels:
            # Get base scenario capital costs
            heat_pump_cost = heat_pump_results.get('capital_cost_per_property', 20000)
            fabric_cost = fabric_results.get('capital_cost_per_property', 12000)

            # Net cost after subsidy
            net_heat_pump_cost = max(0, heat_pump_cost - subsidy)
            net_fabric_cost = max(0, fabric_cost - subsidy)

            # Annual savings
            heat_pump_savings = heat_pump_results.get('annual_bill_savings', 0) / \
                               heat_pump_results.get('total_properties', 1)
            fabric_savings = fabric_results.get('annual_bill_savings', 0) / \
                           fabric_results.get('total_properties', 1)

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
            hp_co2_reduction_per_property = heat_pump_results.get('annual_co2_reduction_kg', 0) / \
                                           heat_pump_results.get('total_properties', 1)
            fabric_co2_reduction_per_property = fabric_results.get('annual_co2_reduction_kg', 0) / \
                                               fabric_results.get('total_properties', 1)

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

    def analyze_heat_network_connection_thresholds(
        self,
        df: pd.DataFrame,
        tier_field: str = 'heat_network_tier',
        tier_values: list = None,
        output_path: Optional[Path] = None
    ) -> pd.DataFrame:
        """
        Analyze heat network viability at different connection rates.

        Models what proportion of properties need to connect for
        network economic viability.

        Args:
            df: DataFrame with heat network tier classifications
            tier_field: Column name for heat network tiers
            tier_values: List of tier values to analyze (default: ['Tier 3: High heat density'])
            output_path: Optional path to save results

        Returns:
            DataFrame with connection threshold analysis
        """
        if tier_values is None:
            tier_values = ['Tier 3: High heat density']

        logger.info(f"Analyzing heat network connection thresholds for {len(tier_values)} tiers...")

        all_results = []

        for tier in tier_values:
            if tier_field not in df.columns:
                logger.warning(f"Tier field '{tier_field}' not found, skipping threshold analysis")
                continue

            tier_df = df[df[tier_field] == tier].copy()
            n_properties = len(tier_df)

            if n_properties == 0:
                logger.warning(f"No properties found for {tier}")
                continue

            logger.info(f"  Analyzing {tier}: {n_properties:,} properties")

            # Network infrastructure costs (simplified model)
            NETWORK_FIXED_COST = 5_000_000  # Base network infrastructure
            PER_PROPERTY_CONNECTION = 5000   # Individual connection cost
            ANNUAL_STANDING_CHARGE = 200     # Per property per year
            HEAT_PRICE_PER_KWH = 0.08        # Delivered heat price (£/kWh)

            # Test different connection rates
            connection_rates = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]

            # Average baseline consumption for properties in this tier
            if 'baseline_consumption_kwh_year' in tier_df.columns:
                avg_consumption = tier_df['baseline_consumption_kwh_year'].mean()
            elif 'ENERGY_CONSUMPTION_CURRENT' in tier_df.columns and 'TOTAL_FLOOR_AREA' in tier_df.columns:
                avg_consumption = (tier_df['ENERGY_CONSUMPTION_CURRENT'] * tier_df['TOTAL_FLOOR_AREA']).mean()
            else:
                avg_consumption = 15000  # Default assumption

            for rate in connection_rates:
                n_connected = int(n_properties * rate)

                # Total infrastructure cost
                total_infra_cost = NETWORK_FIXED_COST + (n_connected * PER_PROPERTY_CONNECTION)

                # Annual revenue
                annual_standing_revenue = n_connected * ANNUAL_STANDING_CHARGE
                annual_heat_revenue = n_connected * avg_consumption * HEAT_PRICE_PER_KWH
                annual_revenue = annual_standing_revenue + annual_heat_revenue

                # Simple payback for network operator
                network_payback = total_infra_cost / annual_revenue if annual_revenue > 0 else np.inf

                # Typical viability threshold for infrastructure: 25 years
                viable = network_payback < 25

                all_results.append({
                    'tier': tier,
                    'properties_in_tier': n_properties,
                    'connection_rate': rate,
                    'properties_connected': n_connected,
                    'total_infrastructure_cost': total_infra_cost,
                    'annual_standing_charge_revenue': annual_standing_revenue,
                    'annual_heat_revenue': annual_heat_revenue,
                    'total_annual_revenue': annual_revenue,
                    'network_payback_years': network_payback,
                    'viable_25yr_threshold': viable,
                    'avg_consumption_per_property': avg_consumption,
                })

        threshold_df = pd.DataFrame(all_results)

        # Save if path provided
        if output_path:
            threshold_df.to_csv(output_path, index=False)
            logger.info(f"Saved heat network connection thresholds to {output_path}")

        # Report minimum viable connection rates
        for tier in tier_values:
            tier_results = threshold_df[threshold_df['tier'] == tier]
            viable = tier_results[tier_results['viable_25yr_threshold']]
            if len(viable) > 0:
                min_viable = viable['connection_rate'].min()
                logger.info(f"  {tier}: Minimum viable connection rate = {min_viable*100:.0f}%")
            else:
                logger.info(f"  {tier}: No viable connection rate found (all > 25 year payback)")

        logger.info(f"✓ Heat network connection threshold analysis complete")
        return threshold_df
