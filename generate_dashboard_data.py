#!/usr/bin/env python3
"""
Generate Dashboard Data

This script generates the dashboard-data.json file for the React dashboard.
It consolidates all analysis outputs and addresses all 12 CLIENT_QUESTIONS sections.

Usage:
    python generate_dashboard_data.py [--from-outputs] [--sample]

Options:
    --from-outputs    Load data from existing analysis outputs in data/outputs/
    --sample          Generate sample data (useful for development/testing)

The generated file is placed in:
    - data/outputs/dashboard/dashboard-data.json
    - dashboard/public/dashboard-data.json (for React app)
"""

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Dict, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

# Use loguru if available, otherwise fall back to standard logging
try:
    from loguru import logger
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    logger = logging.getLogger(__name__)


def load_analysis_outputs() -> Dict:
    """Load all available analysis outputs from data/outputs/"""
    outputs_dir = Path("data/outputs")
    processed_dir = Path("data/processed")

    archetype_results = None
    scenario_results = None
    readiness_summary = None
    pathway_summary = None
    borough_breakdown = None
    case_street_summary = None
    subsidy_results = None
    df_validated = None
    load_profile_summary = None
    tipping_point_curve = None
    retrofit_packages_summary = None

    try:
        import pandas as pd

        # Load validated data
        validated_file = processed_dir / "epc_london_validated.parquet"
        if validated_file.exists():
            df_validated = pd.read_parquet(validated_file)
            logger.info(f"Loaded validated data: {len(df_validated)} properties")
        else:
            validated_file = processed_dir / "epc_london_validated.csv"
            if validated_file.exists():
                df_validated = pd.read_csv(validated_file, low_memory=False)
                logger.info(f"Loaded validated data: {len(df_validated)} properties")

        # Load archetype results
        archetype_file = outputs_dir / "archetype_analysis_results.json"
        if archetype_file.exists():
            with open(archetype_file) as f:
                archetype_results = json.load(f)
            logger.info("Loaded archetype analysis results")

        # Load scenario results
        scenario_file = outputs_dir / "scenario_modeling_results.json"
        if scenario_file.exists():
            with open(scenario_file) as f:
                scenario_results = json.load(f)
            logger.info("Loaded scenario modeling results")

        # Load readiness summary
        readiness_file = outputs_dir / "reports/retrofit_readiness_summary.json"
        if readiness_file.exists():
            with open(readiness_file) as f:
                readiness_summary = json.load(f)
            logger.info("Loaded retrofit readiness summary")

        # Load pathway summary
        pathway_file = outputs_dir / "pathway_suitability_by_tier.csv"
        if pathway_file.exists():
            pathway_summary = pd.read_csv(pathway_file)
            logger.info("Loaded pathway summary")

        # Load borough breakdown
        borough_file = outputs_dir / "borough_breakdown.csv"
        if borough_file.exists():
            borough_breakdown = pd.read_csv(borough_file)
            logger.info("Loaded borough breakdown")

        # Load load profiles
        load_profiles_file = outputs_dir / "pathway_load_profile_summary.csv"
        if load_profiles_file.exists():
            load_profile_summary = pd.read_csv(load_profiles_file)
            logger.info("Loaded load profile summary")

        # Load tipping point curve
        tipping_point_file = outputs_dir / "fabric_tipping_point_curve.csv"
        if tipping_point_file.exists():
            tipping_point_curve = pd.read_csv(tipping_point_file)
            logger.info("Loaded tipping point curve")

        # Load retrofit packages
        retrofit_file = outputs_dir / "retrofit_packages_summary.csv"
        if retrofit_file.exists():
            retrofit_packages_summary = pd.read_csv(retrofit_file)
            logger.info("Loaded retrofit packages summary")

    except ImportError:
        logger.warning("pandas not available, cannot load analysis outputs")

    return {
        "archetype_results": archetype_results,
        "scenario_results": scenario_results,
        "readiness_summary": readiness_summary,
        "pathway_summary": pathway_summary,
        "borough_breakdown": borough_breakdown,
        "case_street_summary": case_street_summary,
        "subsidy_results": subsidy_results,
        "df_validated": df_validated,
        "load_profile_summary": load_profile_summary,
        "tipping_point_curve": tipping_point_curve,
        "retrofit_packages_summary": retrofit_packages_summary,
    }


