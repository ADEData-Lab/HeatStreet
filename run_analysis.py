"""
Heat Street EPC Analysis - Complete Interactive Pipeline

Runs the entire analysis from data download to report generation
with interactive prompts and progress indicators.
"""

import os
import shutil
import sys
from pathlib import Path
from loguru import logger
import questionary
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel
from rich import print as rprint
import time

# Add src to path
sys.path.append(str(Path(__file__).parent))

from config.config import load_config, ensure_directories, DATA_RAW_DIR, DATA_PROCESSED_DIR
from src.acquisition.epc_api_downloader import EPCAPIDownloader
from src.acquisition.london_gis_downloader import LondonGISDownloader
from src.cleaning.data_validator import EPCDataValidator
from src.analysis.archetype_analysis import ArchetypeAnalyzer
from src.modeling.scenario_model import ScenarioModeler
from src.utils.analysis_logger import AnalysisLogger


console = Console()


def print_header():
    """Print welcome header."""
    console.clear()
    rprint(Panel.fit(
        "[bold cyan]Heat Street EPC Analysis[/bold cyan]\n"
        "[white]Complete Interactive Pipeline[/white]\n"
        "[dim]London Edwardian Terraced Housing Analysis[/dim]",
        border_style="cyan"
    ))
    print()


def check_credentials():
    """Check if API credentials are configured."""
    email = os.getenv('EPC_API_EMAIL')
    api_key = os.getenv('EPC_API_KEY')

    if not email or not api_key:
        console.print("[yellow]⚠[/yellow]  API credentials not found in .env file", style="yellow")
        console.print()

        if not Path('.env').exists():
            console.print("Creating .env file from template...")
            if Path('.env.example').exists():
                import shutil
                shutil.copy('.env.example', '.env')
                console.print("[green]✓[/green] Created .env file")
            else:
                # Create .env file
                with open('.env', 'w') as f:
                    f.write("# EPC API Credentials\n")
                    f.write("EPC_API_EMAIL=\n")
                    f.write("EPC_API_KEY=\n")
                console.print("[green]✓[/green] Created .env file")

        console.print()
        console.print("[cyan]Please enter your EPC API credentials:[/cyan]")
        console.print("[dim]Get credentials from: https://epc.opendatacommunities.org/[/dim]")
        console.print()

        email = questionary.text(
            "Email address:",
            validate=lambda x: '@' in x
        ).ask()

        api_key = questionary.text(
            "API key:"
        ).ask()

        # Save to .env
        with open('.env', 'w') as f:
            f.write(f"# EPC API Credentials\n")
            f.write(f"EPC_API_EMAIL={email}\n")
            f.write(f"EPC_API_KEY={api_key}\n")

        # Reload environment
        from dotenv import load_dotenv
        load_dotenv(override=True)

        console.print("[green]✓[/green] Credentials saved to .env file")
        console.print()

    return True


def ask_download_scope():
    """Ask user what scope of data to download."""
    console.print("[cyan]Data Download Options:[/cyan]")
    console.print()

    choice = questionary.select(
        "What would you like to download?",
        choices=[
            questionary.Choice("Quick test (single borough, limited data)", value="test"),
            questionary.Choice("Medium dataset (5 boroughs, last 5 years)", value="medium"),
            questionary.Choice("Full dataset (all 33 London boroughs)", value="full"),
            questionary.Choice("Custom selection", value="custom")
        ]
    ).ask()

    if choice == "test":
        borough = questionary.select(
            "Select a borough for testing:",
            choices=["Camden", "Islington", "Hackney", "Westminster", "Southwark"]
        ).ask()
        return {
            'mode': 'single',
            'boroughs': [borough],
            'from_year': 2020,
            'max_per_borough': 1000
        }

    elif choice == "medium":
        return {
            'mode': 'multiple',
            'boroughs': ["Camden", "Islington", "Hackney", "Westminster", "Tower Hamlets"],
            'from_year': 2020,
            'max_per_borough': None
        }

    elif choice == "full":
        confirm = questionary.confirm(
            "Full download will take 2-4 hours. Continue?",
            default=False
        ).ask()

        if confirm:
            return {
                'mode': 'all',
                'boroughs': None,
                'from_year': 2015,
                'max_per_borough': None
            }
        else:
            return ask_download_scope()  # Ask again

    else:  # custom
        boroughs = questionary.checkbox(
            "Select boroughs (space to select, enter to confirm):",
            choices=[
                "Camden", "Islington", "Hackney", "Westminster", "Southwark",
                "Tower Hamlets", "Lambeth", "Wandsworth", "Greenwich", "Lewisham"
            ]
        ).ask()

        from_year = questionary.select(
            "Data from year:",
            choices=["2023", "2020", "2015", "2010"]
        ).ask()

        limit = questionary.confirm(
            "Limit results per borough (faster)?",
            default=False
        ).ask()

        max_per_borough = None
        if limit:
            max_per_borough = int(questionary.text(
                "Maximum records per borough:",
                default="5000"
            ).ask())

        return {
            'mode': 'multiple',
            'boroughs': boroughs,
            'from_year': int(from_year),
            'max_per_borough': max_per_borough
        }


def ask_gis_download():
    """Ask if user wants to download London GIS data for spatial analysis."""
    console.print()
    console.print("[cyan]London GIS Data (Optional)[/cyan]")
    console.print()
    console.print("This analysis can optionally use GIS data from London Datastore for:")
    console.print("  • Existing district heating networks")
    console.print("  • Potential heat network zones")
    console.print("  • Heat load and supply data by borough")
    console.print()

    # Check if already downloaded
    gis_downloader = LondonGISDownloader()
    summary = gis_downloader.get_data_summary()

    if summary['available']:
        console.print("[green]✓[/green] GIS data already downloaded")
        console.print(f"    Heat load files: {summary['heat_load_files']}")
        console.print(f"    Network files: {summary['network_files']}")
        console.print(f"    Heat supply files: {summary['heat_supply_files']}")
        return True

    download = questionary.confirm(
        "Download London GIS data? (~2 MB, required for spatial analysis)",
        default=True
    ).ask()

    if download:
        console.print()
        console.print("[cyan]Downloading London GIS data...[/cyan]")

        if gis_downloader.download_and_prepare():
            console.print("[green]✓[/green] GIS data downloaded and ready")
            return True
        else:
            console.print("[yellow]⚠[/yellow] GIS data download failed (spatial analysis will be limited)")
            return False

    return False


