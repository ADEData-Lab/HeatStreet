"""
Shared Modeling Utilities Module

Centralizes common functions used by ScenarioModeler and PathwayModeler to avoid
code duplication and ensure consistent methodology across the pipeline.

Key utilities:
- Baseline energy selection (prebound-adjusted)
- COP/SCOP calculations based on flow temperature
- Heat pump readiness checks
- EPC band mapping and conversions
- Cost-effectiveness calculations
"""

import pandas as pd
import numpy as np
from typing import Any, Dict, List, Optional, Tuple, Union
from loguru import logger

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import load_config, get_measure_savings
from src.analysis.methodological_adjustments import MethodologicalAdjustments


# ==============================================================================
# EPC BAND CONSTANTS AND MAPPINGS
# ==============================================================================

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

# Maximum EPC band improvement in a single intervention (guardrail)
MAX_EPC_BAND_IMPROVEMENT = 2

# SAP points gained per 1% energy saving
SAP_POINTS_PER_PERCENT_SAVING = 0.45

# Guardrail: max share of stock that can reach Band A
BAND_A_GUARDRAIL_SHARE = 0.10


# ==============================================================================
# BASELINE ENERGY SELECTION
# ==============================================================================

def select_baseline_energy_intensity(property_like: Union[pd.Series, Dict[str, Any]]) -> float:
    """
    Select the appropriate baseline energy intensity for a property.

    Prioritizes prebound-adjusted columns when available, otherwise
    falls back to EPC-modeled values.

    Args:
        property_like: Property data as Series or dict

    Returns:
        Energy intensity in kWh/m²/year

    Raises:
        ValueError: If negative energy intensity is found
    """
    priority_cols = [
        'energy_consumption_adjusted',
        'energy_consumption_adjusted_central',
        'ENERGY_CONSUMPTION_CURRENT',
    ]

    for col in priority_cols:
        val = property_like.get(col)
        if val is not None and not pd.isna(val):
            numeric_val = float(val)
            if numeric_val < 0:
                raise ValueError(f"Negative energy intensity supplied for {col}: {numeric_val}")
            return numeric_val

    # Default fallback
    return float(property_like.get('ENERGY_CONSUMPTION_CURRENT', 150))


def select_baseline_annual_kwh(
    property_like: Union[pd.Series, Dict[str, Any]],
    energy_intensity: Optional[float] = None
) -> float:
    """
    Return absolute baseline consumption in kWh/year.

    Prioritizes prebound-adjusted columns when available.

    Args:
        property_like: Property data as Series or dict
        energy_intensity: Pre-computed intensity (if available)

    Returns:
        Annual energy consumption in kWh/year
    """
    priority_cols = [
        'baseline_consumption_kwh_year',
        'baseline_consumption_kwh_year_central',
        'baseline_consumption_kwh_year_low',
        'baseline_consumption_kwh_year_high',
    ]

    for col in priority_cols:
        val = property_like.get(col)
        if val is not None and not pd.isna(val):
            return float(val)

    # Calculate from intensity and floor area
    if energy_intensity is None:
        energy_intensity = select_baseline_energy_intensity(property_like)

    floor_area = property_like.get('TOTAL_FLOOR_AREA', 100)
    if pd.isna(floor_area):
        floor_area = 100

    return float(energy_intensity) * float(floor_area)


