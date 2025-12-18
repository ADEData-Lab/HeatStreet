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
from src.analysis.methodological_adjustments import MethodologicalAdjustments
from src.spatial.heat_network_analysis import HeatNetworkAnalyzer

BAND_ORDER = ['A', 'B', 'C', 'D', 'E', 'F', 'G']
BAND_THRESHOLD_MAP = {
    'A': 92,
    'B': 81,
    'C': 69,
    'D': 55,
    'E': 39,
    'F': 21,
    'G': 0
}
MAX_EPC_BAND_IMPROVEMENT = 2
SAP_POINTS_PER_PERCENT_SAVING = 0.45
BAND_A_GUARDRAIL_SHARE = 0.10


def _select_baseline_energy_intensity(property_like: Dict[str, Any]) -> float:
    """Pick adjusted energy intensity when available, otherwise EPC value."""
    for key in [
        'energy_consumption_adjusted',
        'energy_consumption_adjusted_central',
        'ENERGY_CONSUMPTION_CURRENT',
    ]:
        val = property_like.get(key)
        if val is not None and not pd.isna(val):
            numeric_val = float(val)
            if numeric_val < 0:
                raise ValueError(f"Negative energy intensity supplied for {key}: {numeric_val}")
            return numeric_val

    return float(property_like.get('ENERGY_CONSUMPTION_CURRENT', 150))


def _select_baseline_annual_kwh(property_like: Dict[str, Any], energy_intensity: float) -> float:
    """Return absolute baseline consumption, prioritising prebound-adjusted columns."""
    for key in [
        'baseline_consumption_kwh_year',
        'baseline_consumption_kwh_year_central',
        'baseline_consumption_kwh_year_low',
        'baseline_consumption_kwh_year_high',
    ]:
        val = property_like.get(key)
        if val is not None and not pd.isna(val):
            return float(val)

    floor_area = property_like.get('TOTAL_FLOOR_AREA', 100)
    if pd.isna(floor_area):
        floor_area = 100

    return float(energy_intensity) * float(floor_area)