def download_data(scope, analysis_logger: AnalysisLogger = None):
    """Download EPC data via API."""
    console.print()
    console.print(Panel("[bold]Phase 1: Data Download[/bold]", border_style="blue"))
    console.print()

    if analysis_logger:
        analysis_logger.start_phase(
            "Data Download",
            "Download EPC data from API and filter for Edwardian terraced houses"
        )

    try:
        downloader = EPCAPIDownloader()

        if scope['mode'] == 'single':
            borough = scope['boroughs'][0]
            console.print(f"[cyan]Downloading {borough} data...[/cyan]")

            df = downloader.download_borough_data(
                borough_name=borough,
                property_type='house',
                from_year=scope['from_year'],
                max_results=scope.get('max_per_borough')
            )

        elif scope['mode'] == 'all':
            console.print(f"[cyan]Downloading ALL London boroughs (this will take a while)...[/cyan]")

            df = downloader.download_all_london_boroughs(
                property_types=['house'],
                from_year=scope['from_year'],
                max_results_per_borough=scope.get('max_per_borough')
            )

        else:  # multiple
            console.print(f"[cyan]Downloading {len(scope['boroughs'])} boroughs...[/cyan]")

            all_data = []
            for borough in scope['boroughs']:
                df_borough = downloader.download_borough_data(
                    borough_name=borough,
                    property_type='house',
                    from_year=scope['from_year'],
                    max_results=scope.get('max_per_borough')
                )
                if not df_borough.empty:
                    all_data.append(df_borough)

            import pandas as pd
            df = pd.concat(all_data, ignore_index=True) if all_data else pd.DataFrame()

        if df.empty:
            console.print("[red]✗[/red] No data downloaded", style="red")
            if analysis_logger:
                analysis_logger.complete_phase(success=False, message="No data downloaded from API")
            return None

        console.print(f"[green]✓[/green] Downloaded {len(df):,} records")

        if analysis_logger:
            analysis_logger.add_metric("raw_records_downloaded", len(df), "Total records from API")
            analysis_logger.add_metric("boroughs_requested", len(scope['boroughs']) if scope['boroughs'] else 33)
            analysis_logger.add_metric("from_year", scope['from_year'])

        # Apply Edwardian filters
        console.print("[cyan]Applying Edwardian terraced housing filters...[/cyan]")
        df_filtered = downloader.apply_edwardian_filters(df)
        console.print(f"[green]✓[/green] Filtered to {len(df_filtered):,} Edwardian terraced houses")

        if analysis_logger:
            analysis_logger.add_metric("filtered_records", len(df_filtered), "Edwardian terraced houses after filtering")
            analysis_logger.add_metric("filter_rate", len(df_filtered) / len(df) * 100, "Percentage retained after filtering")

        # Save data
        console.print("[cyan]Saving data...[/cyan]")
        downloader.save_data(df, "epc_london_raw.csv")
        downloader.save_data(df_filtered, "epc_london_filtered.csv")
        console.print(f"[green]✓[/green] Data saved to data/raw/")

        if analysis_logger:
            analysis_logger.add_output("data/raw/epc_london_raw.csv", "csv", "Raw EPC data from API")
            analysis_logger.add_output("data/raw/epc_london_filtered.csv", "csv", "Filtered Edwardian terraced houses")
            analysis_logger.complete_phase(success=True, message=f"Downloaded {len(df_filtered):,} Edwardian properties")

        return df_filtered

    except ValueError as e:
        console.print(f"[red]✗[/red] Error: {e}", style="red")
        if analysis_logger:
            analysis_logger.complete_phase(success=False, message=f"ValueError: {e}")
        return None
    except Exception as e:
        console.print(f"[red]✗[/red] Unexpected error: {e}", style="red")
        if analysis_logger:
            analysis_logger.complete_phase(success=False, message=f"Error: {e}")
        return None


def validate_data(df, analysis_logger: AnalysisLogger = None):
    """Validate and clean data."""
    console.print()
    console.print(Panel("[bold]Phase 2: Data Validation[/bold]", border_style="blue"))
    console.print()

    if analysis_logger:
        analysis_logger.start_phase(
            "Data Validation",
            "Run quality assurance checks and remove invalid/duplicate records"
        )

    console.print("[cyan]Running quality assurance checks...[/cyan]")

    validator = EPCDataValidator()
    df_validated, report = validator.validate_dataset(df)

    console.print(f"[green]✓[/green] Validation complete")
    console.print(f"    Records passed: {len(df_validated):,} ({len(df_validated)/report['total_records']*100:.1f}%)")
    console.print(f"    Duplicates removed: {report['duplicates_removed']:,}")
    console.print(f"    Invalid records: {report['total_records'] - len(df_validated):,}")

    if analysis_logger:
        analysis_logger.add_metric("input_records", report['total_records'], "Records before validation")
        analysis_logger.add_metric("validated_records", len(df_validated), "Records after validation")
        analysis_logger.add_metric("duplicates_removed", report['duplicates_removed'], "Duplicate records removed")
        analysis_logger.add_metric("invalid_records", report['total_records'] - len(df_validated), "Invalid records removed")
        analysis_logger.add_metric("validation_rate", len(df_validated)/report['total_records']*100, "Percentage of records passing validation")

    # Save validated data
    import pandas as pd
    output_file = DATA_PROCESSED_DIR / "epc_london_validated.csv"
    df_validated.to_csv(output_file, index=False)

    # Try to save parquet (optional for performance)
    try:
        parquet_file = output_file.with_suffix('.parquet')
        # Convert object columns to strings to avoid mixed-type issues
        df_parquet = df_validated.copy()
        for col in df_parquet.columns:
            if df_parquet[col].dtype == 'object':
                df_parquet[col] = df_parquet[col].astype(str)
        df_parquet.to_parquet(parquet_file, index=False)
    except Exception as e:
        console.print(f"[yellow]Note: Could not save parquet format (CSV saved successfully)[/yellow]")
        logger.debug(f"Parquet save failed: {e}")

    validator.save_validation_report()

    console.print(f"[green]✓[/green] Validated data saved")

    if analysis_logger:
        analysis_logger.add_output(str(output_file), "csv", "Validated EPC dataset")
        analysis_logger.add_output("data/processed/validation_report.txt", "report", "Data validation report")
        analysis_logger.complete_phase(success=True, message=f"{len(df_validated):,} records validated")

    return df_validated, report


