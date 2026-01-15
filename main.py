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
from src.utils.run_metadata import RunMetadataManager

# Global metadata manager for stage count tracking
_metadata_manager: RunMetadataManager = None


def get_metadata_manager() -> RunMetadataManager:
    """Get or create the global metadata manager."""
    global _metadata_manager
    if _metadata_manager is None:
        _metadata_manager = RunMetadataManager()
    return _metadata_manager


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

    metadata = get_metadata_manager()
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

            # AUDIT FIX: Record raw loaded count in metadata
            metadata.record_stage_count(
                "raw_loaded_count",
                len(df_filtered),
                description="Properties after initial filtering from raw EPC data",
                dataframe_source="epc_london_filtered.csv"
            )

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
    metadata = get_metadata_manager()
    input_file = DATA_RAW_DIR / "epc_london_filtered.csv"

    if not input_file.exists():
        logger.error(f"Input file not found: {input_file}")
        logger.info("Please run acquisition phase first")
        return None

    import pandas as pd
    df = pd.read_csv(input_file, low_memory=False)

    # Record raw count if not already done (e.g., if running cleaning phase alone)
    if metadata.get_stage_count("raw_loaded_count") is None:
        metadata.record_stage_count(
            "raw_loaded_count",
            len(df),
            description="Properties loaded from raw EPC data",
            dataframe_source="epc_london_filtered.csv"
        )

    validator = EPCDataValidator()
    df_validated, report = validator.validate_dataset(df)

    # AUDIT FIX: Record validated count with drop tracking
    metadata.record_stage_count(
        "after_validation_count",
        len(df_validated),
        description="Properties passing validation rules (floor area, required fields, etc.)",
        dataframe_source="epc_london_validated.csv",
        drop_threshold_pct=0.05,  # Warn if >5% dropped
        allow_drop=True  # Validation drops are expected
    )

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
    from src.reporting.comparisons import ComparisonReporter

    metadata = get_metadata_manager()
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

    # AUDIT FIX: Record scenario input count
    metadata.record_stage_count(
        "scenario_input_count",
        len(df),
        description="Properties entering scenario modeling (should match after_validation_count)",
        dataframe_source=str(input_file.name),
        drop_threshold_pct=0.001,  # Should be nearly identical to validation
        allow_drop=False  # Unexpected drops should fail
    )

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
    pathway_modeler = PathwayModeler(
        include_ground_loop_proxy=getattr(args, 'include_ground_loop_proxy', False),
        ground_loop_scop=getattr(args, 'ground_loop_cop', None),
        ground_loop_capex_delta=getattr(args, 'ground_loop_capex_delta', 0.0),
    )
    pathway_results = pathway_modeler.model_all_pathways(df)
    pathway_summary = pathway_modeler.generate_pathway_summary(pathway_results)
    property_path, _ = pathway_modeler.export_results(pathway_results, pathway_summary)
    if getattr(args, 'run_hn_sensitivity', False):
        pathway_modeler.run_hn_connection_sensitivity(df)
    results['pathways'] = {'results': pathway_results, 'summary': pathway_summary}
    logger.info("✓ Pathway modeling complete")

    # ---- HP vs HN comparison reporting ----
    logger.info("\n📑 Building HP vs HN comparison outputs...")
    comparison_reporter = ComparisonReporter()
    comparison_reporter.generate_comparisons(results_path=property_path)
    logger.info("✓ Comparison reporting complete")

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

    # AUDIT FIX: Record final modeled count (should match scenario_input_count)
    # Get the count from scenario modeler to track any drops during modeling
    final_count = len(df)  # Default to input count
    if modeler.property_results:
        # Use the first scenario's result count as representative
        first_scenario_df = list(modeler.property_results.values())[0]
        final_count = len(first_scenario_df)

    metadata.record_stage_count(
        "final_modeled_count",
        final_count,
        description="Properties with completed scenario results",
        dataframe_source="scenario_modeling_results",
        drop_threshold_pct=0.001,  # Should be nearly identical to input
        allow_drop=True  # Small drops may occur due to edge cases
    )

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

    metadata = get_metadata_manager()
    input_file = DATA_PROCESSED_DIR / "epc_london_validated.csv"
    if not input_file.exists():
        logger.error("Validated data not found. Run cleaning phase first.")
        return None

    df = pd.read_csv(input_file, low_memory=False)

    analyzer = HeatNetworkAnalyzer()

    # Geocode properties
    properties_gdf = analyzer.geocode_properties(df)

    if properties_gdf is not None and len(properties_gdf) > 0:
        # AUDIT FIX: Record geocoded count
        metadata.record_stage_count(
            "after_geocoding_count",
            len(properties_gdf),
            description="Properties with valid coordinates after geocoding",
            dataframe_source="geocoded_properties",
            drop_threshold_pct=5.0,  # May drop more due to missing coords
            allow_drop=True  # Geocoding drops are expected
        )
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

    from src.reporting.executive_summary import ExecutiveSummaryGenerator

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

    # AUDIT FIX: Generate executive summary from actual output files
    logger.info("\n📝 Generating executive summary...")
    try:
        summary_generator = ExecutiveSummaryGenerator()
        summary_path = summary_generator.generate_summary()
        logger.info(f"✓ Executive summary generated: {summary_path}")
    except Exception as e:
        logger.warning(f"Could not generate executive summary: {e}")

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

    parser.add_argument(
        '--run-hn-sensitivity',
        action='store_true',
        help='Run HN connection cost sensitivity alongside pathway modeling'
    )

    parser.add_argument(
        '--include-ground-loop-proxy',
        action='store_true',
        help='Include shared ground loop proxy pathway in modeling outputs'
    )

    parser.add_argument(
        '--ground-loop-cop',
        type=float,
        default=None,
        help='Override COP/SCOP for the ground loop proxy pathway'
    )

    parser.add_argument(
        '--ground-loop-capex-delta',
        type=float,
        default=0.0,
        help='Incremental CAPEX (£) applied to the ground loop proxy pathway'
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

    # AUDIT FIX: Save run metadata with stage counts and generate reconciliation
    metadata = get_metadata_manager()

    # Add explanatory notes for any count differences
    if metadata.get_stage_count("after_validation_count") and metadata.get_stage_count("scenario_input_count"):
        val_count = metadata.get_stage_count("after_validation_count")
        scenario_count = metadata.get_stage_count("scenario_input_count")
        if val_count != scenario_count:
            metadata.add_note(
                f"Validation count ({val_count:,}) differs from scenario input count ({scenario_count:,}). "
                f"Difference of {val_count - scenario_count:,} records may be due to reloading data from disk."
            )

    # Save metadata
    metadata_path = metadata.save()
    logger.info(f"Run metadata saved to: {metadata_path}")

    # Generate and log reconciliation table
    logger.info("\n" + metadata.generate_reconciliation_table())

    logger.info("\n" + "="*70)
    logger.info("PIPELINE COMPLETE")
    logger.info("="*70)


if __name__ == "__main__":
    main()
