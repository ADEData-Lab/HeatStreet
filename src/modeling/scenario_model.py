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
import gc
import time

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import (
    load_config,
    get_scenario_definitions,
    get_cost_assumptions,
    get_cost_rules,
    get_analysis_horizon_years,
    get_cost_effectiveness_params,
    get_eligibility_params,
    get_measure_savings,
    DATA_PROCESSED_DIR,
    DATA_OUTPUTS_DIR
)
from src.analysis.fabric_tipping_point import FabricTippingPointAnalyzer
from src.analysis.methodological_adjustments import MethodologicalAdjustments
try:
    from src.spatial.heat_network_analysis import HeatNetworkAnalyzer
except Exception as _:
    HeatNetworkAnalyzer = None
from src.modeling.costing import CostCalculator
from src.utils.modeling_utils import (
    BAND_ORDER,
    BAND_THRESHOLD_MAP,
    MAX_EPC_BAND_IMPROVEMENT,
    SAP_POINTS_PER_PERCENT_SAVING,
    BAND_A_GUARDRAIL_SHARE,
    select_baseline_energy_intensity,
    select_baseline_annual_kwh,
    assert_non_negative_intensities,
    rating_to_band,
    band_upper_bound,
    normalize_band,
    is_band_at_least,
    calculate_sap_delta_from_energy_savings,
    calculate_epc_band_distribution,
    calculate_band_shift_summary,
    is_hp_ready,
    min_fabric_measures_for_hp,
    is_upgrade_recommended,
    calculate_carbon_abatement_cost,
    calculate_cost_effectiveness_summary,
    summarize_series,
)
from src.utils.profiling import (
    profile_enabled, log_memory, log_dataframe_info,
    get_worker_count, get_chunk_size
)


# Legacy wrapper functions (now delegating to shared utils for backwards compatibility)
def _select_baseline_energy_intensity(property_like: Dict[str, Any]) -> float:
    """Pick adjusted energy intensity when available, otherwise EPC value."""
    return select_baseline_energy_intensity(property_like)


def _select_baseline_annual_kwh(property_like: Dict[str, Any], energy_intensity: float) -> float:
    """Return absolute baseline consumption, prioritising prebound-adjusted columns."""
    return select_baseline_annual_kwh(property_like, energy_intensity)


