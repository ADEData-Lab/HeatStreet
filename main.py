"""
Main Pipeline for Heat Street EPC Analysis

Orchestrates the complete analysis workflow from data acquisition to reporting.
"""

import argparse
from pathlib import Path
from loguru import logger
import sys

# Add src directory to path
sys.path.append(str(Path(__file__).parent))

from config.config import load_config, ensure_directories
from src.acquisition.epc_downloader import EPCDownloader
from src.cleaning.data_validator import EPCDataValidator
from src.analysis.archetype_analysis import ArchetypeAnalyzer
from src.modeling.scenario_model import ScenarioModeler
from src.spatial.heat_network_analysis import HeatNetworkAnalyzer
from src.reporting.visualizations import ReportGenerator


def setup_logging(log_file: Path = None):
    """
    Configure logging for the pipeline.

    Args:
        log_file: Optional path to log file
    """
    logger.remove()  # Remove default handler

    # Console logging
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="INFO"
    )

    # File logging
    if log_file:
        logger.add(
            log_file,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
            level="DEBUG",
            rotation="10 MB"
        )


def run_acquisition_phase(args):
    """Run data acquisition phase."""
    logger.info("="*70)
    logger.info("PHASE 1: DATA ACQUISITION")
    logger.info("="*70)

    downloader = EPCDownloader()

    if args.download:
        # Download bulk data
        downloader.download_bulk_data()
    else:
        # Load existing local data
        df = downloader.load_local_data()

        if not df.empty:
            # Apply initial filters
            df_filtered = downloader.apply_initial_filters(df)

            # Extract case street data
            case_df = downloader.extract_shakespeare_crescent(df_filtered)

            # Save processed data
            downloader.save_processed_data(df_filtered)

            logger.info(f"✓ Acquisition complete: {len(df_filtered):,} properties")
            return df_filtered
        else:
            logger.error("No data available. Please download EPC data first.")
            return None


def run_cleaning_phase(args):
    """Run data cleaning and validation phase."""
    logger.info("\n" + "="*70)
    logger.info("PHASE 2: DATA CLEANING & VALIDATION")
    logger.info("="*70)

    from config.config import DATA_RAW_DIR, DATA_PROCESSED_DIR
    input_file = DATA_RAW_DIR / "epc_london_filtered.csv"

    if not input_file.exists():
        logger.error(f"Input file not found: {input_file}")
        logger.info("Please run acquisition phase first")
        return None

    import pandas as pd
    df = pd.read_csv(input_file, low_memory=False)

    validator = EPCDataValidator()
    df_validated, report = validator.validate_dataset(df)

    # Save validated data
    output_file = DATA_PROCESSED_DIR / "epc_london_validated.csv"
    df_validated.to_csv(output_file, index=False)

    parquet_file = output_file.with_suffix('.parquet')
    df_validated.to_parquet(parquet_file, index=False)

    # Save validation report
    validator.save_validation_report()

    logger.info(f"✓ Validation complete: {len(df_validated):,} properties passed")
    return df_validated


def run_analysis_phase(args):
    """Run archetype characterization analysis."""
    logger.info("\n" + "="*70)
    logger.info("PHASE 3: ARCHETYPE CHARACTERIZATION")
    logger.info("="*70)

    from config.config import DATA_PROCESSED_DIR
    import pandas as pd

    input_file = DATA_PROCESSED_DIR / "epc_london_validated.csv"
    if not input_file.exists():
        logger.error("Validated data not found. Run cleaning phase first.")
        return None

    df = pd.read_csv(input_file, low_memory=False)

    analyzer = ArchetypeAnalyzer()
    results = analyzer.analyze_archetype(df)
    analyzer.save_results()

    logger.info("✓ Archetype analysis complete")
    return results


