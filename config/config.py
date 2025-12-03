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
