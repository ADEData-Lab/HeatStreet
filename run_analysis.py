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

    parquet_file = output_file.with_suffix('.parquet')
    df_validated.to_parquet(parquet_file, index=False)

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


def generate_reports(archetype_results, scenario_results):
    """Generate final reports."""
    console.print()
    console.print(Panel("[bold]Phase 5: Report Generation[/bold]", border_style="blue"))
    console.print()

    console.print("[cyan]Generating reports and visualizations...[/cyan]")

    from src.reporting.visualizations import ReportGenerator

    generator = ReportGenerator()

    # Generate visualizations
    if archetype_results and 'epc_bands' in archetype_results:
        generator.plot_epc_band_distribution(archetype_results['epc_bands'])

    if scenario_results:
        generator.plot_scenario_comparison(scenario_results)

    console.print(f"[green]✓[/green] Reports generated")
    console.print(f"    Location: data/outputs/")

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

    # Phase 5: Report
    generate_reports(archetype_results, scenario_results)

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