def apply_methodological_adjustments(df, analysis_logger: AnalysisLogger = None):
    """Apply evidence-based methodological adjustments."""
    console.print()
    console.print(Panel("[bold]Phase 2.5: Methodological Adjustments[/bold]", border_style="blue"))
    console.print()

    if analysis_logger:
        analysis_logger.start_phase(
            "Methodological Adjustments",
            "Apply evidence-based adjustments (prebound effect, heat pump flow temp, uncertainty)"
        )

    from src.analysis.methodological_adjustments import MethodologicalAdjustments

    console.print("[cyan]Applying evidence-based adjustments...[/cyan]")

    adjuster = MethodologicalAdjustments()

    # Apply all adjustments in sequence
    df_adjusted = adjuster.apply_all_adjustments(df)

    # Generate summary
    summary = adjuster.generate_adjustment_summary(df_adjusted)

    console.print(f"[green]✓[/green] Methodological adjustments applied")
    adjustments_applied = []
    if summary.get('prebound_adjustment', {}).get('applied'):
        console.print(f"    • Prebound effect adjustment (Few et al., 2023)")
        adjustments_applied.append("Prebound effect")
    if summary.get('flow_temperature', {}).get('applied'):
        console.print(f"    • Heat pump flow temperature model")
        adjustments_applied.append("Flow temperature")
    if summary.get('uncertainty', {}).get('applied'):
        console.print(f"    • Measurement uncertainty (Crawley et al., 2019)")
        adjustments_applied.append("Measurement uncertainty")

    if analysis_logger:
        analysis_logger.add_metric("adjustments_applied", len(adjustments_applied), f"Applied: {', '.join(adjustments_applied)}")
        analysis_logger.add_metric("records_adjusted", len(df_adjusted), "Records with adjustments")
        analysis_logger.complete_phase(success=True, message=f"{len(adjustments_applied)} methodological adjustments applied")

    return df_adjusted


def analyze_archetype(df, analysis_logger: AnalysisLogger = None):
    """Run archetype characterization."""
    console.print()
    console.print(Panel("[bold]Phase 3: Archetype Analysis[/bold]", border_style="blue"))
    console.print()

    if analysis_logger:
        analysis_logger.start_phase(
            "Archetype Analysis",
            "Characterize Edwardian housing stock by EPC bands, insulation, heating systems, etc."
        )

    console.print("[cyan]Analyzing property characteristics...[/cyan]")

    analyzer = ArchetypeAnalyzer()
    results = analyzer.analyze_archetype(df)
    analyzer.save_results()

    console.print(f"[green]✓[/green] Archetype analysis complete")

    # Show key findings
    if 'epc_bands' in results and results['epc_bands'] and 'frequency' in results['epc_bands']:
        console.print()
        console.print("[cyan]EPC Band Distribution:[/cyan]")
        for band in ['D', 'E', 'F', 'G']:
            if band in results['epc_bands']['frequency']:
                count = results['epc_bands']['frequency'][band]
                pct = results['epc_bands']['percentage'][band]
                console.print(f"    Band {band}: {count:,} ({pct:.1f}%)")

        if analysis_logger:
            for band in ['D', 'E', 'F', 'G']:
                if band in results['epc_bands']['frequency']:
                    count = results['epc_bands']['frequency'][band]
                    pct = results['epc_bands']['percentage'][band]
                    analysis_logger.add_metric(f"epc_band_{band}", count, f"Band {band}: {pct:.1f}%")
    else:
        console.print()
        console.print("[yellow]Note: EPC band distribution analysis could not be completed (missing required columns)[/yellow]")

    if analysis_logger:
        analysis_logger.add_output("data/outputs/archetype_analysis_results.txt", "report", "Archetype characterization results")
        analysis_logger.complete_phase(success=True, message="Archetype characterization complete")

    return results


def model_scenarios(df, analysis_logger: AnalysisLogger = None):
    """Run scenario modeling."""
    console.print()
    console.print(Panel("[bold]Phase 4: Scenario Modeling[/bold]", border_style="blue"))
    console.print()

    if analysis_logger:
        analysis_logger.start_phase(
            "Scenario Modeling",
            "Model decarbonization scenarios (heat pump, hybrid, district heating) and subsidy sensitivity"
        )

    console.print("[cyan]Modeling decarbonization scenarios...[/cyan]")

    modeler = ScenarioModeler()
    scenario_results = modeler.model_all_scenarios(df)

    console.print(f"[green]✓[/green] Scenario modeling complete")

    # Show summary
    console.print()
    console.print("[cyan]Scenario Summary:[/cyan]")
    if scenario_results:
        for scenario, results in scenario_results.items():
            if 'capital_cost_per_property' in results:
                console.print(f"    {scenario}: £{results['capital_cost_per_property']:,.0f} per property")
                if analysis_logger:
                    analysis_logger.add_metric(f"scenario_{scenario}_cost", results['capital_cost_per_property'], f"Capital cost per property")
            else:
                console.print(f"    {scenario}: Analysis incomplete (missing required data)")
    else:
        console.print("[yellow]Note: Scenario modeling could not be completed (missing required columns)[/yellow]")

    # Subsidy analysis
    console.print()
    console.print("[cyan]Running subsidy sensitivity analysis...[/cyan]")
    subsidy_results = modeler.model_subsidy_sensitivity(df, 'heat_pump')

    modeler.save_results()
    console.print(f"[green]✓[/green] Results saved")

    if analysis_logger:
        analysis_logger.add_metric("scenarios_modeled", len(scenario_results), "Decarbonization scenarios analyzed")
        analysis_logger.add_output("data/outputs/scenario_modeling_results.txt", "report", "Scenario modeling results")
        analysis_logger.complete_phase(success=True, message=f"{len(scenario_results)} scenarios modeled successfully")

    return scenario_results, subsidy_results


