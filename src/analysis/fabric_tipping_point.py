"""
Fabric Tipping Point Analysis Module

Generates cumulative fabric investment curves showing diminishing returns.
Identifies the "tipping point" where marginal cost per kWh saved increases sharply.

Key outputs:
- Cumulative capex vs cumulative kWh savings
- Marginal cost per kWh saved for each additional measure
- Identification of diminishing returns threshold

Output file:
- fabric_tipping_point_curve.csv: Curve data with marginal cost analysis
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
    get_cost_assumptions,
    get_measure_savings,
    DATA_PROCESSED_DIR,
    DATA_OUTPUTS_DIR
)
from src.analysis.retrofit_packages import get_measure_catalogue, Measure


class FabricTippingPointAnalyzer:
    """
    Analyzes fabric investment curves to identify diminishing returns.

    The "tipping point" is where the marginal cost per kWh saved
    starts to increase significantly, indicating that further fabric
    investment becomes progressively less cost-effective.
    """

    def __init__(self, output_dir: Optional[Path] = None):
        """
        Initialize the tipping point analyzer.

        Args:
            output_dir: Directory for outputs. Defaults to DATA_OUTPUTS_DIR.
        """
        self.config = load_config()
        self.costs = get_cost_assumptions()
        self.savings = get_measure_savings()
        self.catalogue = get_measure_catalogue()

        self.output_dir = output_dir or DATA_OUTPUTS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Energy price for cost-effectiveness
        self.gas_price = self.config.get('energy_prices', {}).get('current', {}).get('gas', 0.0624)

        logger.info("Initialized FabricTippingPointAnalyzer")

    def generate_fabric_measure_sequence(self) -> List[str]:
        """
        Generate an ordered sequence of fabric measures from low to high cost.

        The sequence represents a logical progression of fabric improvements,
        ordered by typical cost-effectiveness (simple payback).

        Returns:
            List of measure IDs in recommended order
        """
        # Define typical fabric measures in order of cost-effectiveness
        # (Based on common retrofit guidance: cheap wins first, then more expensive)
        fabric_sequence = [
            'draught_proofing',           # Cheapest, quick win
            'loft_insulation',             # Low cost, high savings
            'cavity_wall_insulation',      # Medium cost, good savings
            'floor_insulation',            # Medium cost, moderate savings
            'double_glazing_upgrade',      # Higher cost, moderate savings
            'solid_wall_insulation_ewi',   # High cost, good savings but expensive
            'triple_glazing_upgrade',      # Highest cost, marginal additional benefit
        ]

        # Filter to only include measures that exist in catalogue
        return [m for m in fabric_sequence if m in self.catalogue]

    def calculate_tipping_point_curve(
        self,
        typical_annual_heat_demand_kwh: float = 15000,
        property_archetype: str = "typical_edwardian_terrace"
    ) -> pd.DataFrame:
        """
        Calculate the fabric tipping point curve for a representative property.

        For each step in the fabric improvement sequence, calculates:
        - Cumulative capex
        - Cumulative kWh savings
        - Marginal cost per additional kWh saved

        Args:
            typical_annual_heat_demand_kwh: Baseline annual heating demand (kWh)
            property_archetype: Description of representative property

        Returns:
            DataFrame with curve data

        Output file: fabric_tipping_point_curve.csv
        """
        logger.info(f"Calculating tipping point curve for {property_archetype}...")
        logger.info(f"  Baseline heating demand: {typical_annual_heat_demand_kwh:,.0f} kWh/year")

        sequence = self.generate_fabric_measure_sequence()
        logger.info(f"  Measure sequence: {', '.join(sequence)}")

        # Track cumulative effects
        cumulative_capex = 0.0
        cumulative_saving_kwh = 0.0
        remaining_demand_fraction = 1.0  # Start at 100% of baseline

        results = []

        # Add baseline (no intervention) as starting point
        results.append({
            'step': 0,
            'measure_id': 'baseline',
            'measure_name': 'No intervention',
            'measure_capex': 0.0,
            'cumulative_capex': 0.0,
            'cumulative_kwh_saved': 0.0,
            'remaining_demand_kwh': typical_annual_heat_demand_kwh,
            'remaining_demand_pct': 100.0,
            'marginal_kwh_saved': 0.0,
            'marginal_capex': 0.0,
            'marginal_cost_per_kwh_saved': np.nan,
            'cumulative_cost_per_kwh_saved': np.nan,
        })

        # Apply each measure sequentially
        for step, measure_id in enumerate(sequence, start=1):
            measure = self.catalogue[measure_id]

            # Measure cost
            measure_capex = measure.capex_per_home
            cumulative_capex += measure_capex

            # Savings (applied to remaining demand using diminishing returns model)
            # Each measure saves a percentage of the REMAINING demand
            measure_saving_pct = measure.annual_kwh_saving_pct
            kwh_saved_by_this_measure = typical_annual_heat_demand_kwh * remaining_demand_fraction * measure_saving_pct

            # Update remaining demand
            remaining_demand_fraction *= (1 - measure_saving_pct)
            cumulative_saving_kwh += kwh_saved_by_this_measure

            # Calculate remaining demand
            remaining_demand_kwh = typical_annual_heat_demand_kwh * remaining_demand_fraction

            # Marginal cost-effectiveness
            marginal_cost_per_kwh = (
                measure_capex / kwh_saved_by_this_measure
                if kwh_saved_by_this_measure > 0 else np.inf
            )

            # Cumulative cost-effectiveness
            cumulative_cost_per_kwh = (
                cumulative_capex / cumulative_saving_kwh
                if cumulative_saving_kwh > 0 else np.inf
            )

            results.append({
                'step': step,
                'measure_id': measure_id,
                'measure_name': measure.name,
                'measure_capex': measure_capex,
                'cumulative_capex': cumulative_capex,
                'cumulative_kwh_saved': cumulative_saving_kwh,
                'remaining_demand_kwh': remaining_demand_kwh,
                'remaining_demand_pct': remaining_demand_fraction * 100,
                'marginal_kwh_saved': kwh_saved_by_this_measure,
                'marginal_capex': measure_capex,
                'marginal_cost_per_kwh_saved': marginal_cost_per_kwh,
                'cumulative_cost_per_kwh_saved': cumulative_cost_per_kwh,
            })

            logger.info(
                f"  Step {step}: {measure.name} | "
                f"Capex: £{measure_capex:,.0f} | "
                f"Saves: {kwh_saved_by_this_measure:,.0f} kWh | "
                f"Marginal: £{marginal_cost_per_kwh:.3f}/kWh"
            )

        curve_df = pd.DataFrame(results)

        # Identify tipping point (where marginal cost starts increasing sharply)
        # Use a simple heuristic: find where marginal cost exceeds 2x the minimum
        finite_costs = curve_df[np.isfinite(curve_df['marginal_cost_per_kwh_saved'])]
        if len(finite_costs) > 0:
            min_marginal_cost = finite_costs['marginal_cost_per_kwh_saved'].min()
            tipping_threshold = min_marginal_cost * 2.0

            curve_df['is_beyond_tipping_point'] = (
                curve_df['marginal_cost_per_kwh_saved'] > tipping_threshold
            )

            tipping_point_step = curve_df[
                curve_df['is_beyond_tipping_point']
            ]['step'].min()

            if pd.notna(tipping_point_step):
                logger.info(f"\n  ⚠️ TIPPING POINT identified at Step {int(tipping_point_step)}")
                logger.info(f"     Marginal cost threshold: £{tipping_threshold:.3f}/kWh")
        else:
            curve_df['is_beyond_tipping_point'] = False

        # Save to CSV
        output_path = self.output_dir / "fabric_tipping_point_curve.csv"
        curve_df.to_csv(output_path, index=False, float_format='%.2f')
        logger.info(f"\nSaved tipping point curve to {output_path}")

        return curve_df

    def generate_summary_metrics(self, curve_df: pd.DataFrame) -> Dict:
        """
        Generate summary metrics from the tipping point curve.

        Args:
            curve_df: DataFrame from calculate_tipping_point_curve

        Returns:
            Dictionary with key metrics
        """
        # Find the most cost-effective measure
        finite_costs = curve_df[
            np.isfinite(curve_df['marginal_cost_per_kwh_saved']) &
            (curve_df['step'] > 0)
        ]

        if len(finite_costs) > 0:
            best_measure_idx = finite_costs['marginal_cost_per_kwh_saved'].idxmin()
            best_measure = curve_df.loc[best_measure_idx]

            worst_measure_idx = finite_costs['marginal_cost_per_kwh_saved'].idxmax()
            worst_measure = curve_df.loc[worst_measure_idx]
        else:
            best_measure = None
            worst_measure = None

        # Final cumulative metrics
        final_row = curve_df.iloc[-1]

        summary = {
            'total_measures': len(curve_df) - 1,  # Exclude baseline
            'total_capex': final_row['cumulative_capex'],
            'total_kwh_saved': final_row['cumulative_kwh_saved'],
            'total_saving_pct': 100 - final_row['remaining_demand_pct'],
            'avg_cost_per_kwh': final_row['cumulative_cost_per_kwh_saved'],
            'best_measure_id': best_measure['measure_id'] if best_measure is not None else None,
            'best_measure_cost_per_kwh': (
                best_measure['marginal_cost_per_kwh_saved']
                if best_measure is not None else np.nan
            ),
            'worst_measure_id': worst_measure['measure_id'] if worst_measure is not None else None,
            'worst_measure_cost_per_kwh': (
                worst_measure['marginal_cost_per_kwh_saved']
                if worst_measure is not None else np.nan
            ),
            'cost_ratio_worst_to_best': (
                worst_measure['marginal_cost_per_kwh_saved'] / best_measure['marginal_cost_per_kwh_saved']
                if (best_measure is not None and worst_measure is not None) else np.nan
            )
        }

        logger.info("\n" + "="*70)
        logger.info("TIPPING POINT ANALYSIS SUMMARY")
        logger.info("="*70)
        logger.info(f"Total measures analyzed: {summary['total_measures']}")
        logger.info(f"Total capex (full package): £{summary['total_capex']:,.0f}")
        logger.info(f"Total kWh saved: {summary['total_kwh_saved']:,.0f} kWh/year")
        logger.info(f"Total demand reduction: {summary['total_saving_pct']:.1f}%")
        logger.info(f"Average cost per kWh saved: £{summary['avg_cost_per_kwh']:.3f}/kWh")

        if best_measure is not None:
            logger.info(f"\nMost cost-effective: {summary['best_measure_id']}")
            logger.info(f"  Marginal cost: £{summary['best_measure_cost_per_kwh']:.3f}/kWh")

        if worst_measure is not None:
            logger.info(f"\nLeast cost-effective: {summary['worst_measure_id']}")
            logger.info(f"  Marginal cost: £{summary['worst_measure_cost_per_kwh']:.3f}/kWh")
            logger.info(f"  Cost ratio (worst/best): {summary['cost_ratio_worst_to_best']:.1f}x")

        logger.info("="*70 + "\n")

        return summary

    def run_analysis(
        self,
        typical_annual_heat_demand_kwh: float = 15000
    ) -> Tuple[pd.DataFrame, Dict]:
        """
        Run the complete tipping point analysis.

        Args:
            typical_annual_heat_demand_kwh: Baseline annual heating demand

        Returns:
            Tuple of (curve_df, summary_metrics)
        """
        logger.info("Running fabric tipping point analysis...")

        curve_df = self.calculate_tipping_point_curve(
            typical_annual_heat_demand_kwh=typical_annual_heat_demand_kwh
        )

        summary = self.generate_summary_metrics(curve_df)

        logger.info("Fabric tipping point analysis complete!")

        return curve_df, summary


def main():
    """Main execution function for fabric tipping point analysis."""
    logger.info("Starting fabric tipping point analysis...")

    analyzer = FabricTippingPointAnalyzer()

    # Use typical Edwardian terrace heating demand
    # (from literature: ~150 kWh/m²/year × 100m² floor area)
    curve_df, summary = analyzer.run_analysis(
        typical_annual_heat_demand_kwh=15000
    )

    logger.info("Analysis complete!")


if __name__ == "__main__":
    main()
