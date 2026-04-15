"""
Heat Street EPC Analysis - Complete Interactive Pipeline

Runs the entire analysis from data download to report generation
with interactive prompts and progress indicators.
"""

import os
import json
import shutil
import sys
import subprocess
import gc
import re
import platform
from pathlib import Path
from typing import Tuple, Union
from datetime import date as date_cls, datetime
from loguru import logger
import questionary
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel
from rich import print as rprint
import time

# Add src to path
sys.path.append(str(Path(__file__).parent))

from config.config import load_config, ensure_directories, DATA_RAW_DIR, DATA_PROCESSED_DIR, DATA_OUTPUTS_DIR
from src.acquisition.epc_api_downloader import EPCAPIDownloader
from src.acquisition.london_gis_downloader import LondonGISDownloader
from src.acquisition.hnpd_downloader import HNPDDownloader
from src.cleaning.data_validator import EPCDataValidator
from src.analysis.archetype_analysis import ArchetypeAnalyzer
from src.modeling.scenario_model import ScenarioModeler
from src.modeling.pathway_model import PathwayModeler
from src.reporting.comparisons import ComparisonReporter
from src.utils.analysis_logger import AnalysisLogger


console = Console()


def validate_email(email: str) -> Union[bool, str]:
    """
    Validate email address format.

    Returns:
        True if valid, error message string if invalid
    """
    if not email or '@' not in email:
        return "Email address must contain '@'"

    # RFC 5322 simplified regex
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(pattern, email):
        return "Please enter a valid email (e.g., user@example.com)"

    return True


def validate_api_key(api_key: str) -> Union[bool, str]:
    """
    Validate API key format.

    Returns:
        True if valid, error message string if invalid
    """
    if not api_key or len(api_key.strip()) == 0:
        return "API key cannot be empty"

    # EPC API keys: 10-64 alphanumeric characters
    if len(api_key) < 10:
        return "API key too short (expected ≥10 characters)"

    if not re.match(r'^[a-zA-Z0-9\-_]+$', api_key):
        return "API key contains invalid characters"

    return True


def parse_iso_date(value: str) -> date_cls:
    """Parse an ISO YYYY-MM-DD date string."""
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def validate_end_date(value: str) -> Union[bool, str]:
    """Validate sample end date input."""
    if not value or not value.strip():
        return "End date cannot be empty"

    try:
        parse_iso_date(value)
    except ValueError:
        return "Please enter a valid date in YYYY-MM-DD format"

    return True


def validate_start_date(value: str, sample_end_date: date_cls) -> Union[bool, str]:
    """Validate sample start date input against the selected end date."""
    if not value or not value.strip():
        return "Start date cannot be empty"

    try:
        sample_start_date = parse_iso_date(value)
    except ValueError:
        return "Please enter a valid date in YYYY-MM-DD format"

    if sample_start_date > sample_end_date:
        return f"Start date cannot be after end date ({sample_end_date.isoformat()})"

    return True


def compute_sample_start_date(sample_end_date: date_cls) -> date_cls:
    """
    Compute the exact inclusive 10-year sample start date.

    Uses the same calendar day 10 years earlier, with a leap-year fallback to
    28 February when needed.
    """
    try:
        return sample_end_date.replace(year=sample_end_date.year - 10)
    except ValueError:
        return sample_end_date.replace(year=sample_end_date.year - 10, day=28)


def prompt_sample_end_date() -> date_cls:
    """Prompt for the sample end date, defaulting to today."""
    default_value = date_cls.today().isoformat()
    sample_end_text = questionary.text(
        "Sample end date (YYYY-MM-DD):",
        default=default_value,
        validate=validate_end_date,
    ).ask()

    if sample_end_text is None:
        raise KeyboardInterrupt("Sample end date input cancelled")

    return parse_iso_date(sample_end_text)


def prompt_sample_window() -> Tuple[date_cls, date_cls]:
    """Prompt for a fully configurable sample window."""
    sample_end_date = prompt_sample_end_date()
    default_start_date = compute_sample_start_date(sample_end_date).isoformat()
    sample_start_text = questionary.text(
        "Sample start date (YYYY-MM-DD):",
        default=default_start_date,
        validate=lambda value: validate_start_date(value, sample_end_date),
    ).ask()

    if sample_start_text is None:
        raise KeyboardInterrupt("Sample start date input cancelled")

    sample_start_date = parse_iso_date(sample_start_text)
    return sample_start_date, sample_end_date


def metadata_sidecar_path(file_path: Path) -> Path:
    """Return the sidecar metadata path for a dataset."""
    return file_path.with_name(f"{file_path.stem}_metadata.json")


def write_sample_window_metadata(
    file_path: Path,
    sample_start_date: date_cls,
    sample_end_date: date_cls,
    dataset_type: str,
) -> None:
    """Persist sample-window metadata for a dataset."""
    metadata = {
        "dataset_path": str(file_path),
        "dataset_type": dataset_type,
        "sample_start_date": sample_start_date.isoformat(),
        "sample_end_date": sample_end_date.isoformat(),
        "written_at": datetime.now().isoformat(),
    }
    metadata_sidecar_path(file_path).write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )


def read_sample_window_metadata(file_path: Path):
    """Load dataset sidecar metadata if present."""
    metadata_path = metadata_sidecar_path(file_path)
    if not metadata_path.exists():
        return None

    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Could not read sample window metadata from {metadata_path}: {e}")
        return None


def sample_window_matches(file_path: Path, sample_start_date: date_cls, sample_end_date: date_cls) -> bool:
    """Return True when dataset metadata matches the requested sample window."""
    metadata = read_sample_window_metadata(file_path)
    if not metadata:
        return False

    return (
        metadata.get("sample_start_date") == sample_start_date.isoformat()
        and metadata.get("sample_end_date") == sample_end_date.isoformat()
    )


def is_one_stop_only(config=None) -> bool:
    """Return True when reporting is restricted to the one-stop markdown output."""
    config = config or load_config()
    return bool(config.get("reporting", {}).get("one_stop_only", False))


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
            validate=validate_email
        ).ask()

        if email is None:
            console.print("[yellow]Credential input cancelled[/yellow]")
            return False

        api_key = questionary.text(
            "API key:",
            validate=validate_api_key
        ).ask()

        if api_key is None:
            console.print("[yellow]Credential input cancelled[/yellow]")
            return False

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

    download = True  # Automatically download GIS data for spatial analysis

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


def ask_hnpd_download():
    """Ask if user wants to download BEIS Heat Network Planning Database."""
    console.print()
    console.print("[cyan]BEIS Heat Network Planning Database (Recommended)[/cyan]")
    console.print()
    console.print("The HNPD provides current heat network data (January 2024) for:")
    console.print("  • Operational heat networks across the UK")
    console.print("  • Networks under construction")
    console.print("  • Planned networks with planning permission")
    console.print("  • More accurate than 2012 London Heat Map data")
    console.print()

    # Check if already downloaded
    hnpd_downloader = HNPDDownloader()
    summary = hnpd_downloader.get_data_summary()

    if summary['available']:
        console.print("[green]✓[/green] HNPD data already downloaded")
        console.print(f"    Total records: {summary['total_records']}")
        console.print(f"    Tier 1 networks: {summary['tier_1_networks']} (operational/under construction)")
        console.print(f"    Tier 2 networks: {summary['tier_2_networks']} (planning granted)")
        console.print(f"    Regions covered: {summary['region_count']}")
        return True

    download = True  # Automatically download HNPD data

    if download:
        console.print()
        console.print("[cyan]Downloading BEIS Heat Network Planning Database...[/cyan]")

        if hnpd_downloader.download_and_prepare():
            console.print("[green]✓[/green] HNPD data downloaded and ready")
            summary = hnpd_downloader.get_data_summary()
            console.print(f"    {summary['total_records']} heat network records loaded")
            console.print(f"    {summary['tier_1_networks']} Tier 1 + {summary['tier_2_networks']} Tier 2 networks")
            return True
        else:
            console.print("[yellow]⚠[/yellow] HNPD download failed (will use London Heat Map 2012 as fallback)")
            return False

    console.print("[yellow]⚠[/yellow] Skipping HNPD download (will use London Heat Map 2012 as fallback)")
    return False