def analyze_retrofit_readiness(df, analysis_logger: AnalysisLogger = None):
    """Analyze heat pump retrofit readiness."""
    console.print()
    console.print(Panel("[bold]Phase 4.3: Retrofit Readiness Analysis[/bold]", border_style="blue"))
    console.print()

    if analysis_logger:
        analysis_logger.start_phase(
            "Retrofit Readiness Analysis",
            "Assess heat pump readiness, fabric pre-requisites, and retrofit costs"
        )

    console.print("[cyan]Assessing heat pump readiness and barriers...[/cyan]")
    console.print()
    console.print("This phase analyzes:")
    console.print("  • Current heat pump suitability")
    console.print("  • Required fabric pre-requisites")
    console.print("  • Pre-retrofit cost barriers")
    console.print("  • Heat demand before/after fabric improvements")
    console.print()

    try:
        from src.analysis.retrofit_readiness import RetrofitReadinessAnalyzer

        analyzer = RetrofitReadinessAnalyzer()

        # Run readiness assessment
        df_readiness = analyzer.assess_heat_pump_readiness(df)
        summary = analyzer.generate_readiness_summary(df_readiness)

        # Save results
        analyzer.save_readiness_results(df_readiness, summary)

        # Display key findings
        console.print("[green]✓[/green] Retrofit readiness analysis complete")
        console.print()
        console.print("[cyan]Key Findings:[/cyan]")
        console.print(f"  Tier 1 (Ready Now): {summary['tier_distribution'].get(1, 0):,} properties ({summary['tier_percentages'].get(1, 0):.1f}%)")
        console.print(f"  Tier 2 (Minor Work): {summary['tier_distribution'].get(2, 0):,} properties ({summary['tier_percentages'].get(2, 0):.1f}%)")
        console.print(f"  Tier 3 (Major Work): {summary['tier_distribution'].get(3, 0):,} properties ({summary['tier_percentages'].get(3, 0):.1f}%)")
        console.print(f"  Tier 4 (Challenging): {summary['tier_distribution'].get(4, 0):,} properties ({summary['tier_percentages'].get(4, 0):.1f}%)")
        console.print(f"  Tier 5 (Not Suitable): {summary['tier_distribution'].get(5, 0):,} properties ({summary['tier_percentages'].get(5, 0):.1f}%)")
        console.print()
        console.print(f"  Solid wall barrier: {summary['needs_solid_wall_insulation']:,} properties need SWI")
        console.print(f"  Mean fabric cost: £{summary['mean_fabric_cost']:,.0f}")
        console.print(f"  Total retrofit investment: £{summary['total_retrofit_cost']/1e6:.1f}M")
        console.print()

        if analysis_logger:
            for tier in range(1, 6):
                count = summary['tier_distribution'].get(tier, 0)
                pct = summary['tier_percentages'].get(tier, 0)
                analysis_logger.add_metric(f"retrofit_tier_{tier}", count, f"{pct:.1f}% of properties")
            analysis_logger.add_metric("mean_fabric_cost", summary['mean_fabric_cost'], "Average fabric improvement cost per property")
            analysis_logger.add_metric("total_retrofit_cost", summary['total_retrofit_cost'], "Total retrofit investment needed")

        # Generate visualizations
        console.print("[cyan]Creating retrofit readiness visualizations...[/cyan]")

        from src.reporting.visualizations import ReportGenerator
        viz = ReportGenerator()

        viz.plot_retrofit_readiness_dashboard(df_readiness, summary)
        viz.plot_fabric_cost_distribution(df_readiness)
        viz.plot_heat_demand_scatter(df_readiness)

        console.print(f"[green]✓[/green] Visualizations saved to data/outputs/figures/")

        if analysis_logger:
            analysis_logger.add_output("data/outputs/retrofit_readiness_analysis.csv", "csv", "Property-level retrofit readiness")
            analysis_logger.add_output("data/outputs/reports/retrofit_readiness_summary.txt", "report", "Retrofit readiness summary")
            analysis_logger.add_output("data/outputs/figures/retrofit_readiness_dashboard.png", "png", "Retrofit readiness visualization")
            analysis_logger.complete_phase(success=True, message="Retrofit readiness assessment complete")

        return df_readiness, summary

    except Exception as e:
        console.print(f"[yellow]⚠ Retrofit readiness analysis failed: {e}[/yellow]")
        logger.error(f"Retrofit readiness error: {e}")
        if analysis_logger:
            analysis_logger.complete_phase(success=False, message=f"Error: {e}")
        return None, None


def run_spatial_analysis(df, analysis_logger: AnalysisLogger = None):
    """Run spatial heat network tier analysis (optional - requires GDAL)."""
    console.print()
    console.print(Panel("[bold]Phase 4.5: Spatial Analysis (Optional)[/bold]", border_style="blue"))
    console.print()

    console.print("[cyan]Heat Network Tier Classification[/cyan]")
    console.print()
    console.print("This phase requires GDAL/geopandas for spatial analysis.")
    console.print("If not installed, this phase will be skipped.")
    console.print()

    try:
        from src.spatial.heat_network_analysis import HeatNetworkAnalyzer

        if analysis_logger:
            analysis_logger.start_phase(
                "Spatial Analysis",
                "Geocode properties and classify into heat network tiers based on heat density"
            )

        analyzer = HeatNetworkAnalyzer()

        console.print("[cyan]Running spatial analysis...[/cyan]")
        console.print("  • Geocoding properties from lat/lon coordinates")
        console.print("  • Loading London heat network GIS data")
        console.print("  • Calculating heat density (GWh/km²)")
        console.print("  • Classifying into 5 heat network tiers")
        console.print()

        properties_classified, pathway_summary = analyzer.run_complete_analysis(
            df, auto_download_gis=True
        )

        if properties_classified is not None and pathway_summary is not None:
            console.print(f"[green]✓[/green] Spatial analysis complete!")
            console.print()
            console.print("[cyan]Heat Network Tier Summary:[/cyan]")

            # Show tier counts
            for _, row in pathway_summary.iterrows():
                tier_name = row['Tier']
                count = row['Property Count']
                pct = row['Percentage']
                pathway = row['Recommended Pathway']
                console.print(f"    {tier_name}: {count:,} ({pct:.1f}%) → {pathway}")

            console.print()
            console.print(f"[cyan]📁 Outputs:[/cyan]")
            console.print(f"    • GeoJSON: data/processed/epc_with_heat_network_tiers.geojson")
            console.print(f"    • CSV: data/outputs/pathway_suitability_by_tier.csv")
            console.print(f"    • Interactive Map: data/outputs/maps/heat_network_tiers.html")

            if analysis_logger:
                map_html = Path("data/outputs/maps/heat_network_tiers.html")
                map_png = map_html.with_suffix('.png')
                map_pdf = map_html.with_suffix('.pdf')

                analysis_logger.add_metric("properties_geocoded", len(properties_classified), "Properties with spatial classification")
                analysis_logger.add_output("data/processed/epc_with_heat_network_tiers.geojson", "geojson", "Geocoded properties with heat network tiers")
                analysis_logger.add_output("data/outputs/pathway_suitability_by_tier.csv", "csv", "Pathway suitability by tier")
                analysis_logger.add_output("data/outputs/maps/heat_network_tiers.html", "html", "Interactive heat network tier map")

                if map_png.exists():
                    analysis_logger.add_output(str(map_png), "png", "Heat network tier map (image)")
                if map_pdf.exists():
                    analysis_logger.add_output(str(map_pdf), "pdf", "Heat network tier map (PDF)")
                analysis_logger.complete_phase(success=True, message="Spatial analysis with heat network classification complete")

            return properties_classified, pathway_summary
        else:
            console.print("[yellow]⚠ Spatial analysis could not complete[/yellow]")
            if analysis_logger:
                analysis_logger.complete_phase(success=False, message="Spatial analysis could not complete")
            return None, None

    except ImportError as e:
        console.print()
        console.print("[yellow]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/yellow]")
        console.print("[yellow]⚠ GDAL/geopandas not installed - Skipping spatial analysis[/yellow]")
        console.print("[yellow]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/yellow]")
        console.print()
        console.print("[cyan]To enable spatial analysis:[/cyan]")
        console.print("  [bold]Windows (Recommended):[/bold]")
        console.print("    conda install -c conda-forge geopandas")
        console.print()
        console.print("  [bold]Linux/Mac:[/bold]")
        console.print("    pip install -r requirements-spatial.txt")
        console.print()
        console.print("[cyan]The rest of the analysis will continue without spatial features.[/cyan]")
        console.print()
        if analysis_logger:
            analysis_logger.skip_phase("Spatial Analysis", "GDAL/geopandas not installed")
        return None, None

    except Exception as e:
        console.print(f"[yellow]⚠ Spatial analysis error: {e}[/yellow]")
        console.print("[cyan]Continuing without spatial analysis...[/cyan]")
        if analysis_logger:
            analysis_logger.complete_phase(success=False, message=f"Error: {e}")
        return None, None