def assert_non_negative_intensities(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure no negative energy intensity values are present.

    Args:
        df: DataFrame with energy intensity columns

    Returns:
        DataFrame (unchanged if valid)

    Raises:
        ValueError: If negative intensities found
    """
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
        raise ValueError(f"Negative energy intensities found: {negative_counts}")

    return df


# ==============================================================================
# EPC BAND UTILITIES
# ==============================================================================

def rating_to_band(rating: float) -> str:
    """
    Convert a SAP rating to an EPC band.

    Args:
        rating: SAP rating (0-100)

    Returns:
        EPC band letter (A-G)
    """
    try:
        numeric_rating = float(rating)
    except (TypeError, ValueError):
        numeric_rating = 0.0

    for band in BAND_ORDER:
        if numeric_rating >= BAND_THRESHOLD_MAP[band]:
            return band

    return 'G'


def band_to_threshold(band: str) -> float:
    """
    Get the minimum SAP score for an EPC band.

    Args:
        band: EPC band letter

    Returns:
        Minimum SAP score for the band
    """
    band_clean = str(band).strip().upper()
    return float(BAND_THRESHOLD_MAP.get(band_clean, 0))


def band_upper_bound(band: str) -> float:
    """
    Return the maximum SAP score allowed within a band.

    Args:
        band: EPC band letter

    Returns:
        Maximum SAP score (exclusive of next band)
    """
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


def normalize_band(band: str, fallback_rating: float) -> str:
    """
    Normalize band text, falling back to SAP-derived band when invalid.

    Args:
        band: Band string from EPC data
        fallback_rating: SAP rating to use if band is invalid

    Returns:
        Valid EPC band letter
    """
    band_clean = str(band).strip().upper()
    if band_clean in BAND_ORDER:
        return band_clean

    return rating_to_band(fallback_rating)


def is_band_at_least(band: str, minimum: str) -> bool:
    """
    Check whether EPC band meets or exceeds the minimum.

    Args:
        band: Current EPC band
        minimum: Required minimum band

    Returns:
        True if band >= minimum (A is best)
    """
    band_upper = band.strip().upper() if band else 'G'
    minimum_upper = minimum.strip().upper() if minimum else 'G'

    if band_upper not in BAND_ORDER or minimum_upper not in BAND_ORDER:
        return False

    return BAND_ORDER.index(band_upper) <= BAND_ORDER.index(minimum_upper)


def calculate_sap_delta_from_energy_savings(
    baseline_kwh: float,
    post_kwh: float,
    baseline_sap: float
) -> Tuple[float, float]:
    """
    Estimate SAP delta from energy savings.

    Uses a linear approximation based on percentage energy reduction.

    Args:
        baseline_kwh: Baseline annual consumption
        post_kwh: Post-measure annual consumption
        baseline_sap: Current SAP rating

    Returns:
        Tuple of (sap_point_gain, saving_pct_basis)
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


def calculate_epc_band_distribution(
    df: pd.DataFrame,
    band_column: str = 'CURRENT_ENERGY_RATING'
) -> Dict[str, int]:
    """
    Calculate EPC band distribution from a DataFrame.

    Args:
        df: DataFrame with EPC data
        band_column: Column containing EPC bands

    Returns:
        Dictionary mapping band -> count
    """
    if band_column not in df.columns:
        return {}

    return df[band_column].value_counts().to_dict()


def calculate_band_shift_summary(
    before_bands: Dict[str, int],
    after_bands: Dict[str, int]
) -> Dict[str, Any]:
    """
    Calculate summary of EPC band shifts.

    Args:
        before_bands: Band distribution before intervention
        after_bands: Band distribution after intervention

    Returns:
        Dictionary with shift statistics
    """
    total = sum(before_bands.values())
    if total == 0:
        return {}

    # Calculate properties at each band level
    def count_at_band_or_better(bands: Dict[str, int], target: str) -> int:
        target_idx = BAND_ORDER.index(target) if target in BAND_ORDER else len(BAND_ORDER)
        return sum(bands.get(b, 0) for b in BAND_ORDER[:target_idx + 1])

    return {
        'total_properties': total,
        'before': before_bands,
        'after': after_bands,
        'band_c_or_better_before': count_at_band_or_better(before_bands, 'C'),
        'band_c_or_better_after': count_at_band_or_better(after_bands, 'C'),
        'band_c_or_better_before_pct': count_at_band_or_better(before_bands, 'C') / total * 100,
        'band_c_or_better_after_pct': count_at_band_or_better(after_bands, 'C') / total * 100,
        'band_a_before': before_bands.get('A', 0),
        'band_a_after': after_bands.get('A', 0),
    }


# ==============================================================================
# COP/SCOP CALCULATION UTILITIES
# ==============================================================================

# Module-level adjuster instance for performance
_adjuster: Optional[MethodologicalAdjustments] = None


def get_adjuster() -> MethodologicalAdjustments:
    """Get or create a shared MethodologicalAdjustments instance."""
    global _adjuster
    if _adjuster is None:
        _adjuster = MethodologicalAdjustments()
    return _adjuster


def derive_heat_pump_cop(
    flow_temp: Union[pd.Series, float, int],
    include_bounds: bool = True
) -> Dict[str, Union[pd.Series, float]]:
    """
    Derive heat pump COP based on flow temperature.

    Uses the configured COP vs flow temperature curves from config.yaml.

    Args:
        flow_temp: Target flow temperature(s) in °C
        include_bounds: Whether to return low/high sensitivity bounds

    Returns:
        Dictionary with central (and optional low/high) COP values
    """
    adjuster = get_adjuster()
    return adjuster.derive_heat_pump_cop(flow_temp, include_bounds=include_bounds)


def estimate_flow_temperature(df: pd.DataFrame) -> pd.DataFrame:
    """
    Estimate required flow temperature for heat pumps based on fabric.

    Args:
        df: DataFrame with property data

    Returns:
        DataFrame with flow temperature estimates added
    """
    adjuster = get_adjuster()
    return adjuster.estimate_flow_temperature(df)


def calculate_operating_flow_temp(
    baseline_flow_temp: float,
    flow_temp_reduction: float,
    min_flow_temp: float = 35.0
) -> float:
    """
    Calculate operating flow temperature after fabric measures.

    Args:
        baseline_flow_temp: Estimated baseline flow temperature
        flow_temp_reduction: Total flow temp reduction from measures (K)
        min_flow_temp: Minimum achievable flow temperature

    Returns:
        Operating flow temperature in °C
    """
    return max(min_flow_temp, baseline_flow_temp - flow_temp_reduction)


# ==============================================================================
# HEAT PUMP READINESS UTILITIES
# ==============================================================================

def is_hp_ready(
    property_like: Union[pd.Series, Dict[str, Any]],
    max_heat_demand_kwh_m2: float = 100.0,
    min_epc_band: str = 'C'
) -> bool:
    """
    Check if a property is heat pump ready based on current fabric.

    A property is HP-ready if it meets EITHER:
    - Heat demand ≤ threshold (kWh/m²/yr)
    - EPC band meets or exceeds minimum

    Args:
        property_like: Property data as Series or dict
        max_heat_demand_kwh_m2: Maximum heat demand threshold
        min_epc_band: Minimum required EPC band

    Returns:
        True if property is HP-ready
    """
    # Check heat demand
    heat_demand = None
    for col in ['energy_consumption_adjusted', 'energy_consumption_adjusted_central',
                'ENERGY_CONSUMPTION_CURRENT', 'heat_demand_kwh_m2']:
        val = property_like.get(col)
        if val is not None and not pd.isna(val):
            heat_demand = float(val)
            break

    if heat_demand is not None and heat_demand <= max_heat_demand_kwh_m2:
        return True

    # Check EPC band
    epc_band = property_like.get('CURRENT_ENERGY_RATING', 'G')
    if is_band_at_least(str(epc_band), min_epc_band):
        return True

    return False


def is_hp_ready_after_fabric(
    property_like: Union[pd.Series, Dict[str, Any]],
    fabric_measures: List[str],
    measure_savings: Optional[Dict] = None,
    max_heat_demand_kwh_m2: float = 100.0
) -> bool:
    """
    Check if a property would be HP-ready after fabric improvements.

    Args:
        property_like: Property data as Series or dict
        fabric_measures: List of fabric measures to apply
        measure_savings: Measure savings config (loaded if None)
        max_heat_demand_kwh_m2: Heat demand threshold

    Returns:
        True if property would be HP-ready after fabric
    """
    if measure_savings is None:
        measure_savings = get_measure_savings()

    heat_demand = select_baseline_energy_intensity(property_like)

    # Apply multiplicative savings
    for measure in fabric_measures:
        saving_pct = measure_savings.get(measure, {}).get('kwh_saving_pct', 0)
        if saving_pct:
            heat_demand *= (1 - saving_pct)

    return heat_demand <= max_heat_demand_kwh_m2


def min_fabric_measures_for_hp(
    property_like: Union[pd.Series, Dict[str, Any]],
    available_bundles: Optional[Dict[str, List[str]]] = None,
    measure_savings: Optional[Dict] = None,
    max_heat_demand_kwh_m2: float = 100.0
) -> List[str]:
    """
    Determine minimum fabric measures needed to make a property HP-ready.

    Uses precomputed fabric bundles if available, otherwise applies a
    conservative default bundle.

    Args:
        property_like: Property data as Series or dict
        available_bundles: Precomputed fabric bundles from tipping point analysis
        measure_savings: Measure savings config (loaded if None)
        max_heat_demand_kwh_m2: Heat demand threshold

    Returns:
        List of measure IDs needed to reach HP-ready status
    """
    # If already HP-ready, no fabric needed
    if is_hp_ready(property_like, max_heat_demand_kwh_m2=max_heat_demand_kwh_m2):
        return []

    if measure_savings is None:
        measure_savings = get_measure_savings()

    # Try precomputed bundle first
    if available_bundles and 'fabric_minimum_to_ashp' in available_bundles:
        bundle = available_bundles['fabric_minimum_to_ashp']
        if is_hp_ready_after_fabric(property_like, bundle, measure_savings, max_heat_demand_kwh_m2):
            return bundle

    # Conservative default bundle based on wall type
    wall_type = str(property_like.get('wall_type', '')).lower()
    glazing_type = str(property_like.get('glazing_type', '')).lower()

    default_measures = ['loft_insulation_topup']

    if 'solid' in wall_type or not property_like.get('wall_insulated', True):
        default_measures.append('wall_insulation')

    if 'single' in glazing_type:
        default_measures.append('double_glazing')

    return default_measures


def assess_hp_readiness_status(
    property_like: Union[pd.Series, Dict[str, Any]],
    fabric_minimum_measures: List[str],
    measure_savings: Optional[Dict] = None,
    max_heat_demand_kwh_m2: float = 100.0,
    min_epc_band: str = 'C'
) -> Dict[str, Any]:
    """
    Comprehensive HP readiness assessment for a property.

    Returns:
        Dictionary with readiness status flags:
        - ashp_ready: Currently HP-ready
        - ashp_projected_ready: Would be HP-ready after minimum fabric
        - ashp_fabric_needed: Needs fabric to become HP-ready
        - ashp_not_ready_after_fabric: Not suitable even after fabric
    """
    if measure_savings is None:
        measure_savings = get_measure_savings()

    ready_now = is_hp_ready(property_like, max_heat_demand_kwh_m2, min_epc_band)
    ready_after_fabric = is_hp_ready_after_fabric(
        property_like, fabric_minimum_measures, measure_savings, max_heat_demand_kwh_m2
    )

    return {
        'ashp_ready': ready_now,
        'ashp_projected_ready': ready_after_fabric,
        'ashp_fabric_needed': not ready_now and ready_after_fabric,
        'ashp_not_ready_after_fabric': not ready_now and not ready_after_fabric,
    }


# ==============================================================================
# COST-EFFECTIVENESS UTILITIES
# ==============================================================================

def calculate_simple_payback(capex: float, annual_saving: float) -> float:
    """
    Calculate simple payback period.

    Args:
        capex: Capital cost
        annual_saving: Annual bill savings

    Returns:
        Payback period in years (inf if not cost-effective)
    """
    if pd.isna(capex) or pd.isna(annual_saving):
        return np.inf
    if annual_saving <= 0:
        return np.inf
    if capex <= 0:
        return 0.0
    return capex / annual_saving


def calculate_discounted_payback(
    capex: float,
    annual_saving: float,
    discount_rate: float = 0.035,
    max_years: int = 50
) -> float:
    """
    Calculate discounted payback period using NPV method.

    Args:
        capex: Capital cost
        annual_saving: Annual bill savings
        discount_rate: Discount rate (default 3.5% per Green Book)
        max_years: Maximum years to calculate

    Returns:
        Discounted payback period in years (inf if not achieved)
    """
    if annual_saving <= 0 or capex <= 0:
        return np.inf

    cumulative = 0.0
    for year in range(1, max_years + 1):
        discounted = annual_saving / ((1 + discount_rate) ** year)
        cumulative += discounted
        if cumulative >= capex:
            return float(year)

    return np.inf


def is_upgrade_recommended(
    payback_years: float,
    max_payback_threshold: float = 20.0,
    carbon_abatement_cost: Optional[float] = None,
    max_abatement_cost: Optional[float] = None
) -> bool:
    """
    Determine if an upgrade is cost-effective and recommended.

    Args:
        payback_years: Calculated payback period
        max_payback_threshold: Maximum acceptable payback (years)
        carbon_abatement_cost: Cost per tonne CO2 saved (optional)
        max_abatement_cost: Maximum acceptable abatement cost (optional)

    Returns:
        True if upgrade is recommended based on cost-effectiveness
    """
    # Check payback threshold
    if pd.isna(payback_years) or not np.isfinite(payback_years):
        return False

    if payback_years > max_payback_threshold:
        return False

    # Optionally check carbon abatement cost
    if carbon_abatement_cost is not None and max_abatement_cost is not None:
        if pd.isna(carbon_abatement_cost) or carbon_abatement_cost > max_abatement_cost:
            return False

    return True


def calculate_carbon_abatement_cost(
    capex: float,
    annual_co2_saving_kg: float,
    years: int = 20
) -> float:
    """
    Calculate cost per tonne of CO2 abated.

    Args:
        capex: Capital cost
        annual_co2_saving_kg: Annual CO2 saving in kg
        years: Assessment horizon

    Returns:
        Cost per tonne CO2 (£/tCO2)
    """
    if annual_co2_saving_kg <= 0 or years <= 0:
        return np.inf

    total_co2_tonnes = (annual_co2_saving_kg * years) / 1000
    if total_co2_tonnes <= 0:
        return np.inf

    return capex / total_co2_tonnes


# ==============================================================================
# FLOW TEMPERATURE REDUCTION UTILITIES
# ==============================================================================

def calculate_flow_temp_reduction(
    measures: List[str],
    measure_savings: Optional[Dict] = None
) -> float:
    """
    Calculate total flow temperature reduction from a set of measures.

    Args:
        measures: List of measure IDs
        measure_savings: Measure savings config (loaded if None)

    Returns:
        Total flow temperature reduction in K
    """
    if measure_savings is None:
        measure_savings = get_measure_savings()

    total_reduction = 0.0

    for measure in measures:
        # Handle aliases
        lookup = 'radiator_upsizing' if measure == 'emitter_upgrades' else measure
        reduction = measure_savings.get(lookup, {}).get('flow_temp_reduction_k', 0)
        if reduction:
            total_reduction += float(reduction)

    return total_reduction


def calculate_combined_energy_saving(
    measures: List[str],
    baseline_kwh: float,
    wall_type: str = 'Solid',
    measure_savings: Optional[Dict] = None
) -> Tuple[float, float]:
    """
    Calculate combined energy savings using diminishing returns formula.

    Args:
        measures: List of measure IDs
        baseline_kwh: Baseline annual consumption
        wall_type: Property wall type (affects wall insulation savings)
        measure_savings: Measure savings config (loaded if None)

    Returns:
        Tuple of (total_saving_kwh, remaining_demand_kwh)
    """
    if measure_savings is None:
        measure_savings = get_measure_savings()

    remaining_fraction = 1.0

    for measure in measures:
        cfg = measure_savings.get(measure, {})

        if measure == 'wall_insulation':
            if wall_type == 'Cavity':
                pct = cfg.get('cavity_kwh_saving_pct', 0.20)
            else:
                pct = cfg.get('solid_kwh_saving_pct', 0.30)
        else:
            pct = cfg.get('kwh_saving_pct', 0)

        if pct:
            remaining_fraction *= (1 - pct)

    total_saving = baseline_kwh * (1 - remaining_fraction)
    remaining = baseline_kwh * remaining_fraction

    return total_saving, remaining


# ==============================================================================
# AGGREGATION UTILITIES
# ==============================================================================

def summarize_series(series: pd.Series) -> Dict[str, float]:
    """
    Return common summary statistics for a numeric series.

    Args:
        series: Numeric series

    Returns:
        Dictionary with mean, median, p10, p90, min, max
    """
    clean = series.replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) == 0:
        return {k: np.nan for k in ['mean', 'median', 'p10', 'p90', 'min', 'max']}

    return {
        'mean': float(clean.mean()),
        'median': float(clean.median()),
        'p10': float(clean.quantile(0.10)),
        'p90': float(clean.quantile(0.90)),
        'min': float(clean.min()),
        'max': float(clean.max()),
    }


