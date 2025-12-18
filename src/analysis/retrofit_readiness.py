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
from src.modeling.costing import CostCalculator
from src.analysis.methodological_adjustments import MethodologicalAdjustments


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
        self.cost_rules = self.config.get('cost_rules', {})
        self.cost_calculator = CostCalculator(self.config.get('costs', {}), self.cost_rules)
        self.adjuster = MethodologicalAdjustments()
        logger.info("Initialized Retrofit Readiness Analyzer")
        logger.info(self.cost_calculator.summary_notes() or "Costing rules configured.")

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

        # Estimate flow temperature and COP to inform readiness and sizing
        df_readiness = self.adjuster.estimate_flow_temperature(df_readiness)
        df_readiness = self.adjuster.attach_cop_estimates(df_readiness)

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
        """
        Identify properties needing loft insulation upgrade.

        Uses tiered confidence approach:
        - High confidence: Explicit thickness or 'no insulation'
        - Medium confidence: Efficiency rating only
        - Low confidence: Unknown (conservative - assume needs work)

        Returns True for properties that definitely or likely need top-up.
        """
        import re

        # EPC API provides ROOF_DESCRIPTION and ROOF_ENERGY_EFF
        needs_loft = pd.Series(False, index=df.index)
        confidence = pd.Series('unknown', index=df.index)

        # Check ROOF_DESCRIPTION for explicit thickness
        if 'ROOF_DESCRIPTION' in df.columns:
            roof_desc = df['ROOF_DESCRIPTION'].fillna('').str.lower()

            # No insulation - definitely needs work (high confidence)
            no_insulation = roof_desc.str.contains('no insulation|0 mm|0mm|uninsulated', na=False)
            needs_loft |= no_insulation
            confidence[no_insulation] = 'high'

            # Extract thickness where present
            def get_thickness(desc):
                match = re.search(r'(\d+)\s*mm', str(desc).lower())
                return int(match.group(1)) if match else None

            thicknesses = roof_desc.apply(get_thickness)

            # Low thickness (<200mm) - needs top-up (high confidence)
            low_thickness = thicknesses.notna() & (thicknesses < 200)
            needs_loft |= low_thickness
            confidence[low_thickness] = 'high'

            # Good thickness (200-269mm) - optional top-up (high confidence, not critical)
            good_thickness = thicknesses.notna() & (thicknesses >= 200) & (thicknesses < 270)
            confidence[good_thickness] = 'high'

            # Full thickness (270mm+) - no work needed (high confidence)
            full_thickness = thicknesses.notna() & (thicknesses >= 270)
            confidence[full_thickness] = 'high'

        # Check ROOF_ENERGY_EFF for remaining unknowns (medium confidence)
        if 'ROOF_ENERGY_EFF' in df.columns:
            unknown_mask = confidence == 'unknown'

            very_poor = df['ROOF_ENERGY_EFF'].isin(['Very Poor', 'very poor'])
            poor = df['ROOF_ENERGY_EFF'].isin(['Poor', 'poor'])
            average = df['ROOF_ENERGY_EFF'].isin(['Average', 'average'])
            good = df['ROOF_ENERGY_EFF'].isin(['Good', 'good', 'Very Good', 'very good'])

            # Very poor/poor rating - likely needs work (medium confidence)
            needs_loft |= (unknown_mask & (very_poor | poor))
            confidence[unknown_mask & (very_poor | poor | average | good)] = 'medium'

        # For remaining unknowns, use conservative assumption (low confidence)
        still_unknown = confidence == 'unknown'
        needs_loft |= still_unknown  # Conservative: assume needs work if unknown
        confidence[still_unknown] = 'low'

        # Store confidence for reporting
        if 'loft_topup_confidence' not in df.columns:
            df['loft_topup_confidence'] = confidence

        # Log summary
        total = len(df)
        needs_count = needs_loft.sum()
        logger.info(f"Loft insulation needs: {needs_count:,} ({needs_count/total*100:.1f}%)")

        return needs_loft

    def _needs_wall_insulation(self, df: pd.DataFrame) -> pd.Series:
        """
        Identify properties needing wall insulation.

        Returns True if:
        1. wall_insulated is False/NaN (from data_validator), OR
        2. WALLS_DESCRIPTION contains 'no insulation'/'uninsulated', OR
        3. WALLS_ENERGY_EFF is 'Poor' or 'Very Poor'

        This function checks multiple indicators to avoid false negatives.
        """
        needs_wall = pd.Series(False, index=df.index)

        # Primary check: wall_insulated boolean field (created by data_validator.py)
        if 'wall_insulated' in df.columns:
            # Need insulation if walls are uninsulated (False) or unknown (NaN)
            # Convert boolean to proper mask, handling NaN values
            wall_insulated = df['wall_insulated'].fillna(False)
            needs_wall = ~wall_insulated

            logger.debug(f"Wall insulation check from wall_insulated: {needs_wall.sum():,} need insulation")

        # Secondary check: WALLS_DESCRIPTION text
        if 'WALLS_DESCRIPTION' in df.columns:
            walls_desc = df['WALLS_DESCRIPTION'].fillna('').str.lower()

            # Check for explicit "no insulation" or similar
            no_insulation_mask = (
                walls_desc.str.contains('no insulation', na=False) |
                walls_desc.str.contains('uninsulated', na=False) |
                (walls_desc.str.contains('solid', na=False) & ~walls_desc.str.contains('insulation|insulated', na=False))
            )

            # Combine with primary check (OR logic - either indicates need)
            needs_wall = needs_wall | no_insulation_mask

            logger.debug(f"Wall insulation check from WALLS_DESCRIPTION: {no_insulation_mask.sum():,} need insulation")

        # Tertiary check: WALLS_ENERGY_EFF efficiency rating
        if 'WALLS_ENERGY_EFF' in df.columns:
            poor_walls = df['WALLS_ENERGY_EFF'].isin(['Very Poor', 'very poor', 'Poor', 'poor'])
            needs_wall = needs_wall | poor_walls

            logger.debug(f"Wall insulation check from WALLS_ENERGY_EFF: {poor_walls.sum():,} have poor efficiency")

        # Log summary
        total_needs = needs_wall.sum()
        total_properties = len(df)
        pct_needs = (total_needs / total_properties * 100) if total_properties > 0 else 0
        logger.info(f"Wall insulation needs: {total_needs:,} properties ({pct_needs:.1f}%)")

        return needs_wall

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
        Classify properties into heat pump readiness tiers based on fabric condition
        and estimated flow temperature requirement.

        Tiers:
        1 - Ready: Good insulation, likely adequate emitters (5-15% expected)
        2 - Minor work: One deficiency (e.g., loft top-up needed) (20-30% expected)
        3 - Moderate work: Two deficiencies (e.g., loft + glazing) (30-40% expected)
        4 - Significant work: Poor fabric, likely needs emitter upgrades (20-30% expected)
        5 - Major intervention: Very poor fabric, definitely needs emitters (5-15% expected)

        Based on multi-factor assessment rather than just heat demand thresholds.
        """
        tier = pd.Series(3, index=df.index)  # Default to middle tier

        # Calculate deficiency score for each property
        deficiency_scores = pd.Series(0.0, index=df.index)

        # Wall insulation check (major factor - weighted 2x)
        if 'wall_insulated' in df.columns:
            # Uninsulated walls = major deficiency
            uninsulated_walls = ~df['wall_insulated']
            deficiency_scores += uninsulated_walls.astype(float) * 2.0

        # Also check wall type for solid walls (harder to insulate)
        if 'wall_type' in df.columns:
            solid_walls = df['wall_type'].str.contains('Solid|solid', na=False)
            # Uninsulated solid walls get extra penalty
            if 'wall_insulated' in df.columns:
                uninsulated_solid = solid_walls & (~df['wall_insulated'])
                deficiency_scores += uninsulated_solid.astype(float) * 0.5

        # Loft insulation check
        if 'ROOF_ENERGY_EFF' in df.columns:
            poor_roof = df['ROOF_ENERGY_EFF'].isin(['Very Poor', 'very poor', 'Poor', 'poor'])
            deficiency_scores += poor_roof.astype(float) * 1.0
        elif 'ROOF_DESCRIPTION' in df.columns:
            no_loft = df['ROOF_DESCRIPTION'].str.contains(
                'no insulation|0 mm|uninsulated', case=False, na=False
            )
            deficiency_scores += no_loft.astype(float) * 1.0

            # Partial/insufficient loft insulation
            low_loft = df['ROOF_DESCRIPTION'].str.contains(
                '50mm|75mm|100mm', case=False, na=False
            )
            deficiency_scores += low_loft.astype(float) * 0.5

        # Glazing check
        if 'glazing_type' in df.columns:
            single_glazed = df['glazing_type'].str.contains('Single|single', na=False)
            deficiency_scores += single_glazed.astype(float) * 1.0
        elif 'WINDOWS_DESCRIPTION' in df.columns:
            single_glazed = df['WINDOWS_DESCRIPTION'].str.contains('single', case=False, na=False)
            deficiency_scores += single_glazed.astype(float) * 1.0

        # Floor insulation check
        if 'FLOOR_ENERGY_EFF' in df.columns:
            poor_floor = df['FLOOR_ENERGY_EFF'].isin(['Very Poor', 'very poor', 'Poor', 'poor'])
            deficiency_scores += poor_floor.astype(float) * 0.5

        # SAP score as proxy for overall fabric performance
        if 'CURRENT_ENERGY_EFFICIENCY' in df.columns:
            sap = df['CURRENT_ENERGY_EFFICIENCY'].fillna(50)
            very_poor_sap = sap < 40
            poor_sap = (sap >= 40) & (sap < 55)
            deficiency_scores += very_poor_sap.astype(float) * 1.0
            deficiency_scores += poor_sap.astype(float) * 0.5

        # Classify into tiers based on deficiency score
        # Score thresholds designed to give expected distribution
        tier = pd.Series(3, index=df.index)  # Default

        tier[deficiency_scores <= 0.5] = 1   # Ready (score 0-0.5)
        tier[(deficiency_scores > 0.5) & (deficiency_scores <= 1.5)] = 2   # Minor work
        tier[(deficiency_scores > 1.5) & (deficiency_scores <= 2.5)] = 3   # Moderate work
        tier[(deficiency_scores > 2.5) & (deficiency_scores <= 4.0)] = 4   # Significant work
        tier[deficiency_scores > 4.0] = 5   # Major intervention

        # Store deficiency score for debugging/analysis
        df['deficiency_score'] = deficiency_scores

        # Log tier distribution for validation
        tier_counts = tier.value_counts().sort_index()
        tier_pcts = (tier.value_counts(normalize=True).sort_index() * 100)
        logger.info("Retrofit readiness tier distribution:")
        for t in range(1, 6):
            count = tier_counts.get(t, 0)
            pct = tier_pcts.get(t, 0)
            logger.info(f"  Tier {t}: {count:,} properties ({pct:.1f}%)")

        return tier

    def _calculate_fabric_costs(self, df: pd.DataFrame) -> pd.Series:
        """Calculate cost of fabric improvements needed before heat pump."""
        costs = pd.Series(0.0, index=df.index, dtype=float)

        loft_mask = df['needs_loft_topup']
        cavity_mask = df['wall_insulation_type'] == 'cavity_wall'
        solid_mask = df['wall_insulation_type'] == 'solid_wall_ewi'
        glazing_mask = df['needs_glazing_upgrade']

        costs += self._cost_series(df, 'loft_insulation_topup', loft_mask)
        costs += self._cost_series(df, 'wall_insulation_cavity', cavity_mask)
        costs += self._cost_series(df, 'solid_wall_insulation_ewi', solid_mask)
        costs += self._cost_series(df, 'double_glazing', glazing_mask)

        return costs

    def _calculate_total_retrofit_cost(self, df: pd.DataFrame) -> pd.Series:
        """Calculate total cost including fabric + heat pump + ancillaries."""
        total_cost = df['fabric_prerequisite_cost'].astype(float).copy()

        total_cost += self._cost_series(df, 'emitter_upgrades', df['needs_radiator_upsizing'])
        total_cost += self._cost_series(df, 'hot_water_cylinder')

        hp_cost = df.apply(
            lambda row: self.cost_calculator.measure_cost(
                'hybrid_heat_pump' if row.get('hp_readiness_tier') == 4 else 'ashp_installation',
                row
            )[0],
            axis=1
        )
        total_cost += hp_cost

        return total_cost

    def _cost_series(self, df: pd.DataFrame, measure_name: str, mask: Optional[pd.Series] = None) -> pd.Series:
        """Vectorised helper to apply costing rules with an optional mask."""
        mask_to_use = mask if mask is not None else pd.Series(True, index=df.index)
        return df.apply(
            lambda row: self.cost_calculator.measure_cost(measure_name, row)[0]
            if mask_to_use.loc[row.name]
            else 0.0,
            axis=1
        )

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
            'mean_hp_cop_central': df_readiness['hp_cop_central'].mean() if 'hp_cop_central' in df_readiness.columns else None,
            'mean_hp_cop_low': df_readiness['hp_cop_low'].mean() if 'hp_cop_low' in df_readiness.columns else None,
            'mean_hp_cop_high': df_readiness['hp_cop_high'].mean() if 'hp_cop_high' in df_readiness.columns else None,

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

        with open(summary_path, 'w', encoding='utf-8') as f:
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