def generate_reports(archetype_results, scenario_results, subsidy_results=None, df_validated=None, pathway_summary=None, analysis_logger: AnalysisLogger = None):
    """Generate final reports and visualizations."""
    console.print()
    console.print(Panel("[bold]Phase 5: Report Generation[/bold]", border_style="blue"))
    console.print()

    if analysis_logger:
        analysis_logger.start_phase(
            "Report Generation",
            "Generate comprehensive reports, visualizations, and Excel workbook"
        )

    console.print("[cyan]Generating comprehensive reports and visualizations...[/cyan]")

    from src.reporting.visualizations import ReportGenerator

    generator = ReportGenerator()
    reports_created = []

    # 1. EPC Band Distribution
    if archetype_results and 'epc_bands' in archetype_results and archetype_results['epc_bands']:
        try:
            generator.plot_epc_band_distribution(archetype_results['epc_bands'])
            reports_created.append("✓ EPC band distribution chart")
        except Exception as e:
            console.print(f"[yellow]⚠ Could not generate EPC band chart: {e}[/yellow]")

    # 2. SAP Score Distribution
    if df_validated is not None and 'CURRENT_ENERGY_EFFICIENCY' in df_validated.columns:
        try:
            import pandas as pd
            sap_scores = df_validated['CURRENT_ENERGY_EFFICIENCY'].dropna()
            if len(sap_scores) > 0:
                generator.plot_sap_score_distribution(sap_scores)
                reports_created.append("✓ SAP score distribution histogram")
        except Exception as e:
            console.print(f"[yellow]⚠ Could not generate SAP score chart: {e}[/yellow]")

    # 3. Scenario Comparison
    if scenario_results and len(scenario_results) > 0:
        try:
            generator.plot_scenario_comparison(scenario_results)
            reports_created.append("✓ Scenario comparison charts")
        except Exception as e:
            console.print(f"[yellow]⚠ Could not generate scenario comparison: {e}[/yellow]")

    # 4. Subsidy Sensitivity Analysis
    if subsidy_results and len(subsidy_results) > 0:
        try:
            generator.plot_subsidy_sensitivity(subsidy_results)
            reports_created.append("✓ Subsidy sensitivity analysis")
        except Exception as e:
            console.print(f"[yellow]⚠ Could not generate subsidy chart: {e}[/yellow]")

    # 5. Text and Markdown Summary Reports
    if archetype_results and scenario_results:
        try:
            # Use real pathway summary from spatial analysis if available
            import pandas as pd

            if pathway_summary is not None and len(pathway_summary) > 0:
                # Use actual spatial analysis results
                tier_summary = pathway_summary
                console.print("[cyan]Using real heat network tier data from spatial analysis[/cyan]")
            else:
                # Fallback: placeholder tier summary (if spatial analysis was skipped)
                tier_summary = pd.DataFrame({
                    'Tier': ['Tier 5 (All properties - spatial analysis not run)'],
                    'Property Count': [len(df_validated) if df_validated is not None else 0],
                    'Percentage': [100.0],
                    'Recommended Pathway': ['Heat Pump (default recommendation)']
                })

            generator.generate_summary_report(archetype_results, scenario_results, tier_summary)
            reports_created.append("✓ Executive summary report (text)")
            generator.generate_markdown_summary(archetype_results, scenario_results, tier_summary)
            reports_created.append("✓ Executive summary report (Markdown)")
        except Exception as e:
            console.print(f"[yellow]⚠ Could not generate summary report: {e}[/yellow]")

    # 6. Excel Export
    if archetype_results and scenario_results:
        try:
            generator.export_to_excel(
                archetype_results=archetype_results,
                scenario_results=scenario_results,
                subsidy_results=subsidy_results,
                df_properties=df_validated
            )
            reports_created.append("✓ Excel workbook with all results")
        except Exception as e:
            console.print(f"[yellow]⚠ Could not generate Excel export: {e}[/yellow]")

    console.print()
    console.print(f"[green]✓[/green] Report generation complete!")
    console.print()

    if reports_created:
        console.print("[cyan]Generated outputs:[/cyan]")
        for report in reports_created:
            console.print(f"    {report}")
    else:
        console.print("[yellow]No reports could be generated (missing data)[/yellow]")

    console.print()
    console.print(f"[cyan]📁 Output location:[/cyan] data/outputs/")
    console.print(f"    • Figures: data/outputs/figures/")
    console.print(f"    • Reports: data/outputs/reports/")
    console.print(f"    • Results: data/outputs/*.txt")

    if analysis_logger:
        analysis_logger.add_metric("reports_generated", len(reports_created), f"{len(reports_created)} reports and visualizations")
        for report in reports_created:
            # Extract file types from report descriptions
            if "chart" in report.lower() or "histogram" in report.lower():
                analysis_logger.add_output("data/outputs/figures/", "png", report.replace("✓ ", ""))
        analysis_logger.add_output("data/outputs/heat_street_analysis_results.xlsx", "xlsx", "Comprehensive Excel workbook")
        analysis_logger.add_output("data/outputs/reports/executive_summary.txt", "report", "Executive summary (text)")
        analysis_logger.add_output("data/outputs/reports/executive_summary.md", "report", "Executive summary (Markdown)")
        analysis_logger.complete_phase(success=True, message=f"{len(reports_created)} reports and visualizations generated")

    return True


