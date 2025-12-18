"""
Configuration loader for Heat Street EPC Analysis project.
"""

import os
import yaml
from pathlib import Path
from typing import Dict, Any

# Get project root directory
PROJECT_ROOT = Path(__file__).parent.parent

# Define paths
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
DATA_RAW_DIR = DATA_DIR / "raw"
DATA_PROCESSED_DIR = DATA_DIR / "processed"
DATA_SUPPLEMENTARY_DIR = DATA_DIR / "supplementary"
DATA_OUTPUTS_DIR = DATA_DIR / "outputs"


def load_config(config_file: str = "config.yaml") -> Dict[str, Any]:
    """
    Load configuration from YAML file.

    Args:
        config_file: Name of the configuration file

    Returns:
        Dictionary containing configuration parameters
    """
    config_path = CONFIG_DIR / config_file

    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    return config


def get_london_boroughs() -> list:
    """Get list of London boroughs from config."""
    config = load_config()
    return config['geography']['boroughs']


def get_property_filters() -> Dict[str, Any]:
    """Get property filter criteria from config."""
    config = load_config()
    return config['property_filters']


def get_data_quality_thresholds() -> Dict[str, Any]:
    """Get data quality thresholds from config."""
    config = load_config()
    return config['data_quality']


def get_scenario_definitions() -> Dict[str, Any]:
    """Get scenario definitions from config."""
    config = load_config()
    return config['scenarios']


def get_cost_assumptions() -> Dict[str, float]:
    """Get cost assumptions from config."""
    config = load_config()
    return config['costs']


def get_cost_rules() -> Dict[str, Any]:
    """Get structured costing rules (basis, caps, rationale) from config."""
    config = load_config()
    return config.get('cost_rules', {})


def get_measure_savings() -> Dict[str, Any]:
    """Get measure savings assumptions from config."""
    config = load_config()
    return config.get('measure_savings', {})


def get_heat_network_params() -> Dict[str, Any]:
    """Get heat network parameters from config."""
    config = load_config()
    return config.get('heat_network', {})


def get_financial_params() -> Dict[str, Any]:
    """Get financial parameters (discount rate, price scenarios) from config."""
    config = load_config()
    financial = config.get('financial', {})

    # Validate analysis horizon to avoid silent defaults
    horizon = financial.get('analysis_horizon_years')
    if horizon is None:
        raise ValueError(
            "Missing analysis horizon in financial parameters (config['financial']['analysis_horizon_years'])."
        )

    try:
        horizon_value = float(horizon)
    except (TypeError, ValueError) as exc:
        raise ValueError("Analysis horizon must be numeric and greater than zero.") from exc

    if horizon_value <= 0:
        raise ValueError("Analysis horizon must be greater than zero.")

    financial['analysis_horizon_years'] = horizon_value
    return financial


def get_analysis_horizon_years() -> float:
    """Return validated analysis horizon (years) from financial parameters."""
    return get_financial_params()['analysis_horizon_years']


def get_cost_effectiveness_params() -> Dict[str, Any]:
    """Get cost-effectiveness threshold parameters from config."""
    config = load_config()
    financial = config.get('financial', {})
    ce_params = financial.get('cost_effectiveness', {})

    return {
        'max_payback_years': ce_params.get('max_payback_years', 20),
        'max_carbon_abatement_cost': ce_params.get('max_carbon_abatement_cost', 300),
    }


def get_eligibility_params() -> Dict[str, Any]:
    """Get eligibility parameters for ASHP and heat networks."""
    config = load_config()
    return config.get('eligibility', {})


def get_uncertainty_params() -> Dict[str, Any]:
    """Get uncertainty parameters from config."""
    config = load_config()
    return config.get('uncertainty', {})