def download_data(
    analysis_logger: AnalysisLogger = None,
    sample_start_date: date_cls = None,
    sample_end_date: date_cls = None,
):
    """Download EPC data via API."""
    console.print()
    console.print(Panel("[bold]Phase 1: Data Download[/bold]", border_style="blue"))
    console.print()

    downloader = EPCAPIDownloader()
    from_year = sample_start_date.year if sample_start_date else 2015

    download_scope = questionary.select(
        "Select download scope:",
        choices=[
            "All London boroughs (full dataset)",
            "Single borough (testing)",
        ],
    ).ask()

    if not download_scope:
        console.print("[yellow]⚠[/yellow] Download cancelled by user", style="yellow")
        return None

    selected_borough = None
    if download_scope == "Single borough (testing)":
        selected_borough = questionary.autocomplete(
            "Select borough:",
            choices=list(downloader.LONDON_LA_CODES.keys()),
        ).ask()

        if not selected_borough:
            console.print("[yellow]⚠[/yellow] Download cancelled by user", style="yellow")
            return None

    if analysis_logger:
        analysis_logger.start_phase(
            "Data Download",
            "Download EPC data from API and filter for Edwardian terraced houses"
        )

    try:
        if selected_borough:
            console.print(f"[cyan]Downloading {selected_borough} only...[/cyan]")
            df = downloader.download_borough_data(
                selected_borough,
                property_type='house',
                from_year=from_year,
                sample_start_date=sample_start_date,
                sample_end_date=sample_end_date,
                max_results=None,
                log_borough=True,
                show_progress=True,
            )
        else:
            console.print("[cyan]Downloading ALL London boroughs (this will take a while)...[/cyan]")
            df = downloader.download_all_london_boroughs(
                property_types=['house'],
                from_year=from_year,
                sample_start_date=sample_start_date,
                sample_end_date=sample_end_date,
                max_results_per_borough=None,
                log_boroughs=False,
            )

        if df.empty:
            console.print("[red]✗[/red] No data downloaded", style="red")
            if analysis_logger:
                analysis_logger.complete_phase(success=False, message="No data downloaded from API")
            return None

        console.print(f"[green]✓[/green] Downloaded {len(df):,} records")

        if analysis_logger:
            analysis_logger.add_metric("raw_records_downloaded", len(df), "Total records from API")
            analysis_logger.add_metric("from_year", from_year)
            if sample_start_date:
                analysis_logger.add_metric("sample_start_date", sample_start_date.isoformat(), "Exact inclusive sample start date")
            if sample_end_date:
                analysis_logger.add_metric("sample_end_date", sample_end_date.isoformat(), "Exact inclusive sample end date")

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
        if sample_start_date and sample_end_date:
            write_sample_window_metadata(
                DATA_RAW_DIR / "epc_london_raw.csv",
                sample_start_date,
                sample_end_date,
                "raw_epc_download",
            )
            write_sample_window_metadata(
                DATA_RAW_DIR / "epc_london_filtered.csv",
                sample_start_date,
                sample_end_date,
                "filtered_epc_download",
            )
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


def validate_data(
    df,
    analysis_logger: AnalysisLogger = None,
    sample_start_date: date_cls = None,
    sample_end_date: date_cls = None,
):
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
        analysis_logger.add_metric("negative_energy_values", report.get('negative_energy_values', 0), "Records with negative ENERGY_CONSUMPTION_CURRENT")
        analysis_logger.add_metric("negative_co2_values", report.get('negative_co2_values', 0), "Records with negative CO2_EMISSIONS_CURRENT")

    # Save validated data
    import pandas as pd
    output_file = DATA_PROCESSED_DIR / "epc_london_validated.csv"
    df_validated.to_csv(output_file, index=False)
    if sample_start_date and sample_end_date:
        write_sample_window_metadata(
            output_file,
            sample_start_date,
            sample_end_date,
            "validated_epc_dataset",
        )

    # Try to save parquet (optional for performance)
    try:
        parquet_file = output_file.with_suffix('.parquet')
        # Convert object/categorical columns to strings for parquet compatibility
        # Save original dtypes to restore after
        cat_cols = df_validated.select_dtypes(include=['category']).columns.tolist()
        obj_cols = df_validated.select_dtypes(include=['object']).columns.tolist()
        cols_to_convert = cat_cols + obj_cols

        if cols_to_convert:
            original_dtypes = {col: df_validated[col].dtype for col in cols_to_convert}
            for col in cols_to_convert:
                df_validated[col] = df_validated[col].astype(str)

        df_validated.to_parquet(parquet_file, index=False)

        # Restore original dtypes
        if cols_to_convert:
            for col, dtype in original_dtypes.items():
                if col in df_validated.columns:
                    df_validated[col] = df_validated[col].astype(dtype)
    except Exception as e:
        console.print(f"[yellow]Note: Could not save parquet format (CSV saved successfully)[/yellow]")
        logger.debug(f"Parquet save failed: {e}")

    validator.save_validation_report()
    try:
        validation_report_json = DATA_PROCESSED_DIR / "validation_report.json"

        # Ensure JSON is always written (numpy scalar types can otherwise truncate the file mid-write).
        from src.utils.analysis_logger import convert_to_json_serializable

        report = dict(report)
        report["records_passed"] = int(len(df_validated))
        total_records = int(report.get("total_records", len(df)))
        duplicates_removed = int(report.get("duplicates_removed", 0))
        report["invalid_records"] = max(total_records - duplicates_removed - int(report["records_passed"]), 0)

        with open(validation_report_json, "w", encoding="utf-8") as f:
            json.dump(convert_to_json_serializable(report), f, indent=2)
    except Exception as e:
        logger.debug(f"Could not save validation report JSON: {e}")

    console.print(f"[green]✓[/green] Validated data saved")

    if analysis_logger:
        analysis_logger.add_output(str(output_file), "csv", "Validated EPC dataset")
        analysis_logger.add_output("data/processed/validation_report.txt", "report", "Data validation report")
        analysis_logger.add_output("data/processed/validation_report.json", "report", "Data validation report (JSON)")
        analysis_logger.complete_phase(success=True, message=f"{len(df_validated):,} records validated")

    return df_validated, report