def generate_additional_reports(df_raw, df_validated, validation_report, archetype_results, scenario_results, analysis_logger: AnalysisLogger = None):
    """Generate additional specialized reports for client presentation."""
    console.print()
    console.print(Panel("[bold]Phase 5.5: Additional Reports[/bold]", border_style="blue"))
    console.print()

    if analysis_logger:
        analysis_logger.start_phase(
            "Additional Reports",
            "Generate specialized reports (case streets, borough breakdown, data quality, subsidy analysis)"
        )

    from src.analysis.additional_reports import AdditionalReports
    from pathlib import Path

    reporter = AdditionalReports()
    reports_created = []

    output_dir = Path("data/outputs")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Shakespeare Crescent Extract
    try:
        console.print("[cyan]Extracting Shakespeare Crescent data...[/cyan]")
        case_street_path = output_dir / "shakespeare_crescent_extract.csv"
        case_street_df, case_street_summary = reporter.extract_case_street(
            df_validated,
            street_name="Shakespeare Crescent",
            output_path=case_street_path
        )
        if len(case_street_df) > 0:
            reports_created.append(f"✓ Shakespeare Crescent extract ({len(case_street_df)} properties)")
        else:
            console.print("[yellow]  No properties found on Shakespeare Crescent[/yellow]")
    except Exception as e:
        console.print(f"[yellow]⚠ Could not generate case street extract: {e}[/yellow]")
        case_street_df, case_street_summary = None, None

    # 2. Borough-level Breakdown
    try:
        console.print("[cyan]Generating borough-level breakdown...[/cyan]")
        borough_path = output_dir / "borough_breakdown.csv"
        borough_df = reporter.generate_borough_breakdown(
            df_validated,
            output_path=borough_path
        )
        reports_created.append(f"✓ Borough breakdown ({len(borough_df)} boroughs)")
    except Exception as e:
        console.print(f"[yellow]⚠ Could not generate borough breakdown: {e}[/yellow]")
        borough_df = None

    # 3. Data Quality Report
    try:
        console.print("[cyan]Generating data quality report...[/cyan]")
        quality_path = output_dir / "data_quality_report.txt"
        quality_report = reporter.generate_data_quality_report(
            df_raw,
            df_validated,
            validation_report,
            output_path=quality_path
        )
        reports_created.append("✓ Data quality report")
    except Exception as e:
        console.print(f"[yellow]⚠ Could not generate data quality report: {e}[/yellow]")

    # 4. Subsidy Sensitivity Analysis
    try:
        console.print("[cyan]Running subsidy sensitivity analysis...[/cyan]")
        subsidy_path = output_dir / "subsidy_sensitivity_analysis.csv"
        sensitivity_df = reporter.subsidy_sensitivity_analysis(
            df_validated,
            scenario_results,
            subsidy_levels=[0, 5000, 7500, 10000, 15000],
            output_path=subsidy_path
        )
        reports_created.append("✓ Subsidy sensitivity analysis")
    except Exception as e:
        console.print(f"[yellow]⚠ Could not generate subsidy sensitivity: {e}[/yellow]")

    # 5. Heat Network Connection Thresholds
    try:
        console.print("[cyan]Analyzing heat network connection thresholds...[/cyan]")
        threshold_path = output_dir / "heat_network_connection_thresholds.csv"
        # Check if heat network tier exists
        if 'heat_network_tier' in df_validated.columns:
            threshold_df = reporter.analyze_heat_network_connection_thresholds(
                df_validated,
                tier_field='heat_network_tier',
                tier_values=['Tier 3: High heat density', 'Tier 4: Medium heat density'],
                output_path=threshold_path
            )
            reports_created.append("✓ Heat network connection threshold analysis")
        else:
            console.print("[yellow]  Heat network tier not found, skipping threshold analysis[/yellow]")
    except Exception as e:
        console.print(f"[yellow]⚠ Could not generate connection thresholds: {e}[/yellow]")

    console.print()
    console.print(f"[green]✓[/green] Additional reports complete!")
    console.print()

    if reports_created:
        console.print("[cyan]Generated reports:[/cyan]")
        for report in reports_created:
            console.print(f"    {report}")

    if analysis_logger:
        analysis_logger.add_metric("additional_reports", len(reports_created), f"{len(reports_created)} specialized reports")
        analysis_logger.add_output("data/outputs/borough_breakdown.csv", "csv", "Borough-level breakdown")
        analysis_logger.add_output("data/outputs/subsidy_sensitivity_analysis.csv", "csv", "Subsidy sensitivity analysis")
        analysis_logger.add_output("data/outputs/data_quality_report.txt", "report", "Data quality assessment")
        analysis_logger.complete_phase(success=True, message=f"{len(reports_created)} additional specialized reports generated")

    return {
        "case_street_df": case_street_df,
        "case_street_summary": case_street_summary,
        "borough_breakdown": borough_df,
    }