def get_performance_gap_factors(variant: str = "central") -> Dict[str, Any]:
    """Get EPC performance gap (prebound) factors by variant.

    Args:
        variant: Which variant to return. Use "all" to retrieve every variant.

    Returns:
        Dictionary mapping EPC band → factor for the requested variant, or all variants.
    """
    config = load_config()
    prebound_cfg = config.get('methodological_adjustments', {}).get('prebound_effect', {})
    factors_by_variant = prebound_cfg.get('performance_gap_factors', {})

    if not factors_by_variant:
        raise ValueError(
            "Missing performance gap factors in config.methodological_adjustments.prebound_effect.performance_gap_factors."
        )

    if variant in {"all", None}:
        return factors_by_variant

    if variant not in factors_by_variant:
        available = ", ".join(sorted(factors_by_variant))
        raise ValueError(f"Unknown performance gap variant '{variant}'. Available: {available}")

    return factors_by_variant[variant]


def get_default_performance_gap_variant() -> str:
    """Return configured default performance gap variant (prebound scenario)."""
    config = load_config()
    return (
        config.get('methodological_adjustments', {})
        .get('prebound_effect', {})
        .get('default_variant', 'central')
    )


def get_anomaly_detection_params() -> Dict[str, Any]:
    """Get EPC anomaly detection thresholds from config."""
    config = load_config()
    return config.get('anomaly_detection', {})


def get_energy_prices(scenario: str = 'current') -> Dict[str, float]:
    """
    Get energy prices for a given scenario.

    Args:
        scenario: One of 'current', 'projected_2030', 'projected_2040'
                  or a price_scenario key from financial config

    Returns:
        Dictionary with gas, electricity prices in £/kWh
    """
    config = load_config()

    # Try legacy energy_prices first
    if scenario in config.get('energy_prices', {}):
        return config['energy_prices'][scenario]

    # Try new financial.price_scenarios
    price_scenarios = config.get('financial', {}).get('price_scenarios', {})
    if scenario in price_scenarios:
        return price_scenarios[scenario]

    # Default to current prices
    return config.get('energy_prices', {}).get('current', {
        'gas': 0.0624,
        'electricity': 0.245
    })


def get_heat_pump_cop_curve() -> Dict[str, Any]:
    """Return the configured COP/SPF vs flow temperature curve.

    The curve should include temperature breakpoints (°C) and performance
    variants (central/low/high) for interpolation. Missing variants default to
    the central curve.
    """
    config = load_config()
    hp_cfg = config.get('heat_pump', {})
    curve = hp_cfg.get('cop_vs_flow_temp') or hp_cfg.get('cop_curve')

    if not isinstance(curve, dict):
        raise ValueError("Missing heat pump COP curve configuration.")

    temps = curve.get('temperatures_c')
    if not temps or not isinstance(temps, (list, tuple)):
        raise ValueError("Heat pump COP curve requires 'temperatures_c' breakpoints.")

    def _validate_variant(name: str) -> Any:
        values = curve.get(name)
        if values is None:
            return None
        if len(values) != len(temps):
            raise ValueError(
                f"Heat pump COP curve '{name}' length {len(values)} does not match temperatures length {len(temps)}."
            )
        return values

    central = _validate_variant('central_spf') or _validate_variant('central_cop')
    if central is None:
        raise ValueError("Heat pump COP curve missing central performance values.")

    low = _validate_variant('low_spf') or _validate_variant('low_cop') or central
    high = _validate_variant('high_spf') or _validate_variant('high_cop') or central

    return {
        'temperatures_c': temps,
        'central': central,
        'low': low,
        'high': high,
    }


def ensure_directories():
    """Create necessary directories if they don't exist."""
    directories = [
        DATA_RAW_DIR,
        DATA_PROCESSED_DIR,
        DATA_SUPPLEMENTARY_DIR,
        DATA_OUTPUTS_DIR,
        DATA_OUTPUTS_DIR / "figures",
        DATA_OUTPUTS_DIR / "reports",
        DATA_OUTPUTS_DIR / "maps",
    ]

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    # Test configuration loading
    config = load_config()
    print("Configuration loaded successfully!")
    print(f"Project: {config['project']['name']}")
    print(f"Number of London boroughs: {len(config['geography']['boroughs'])}")

    # Ensure directories exist
    ensure_directories()
    print("Directory structure verified!")