def run_modeling_phase(args):
    """Run comprehensive modeling and analysis phase."""
    logger.info("\n" + "="*70)
    logger.info("PHASE 4: COMPREHENSIVE MODELING & ANALYSIS")
    logger.info("="*70)

    from config.config import DATA_PROCESSED_DIR
    import pandas as pd
    from src.analysis.fabric_analysis import FabricAnalyzer
    from src.analysis.retrofit_packages import RetrofitPackageAnalyzer
    from src.modeling.pathway_model import PathwayModeler
    from src.analysis.load_profiles import LoadProfileGenerator
    from src.analysis.penetration_sensitivity import PenetrationSensitivityAnalyzer
    from src.analysis.fabric_tipping_point import FabricTippingPointAnalyzer

    input_file = DATA_PROCESSED_DIR / "epc_london_validated.csv"
    if not input_file.exists():
        # Try parquet
        input_file = DATA_PROCESSED_DIR / "epc_london_validated.parquet"
        if not input_file.exists():
            logger.error("Validated data not found. Run cleaning phase first.")
            return None

    logger.info(f"Loading data from: {input_file}")
    if input_file.suffix == '.parquet':
        df = pd.read_parquet(input_file)
    else:
        df = pd.read_csv(input_file, low_memory=False)

    logger.info(f"Loaded {len(df):,} properties")

    results = {}

    # ---- Fabric Analysis (Section 1 & 7) ----
    logger.info("\n📊 Running fabric analysis...")
    fabric_analyzer = FabricAnalyzer()
    fabric_results = fabric_analyzer.run_full_analysis(df)
    results['fabric'] = fabric_results
    logger.info("✓ Fabric analysis complete")

    # ---- Retrofit Packages Analysis (Section 2, 3, 4) ----
    logger.info("\n📦 Running retrofit packages analysis...")
    package_analyzer = RetrofitPackageAnalyzer()
    package_results = package_analyzer.analyze_all_packages(df)
    package_summary = package_analyzer.generate_package_summary(package_results)
    window_comparison = package_analyzer.generate_window_comparison()
    package_analyzer.export_results(package_results, package_summary, window_comparison)
    results['packages'] = {'results': package_results, 'summary': package_summary}
    logger.info("✓ Retrofit packages analysis complete")

    # ---- Fabric Tipping Point (Section 8) ----
    logger.info("\n📈 Running fabric tipping point analysis...")
    tipping_analyzer = FabricTippingPointAnalyzer()
    tipping_curve, tipping_summary = tipping_analyzer.run_analysis(
        typical_annual_heat_demand_kwh=15000
    )
    results['tipping_point'] = {'curve': tipping_curve, 'summary': tipping_summary}
    logger.info("✓ Tipping point analysis complete")

    # ---- Pathway Modeling (Section 5 & 6) ----
    logger.info("\n🛤️  Running pathway modeling...")
    pathway_modeler = PathwayModeler()
    pathway_results = pathway_modeler.model_all_pathways(df)
    pathway_summary = pathway_modeler.generate_pathway_summary(pathway_results)
    pathway_modeler.export_results(pathway_results, pathway_summary)
    results['pathways'] = {'results': pathway_results, 'summary': pathway_summary}
    logger.info("✓ Pathway modeling complete")

    # ---- Load Profiles (Section 9) ----
    logger.info("\n⚡ Running load profile analysis...")
    load_generator = LoadProfileGenerator()
    load_profiles, load_summary = load_generator.generate_pathway_load_profiles(pathway_results)
    load_generator.export_results(load_profiles, load_summary)
    results['load_profiles'] = {'profiles': load_profiles, 'summary': load_summary}
    logger.info("✓ Load profile analysis complete")

    # ---- Penetration Sensitivity (Section 10) ----
    logger.info("\n🔄 Running penetration sensitivity analysis...")
    sensitivity_analyzer = PenetrationSensitivityAnalyzer()
    sensitivity_results = sensitivity_analyzer.run_sensitivity_analysis(df)
    sensitivity_analyzer.export_results(sensitivity_results)
    results['sensitivity'] = sensitivity_results
    logger.info("✓ Penetration sensitivity complete")

    # ---- Original Scenario Modeling (for backwards compatibility) ----
    logger.info("\n🎯 Running scenario modeling...")
    modeler = ScenarioModeler()
    scenario_results = modeler.model_all_scenarios(df)
    subsidy_results = modeler.model_subsidy_sensitivity(df, 'heat_pump')
    modeler.save_results()
    results['scenarios'] = {'results': scenario_results, 'subsidy': subsidy_results}
    logger.info("✓ Scenario modeling complete")

    logger.info("\n" + "="*70)
    logger.info("✓ COMPREHENSIVE MODELING & ANALYSIS COMPLETE")
    logger.info("="*70)

    return results