def apply_methodological_adjustments(
    df,
    analysis_logger: AnalysisLogger = None,
    sample_start_date: date_cls = None,
    sample_end_date: date_cls = None,
):
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
    output_file = DATA_PROCESSED_DIR / "epc_london_adjusted.csv"
    df_adjusted.to_csv(output_file, index=False)
    if sample_start_date and sample_end_date:
        write_sample_window_metadata(
            output_file,
            sample_start_date,
            sample_end_date,
            "adjusted_epc_dataset",
        )
    parquet_file = None
    try:
        parquet_file = output_file.with_suffix(".parquet")
        # Convert object/categorical columns to strings for parquet compatibility
        cat_cols = df_adjusted.select_dtypes(include=['category']).columns.tolist()
        obj_cols = df_adjusted.select_dtypes(include=['object']).columns.tolist()
        cols_to_convert = cat_cols + obj_cols

        if cols_to_convert:
            original_dtypes = {col: df_adjusted[col].dtype for col in cols_to_convert}
            for col in cols_to_convert:
                df_adjusted[col] = df_adjusted[col].astype(str)

        df_adjusted.to_parquet(parquet_file, index=False)

        # Restore original dtypes
        if cols_to_convert:
            for col, dtype in original_dtypes.items():
                if col in df_adjusted.columns:
                    df_adjusted[col] = df_adjusted[col].astype(dtype)
    except Exception as e:
        parquet_file = None
        logger.debug(f"Could not save adjusted parquet: {e}")

    try:
        summary_path = DATA_PROCESSED_DIR / "methodological_adjustments_summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
    except Exception as e:
        logger.debug(f"Could not save adjustment summary JSON: {e}")

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
        analysis_logger.add_output(str(output_file), "csv", "Adjusted EPC dataset")
        analysis_logger.add_output("data/processed/methodological_adjustments_summary.json", "report", "Methodological adjustments summary (JSON)")
        if parquet_file and parquet_file.exists():
            analysis_logger.add_output(str(parquet_file), "parquet", "Adjusted EPC dataset (Parquet)")
        analysis_logger.complete_phase(success=True, message=f"{len(adjustments_applied)} methodological adjustments applied")

    return df_adjusted, summary


def ensure_hp_hn_comparison_outputs(df=None, analysis_logger: AnalysisLogger = None):
    """Ensure the HP-vs-HN comparison artefacts exist, rebuilding them if required."""
    outputs_dir = Path(DATA_OUTPUTS_DIR)
    comparisons_dir = outputs_dir / "comparisons"
    comparison_csv = comparisons_dir / "hn_vs_hp_comparison.csv"
    comparison_snippet = comparisons_dir / "hn_vs_hp_report_snippet.md"

    if comparison_csv.exists():
        console.print("[cyan]Reusing existing HP vs HN comparison artefacts...[/cyan]")
        return {
            "comparison_csv": comparison_csv,
            "comparison_snippet": comparison_snippet if comparison_snippet.exists() else None,
            "rebuilt": False,
        }

    console.print(
        f"[yellow]⚠ Missing {comparison_csv}; attempting to rebuild HP vs HN comparison outputs...[/yellow]"
    )

    try:
        pathway_modeler = PathwayModeler()
        property_results_path = pathway_modeler.output_dir / "pathway_results_by_property.parquet"
        summary_path = pathway_modeler.output_dir / "pathway_results_summary.csv"

        if property_results_path.exists() and summary_path.exists():
            console.print("[cyan]Using existing pathway modeling outputs to rebuild comparison...[/cyan]")
        else:
            if df is None or len(df) == 0:
                raise ValueError("No source dataframe available to rebuild HP vs HN comparison outputs")

            console.print("[cyan]Running pathway modeling to regenerate comparison inputs...[/cyan]")
            pathway_results = pathway_modeler.model_all_pathways(df)
            pathway_summary = pathway_modeler.generate_pathway_summary(pathway_results)
            property_results_path, summary_path = pathway_modeler.export_results(
                pathway_results,
                pathway_summary,
            )

        comparison_reporter = ComparisonReporter()
        comparison_df = comparison_reporter.generate_comparisons(results_path=property_results_path)

        if comparison_df is None or comparison_df.empty or not comparison_csv.exists():
            raise RuntimeError("Comparison rebuild did not produce a usable hn_vs_hp_comparison.csv")

        console.print(f"[green]✓[/green] Rebuilt HP vs HN comparison artefacts at {comparison_csv}")

        if analysis_logger:
            analysis_logger.add_output(str(property_results_path), "parquet", "Pathway results by property")
            analysis_logger.add_output(str(summary_path), "csv", "Pathway results summary")
            analysis_logger.add_output(str(comparison_csv), "csv", "HP vs HN comparison table")
            if comparison_snippet.exists():
                analysis_logger.add_output(str(comparison_snippet), "md", "HP vs HN markdown snippet")

        return {
            "comparison_csv": comparison_csv,
            "comparison_snippet": comparison_snippet if comparison_snippet.exists() else None,
            "rebuilt": True,
        }
    except Exception as e:
        console.print(f"[yellow]⚠ Could not rebuild HP vs HN comparison outputs: {e}[/yellow]")
        logger.exception("HP vs HN comparison rebuild failed")
        return None


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
    subsidy_results_by_scenario = modeler.model_subsidy_sensitivity_multi(
        df,
        scenario_names=["heat_pump", "hybrid", "heat_network"],
    )
    # Keep legacy single-scenario dict for downstream plotting/report functions.
    subsidy_results = subsidy_results_by_scenario.get("heat_pump", {})

    save_paths = modeler.save_results()
    console.print(f"[green]✓[/green] Results saved")
    if save_paths.get('property_path'):
        console.print(f"    • Property-level results: {save_paths['property_path']}")
    if save_paths.get('summary_path'):
        console.print(f"    • Scenario summary: {save_paths['summary_path']}")

    # Generate the fabric tipping point figure (PNG + editable SVG).
    try:
        from src.reporting.visualizations import ReportGenerator

        viz = ReportGenerator()
        viz.plot_fabric_tipping_point_analysis()
        console.print("[green]✓[/green] Tipping point chart saved to data/outputs/figures/")

        if analysis_logger:
            tipping_png = DATA_OUTPUTS_DIR / "figures" / "tipping_point.png"
            tipping_svg = DATA_OUTPUTS_DIR / "figures" / "tipping_point.svg"
            if tipping_png.exists():
                analysis_logger.add_output(
                    "data/outputs/figures/tipping_point.png",
                    "png",
                    "Fabric tipping point analysis (chart)",
                )
            if tipping_svg.exists():
                analysis_logger.add_output(
                    "data/outputs/figures/tipping_point.svg",
                    "svg",
                    "Fabric tipping point analysis (vector)",
                )
    except Exception as e:
        console.print(f"[yellow]⚠ Could not generate tipping point chart: {e}[/yellow]")
        logger.exception("Tipping point chart generation failed")

    # Generate pathway-level outputs and HP vs HN comparisons for both report modes.
    console.print()
    console.print("[cyan]Building pathway modeling outputs and HP vs HN comparisons...[/cyan]")
    ensure_hp_hn_comparison_outputs(df, analysis_logger)

    if analysis_logger:
        analysis_logger.add_metric("scenarios_modeled", len(scenario_results), "Decarbonization scenarios analyzed")
        analysis_logger.add_output("data/outputs/scenario_modeling_results.txt", "report", "Scenario modeling results")
        if save_paths.get('property_path'):
            analysis_logger.add_output(str(save_paths['property_path']), "parquet", "Scenario results by property")
        if save_paths.get('summary_path'):
            analysis_logger.add_output(str(save_paths['summary_path']), "csv", "Scenario results summary")
        analysis_logger.complete_phase(success=True, message=f"{len(scenario_results)} scenarios modeled successfully")

    return scenario_results, subsidy_results