def generate_sample_dashboard_data() -> Dict:
    """Generate sample dashboard data matching the expected schema.

    This data is based on typical London Edwardian terraced housing analysis
    and addresses all 12 CLIENT_QUESTIONS sections.
    """
    return {
        # Section 1: EPC Band Distribution
        "epcBandData": [
            {"band": "A", "count": 2393, "percentage": 0.3, "color": "#1a472a"},
            {"band": "B", "count": 23691, "percentage": 3.4, "color": "#2d6a4f"},
            {"band": "C", "count": 200312, "percentage": 28.4, "color": "#40916c"},
            {"band": "D", "count": 370061, "percentage": 52.5, "color": "#f4a261"},
            {"band": "E", "count": 95136, "percentage": 13.5, "color": "#e76f51"},
            {"band": "F", "count": 9836, "percentage": 1.4, "color": "#d62828"},
            {"band": "G", "count": 3054, "percentage": 0.4, "color": "#9d0208"},
        ],
        # Case street comparison
        "epcComparisonData": [
            {"band": "A", "shakespeareCrescent": 0.0, "londonAverage": 0.3},
            {"band": "B", "shakespeareCrescent": 0.0, "londonAverage": 3.4},
            {"band": "C", "shakespeareCrescent": 57.1, "londonAverage": 28.4},
            {"band": "D", "shakespeareCrescent": 42.9, "londonAverage": 52.5},
            {"band": "E", "shakespeareCrescent": 0.0, "londonAverage": 13.5},
            {"band": "F", "shakespeareCrescent": 0.0, "londonAverage": 1.4},
            {"band": "G", "shakespeareCrescent": 0.0, "londonAverage": 0.4},
        ],
        # Section 1: Wall Types
        "wallTypeData": [
            {"type": "Solid Brick", "count": 440296, "percentage": 62.5, "insulated": 3.2},
            {"type": "Cavity", "count": 246368, "percentage": 35.0, "insulated": 68.4},
            {"type": "Timber Frame", "count": 14090, "percentage": 2.0, "insulated": 12.1},
            {"type": "Other", "count": 3729, "percentage": 0.5, "insulated": 8.9},
        ],
        # Section 1: Heating Systems
        "heatingSystemData": [
            {"name": "Gas Boiler", "value": 95.8, "count": 675096},
            {"name": "Electric", "value": 2.8, "count": 19726},
            {"name": "Oil/Solid Fuel", "value": 0.9, "count": 6340},
            {"name": "Other", "value": 0.5, "count": 3321},
        ],
        # Section 1 & 4: Glazing (with U-values for window comparison)
        "glazingData": [
            {"type": "Single", "share": 3.9, "uValue": 4.8, "count": 27475, "percentage": 3.9},
            {"type": "Double", "share": 81.2, "uValue": 2.0, "count": 572003, "percentage": 81.2},
            {"type": "Triple", "share": 0.1, "uValue": 1.0, "count": 704, "percentage": 0.1},
            {"type": "Unknown", "share": 14.8, "uValue": 2.8, "count": 104301, "percentage": 14.8},
        ],
        # Section 1: Loft Insulation
        "loftInsulationData": [
            {"thickness": "None", "properties": 162000},
            {"thickness": "100-200mm", "properties": 444000},
            {"thickness": "≥270mm", "properties": 98000},
        ],
        # Section 6: Scenario Modeling
        "scenarioData": [
            {"scenario": "Baseline", "capitalCost": 0, "costPerProperty": 0, "co2Reduction": 0, "billSavings": 0, "paybackYears": 0},
            {"scenario": "Fabric Only", "capitalCost": 20012, "costPerProperty": 28407, "co2Reduction": 1762631, "billSavings": 853, "paybackYears": 35.0},
            {"scenario": "Heat Pump", "capitalCost": 29924, "costPerProperty": 42477, "co2Reduction": 3471850, "billSavings": 1681, "paybackYears": 28.1},
            {"scenario": "Heat Network", "capitalCost": 23534, "costPerProperty": 33407, "co2Reduction": 1762631, "billSavings": 853, "paybackYears": 41.5},
            {"scenario": "Hybrid (spatial mix: Heat Pumps + Heat Networks)", "capitalCost": 20012, "costPerProperty": 28407, "co2Reduction": 1281914, "billSavings": 621, "paybackYears": 47.2},
        ],
        # Section 6 & 10: Heat Network Tiers
        "tierData": [
            {"tier": "Tier 1: Adjacent", "properties": 1270, "percentage": 0.2, "recommendation": "DH (existing)"},
            {"tier": "Tier 2: Near DH", "properties": 2247, "percentage": 0.3, "recommendation": "DH (extension)"},
            {"tier": "Tier 3: High Density", "properties": 232472, "percentage": 33.0, "recommendation": "DH (extension)"},
            {"tier": "Tier 4: Medium Density", "properties": 239077, "percentage": 33.9, "recommendation": "Heat Pump"},
            {"tier": "Tier 5: Low Density", "properties": 229417, "percentage": 32.6, "recommendation": "Heat Pump"},
        ],
        # Section 2: Retrofit Readiness
        "retrofitReadinessData": [
            {"tier": "Tier 1 (Ready)", "properties": 56344, "percentage": 8.0, "avgCost": 15420},
            {"tier": "Tier 2 (Minor Work)", "properties": 178179, "percentage": 25.3, "avgCost": 20280},
            {"tier": "Tier 3 (Moderate Work)", "properties": 251438, "percentage": 35.7, "avgCost": 24650},
            {"tier": "Tier 4 (Major Work)", "properties": 162449, "percentage": 23.1, "avgCost": 29840},
            {"tier": "Tier 5 (Extensive Work)", "properties": 56073, "percentage": 7.9, "avgCost": 38720},
        ],
        # Section 2 & 3: Intervention Requirements
        "interventionData": [
            {"intervention": "Radiator Upsizing", "percentage": 96.3, "count": 678419},
            {"intervention": "Loft Insulation", "percentage": 86.1, "count": 606560},
            {"intervention": "Wall Insulation", "percentage": 77.4, "count": 545270},
            {"intervention": "Floor Insulation", "percentage": 68.2, "count": 480458},
            {"intervention": "Draught Proofing", "percentage": 52.8, "count": 371967},
            {"intervention": "Window Upgrade", "percentage": 21.5, "count": 151465},
        ],
        # Section 11: Borough Data
        "boroughData": [
            {"borough": "Newham", "code": "E09000025", "count": 89234, "meanEPC": 62.1, "energy": 238},
            {"borough": "Croydon", "code": "E09000008", "count": 76512, "meanEPC": 64.3, "energy": 227},
            {"borough": "Lambeth", "code": "E09000022", "count": 68947, "meanEPC": 63.8, "energy": 230},
            {"borough": "Wandsworth", "code": "E09000032", "count": 64823, "meanEPC": 65.2, "energy": 223},
            {"borough": "Lewisham", "code": "E09000023", "count": 58392, "meanEPC": 63.4, "energy": 232},
            {"borough": "Southwark", "code": "E09000028", "count": 52167, "meanEPC": 62.9, "energy": 235},
            {"borough": "Ealing", "code": "E09000009", "count": 48934, "meanEPC": 64.7, "energy": 225},
            {"borough": "Brent", "code": "E09000005", "count": 45621, "meanEPC": 63.2, "energy": 233},
        ],
        # Section 7: Confidence Bands (Uncertainty)
        "confidenceBandsData": [
            {"stage": "Baseline", "estimate": 18500, "lower": 15725, "upper": 21275},
            {"stage": "Loft", "estimate": 16200, "lower": 13770, "upper": 18630},
            {"stage": "Walls", "estimate": 13800, "lower": 11730, "upper": 15870},
            {"stage": "Floor", "estimate": 12500, "lower": 10625, "upper": 14375},
            {"stage": "Full Retrofit", "estimate": 11600, "lower": 9860, "upper": 13340},
        ],
        # Section 10: Sensitivity Analysis
        "sensitivityData": [
            {"parameter": "Gas price", "lowImpact": 650, "highImpact": 1100, "range": 450},
            {"parameter": "Electricity price", "lowImpact": 600, "highImpact": 1050, "range": 450},
            {"parameter": "Heat pump COP", "lowImpact": 700, "highImpact": 950, "range": 250},
            {"parameter": "Air tightness", "lowImpact": 750, "highImpact": 880, "range": 130},
            {"parameter": "Fabric cost", "lowImpact": 775, "highImpact": 850, "range": 75},
        ],
        # Section 9: Grid Peak Data
        "gridPeakData": [
            {"scenario": "Baseline", "peak": 5.2, "average": 3.2},
            {"scenario": "Fabric Only", "peak": 4.4, "average": 2.7},
            {"scenario": "Heat Pump", "peak": 3.1, "average": 1.9},
            {"scenario": "Heat Network", "peak": 0.8, "average": 0.45},
        ],
        # Section 9: Indoor Climate Data
        "indoorClimateData": [
            {"hour": "06:00", "temperature": 17.5, "humidity": 62},
            {"hour": "09:00", "temperature": 18.9, "humidity": 58},
            {"hour": "12:00", "temperature": 19.6, "humidity": 55},
            {"hour": "15:00", "temperature": 20.4, "humidity": 53},
            {"hour": "18:00", "temperature": 20.1, "humidity": 54},
            {"hour": "21:00", "temperature": 19.3, "humidity": 57},
        ],
        # Section 8: Cost Curve (Tipping Point)
        "costCurveData": [
            {"measure": "Baseline", "cost": 0, "savings": 0},
            {"measure": "Tier 1", "cost": 2150, "savings": 620},
            {"measure": "Tier 2", "cost": 4280, "savings": 1080},
            {"measure": "Tier 3", "cost": 7650, "savings": 1420},
            {"measure": "Tier 4", "cost": 12840, "savings": 1675},
            {"measure": "Tier 5", "cost": 18720, "savings": 1810},
        ],
        # Section 5: Cost-Benefit Tiers
        "costBenefitTierData": [
            {"tier": "Tier 1", "tierLabel": "Ready Now", "properties": 56344, "share": 8.0, "fabricCost": 2150, "totalCost": 15420, "heatDemand": 108, "reduction": 142, "reductionPct": 56.8, "efficiency": 29.3},
            {"tier": "Tier 2", "tierLabel": "Minor Work", "properties": 178179, "share": 25.3, "fabricCost": 4280, "totalCost": 20280, "heatDemand": 125, "reduction": 125, "reductionPct": 50.0, "efficiency": 21.2},
            {"tier": "Tier 3", "tierLabel": "Moderate Work", "properties": 251438, "share": 35.7, "fabricCost": 7650, "totalCost": 24650, "heatDemand": 145, "reduction": 105, "reductionPct": 42.0, "efficiency": 9.2},
            {"tier": "Tier 4", "tierLabel": "Major Work", "properties": 162449, "share": 23.1, "fabricCost": 12840, "totalCost": 29840, "heatDemand": 162, "reduction": 88, "reductionPct": 35.2, "efficiency": 7.8},
            {"tier": "Tier 5", "tierLabel": "Extensive Work", "properties": 56073, "share": 7.9, "fabricCost": 18720, "totalCost": 38720, "heatDemand": 178, "reduction": 72, "reductionPct": 28.8, "efficiency": 6.9},
        ],
        # Section 2: Cost Levers
        "costLeversData": [
            {"lever": "Shared ground loops", "impact": 2100, "difficulty": "Medium"},
            {"lever": "Supply chain optimisation", "impact": 1800, "difficulty": "Low"},
            {"lever": "Bulk procurement", "impact": 1200, "difficulty": "Low"},
            {"lever": "Standardised designs", "impact": 800, "difficulty": "Low"},
            {"lever": "Street-by-street delivery", "impact": 200, "difficulty": "Medium"},
        ],
        # Summary Statistics
        # NOTE: totalProperties is now derived from EPC band counts (sum of all bands)
        # This ensures consistency with the data being displayed
        "summaryStats": {
            "totalProperties": sum(band["count"] for band in [
                {"band": "A", "count": 2393},
                {"band": "B", "count": 23691},
                {"band": "C", "count": 200312},
                {"band": "D", "count": 370061},
                {"band": "E", "count": 95136},
                {"band": "F", "count": 9836},
                {"band": "G", "count": 3054},
            ]),  # Derived from epcBandData above
            "avgSAPScore": 63.4,
            "meanSAPScore": 63.4,
            "wallInsulationRate": 33.7,
            "dhViableProperties": 235989,
            "gasBoilerDependency": 95.8,
            "belowBandC": 67.8,
            "costAdvantageDHvsHP": 9070,
            "peakGridReduction": 85,
            "optimalInvestmentPoint": 4500,
            "meanFabricCost": 7710,
            "meanTotalRetrofitCost": 22177,
            "heatDemandReduction": 37.4,
            "readyOrNearReady": 33.3,
            "commonEpcBand": "D",
        },
    }


