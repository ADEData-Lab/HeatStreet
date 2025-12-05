"""
Penetration Sensitivity Module

Analyzes sensitivity of pathway costs to heat network penetration and energy prices.
Creates output grids for interactive dashboard visualization.

Outputs:
- hn_penetration_sensitivity.csv: Grid of results by HN share and price scenario
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from itertools import product
from loguru import logger

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import (
    load_config,
    get_heat_network_params,
    get_financial_params,
    DATA_PROCESSED_DIR,
    DATA_OUTPUTS_DIR
)


class PenetrationSensitivityAnalyzer:
    """
    Analyzes sensitivity to heat network penetration and price assumptions.

    Generates grid of results for:
    - Different HN penetration levels (0.2% to 10%)
    - Different price scenarios (baseline, low, high, projected)
    """

    def __init__(self, output_dir: Optional[Path] = None):
        """Initialize the sensitivity analyzer."""
        self.config = load_config()
        self.hn_params = get_heat_network_params()
        self.financial = get_financial_params()

        self.output_dir = output_dir or DATA_OUTPUTS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Get penetration levels from config
        self.penetration_levels = self.hn_params.get(
            'penetration_sensitivity',
            [0.002, 0.005, 0.01, 0.02, 0.05, 0.10]
        )

        # Get price scenarios from config
        self.price_scenarios = self.financial.get('price_scenarios', {
            'baseline': {
                'name': 'Current prices',
                'gas': 0.0624,
                'electricity': 0.245,
                'heat_network': 0.08
            },
            'low': {
                'name': 'Low prices',
                'gas': 0.05,
                'electricity': 0.20,
                'heat_network': 0.06
            },
            'high': {
                'name': 'High prices',
                'gas': 0.08,
                'electricity': 0.30,
                'heat_network': 0.10
            }
        })

        # Heat pump SCOP
        self.hp_scop = self.config.get('heat_pump', {}).get('scop', 3.0)

        # HN efficiency
        self.hn_efficiency = self.hn_params.get('distribution_efficiency', 0.90)

        logger.info("Initialized PenetrationSensitivityAnalyzer")
        logger.info(f"  Penetration levels: {self.penetration_levels}")
        logger.info(f"  Price scenarios: {list(self.price_scenarios.keys())}")

    def calculate_pathway_costs(
        self,
        annual_heat_demand_kwh: float,
        pathway_id: str,
        gas_price: float,
        elec_price: float,
        hn_tariff: float
    ) -> Dict:
        """
        Calculate annual costs for a pathway given energy prices.

        Args:
            annual_heat_demand_kwh: Annual heat demand in kWh
            pathway_id: Pathway identifier
            gas_price: Gas price £/kWh
            elec_price: Electricity price £/kWh
            hn_tariff: Heat network tariff £/kWh

        Returns:
            Dictionary with cost metrics
        """
        if pathway_id == 'gas_baseline' or 'fabric_only' in pathway_id:
            # Gas boiler
            annual_bill = annual_heat_demand_kwh * gas_price
            cost_per_kwh = gas_price

        elif 'hp' in pathway_id and 'hn' not in pathway_id:
            # Heat pump only
            electricity_kwh = annual_heat_demand_kwh / self.hp_scop
            annual_bill = electricity_kwh * elec_price
            cost_per_kwh = elec_price / self.hp_scop

        elif 'hn' in pathway_id and 'hp' not in pathway_id:
            # Heat network only
            delivered_kwh = annual_heat_demand_kwh / self.hn_efficiency
            annual_bill = delivered_kwh * hn_tariff
            cost_per_kwh = hn_tariff / self.hn_efficiency

        else:
            # Hybrid - return both options
            hp_elec = annual_heat_demand_kwh / self.hp_scop
            hp_bill = hp_elec * elec_price

            hn_delivered = annual_heat_demand_kwh / self.hn_efficiency
            hn_bill = hn_delivered * hn_tariff

            # Return HP as default (HN depends on penetration)
            annual_bill = hp_bill
            cost_per_kwh = elec_price / self.hp_scop

        return {
            'annual_bill': annual_bill,
            'cost_per_kwh': cost_per_kwh
        }

    def run_sensitivity_analysis(
        self,
        annual_heat_demand_per_home: float = 12000,
        n_properties: int = 1000
    ) -> pd.DataFrame:
        """
        Run full sensitivity analysis across penetration and price combinations.

        Args:
            annual_heat_demand_per_home: Typical annual heat demand per property (kWh)
            n_properties: Total number of properties in analysis

        Returns:
            DataFrame with sensitivity results grid
        """
        logger.info("Running penetration and price sensitivity analysis...")

        results = []

        for hn_share, price_scenario in product(
            self.penetration_levels,
            self.price_scenarios.keys()
        ):
            prices = self.price_scenarios[price_scenario]
            gas_price = prices.get('gas', 0.0624)
            elec_price = prices.get('electricity', 0.245)
            hn_tariff = prices.get('heat_network', 0.08)

            # Number of homes on each pathway
            n_hn = int(n_properties * hn_share)
            n_hp = n_properties - n_hn

            # Calculate costs for each group
            # Heat network homes
            hn_cost = self.calculate_pathway_costs(
                annual_heat_demand_per_home,
                'fabric_plus_hn_only',
                gas_price, elec_price, hn_tariff
            )

            # Heat pump homes
            hp_cost = self.calculate_pathway_costs(
                annual_heat_demand_per_home,
                'fabric_plus_hp_only',
                gas_price, elec_price, hn_tariff
            )

            # Gas baseline
            gas_cost = self.calculate_pathway_costs(
                annual_heat_demand_per_home,
                'gas_baseline',
                gas_price, elec_price, hn_tariff
            )

            # Weighted average for hybrid pathway
            if n_properties > 0:
                hybrid_avg_bill = (
                    n_hn * hn_cost['annual_bill'] + n_hp * hp_cost['annual_bill']
                ) / n_properties
            else:
                hybrid_avg_bill = hp_cost['annual_bill']

            results.append({
                'hn_share': hn_share,
                'hn_share_pct': hn_share * 100,
                'price_scenario': price_scenario,
                'price_scenario_name': prices.get('name', price_scenario),

                # Prices
                'gas_price': gas_price,
                'elec_price': elec_price,
                'hn_tariff': hn_tariff,

                # Property counts
                'n_properties': n_properties,
                'n_hn_homes': n_hn,
                'n_hp_homes': n_hp,

                # Individual pathway costs
                'gas_baseline_annual_bill': gas_cost['annual_bill'],
                'gas_baseline_cost_per_kwh': gas_cost['cost_per_kwh'],

                'hp_pathway_annual_bill': hp_cost['annual_bill'],
                'hp_pathway_cost_per_kwh': hp_cost['cost_per_kwh'],

                'hn_pathway_annual_bill': hn_cost['annual_bill'],
                'hn_pathway_cost_per_kwh': hn_cost['cost_per_kwh'],

                # Hybrid pathway (weighted average)
                'hybrid_avg_annual_bill': hybrid_avg_bill,
                'hybrid_avg_cost_per_kwh': hybrid_avg_bill / annual_heat_demand_per_home,

                # Savings vs gas baseline
                'hp_saving_vs_gas': gas_cost['annual_bill'] - hp_cost['annual_bill'],
                'hn_saving_vs_gas': gas_cost['annual_bill'] - hn_cost['annual_bill'],
                'hybrid_saving_vs_gas': gas_cost['annual_bill'] - hybrid_avg_bill,

                # HP vs HN comparison
                'hn_cheaper_than_hp': hn_cost['annual_bill'] < hp_cost['annual_bill'],
                'hn_vs_hp_saving': hp_cost['annual_bill'] - hn_cost['annual_bill'],
            })

        results_df = pd.DataFrame(results)

        logger.info(f"Generated {len(results_df)} sensitivity results")

        return results_df

    def generate_summary_pivot(self, sensitivity_df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate pivot table summarizing key metrics.

        Args:
            sensitivity_df: Full sensitivity results

        Returns:
            Pivot table with HN share vs price scenario
        """
        # Pivot: rows = HN share, columns = price scenario, values = hybrid bill
        pivot = sensitivity_df.pivot_table(
            index='hn_share_pct',
            columns='price_scenario',
            values='hybrid_avg_annual_bill',
            aggfunc='mean'
        )

        return pivot

    def export_results(self, sensitivity_df: pd.DataFrame) -> Path:
        """Export sensitivity results."""
        output_path = self.output_dir / "hn_penetration_sensitivity.csv"
        sensitivity_df.to_csv(output_path, index=False)
        logger.info(f"Saved sensitivity results to {output_path}")

        # Also save pivot summary
        pivot = self.generate_summary_pivot(sensitivity_df)
        pivot_path = self.output_dir / "hn_penetration_sensitivity_pivot.csv"
        pivot.to_csv(pivot_path)
        logger.info(f"Saved pivot summary to {pivot_path}")

        return output_path

    def run_analysis(
        self,
        properties_df: Optional[pd.DataFrame] = None,
        annual_heat_demand_per_home: float = None
    ) -> Dict:
        """
        Run complete sensitivity analysis.

        Args:
            properties_df: Properties DataFrame (optional, for calculating mean demand)
            annual_heat_demand_per_home: Override annual demand per home

        Returns:
            Dictionary with results
        """
        logger.info("Running sensitivity analysis...")

        # Calculate mean demand from properties if provided
        if annual_heat_demand_per_home is None:
            if properties_df is not None and 'ENERGY_CONSUMPTION_CURRENT' in properties_df.columns:
                mean_intensity = properties_df['ENERGY_CONSUMPTION_CURRENT'].mean()
                mean_area = properties_df.get('TOTAL_FLOOR_AREA', pd.Series([100])).mean()
                annual_heat_demand_per_home = mean_intensity * mean_area * 0.8  # 80% for heating
                logger.info(f"Calculated mean heat demand: {annual_heat_demand_per_home:,.0f} kWh/home")
            else:
                annual_heat_demand_per_home = 12000  # Default
                logger.info(f"Using default heat demand: {annual_heat_demand_per_home:,.0f} kWh/home")

        n_properties = len(properties_df) if properties_df is not None else 1000

        # Run sensitivity
        sensitivity_df = self.run_sensitivity_analysis(
            annual_heat_demand_per_home=annual_heat_demand_per_home,
            n_properties=n_properties
        )

        # Export
        self.export_results(sensitivity_df)

        return {
            'sensitivity': sensitivity_df,
            'pivot': self.generate_summary_pivot(sensitivity_df)
        }