def analyze_retrofit_readiness(df, analysis_logger: AnalysisLogger = None, one_stop_only: bool = False):
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

        viz = None
        try:
            from src.reporting.visualizations import ReportGenerator

            viz = ReportGenerator()
        except Exception as e:
            console.print(f"[yellow]⚠ Could not initialise visualizations: {e}[/yellow]")
            logger.exception("Visualization initialization failed")

        if viz is not None:
            # Always generate the EPC lodgements-by-year figure (used in the report).
            try:
                console.print("[cyan]Creating EPC lodgement visualizations...[/cyan]")
                viz.plot_epc_lodgements_by_year_band(df)
                console.print("[green]✓[/green] EPC lodgement charts saved to data/outputs/figures/")

                if analysis_logger:
                    counts_png = DATA_OUTPUTS_DIR / "figures" / "epc_lodgement_year_band_stacked_counts.png"
                    share_png = DATA_OUTPUTS_DIR / "figures" / "epc_lodgement_year_band_stacked_share.png"
                    if counts_png.exists():
                        analysis_logger.add_output(
                            "data/outputs/figures/epc_lodgement_year_band_stacked_counts.png",
                            "png",
                            "EPC lodgements by year (counts; bands stacked)",
                        )
                    if share_png.exists():
                        analysis_logger.add_output(
                            "data/outputs/figures/epc_lodgement_year_band_stacked_share.png",
                            "png",
                            "EPC lodgements by year (share; bands stacked)",
                        )
            except Exception as e:
                console.print(f"[yellow]⚠ Could not generate EPC lodgement charts: {e}[/yellow]")
                logger.exception("EPC lodgement chart generation failed")

        if not one_stop_only and viz is not None:
            # Generate retrofit readiness visualizations (heavier charts).
            console.print("[cyan]Creating retrofit readiness visualizations...[/cyan]")
            try:
                viz.plot_retrofit_readiness_dashboard(df_readiness, summary)
                viz.plot_fabric_cost_distribution(df_readiness)
                viz.plot_heat_demand_scatter(df_readiness)
                console.print("[green]✓[/green] Visualizations saved to data/outputs/figures/")
            except Exception as e:
                console.print(f"[yellow]⚠ Could not generate retrofit readiness charts: {e}[/yellow]")
                logger.exception("Retrofit readiness chart generation failed")

        if analysis_logger:
            analysis_logger.add_output("data/outputs/retrofit_readiness_analysis.csv", "csv", "Property-level retrofit readiness")
            analysis_logger.add_output("data/outputs/reports/retrofit_readiness_summary.txt", "report", "Retrofit readiness summary")
            if not one_stop_only:
                analysis_logger.add_output("data/outputs/figures/retrofit_readiness_dashboard.png", "png", "Retrofit readiness visualization")
            analysis_logger.complete_phase(success=True, message="Retrofit readiness assessment complete")

        return df_readiness, summary

    except Exception as e:
        console.print(f"[yellow]⚠ Retrofit readiness analysis failed: {e}[/yellow]")
        logger.error(f"Retrofit readiness error: {e}")
        if analysis_logger:
            analysis_logger.complete_phase(success=False, message=f"Error: {e}")
        return None, None


def run_spatial_analysis(df, analysis_logger: AnalysisLogger = None, one_stop_only: bool = False):
    """Run spatial heat network tier analysis (optional - requires GDAL)."""
    console.print()
    console.print(Panel("[bold]Phase 4.5: Spatial Analysis (Optional)[/bold]", border_style="blue"))
    console.print()

    console.print("[cyan]Heat Network Tier Classification[/cyan]")
    console.print()
    console.print("This phase requires GDAL/geopandas for spatial analysis.")
    console.print("If not installed, this phase will be skipped.")
    console.print()

    def get_spatial_dependency_status():
        """Return missing modules plus available vector IO backends."""
        missing = []
        for module_name in ("geopandas", "shapely", "pyproj"):
            try:
                __import__(module_name)
            except ImportError:
                missing.append(module_name)

        available_backends = []
        for backend_name in ("pyogrio", "fiona"):
            try:
                __import__(backend_name)
                available_backends.append(backend_name)
            except ImportError:
                continue

        if not available_backends:
            missing.append("pyogrio-or-fiona")

        return missing, available_backends

    def get_spatial_install_command() -> tuple[str, str]:
        """Return the preferred install mode and command for this environment."""
        is_windows = platform.system() == "Windows"
        conda_env = os.getenv("CONDA_DEFAULT_ENV")

        if is_windows and conda_env and conda_env.lower() != "base":
            command = (
                f"conda install -n {conda_env} -c conda-forge "
                "geopandas pyogrio pyproj shapely rtree"
            )
            return "conda", command

        if is_windows:
            return "conda", "conda install -c conda-forge geopandas pyogrio pyproj shapely rtree"

        return "pip", "pip install -r requirements-spatial.txt"

    def check_spatial_dependencies():
        """Check for required spatial libraries before running analysis."""
        missing_modules, available_backends = get_spatial_dependency_status()
        if not missing_modules:
            return True

        install_mode, install_command = get_spatial_install_command()

        console.print()
        console.print("[yellow]⚠ Spatial libraries missing[/yellow]")
        console.print(f"Missing modules/backend: {', '.join(missing_modules)}")
        if available_backends:
            console.print(f"Detected spatial IO backend(s): {', '.join(available_backends)}")
        console.print("Map outputs require the spatial stack to be available.")
        console.print(f"Recommended fix for this environment: [bold]{install_command}[/bold]")
        console.print()

        choice = questionary.select(
            "How would you like to proceed?",
            choices=[
                questionary.Choice(f"Attempt to install spatial dependencies now ({install_mode})", value="install"),
                questionary.Choice("Pause/abort to install manually", value="abort"),
                questionary.Choice("Continue without spatial results", value="skip"),
            ],
        ).ask()

        if choice == "install":
            console.print()
            console.print("[cyan]Attempting to install spatial dependencies...[/cyan]")
            if install_mode == "conda":
                conda_env = os.getenv("CONDA_DEFAULT_ENV")
                install_args = ["conda", "install", "-c", "conda-forge"]
                if conda_env and conda_env.lower() != "base":
                    install_args.extend(["-n", conda_env])
                install_args.extend(["geopandas", "pyogrio", "pyproj", "shapely", "rtree", "-y"])
                result = subprocess.run(install_args, capture_output=True, text=True)
            else:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-r", "requirements-spatial.txt"],
                    capture_output=True,
                    text=True,
                )

            if result.returncode == 0:
                console.print("[green]✓[/green] Spatial dependencies installed. Re-checking...")
                return check_spatial_dependencies()

            console.print("[yellow]⚠ Could not install spatial dependencies automatically.[/yellow]")
            console.print(f"Install manually with: {install_command}")

        if choice == "abort":
            console.print("[yellow]Analysis paused. Install the spatial dependencies and re-run the spatial phase.[/yellow]")
            if analysis_logger:
                analysis_logger.skip_phase(
                    "Spatial Analysis", "User paused to install GIS dependencies before continuing",
                )
            raise SystemExit(0)

        console.print("[yellow]Continuing without spatial analysis. Map outputs will be absent.[/yellow]")
        if analysis_logger:
            analysis_logger.skip_phase(
                "Spatial Analysis", "Spatial dependencies missing; map outputs will not be generated",
            )
        return False

        if False:
            console.print("[yellow]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/yellow]")
            console.print("[yellow]⚠ Spatial libraries missing[/yellow]")
            console.print("[yellow]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/yellow]")
            console.print()
            console.print("Map outputs require installing [bold]requirements-spatial.txt[/bold] or using the Conda launcher.")
            console.print("Without these libraries, the spatial phase will be skipped and maps will be absent.")
            console.print()

            choice = questionary.select(
                "How would you like to proceed?",
                choices=[
                    questionary.Choice("Attempt to install requirements-spatial.txt now (pip)", value="install"),
                    questionary.Choice("Pause/abort to install manually (e.g., via Conda launcher)", value="abort"),
                    questionary.Choice("Continue without spatial results", value="skip"),
                ],
            ).ask()

            if choice == "install":
                console.print()
                console.print("[cyan]Attempting to install spatial dependencies...[/cyan]")
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-r", "requirements-spatial.txt"],
                    capture_output=True,
                    text=True,
                )

                if result.returncode == 0:
                    console.print("[green]✓[/green] Spatial dependencies installed. Re-checking...")
                    return check_spatial_dependencies()

                console.print("[yellow]⚠ Could not install spatial dependencies automatically.[/yellow]")
                console.print("Install manually with: pip install -r requirements-spatial.txt or use the Conda launcher.")

            if choice == "abort":
                console.print("[yellow]Analysis paused. Install the spatial dependencies and re-run the spatial phase.[/yellow]")
                if analysis_logger:
                    analysis_logger.skip_phase(
                        "Spatial Analysis", "User paused to install GIS dependencies before continuing",
                    )
                raise SystemExit(0)

            console.print("[yellow]Continuing without spatial analysis. Map outputs will be absent.[/yellow]")
            if analysis_logger:
                analysis_logger.skip_phase(
                    "Spatial Analysis", "Spatial dependencies missing; map outputs will not be generated",
                )
            return False

        return True

    if not check_spatial_dependencies():
        return None, None

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
            df, auto_download_gis=True, create_maps=not one_stop_only
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
            if not one_stop_only:
                console.print(f"    • Interactive Map: data/outputs/maps/heat_network_tiers.html")

            if analysis_logger:
                analysis_logger.add_metric("properties_geocoded", len(properties_classified), "Properties with spatial classification")
                analysis_logger.add_output("data/processed/epc_with_heat_network_tiers.geojson", "geojson", "Geocoded properties with heat network tiers")
                analysis_logger.add_output("data/outputs/pathway_suitability_by_tier.csv", "csv", "Pathway suitability by tier")
                if not one_stop_only:
                    map_html = Path("data/outputs/maps/heat_network_tiers.html")
                    map_png = map_html.with_suffix('.png')
                    map_pdf = map_html.with_suffix('.pdf')

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
        console.print("    conda install -c conda-forge geopandas pyogrio pyproj shapely rtree")
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

    if is_one_stop_only():
        console.print("[cyan]One-stop reporting enabled; skipping additional report outputs.[/cyan]")
        if analysis_logger:
            analysis_logger.skip_phase("Report Generation", "One-stop report output enabled")
        return []

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


