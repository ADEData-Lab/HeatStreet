"""
Heat Street EPC Analysis - Complete Interactive Pipeline

Runs the entire analysis from data download to report generation
with interactive prompts and progress indicators.
"""

import os
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


def download_data(scope):
    """Download EPC data via API."""
    console.print()
    console.print(Panel("[bold]Phase 1: Data Download[/bold]", border_style="blue"))
    console.print()

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
            return None

        console.print(f"[green]✓[/green] Downloaded {len(df):,} records")

        # Apply Edwardian filters
        console.print("[cyan]Applying Edwardian terraced housing filters...[/cyan]")
        df_filtered = downloader.apply_edwardian_filters(df)
        console.print(f"[green]✓[/green] Filtered to {len(df_filtered):,} Edwardian terraced houses")

        # Save data
        console.print("[cyan]Saving data...[/cyan]")
        downloader.save_data(df, "epc_london_raw.csv")
        downloader.save_data(df_filtered, "epc_london_filtered.csv")
        console.print(f"[green]✓[/green] Data saved to data/raw/")

        return df_filtered

    except ValueError as e:
        console.print(f"[red]✗[/red] Error: {e}", style="red")
        return None
    except Exception as e:
        console.print(f"[red]✗[/red] Unexpected error: {e}", style="red")
        return None


def validate_data(df):
    """Validate and clean data."""
    console.print()
    console.print(Panel("[bold]Phase 2: Data Validation[/bold]", border_style="blue"))
    console.print()

    console.print("[cyan]Running quality assurance checks...[/cyan]")

    validator = EPCDataValidator()
    df_validated, report = validator.validate_dataset(df)

    console.print(f"[green]✓[/green] Validation complete")
    console.print(f"    Records passed: {len(df_validated):,} ({len(df_validated)/report['total_records']*100:.1f}%)")
    console.print(f"    Duplicates removed: {report['duplicates_removed']:,}")
    console.print(f"    Invalid records: {report['total_records'] - len(df_validated):,}")

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

    return df_validated


def analyze_archetype(df):
    """Run archetype characterization."""
    console.print()
    console.print(Panel("[bold]Phase 3: Archetype Analysis[/bold]", border_style="blue"))
    console.print()

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
    else:
        console.print()
        console.print("[yellow]Note: EPC band distribution analysis could not be completed (missing required columns)[/yellow]")

    return results


def model_scenarios(df):
    """Run scenario modeling."""
    console.print()
    console.print(Panel("[bold]Phase 4: Scenario Modeling[/bold]", border_style="blue"))
    console.print()

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

    return scenario_results, subsidy_results


def analyze_retrofit_readiness(df):
    """Analyze heat pump retrofit readiness."""
    console.print()
    console.print(Panel("[bold]Phase 4.3: Retrofit Readiness Analysis[/bold]", border_style="blue"))
    console.print()

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

        # Generate visualizations
        console.print("[cyan]Creating retrofit readiness visualizations...[/cyan]")

        from src.reporting.visualizations import ReportGenerator
        viz = ReportGenerator()

        viz.plot_retrofit_readiness_dashboard(df_readiness, summary)
        viz.plot_fabric_cost_distribution(df_readiness)
        viz.plot_heat_demand_scatter(df_readiness)

        console.print(f"[green]✓[/green] Visualizations saved to data/outputs/figures/")

        return df_readiness, summary

    except Exception as e:
        console.print(f"[yellow]⚠ Retrofit readiness analysis failed: {e}[/yellow]")
        logger.error(f"Retrofit readiness error: {e}")
        return None, None


def run_spatial_analysis(df):
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

            return pathway_summary
        else:
            console.print("[yellow]⚠ Spatial analysis could not complete[/yellow]")
            return None

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
        return None

    except Exception as e:
        console.print(f"[yellow]⚠ Spatial analysis error: {e}[/yellow]")
        console.print("[cyan]Continuing without spatial analysis...[/cyan]")
        return None


def generate_reports(archetype_results, scenario_results, subsidy_results=None, df_validated=None, pathway_summary=None):
    """Generate final reports and visualizations."""
    console.print()
    console.print(Panel("[bold]Phase 5: Report Generation[/bold]", border_style="blue"))
    console.print()

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

    # 5. Text Summary Report
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
            reports_created.append("✓ Executive summary report")
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

    return True


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

    # Ask about GIS data download
    ask_gis_download()

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
        "Start analysis?",
        default=True
    ).ask()

    if not proceed:
        console.print("[yellow]Analysis cancelled[/yellow]")
        return

    # Run pipeline
    start_time = time.time()

    # Phase 1: Download
    df = download_data(scope)
    if df is None or df.empty:
        console.print("[red]✗ Analysis stopped - no data available[/red]")
        return

    # Phase 2: Validate
    df_validated = validate_data(df)
    if df_validated.empty:
        console.print("[red]✗ Analysis stopped - no valid data[/red]")
        return

    # Phase 3: Analyze
    archetype_results = analyze_archetype(df_validated)

    # Phase 4: Model
    scenario_results, subsidy_results = model_scenarios(df_validated)

    # Phase 4.3: Retrofit Readiness
    df_readiness, readiness_summary = analyze_retrofit_readiness(df_validated)

    # Phase 4.5: Spatial Analysis (optional)
    pathway_summary = run_spatial_analysis(df_validated)

    # Phase 5: Report
    generate_reports(archetype_results, scenario_results, subsidy_results, df_validated, pathway_summary)

    # Complete
    elapsed = time.time() - start_time

    console.print()
    console.print(Panel.fit(
        f"[bold green]✓ Analysis Complete![/bold green]\n\n"
        f"Time elapsed: {elapsed/60:.1f} minutes\n"
        f"Properties analyzed: {len(df_validated):,}\n\n"
        f"[cyan]Results saved to:[/cyan]\n"
        f"  • data/processed/ (validated data)\n"
        f"  • data/outputs/ (reports and charts)",
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
