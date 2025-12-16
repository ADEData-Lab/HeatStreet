"""
Scenario Modeling Module

Models decarbonization pathway scenarios for Edwardian terraced housing stock.
Implements Section 4 of the project specification.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from loguru import logger
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import os

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import (
    load_config,
    get_scenario_definitions,
    get_cost_assumptions,
    get_analysis_horizon_years,
    get_measure_savings,
    DATA_PROCESSED_DIR,
    DATA_OUTPUTS_DIR
)
from src.analysis.fabric_tipping_point import FabricTippingPointAnalyzer
from src.spatial.heat_network_analysis import HeatNetworkAnalyzer


@dataclass
class PropertyUpgrade:
    """Represents an upgrade to a single property."""
    property_id: str
    scenario: str
    capital_cost: float
    annual_energy_reduction_kwh: float
    annual_co2_reduction_kg: float
    annual_bill_savings: float
    baseline_bill: float = 0.0
    post_measure_bill: float = 0.0
    baseline_co2_kg: float = 0.0
    post_measure_co2_kg: float = 0.0
    new_epc_band: str = ''
    payback_years: float = np.inf
    uprn: str = ''
    postcode: str = ''
    measures_applied: List[str] = field(default_factory=list)
    measures_removed: List[str] = field(default_factory=list)
    hybrid_pathway: Optional[str] = None
    hn_ready: bool = False
    tier_number: Optional[int] = None
    distance_to_network_m: Optional[float] = None
    in_heat_zone: bool = False
    ashp_ready: bool = False
    ashp_projected_ready: bool = False
    ashp_fabric_needed: bool = False
    ashp_not_ready_after_fabric: bool = False
    fabric_inserted_for_hp: bool = False
    heat_pump_removed: bool = False


def _calculate_property_upgrade_worker(args):
    """
    Worker function for parallel property upgrade calculations.
    Must be at module level for pickling.

    Args:
        args: Tuple of (property_dict, scenario_name, measures, costs, config)

    Returns:
        PropertyUpgrade object
    """
    (
        property_dict,
        scenario_name,
        measures,
        costs,
        config,
        applied_fabric,
        removed_hp,
        hybrid_pathway,
        removed_measures,
    ) = args

    capital_cost = 0
    energy_reduction = 0
    co2_reduction = 0

    floor_area = property_dict.get('TOTAL_FLOOR_AREA', 100)
    energy_consumption = property_dict.get('ENERGY_CONSUMPTION_CURRENT', 150)
    wall_type = property_dict.get('wall_type', 'Solid')
    current_rating = property_dict.get('CURRENT_ENERGY_EFFICIENCY', 50)

    # Helper function to get absolute energy
    def get_absolute_energy():
        return energy_consumption * floor_area

    # Calculate costs and impacts for each measure
    for measure in measures:
        if measure == 'loft_insulation_topup':
            loft_area = floor_area * 0.9
            capital_cost += loft_area * costs['loft_insulation_per_m2']
            energy_reduction += get_absolute_energy() * 0.15

        elif measure == 'wall_insulation':
            if wall_type == 'Cavity':
                capital_cost += costs['cavity_wall_insulation']
                energy_reduction += get_absolute_energy() * 0.20
            else:
                wall_area = floor_area * 1.5
                capital_cost += wall_area * costs['internal_wall_insulation_per_m2']
                energy_reduction += get_absolute_energy() * 0.30

        elif measure == 'double_glazing':
            window_area = floor_area * 0.2
            capital_cost += window_area * costs['double_glazing_per_m2']
            energy_reduction += get_absolute_energy() * 0.10

        elif measure == 'triple_glazing':
            window_area = floor_area * 0.2
            capital_cost += costs.get('triple_glazing_upgrade', window_area * costs.get('double_glazing_per_m2', 0))
            energy_reduction += get_absolute_energy() * 0.15

        elif measure == 'floor_insulation':
            capital_cost += costs.get('floor_insulation', 0)
            energy_reduction += get_absolute_energy() * 0.05

        elif measure == 'draught_proofing':
            capital_cost += costs.get('draught_proofing', 0)
            energy_reduction += get_absolute_energy() * 0.05

        elif measure == 'ashp_installation':
            capital_cost += costs['ashp_installation']
            current_heating = get_absolute_energy() * 0.8
            gas_saved = current_heating
            electricity_used = current_heating / config['heat_pump']['scop']
            energy_reduction += gas_saved - electricity_used

        elif measure == 'emitter_upgrades':
            num_radiators = int(floor_area / 15)
            capital_cost += num_radiators * costs['emitter_upgrade_per_radiator']

        elif measure == 'district_heating_connection':
            capital_cost += costs['district_heating_connection']
            energy_reduction += get_absolute_energy() * 0.15

        elif measure in ['fabric_improvements', 'modest_fabric_improvements']:
            # Combination of measures
            loft_area = floor_area * 0.9
            capital_cost += loft_area * costs['loft_insulation_per_m2']
            if wall_type == 'Cavity':
                capital_cost += costs['cavity_wall_insulation']
            else:
                wall_area = floor_area * 1.5
                capital_cost += wall_area * costs['internal_wall_insulation_per_m2']
            window_area = floor_area * 0.2
            capital_cost += window_area * costs['double_glazing_per_m2']
            energy_reduction += get_absolute_energy() * 0.40

    # Calculate CO2 reduction
    co2_reduction = energy_reduction * config['carbon_factors']['current']['gas']

    # Calculate bill savings
    bill_savings = energy_reduction * config['energy_prices']['current']['gas']

    baseline_bill = get_absolute_energy() * config['energy_prices']['current']['gas']
    post_measure_bill = max(baseline_bill - bill_savings, 0)

    baseline_co2 = get_absolute_energy() * config['carbon_factors']['current']['gas']
    post_measure_co2 = max(baseline_co2 - co2_reduction, 0)

    # Estimate new EPC band
    improvement_points = (energy_reduction / floor_area) * 0.5
    new_rating = min(100, current_rating + improvement_points)

    # Convert rating to band
    if new_rating >= 92:
        new_band = 'A'
    elif new_rating >= 81:
        new_band = 'B'
    elif new_rating >= 69:
        new_band = 'C'
    elif new_rating >= 55:
        new_band = 'D'
    elif new_rating >= 39:
        new_band = 'E'
    elif new_rating >= 21:
        new_band = 'F'
    else:
        new_band = 'G'

    # Calculate payback period
    if pd.isna(bill_savings) or pd.isna(capital_cost):
        payback_years = np.inf
    elif bill_savings <= 0:
        payback_years = np.inf
    elif capital_cost <= 0:
        payback_years = 0
    else:
        payback_years = capital_cost / bill_savings

    return PropertyUpgrade(
        property_id=str(property_dict.get('LMK_KEY', 'unknown')),
        uprn=str(property_dict.get('UPRN', '')),
        postcode=str(property_dict.get('POSTCODE', '')),
        scenario=scenario_name,
        measures_applied=measures,
        measures_removed=removed_measures,
        hybrid_pathway=hybrid_pathway,
        hn_ready=bool(property_dict.get('hn_ready', False)),
        tier_number=property_dict.get('tier_number'),
        distance_to_network_m=property_dict.get('distance_to_network_m'),
        in_heat_zone=bool(property_dict.get('in_heat_zone', False)),
        ashp_ready=bool(property_dict.get('ashp_ready', False)),
        ashp_projected_ready=bool(property_dict.get('ashp_projected_ready', False)),
        ashp_fabric_needed=bool(property_dict.get('ashp_fabric_needed', False)),
        ashp_not_ready_after_fabric=bool(property_dict.get('ashp_not_ready_after_fabric', False)),
        fabric_inserted_for_hp=applied_fabric,
        heat_pump_removed=removed_hp,
        capital_cost=capital_cost if not pd.isna(capital_cost) else 0,
        annual_energy_reduction_kwh=energy_reduction if not pd.isna(energy_reduction) else 0,
        annual_co2_reduction_kg=co2_reduction if not pd.isna(co2_reduction) else 0,
        annual_bill_savings=bill_savings if not pd.isna(bill_savings) else 0,
        baseline_bill=baseline_bill if not pd.isna(baseline_bill) else 0,
        post_measure_bill=post_measure_bill if not pd.isna(post_measure_bill) else 0,
        baseline_co2_kg=baseline_co2 if not pd.isna(baseline_co2) else 0,
        post_measure_co2_kg=post_measure_co2 if not pd.isna(post_measure_co2) else 0,
        new_epc_band=new_band,
        payback_years=payback_years
    )


class ScenarioModeler:
    """
    Models different decarbonization pathways for the housing stock.
    """

    def __init__(self):
        """Initialize the scenario modeler."""
        self.config = load_config()
        self.scenarios = get_scenario_definitions()
        self.costs = get_cost_assumptions()
        self.measure_savings = get_measure_savings()
        self.energy_prices = self.config['energy_prices']
        self.carbon_factors = self.config['carbon_factors']
        self.analysis_horizon_years = get_analysis_horizon_years()

        self.measure_catalogue = {
            'loft_insulation_topup',
            'wall_insulation',
            'double_glazing',
            'triple_glazing',
            'floor_insulation',
            'draught_proofing',
            'ashp_installation',
            'emitter_upgrades',
            'district_heating_connection',
            'fabric_improvements',
            'modest_fabric_improvements',
            'heat_network_where_available',
            'ashp_elsewhere',
            'fabric_bundle_tipping_point',
            'fabric_bundle_minimum_ashp'
        }

        eligibility_cfg = self.config.get('eligibility', {}).get('ashp', {})
        self.ashp_heat_demand_threshold = eligibility_cfg.get('max_heat_demand_kwh_per_m2', 100)
        self.ashp_min_epc_band = eligibility_cfg.get('min_epc_band', 'C')

        # Fabric bundles derived from marginal benefit analysis
        tipping_analyzer = FabricTippingPointAnalyzer(output_dir=DATA_OUTPUTS_DIR)
        curve_df, _ = tipping_analyzer.run_analysis()
        self.fabric_bundles = tipping_analyzer.derive_fabric_bundles(
            curve_df,
            typical_annual_heat_demand_kwh=15000
        )
        self.fabric_placeholder_map = {
            'fabric_improvements': self._map_fabric_bundle_to_scenario(
                self.fabric_bundles.get('fabric_full_to_tipping', [])
            ),
            'modest_fabric_improvements': self._map_fabric_bundle_to_scenario(
                self.fabric_bundles.get('fabric_minimum_to_ashp', [])
            )
        }
        self.fabric_minimum_measures = self._map_fabric_bundle_to_scenario(
            self.fabric_bundles.get('fabric_minimum_to_ashp', [])
        )
        self.scenarios = self._validate_scenario_definitions(
            self._inject_fabric_bundles(self.scenarios)
        )

        self.results = {}
        self.property_results: Dict[str, pd.DataFrame] = {}

        self.hn_analyzer = HeatNetworkAnalyzer()

        logger.info("Initialized Scenario Modeler")
        logger.info(f"Loaded {len(self.scenarios)} scenarios")

    def _apply_heat_network_readiness(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add deterministic heat network readiness columns to the EPC dataset."""

        required_cols = {'hn_ready', 'tier_number', 'distance_to_network_m', 'in_heat_zone'}

        if required_cols.issubset(df.columns):
            return df

        try:
            logger.info("Enriching EPC data with heat network readiness flags...")
            annotated = self.hn_analyzer.annotate_heat_network_readiness(df)
            if annotated is not None:
                return annotated
        except Exception as exc:
            logger.warning(f"Heat network readiness annotation failed: {exc}")

        fallback = df.copy()
        fallback['hn_ready'] = False
        fallback['tier_number'] = fallback.get('tier_number', 5)
        fallback['distance_to_network_m'] = np.nan
        fallback['in_heat_zone'] = False
        fallback['tier_number'] = pd.to_numeric(fallback['tier_number'], errors='coerce').fillna(5).astype(int)
        return fallback

    def model_all_scenarios(self, df: pd.DataFrame) -> Dict:
        """
        Model all decarbonization scenarios for the dataset.

        Args:
            df: Validated EPC DataFrame with property characteristics

        Returns:
            Dictionary containing results for all scenarios
        """
        logger.info(f"Modeling scenarios for {len(df):,} properties...")

        df_with_flags = self._preprocess_ashp_readiness(df)

        for scenario_name, scenario_config in self.scenarios.items():
            logger.info(f"\nModeling scenario: {scenario_name}")
            self.results[scenario_name] = self.model_scenario(df_with_flags, scenario_name, scenario_config)

        logger.info("\nAll scenario modeling complete!")
        return self.results

    def model_scenario(
        self,
        df: pd.DataFrame,
        scenario_name: str,
        scenario_config: Dict
    ) -> Dict:
        """
        Model a single decarbonization scenario with parallel processing.

        Args:
            df: Property DataFrame
            scenario_name: Name of the scenario
            scenario_config: Scenario configuration

        Returns:
            Dictionary containing scenario results
        """
        measures = scenario_config.get('measures', [])
        measures = self._resolve_scenario_measures(measures)

        if not measures:
            # Baseline scenario - no interventions
            return self._model_baseline(df)

        df_with_flags = self._preprocess_ashp_readiness(df)

        # Calculate costs and impacts for each property using parallel processing
        logger.info(f"  Processing {len(df_with_flags):,} properties in parallel...")

        # Convert DataFrame rows to dictionaries for pickling
        property_dicts = df_with_flags.to_dict('records')

        # Prepare arguments for parallel processing
        args_list = []

        for prop_dict in property_dicts:
            property_measures, applied_fabric, removed_hp, hybrid_pathway, removed_measures = self._build_property_measures(
                measures,
                prop_dict
            )

            args_list.append(
                (
                    prop_dict,
                    scenario_name,
                    property_measures,
                    self.costs,
                    self.config,
                    applied_fabric,
                    removed_hp,
                    hybrid_pathway,
                    removed_measures
                )
            )

        # Use ProcessPoolExecutor for CPU-bound calculations
        # Use max_workers based on CPU count, leave some cores free
        max_workers = max(1, multiprocessing.cpu_count() - 1)

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            property_upgrades = list(executor.map(_calculate_property_upgrade_worker, args_list, chunksize=100))

        logger.info(f"  Parallel processing complete!")

        property_df = pd.DataFrame([asdict(upgrade) for upgrade in property_upgrades])
        self.property_results[scenario_name] = property_df

        # Aggregate results
        results = self._aggregate_scenario_results(property_df, df_with_flags)
        results['scenario_name'] = scenario_name
        results['measures'] = measures

        return results

    def _model_baseline(self, df: pd.DataFrame) -> Dict:
        """Model baseline (no intervention) scenario."""
        logger.info("Modeling baseline scenario...")

        # ENERGY_CONSUMPTION_CURRENT is in kWh/m²/year - multiply by floor area for absolute values
        if 'ENERGY_CONSUMPTION_CURRENT' in df.columns and 'TOTAL_FLOOR_AREA' in df.columns:
            total_energy = (df['ENERGY_CONSUMPTION_CURRENT'] * df['TOTAL_FLOOR_AREA']).sum()
        else:
            total_energy = 0

        # CO2_EMISSIONS_CURRENT is already in tonnes/year (absolute)
        total_co2 = df['CO2_EMISSIONS_CURRENT'].sum() if 'CO2_EMISSIONS_CURRENT' in df.columns else 0
        # Convert tonnes to kg
        total_co2_kg = total_co2 * 1000

        return {
            'total_properties': len(df),
            'capital_cost_total': 0,
            'capital_cost_per_property': 0,
            'annual_energy_reduction_kwh': 0,
            'annual_co2_reduction_kg': 0,
            'annual_bill_savings': 0,
            'current_annual_energy_kwh': float(total_energy),
            'current_annual_co2_kg': float(total_co2_kg),
            'epc_band_shifts': {},
            'average_payback_years': 0
        }

    def _inject_fabric_bundles(self, scenarios: Dict[str, Dict]) -> Dict[str, Dict]:
        """Replace fabric bundle placeholders with concrete measure lists."""
        expanded = {}
        for scenario_name, scenario_cfg in scenarios.items():
            measures = scenario_cfg.get('measures', [])
            expanded_measures: List[str] = []

            for measure in measures:
                if measure == 'fabric_bundle_tipping_point':
                    expanded_measures.extend(
                        self._map_fabric_bundle_to_scenario(
                            self.fabric_bundles.get('fabric_full_to_tipping', [])
                        )
                    )
                elif measure == 'fabric_bundle_minimum_ashp':
                    expanded_measures.extend(
                        self._map_fabric_bundle_to_scenario(
                            self.fabric_bundles.get('fabric_minimum_to_ashp', [])
                        )
                    )
                else:
                    expanded_measures.append(measure)

            # Preserve order while removing duplicates
            deduped: List[str] = []
            for item in expanded_measures:
                if item not in deduped:
                    deduped.append(item)

            expanded[scenario_name] = {
                **scenario_cfg,
                'measures': deduped
            }

        return expanded

    def _validate_scenario_definitions(self, scenarios: Dict[str, Dict]) -> Dict[str, Dict]:
        """Ensure scenarios only contain recognised measures."""
        for scenario_name, scenario_cfg in scenarios.items():
            measures = scenario_cfg.get('measures', [])
            self._validate_measures(measures, context=f"Scenario '{scenario_name}'")

        return scenarios

    def _resolve_scenario_measures(self, measures: List[str]) -> List[str]:
        """Expand placeholders and validate measure lists prior to modeling."""
        resolved = self._expand_fabric_placeholders(measures)
        self._validate_measures(resolved)
        return self._dedupe_preserve_order(resolved)

    def _expand_fabric_placeholders(self, measures: List[str]) -> List[str]:
        resolved: List[str] = []
        for measure in measures:
            if measure in self.fabric_placeholder_map:
                resolved.extend(self.fabric_placeholder_map.get(measure, []))
            else:
                resolved.append(measure)

        return resolved

    def _validate_measures(self, measures: List[str], context: str = "") -> None:
        unknown = sorted({m for m in measures if m not in self.measure_catalogue})
        if unknown:
            message = ", ".join(unknown)
            if context:
                raise ValueError(f"{context} contains unrecognised measures: {message}")
            raise ValueError(f"Unrecognised measures: {message}")

    def _map_fabric_bundle_to_scenario(self, bundle: List[str]) -> List[str]:
        """Translate catalogue measure IDs to scenario measure names."""
        mapping = {
            'loft_insulation': 'loft_insulation_topup',
            'cavity_wall_insulation': 'wall_insulation',
            'solid_wall_insulation_ewi': 'wall_insulation',
            'solid_wall_insulation_iwi': 'wall_insulation',
            'floor_insulation': 'floor_insulation',
            'double_glazing_upgrade': 'double_glazing',
            'triple_glazing_upgrade': 'triple_glazing',
            'draught_proofing': 'draught_proofing'
        }

        mapped: List[str] = []
        for measure in bundle:
            mapped_measure = mapping.get(measure)
            if mapped_measure:
                mapped.append(mapped_measure)

        return mapped

    def _preprocess_ashp_readiness(self, df: pd.DataFrame) -> pd.DataFrame:
        """Flag properties that meet (or can meet) ASHP readiness thresholds."""

        df = self._apply_heat_network_readiness(df)

        if 'ashp_ready' in df.columns:
            return df

        processed = df.copy()
        heat_demand = processed.get('ENERGY_CONSUMPTION_CURRENT')
        if heat_demand is None:
            heat_demand = pd.Series(np.nan, index=processed.index)
        processed['heat_demand_kwh_m2'] = heat_demand

        if 'hn_ready' not in processed.columns:
            tier_values = processed.get('heat_network_tier')
            if tier_values is None:
                processed['hn_ready'] = False
            else:
                processed['hn_ready'] = tier_values.fillna('').apply(
                    lambda tier: isinstance(tier, str) and not str(tier).startswith('Tier 5') and str(tier).strip() != ''
                )

        processed['ashp_meets_heat_demand'] = heat_demand <= self.ashp_heat_demand_threshold

        processed['ashp_meets_epc'] = processed.get('CURRENT_ENERGY_RATING', pd.Series('', index=processed.index)).apply(
            lambda band: self._is_band_at_least(str(band), self.ashp_min_epc_band)
        )

        processed['ashp_ready'] = processed['ashp_meets_heat_demand'] | processed['ashp_meets_epc']

        projected = self._estimate_heat_demand_after_measures(
            heat_demand,
            self.fabric_minimum_measures
        )

        processed['ashp_heat_demand_after_fabric'] = projected
        processed['ashp_projected_ready'] = projected <= self.ashp_heat_demand_threshold
        processed['ashp_fabric_needed'] = ~processed['ashp_ready'] & processed['ashp_projected_ready']
        processed['ashp_not_ready_after_fabric'] = ~processed['ashp_ready'] & ~processed['ashp_projected_ready']

        return processed

    def _build_property_measures(self, measures: List[str], property_dict: Dict) -> Tuple[List[str], bool, bool, Optional[str], List[str]]:
        """Insert ASHP-readiness fabric where needed and drop ASHP when infeasible."""

        measure_plan = self._resolve_scenario_measures(measures)
        hybrid_pathway: Optional[str] = None
        removed: List[str] = []

        if {'heat_network_where_available', 'ashp_elsewhere'} & set(measure_plan):
            hn_ready = bool(property_dict.get('hn_ready', False))
            updated_plan: List[str] = [
                m for m in measure_plan if m not in ['heat_network_where_available', 'ashp_elsewhere']
            ]

            if hn_ready:
                updated_plan.append('district_heating_connection')
                hybrid_pathway = 'heat_network'
            else:
                updated_plan.extend(['ashp_installation', 'emitter_upgrades'])
                hybrid_pathway = 'ashp'

            measure_plan = updated_plan

        needs_heat_pump = 'ashp_installation' in measure_plan
        applied_fabric = False
        removed_hp = False

        if needs_heat_pump:
            ready = bool(property_dict.get('ashp_ready', False))
            projected_ready = bool(property_dict.get('ashp_projected_ready', False))

            if not ready and projected_ready:
                measure_plan = self.fabric_minimum_measures + measure_plan
                applied_fabric = True
            elif not ready and not projected_ready:
                removed.extend([m for m in measure_plan if m in ['ashp_installation', 'emitter_upgrades']])
                measure_plan = [m for m in measure_plan if m not in ['ashp_installation', 'emitter_upgrades']]
                removed_hp = True

        return self._dedupe_preserve_order(measure_plan), applied_fabric, removed_hp, hybrid_pathway, removed

    def _dedupe_preserve_order(self, measures: List[str]) -> List[str]:
        seen = set()
        deduped: List[str] = []
        for measure in measures:
            if measure not in seen:
                deduped.append(measure)
                seen.add(measure)
        return deduped

    def _estimate_heat_demand_after_measures(self, baseline: pd.Series, measures: List[str]) -> pd.Series:
        """Roughly estimate post-measure heat demand using multiplicative savings."""

        residual = baseline.copy()
        for measure in measures:
            saving_pct = self.measure_savings.get(measure, {}).get('kwh_saving_pct')
            if saving_pct:
                residual = residual * (1 - saving_pct)

        return residual

    @staticmethod
    def _is_band_at_least(band: str, minimum: str) -> bool:
        """Check whether EPC band meets or exceeds the minimum (A best)."""
        order = ['A', 'B', 'C', 'D', 'E', 'F', 'G']
        band_upper = band.strip().upper() if band else 'G'
        minimum_upper = minimum.strip().upper() if minimum else 'G'

        if band_upper not in order or minimum_upper not in order:
            return False

        return order.index(band_upper) <= order.index(minimum_upper)

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

            elif measure == 'triple_glazing':
                capital_cost += self._cost_triple_glazing(property_data)
                energy_reduction += self._savings_triple_glazing(property_data)

            elif measure == 'floor_insulation':
                capital_cost += self._cost_floor_insulation(property_data)
                energy_reduction += self._savings_floor_insulation(property_data)

            elif measure == 'draught_proofing':
                capital_cost += self._cost_draught_proofing(property_data)
                energy_reduction += self._savings_draught_proofing(property_data)

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

        # Calculate payback period with proper handling of edge cases
        # Handle NaN, zero, and negative savings
        if pd.isna(bill_savings) or pd.isna(capital_cost):
            payback_years = np.inf  # Not calculable
        elif bill_savings <= 0:
            payback_years = np.inf  # Not cost-effective at current prices
        elif capital_cost <= 0:
            payback_years = 0  # No cost = immediate payback
        else:
            payback_years = capital_cost / bill_savings

        return PropertyUpgrade(
            property_id=str(property_data.get('LMK_KEY', 'unknown')),
            scenario=scenario_name,
            capital_cost=capital_cost if not pd.isna(capital_cost) else 0,
            annual_energy_reduction_kwh=energy_reduction if not pd.isna(energy_reduction) else 0,
            annual_co2_reduction_kg=co2_reduction if not pd.isna(co2_reduction) else 0,
            annual_bill_savings=bill_savings if not pd.isna(bill_savings) else 0,
            new_epc_band=new_band,
            payback_years=payback_years
        )

    def _cost_loft_insulation(self, property_data: pd.Series) -> float:
        """Calculate cost of loft insulation top-up."""
        floor_area = property_data.get('TOTAL_FLOOR_AREA', 100)
        # Assume loft area is ~90% of floor area
        loft_area = floor_area * 0.9
        return loft_area * self.costs['loft_insulation_per_m2']

    def _get_absolute_energy(self, property_data: pd.Series) -> float:
        """
        Get absolute energy consumption in kWh/year.
        ENERGY_CONSUMPTION_CURRENT from EPC is in kWh/m²/year, so multiply by floor area.
        """
        energy_intensity = property_data.get('ENERGY_CONSUMPTION_CURRENT', 150)  # kWh/m²/year
        floor_area = property_data.get('TOTAL_FLOOR_AREA', 100)  # m²
        return energy_intensity * floor_area  # kWh/year

    def _savings_loft_insulation(self, property_data: pd.Series) -> float:
        """Calculate energy savings from loft insulation."""
        current_energy = self._get_absolute_energy(property_data)
        saving_pct = self.measure_savings.get('loft_insulation_topup', {}).get('kwh_saving_pct', 0.15)
        return current_energy * saving_pct

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
        current_energy = self._get_absolute_energy(property_data)
        wall_type = property_data.get('wall_type', 'Solid')

        wall_savings = self.measure_savings.get('wall_insulation', {})
        cavity_pct = wall_savings.get('cavity_kwh_saving_pct', 0.20)
        solid_pct = wall_savings.get('solid_kwh_saving_pct', 0.30)

        if wall_type == 'Cavity':
            return current_energy * cavity_pct
        else:
            return current_energy * solid_pct  # Higher savings for solid walls

    def _cost_glazing(self, property_data: pd.Series) -> float:
        """Calculate cost of window glazing upgrade."""
        floor_area = property_data.get('TOTAL_FLOOR_AREA', 100)
        # Assume window area = floor area * 0.2 (simplified)
        window_area = floor_area * 0.2
        return window_area * self.costs['double_glazing_per_m2']

    def _savings_glazing(self, property_data: pd.Series) -> float:
        """Calculate energy savings from window glazing."""
        current_energy = self._get_absolute_energy(property_data)
        saving_pct = self.measure_savings.get('double_glazing', {}).get('kwh_saving_pct', 0.10)
        return current_energy * saving_pct

    def _cost_triple_glazing(self, property_data: pd.Series) -> float:
        """Calculate cost of triple glazing upgrade."""
        return self.costs.get('triple_glazing_upgrade', self.costs.get('double_glazing_upgrade', 0))

    def _savings_triple_glazing(self, property_data: pd.Series) -> float:
        """Calculate energy savings from triple glazing."""
        current_energy = self._get_absolute_energy(property_data)
        saving_pct = self.measure_savings.get('triple_glazing', {}).get('kwh_saving_pct', 0.15)
        return current_energy * saving_pct

    def _cost_floor_insulation(self, property_data: pd.Series) -> float:
        """Calculate cost of suspended timber floor insulation."""
        return self.costs.get('floor_insulation', 0)

    def _savings_floor_insulation(self, property_data: pd.Series) -> float:
        """Calculate savings from insulating suspended timber floors."""
        current_energy = self._get_absolute_energy(property_data)
        saving_pct = self.measure_savings.get('floor_insulation', {}).get('kwh_saving_pct', 0.05)
        return current_energy * saving_pct

    def _cost_draught_proofing(self, property_data: pd.Series) -> float:
        """Calculate cost of draught proofing."""
        return self.costs.get('draught_proofing', 0)

    def _savings_draught_proofing(self, property_data: pd.Series) -> float:
        """Calculate savings from draught proofing."""
        current_energy = self._get_absolute_energy(property_data)
        saving_pct = self.measure_savings.get('draught_proofing', {}).get('kwh_saving_pct', 0.05)
        return current_energy * saving_pct

    def _savings_heat_pump(self, property_data: pd.Series) -> float:
        """Calculate energy savings from heat pump (accounting for COP)."""
        # Heat pumps use electricity instead of gas
        # With SCOP of 3.0, need 1/3 the energy
        # But electricity is ~3.4x more expensive than gas
        # So bill impact is complex - simplified here
        current_heating = self._get_absolute_energy(property_data) * 0.8
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
        current_energy = self._get_absolute_energy(property_data)
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
        current_energy = self._get_absolute_energy(property_data)
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
        property_df: pd.DataFrame,
        df: pd.DataFrame
    ) -> Dict:
        """
        Aggregate individual property upgrades into scenario-level results.

        Args:
            property_df: DataFrame of property-level scenario results
            df: Original property DataFrame

        Returns:
            Aggregated scenario results
        """
        total_properties = len(property_df)

        if total_properties == 0:
            return {}

        numeric_df = property_df.replace({np.inf: np.nan, -np.inf: np.nan})

        # Calculate payback statistics (filter out infinite values)
        # Properties with inf payback are not cost-effective at current prices
        finite_paybacks = numeric_df['payback_years'].dropna()
        reasonable_paybacks = [p for p in finite_paybacks if p < 100]

        if len(reasonable_paybacks) > 0:
            avg_payback = np.mean(reasonable_paybacks)
            median_payback = np.median(reasonable_paybacks)
        else:
            # No cost-effective properties
            avg_payback = np.inf
            median_payback = np.inf

        # Count properties by cost-effectiveness
        n_cost_effective = len(reasonable_paybacks)
        n_not_cost_effective = total_properties - len(finite_paybacks)
        pct_not_cost_effective = (n_not_cost_effective / total_properties * 100) if total_properties > 0 else 0

        results = {
            'total_properties': total_properties,
            'capital_cost_total': float(numeric_df['capital_cost'].sum()),
            'capital_cost_per_property': float(numeric_df['capital_cost'].mean()),
            'annual_energy_reduction_kwh': float(numeric_df['annual_energy_reduction_kwh'].sum()),
            'annual_co2_reduction_kg': float(numeric_df['annual_co2_reduction_kg'].sum()),
            'annual_bill_savings': float(numeric_df['annual_bill_savings'].sum()),
            'baseline_bill_total': float(numeric_df['baseline_bill'].sum()),
            'post_measure_bill_total': float(numeric_df['post_measure_bill'].sum()),
            'baseline_co2_total_kg': float(numeric_df['baseline_co2_kg'].sum()),
            'post_measure_co2_total_kg': float(numeric_df['post_measure_co2_kg'].sum()),
            'average_payback_years': avg_payback if np.isfinite(avg_payback) else None,
            'median_payback_years': median_payback if np.isfinite(median_payback) else None,
            'properties_cost_effective': n_cost_effective,
            'properties_not_cost_effective': n_not_cost_effective,
            'pct_not_cost_effective': pct_not_cost_effective,
        }

        if {'ashp_ready', 'ashp_fabric_needed', 'ashp_not_ready_after_fabric'}.issubset(property_df.columns):
            ready_count = int(property_df['ashp_ready'].sum())
            fabric_count = int(property_df['ashp_fabric_needed'].sum())
            not_ready_count = int(property_df['ashp_not_ready_after_fabric'].sum())
            results.update({
                'ashp_ready_properties': ready_count,
                'ashp_ready_pct': (ready_count / total_properties * 100) if total_properties > 0 else 0,
                'ashp_fabric_required_properties': fabric_count,
                'ashp_not_ready_properties': not_ready_count,
            })

        if 'fabric_inserted_for_hp' in property_df.columns:
            results['ashp_fabric_applied_properties'] = int(property_df['fabric_inserted_for_hp'].sum())

        if 'heat_pump_removed' in property_df.columns:
            results['ashp_not_eligible_properties'] = int(property_df['heat_pump_removed'].sum())

        if 'hn_ready' in property_df.columns:
            results['hn_ready_properties'] = int(property_df['hn_ready'].sum())

        if 'hybrid_pathway' in property_df.columns:
            results['hn_assigned_properties'] = int((property_df['hybrid_pathway'] == 'heat_network').sum())
            results['ashp_assigned_properties'] = int((property_df['hybrid_pathway'] == 'ashp').sum())

        # Log payback summary
        if np.isfinite(avg_payback):
            logger.info(f"  Mean payback (where cost-effective): {avg_payback:.1f} years")
            logger.info(f"  Median payback: {median_payback:.1f} years")
        if pct_not_cost_effective > 0:
            logger.info(f"  Properties not cost-effective at current prices: {pct_not_cost_effective:.1f}%")

        # EPC band shifts
        current_bands = df['CURRENT_ENERGY_RATING'].value_counts().to_dict() if 'CURRENT_ENERGY_RATING' in df.columns else {}
        new_bands = property_df['new_epc_band'].value_counts().to_dict()

        results['epc_band_shifts'] = {
            'before': current_bands,
            'after': new_bands
        }

        # Payback distribution (handle infinite values)
        payback_categories = {
            '0-5 years': len(numeric_df[(numeric_df['payback_years'] <= 5)]),
            '5-10 years': len(numeric_df[(numeric_df['payback_years'] > 5) & (numeric_df['payback_years'] <= 10)]),
            '10-15 years': len(numeric_df[(numeric_df['payback_years'] > 10) & (numeric_df['payback_years'] <= 15)]),
            '15-20 years': len(numeric_df[(numeric_df['payback_years'] > 15) & (numeric_df['payback_years'] <= 20)]),
            '>20 years': len(numeric_df[(numeric_df['payback_years'] > 20)]),
            'Not cost-effective': len(property_df) - len(finite_paybacks)
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
            total_co2_saved = (
                base_results['annual_co2_reduction_kg'] * uptake_rate * self.analysis_horizon_years
            )
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

    def _build_summary_dataframe(self) -> pd.DataFrame:
        rows: List[Dict[str, Any]] = []
        for scenario, results in self.results.items():
            if not isinstance(results, dict):
                continue

            rows.append({
                'scenario': scenario,
                'total_properties': results.get('total_properties'),
                'capital_cost_total': results.get('capital_cost_total'),
                'capital_cost_per_property': results.get('capital_cost_per_property'),
                'annual_energy_reduction_kwh': results.get('annual_energy_reduction_kwh'),
                'annual_co2_reduction_kg': results.get('annual_co2_reduction_kg'),
                'annual_bill_savings': results.get('annual_bill_savings'),
                'baseline_bill_total': results.get('baseline_bill_total'),
                'post_measure_bill_total': results.get('post_measure_bill_total'),
                'baseline_co2_total_kg': results.get('baseline_co2_total_kg'),
                'post_measure_co2_total_kg': results.get('post_measure_co2_total_kg'),
                'average_payback_years': results.get('average_payback_years'),
                'median_payback_years': results.get('median_payback_years'),
                'ashp_ready_properties': results.get('ashp_ready_properties'),
                'ashp_fabric_required_properties': results.get('ashp_fabric_required_properties'),
                'ashp_not_ready_properties': results.get('ashp_not_ready_properties'),
                'ashp_fabric_applied_properties': results.get('ashp_fabric_applied_properties'),
                'ashp_not_eligible_properties': results.get('ashp_not_eligible_properties'),
                'hn_ready_properties': results.get('hn_ready_properties'),
                'hn_assigned_properties': results.get('hn_assigned_properties'),
                'ashp_assigned_properties': results.get('ashp_assigned_properties'),
            })

        return pd.DataFrame(rows)

    def save_results(self, output_path: Optional[Path] = None) -> Dict[str, Optional[Path]]:
        """
        Save scenario modeling results to file.

        Args:
            output_path: Path to save results

        Returns:
            Dictionary of key artefact paths
        """
        if output_path is None:
            output_path = DATA_OUTPUTS_DIR / "scenario_modeling_results.txt"

        with open(output_path, 'w', encoding='utf-8') as f:
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

        summary_path: Optional[Path] = None
        if self.results:
            summary_df = self._build_summary_dataframe()
            summary_path = DATA_OUTPUTS_DIR / "scenario_results_summary.csv"
            summary_df.to_csv(summary_path, index=False)
            logger.info(f"Scenario summary saved to: {summary_path}")

        property_path: Optional[Path] = None
        if self.property_results:
            combined_df = pd.concat(self.property_results.values(), ignore_index=True)
            property_path = DATA_OUTPUTS_DIR / "scenario_results_by_property.parquet"
            combined_df.to_parquet(property_path, index=False)
            logger.info(f"Property-level scenario results saved to: {property_path}")

        return {
            'report_path': output_path,
            'summary_path': summary_path,
            'property_path': property_path,
        }


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