def generate_one_stop_report(df=None, analysis_logger: AnalysisLogger = None):
    """Generate the one-stop JSON report."""
    console.print()
    console.print(Panel("[bold]Phase 5: One-Stop Report[/bold]", border_style="blue"))
    console.print()
    console.print("[cyan]Generating one-stop JSON report...[/cyan]")

    ensure_hp_hn_comparison_outputs(df, analysis_logger)

    from src.reporting.one_stop_report import OneStopReportGenerator

    generator = OneStopReportGenerator()
    output_path = generator.generate()

    console.print(f"[green]✓[/green] One-stop report generated: {output_path}")

    if analysis_logger:
        analysis_logger.add_output("data/outputs/one_stop_output.json", "json", "One-stop report")

    return output_path


def cleanup_reporting_outputs():
    """
    Archive non-core report artifacts for one-stop mode.

    Historically, one-stop mode aggressively deleted intermediate reporting outputs to
    leave only the consolidated one-stop JSON. That makes QA/auditing harder, because
    the one-stop output still references source CSV/JSON files that no longer exist.

    Instead of deleting, move everything except the core outputs into:
      data/outputs/bin/<run_timestamp>/

    Returns:
        Path to the archive directory, or None if nothing was moved.
    """
    from datetime import datetime

    outputs_dir = Path(DATA_OUTPUTS_DIR)

    preserved_files = {
        "one_stop_output.json",
        "one_stop_dashboard.html",
        "analysis_log.txt",
        "analysis_log.json",
        "run_metadata.json",
        "analysis_outputs_compendium.xlsx",
    }

    # Prefer using analysis_log.json metadata for a stable run identifier.
    run_id = None
    try:
        analysis_log_path = outputs_dir / "analysis_log.json"
        if analysis_log_path.exists():
            run_id = (json.loads(analysis_log_path.read_text(encoding="utf-8")) or {}).get("metadata", {}).get("analysis_start")
    except Exception:
        run_id = None

    run_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if run_id:
        try:
            run_stamp = datetime.fromisoformat(str(run_id)).strftime("%Y%m%d-%H%M%S")
        except Exception:
            pass

    archive_root = outputs_dir / "bin"
    archive_root.mkdir(parents=True, exist_ok=True)

    archive_dir = archive_root / f"run_{run_stamp}"
    if archive_dir.exists():
        archive_dir = archive_root / f"run_{run_stamp}_{datetime.now().strftime('%f')}"
    archive_dir.mkdir(parents=True, exist_ok=True)

    moved = []
    if outputs_dir.exists():
        for path in outputs_dir.iterdir():
            if path.name in preserved_files or path.name == "bin":
                continue
            if path.name == "figures" and path.is_dir():
                # Keep figures in place for easy access, but also copy to the archive for auditability.
                try:
                    dest = archive_dir / path.name
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(path, dest)
                    moved.append({"from": str(path), "to": str(dest), "mode": "copy"})
                except Exception as exc:
                    logger.warning(f"Could not copy figures directory {path} to archive: {exc}")
                continue
            try:
                dest = archive_dir / path.name
                shutil.move(str(path), str(dest))
                moved.append({"from": str(path), "to": str(dest)})
            except Exception as exc:
                logger.warning(f"Could not archive output {path}: {exc}")

    if not moved:
        return None

    try:
        manifest = {
            "archived_at": datetime.now().isoformat(),
            "run_id": run_id,
            "archive_dir": str(archive_dir),
            "moved": moved,
        }
        (archive_dir / "archive_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning(f"Could not write archive manifest: {exc}")

    return archive_dir


def generate_additional_reports(df_raw, df_validated, validation_report, archetype_results, scenario_results, analysis_logger: AnalysisLogger = None):
    """Generate additional specialized reports for client presentation."""
    console.print()
    console.print(Panel("[bold]Phase 5.5: Additional Reports[/bold]", border_style="blue"))
    console.print()

    if analysis_logger:
        analysis_logger.start_phase(
            "Additional Reports",
            "Generate specialized reports (case streets, borough breakdown, borough priority, tenure segmentation, data quality, subsidy analysis)"
        )

    from src.analysis.additional_reports import AdditionalReports
    from pathlib import Path

    reporter = AdditionalReports()
    reports_created = []

    output_dir = Path("data/outputs")
    output_dir.mkdir(parents=True, exist_ok=True)
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

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

    # 2.5 Borough Priority Ranking
    try:
        console.print("[cyan]Generating borough priority ranking...[/cyan]")
        borough_priority_path = reports_dir / "borough_priority_ranking.csv"
        borough_priority_summary_path = reports_dir / "borough_priority_ranking.txt"
        borough_priority_df = reporter.generate_borough_priority_ranking(
            df_validated,
            output_path=borough_priority_path,
            summary_path=borough_priority_summary_path,
            source_label="data/processed/epc_london_adjusted.csv",
        )
        reports_created.append(f"✓ Borough priority ranking ({len(borough_priority_df)} boroughs)")
    except Exception as e:
        console.print(f"[yellow]⚠ Could not generate borough priority ranking: {e}[/yellow]")
        borough_priority_df = None

    # 2.6 Tenure Segmentation
    try:
        console.print("[cyan]Generating tenure segmentation analysis...[/cyan]")
        tenure_segmentation_path = reports_dir / "tenure_segmentation.csv"
        tenure_segmentation_summary_path = reports_dir / "tenure_segmentation.txt"
        tenure_segmentation_df = reporter.generate_tenure_segmentation(
            df_validated,
            output_path=tenure_segmentation_path,
            summary_path=tenure_segmentation_summary_path,
            source_label="data/processed/epc_london_adjusted.csv",
        )
        reports_created.append(f"✓ Tenure segmentation ({len(tenure_segmentation_df)} tenure groups)")
    except Exception as e:
        console.print(f"[yellow]⚠ Could not generate tenure segmentation analysis: {e}[/yellow]")
        tenure_segmentation_df = None

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
        subsidy_path = output_dir / "subsidy_sensitivity_analysis_simple_gbp.csv"
        reporter.subsidy_sensitivity_analysis(
            df_validated,
            scenario_results,
            subsidy_levels=[0, 5000, 7500, 10000, 15000],
            output_path=subsidy_path
        )
        reports_created.append("✓ Subsidy sensitivity analysis")
    except Exception as e:
        console.print(f"[yellow]⚠ Could not generate subsidy sensitivity: {e}[/yellow]")

    # 5. Heat Network Connection Thresholds
    threshold_df = None
    try:
        console.print("[cyan]Analyzing heat network connection thresholds...[/cyan]")
        threshold_path = output_dir / "heat_network_connection_thresholds.csv"
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
        threshold_df = None

    console.print()
    console.print(f"[green]✓[/green] Additional reports complete!")
    console.print()

    if reports_created:
        console.print("[cyan]Generated reports:[/cyan]")
        for report in reports_created:
            console.print(f"    {report}")

    if analysis_logger:
        analysis_logger.add_metric("additional_reports", len(reports_created), f"{len(reports_created)} specialized reports")
        analysis_logger.add_output("data/outputs/shakespeare_crescent_extract.csv", "csv", "Case street extract")
        analysis_logger.add_output("data/outputs/borough_breakdown.csv", "csv", "Borough-level breakdown")
        analysis_logger.add_output("data/outputs/reports/borough_priority_ranking.csv", "csv", "Borough-level priority ranking")
        analysis_logger.add_output("data/outputs/reports/borough_priority_ranking.txt", "report", "Borough priority ranking summary")
        analysis_logger.add_output("data/outputs/reports/tenure_segmentation.csv", "csv", "Tenure segmentation analysis")
        analysis_logger.add_output("data/outputs/reports/tenure_segmentation.txt", "report", "Tenure segmentation summary")
        analysis_logger.add_output("data/outputs/heat_network_connection_thresholds.csv", "csv", "Heat network connection threshold analysis")
        analysis_logger.add_output("data/outputs/subsidy_sensitivity_analysis_simple_gbp.csv", "csv", "Subsidy sensitivity analysis (simple, GBP levels)")
        analysis_logger.add_output("data/outputs/data_quality_report.txt", "report", "Data quality assessment")
        analysis_logger.complete_phase(success=True, message=f"{len(reports_created)} additional specialized reports generated")

    return {
        "case_street_df": case_street_df,
        "case_street_summary": case_street_summary,
        "borough_breakdown": borough_df,
        "borough_priority_ranking": borough_priority_df,
        "tenure_segmentation": tenure_segmentation_df,
        "heat_network_thresholds": threshold_df,
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

    ensure_hp_hn_comparison_outputs(df_validated, analysis_logger)

    try:
        from src.reporting.dashboard_data_builder import DashboardDataBuilder
        import pandas as pd

        builder = DashboardDataBuilder()
        case_summary = (additional_reports or {}).get("case_street_summary") if additional_reports else None
        case_street_df = (additional_reports or {}).get("case_street_df") if additional_reports else None
        borough_breakdown = (additional_reports or {}).get("borough_breakdown") if additional_reports else None
        borough_priority_ranking = (additional_reports or {}).get("borough_priority_ranking") if additional_reports else None
        tenure_segmentation = (additional_reports or {}).get("tenure_segmentation") if additional_reports else None
        heat_network_thresholds = (additional_reports or {}).get("heat_network_thresholds") if additional_reports else None

        # Load additional data files if they exist
        load_profile_summary = None
        tipping_point_curve = None
        retrofit_packages_summary = None
        hn_vs_hp_comparison = None

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

        comparison_file = outputs_dir / "comparisons" / "hn_vs_hp_comparison.csv"
        if comparison_file.exists():
            try:
                hn_vs_hp_comparison = pd.read_csv(comparison_file)
                console.print(f"[green]✓[/green] Loaded HP vs HN comparison")
            except Exception as e:
                logger.debug(f"Could not load HP vs HN comparison: {e}")

        threshold_file = outputs_dir / "heat_network_connection_thresholds.csv"
        if heat_network_thresholds is None and threshold_file.exists():
            try:
                heat_network_thresholds = pd.read_csv(threshold_file)
                console.print(f"[green]✓[/green] Loaded heat network connection thresholds")
            except Exception as e:
                logger.debug(f"Could not load heat network thresholds: {e}")

        dataset = builder.build_dataset(
            archetype_results,
            scenario_results,
            readiness_summary,
            pathway_summary,
            borough_breakdown,
            borough_priority_ranking,
            tenure_segmentation,
            case_summary,
            case_street_df,
            heat_network_thresholds,
            hn_vs_hp_comparison,
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


def _describe_existing_file(file_path: Path, title: str, include_records: bool = True):
    """Display a panel describing an existing data file."""
    if not file_path.exists():
        return

    try:
        file_size = os.path.getsize(file_path) / (1024 * 1024)  # MB
        mod_time = os.path.getmtime(file_path)
        from datetime import datetime
        mod_date = datetime.fromtimestamp(mod_time).strftime('%Y-%m-%d %H:%M')

        record_line = ""
        if include_records:
            try:
                record_count = max(sum(1 for _ in open(file_path, encoding="utf-8")) - 1, 0)
                record_line = f"Records: ~{record_count:,}\n"
            except Exception as e:
                logger.debug(f"Could not count records in {file_path}: {e}")
        console.print()
        console.print(Panel(
            f"[bold cyan]{title}[/bold cyan]\n\n"
            f"File: {file_path.name}\n"
            f"Size: {file_size:.1f} MB\n"
            f"{record_line}"
            f"Last modified: {mod_date}",
            border_style="green"
        ))
        console.print()
    except Exception as e:
        logger.debug(f"Could not describe file {file_path}: {e}")


def prompt_use_existing_dataframe(
    phase_name: str,
    description: str,
    file_path: Path,
    analysis_logger: AnalysisLogger = None,
    include_records: bool = True,
    sample_start_date: date_cls = None,
    sample_end_date: date_cls = None,
):
    """
    Ask the user whether to reuse an existing processed dataset.

    Returns a DataFrame if loaded, otherwise None.
    """
    if not file_path.exists():
        return None

    if sample_start_date and sample_end_date and not sample_window_matches(file_path, sample_start_date, sample_end_date):
        console.print(
            f"[yellow]⚠ Existing {description} does not match requested sample window "
            f"{sample_start_date.isoformat()} to {sample_end_date.isoformat()} - regenerating[/yellow]"
        )
        return None

    _describe_existing_file(file_path, f"Existing {description}", include_records)

    use_existing = True  # Automatically use existing processed datasets

    if not use_existing:
        return None

    if analysis_logger:
        analysis_logger.start_phase(
            phase_name,
            f"Load existing {description} from disk"
        )

    try:
        import pandas as pd

        df_existing = pd.read_csv(file_path)
        console.print(f"[green]✓[/green] Loaded existing {description} ({len(df_existing):,} records)")

        if analysis_logger:
            analysis_logger.add_metric("records_loaded", len(df_existing), f"{description} records loaded from disk")
            analysis_logger.add_output(str(file_path), "csv", f"Existing {description}")
            analysis_logger.complete_phase(success=True, message=f"Loaded existing {description}")

        return df_existing
    except Exception as e:
        console.print(f"[yellow]⚠ Could not load existing {description}: {e}[/yellow]")
        logger.exception(f"Failed to load existing {description}")
        if analysis_logger and analysis_logger.current_phase:
            analysis_logger.complete_phase(success=False, message=f"Failed to load existing {description}: {e}")
        return None


def load_json_if_exists(file_path: Path):
    """Load a JSON file if it exists, otherwise return None."""
    if not file_path.exists():
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.debug(f"Could not load JSON from {file_path}: {e}")
        return None


def check_existing_data(sample_start_date: date_cls = None, sample_end_date: date_cls = None):
    """Check if previously downloaded data exists."""
    raw_csv = DATA_RAW_DIR / "epc_london_raw.csv"
    filtered_csv = DATA_RAW_DIR / "epc_london_filtered.csv"

    def _matches(file_path: Path) -> bool:
        if sample_start_date and sample_end_date:
            return sample_window_matches(file_path, sample_start_date, sample_end_date)
        return True

    if raw_csv.exists() or filtered_csv.exists():
        # Get file info
        if filtered_csv.exists() and _matches(filtered_csv):
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

        elif raw_csv.exists() and _matches(raw_csv):
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

        elif filtered_csv.exists() or raw_csv.exists():
            console.print()
            console.print(Panel(
                f"[bold yellow]Existing Data Ignored[/bold yellow]\n\n"
                f"Stored data does not match the requested sample window:\n"
                f"{sample_start_date.isoformat()} to {sample_end_date.isoformat()}",
                border_style="yellow"
            ))
            console.print()

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

    config = load_config()
    one_stop_only = is_one_stop_only(config)

    # Initialize analysis logger
    analysis_logger = AnalysisLogger()
    console.print("[green]✓[/green] Analysis logger initialized")
    console.print()

    # Ask about heat network data downloads
    # HNPD first (recommended, 2024 data)
    ask_hnpd_download()

    # London GIS data second (for heat density in Tiers 3-5)
    ask_gis_download()

    try:
        sample_start_date, sample_end_date = prompt_sample_window()
    except KeyboardInterrupt:
        console.print("[yellow]Analysis cancelled by user[/yellow]")
        return

    analysis_logger.set_metadata("sample_start_date", sample_start_date.isoformat())
    analysis_logger.set_metadata("sample_end_date", sample_end_date.isoformat())

    # Check for existing data
    has_existing, existing_file, record_count = check_existing_data(
        sample_start_date=sample_start_date,
        sample_end_date=sample_end_date,
    )

    df = None
    fresh_data_downloaded = False  # Track if we just downloaded new data

    if has_existing:
        # Ask user whether to use existing data or download new
        use_existing = questionary.select(
            "Existing data found. What would you like to do?",
            choices=[
                questionary.Choice("Use existing data", value=True),
                questionary.Choice("Download new data (will overwrite existing)", value=False),
            ],
        ).ask()

        if use_existing is None:
            console.print("[yellow]Analysis cancelled by user[/yellow]")
            return

        if use_existing:
            df = load_existing_data(existing_file, analysis_logger)
        else:
            console.print()
            console.print("[yellow]Downloading new data (existing data will be overwritten)...[/yellow]")
            console.print()
            fresh_data_downloaded = True  # Flag that we're downloading fresh data

    # If not using existing data, download new
    if df is None or df.empty:
        fresh_data_downloaded = True  # Flag that we're downloading fresh data

        # Show summary
        console.print()
        console.print(Panel(
            f"[bold]Analysis Configuration[/bold]\n\n"
            f"Mode: full\n"
            f"Sample start date: {sample_start_date.isoformat()}\n"
            f"Sample end date: {sample_end_date.isoformat()}",
            border_style="cyan"
        ))
        console.print()

        proceed = True  # Automatically proceed with download

        if not proceed:
            console.print("[yellow]Analysis cancelled[/yellow]")
            return

        # Run pipeline
        start_time = time.time()

        # Phase 1: Download
        df = download_data(
            analysis_logger,
            sample_start_date=sample_start_date,
            sample_end_date=sample_end_date,
        )
        if df is None or df.empty:
            console.print("[red]✗ Analysis stopped - no data available[/red]")
            return
        gc.collect()  # Cleanup API response objects
    else:
        start_time = time.time()
        console.print()
        console.print("[cyan]Proceeding with existing data...[/cyan]")
        console.print()

    df_raw = df.copy()

    # Phase 2: Check for existing validated data before running validation
    # If we just downloaded fresh data, force re-validation instead of using old validated data
    validated_path = DATA_PROCESSED_DIR / "epc_london_validated.csv"
    df_validated = None
    if not fresh_data_downloaded:
        df_validated = prompt_use_existing_dataframe(
            "Data Validation",
            "validated EPC dataset",
            validated_path,
            analysis_logger,
            sample_start_date=sample_start_date,
            sample_end_date=sample_end_date,
        )
    validation_report = None

    if df_validated is not None:
        validation_report = load_json_if_exists(DATA_PROCESSED_DIR / "validation_report.json")
        if validation_report:
            console.print("[cyan]Loaded validation report from previous run[/cyan]")
        else:
            console.print("[yellow]⚠ Validation report JSON not found; generating from validated data...[/yellow]")
            # Generate a minimal validation report from the validated data and raw data
            validation_report = {
                "total_records": len(df),
                "duplicates_removed": 0,  # Unknown from pre-validated data
                "invalid_records": len(df) - len(df_validated),
                "valid_records": len(df_validated),
                "negative_energy_values": 0,  # Unknown
                "negative_co2_values": 0,  # Unknown
                "note": "Generated retroactively from validated dataset"
            }
            # Save it for future use
            try:
                validation_report_path = DATA_PROCESSED_DIR / "validation_report.json"
                with open(validation_report_path, "w", encoding="utf-8") as f:
                    json.dump(validation_report, f, indent=2)
                console.print(f"[green]✓ Created validation_report.json with {len(df_validated):,} valid records[/green]")
            except Exception as e:
                logger.warning(f"Could not save validation report: {e}")
    else:
        # Phase 2: Validate
        df_validated, validation_report = validate_data(
            df,
            analysis_logger,
            sample_start_date=sample_start_date,
            sample_end_date=sample_end_date,
        )
        # Cleanup raw dataframe since we now use df_validated
        del df
        gc.collect()

    # Set metadata
    analysis_logger.set_metadata("total_properties", len(df_validated))

    if df_validated.empty:
        console.print("[red]✗ Analysis stopped - no valid data[/red]")
        return

    # Phase 2.5: Methodological Adjustments (check for existing adjusted data)
    # If we just downloaded fresh data, force re-adjustment instead of using old adjusted data
    adjusted_path = DATA_PROCESSED_DIR / "epc_london_adjusted.csv"
    df_adjusted = None
    if not fresh_data_downloaded:
        df_adjusted = prompt_use_existing_dataframe(
            "Methodological Adjustments",
            "methodologically adjusted dataset",
            adjusted_path,
            analysis_logger,
            sample_start_date=sample_start_date,
            sample_end_date=sample_end_date,
        )
    adjustment_summary = None
    if df_adjusted is not None:
        adjustment_summary = load_json_if_exists(DATA_PROCESSED_DIR / "methodological_adjustments_summary.json")
        if adjustment_summary:
            console.print("[cyan]Loaded methodological adjustment summary from previous run[/cyan]")
        else:
            console.print("[yellow]⚠ Adjustment summary JSON not found; proceeding without it[/yellow]")
    else:
        df_adjusted, adjustment_summary = apply_methodological_adjustments(
            df_validated,
            analysis_logger,
            sample_start_date=sample_start_date,
            sample_end_date=sample_end_date,
        )
        # Cleanup pre-adjustment dataframe since we now use df_adjusted
        if 'df_validated' in locals() and df_validated is not df_adjusted:
            del df_validated
        gc.collect()

    # Phase 3: Analyze (use adjusted data)
    archetype_results = analyze_archetype(df_adjusted, analysis_logger)
    gc.collect()  # Cleanup analysis intermediate results

    # Phase 4: Model (use adjusted data for realistic baselines)
    scenario_results, subsidy_results = model_scenarios(df_adjusted, analysis_logger)
    gc.collect()  # Major cleanup after expensive modeling phase

    # Phase 4.3: Retrofit Readiness
    df_readiness, readiness_summary = analyze_retrofit_readiness(
        df_adjusted,
        analysis_logger,
        one_stop_only=one_stop_only,
    )
    gc.collect()  # Cleanup readiness calculation intermediates

    # Phase 4.5: Spatial Analysis (optional)
    properties_with_tiers, pathway_summary = run_spatial_analysis(
        df_adjusted,
        analysis_logger,
        one_stop_only=one_stop_only,
    )
    gc.collect()  # Cleanup GIS objects and geocoding cache

    # Phase 5.5: Additional reports and supporting tables
    additional_outputs = generate_additional_reports(
        df_raw,
        df_adjusted,
        validation_report,
        archetype_results,
        scenario_results,
        analysis_logger,
    )

    # Phase 5: Report
    if one_stop_only:
        generate_one_stop_report(df_adjusted, analysis_logger)
        gc.collect()  # Cleanup report generation objects
    else:
        generate_reports(archetype_results, scenario_results, subsidy_results, df_adjusted, pathway_summary, analysis_logger)
        gc.collect()  # Cleanup matplotlib figures and Excel writer objects

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
    gc.collect()  # Final cleanup after dashboard packaging

    # Complete
    elapsed = time.time() - start_time

    # Save analysis log
    console.print()
    console.print("[cyan]Saving analysis log...[/cyan]")
    log_path = analysis_logger.save_log()

    # Post-process one-stop output (if present) to ensure run timings and validation totals are auditable.
    try:
        from src.reporting.patch_one_stop_output import patch_one_stop_output

        patched_path = patch_one_stop_output(DATA_OUTPUTS_DIR)
        if patched_path:
            console.print(f"[green]OK[/green] Patched one-stop report metadata: {patched_path}")
    except Exception as e:
        logger.warning(f"Could not patch one-stop output from analysis_log.json: {e}")

    # Generate a lightweight, self-contained HTML dashboard from the one-stop JSON output.
    try:
        from src.reporting.one_stop_html_dashboard import build_one_stop_html_dashboard

        dashboard_path = build_one_stop_html_dashboard(Path(DATA_OUTPUTS_DIR))
        if dashboard_path:
            console.print(f"[green]✓[/green] One-stop HTML dashboard generated: {dashboard_path}")
            if analysis_logger:
                analysis_logger.add_output(
                    "data/outputs/one_stop_dashboard.html",
                    "html",
                    "One-stop HTML dashboard (self-contained)",
                )
    except Exception as e:
        logger.warning(f"Could not generate one-stop HTML dashboard: {e}")

    # Archive intermediate outputs for auditability in one-stop mode (instead of deleting them).
    if one_stop_only:
        try:
            archived_to = cleanup_reporting_outputs()
            if archived_to:
                console.print(f"[cyan]Archived intermediate outputs to:[/cyan] {archived_to}")
        except Exception as e:
            logger.warning(f"Could not archive one-stop outputs: {e}")
    console.print(f"[green]✓[/green] Analysis log saved to: {log_path}")
    combined_workbook = analysis_logger.metadata.get('combined_workbook')
    if combined_workbook:
        console.print(f"[green]✓[/green] Combined outputs workbook saved to: {combined_workbook}")

    # Show summary statistics
    summary_stats = analysis_logger.get_summary_stats()
    console.print()
    console.print(f"[cyan]Analysis Summary:[/cyan]")
    console.print(f"  • Total phases: {summary_stats['total_phases']}")
    console.print(f"  • Successful: {summary_stats['successful_phases']}")
    console.print(f"  • Failed: {summary_stats['failed_phases']}")
    console.print(f"  • Skipped: {summary_stats['skipped_phases']}")

    console.print()
    outputs_label = "one_stop_output.json (one-stop report)" if one_stop_only else "reports and charts"

    console.print(Panel.fit(
        f"[bold green]✓ Analysis Complete![/bold green]\n\n"
        f"Time elapsed: {elapsed/60:.1f} minutes\n"
        f"Properties analyzed: {len(df_adjusted):,}\n\n"
        f"[cyan]Results saved to:[/cyan]\n"
        f"  • data/processed/ (validated data)\n"
        f"  • data/outputs/ ({outputs_label})\n"
        f"  • data/outputs/analysis_log.txt (analysis log)\n"
        f"  • data/outputs/analysis_outputs_compendium.xlsx (combined workbook)",
        border_style="green"
    ))
    console.print()

    # Ask if user wants to open results
    open_results = False  # Skip opening results folder automatically

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
