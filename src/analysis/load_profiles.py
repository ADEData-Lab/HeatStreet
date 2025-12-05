"""
Load Profiles Module

Generates normalized demand profiles and peak/average metrics for heat pathways.
Exposes system-level benefits of reduced peaks and load diversity.

Outputs:
- pathway_load_profile_timeseries.csv: Hourly/daily profiles by pathway
- pathway_load_profile_summary.csv: Peak, average, and ratios by pathway
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from loguru import logger

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import (
    load_config,
    DATA_PROCESSED_DIR,
    DATA_OUTPUTS_DIR
)


class LoadProfileGenerator:
    """
    Generates demand profiles for heat decarbonization pathways.

    Creates:
    - Hourly demand profiles (typical winter day)
    - Daily demand profiles (annual)
    - Peak and average power metrics
    - Street-level aggregated profiles
    """

    def __init__(self, output_dir: Optional[Path] = None):
        """Initialize the load profile generator."""
        self.config = load_config()
        self.output_dir = output_dir or DATA_OUTPUTS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Heat pump SCOP
        self.hp_scop = self.config.get('heat_pump', {}).get('scop', 3.0)

        logger.info("Initialized LoadProfileGenerator")

    def generate_hourly_profile_template(self) -> pd.DataFrame:
        """
        Generate a stylized hourly demand profile for a typical winter day.

        Profile based on typical UK domestic heating patterns:
        - Morning peak: 6-9am
        - Midday trough: 10am-4pm
        - Evening peak: 5-10pm
        - Night setback: 11pm-5am

        Returns:
            DataFrame with hour and demand_factor columns
        """
        hours = list(range(24))

        # Demand factors (1.0 = average hourly demand)
        # Total should sum to 24 (average of 1.0)
        demand_factors = [
            0.3,   # 00:00 - Night setback
            0.25,  # 01:00
            0.2,   # 02:00
            0.2,   # 03:00
            0.25,  # 04:00
            0.4,   # 05:00 - Start warming
            1.2,   # 06:00 - Morning peak starts
            1.8,   # 07:00 - Morning peak
            1.9,   # 08:00 - Morning peak max
            1.4,   # 09:00 - Morning peak declining
            1.0,   # 10:00 - Midday
            0.8,   # 11:00
            0.7,   # 12:00
            0.6,   # 13:00
            0.6,   # 14:00
            0.7,   # 15:00
            1.0,   # 16:00 - Afternoon rise
            1.5,   # 17:00 - Evening peak starts
            1.8,   # 18:00 - Evening peak
            1.9,   # 19:00 - Evening peak max
            1.7,   # 20:00 - Evening peak
            1.4,   # 21:00 - Declining
            0.9,   # 22:00
            0.5,   # 23:00 - Night setback
        ]

        # Normalize so average = 1.0
        avg_factor = np.mean(demand_factors)
        demand_factors = [f / avg_factor for f in demand_factors]

        return pd.DataFrame({
            'hour': hours,
            'demand_factor': demand_factors
        })

    def generate_daily_profile_template(self) -> pd.DataFrame:
        """
        Generate daily demand profile for a full year.

        Profile based on UK degree-day heating model:
        - Peak heating: December-February
        - Shoulder: March-April, October-November
        - Summer: May-September (minimal heating)

        Returns:
            DataFrame with day_of_year and demand_factor columns
        """
        days = list(range(1, 366))

        # Monthly heating demand factors (relative to peak month = 1.0)
        monthly_factors = {
            1: 1.0,    # January - peak
            2: 0.95,   # February
            3: 0.75,   # March
            4: 0.45,   # April
            5: 0.15,   # May
            6: 0.05,   # June
            7: 0.02,   # July
            8: 0.02,   # August
            9: 0.10,   # September
            10: 0.40,  # October
            11: 0.70,  # November
            12: 0.95,  # December
        }

        demand_factors = []
        for day in days:
            # Approximate month from day
            if day <= 31:
                month = 1
            elif day <= 59:
                month = 2
            elif day <= 90:
                month = 3
            elif day <= 120:
                month = 4
            elif day <= 151:
                month = 5
            elif day <= 181:
                month = 6
            elif day <= 212:
                month = 7
            elif day <= 243:
                month = 8
            elif day <= 273:
                month = 9
            elif day <= 304:
                month = 10
            elif day <= 334:
                month = 11
            else:
                month = 12

            demand_factors.append(monthly_factors[month])

        return pd.DataFrame({
            'day_of_year': days,
            'demand_factor': demand_factors
        })

    def calculate_pathway_load_profile(
        self,
        annual_demand_kwh: float,
        pathway_id: str,
        heat_source: str,
        n_properties: int = 1
    ) -> Dict:
        """
        Calculate load profile for a pathway.

        Args:
            annual_demand_kwh: Total annual demand for the pathway (kWh)
            pathway_id: Pathway identifier
            heat_source: Heat source type ('gas', 'hp', 'hn', 'hp+hn')
            n_properties: Number of properties (for street-level aggregation)

        Returns:
            Dictionary with profile data and metrics
        """
        hourly_template = self.generate_hourly_profile_template()

        # Convert annual demand to peak day demand
        # Assume peak day is ~1.5% of annual heating demand
        peak_day_kwh = annual_demand_kwh * 0.015

        # Calculate hourly kW for peak day
        hourly_kwh = peak_day_kwh * hourly_template['demand_factor'].values / 24
        hourly_kw = hourly_kwh  # kWh per hour = kW average

        # For heat pumps, convert to electrical demand
        if heat_source == 'hp':
            hourly_kw = hourly_kw / self.hp_scop

        # Calculate metrics
        peak_kw_per_home = np.max(hourly_kw) / n_properties
        average_kw_per_home = np.mean(hourly_kw) / n_properties
        peak_to_average = peak_kw_per_home / average_kw_per_home if average_kw_per_home > 0 else np.inf

        # Street-level totals
        street_peak_kw = np.max(hourly_kw)
        street_average_kw = np.mean(hourly_kw)

        # Apply diversity factor for street-level peak (multiple homes don't all peak at same time)
        # Typical diversity factor: 0.6-0.8 for 10+ homes
        diversity_factor = 0.7 if n_properties >= 10 else 0.85 if n_properties >= 5 else 1.0
        diversified_street_peak = street_peak_kw * diversity_factor

        return {
            'pathway_id': pathway_id,
            'heat_source': heat_source,
            'n_properties': n_properties,
            'annual_demand_kwh': annual_demand_kwh,

            # Per-home metrics
            'peak_kw_per_home': peak_kw_per_home,
            'average_kw_per_home': average_kw_per_home,
            'peak_to_average_ratio': peak_to_average,

            # Street-level metrics
            'street_peak_kw': street_peak_kw,
            'street_peak_kw_diversified': diversified_street_peak,
            'street_average_kw': street_average_kw,
            'diversity_factor': diversity_factor,

            # Profile data
            'hourly_profile': hourly_kw.tolist(),
        }

    def generate_pathway_profiles(
        self,
        pathway_results_df: pd.DataFrame,
        street_size: int = 20
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Generate load profiles for all pathways from pathway results.

        Args:
            pathway_results_df: Results from PathwayModeler
            street_size: Number of homes per street for aggregation

        Returns:
            Tuple of (timeseries_df, summary_df)
        """
        logger.info("Generating load profiles for pathways...")

        summary_rows = []
        timeseries_rows = []

        for pathway_id in pathway_results_df['pathway_id'].unique():
            pathway_data = pathway_results_df[
                pathway_results_df['pathway_id'] == pathway_id
            ]

            # Get total annual demand for all properties
            total_annual_demand = pathway_data['annual_demand_kwh'].sum()
            n_properties = len(pathway_data)

            # Determine heat source from pathway ID
            if 'hp_plus_hn' in pathway_id or 'hp+hn' in pathway_id:
                heat_source = 'hp+hn'
            elif 'hp' in pathway_id:
                heat_source = 'hp'
            elif 'hn' in pathway_id:
                heat_source = 'hn'
            else:
                heat_source = 'gas'

            # Calculate profile
            profile = self.calculate_pathway_load_profile(
                annual_demand_kwh=total_annual_demand,
                pathway_id=pathway_id,
                heat_source=heat_source,
                n_properties=n_properties
            )

            # Summary row
            summary_rows.append({
                'pathway_id': pathway_id,
                'heat_source': heat_source,
                'n_properties': n_properties,
                'annual_demand_total_kwh': total_annual_demand,
                'annual_demand_per_home_kwh': total_annual_demand / n_properties,
                'peak_kw_per_home': profile['peak_kw_per_home'],
                'average_kw_per_home': profile['average_kw_per_home'],
                'peak_to_average_ratio': profile['peak_to_average_ratio'],
                'street_peak_kw': profile['street_peak_kw'] * (street_size / n_properties),
                'street_peak_kw_diversified': profile['street_peak_kw_diversified'] * (street_size / n_properties),
            })

            # Timeseries rows
            for hour, kw in enumerate(profile['hourly_profile']):
                kw_per_home = kw / n_properties
                kw_street = kw_per_home * street_size
                timeseries_rows.append({
                    'pathway_id': pathway_id,
                    'timestep': hour,
                    'hour': hour,
                    'kw_per_home': kw_per_home,
                    'kw_street_total': kw_street,
                })

        summary_df = pd.DataFrame(summary_rows)
        timeseries_df = pd.DataFrame(timeseries_rows)

        return timeseries_df, summary_df

    def export_profiles(
        self,
        timeseries_df: pd.DataFrame,
        summary_df: pd.DataFrame
    ) -> Tuple[Path, Path]:
        """Export load profile outputs."""
        timeseries_path = self.output_dir / "pathway_load_profile_timeseries.csv"
        timeseries_df.to_csv(timeseries_path, index=False)
        logger.info(f"Saved timeseries to {timeseries_path}")

        summary_path = self.output_dir / "pathway_load_profile_summary.csv"
        summary_df.to_csv(summary_path, index=False)
        logger.info(f"Saved summary to {summary_path}")

        return timeseries_path, summary_path

    def run_analysis(
        self,
        pathway_results_df: pd.DataFrame,
        street_size: int = 20
    ) -> Dict:
        """
        Run complete load profile analysis.

        Args:
            pathway_results_df: Results from PathwayModeler
            street_size: Number of homes per street

        Returns:
            Dictionary with timeseries and summary DataFrames
        """
        logger.info("Running load profile analysis...")

        timeseries_df, summary_df = self.generate_pathway_profiles(
            pathway_results_df, street_size
        )

        self.export_profiles(timeseries_df, summary_df)

        logger.info("Load profile analysis complete!")

        return {
            'timeseries': timeseries_df,
            'summary': summary_df
        }


def main():
    """Main execution function."""
    logger.info("Starting load profile analysis...")

    # Load pathway results
    pathway_results_file = DATA_OUTPUTS_DIR / "pathway_results_by_property.parquet"

    if not pathway_results_file.exists():
        logger.error(f"Pathway results not found: {pathway_results_file}")
        logger.info("Please run pathway_model.py first")
        return

    logger.info(f"Loading pathway results from: {pathway_results_file}")
    pathway_results = pd.read_parquet(pathway_results_file)

    # Run analysis
    generator = LoadProfileGenerator()
    results = generator.run_analysis(pathway_results)

    # Log summary
    logger.info("\nLoad Profile Summary:")
    if 'summary' in results:
        for _, row in results['summary'].iterrows():
            logger.info(
                f"  {row['pathway_id']}: "
                f"{row['peak_kw_per_home']:.2f} kW peak, "
                f"{row['average_kw_per_home']:.2f} kW avg, "
                f"ratio {row['peak_to_average_ratio']:.2f}"
            )

    logger.info("Load profile analysis complete!")


if __name__ == "__main__":
    main()