def main():
    """Main execution function."""
    logger.info("Starting penetration sensitivity analysis...")

    # Try to load validated properties for realistic demand calculation
    input_file = DATA_PROCESSED_DIR / "epc_london_validated.parquet"
    properties_df = None

    if input_file.exists():
        logger.info(f"Loading properties from: {input_file}")
        properties_df = pd.read_parquet(input_file)
    else:
        input_file = DATA_PROCESSED_DIR / "epc_london_validated.csv"
        if input_file.exists():
            properties_df = pd.read_csv(input_file, low_memory=False)

    # Run analysis
    analyzer = PenetrationSensitivityAnalyzer()
    results = analyzer.run_analysis(properties_df)

    # Log summary
    logger.info("\nSensitivity Analysis Summary:")

    if 'sensitivity' in results:
        sens_df = results['sensitivity']

        # Show comparison for baseline prices
        baseline = sens_df[sens_df['price_scenario'] == 'baseline']
        if len(baseline) > 0:
            logger.info("\nBaseline prices - annual bills by HN share:")
            for _, row in baseline.iterrows():
                logger.info(
                    f"  HN {row['hn_share_pct']:.1f}%: "
                    f"HP £{row['hp_pathway_annual_bill']:,.0f}, "
                    f"HN £{row['hn_pathway_annual_bill']:,.0f}, "
                    f"Hybrid £{row['hybrid_avg_annual_bill']:,.0f}"
                )

        # Show when HN is cheaper than HP
        hn_cheaper = sens_df[sens_df['hn_cheaper_than_hp']]
        if len(hn_cheaper) > 0:
            logger.info(f"\nHN is cheaper than HP in {len(hn_cheaper)}/{len(sens_df)} scenarios")

    logger.info("\nPenetration sensitivity analysis complete!")


if __name__ == "__main__":
    main()