def package_dashboard_assets(
    archetype_results,
    scenario_results,
    readiness_summary,
    pathway_summary=None,
    additional_reports=None,
    subsidy_results=None,
    df_validated=None,
    analysis_logger: AnalysisLogger = None,
):
    """Export dashboard JSON data into outputs and the React app.

    This phase consolidates all analysis outputs into a single JSON file
    that addresses all 12 CLIENT_QUESTIONS sections:
    1. Fabric Detail Granularity
    2. Retrofit Measures & Packages
    3. Radiator Upsizing
    4. Window Upgrades (Double vs Triple)
    5. Payback Times
    6. Pathways & Hybrid Scenarios
    7. EPC Data Robustness (Anomalies & Uncertainty)
    8. Fabric Tipping Point Curve
    9. Load Profiles & System Impacts
    10. Heat Network Penetration & Price Sensitivity
    11. Tenure Filtering
    12. Documentation & Tests
    """
    console.print()
    console.print(Panel("[bold]Phase 6: Dashboard Packaging[/bold]", border_style="blue"))
    console.print()

    if analysis_logger:
        analysis_logger.start_phase(
            "Dashboard Packaging",
            "Export latest analysis results for the React dashboard",
        )

    try:
        from src.reporting.dashboard_data_builder import DashboardDataBuilder
        import pandas as pd

        builder = DashboardDataBuilder()
        case_summary = (additional_reports or {}).get("case_street_summary") if additional_reports else None
        borough_breakdown = (additional_reports or {}).get("borough_breakdown") if additional_reports else None

        # Load additional data files if they exist
        load_profile_summary = None
        tipping_point_curve = None
        retrofit_packages_summary = None

        outputs_dir = Path("data/outputs")

        # Load load profiles summary (Section 9)
        load_profiles_file = outputs_dir / "pathway_load_profile_summary.csv"
        if load_profiles_file.exists():
            try:
                load_profile_summary = pd.read_csv(load_profiles_file)
                console.print(f"[green]✓[/green] Loaded load profile summary")
            except Exception as e:
                logger.debug(f"Could not load load profiles: {e}")

        # Load tipping point curve (Section 8)
        tipping_point_file = outputs_dir / "fabric_tipping_point_curve.csv"
        if tipping_point_file.exists():
            try:
                tipping_point_curve = pd.read_csv(tipping_point_file)
                console.print(f"[green]✓[/green] Loaded fabric tipping point curve")
            except Exception as e:
                logger.debug(f"Could not load tipping point curve: {e}")

        # Load retrofit packages summary (Section 2, 3, 5)
        retrofit_packages_file = outputs_dir / "retrofit_packages_summary.csv"
        if retrofit_packages_file.exists():
            try:
                retrofit_packages_summary = pd.read_csv(retrofit_packages_file)
                console.print(f"[green]✓[/green] Loaded retrofit packages summary")
            except Exception as e:
                logger.debug(f"Could not load retrofit packages: {e}")

        dataset = builder.build_dataset(
            archetype_results,
            scenario_results,
            readiness_summary,
            pathway_summary,
            borough_breakdown,
            case_summary,
            subsidy_results,
            df_validated,
            load_profile_summary,
            tipping_point_curve,
            retrofit_packages_summary,
        )

        dataset_path = builder.write_dataset(dataset)

        # Copy into dashboard public assets so the React app loads latest data
        public_dir = Path("dashboard/public")
        public_dir.mkdir(parents=True, exist_ok=True)
        public_dataset = public_dir / "dashboard-data.json"
        shutil.copy2(dataset_path, public_dataset)

        console.print(f"[green]✓[/green] Dashboard data saved to {dataset_path}")
        console.print(f"[green]✓[/green] React dashboard updated at {public_dataset}")

        # Log summary of data arrays included
        data_arrays = [k for k in dataset.keys() if isinstance(dataset.get(k), list) and len(dataset.get(k, [])) > 0]
        console.print(f"[cyan]Data arrays included:[/cyan] {len(data_arrays)}")
        for arr in data_arrays:
            count = len(dataset[arr]) if isinstance(dataset[arr], list) else 1
            console.print(f"    • {arr}: {count} items")

        if analysis_logger:
            analysis_logger.add_output(
                str(dataset_path),
                "json",
                "Dashboard dataset for React UI",
            )
            analysis_logger.add_metric("dashboard_data_arrays", len(data_arrays), "Data arrays in dashboard JSON")
            analysis_logger.complete_phase(success=True, message="Dashboard data exported")
    except Exception as e:
        console.print(f"[yellow]⚠ Could not package dashboard: {e}[/yellow]")
        logger.exception("Dashboard packaging error")
        if analysis_logger:
            analysis_logger.complete_phase(success=False, message=f"Error: {e}")
        return False

    return True


def check_existing_data():
    """Check if previously downloaded data exists."""
    raw_csv = DATA_RAW_DIR / "epc_london_raw.csv"
    filtered_csv = DATA_RAW_DIR / "epc_london_filtered.csv"

    if raw_csv.exists() or filtered_csv.exists():
        # Get file info
        if filtered_csv.exists():
            import os
            file_size = os.path.getsize(filtered_csv) / (1024 * 1024)  # MB
            mod_time = os.path.getmtime(filtered_csv)
            from datetime import datetime
            mod_date = datetime.fromtimestamp(mod_time).strftime('%Y-%m-%d %H:%M')

            # Quick count of records
            import pandas as pd
            try:
                df = pd.read_csv(filtered_csv, nrows=0)
                line_count = sum(1 for _ in open(filtered_csv)) - 1  # Subtract header

                console.print()
                console.print(Panel(
                    f"[bold cyan]Existing Data Found[/bold cyan]\n\n"
                    f"File: epc_london_filtered.csv\n"
                    f"Size: {file_size:.1f} MB\n"
                    f"Records: ~{line_count:,}\n"
                    f"Last modified: {mod_date}",
                    border_style="green"
                ))
                console.print()

                return True, filtered_csv, line_count
            except Exception as e:
                logger.debug(f"Could not read existing data: {e}")
                return False, None, 0

        elif raw_csv.exists():
            import os
            file_size = os.path.getsize(raw_csv) / (1024 * 1024)
            mod_time = os.path.getmtime(raw_csv)
            from datetime import datetime
            mod_date = datetime.fromtimestamp(mod_time).strftime('%Y-%m-%d %H:%M')

            console.print()
            console.print(Panel(
                f"[bold cyan]Existing Data Found[/bold cyan]\n\n"
                f"File: epc_london_raw.csv\n"
                f"Size: {file_size:.1f} MB\n"
                f"Last modified: {mod_date}",
                border_style="green"
            ))
            console.print()

            return True, raw_csv, 0

    return False, None, 0


