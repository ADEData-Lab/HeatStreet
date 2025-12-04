"""
Retrofit Readiness Analysis Module

Assesses heat pump readiness for properties and identifies barriers/pre-requisites.
Analyzes fabric quality, heat demand, and calculates costs to achieve "heat pump ready" status.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Tuple, Optional
from loguru import logger

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import load_config, DATA_OUTPUTS_DIR


class RetrofitReadinessAnalyzer:
    """
    Analyzes property readiness for heat pump installation.

    Classifies properties into readiness tiers and calculates pre-requisite costs.
    """

    # Heat pump readiness thresholds
    HEAT_DEMAND_THRESHOLDS = {
        'ready': 100,           # kWh/m²/year - can install HP now
        'minor_work': 150,      # kWh/m²/year - needs minor fabric improvements
        'major_work': 200,      # kWh/m²/year - needs major fabric improvements
        'challenging': 250,     # kWh/m²/year - very challenging, may need hybrid
        # > 250 = not suitable for standard heat pump
    }

    # Intervention costs (£)
    INTERVENTION_COSTS = {
        'loft_insulation_topup': 1200,      # 100mm → 270mm
        'cavity_wall_insulation': 3500,     # CWI for cavity walls
        'solid_wall_insulation_ewi': 10000, # External wall insulation (preferred)
        'solid_wall_insulation_iwi': 14000, # Internal wall insulation (conservation areas)
        'double_glazing': 6000,             # Single → double glazing
        'triple_glazing': 9000,             # Double → triple (very cold climates)
        'radiator_upsizing': 2500,          # Oversized radiators for lower flow temps
        'hot_water_cylinder': 1200,         # 200L cylinder + installation
        'electrical_upgrade': 1500,         # 60A → 100A supply
        'heat_pump_installation': 12000,    # Standard ASHP + installation
        'hybrid_heat_pump': 8000,           # Hybrid HP (keeps gas for peaks)
    }

    # Heat loss reduction from interventions (%)
    HEAT_LOSS_REDUCTION = {
        'loft_insulation_topup': 0.15,      # 15% reduction
        'cavity_wall_insulation': 0.35,     # 35% reduction
        'solid_wall_insulation': 0.35,      # 35% reduction
        'double_glazing': 0.10,             # 10% reduction
        'floor_insulation': 0.05,           # 5% reduction
    }

    def __init__(self):
        """Initialize retrofit readiness analyzer."""
        self.config = load_config()
        logger.info("Initialized Retrofit Readiness Analyzer")

    def assess_heat_pump_readiness(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Assess heat pump readiness for all properties.

        Args:
            df: DataFrame with EPC data

        Returns:
            DataFrame with readiness assessment added
        """
        logger.info("Assessing heat pump readiness...")

        df_readiness = df.copy()

        # Calculate current heat demand (kWh/m²/year)
        df_readiness['heat_demand_kwh_m2'] = self._calculate_heat_demand(df_readiness)

        # Identify required interventions
        df_readiness['needs_loft_topup'] = self._needs_loft_insulation(df_readiness)
        df_readiness['needs_wall_insulation'] = self._needs_wall_insulation(df_readiness)
        df_readiness['wall_insulation_type'] = self._wall_insulation_type(df_readiness)
        df_readiness['needs_glazing_upgrade'] = self._needs_glazing_upgrade(df_readiness)
        df_readiness['needs_radiator_upsizing'] = self._needs_radiator_upsizing(df_readiness)

        # Calculate heat demand after fabric improvements
        df_readiness['heat_demand_after_fabric'] = self._calculate_post_fabric_heat_demand(df_readiness)

        # Classify into readiness tiers
        df_readiness['hp_readiness_tier'] = self._classify_readiness_tier(df_readiness)
        df_readiness['hp_readiness_label'] = df_readiness['hp_readiness_tier'].map({
            1: 'Tier 1: Ready Now',
            2: 'Tier 2: Minor Work Required',
            3: 'Tier 3: Major Work Required',
            4: 'Tier 4: Very Challenging',
            5: 'Tier 5: Not Suitable for Standard HP'
        })

        # Calculate costs
        df_readiness['fabric_prerequisite_cost'] = self._calculate_fabric_costs(df_readiness)
        df_readiness['total_retrofit_cost'] = self._calculate_total_retrofit_cost(df_readiness)

        # Estimate heat pump size needed
        df_readiness['estimated_hp_size_kw'] = self._estimate_heat_pump_size(df_readiness)

        logger.info(f"✓ Assessed {len(df_readiness):,} properties for heat pump readiness")

        return df_readiness

    def _calculate_heat_demand(self, df: pd.DataFrame) -> pd.Series:
        """Calculate current heat demand in kWh/m²/year."""
        # ENERGY_CONSUMPTION_CURRENT from EPC API is already in kWh/m²/year
        # See: https://epc.opendatacommunities.org/docs/guidance (glossary)
        # No need to divide by floor area - just use directly

        heat_demand = df['ENERGY_CONSUMPTION_CURRENT'].copy()

        return heat_demand

    def _needs_loft_insulation(self, df: pd.DataFrame) -> pd.Series:
        """Identify properties needing loft insulation upgrade."""
        # EPC API provides ROOF_DESCRIPTION and ROOF_ENERGY_EFF, not loft_insulation_thickness
        needs_loft = pd.Series(False, index=df.index)  # Default to False (conservative)

        # Check ROOF_ENERGY_EFF first (most reliable indicator)
        if 'ROOF_ENERGY_EFF' in df.columns:
            # Need upgrade if roof efficiency is poor or very poor
            needs_loft = df['ROOF_ENERGY_EFF'].isin(['Poor', 'poor', 'Very Poor', 'very poor'])

        # If ROOF_DESCRIPTION available, check for insulation mentions
        elif 'ROOF_DESCRIPTION' in df.columns:
            # Flag properties with no insulation mentioned
            no_insulation_mask = (
                df['ROOF_DESCRIPTION'].str.contains('no insulation|uninsulated', case=False, na=False) |
                df['ROOF_DESCRIPTION'].isna()
            )
            # Flag properties with insufficient insulation
            low_insulation_mask = df['ROOF_DESCRIPTION'].str.contains(
                '50mm|75mm|100mm|less than', case=False, na=False
            )
            needs_loft = no_insulation_mask | low_insulation_mask

        # Fallback: check legacy loft_insulation_thickness field (if exists)
        elif 'loft_insulation_thickness' in df.columns:
            needs_loft = (
                (df['loft_insulation_thickness'].isna()) |
                (df['loft_insulation_thickness'] == 'None') |
                (df['loft_insulation_thickness'] == 'unknown') |
                (df['loft_insulation_thickness'].str.contains('100mm|less', case=False, na=False))
            )

        return needs_loft

    def _needs_wall_insulation(self, df: pd.DataFrame) -> pd.Series:
        """Identify properties needing wall insulation."""
        # Check for wall_insulated boolean field (created by data_validator.py)
        if 'wall_insulated' in df.columns:
            # Need insulation if walls are uninsulated (False or NaN)
            needs_wall = (~df['wall_insulated']) | (df['wall_insulated'].isna())
            return needs_wall

        # Fallback: check for legacy string field
        if 'wall_insulation' in df.columns:
            needs_wall = (
                (df['wall_insulation'] == 'No') |
                (df['wall_insulation'] == 'None') |
                (df['wall_insulation'].isna())
            )
            return needs_wall

        # No wall insulation data available
        return pd.Series(False, index=df.index)

    def _wall_insulation_type(self, df: pd.DataFrame) -> pd.Series:
        """Determine which type of wall insulation is needed."""
        insulation_type = pd.Series('none', index=df.index)

        if 'wall_type' not in df.columns:
            return insulation_type

        # Solid walls need EWI or IWI
        solid_walls = df['wall_type'].str.contains('solid', case=False, na=False)
        needs_insulation = self._needs_wall_insulation(df)

        insulation_type[solid_walls & needs_insulation] = 'solid_wall_ewi'

        # Cavity walls need CWI
        cavity_walls = df['wall_type'].str.contains('cavity', case=False, na=False)
        insulation_type[cavity_walls & needs_insulation] = 'cavity_wall'

        return insulation_type

    def _needs_glazing_upgrade(self, df: pd.DataFrame) -> pd.Series:
        """Identify properties needing glazing upgrade."""
        if 'glazing_type' not in df.columns:
            return pd.Series(False, index=df.index)

        # Need upgrade if single glazed
        needs_glazing = df['glazing_type'].str.contains('single', case=False, na=False)

        return needs_glazing

    def _needs_radiator_upsizing(self, df: pd.DataFrame) -> pd.Series:
        """Estimate properties needing radiator upsizing for heat pumps."""
        # Most properties with high heat demand will need radiator upsizing
        # Heat pumps run at 45-55°C vs 70-80°C for gas boilers
        # Properties with heat demand >100 kWh/m² likely need larger radiators

        heat_demand = self._calculate_heat_demand(df)
        needs_radiators = heat_demand > 100

        return needs_radiators

    def _calculate_post_fabric_heat_demand(self, df: pd.DataFrame) -> pd.Series:
        """Calculate heat demand after fabric improvements."""
        current_demand = self._calculate_heat_demand(df)
        post_fabric_demand = current_demand.copy()

        # Apply reductions for each intervention
        if df['needs_loft_topup'].any():
            reduction = self.HEAT_LOSS_REDUCTION['loft_insulation_topup']
            post_fabric_demand = post_fabric_demand * (1 - reduction * df['needs_loft_topup'])

        if df['needs_wall_insulation'].any():
            # Use appropriate wall insulation reduction
            wall_reduction = self.HEAT_LOSS_REDUCTION['solid_wall_insulation']
            cavity_reduction = self.HEAT_LOSS_REDUCTION['cavity_wall_insulation']

            solid_mask = df['wall_insulation_type'].str.contains('solid', na=False)
            cavity_mask = df['wall_insulation_type'].str.contains('cavity', na=False)

            post_fabric_demand = post_fabric_demand * (1 - wall_reduction * solid_mask)
            post_fabric_demand = post_fabric_demand * (1 - cavity_reduction * cavity_mask)

        if df['needs_glazing_upgrade'].any():
            reduction = self.HEAT_LOSS_REDUCTION['double_glazing']
            post_fabric_demand = post_fabric_demand * (1 - reduction * df['needs_glazing_upgrade'])

        return post_fabric_demand

    def _classify_readiness_tier(self, df: pd.DataFrame) -> pd.Series:
        """
        Classify properties into heat pump readiness tiers.

        Tier 1: Ready now (<100 kWh/m², minimal fabric work)
        Tier 2: Minor work (100-150 kWh/m², loft/glazing)
        Tier 3: Major work (150-200 kWh/m², solid wall insulation)
        Tier 4: Very challenging (200-250 kWh/m²)
        Tier 5: Not suitable (>250 kWh/m²)
        """
        tier = pd.Series(5, index=df.index)  # Default to tier 5

        current_demand = df['heat_demand_kwh_m2']
        post_fabric_demand = df['heat_demand_after_fabric']

        # Tier 1: Ready now
        # Low current demand AND minimal work needed
        tier1_criteria = (
            (current_demand < self.HEAT_DEMAND_THRESHOLDS['ready']) &
            (~df['needs_wall_insulation'])
        )
        tier[tier1_criteria] = 1

        # Tier 2: Minor work
        # Current demand moderate OR post-fabric demand low
        tier2_criteria = (
            (tier != 1) &
            (
                (current_demand < self.HEAT_DEMAND_THRESHOLDS['minor_work']) |
                (post_fabric_demand < self.HEAT_DEMAND_THRESHOLDS['ready'])
            ) &
            (~df['wall_insulation_type'].str.contains('solid', na=False))  # No solid wall
        )
        tier[tier2_criteria] = 2

        # Tier 3: Major work
        # Needs solid wall insulation but achievable
        tier3_criteria = (
            (tier > 2) &
            (
                (current_demand < self.HEAT_DEMAND_THRESHOLDS['major_work']) |
                (post_fabric_demand < self.HEAT_DEMAND_THRESHOLDS['minor_work'])
            )
        )
        tier[tier3_criteria] = 3

        # Tier 4: Very challenging
        # High demand even after fabric work
        tier4_criteria = (
            (tier > 3) &
            (
                (current_demand < self.HEAT_DEMAND_THRESHOLDS['challenging']) |
                (post_fabric_demand < self.HEAT_DEMAND_THRESHOLDS['major_work'])
            )
        )
        tier[tier4_criteria] = 4

        # Tier 5: Everything else (>250 kWh/m² or still high after fabric)

        return tier

    def _calculate_fabric_costs(self, df: pd.DataFrame) -> pd.Series:
        """Calculate cost of fabric improvements needed before heat pump."""
        costs = pd.Series(0, index=df.index)

        # Loft insulation
        costs += df['needs_loft_topup'] * self.INTERVENTION_COSTS['loft_insulation_topup']

        # Wall insulation
        solid_wall_cost = self.INTERVENTION_COSTS['solid_wall_insulation_ewi']
        cavity_wall_cost = self.INTERVENTION_COSTS['cavity_wall_insulation']

        costs += (
            (df['wall_insulation_type'] == 'solid_wall_ewi') * solid_wall_cost +
            (df['wall_insulation_type'] == 'cavity_wall') * cavity_wall_cost
        )

        # Glazing
        costs += df['needs_glazing_upgrade'] * self.INTERVENTION_COSTS['double_glazing']

        return costs

    def _calculate_total_retrofit_cost(self, df: pd.DataFrame) -> pd.Series:
        """Calculate total cost including fabric + heat pump + ancillaries."""
        total_cost = df['fabric_prerequisite_cost'].copy()

        # Add radiator upsizing
        total_cost += df['needs_radiator_upsizing'] * self.INTERVENTION_COSTS['radiator_upsizing']

        # Add hot water cylinder (assume all combi boiler replacements need this)
        total_cost += self.INTERVENTION_COSTS['hot_water_cylinder']

        # Add heat pump
        # Use hybrid for Tier 4, standard for others
        hp_cost = np.where(
            df['hp_readiness_tier'] == 4,
            self.INTERVENTION_COSTS['hybrid_heat_pump'],
            self.INTERVENTION_COSTS['heat_pump_installation']
        )
        total_cost += hp_cost

        return total_cost

    def _estimate_heat_pump_size(self, df: pd.DataFrame) -> pd.Series:
        """Estimate heat pump size needed (kW)."""
        # Rule of thumb: 0.05 kW per m² for well-insulated homes
        # 0.08 kW per m² for poorly insulated

        if 'TOTAL_FLOOR_AREA' not in df.columns:
            return pd.Series(8.0, index=df.index)  # Default 8kW

        floor_area = df['TOTAL_FLOOR_AREA']

        # Use post-fabric heat demand to estimate sizing factor
        heat_demand = df['heat_demand_after_fabric']

        # Lower demand = smaller sizing factor
        sizing_factor = np.where(heat_demand < 100, 0.05, 0.08)
        sizing_factor = np.where(heat_demand > 150, 0.10, sizing_factor)

        hp_size = floor_area * sizing_factor

        # Clip to reasonable range (5-16 kW for domestic)
        hp_size = hp_size.clip(5, 16)

        return hp_size

    def generate_readiness_summary(self, df_readiness: pd.DataFrame) -> Dict:
        """
        Generate summary statistics for heat pump readiness.

        Args:
            df_readiness: DataFrame with readiness assessment

        Returns:
            Dictionary with summary statistics
        """
        logger.info("Generating heat pump readiness summary...")

        total_properties = len(df_readiness)

        summary = {
            'total_properties': total_properties,

            # Tier distribution
            'tier_distribution': df_readiness['hp_readiness_tier'].value_counts().sort_index().to_dict(),
            'tier_percentages': (df_readiness['hp_readiness_tier'].value_counts(normalize=True).sort_index() * 100).to_dict(),

            # Intervention needs
            'needs_loft_insulation': df_readiness['needs_loft_topup'].sum(),
            'needs_wall_insulation': df_readiness['needs_wall_insulation'].sum(),
            'needs_solid_wall_insulation': (df_readiness['wall_insulation_type'] == 'solid_wall_ewi').sum(),
            'needs_cavity_wall_insulation': (df_readiness['wall_insulation_type'] == 'cavity_wall').sum(),
            'needs_glazing_upgrade': df_readiness['needs_glazing_upgrade'].sum(),
            'needs_radiator_upsizing': df_readiness['needs_radiator_upsizing'].sum(),

            # Cost statistics
            'mean_fabric_cost': df_readiness['fabric_prerequisite_cost'].mean(),
            'median_fabric_cost': df_readiness['fabric_prerequisite_cost'].median(),
            'total_fabric_cost': df_readiness['fabric_prerequisite_cost'].sum(),
            'mean_total_retrofit_cost': df_readiness['total_retrofit_cost'].mean(),
            'median_total_retrofit_cost': df_readiness['total_retrofit_cost'].median(),
            'total_retrofit_cost': df_readiness['total_retrofit_cost'].sum(),

            # Heat demand statistics
            'mean_current_heat_demand': df_readiness['heat_demand_kwh_m2'].mean(),
            'mean_post_fabric_heat_demand': df_readiness['heat_demand_after_fabric'].mean(),
            'heat_demand_reduction_percent': (
                (df_readiness['heat_demand_kwh_m2'].mean() - df_readiness['heat_demand_after_fabric'].mean()) /
                df_readiness['heat_demand_kwh_m2'].mean() * 100
            ),

            # Cost distribution by tier
            'fabric_cost_by_tier': df_readiness.groupby('hp_readiness_tier')['fabric_prerequisite_cost'].mean().to_dict(),
            'total_cost_by_tier': df_readiness.groupby('hp_readiness_tier')['total_retrofit_cost'].mean().to_dict(),
        }

        return summary

    def save_readiness_results(self, df_readiness: pd.DataFrame, summary: Dict, output_path: Optional[Path] = None):
        """Save readiness analysis results."""
        if output_path is None:
            output_path = DATA_OUTPUTS_DIR / "retrofit_readiness_analysis.csv"

        # Save full results
        df_readiness.to_csv(output_path, index=False)
        logger.info(f"✓ Saved readiness analysis to {output_path}")

        # Save summary report
        summary_path = DATA_OUTPUTS_DIR / "reports" / "retrofit_readiness_summary.txt"
        summary_path.parent.mkdir(parents=True, exist_ok=True)

        with open(summary_path, 'w') as f:
            f.write("=" * 80 + "\n")
            f.write("HEAT PUMP RETROFIT READINESS ANALYSIS\n")
            f.write("=" * 80 + "\n\n")

            f.write(f"Total Properties Analyzed: {summary['total_properties']:,}\n\n")

            f.write("READINESS TIER DISTRIBUTION:\n")
            f.write("-" * 80 + "\n")
            for tier in range(1, 6):
                count = summary['tier_distribution'].get(tier, 0)
                pct = summary['tier_percentages'].get(tier, 0)
                f.write(f"Tier {tier}: {count:,} properties ({pct:.1f}%)\n")
            f.write("\n")

            f.write("INTERVENTION REQUIREMENTS:\n")
            f.write("-" * 80 + "\n")
            f.write(f"Need loft insulation: {summary['needs_loft_insulation']:,} ({summary['needs_loft_insulation']/summary['total_properties']*100:.1f}%)\n")
            f.write(f"Need wall insulation: {summary['needs_wall_insulation']:,} ({summary['needs_wall_insulation']/summary['total_properties']*100:.1f}%)\n")
            f.write(f"  - Solid wall: {summary['needs_solid_wall_insulation']:,}\n")
            f.write(f"  - Cavity wall: {summary['needs_cavity_wall_insulation']:,}\n")
            f.write(f"Need glazing upgrade: {summary['needs_glazing_upgrade']:,} ({summary['needs_glazing_upgrade']/summary['total_properties']*100:.1f}%)\n")
            f.write(f"Need radiator upsizing: {summary['needs_radiator_upsizing']:,} ({summary['needs_radiator_upsizing']/summary['total_properties']*100:.1f}%)\n\n")

            f.write("COST ANALYSIS:\n")
            f.write("-" * 80 + "\n")
            f.write(f"Mean fabric pre-requisite cost: £{summary['mean_fabric_cost']:,.0f}\n")
            f.write(f"Median fabric pre-requisite cost: £{summary['median_fabric_cost']:,.0f}\n")
            f.write(f"Total fabric investment needed: £{summary['total_fabric_cost']/1e6:.1f}M\n\n")
            f.write(f"Mean total retrofit cost: £{summary['mean_total_retrofit_cost']:,.0f}\n")
            f.write(f"Median total retrofit cost: £{summary['median_total_retrofit_cost']:,.0f}\n")
            f.write(f"Total retrofit investment needed: £{summary['total_retrofit_cost']/1e6:.1f}M\n\n")

            f.write("HEAT DEMAND ANALYSIS:\n")
            f.write("-" * 80 + "\n")
            f.write(f"Mean current heat demand: {summary['mean_current_heat_demand']:.0f} kWh/m²/year\n")
            f.write(f"Mean post-fabric heat demand: {summary['mean_post_fabric_heat_demand']:.0f} kWh/m²/year\n")
            f.write(f"Heat demand reduction: {summary['heat_demand_reduction_percent']:.1f}%\n\n")

            f.write("FABRIC COST BY READINESS TIER:\n")
            f.write("-" * 80 + "\n")
            for tier in range(1, 6):
                cost = summary['fabric_cost_by_tier'].get(tier, 0)
                f.write(f"Tier {tier}: £{cost:,.0f} average fabric cost\n")
            f.write("\n")

            f.write("TOTAL RETROFIT COST BY READINESS TIER:\n")
            f.write("-" * 80 + "\n")
            for tier in range(1, 6):
                cost = summary['total_cost_by_tier'].get(tier, 0)
                f.write(f"Tier {tier}: £{cost:,.0f} average total cost\n")

        logger.info(f"✓ Saved summary report to {summary_path}")


def main():
    """Example usage."""
    from src.cleaning.data_validator import DataValidator

    # Load sample data
    validator = DataValidator()
    df = validator.load_data(Path("data/processed/epc_london_validated.csv"))

    # Run readiness analysis
    analyzer = RetrofitReadinessAnalyzer()
    df_readiness = analyzer.assess_heat_pump_readiness(df)
    summary = analyzer.generate_readiness_summary(df_readiness)
    analyzer.save_readiness_results(df_readiness, summary)

    # Print summary
    print("\nHeat Pump Readiness Summary:")
    print(f"Total properties: {summary['total_properties']:,}")
    print(f"\nTier distribution:")
    for tier, count in summary['tier_distribution'].items():
        pct = summary['tier_percentages'][tier]
        print(f"  Tier {tier}: {count:,} ({pct:.1f}%)")


if __name__ == "__main__":
    main()