def generate_dashboard_data(from_outputs: bool = False, sample: bool = False) -> Path:
    """Generate dashboard data and save to output files.

    Args:
        from_outputs: Load data from existing analysis outputs
        sample: Generate sample data

    Returns:
        Path to the generated dashboard-data.json file
    """
    logger.info("Generating dashboard data...")

    # Create output directories
    outputs_dir = Path("data/outputs/dashboard")
    outputs_dir.mkdir(parents=True, exist_ok=True)

    public_dir = Path("dashboard/public")
    public_dir.mkdir(parents=True, exist_ok=True)

    if from_outputs:
        logger.info("Loading from analysis outputs...")
        data_sources = load_analysis_outputs()

        # Use the DashboardDataBuilder
        try:
            from src.reporting.dashboard_data_builder import DashboardDataBuilder

            builder = DashboardDataBuilder()
            dataset = builder.build_dataset(
                archetype_results=data_sources.get("archetype_results"),
                scenario_results=data_sources.get("scenario_results"),
                readiness_summary=data_sources.get("readiness_summary"),
                pathway_summary=data_sources.get("pathway_summary"),
                borough_breakdown=data_sources.get("borough_breakdown"),
                case_street_summary=data_sources.get("case_street_summary"),
                subsidy_results=data_sources.get("subsidy_results"),
                df_validated=data_sources.get("df_validated"),
                load_profile_summary=data_sources.get("load_profile_summary"),
                tipping_point_curve=data_sources.get("tipping_point_curve"),
                retrofit_packages_summary=data_sources.get("retrofit_packages_summary"),
            )
        except ImportError as e:
            logger.warning(f"Could not import DashboardDataBuilder: {e}")
            logger.info("Falling back to sample data")
            dataset = generate_sample_dashboard_data()
    else:
        logger.info("Generating sample dashboard data...")
        dataset = generate_sample_dashboard_data()

    # Write to output files
    output_path = outputs_dir / "dashboard-data.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, default=str)
    logger.info(f"Saved dashboard data to {output_path}")

    # Copy to dashboard public directory
    public_path = public_dir / "dashboard-data.json"
    shutil.copy2(output_path, public_path)
    logger.info(f"Copied dashboard data to {public_path}")

    # Log summary
    data_arrays = [k for k in dataset.keys() if isinstance(dataset.get(k), list)]
    logger.info(f"Dashboard data generated with {len(data_arrays)} data arrays")
    for arr in data_arrays:
        count = len(dataset[arr]) if isinstance(dataset[arr], list) else 1
        logger.info(f"  • {arr}: {count} items")

    return output_path


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate dashboard data for the Heat Street EPC React dashboard"
    )
    parser.add_argument(
        "--from-outputs",
        action="store_true",
        help="Load data from existing analysis outputs in data/outputs/",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Generate sample data (default if no outputs available)",
    )
    args = parser.parse_args()

    output_path = generate_dashboard_data(
        from_outputs=args.from_outputs,
        sample=args.sample,
    )

    print(f"\n✓ Dashboard data generated successfully!")
    print(f"  Output: {output_path}")
    print(f"  Public: dashboard/public/dashboard-data.json")
    print(f"\nTo start the dashboard:")
    print(f"  cd dashboard && npm install && npm run dev")


if __name__ == "__main__":
    main()
