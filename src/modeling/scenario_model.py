"""
Scenario Modeling Module

Models decarbonization pathway scenarios for Edwardian terraced housing stock.
Implements Section 4 of the project specification.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from loguru import logger

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import (
    load_config,
    get_scenario_definitions,
    get_cost_assumptions,
    DATA_PROCESSED_DIR,
    DATA_OUTPUTS_DIR
)


@dataclass
class PropertyUpgrade:
    """Represents an upgrade to a single property."""
    property_id: str
    scenario: str
    capital_cost: float
    annual_energy_reduction_kwh: float
    annual_co2_reduction_kg: float
    annual_bill_savings: float
    new_epc_band: str
    payback_years: float


class ScenarioModeler:
    """
    Models different decarbonization pathways for the housing stock.
    """

    def __init__(self):
        """Initialize the scenario modeler."""
        self.config = load_config()
        self.scenarios = get_scenario_definitions()
        self.costs = get_cost_assumptions()
        self.energy_prices = self.config['energy_prices']
        self.carbon_factors = self.config['carbon_factors']

        self.results = {}

        logger.info("Initialized Scenario Modeler")
        logger.info(f"Loaded {len(self.scenarios)} scenarios")

    def model_all_scenarios(self, df: pd.DataFrame) -> Dict:
        """
        Model all decarbonization scenarios for the dataset.

        Args:
            df: Validated EPC DataFrame with property characteristics

        Returns:
            Dictionary containing results for all scenarios
        """
        logger.info(f"Modeling scenarios for {len(df):,} properties...")

        for scenario_name, scenario_config in self.scenarios.items():
            logger.info(f"\nModeling scenario: {scenario_name}")
            self.results[scenario_name] = self.model_scenario(df, scenario_name, scenario_config)

        logger.info("\nAll scenario modeling complete!")
        return self.results

    def model_scenario(
        self,
        df: pd.DataFrame,
        scenario_name: str,
        scenario_config: Dict
    ) -> Dict:
        """
        Model a single decarbonization scenario.

        Args:
            df: Property DataFrame
            scenario_name: Name of the scenario
            scenario_config: Scenario configuration

        Returns:
            Dictionary containing scenario results
        """
        measures = scenario_config.get('measures', [])

        if not measures:
            # Baseline scenario - no interventions
            return self._model_baseline(df)

        # Calculate costs and impacts for each property
        property_upgrades = []

        for idx, row in df.iterrows():
            upgrade = self._calculate_property_upgrade(row, scenario_name, measures)
            property_upgrades.append(upgrade)

        # Aggregate results
        results = self._aggregate_scenario_results(property_upgrades, df)
        results['scenario_name'] = scenario_name
        results['measures'] = measures

        return results

    def _model_baseline(self, df: pd.DataFrame) -> Dict:
        """Model baseline (no intervention) scenario."""
        logger.info("Modeling baseline scenario...")

        total_energy = df['ENERGY_CONSUMPTION_CURRENT'].sum() if 'ENERGY_CONSUMPTION_CURRENT' in df.columns else 0
        total_co2 = df['CO2_EMISSIONS_CURRENT'].sum() if 'CO2_EMISSIONS_CURRENT' in df.columns else 0

        return {
            'total_properties': len(df),
            'capital_cost_total': 0,
            'capital_cost_per_property': 0,
            'annual_energy_reduction_kwh': 0,
            'annual_co2_reduction_kg': 0,
            'annual_bill_savings': 0,
            'current_annual_energy_kwh': float(total_energy),
            'current_annual_co2_kg': float(total_co2),
            'epc_band_shifts': {},
            'average_payback_years': 0
        }

    def _calculate_property_upgrade(
        self,
        property_data: pd.Series,
        scenario_name: str,
        measures: List[str]
    ) -> PropertyUpgrade:
        """
        Calculate upgrade costs and impacts for a single property.

        Args:
            property_data: Property characteristics
            scenario_name: Name of the scenario
            measures: List of measures to apply

        Returns:
            PropertyUpgrade object
        """
        capital_cost = 0
        energy_reduction = 0
        co2_reduction = 0

        floor_area = property_data.get('TOTAL_FLOOR_AREA', 100)  # Default if missing

        # Calculate costs and impacts for each measure
        for measure in measures:
            if measure == 'loft_insulation_topup':
                capital_cost += self._cost_loft_insulation(property_data)
                energy_reduction += self._savings_loft_insulation(property_data)

            elif measure == 'wall_insulation':
                capital_cost += self._cost_wall_insulation(property_data)
                energy_reduction += self._savings_wall_insulation(property_data)

            elif measure == 'double_glazing':
                capital_cost += self._cost_glazing(property_data)
                energy_reduction += self._savings_glazing(property_data)

            elif measure == 'ashp_installation':
                capital_cost += self.costs['ashp_installation']
                energy_reduction += self._savings_heat_pump(property_data)

            elif measure == 'emitter_upgrades':
                capital_cost += self._cost_emitter_upgrade(property_data)

            elif measure == 'district_heating_connection':
                capital_cost += self.costs['district_heating_connection']
                energy_reduction += self._savings_district_heating(property_data)

            elif measure in ['fabric_improvements', 'modest_fabric_improvements']:
                # Combination of measures
                capital_cost += self._cost_fabric_package(property_data)
                energy_reduction += self._savings_fabric_package(property_data)

        # Calculate CO2 reduction
        co2_reduction = energy_reduction * self.carbon_factors['current']['gas']

        # Calculate bill savings
        bill_savings = energy_reduction * self.energy_prices['current']['gas']

        # Estimate new EPC band (simplified)
        current_rating = property_data.get('CURRENT_ENERGY_EFFICIENCY', 50)
        improvement_points = (energy_reduction / floor_area) * 0.5  # Simplified conversion
        new_rating = min(100, current_rating + improvement_points)
        new_band = self._rating_to_band(new_rating)

        # Calculate payback period
        payback_years = capital_cost / bill_savings if bill_savings > 0 else 999

        return PropertyUpgrade(
            property_id=str(property_data.get('LMK_KEY', 'unknown')),
            scenario=scenario_name,
            capital_cost=capital_cost,
            annual_energy_reduction_kwh=energy_reduction,
            annual_co2_reduction_kg=co2_reduction,
            annual_bill_savings=bill_savings,
            new_epc_band=new_band,
            payback_years=payback_years
        )

    def _cost_loft_insulation(self, property_data: pd.Series) -> float:
        """Calculate cost of loft insulation top-up."""
        floor_area = property_data.get('TOTAL_FLOOR_AREA', 100)
        # Assume loft area is ~90% of floor area
        loft_area = floor_area * 0.9
        return loft_area * self.costs['loft_insulation_per_m2']

    def _savings_loft_insulation(self, property_data: pd.Series) -> float:
        """Calculate energy savings from loft insulation."""
        # Typical savings: 15-25% of heating energy for uninsulated loft
        current_energy = property_data.get('ENERGY_CONSUMPTION_CURRENT', 15000)
        return current_energy * 0.15  # Conservative estimate

    def _cost_wall_insulation(self, property_data: pd.Series) -> float:
        """Calculate cost of wall insulation."""
        wall_type = property_data.get('wall_type', 'Solid')
        floor_area = property_data.get('TOTAL_FLOOR_AREA', 100)

        if wall_type == 'Cavity':
            return self.costs['cavity_wall_insulation']
        else:
            # Internal wall insulation for solid walls
            # Assume wall area = floor area * 1.5 (simplified)
            wall_area = floor_area * 1.5
            return wall_area * self.costs['internal_wall_insulation_per_m2']

    def _savings_wall_insulation(self, property_data: pd.Series) -> float:
        """Calculate energy savings from wall insulation."""
        # Typical savings: 20-35% of heating energy for uninsulated walls
        current_energy = property_data.get('ENERGY_CONSUMPTION_CURRENT', 15000)
        wall_type = property_data.get('wall_type', 'Solid')

        if wall_type == 'Cavity':
            return current_energy * 0.20
        else:
            return current_energy * 0.30  # Higher savings for solid walls

    def _cost_glazing(self, property_data: pd.Series) -> float:
        """Calculate cost of window glazing upgrade."""
        floor_area = property_data.get('TOTAL_FLOOR_AREA', 100)
        # Assume window area = floor area * 0.2 (simplified)
        window_area = floor_area * 0.2
        return window_area * self.costs['double_glazing_per_m2']

    def _savings_glazing(self, property_data: pd.Series) -> float:
        """Calculate energy savings from window glazing."""
        # Typical savings: 10-15% of heating energy
        current_energy = property_data.get('ENERGY_CONSUMPTION_CURRENT', 15000)
        return current_energy * 0.10

    def _savings_heat_pump(self, property_data: pd.Series) -> float:
        """Calculate energy savings from heat pump (accounting for COP)."""
        # Heat pumps use electricity instead of gas
        # With SCOP of 3.0, need 1/3 the energy
        # But electricity is ~3.4x more expensive than gas
        # So bill impact is complex - simplified here
        current_heating = property_data.get('ENERGY_CONSUMPTION_CURRENT', 15000) * 0.8
        # Primary energy savings (gas reduced, electricity increased)
        gas_saved = current_heating
        electricity_used = current_heating / self.config['heat_pump']['scop']
        return gas_saved - electricity_used

    def _cost_emitter_upgrade(self, property_data: pd.Series) -> float:
        """Calculate cost of radiator emitter upgrades for heat pump."""
        floor_area = property_data.get('TOTAL_FLOOR_AREA', 100)
        # Assume 1 radiator per 15 m²
        num_radiators = int(floor_area / 15)
        return num_radiators * self.costs['emitter_upgrade_per_radiator']

    def _savings_district_heating(self, property_data: pd.Series) -> float:
        """Calculate savings from district heating connection."""
        # Depends on district heating tariff vs current costs
        # Simplified: 10-20% savings on bills
        current_energy = property_data.get('ENERGY_CONSUMPTION_CURRENT', 15000)
        return current_energy * 0.15

    def _cost_fabric_package(self, property_data: pd.Series) -> float:
        """Calculate cost of combined fabric improvements."""
        total = 0
        total += self._cost_loft_insulation(property_data)
        total += self._cost_wall_insulation(property_data)
        total += self._cost_glazing(property_data)
        return total

    def _savings_fabric_package(self, property_data: pd.Series) -> float:
        """Calculate savings from combined fabric improvements."""
        # Don't simply add - there are diminishing returns
        # Use conservative estimate of 40% total savings
        current_energy = property_data.get('ENERGY_CONSUMPTION_CURRENT', 15000)
        return current_energy * 0.40

    def _rating_to_band(self, rating: float) -> str:
        """Convert SAP rating to EPC band."""
        if rating >= 92:
            return 'A'
        elif rating >= 81:
            return 'B'
        elif rating >= 69:
            return 'C'
        elif rating >= 55:
            return 'D'
        elif rating >= 39:
            return 'E'
        elif rating >= 21:
            return 'F'
        else:
            return 'G'

    def _aggregate_scenario_results(
        self,
        upgrades: List[PropertyUpgrade],
        df: pd.DataFrame
    ) -> Dict:
        """
        Aggregate individual property upgrades into scenario-level results.

        Args:
            upgrades: List of PropertyUpgrade objects
            df: Original property DataFrame

        Returns:
            Aggregated scenario results
        """
        total_properties = len(upgrades)

        results = {
            'total_properties': total_properties,
            'capital_cost_total': sum(u.capital_cost for u in upgrades),
            'capital_cost_per_property': sum(u.capital_cost for u in upgrades) / total_properties,
            'annual_energy_reduction_kwh': sum(u.annual_energy_reduction_kwh for u in upgrades),
            'annual_co2_reduction_kg': sum(u.annual_co2_reduction_kg for u in upgrades),
            'annual_bill_savings': sum(u.annual_bill_savings for u in upgrades),
            'average_payback_years': np.mean([u.payback_years for u in upgrades if u.payback_years < 100]),
            'median_payback_years': np.median([u.payback_years for u in upgrades if u.payback_years < 100])
        }

        # EPC band shifts
        current_bands = df['CURRENT_ENERGY_RATING'].value_counts().to_dict() if 'CURRENT_ENERGY_RATING' in df.columns else {}
        new_bands = pd.Series([u.new_epc_band for u in upgrades]).value_counts().to_dict()

        results['epc_band_shifts'] = {
            'before': current_bands,
            'after': new_bands
        }

        # Payback distribution
        payback_categories = {
            '0-5 years': len([u for u in upgrades if u.payback_years <= 5]),
            '5-10 years': len([u for u in upgrades if 5 < u.payback_years <= 10]),
            '10-15 years': len([u for u in upgrades if 10 < u.payback_years <= 15]),
            '15-20 years': len([u for u in upgrades if 15 < u.payback_years <= 20]),
            '>20 years': len([u for u in upgrades if u.payback_years > 20])
        }

        results['payback_distribution'] = payback_categories

        return results

    def model_subsidy_sensitivity(
        self,
        df: pd.DataFrame,
        scenario_name: str = 'heat_pump'
    ) -> Dict:
        """
        Model impact of varying subsidy levels on uptake and costs.

        Args:
            df: Property DataFrame
            scenario_name: Which scenario to apply subsidies to

        Returns:
            Dictionary containing subsidy sensitivity results
        """
        logger.info(f"Modeling subsidy sensitivity for {scenario_name} scenario...")

        subsidy_levels = self.config.get('subsidy_levels', [0, 25, 50, 75, 100])
        scenario_config = self.scenarios[scenario_name]

        sensitivity_results = {}

        for subsidy_pct in subsidy_levels:
            logger.info(f"  Analyzing {subsidy_pct}% subsidy level...")

            # Model scenario with subsidy
            base_results = self.model_scenario(df, scenario_name, scenario_config)

            # Apply subsidy
            capital_cost_subsidized = base_results['capital_cost_total'] * (1 - subsidy_pct/100)
            capital_cost_per_property = base_results['capital_cost_per_property'] * (1 - subsidy_pct/100)

            # Recalculate payback with subsidy
            annual_savings = base_results['annual_bill_savings']
            payback_years = capital_cost_subsidized / annual_savings if annual_savings > 0 else 999

            # Estimate uptake based on payback (simplified model)
            # Assume uptake increases as payback decreases
            if payback_years <= 5:
                uptake_rate = 0.80
            elif payback_years <= 10:
                uptake_rate = 0.60
            elif payback_years <= 15:
                uptake_rate = 0.40
            elif payback_years <= 20:
                uptake_rate = 0.20
            else:
                uptake_rate = 0.05

            properties_upgraded = int(base_results['total_properties'] * uptake_rate)
            public_expenditure = (base_results['capital_cost_per_property'] * subsidy_pct/100) * properties_upgraded

            # Carbon abatement cost
            total_co2_saved = base_results['annual_co2_reduction_kg'] * uptake_rate * 20  # 20-year lifetime
            carbon_abatement_cost = public_expenditure / (total_co2_saved / 1000) if total_co2_saved > 0 else 0  # £/tCO2

            sensitivity_results[f'{subsidy_pct}%'] = {
                'subsidy_percentage': subsidy_pct,
                'capital_cost_per_property': capital_cost_per_property,
                'payback_years': payback_years,
                'estimated_uptake_rate': uptake_rate,
                'properties_upgraded': properties_upgraded,
                'public_expenditure_total': public_expenditure,
                'public_expenditure_per_property': public_expenditure / properties_upgraded if properties_upgraded > 0 else 0,
                'carbon_abatement_cost_per_tonne': carbon_abatement_cost
            }

        return sensitivity_results

    def save_results(self, output_path: Optional[Path] = None):
        """
        Save scenario modeling results to file.

        Args:
            output_path: Path to save results
        """
        if output_path is None:
            output_path = DATA_OUTPUTS_DIR / "scenario_modeling_results.txt"

        with open(output_path, 'w') as f:
            f.write("SCENARIO MODELING RESULTS\n")
            f.write("="*70 + "\n\n")

            for scenario, results in self.results.items():
                f.write(f"\nSCENARIO: {scenario.upper()}\n")
                f.write("-"*70 + "\n")

                for key, value in results.items():
                    if key != 'measures':
                        f.write(f"{key}: {value}\n")

                f.write("\n")

        logger.info(f"Results saved to: {output_path}")


def main():
    """Main execution function for scenario modeling."""
    logger.info("Starting scenario modeling...")

    # Load validated data
    input_file = DATA_PROCESSED_DIR / "epc_london_validated.csv"

    if not input_file.exists():
        logger.error(f"Input file not found: {input_file}")
        return

    logger.info(f"Loading data from: {input_file}")
    df = pd.read_csv(input_file, low_memory=False)

    # Initialize modeler
    modeler = ScenarioModeler()

    # Model all scenarios
    results = modeler.model_all_scenarios(df)

    # Model subsidy sensitivity
    subsidy_results = modeler.model_subsidy_sensitivity(df, 'heat_pump')

    # Save results
    modeler.save_results()

    logger.info("Scenario modeling complete!")


if __name__ == "__main__":
    main()