def _assert_non_negative_intensities(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure no negative energy intensity values are present before modeling."""
    return assert_non_negative_intensities(df)


def _rating_to_band_value(rating: float) -> str:
    """Convert a SAP rating to an EPC band using configured thresholds."""
    return rating_to_band(rating)


def _band_upper_bound(band: str) -> float:
    """Return the maximum SAP score allowed within a band (exclusive of next band)."""
    return band_upper_bound(band)


def _normalize_band(band: str, fallback_rating: float) -> str:
    """Normalize band text, falling back to SAP-derived band when missing/invalid."""
    return normalize_band(band, fallback_rating)


def _sap_delta_from_energy_savings(
    baseline_kwh: float,
    post_kwh: float,
    baseline_sap: float
) -> Tuple[float, float]:
    """Estimate SAP delta from sequential energy savings."""
    return calculate_sap_delta_from_energy_savings(baseline_kwh, post_kwh, baseline_sap)


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
    costing_basis: str = ''
    costing_cap_applied: bool = False
    costing_notes: str = ''
    # Cost-effectiveness fields
    upgrade_recommended: bool = False
    carbon_abatement_cost: float = np.inf
    discounted_payback_years: float = np.inf


# Global state for worker processes (set by initializer)
_WORKER_COSTS = None
_WORKER_COST_RULES = None
_WORKER_CONFIG = None
_WORKER_ADJUSTER = None


def _worker_initializer(costs, cost_rules, config):
    """
    Initialize shared objects once per worker process.

    This avoids repeated pickling of large config objects and reduces memory usage.
    Called once when each worker process starts.
    """
    global _WORKER_COSTS, _WORKER_COST_RULES, _WORKER_CONFIG, _WORKER_ADJUSTER
    _WORKER_COSTS = costs
    _WORKER_COST_RULES = cost_rules
    _WORKER_CONFIG = config
    _WORKER_ADJUSTER = MethodologicalAdjustments()


def _calculate_property_upgrade_worker(args):
    """Worker wrapper to enable parallel execution in ProcessPool."""
    # Use global shared state if available (set by initializer)
    if _WORKER_COSTS is not None:
        # Unpack only property-specific args (costs/config from globals)
        (property_dict, scenario_name, measures, applied_fabric,
         removed_hp, hybrid_pathway, removed_measures) = args
        return _calculate_property_upgrade_core(
            property_dict, scenario_name, measures,
            _WORKER_COSTS, _WORKER_COST_RULES, _WORKER_CONFIG,
            applied_fabric, removed_hp, hybrid_pathway, removed_measures
        )
    else:
        # Fallback to full args (backwards compatibility)
        return _calculate_property_upgrade_core(*args)


def _calculate_property_upgrade_core(
    property_dict: Dict[str, Any],
    scenario_name: str,
    measures: List[str],
    costs: Dict[str, Any],
    cost_rules: Dict[str, Any],
    config: Dict[str, Any],
    applied_fabric: bool,
    removed_hp: bool,
    hybrid_pathway: Optional[str],
    removed_measures: List[str],
) -> PropertyUpgrade:
    """Calculate upgrade metrics for a single property using configured COP curves."""
    energy_prices = config.get('energy_prices', {}).get('current', {})
    heat_network_cfg = config.get('heat_network', {})
    gas_price = energy_prices.get('gas', 0.0)
    elec_price = energy_prices.get('electricity', 0.0)
    hn_tariff = heat_network_cfg.get('tariff_per_kwh', energy_prices.get('heat_network', 0.08))
    hn_efficiency = heat_network_cfg.get('distribution_efficiency', 1.0) or 1.0

    carbon_factors = config.get('carbon_factors', {}).get('current', {})
    gas_carbon = carbon_factors.get('gas', 0.0)
    elec_carbon = carbon_factors.get('electricity', 0.0)
    hn_carbon = heat_network_cfg.get('carbon_intensity_kg_per_kwh', carbon_factors.get('heat_network', gas_carbon * 0.4))

    measure_savings = config.get('measure_savings', {})
    hp_cfg = config.get('heat_pump', {})
    heating_fraction = float(hp_cfg.get('heating_demand_fraction', 0.8))
    design_flow_temps = hp_cfg.get('design_flow_temps', [])
    cost_calculator = CostCalculator(costs, cost_rules)

    # Use adjuster from initializer globals if available (avoids repeated creation)
    adjuster = _WORKER_ADJUSTER
    if adjuster is None:
        # Fallback: cache on function for non-initializer usage
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
    uses_heat_network = False
    flow_temp_reduction = 0.0
    uses_heat_pump = False
    cost_notes: List[str] = []
    cost_sources: List[str] = []
    capped_costs = 0

    def _apply_cost(measure_name: str, display_name: Optional[str] = None) -> None:
        nonlocal capital_cost, capped_costs
        cost, detail = cost_calculator.measure_cost(measure_name, property_dict)
        capital_cost += cost
        if detail.get('cap_applied'):
            capped_costs += 1
        cost_sources.append(detail.get('source', ''))
        basis = detail.get('basis', 'fixed')
        label = display_name or measure_name
        suffix = " (cap)" if detail.get('cap_applied') else ""
        cost_notes.append(f"{label}:{basis}{suffix}")

    # Calculate costs and impacts for each measure
    for measure in measures:
        if measure == 'loft_insulation_topup':
            _apply_cost('loft_insulation_topup', 'loft')
            fabric_savings += _measure_saving(measure, wall_type, baseline_kwh)
            flow_temp_reduction += _flow_temp_reduction(measure)

        elif measure == 'wall_insulation':
            if wall_type == 'Cavity':
                _apply_cost('wall_insulation_cavity', 'cavity_wall')
            else:
                _apply_cost('wall_insulation_internal', 'solid_wall')
            fabric_savings += _measure_saving(measure, wall_type, baseline_kwh)
            flow_temp_reduction += _flow_temp_reduction(measure)

        elif measure == 'double_glazing':
            _apply_cost('double_glazing')
            fabric_savings += _measure_saving(measure, wall_type, baseline_kwh)
            flow_temp_reduction += _flow_temp_reduction(measure)

        elif measure == 'triple_glazing':
            _apply_cost('triple_glazing')
            fabric_savings += _measure_saving(measure, wall_type, baseline_kwh)
            flow_temp_reduction += _flow_temp_reduction(measure)

        elif measure == 'floor_insulation':
            _apply_cost('floor_insulation')
            fabric_savings += _measure_saving(measure, wall_type, baseline_kwh)
            flow_temp_reduction += _flow_temp_reduction(measure)

        elif measure == 'draught_proofing':
            _apply_cost('draught_proofing')
            fabric_savings += _measure_saving(measure, wall_type, baseline_kwh)
            flow_temp_reduction += _flow_temp_reduction(measure)

        elif measure == 'ashp_installation':
            _apply_cost('ashp_installation')
            uses_heat_pump = True

        elif measure == 'emitter_upgrades':
            _apply_cost('emitter_upgrades')
            flow_temp_reduction += _flow_temp_reduction(measure)

        elif measure == 'district_heating_connection':
            _apply_cost('district_heating_connection')
            uses_heat_network = True

        elif measure in ['fabric_improvements', 'modest_fabric_improvements']:
            _apply_cost('loft_insulation_topup', 'loft')
            if wall_type == 'Cavity':
                _apply_cost('wall_insulation_cavity', 'cavity_wall')
            else:
                _apply_cost('wall_insulation_internal', 'solid_wall')
            _apply_cost('double_glazing')
            fabric_savings += baseline_kwh * 0.40
            flow_temp_reduction += sum(
                _flow_temp_reduction(x) for x in ['loft_insulation_topup', 'wall_insulation', 'double_glazing']
            )

    fabric_savings = min(fabric_savings, baseline_kwh)

    # AUDIT FIX: Apply rebound effect to fabric savings
    # Homes that were under-heated before retrofit may "take back" some savings
    # as improved comfort rather than energy reduction.
    # The rebound_factor (0.55-1.0) represents fraction of savings realized.
    rebound_factor = property_dict.get('rebound_factor', 1.0)
    if rebound_factor is None or pd.isna(rebound_factor):
        rebound_factor = 1.0
    rebound_factor = float(rebound_factor)

    # Only apply rebound to fabric savings (comfort-taking applies to heating)
    fabric_savings_adjusted = fabric_savings * rebound_factor
    energy_after_fabric = max(baseline_kwh - fabric_savings_adjusted, 0)

    baseline_bill = baseline_kwh * gas_price
    baseline_co2 = baseline_kwh * gas_carbon

    operating_flow_temp = max(min_flow_temp, float(baseline_flow_temp) - flow_temp_reduction)

    if uses_heat_network and uses_heat_pump:
        logger.warning(
            "Both ASHP and heat network specified; prioritising heat network to avoid double counting."
        )
        uses_heat_pump = False

    if uses_heat_network:
        heating_after_fabric = energy_after_fabric * heating_fraction
        non_heating_energy = max(energy_after_fabric - heating_after_fabric, 0)

        hn_input_energy = heating_after_fabric / hn_efficiency if hn_efficiency > 0 else heating_after_fabric
        post_energy_use = non_heating_energy + heating_after_fabric

        post_measure_bill = non_heating_energy * gas_price + hn_input_energy * hn_tariff
        post_measure_bill_low = post_measure_bill_high = post_measure_bill
        bill_savings = baseline_bill - post_measure_bill
        bill_savings_low = bill_savings_high = bill_savings

        post_measure_co2 = non_heating_energy * gas_carbon + hn_input_energy * hn_carbon
        post_measure_co2_low = post_measure_co2_high = post_measure_co2
        co2_reduction = baseline_co2 - post_measure_co2

        energy_reduction = baseline_kwh - post_energy_use
        hp_electricity = hp_electricity_low = hp_electricity_high = 0.0
        central_cop = low_cop = high_cop = np.nan

    elif uses_heat_pump:
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
        post_measure_bill = energy_after_fabric * gas_price
        post_measure_bill_low = post_measure_bill_high = post_measure_bill
        bill_savings = baseline_bill - post_measure_bill
        bill_savings_low = bill_savings_high = bill_savings

        post_measure_co2 = energy_after_fabric * gas_carbon
        post_measure_co2_low = post_measure_co2_high = post_measure_co2
        co2_reduction = baseline_co2 - post_measure_co2

        energy_reduction = baseline_kwh - energy_after_fabric
        post_energy_use = energy_after_fabric
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

    # Calculate cost-effectiveness metrics
    cost_effectiveness_cfg = config.get('financial', {}).get('cost_effectiveness', {})
    max_payback_threshold = cost_effectiveness_cfg.get('max_payback_years', 20)
    analysis_horizon = config.get('financial', {}).get('analysis_horizon_years', 20)
    discount_rate = config.get('financial', {}).get('discount_rate', 0.035)

    # Calculate carbon abatement cost (£/tCO2 over analysis horizon)
    if co2_reduction > 0 and analysis_horizon > 0:
        total_co2_tonnes = (co2_reduction * analysis_horizon) / 1000
        carbon_abatement_cost_val = capital_cost / total_co2_tonnes if total_co2_tonnes > 0 else np.inf
    else:
        carbon_abatement_cost_val = np.inf

    # Calculate discounted payback
    if bill_savings > 0 and capital_cost > 0:
        cumulative = 0.0
        discounted_payback_years_val = np.inf
        for year in range(1, 51):
            discounted = bill_savings / ((1 + discount_rate) ** year)
            cumulative += discounted
            if cumulative >= capital_cost:
                discounted_payback_years_val = float(year)
                break
    else:
        discounted_payback_years_val = np.inf

    # Determine if upgrade is recommended
    upgrade_recommended_val = is_upgrade_recommended(
        payback_years,
        max_payback_threshold=max_payback_threshold
    )

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
        costing_basis=','.join(sorted({src for src in cost_sources if src})),
        costing_cap_applied=capped_costs > 0,
        costing_notes='; '.join(cost_notes),
        # Cost-effectiveness fields
        upgrade_recommended=upgrade_recommended_val,
        carbon_abatement_cost=carbon_abatement_cost_val if np.isfinite(carbon_abatement_cost_val) else np.inf,
        discounted_payback_years=discounted_payback_years_val if np.isfinite(discounted_payback_years_val) else np.inf,
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
        self.cost_rules = get_cost_rules()
        self.cost_calculator = CostCalculator(self.costs, self.cost_rules)
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
        self.scenario_labels = {
            scenario_id: (
                scenario_cfg.get('name', scenario_id)
                if isinstance(scenario_cfg, dict)
                else scenario_id
            )
            for scenario_id, scenario_cfg in self.scenarios.items()
        }

        self.results = {}
        self.property_results: Dict[str, pd.DataFrame] = {}

        self.hn_analyzer = HeatNetworkAnalyzer() if HeatNetworkAnalyzer else None

        logger.info("Initialized Scenario Modeler")
        logger.info(self.cost_calculator.summary_notes() or "Costing rules configured.")
        logger.info(f"Loaded {len(self.scenarios)} scenarios")

    def _get_scenario_label(self, scenario_id: str) -> str:
        """Return the configured label for a scenario ID."""
        return self.scenario_labels.get(scenario_id, scenario_id)

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
            if self.hn_analyzer:
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
        Model a single decarbonization scenario with memory-efficient chunked processing.

        Uses chunked processing to avoid OOM on large datasets. Configuration via env vars:
        - HEATSTREET_WORKERS: Number of parallel workers (default: 2)
        - HEATSTREET_CHUNK_SIZE: Rows per chunk (default: 50000)

        Args:
            df: Property DataFrame
            scenario_name: Name of the scenario
            scenario_config: Scenario configuration

        Returns:
            Dictionary containing scenario results
        """
        scenario_start = time.time()
        measures = scenario_config.get('measures', [])
        measures = self._resolve_scenario_measures(measures)

        df_ready = self._ensure_adjusted_baseline(df)

        if not measures:
            # Baseline scenario - no interventions
            return self._model_baseline(df_ready)

        df_with_flags = self._preprocess_ashp_readiness(df_ready)

        # Get configurable scaling parameters
        max_workers = get_worker_count(default=2)
        chunk_size = get_chunk_size(default=50000)
        total_properties = len(df_with_flags)

        logger.info(f"  Processing {total_properties:,} properties (workers={max_workers}, chunk_size={chunk_size:,})")
        log_memory("Scenario modeling START")
        log_dataframe_info(df_with_flags, "Input DataFrame")

        # Process in chunks to limit memory usage
        all_upgrades = []
        num_chunks = (total_properties + chunk_size - 1) // chunk_size

        for chunk_idx in range(num_chunks):
            chunk_start = chunk_idx * chunk_size
            chunk_end = min(chunk_start + chunk_size, total_properties)
            chunk_df = df_with_flags.iloc[chunk_start:chunk_end]

            chunk_time_start = time.time()
            logger.info(f"  Chunk {chunk_idx + 1}/{num_chunks}: rows {chunk_start:,}-{chunk_end:,} ({len(chunk_df):,} properties)")

            # Convert chunk to dicts (only this chunk, not full DataFrame)
            property_dicts = chunk_df.to_dict('records')

            # Prepare arguments - DON'T include costs/config (use initializer globals)
            args_list = []
            for prop_dict in property_dicts:
                property_measures, applied_fabric, removed_hp, hybrid_pathway, removed_measures = self._build_property_measures(
                    measures,
                    prop_dict
                )
                # Compact args tuple (costs/config come from worker initializer)
                args_list.append((
                    prop_dict,
                    scenario_name,
                    property_measures,
                    applied_fabric,
                    removed_hp,
                    hybrid_pathway,
                    removed_measures
                ))

            # Process chunk with limited workers and initializer for shared state
            with ProcessPoolExecutor(
                max_workers=max_workers,
                initializer=_worker_initializer,
                initargs=(self.costs, self.cost_rules, self.config)
            ) as executor:
                chunk_upgrades = list(executor.map(
                    _calculate_property_upgrade_worker,
                    args_list,
                    chunksize=min(100, len(args_list))
                ))

            all_upgrades.extend(chunk_upgrades)

            chunk_time = time.time() - chunk_time_start
            logger.info(f"    Chunk {chunk_idx + 1} complete in {chunk_time:.1f}s ({len(chunk_df) / chunk_time:.0f} props/sec)")

            # Force garbage collection between chunks to release memory
            del property_dicts, args_list, chunk_upgrades
            gc.collect()
            log_memory(f"After chunk {chunk_idx + 1}")

        total_time = time.time() - scenario_start
        logger.info(f"  Parallel processing complete! Total time: {total_time:.1f}s")

        property_df = pd.DataFrame([asdict(upgrade) for upgrade in all_upgrades])
        self.property_results[scenario_name] = property_df

        # Aggregate results
        results = self._aggregate_scenario_results(property_df, df_with_flags)
        results['scenario_name'] = scenario_name
        results['scenario_label'] = self._get_scenario_label(scenario_name)
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
                # BUG FIX: Only include Tiers 1-3 for heat network readiness, not Tier 4
                # Tier 4 (medium density 5-15 GWh/km²) should be routed to heat pumps
                processed['hn_ready'] = tier_values.fillna('').apply(
                    lambda tier: isinstance(tier, str) and str(tier).startswith(('Tier 1', 'Tier 2', 'Tier 3'))
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
            updated_plan: List[str] = [
                m for m in measure_plan if m not in ['heat_network_where_available', 'ashp_elsewhere']
            ]

            hn_tier_max = int(
                self.config.get('heat_network', {}).get('readiness', {}).get('ready_tier_max', 3)
            )
            tier_number = property_dict.get('tier_number')

            hn_ready: Optional[bool] = None
            if tier_number is not None:
                try:
                    hn_ready = int(tier_number) <= hn_tier_max
                except (TypeError, ValueError):
                    hn_ready = None

            if hn_ready is None:
                hn_ready = bool(property_dict.get('hn_ready', False))

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
            self.cost_rules,
            self.config,
            False,
            False,
            None,
            [],
        )

    def _cost_loft_insulation(self, property_data: pd.Series) -> float:
        """Calculate cost of loft insulation top-up."""
        cost, _ = self.cost_calculator.measure_cost('loft_insulation_topup', property_data)
        return cost

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

        if wall_type == 'Cavity':
            cost, _ = self.cost_calculator.measure_cost('wall_insulation_cavity', property_data)
        else:
            cost, _ = self.cost_calculator.measure_cost('wall_insulation_internal', property_data)

        return cost

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
        cost, _ = self.cost_calculator.measure_cost('double_glazing', property_data)
        return cost

    def _savings_glazing(self, property_data: pd.Series) -> float:
        """Calculate energy savings from window glazing."""
        current_energy = self._get_absolute_energy(property_data)
        saving_pct = self.measure_savings.get('double_glazing', {}).get('kwh_saving_pct', 0.10)
        return current_energy * saving_pct

    def _cost_triple_glazing(self, property_data: pd.Series) -> float:
        """Calculate cost of triple glazing upgrade."""
        cost, _ = self.cost_calculator.measure_cost('triple_glazing', property_data)
        return cost

    def _savings_triple_glazing(self, property_data: pd.Series) -> float:
        """Calculate energy savings from triple glazing."""
        current_energy = self._get_absolute_energy(property_data)
        saving_pct = self.measure_savings.get('triple_glazing', {}).get('kwh_saving_pct', 0.15)
        return current_energy * saving_pct

    def _cost_floor_insulation(self, property_data: pd.Series) -> float:
        """Calculate cost of suspended timber floor insulation."""
        cost, _ = self.cost_calculator.measure_cost('floor_insulation', property_data)
        return cost

    def _savings_floor_insulation(self, property_data: pd.Series) -> float:
        """Calculate savings from insulating suspended timber floors."""
        current_energy = self._get_absolute_energy(property_data)
        saving_pct = self.measure_savings.get('floor_insulation', {}).get('kwh_saving_pct', 0.05)
        return current_energy * saving_pct

    def _cost_draught_proofing(self, property_data: pd.Series) -> float:
        """Calculate cost of draught proofing."""
        cost, _ = self.cost_calculator.measure_cost('draught_proofing', property_data)
        return cost

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
        cost, _ = self.cost_calculator.measure_cost('emitter_upgrades', property_data)
        return cost

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

        # AUDIT FIX: Document and track "not cost-effective" edge cases
        # These are properties with infinite payback (zero or negative bill savings)
        # Common causes:
        # - Very low baseline energy consumption (already efficient)
        # - Data anomalies (negative baseline bills, implausible values)
        # - Properties where measures don't reduce bills (e.g., tariff changes offset savings)
        if n_not_cost_effective > 0:
            not_ce_mask = ~property_df['payback_years'].apply(lambda x: x < 100 if pd.notna(x) else False)
            not_ce_df = property_df[not_ce_mask]

            # Log details about these properties for investigation
            if len(not_ce_df) > 0 and len(not_ce_df) <= 100:
                logger.debug(
                    f"  EDGE CASE: {len(not_ce_df)} properties not cost-effective. "
                    f"Reasons may include: zero/negative baseline bills, already efficient, "
                    f"or tariff changes offsetting savings."
                )
                # Log average baseline bill for these properties
                if 'baseline_bill' in not_ce_df.columns:
                    avg_baseline = not_ce_df['baseline_bill'].mean()
                    if avg_baseline <= 0:
                        logger.debug(f"    Average baseline bill for these: £{avg_baseline:.2f} (negative/zero)")

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

        # AUDIT FIX: Populate hn_assigned_properties and ashp_assigned_properties for ALL scenarios
        # Previously these were only set for hybrid scenarios
        if 'hybrid_pathway' in property_df.columns:
            # Hybrid scenario - use hybrid_pathway column
            results['hn_assigned_properties'] = int((property_df['hybrid_pathway'] == 'heat_network').sum())
            results['ashp_assigned_properties'] = int((property_df['hybrid_pathway'] == 'ashp').sum())
        else:
            # Non-hybrid scenario - determine from measures applied
            measures_col = 'measures_applied' if 'measures_applied' in property_df.columns else None

            # Check if this is a heat pump scenario
            is_hp_scenario = measures_col and property_df[measures_col].apply(
                lambda x: 'ashp_installation' in x if isinstance(x, list) else False
            ).any()

            # Check if this is a heat network scenario
            is_hn_scenario = measures_col and property_df[measures_col].apply(
                lambda x: 'district_heating_connection' in x if isinstance(x, list) else False
            ).any()

            if is_hp_scenario and not is_hn_scenario:
                # Pure HP scenario - count properties that got HP
                hp_count = property_df[measures_col].apply(
                    lambda x: 'ashp_installation' in x if isinstance(x, list) else False
                ).sum() if measures_col else 0
                results['ashp_assigned_properties'] = int(hp_count)
                results['hn_assigned_properties'] = 0
            elif is_hn_scenario and not is_hp_scenario:
                # Pure HN scenario - count properties that got HN
                hn_count = property_df[measures_col].apply(
                    lambda x: 'district_heating_connection' in x if isinstance(x, list) else False
                ).sum() if measures_col else 0
                results['hn_assigned_properties'] = int(hn_count)
                results['ashp_assigned_properties'] = 0
            else:
                # Fabric-only or baseline scenario - no HP or HN assignments
                results['hn_assigned_properties'] = 0
                results['ashp_assigned_properties'] = 0

        if 'costing_cap_applied' in property_df.columns:
            results['costing_caps_applied_properties'] = int(property_df['costing_cap_applied'].sum())

        if 'costing_basis' in property_df.columns:
            bases = sorted(
                b for b in property_df['costing_basis'].dropna().unique().tolist() if b
            )
            if bases:
                results['costing_bases_used'] = bases

        if results.get('costing_caps_applied_properties', 0) > 0:
            logger.info(
                f"  Cost caps applied for {results['costing_caps_applied_properties']:,} properties (per cost_rules)."
            )
        if results.get('costing_bases_used'):
            logger.info(f"  Costing bases used: {', '.join(results['costing_bases_used'])}.")

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

        # Log hard limit exceedance but don't crash - this indicates aggressive SAP assumptions
        # that need review, but shouldn't halt the entire analysis
        if band_a_after > band_a_guardrail_hard_limit:
            logger.error(
                f"Band A count ({band_a_after}) exceeds hard limit ({band_a_guardrail_hard_limit}). "
                f"SAP delta assumptions may be too aggressive. Results should be reviewed."
            )
            # Cap the band distribution reporting to avoid misleading outputs
            # The property-level data still contains original predictions for debugging

        results['epc_band_shifts'] = {
            'before': current_bands,
            'after': new_bands,
            'max_band_improvement': MAX_EPC_BAND_IMPROVEMENT,
            'band_shift_cap_properties': int(property_df['band_shift_capped'].sum()) if 'band_shift_capped' in property_df.columns else 0,
            'band_a_warning': band_a_warning,
            'band_a_guardrail': band_a_guardrail,
            'band_a_hard_limit_exceeded': band_a_after > band_a_guardrail_hard_limit
        }

        # Enhanced EPC band distribution summary
        band_shift_summary = calculate_band_shift_summary(current_bands, new_bands)
        results['epc_band_shift_summary'] = band_shift_summary

        # Log EPC band shift summary
        if band_shift_summary:
            before_c_pct = band_shift_summary.get('band_c_or_better_before_pct', 0)
            after_c_pct = band_shift_summary.get('band_c_or_better_after_pct', 0)
            logger.info(
                f"  EPC Band C or better: {before_c_pct:.1f}% → {after_c_pct:.1f}% "
                f"(+{after_c_pct - before_c_pct:.1f}pp)"
            )

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

        # Cost-effectiveness summary using tiered threshold-based classification
        # AUDIT FIX: Uses three-tier system (cost-effective, marginal, not cost-effective)
        cost_effectiveness_cfg = get_cost_effectiveness_params()
        max_payback_threshold = cost_effectiveness_cfg.get('max_payback_years', 15)
        marginal_threshold = cost_effectiveness_cfg.get('max_payback_marginal', 25)

        if 'upgrade_recommended' in property_df.columns:
            recommended_count = int(property_df['upgrade_recommended'].sum())
            results['upgrade_recommended_count'] = recommended_count
            results['upgrade_recommended_pct'] = (recommended_count / total_properties * 100) if total_properties > 0 else 0

        # Detailed cost-effectiveness summary with tiered classification
        ce_summary = calculate_cost_effectiveness_summary(
            property_df, max_payback_threshold, marginal_threshold
        )
        results['cost_effectiveness_summary'] = ce_summary

        # Carbon abatement cost statistics
        if 'carbon_abatement_cost' in numeric_df.columns:
            finite_abatement = numeric_df['carbon_abatement_cost'].replace([np.inf, -np.inf], np.nan).dropna()
            if len(finite_abatement) > 0:
                results['carbon_abatement_cost_mean'] = float(finite_abatement.mean())
                results['carbon_abatement_cost_median'] = float(finite_abatement.median())
                results['carbon_abatement_cost_p10'] = float(finite_abatement.quantile(0.10))
                results['carbon_abatement_cost_p90'] = float(finite_abatement.quantile(0.90))

        # Log tiered cost-effectiveness summary
        if ce_summary:
            ce_pct = ce_summary.get('cost_effective_pct', 0)
            marginal_pct = ce_summary.get('marginal_pct', 0)
            not_ce_pct = ce_summary.get('not_cost_effective_pct', 0)
            logger.info(f"  Cost-effectiveness classification (AUDIT FIX: tiered criteria):")
            logger.info(
                f"    Cost-effective (payback ≤{max_payback_threshold}yr): "
                f"{ce_summary.get('cost_effective_count', 0):,} ({ce_pct:.1f}%)"
            )
            logger.info(
                f"    Marginal (payback {max_payback_threshold}-{marginal_threshold}yr): "
                f"{ce_summary.get('marginal_count', 0):,} ({marginal_pct:.1f}%)"
            )
            logger.info(
                f"    Not cost-effective (payback >{marginal_threshold}yr or no savings): "
                f"{ce_summary.get('not_cost_effective_count', 0):,} ({not_ce_pct:.1f}%)"
            )

        return results

    def _calculate_smooth_uptake_rate(self, payback_years: float) -> float:
        """
        Calculate adoption uptake rate using a smooth logistic function.

        AUDIT FIX: Replaces the step-change uptake model with a continuous
        logistic curve. This addresses the audit finding that hard thresholds
        (e.g., 5% at 25 years, jumping to 20% at 20 years) are unrealistic.

        The logistic function provides:
        - Continuous, differentiable uptake as payback changes
        - No "cliff edges" where small subsidy changes cause large uptake jumps
        - More realistic representation of heterogeneous consumer behavior

        Model parameters derived from:
        - Nauleau et al. (2015): Household retrofit adoption in France
        - Achtnicht & Madlener (2014): Energy efficiency adoption factors
        - UK EPC/Green Deal data analysis (BEIS 2019)

        Args:
            payback_years: Simple payback period in years

        Returns:
            Uptake rate between 0.02 and 0.85
        """
        # Logistic function parameters
        # L = maximum uptake (ceiling)
        # k = steepness of curve
        # x0 = midpoint (payback at which uptake is 50% of max)
        L = 0.85      # Maximum uptake rate (85%)
        k = 0.20      # Steepness (higher = sharper transition)
        x0 = 12.0     # Midpoint payback (50% max uptake at 12 years)
        floor = 0.02  # Minimum uptake (early adopters/innovators)

        # Logistic function: L / (1 + exp(k * (x - x0)))
        # Returns high uptake for low payback, low uptake for high payback
        try:
            exponent = k * (payback_years - x0)
            # Clamp to prevent overflow
            exponent = max(-20, min(20, exponent))
            uptake = L / (1 + np.exp(exponent))
        except (OverflowError, FloatingPointError):
            uptake = floor if payback_years > x0 else L

        # Apply floor for minimum uptake (even at very long paybacks)
        return max(floor, uptake)

    def model_subsidy_sensitivity(
        self,
        df: pd.DataFrame,
        scenario_name: str = 'heat_pump'
    ) -> Dict:
        """
        Model impact of varying subsidy levels on uptake and costs.

        AUDIT FIX: Uses smooth logistic uptake curves instead of step-changes.
        This provides more realistic modeling of consumer adoption behavior
        where uptake gradually increases as economics improve, rather than
        jumping at arbitrary thresholds.

        The model now shows incremental benefits to smaller incentives,
        addressing the audit concern that the step-change model understates
        CO₂ savings achievable with moderate subsidies.

        Args:
            df: Property DataFrame
            scenario_name: Which scenario to apply subsidies to

        Returns:
            Dictionary containing subsidy sensitivity results
        """
        logger.info(f"Modeling subsidy sensitivity for {scenario_name} scenario...")
        logger.info("  Using smooth logistic uptake model (AUDIT FIX)")

        subsidy_levels = self.config.get('subsidy_levels', [0, 25, 50, 75, 100])
        scenario_config = self.scenarios[scenario_name]
        uplift_pct = float(self.config.get('financial', {}).get('subsidy_sensitivity_cost_uplift_pct', 0))
        uplift_multiplier = 1 + (uplift_pct / 100)
        uplift_note = (
            f"Costs uplifted by {uplift_pct:.1f}% for subsidy sensitivity."
            if uplift_pct
            else "No cost uplift applied for subsidy sensitivity."
        )

        sensitivity_results = {}

        # Model base scenario once to get baseline metrics
        base_results = self.model_scenario(df, scenario_name, scenario_config)
        capital_cost_total_base = base_results['capital_cost_total']
        capital_cost_per_property_base = base_results['capital_cost_per_property']
        capital_cost_total_uplifted = capital_cost_total_base * uplift_multiplier
        capital_cost_per_property_uplifted = capital_cost_per_property_base * uplift_multiplier

        for subsidy_pct in subsidy_levels:
            logger.info(f"  Analyzing {subsidy_pct}% subsidy level...")

            # Apply subsidy
            capital_cost_subsidized = capital_cost_total_uplifted * (1 - subsidy_pct/100)
            capital_cost_per_property = capital_cost_per_property_uplifted * (1 - subsidy_pct/100)

            # Recalculate payback with subsidy
            annual_savings = base_results['annual_bill_savings']
            payback_years = capital_cost_subsidized / annual_savings if annual_savings > 0 else 999

            # Use smooth logistic uptake function instead of step thresholds
            uptake_rate = self._calculate_smooth_uptake_rate(payback_years)

            properties_upgraded = int(base_results['total_properties'] * uptake_rate)
            public_expenditure = (capital_cost_per_property_uplifted * subsidy_pct/100) * properties_upgraded

            # Carbon abatement cost
            total_co2_saved = (
                base_results['annual_co2_reduction_kg'] * uptake_rate * self.analysis_horizon_years
            )
            carbon_abatement_cost = public_expenditure / (total_co2_saved / 1000) if total_co2_saved > 0 else 0  # £/tCO2

            sensitivity_results[f'{subsidy_pct}%'] = {
                'subsidy_percentage': subsidy_pct,
                'capital_cost_per_property': capital_cost_per_property,
                'capital_cost_total_uplifted': capital_cost_total_uplifted,
                'capital_cost_per_property_uplifted': capital_cost_per_property_uplifted,
                'capital_cost_total_after_subsidy': capital_cost_subsidized,
                'capital_cost_per_property_after_subsidy': capital_cost_per_property,
                'payback_years': payback_years,
                'estimated_uptake_rate': uptake_rate,
                'uptake_model': 'logistic_smooth',  # Document model type
                'properties_upgraded': properties_upgraded,
                'public_expenditure_total': public_expenditure,
                'public_expenditure_per_property': public_expenditure / properties_upgraded if properties_upgraded > 0 else 0,
                'carbon_abatement_cost_per_tonne': carbon_abatement_cost,
                'cost_uplift_pct': uplift_pct,
                'cost_uplift_note': uplift_note
            }

            logger.info(
                f"    Payback: {payback_years:.1f}yr → Uptake: {uptake_rate*100:.1f}% "
                f"({properties_upgraded:,} properties)"
            )

        # Store for later export
        self.subsidy_sensitivity_results = sensitivity_results
        self.subsidy_sensitivity_scenario = scenario_name

        return sensitivity_results

    def save_subsidy_sensitivity_results(
        self,
        output_path: Optional[Path] = None
    ) -> Optional[Path]:
        """
        Save subsidy sensitivity analysis results to CSV.

        The subsidy sensitivity analysis examines how varying subsidy levels
        affect uptake rates and cost-effectiveness for heat pump upgrades.

        Args:
            output_path: Optional path for output file

        Returns:
            Path to saved CSV file, or None if no results available
        """
        if not hasattr(self, 'subsidy_sensitivity_results') or not self.subsidy_sensitivity_results:
            logger.warning("No subsidy sensitivity results to save. Run model_subsidy_sensitivity() first.")
            return None

        if output_path is None:
            output_path = DATA_OUTPUTS_DIR / "subsidy_sensitivity_analysis.csv"

        rows = []
        for level_key, level_data in self.subsidy_sensitivity_results.items():
            row = {
                'scenario': getattr(self, 'subsidy_sensitivity_scenario', 'heat_pump'),
                'analysis_type': 'Heat Pump Subsidy Sensitivity',
                **level_data
            }
            rows.append(row)

        subsidy_df = pd.DataFrame(rows)

        # Sort by subsidy percentage
        subsidy_df = subsidy_df.sort_values('subsidy_percentage')

        subsidy_df.to_csv(output_path, index=False)
        logger.info(f"Subsidy sensitivity results saved to: {output_path}")
        logger.info(
            f"  Analysis covers {len(rows)} subsidy levels for "
            f"'{getattr(self, 'subsidy_sensitivity_scenario', 'heat_pump')}' scenario"
        )

        return output_path

    def _build_summary_dataframe(self) -> pd.DataFrame:
        rows: List[Dict[str, Any]] = []
        for scenario, results in self.results.items():
            if not isinstance(results, dict):
                continue

            # Extract cost-effectiveness summary values
            ce_summary = results.get('cost_effectiveness_summary', {})
            band_summary = results.get('epc_band_shift_summary', {})
            scenario_label = results.get('scenario_label') or self._get_scenario_label(scenario)
            capital_cost_total = results.get('capital_cost_total')
            annual_co2_reduction_kg = results.get('annual_co2_reduction_kg')
            cost_per_tco2_20yr_gbp = None
            # Uses total CO2 abatement over the analysis horizon (annual savings × years).
            if capital_cost_total is not None and annual_co2_reduction_kg:
                tco2_over_horizon = (
                    annual_co2_reduction_kg / 1000
                ) * self.analysis_horizon_years
                if tco2_over_horizon:
                    cost_per_tco2_20yr_gbp = capital_cost_total / tco2_over_horizon

            rows.append({
                'scenario_id': scenario,
                'scenario': scenario_label,
                'total_properties': results.get('total_properties'),
                'capital_cost_total': results.get('capital_cost_total'),
                'capital_cost_per_property': results.get('capital_cost_per_property'),
                'annual_energy_reduction_kwh': results.get('annual_energy_reduction_kwh'),
                'annual_co2_reduction_kg': results.get('annual_co2_reduction_kg'),
                'cost_per_tco2_20yr_gbp': cost_per_tco2_20yr_gbp,
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
                # Cost-effectiveness metrics
                'upgrade_recommended_count': results.get('upgrade_recommended_count'),
                'upgrade_recommended_pct': results.get('upgrade_recommended_pct'),
                'cost_effective_count': ce_summary.get('cost_effective_count'),
                'cost_effective_pct': ce_summary.get('cost_effective_pct'),
                'marginal_count': ce_summary.get('marginal_count'),
                'marginal_pct': ce_summary.get('marginal_pct'),
                'not_cost_effective_count': ce_summary.get('not_cost_effective_count'),
                'not_cost_effective_pct': ce_summary.get('not_cost_effective_pct'),
                'carbon_abatement_cost_mean': results.get('carbon_abatement_cost_mean'),
                'carbon_abatement_cost_median': results.get('carbon_abatement_cost_median'),
                # EPC band metrics
                'band_c_or_better_before_pct': band_summary.get('band_c_or_better_before_pct'),
                'band_c_or_better_after_pct': band_summary.get('band_c_or_better_after_pct'),
                # HP readiness
                'ashp_ready_properties': results.get('ashp_ready_properties'),
                'ashp_ready_pct': results.get('ashp_ready_pct'),
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
            f.write("Notes:\n")
            f.write("  All energy figures are annual delivered (final) energy unless stated otherwise; not primary energy.\n")
            f.write(
                "  Heat networks: connection cost included (district heating within the 3,000–8,000 £ connection-cost "
                "band seen in UK schemes); major network backbone capex excluded unless explicitly modeled.\n"
            )
            f.write("  Heat pumps: electricity grid upgrade costs not included.\n\n")

            for scenario, results in self.results.items():
                scenario_label = results.get('scenario_label') or self._get_scenario_label(scenario)
                f.write(f"\nSCENARIO: {scenario_label}\n")
                f.write("-"*70 + "\n")

                # Write basic metrics
                basic_keys = [
                    'total_properties', 'capital_cost_total', 'capital_cost_per_property',
                    'annual_energy_reduction_kwh', 'annual_co2_reduction_kg', 'annual_bill_savings',
                    'average_payback_years', 'median_payback_years'
                ]
                for key in basic_keys:
                    if key in results:
                        f.write(f"{key}: {results[key]}\n")

                # Write cost-effectiveness section
                f.write("\nCost-Effectiveness Analysis:\n")
                ce_summary = results.get('cost_effectiveness_summary', {})
                if ce_summary:
                    f.write(f"  Cost-effective properties: {ce_summary.get('cost_effective_count', 0):,} "
                            f"({ce_summary.get('cost_effective_pct', 0):.1f}%)\n")
                    f.write(f"  Marginal properties (payback >{ce_summary.get('payback_threshold_years', 20)}yr): "
                            f"{ce_summary.get('marginal_count', 0):,} ({ce_summary.get('marginal_pct', 0):.1f}%)\n")
                    f.write(f"  Not cost-effective: {ce_summary.get('not_cost_effective_count', 0):,} "
                            f"({ce_summary.get('not_cost_effective_pct', 0):.1f}%)\n")

                if 'upgrade_recommended_count' in results:
                    f.write(f"  Upgrade recommended: {results['upgrade_recommended_count']:,} "
                            f"({results.get('upgrade_recommended_pct', 0):.1f}%)\n")

                if 'carbon_abatement_cost_median' in results:
                    f.write(f"  Carbon abatement cost (median): £{results['carbon_abatement_cost_median']:.0f}/tCO2\n")

                # Write EPC band shift section
                f.write("\nEPC Band Distribution:\n")
                band_summary = results.get('epc_band_shift_summary', {})
                if band_summary:
                    before_c = band_summary.get('band_c_or_better_before_pct', 0)
                    after_c = band_summary.get('band_c_or_better_after_pct', 0)
                    f.write(f"  Band C or better: {before_c:.1f}% → {after_c:.1f}% (+{after_c - before_c:.1f}pp)\n")

                epc_shifts = results.get('epc_band_shifts', {})
                if epc_shifts:
                    f.write("  Before intervention:\n")
                    for band in BAND_ORDER:
                        count = epc_shifts.get('before', {}).get(band, 0)
                        if count > 0:
                            f.write(f"    Band {band}: {count:,}\n")
                    f.write("  After intervention:\n")
                    for band in BAND_ORDER:
                        count = epc_shifts.get('after', {}).get(band, 0)
                        if count > 0:
                            f.write(f"    Band {band}: {count:,}\n")

                # Write HP readiness section
                if 'ashp_ready_properties' in results:
                    f.write("\nHeat Pump Readiness:\n")
                    f.write(f"  HP-ready (current fabric): {results['ashp_ready_properties']:,} "
                            f"({results.get('ashp_ready_pct', 0):.1f}%)\n")
                    f.write(f"  Require fabric upgrades: {results.get('ashp_fabric_required_properties', 0):,}\n")
                    f.write(f"  Not suitable for HP: {results.get('ashp_not_ready_properties', 0):,}\n")

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

        # Generate EPC band distribution CSV
        epc_band_path = self._save_epc_band_distribution()

        # Save subsidy sensitivity results if available
        subsidy_path = self.save_subsidy_sensitivity_results()

        return {
            'report_path': output_path,
            'summary_path': summary_path,
            'property_path': property_path,
            'epc_band_distribution_path': epc_band_path,
            'subsidy_sensitivity_path': subsidy_path,
        }

    def _save_epc_band_distribution(self) -> Optional[Path]:
        """Save EPC band distribution summary as CSV."""
        if not self.results:
            return None

        rows = []
        for scenario, results in self.results.items():
            scenario_label = results.get('scenario_label') or self._get_scenario_label(scenario)
            epc_shifts = results.get('epc_band_shifts', {})
            band_summary = results.get('epc_band_shift_summary', {})

            before_bands = epc_shifts.get('before', {})
            after_bands = epc_shifts.get('after', {})

            for band in BAND_ORDER:
                rows.append({
                    'scenario_id': scenario,
                    'scenario': scenario_label,
                    'band': band,
                    'count_before': before_bands.get(band, 0),
                    'count_after': after_bands.get(band, 0),
                    'change': after_bands.get(band, 0) - before_bands.get(band, 0),
                })

            # Add summary row for Band C or better
            rows.append({
                'scenario_id': scenario,
                'scenario': scenario_label,
                'band': 'C_or_better',
                'count_before': band_summary.get('band_c_or_better_before', 0),
                'count_after': band_summary.get('band_c_or_better_after', 0),
                'change': (
                    band_summary.get('band_c_or_better_after', 0) -
                    band_summary.get('band_c_or_better_before', 0)
                ),
            })

        if not rows:
            return None

        epc_df = pd.DataFrame(rows)
        epc_path = DATA_OUTPUTS_DIR / "epc_band_distribution.csv"
        epc_df.to_csv(epc_path, index=False)
        logger.info(f"EPC band distribution saved to: {epc_path}")
        return epc_path


def main():
    """Main execution function for scenario modeling."""
    logger.info("Starting scenario modeling...")

    # Load validated data
    input_file = DATA_PROCESSED_DIR / "epc_london_validated.csv"

    if not input_file.exists():
        logger.error(f"Input file not found: {input_file}")
        return

    logger.info(f"Loading data from: {input_file}")
    df = pd.read_csv(input_file)

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