def _assert_non_negative_intensities(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure no negative energy intensity values are present before modeling."""
    intensity_cols = [
        'energy_consumption_adjusted',
        'energy_consumption_adjusted_central',
        'ENERGY_CONSUMPTION_CURRENT',
    ]

    present_cols = [col for col in intensity_cols if col in df.columns]
    if not present_cols:
        return df

    negative_counts = {
        col: int((pd.to_numeric(df[col], errors='coerce') < 0).sum())
        for col in present_cols
    }

    total_negatives = sum(negative_counts.values())
    if total_negatives > 0:
        raise ValueError(f"Negative energy intensities found in scenario inputs: {negative_counts}")

    return df


def _rating_to_band_value(rating: float) -> str:
    """Convert a SAP rating to an EPC band using configured thresholds."""
    try:
        numeric_rating = float(rating)
    except (TypeError, ValueError):
        numeric_rating = 0.0

    for band in BAND_ORDER:
        if numeric_rating >= BAND_THRESHOLD_MAP[band]:
            return band

    return 'G'


def _band_upper_bound(band: str) -> float:
    """Return the maximum SAP score allowed within a band (exclusive of next band)."""
    band_clean = str(band).strip().upper()

    if band_clean == 'A':
        return 100.0

    try:
        idx = BAND_ORDER.index(band_clean)
    except ValueError:
        return 100.0

    if idx == 0:
        return 100.0

    prev_band = BAND_ORDER[idx - 1]
    return BAND_THRESHOLD_MAP.get(prev_band, 100.0) - 0.01


def _normalize_band(band: str, fallback_rating: float) -> str:
    """Normalize band text, falling back to SAP-derived band when missing/invalid."""
    band_clean = str(band).strip().upper()
    if band_clean in BAND_ORDER:
        return band_clean

    return _rating_to_band_value(fallback_rating)


def _sap_delta_from_energy_savings(
    baseline_kwh: float,
    post_kwh: float,
    baseline_sap: float
) -> Tuple[float, float]:
    """Estimate SAP delta from sequential energy savings.

    Returns a tuple of (sap_point_gain, saving_pct_basis).
    """
    try:
        baseline_val = float(baseline_kwh)
    except (TypeError, ValueError):
        baseline_val = 0.0

    try:
        post_val = float(post_kwh)
    except (TypeError, ValueError):
        post_val = baseline_val

    if baseline_val <= 0:
        return 0.0, 0.0

    saving_fraction = max(0.0, min(1.0, (baseline_val - post_val) / baseline_val))
    sap_gain = saving_fraction * 100 * SAP_POINTS_PER_PERCENT_SAVING

    sap_headroom = max(0.0, 100 - float(baseline_sap if not pd.isna(baseline_sap) else 0.0))
    return min(sap_gain, sap_headroom), saving_fraction * 100


@dataclass
class PropertyUpgrade:
    """Represents an upgrade to a single property."""
    property_id: str
    scenario: str
    capital_cost: float
    annual_energy_reduction_kwh: float
    annual_co2_reduction_kg: float
    annual_bill_savings: float
    baseline_energy_kwh: float = 0.0
    post_measure_energy_kwh: float = 0.0
    baseline_bill: float = 0.0
    post_measure_bill: float = 0.0
    baseline_co2_kg: float = 0.0
    post_measure_co2_kg: float = 0.0
    new_epc_band: str = ''
    baseline_epc_band: str = ''
    sap_rating_before: float = 0.0
    sap_rating_after: float = 0.0
    sap_rating_delta: float = 0.0
    sap_delta_basis_pct: float = 0.0
    band_shift_steps: int = 0
    band_shift_capped: bool = False
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
    estimated_flow_temp_c: float = np.nan
    operating_flow_temp_c: float = np.nan
    heat_pump_cop_central: float = np.nan
    heat_pump_cop_low: float = np.nan
    heat_pump_cop_high: float = np.nan
    heat_pump_electricity_kwh: float = 0.0
    heat_pump_electricity_kwh_low: float = 0.0
    heat_pump_electricity_kwh_high: float = 0.0
    annual_bill_savings_low: float = 0.0
    annual_bill_savings_high: float = 0.0
    post_measure_bill_low: float = 0.0
    post_measure_bill_high: float = 0.0
    post_measure_co2_kg_low: float = 0.0
    post_measure_co2_kg_high: float = 0.0


def _calculate_property_upgrade_worker(args):
    """Worker wrapper to enable parallel execution in ProcessPool."""
    return _calculate_property_upgrade_core(*args)


def _calculate_property_upgrade_core(
    property_dict: Dict[str, Any],
    scenario_name: str,
    measures: List[str],
    costs: Dict[str, Any],
    config: Dict[str, Any],
    applied_fabric: bool,
    removed_hp: bool,
    hybrid_pathway: Optional[str],
    removed_measures: List[str],
) -> PropertyUpgrade:
    """Calculate upgrade metrics for a single property using configured COP curves."""
    energy_prices = config.get('energy_prices', {}).get('current', {})
    gas_price = energy_prices.get('gas', 0.0)
    elec_price = energy_prices.get('electricity', 0.0)

    carbon_factors = config.get('carbon_factors', {}).get('current', {})
    gas_carbon = carbon_factors.get('gas', 0.0)
    elec_carbon = carbon_factors.get('electricity', 0.0)

    measure_savings = config.get('measure_savings', {})
    hp_cfg = config.get('heat_pump', {})
    heating_fraction = float(hp_cfg.get('heating_demand_fraction', 0.8))
    design_flow_temps = hp_cfg.get('design_flow_temps', [])

    adjuster = getattr(_calculate_property_upgrade_core, "_adjuster", None)
    if adjuster is None:
        adjuster = MethodologicalAdjustments()
        setattr(_calculate_property_upgrade_core, "_adjuster", adjuster)

    def _flow_temp_reduction(measure_name: str) -> float:
        lookup = 'radiator_upsizing' if measure_name == 'emitter_upgrades' else measure_name
        return float(measure_savings.get(lookup, {}).get('flow_temp_reduction_k', 0) or 0)

    def _measure_saving(measure_name: str, wall_type: str, baseline_kwh: float) -> float:
        cfg = measure_savings.get(measure_name, {})

        if measure_name == 'wall_insulation':
            pct = cfg.get('cavity_kwh_saving_pct', 0.20) if wall_type == 'Cavity' else cfg.get('solid_kwh_saving_pct', 0.30)
            return baseline_kwh * pct

        pct = cfg.get('kwh_saving_pct')
        if pct is not None:
            return baseline_kwh * pct

        if measure_name == 'district_heating_connection':
            return baseline_kwh * 0.15

        return 0.0

    floor_area = property_dict.get('TOTAL_FLOOR_AREA', 100)
    baseline_intensity = _select_baseline_energy_intensity(property_dict)
    baseline_kwh = _select_baseline_annual_kwh(property_dict, baseline_intensity)
    wall_type = property_dict.get('wall_type', 'Solid')
    current_rating = property_dict.get('CURRENT_ENERGY_EFFICIENCY', 50)

    try:
        current_rating = float(current_rating)
        if pd.isna(current_rating):
            current_rating = 0.0
    except (TypeError, ValueError):
        current_rating = 0.0

    baseline_flow_temp = property_dict.get('estimated_flow_temp')
    if baseline_flow_temp is None or pd.isna(baseline_flow_temp):
        estimated = adjuster.estimate_flow_temperature(pd.DataFrame([property_dict]))
        baseline_flow_temp = float(estimated['estimated_flow_temp'].iloc[0]) if 'estimated_flow_temp' in estimated else float(adjuster.min_flow_temp)

    min_flow_temp = float(min(design_flow_temps)) if design_flow_temps else adjuster.min_flow_temp

    capital_cost = 0.0
    fabric_savings = 0.0
    district_savings = 0.0
    flow_temp_reduction = 0.0
    uses_heat_pump = False

    # Calculate costs and impacts for each measure
    for measure in measures:
        if measure == 'loft_insulation_topup':
            loft_area = floor_area * 0.9
            capital_cost += loft_area * costs.get('loft_insulation_per_m2', 0)
            fabric_savings += _measure_saving(measure, wall_type, baseline_kwh)
            flow_temp_reduction += _flow_temp_reduction(measure)

        elif measure == 'wall_insulation':
            if wall_type == 'Cavity':
                capital_cost += costs.get('cavity_wall_insulation', 0)
            else:
                wall_area_calc = floor_area * 1.5
                capital_cost += wall_area_calc * costs.get('internal_wall_insulation_per_m2', 0)
            fabric_savings += _measure_saving(measure, wall_type, baseline_kwh)
            flow_temp_reduction += _flow_temp_reduction(measure)

        elif measure == 'double_glazing':
            window_area = floor_area * 0.2
            capital_cost += window_area * costs.get('double_glazing_per_m2', 0)
            fabric_savings += _measure_saving(measure, wall_type, baseline_kwh)
            flow_temp_reduction += _flow_temp_reduction(measure)

        elif measure == 'triple_glazing':
            window_area = floor_area * 0.2
            capital_cost += costs.get('triple_glazing_upgrade', window_area * costs.get('double_glazing_per_m2', 0))
            fabric_savings += _measure_saving(measure, wall_type, baseline_kwh)
            flow_temp_reduction += _flow_temp_reduction(measure)

        elif measure == 'floor_insulation':
            capital_cost += costs.get('floor_insulation', 0)
            fabric_savings += _measure_saving(measure, wall_type, baseline_kwh)
            flow_temp_reduction += _flow_temp_reduction(measure)

        elif measure == 'draught_proofing':
            capital_cost += costs.get('draught_proofing', 0)
            fabric_savings += _measure_saving(measure, wall_type, baseline_kwh)
            flow_temp_reduction += _flow_temp_reduction(measure)

        elif measure == 'ashp_installation':
            capital_cost += costs.get('ashp_installation', 0)
            uses_heat_pump = True

        elif measure == 'emitter_upgrades':
            num_radiators = int(floor_area / 15)
            capital_cost += num_radiators * costs.get('emitter_upgrade_per_radiator', 0)
            flow_temp_reduction += _flow_temp_reduction(measure)

        elif measure == 'district_heating_connection':
            capital_cost += costs.get('district_heating_connection', 0)
            district_savings += _measure_saving(measure, wall_type, baseline_kwh)

        elif measure in ['fabric_improvements', 'modest_fabric_improvements']:
            loft_area = floor_area * 0.9
            capital_cost += loft_area * costs.get('loft_insulation_per_m2', 0)
            if wall_type == 'Cavity':
                capital_cost += costs.get('cavity_wall_insulation', 0)
            else:
                wall_area_calc = floor_area * 1.5
                capital_cost += wall_area_calc * costs.get('internal_wall_insulation_per_m2', 0)
            window_area = floor_area * 0.2
            capital_cost += window_area * costs.get('double_glazing_per_m2', 0)
            fabric_savings += baseline_kwh * 0.40
            flow_temp_reduction += sum(
                _flow_temp_reduction(x) for x in ['loft_insulation_topup', 'wall_insulation', 'double_glazing']
            )

    fabric_savings = min(fabric_savings, baseline_kwh)
    energy_after_fabric = max(baseline_kwh - fabric_savings, 0)
    district_savings = min(district_savings, energy_after_fabric)
    energy_after_non_hp = max(energy_after_fabric - district_savings, 0)

    baseline_bill = baseline_kwh * gas_price
    baseline_co2 = baseline_kwh * gas_carbon

    operating_flow_temp = max(min_flow_temp, float(baseline_flow_temp) - flow_temp_reduction)

    if uses_heat_pump:
        cop = adjuster.derive_heat_pump_cop(operating_flow_temp, include_bounds=True)
        central_cop = cop.get('central') or 1e-6
        low_cop = cop.get('low') or central_cop
        high_cop = cop.get('high') or central_cop

        heating_after_fabric = energy_after_fabric * heating_fraction
        non_heating_energy = max(energy_after_fabric - heating_after_fabric, 0)

        hp_electricity = heating_after_fabric / central_cop if central_cop > 0 else heating_after_fabric
        hp_electricity_low = heating_after_fabric / low_cop if low_cop > 0 else heating_after_fabric
        hp_electricity_high = heating_after_fabric / high_cop if high_cop > 0 else heating_after_fabric

        post_energy_central = non_heating_energy + hp_electricity
        post_energy_low = non_heating_energy + hp_electricity_low
        post_energy_high = non_heating_energy + hp_electricity_high

        post_measure_bill = non_heating_energy * gas_price + hp_electricity * elec_price
        post_measure_bill_low = non_heating_energy * gas_price + hp_electricity_low * elec_price
        post_measure_bill_high = non_heating_energy * gas_price + hp_electricity_high * elec_price

        bill_savings = baseline_bill - post_measure_bill
        bill_savings_low = baseline_bill - post_measure_bill_low
        bill_savings_high = baseline_bill - post_measure_bill_high

        post_measure_co2 = non_heating_energy * gas_carbon + hp_electricity * elec_carbon
        post_measure_co2_low = non_heating_energy * gas_carbon + hp_electricity_low * elec_carbon
        post_measure_co2_high = non_heating_energy * gas_carbon + hp_electricity_high * elec_carbon

        energy_reduction = baseline_kwh - post_energy_central
        post_energy_use = post_energy_central
        co2_reduction = baseline_co2 - post_measure_co2

    else:
        post_measure_bill = energy_after_non_hp * gas_price
        post_measure_bill_low = post_measure_bill_high = post_measure_bill
        bill_savings = baseline_bill - post_measure_bill
        bill_savings_low = bill_savings_high = bill_savings

        post_measure_co2 = energy_after_non_hp * gas_carbon
        post_measure_co2_low = post_measure_co2_high = post_measure_co2
        co2_reduction = baseline_co2 - post_measure_co2

        energy_reduction = baseline_kwh - energy_after_non_hp
        post_energy_use = energy_after_non_hp
        hp_electricity = hp_electricity_low = hp_electricity_high = 0.0
        central_cop = low_cop = high_cop = np.nan

    energy_reduction = float(energy_reduction)
    capital_cost = float(capital_cost)

    sap_delta, sap_delta_basis_pct = _sap_delta_from_energy_savings(
        baseline_kwh,
        post_energy_use,
        current_rating
    )

    sap_rating_after = min(100.0, current_rating + sap_delta)

    baseline_band = _normalize_band(property_dict.get('CURRENT_ENERGY_RATING', ''), current_rating)
    estimated_band = _rating_to_band_value(sap_rating_after)

    baseline_idx = BAND_ORDER.index(baseline_band)
    estimated_idx = BAND_ORDER.index(estimated_band)
    band_shift_steps = max(0, baseline_idx - estimated_idx)
    band_shift_capped = band_shift_steps > MAX_EPC_BAND_IMPROVEMENT

    if band_shift_capped:
        capped_idx = max(0, baseline_idx - MAX_EPC_BAND_IMPROVEMENT)
        new_band = BAND_ORDER[capped_idx]
        sap_rating_after = min(sap_rating_after, _band_upper_bound(new_band))
        band_shift_steps = baseline_idx - capped_idx
    else:
        new_band = estimated_band

    sap_rating_delta = sap_rating_after - current_rating

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
        baseline_energy_kwh=baseline_kwh if not pd.isna(baseline_kwh) else 0,
        post_measure_energy_kwh=post_energy_use if not pd.isna(post_energy_use) else 0,
        baseline_bill=baseline_bill if not pd.isna(baseline_bill) else 0,
        post_measure_bill=post_measure_bill if not pd.isna(post_measure_bill) else 0,
        baseline_co2_kg=baseline_co2 if not pd.isna(baseline_co2) else 0,
        post_measure_co2_kg=post_measure_co2 if not pd.isna(post_measure_co2) else 0,
        new_epc_band=new_band,
        baseline_epc_band=baseline_band,
        sap_rating_before=current_rating,
        sap_rating_after=sap_rating_after,
        sap_rating_delta=sap_rating_delta,
        sap_delta_basis_pct=sap_delta_basis_pct,
        band_shift_steps=band_shift_steps,
        band_shift_capped=band_shift_capped,
        payback_years=payback_years,
        estimated_flow_temp_c=float(baseline_flow_temp) if not pd.isna(baseline_flow_temp) else np.nan,
        operating_flow_temp_c=operating_flow_temp,
        heat_pump_cop_central=central_cop,
        heat_pump_cop_low=low_cop,
        heat_pump_cop_high=high_cop,
        heat_pump_electricity_kwh=hp_electricity,
        heat_pump_electricity_kwh_low=hp_electricity_low,
        heat_pump_electricity_kwh_high=hp_electricity_high,
        annual_bill_savings_low=bill_savings_low if not pd.isna(bill_savings_low) else 0,
        annual_bill_savings_high=bill_savings_high if not pd.isna(bill_savings_high) else 0,
        post_measure_bill_low=post_measure_bill_low if not pd.isna(post_measure_bill_low) else 0,
        post_measure_bill_high=post_measure_bill_high if not pd.isna(post_measure_bill_high) else 0,
        post_measure_co2_kg_low=post_measure_co2_low if not pd.isna(post_measure_co2_low) else 0,
        post_measure_co2_kg_high=post_measure_co2_high if not pd.isna(post_measure_co2_high) else 0,
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

        self.adjuster = MethodologicalAdjustments()
        self.heating_fraction = float(self.config.get('heat_pump', {}).get('heating_demand_fraction', 0.8))
        self.min_flow_temp = float(min(self.config.get('heat_pump', {}).get('design_flow_temps', [self.adjuster.min_flow_temp])))

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

    def _ensure_adjusted_baseline(self, df: pd.DataFrame) -> pd.DataFrame:
        """Guarantee prebound-adjusted baseline columns before modeling."""
        if 'energy_consumption_adjusted' in df.columns or 'energy_consumption_adjusted_central' in df.columns:
            return _assert_non_negative_intensities(df)

        logger.info("Applying prebound adjustment to supply adjusted baseline for scenario modeling...")
        adjusted = self.adjuster.apply_prebound_adjustment(df)
        return _assert_non_negative_intensities(adjusted)

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

        df_baseline = self._ensure_adjusted_baseline(df)
        df_with_flags = self._preprocess_ashp_readiness(df_baseline)

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

        df_ready = self._ensure_adjusted_baseline(df)

        if not measures:
            # Baseline scenario - no interventions
            return self._model_baseline(df_ready)

        df_with_flags = self._preprocess_ashp_readiness(df_ready)

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

        if 'baseline_consumption_kwh_year' in df.columns:
            total_energy = df['baseline_consumption_kwh_year'].sum()
        else:
            intensity_series = (
                df['energy_consumption_adjusted']
                if 'energy_consumption_adjusted' in df.columns
                else df['energy_consumption_adjusted_central']
                if 'energy_consumption_adjusted_central' in df.columns
                else df['ENERGY_CONSUMPTION_CURRENT']
                if 'ENERGY_CONSUMPTION_CURRENT' in df.columns
                else pd.Series(0, index=df.index)
            )
            floor_area_series = (
                df['TOTAL_FLOOR_AREA'] if 'TOTAL_FLOOR_AREA' in df.columns else pd.Series(0, index=df.index)
            )
            total_energy = (intensity_series.fillna(0) * floor_area_series.fillna(0)).sum()

        gas_carbon_factor = self.carbon_factors.get('current', {}).get('gas', 0)
        total_co2_kg = float(total_energy) * gas_carbon_factor

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

        processed = df.copy()
        processed = self.adjuster.estimate_flow_temperature(processed)
        processed = self.adjuster.attach_cop_estimates(processed)

        if 'ashp_ready' in df.columns:
            return processed

        heat_demand = None
        for col in ['energy_consumption_adjusted', 'energy_consumption_adjusted_central', 'ENERGY_CONSUMPTION_CURRENT']:
            if col in processed.columns:
                heat_demand = processed[col]
                break

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
        return _calculate_property_upgrade_core(
            property_data.to_dict(),
            scenario_name,
            measures,
            self.costs,
            self.config,
            False,
            False,
            None,
            [],
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
        Prioritises prebound-adjusted intensities when available.
        """
        energy_intensity = _select_baseline_energy_intensity(property_data)
        return _select_baseline_annual_kwh(property_data, energy_intensity)

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
        return _rating_to_band_value(rating)

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

        if {'baseline_energy_kwh', 'post_measure_energy_kwh'}.issubset(numeric_df.columns):
            results['baseline_annual_energy_kwh'] = float(numeric_df['baseline_energy_kwh'].sum())
            results['post_measure_energy_kwh'] = float(numeric_df['post_measure_energy_kwh'].sum())

            with np.errstate(divide='ignore', invalid='ignore'):
                reduction_pct = np.where(
                    numeric_df['baseline_energy_kwh'] > 0,
                    numeric_df['annual_energy_reduction_kwh'] / numeric_df['baseline_energy_kwh'],
                    np.nan
                )

            reduction_pct_series = pd.Series(reduction_pct).replace([np.inf, -np.inf], np.nan).dropna()
            if not reduction_pct_series.empty:
                results['mean_energy_reduction_pct'] = float(reduction_pct_series.mean() * 100)
                results['median_energy_reduction_pct'] = float(reduction_pct_series.median() * 100)

        if {'sap_rating_delta', 'sap_rating_before', 'sap_rating_after', 'sap_delta_basis_pct'}.issubset(numeric_df.columns):
            sap_delta_series = numeric_df['sap_rating_delta'].dropna()
            results['sap_rating_delta_total'] = float(sap_delta_series.sum())
            results['sap_rating_delta_mean'] = float(sap_delta_series.mean()) if not sap_delta_series.empty else 0.0
            results['sap_rating_delta_median'] = float(sap_delta_series.median()) if not sap_delta_series.empty else 0.0

            basis_series = numeric_df['sap_delta_basis_pct'].replace([np.inf, -np.inf], np.nan).dropna()
            if not basis_series.empty:
                results['sap_delta_basis_pct_mean'] = float(basis_series.mean())
                results['sap_delta_basis_pct_median'] = float(basis_series.median())

        optional_sums = {
            'annual_bill_savings_low': 'annual_bill_savings_low',
            'annual_bill_savings_high': 'annual_bill_savings_high',
            'post_measure_bill_total_low': 'post_measure_bill_low',
            'post_measure_bill_total_high': 'post_measure_bill_high',
            'post_measure_co2_total_kg_low': 'post_measure_co2_kg_low',
            'post_measure_co2_total_kg_high': 'post_measure_co2_kg_high',
            'heat_pump_electricity_total_kwh': 'heat_pump_electricity_kwh',
            'heat_pump_electricity_total_kwh_low': 'heat_pump_electricity_kwh_low',
            'heat_pump_electricity_total_kwh_high': 'heat_pump_electricity_kwh_high',
        }

        for result_key, col in optional_sums.items():
            if col in numeric_df.columns:
                results[result_key] = float(numeric_df[col].sum())

        if 'band_shift_capped' in property_df.columns:
            capped_count = int(property_df['band_shift_capped'].sum())
            results['epc_band_shift_cap_applied_properties'] = capped_count
            results['epc_band_max_improvement'] = MAX_EPC_BAND_IMPROVEMENT

        if 'band_shift_steps' in property_df.columns:
            results['epc_band_shift_mean_steps'] = float(property_df['band_shift_steps'].mean())

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

        band_a_before = current_bands.get('A', 0)
        band_a_after = new_bands.get('A', 0)
        band_a_guardrail = band_a_before + int(total_properties * BAND_A_GUARDRAIL_SHARE)
        band_a_guardrail_hard_limit = band_a_before + int(total_properties * BAND_A_GUARDRAIL_SHARE * 2)
        band_a_warning = band_a_after > band_a_guardrail

        if band_a_warning:
            logger.warning(
                f"Band A count exceeds guardrail (before={band_a_before}, after={band_a_after}, guardrail={band_a_guardrail})"
            )

        assert band_a_after <= band_a_guardrail_hard_limit, (
            "Unrealistic migration to EPC band A detected after capping; "
            "review SAP delta assumptions."
        )

        results['epc_band_shifts'] = {
            'before': current_bands,
            'after': new_bands,
            'max_band_improvement': MAX_EPC_BAND_IMPROVEMENT,
            'band_shift_cap_properties': int(property_df['band_shift_capped'].sum()) if 'band_shift_capped' in property_df.columns else 0,
            'band_a_warning': band_a_warning,
            'band_a_guardrail': band_a_guardrail
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
                'annual_bill_savings_low': results.get('annual_bill_savings_low'),
                'annual_bill_savings_high': results.get('annual_bill_savings_high'),
                'baseline_bill_total': results.get('baseline_bill_total'),
                'post_measure_bill_total': results.get('post_measure_bill_total'),
                'post_measure_bill_total_low': results.get('post_measure_bill_total_low'),
                'post_measure_bill_total_high': results.get('post_measure_bill_total_high'),
                'baseline_co2_total_kg': results.get('baseline_co2_total_kg'),
                'post_measure_co2_total_kg': results.get('post_measure_co2_total_kg'),
                'post_measure_co2_total_kg_low': results.get('post_measure_co2_total_kg_low'),
                'post_measure_co2_total_kg_high': results.get('post_measure_co2_total_kg_high'),
                'heat_pump_electricity_total_kwh': results.get('heat_pump_electricity_total_kwh'),
                'heat_pump_electricity_total_kwh_low': results.get('heat_pump_electricity_total_kwh_low'),
                'heat_pump_electricity_total_kwh_high': results.get('heat_pump_electricity_total_kwh_high'),
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