def calculate_cost_effectiveness_summary(
    property_df: pd.DataFrame,
    payback_threshold: float = 20.0
) -> Dict[str, Any]:
    """
    Calculate cost-effectiveness summary for a set of property upgrades.

    Args:
        property_df: DataFrame with payback_years column
        payback_threshold: Maximum payback for cost-effective classification

    Returns:
        Dictionary with cost-effectiveness metrics
    """
    total = len(property_df)
    if total == 0:
        return {}

    numeric_df = property_df.replace({np.inf: np.nan, -np.inf: np.nan})

    # Count by cost-effectiveness
    finite_paybacks = numeric_df['payback_years'].dropna()
    cost_effective = finite_paybacks[finite_paybacks <= payback_threshold]
    not_cost_effective_finite = finite_paybacks[finite_paybacks > payback_threshold]
    infinite_payback = total - len(finite_paybacks)

    return {
        'total_properties': total,
        'cost_effective_count': len(cost_effective),
        'cost_effective_pct': len(cost_effective) / total * 100,
        'marginal_count': len(not_cost_effective_finite),
        'marginal_pct': len(not_cost_effective_finite) / total * 100,
        'not_cost_effective_count': infinite_payback,
        'not_cost_effective_pct': infinite_payback / total * 100,
        'avg_payback_cost_effective': cost_effective.mean() if len(cost_effective) > 0 else np.nan,
        'median_payback_cost_effective': cost_effective.median() if len(cost_effective) > 0 else np.nan,
        'payback_threshold_years': payback_threshold,
    }