def run_spatial_phase(args):
    """Run spatial analysis phase."""
    logger.info("\n" + "="*70)
    logger.info("PHASE 5: SPATIAL ANALYSIS")
    logger.info("="*70)

    from config.config import DATA_PROCESSED_DIR, DATA_SUPPLEMENTARY_DIR
    import pandas as pd

    input_file = DATA_PROCESSED_DIR / "epc_london_validated.csv"
    if not input_file.exists():
        logger.error("Validated data not found. Run cleaning phase first.")
        return None

    df = pd.read_csv(input_file, low_memory=False)

    analyzer = HeatNetworkAnalyzer()

    # Geocode properties
    properties_gdf = analyzer.geocode_properties(df)

    if len(properties_gdf) > 0:
        # Load heat network data (if available)
        heat_networks_file = DATA_SUPPLEMENTARY_DIR / "london_heat_networks.geojson"
        heat_zones_file = DATA_SUPPLEMENTARY_DIR / "london_heat_zones.geojson"

        heat_networks, heat_zones = analyzer.load_london_heat_map_data(
            heat_networks_file,
            heat_zones_file
        )

        # Classify properties by tier
        properties_classified = analyzer.classify_heat_network_tiers(
            properties_gdf,
            heat_networks,
            heat_zones
        )

        # Analyze pathway suitability
        pathway_summary = analyzer.analyze_pathway_suitability(properties_classified)

        # Save results
        from config.config import DATA_OUTPUTS_DIR
        output_file = DATA_PROCESSED_DIR / "epc_london_with_tiers.geojson"
        properties_classified.to_file(output_file, driver='GeoJSON')

        pathway_file = DATA_OUTPUTS_DIR / "pathway_suitability_by_tier.csv"
        pathway_summary.to_csv(pathway_file, index=False)

        # Create map
        analyzer.create_heat_network_map(properties_classified)

        logger.info("✓ Spatial analysis complete")
        return pathway_summary
    else:
        logger.warning("No geocoded properties available")
        return None


def run_reporting_phase(args, archetype_results, scenario_results, tier_summary):
    """Run reporting and visualization phase."""
    logger.info("\n" + "="*70)
    logger.info("PHASE 6: REPORTING & VISUALIZATION")
    logger.info("="*70)

    generator = ReportGenerator()

    # Generate visualizations
    if archetype_results and 'epc_bands' in archetype_results:
        generator.plot_epc_band_distribution(archetype_results['epc_bands'])

    if scenario_results:
        generator.plot_scenario_comparison(scenario_results[0])

    if tier_summary is not None:
        generator.plot_heat_network_tiers(tier_summary)

    # Generate summary report
    if archetype_results and scenario_results:
        generator.generate_summary_report(
            archetype_results,
            scenario_results[0],
            tier_summary if tier_summary is not None else None
        )

    logger.info("✓ Reporting complete")


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description="Heat Street EPC Analysis Pipeline"
    )

    parser.add_argument(
        '--phase',
        choices=['all', 'acquire', 'clean', 'analyze', 'model', 'spatial', 'report'],
        default='all',
        help='Which phase to run (default: all)'
    )

    parser.add_argument(
        '--download',
        action='store_true',
        help='Download new EPC data (creates download instructions)'
    )

    parser.add_argument(
        '--log-file',
        type=Path,
        default=Path('pipeline.log'),
        help='Path to log file (default: pipeline.log)'
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.log_file)

    # Ensure directory structure exists
    ensure_directories()

    logger.info("="*70)
    logger.info("HEAT STREET EPC ANALYSIS PIPELINE")
    logger.info("="*70)

    # Run requested phases
    archetype_results = None
    scenario_results = None
    tier_summary = None

    if args.phase in ['all', 'acquire']:
        run_acquisition_phase(args)

    if args.phase in ['all', 'clean']:
        run_cleaning_phase(args)

    if args.phase in ['all', 'analyze']:
        archetype_results = run_analysis_phase(args)

    if args.phase in ['all', 'model']:
        scenario_results = run_modeling_phase(args)

    if args.phase in ['all', 'spatial']:
        tier_summary = run_spatial_phase(args)

    if args.phase in ['all', 'report']:
        run_reporting_phase(args, archetype_results, scenario_results, tier_summary)

    logger.info("\n" + "="*70)
    logger.info("PIPELINE COMPLETE")
    logger.info("="*70)


if __name__ == "__main__":
    main()