def load_existing_data(file_path, analysis_logger: AnalysisLogger = None):
    """Load previously downloaded data from file."""
    console.print()
    console.print(Panel("[bold]Phase 1: Loading Existing Data[/bold]", border_style="blue"))
    console.print()

    if analysis_logger:
        analysis_logger.start_phase(
            "Loading Existing Data",
            "Load previously downloaded EPC data from file"
        )

    console.print(f"[cyan]Loading data from {file_path.name}...[/cyan]")

    import pandas as pd
    df = pd.read_csv(file_path)

    console.print(f"[green]✓[/green] Loaded {len(df):,} records")

    if analysis_logger:
        analysis_logger.add_metric("records_loaded", len(df), "Records loaded from existing file")
        analysis_logger.add_output(str(file_path), "csv", "Existing EPC data loaded")
        analysis_logger.complete_phase(success=True, message=f"Loaded {len(df):,} existing records")

    return df


def main():
    """Main execution function."""
    print_header()

    # Check credentials
    if not check_credentials():
        console.print("[red]Cannot proceed without API credentials[/red]")
        return

    console.print("[green]✓[/green] API credentials configured")
    console.print()

    # Ensure directories exist
    ensure_directories()

    # Initialize analysis logger
    analysis_logger = AnalysisLogger()
    console.print("[green]✓[/green] Analysis logger initialized")
    console.print()

    # Ask about GIS data download
    ask_gis_download()

    # Check for existing data
    has_existing, existing_file, record_count = check_existing_data()

    df = None

    if has_existing:
        use_existing = questionary.confirm(
            "Use existing downloaded data?",
            default=True
        ).ask()

        if use_existing:
            df = load_existing_data(existing_file, analysis_logger)
        else:
            console.print()
            console.print("[yellow]Downloading new data (existing data will be overwritten)...[/yellow]")
            console.print()

    # If not using existing data, download new
    if df is None or df.empty:
        # Ask what to download
        scope = ask_download_scope()

        # Show summary
        console.print()
        console.print(Panel(
            f"[bold]Analysis Configuration[/bold]\n\n"
            f"Mode: {scope['mode']}\n"
            f"From year: {scope['from_year']}\n"
            f"Boroughs: {len(scope['boroughs']) if scope['boroughs'] else 'All (33)'}",
            border_style="cyan"
        ))
        console.print()

        proceed = questionary.confirm(
            "Start download?",
            default=True
        ).ask()

        if not proceed:
            console.print("[yellow]Analysis cancelled[/yellow]")
            return

        # Run pipeline
        start_time = time.time()

        # Phase 1: Download
        df = download_data(scope, analysis_logger)
        if df is None or df.empty:
            console.print("[red]✗ Analysis stopped - no data available[/red]")
            return
    else:
        start_time = time.time()
        console.print()
        console.print("[cyan]Proceeding with existing data...[/cyan]")
        console.print()

    # Set metadata
    analysis_logger.set_metadata("total_properties", len(df))

    # Phase 2: Validate
    df_validated, validation_report = validate_data(df, analysis_logger)
    if df_validated.empty:
        console.print("[red]✗ Analysis stopped - no valid data[/red]")
        return

    # Keep reference to raw data for quality reports
    df_raw = df.copy()

    # Phase 2.5: Methodological Adjustments
    df_adjusted = apply_methodological_adjustments(df_validated, analysis_logger)

    # Phase 3: Analyze (use adjusted data)
    archetype_results = analyze_archetype(df_adjusted, analysis_logger)

    # Phase 4: Model (use adjusted data for realistic baselines)
    scenario_results, subsidy_results = model_scenarios(df_adjusted, analysis_logger)

    # Phase 4.3: Retrofit Readiness
    df_readiness, readiness_summary = analyze_retrofit_readiness(df_adjusted, analysis_logger)

    # Phase 4.5: Spatial Analysis (optional)
    properties_with_tiers, pathway_summary = run_spatial_analysis(df_adjusted, analysis_logger)

    # Phase 5: Report
    generate_reports(archetype_results, scenario_results, subsidy_results, df_adjusted, pathway_summary, analysis_logger)

    # Phase 5.5: Additional Reports
    additional_outputs = generate_additional_reports(
        df_raw,
        df_adjusted,
        validation_report,
        archetype_results,
        scenario_results,
        analysis_logger,
    )

    # Phase 6: Package dashboard
    package_dashboard_assets(
        archetype_results,
        scenario_results,
        readiness_summary,
        pathway_summary,
        additional_outputs,
        subsidy_results,
        df_adjusted,
        analysis_logger,
    )

    # Complete
    elapsed = time.time() - start_time

    # Save analysis log
    console.print()
    console.print("[cyan]Saving analysis log...[/cyan]")
    log_path = analysis_logger.save_log()
    console.print(f"[green]✓[/green] Analysis log saved to: {log_path}")

    # Show summary statistics
    summary_stats = analysis_logger.get_summary_stats()
    console.print()
    console.print(f"[cyan]Analysis Summary:[/cyan]")
    console.print(f"  • Total phases: {summary_stats['total_phases']}")
    console.print(f"  • Successful: {summary_stats['successful_phases']}")
    console.print(f"  • Failed: {summary_stats['failed_phases']}")
    console.print(f"  • Skipped: {summary_stats['skipped_phases']}")

    console.print()
    console.print(Panel.fit(
        f"[bold green]✓ Analysis Complete![/bold green]\n\n"
        f"Time elapsed: {elapsed/60:.1f} minutes\n"
        f"Properties analyzed: {len(df_validated):,}\n\n"
        f"[cyan]Results saved to:[/cyan]\n"
        f"  • data/processed/ (validated data)\n"
        f"  • data/outputs/ (reports and charts)\n"
        f"  • data/outputs/analysis_log.txt (analysis log)",
        border_style="green"
    ))
    console.print()

    # Ask if user wants to open results
    open_results = questionary.confirm(
        "Open results folder?",
        default=True
    ).ask()

    if open_results:
        import subprocess
        import platform

        if platform.system() == 'Windows':
            subprocess.run(['explorer', 'data\\outputs'])
        elif platform.system() == 'Darwin':  # macOS
            subprocess.run(['open', 'data/outputs'])
        else:  # Linux
            subprocess.run(['xdg-open', 'data/outputs'])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Analysis interrupted by user[/yellow]")
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        logger.exception("Unexpected error in main pipeline")
