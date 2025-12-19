"""
EPC Data Acquisition Module

Downloads and extracts EPC data from the official UK EPC Register.
Handles data for configured local authorities with optional property filters.
"""

import os
import requests
import pandas as pd
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timedelta
from tqdm import tqdm
import zipfile
import io
from loguru import logger

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import (
    load_config,
    DATA_RAW_DIR,
    get_local_authorities,
    get_property_filters
)


class EPCDownloader:
    """
    Downloads and extracts EPC data from the UK EPC Register.

    The EPC register provides data at local authority level.
    Data is available from: https://epc.opendatacommunities.org/
    """

    BASE_URL = "https://epc.opendatacommunities.org/api/v1/domestic/search"

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize EPC downloader.

        Args:
            api_key: API key for EPC register (optional, may be required for bulk downloads)
        """
        self.api_key = api_key
        self.config = load_config()
        self.local_authorities = get_local_authorities()
        self.property_filters = get_property_filters()

        # Ensure output directory exists
        DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)

        if self.local_authorities:
            logger.info(f"Initialized EPC Downloader for {len(self.local_authorities)} local authorities")
        else:
            logger.info("Initialized EPC Downloader for England and Wales (all local authorities)")

    def download_bulk_data(self, output_dir: Optional[Path] = None) -> Path:
        """
        Download bulk EPC data files.

        Note: The UK EPC register provides bulk downloads by local authority.
        This is a placeholder that shows the structure - actual implementation
        would use the official bulk download API or files.

        Args:
            output_dir: Directory to save downloaded files

        Returns:
            Path to downloaded data
        """
        if output_dir is None:
            output_dir = DATA_RAW_DIR

        logger.info("Downloading bulk EPC data...")
        logger.warning(
            "IMPORTANT: This requires access to the EPC bulk download service. "
            "You may need to:\n"
            "1. Register at https://epc.opendatacommunities.org/\n"
            "2. Request API credentials\n"
            "3. Download bulk data files for England and Wales local authorities\n"
            "4. Place CSV files in data/raw/ directory"
        )

        # Placeholder for actual download logic
        download_instructions = output_dir / "DOWNLOAD_INSTRUCTIONS.txt"
        with open(download_instructions, 'w') as f:
            f.write("EPC Data Download Instructions\n")
            f.write("=" * 50 + "\n\n")
            f.write("1. Visit: https://epc.opendatacommunities.org/\n")
            f.write("2. Navigate to 'Downloads' or 'API' section\n")
            if self.local_authorities:
                f.write("3. Download data for the following local authorities:\n\n")
                for authority in self.local_authorities:
                    f.write(f"   - {authority}\n")
                f.write("\n4. Save CSV files to: data/raw/\n")
            else:
                f.write("3. Download data for all England and Wales local authorities.\n")
                f.write("4. Save CSV files to: data/raw/\n")
            f.write("5. Name files as: epc_{local_authority_name}.csv\n\n")
            f.write("Alternative: Use the bulk download API if you have credentials\n")

        logger.info(f"Download instructions saved to: {download_instructions}")
        return output_dir

    def load_local_data(self, file_pattern: str = "epc_*.csv") -> pd.DataFrame:
        """
        Load EPC data from local CSV files.

        Args:
            file_pattern: Glob pattern to match EPC data files

        Returns:
            Combined DataFrame of all EPC data
        """
        logger.info(f"Loading EPC data from: {DATA_RAW_DIR}")

        csv_files = list(DATA_RAW_DIR.glob(file_pattern))

        if not csv_files:
            logger.warning(f"No EPC data files found matching pattern: {file_pattern}")
            logger.info("Please download EPC data files first using download_bulk_data()")
            return pd.DataFrame()

        logger.info(f"Found {len(csv_files)} EPC data files")

        dataframes = []
        for csv_file in tqdm(csv_files, desc="Loading CSV files"):
            try:
                df = pd.read_csv(csv_file, low_memory=False)
                dataframes.append(df)
                logger.debug(f"Loaded {len(df)} records from {csv_file.name}")
            except Exception as e:
                logger.error(f"Error loading {csv_file.name}: {e}")

        if not dataframes:
            logger.error("No data loaded successfully")
            return pd.DataFrame()

        # Combine all dataframes
        combined_df = pd.concat(dataframes, ignore_index=True)
        logger.info(f"Total records loaded: {len(combined_df):,}")

        return combined_df

    def apply_initial_filters(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply initial filters based on configured property filters.

        Args:
            df: Raw EPC DataFrame

        Returns:
            Filtered DataFrame
        """
        logger.info("Applying initial filters...")
        initial_count = len(df)

        construction_age_bands = self.property_filters.get('construction_age_bands') or []
        if construction_age_bands and 'CONSTRUCTION_AGE_BAND' in df.columns:
            df = df[df['CONSTRUCTION_AGE_BAND'].isin(construction_age_bands)]
            logger.info(
                "After construction age band filter: "
                f"{len(df):,} records ({len(df)/initial_count*100:.1f}%)"
            )

        property_types = self.property_filters.get('property_types') or []
        if property_types and 'PROPERTY_TYPE' in df.columns:
            property_types_lower = {ptype.lower() for ptype in property_types}
            df = df[df['PROPERTY_TYPE'].str.lower().isin(property_types_lower)]
            logger.info(f"After property type filter: {len(df):,} records")

        built_forms = self.property_filters.get('built_forms') or []
        if built_forms and 'BUILT_FORM' in df.columns:
            built_forms_lower = {form.lower() for form in built_forms}
            df = df[df['BUILT_FORM'].str.lower().isin(built_forms_lower)]
            logger.info(f"After built form filter: {len(df):,} records")

        if self.property_filters.get('exclude_conversions') and 'BUILT_FORM' in df.columns:
            df = df[~df['BUILT_FORM'].str.contains('Flat', case=False, na=False)]
            logger.info(f"After conversion exclusion filter: {len(df):,} records")

        # Filter by certificate recency (last 10 years)
        if 'LODGEMENT_DATE' in df.columns:
            recency_years = self.property_filters.get('certificate_recency_years')
            if recency_years:
                cutoff_date = datetime.now() - timedelta(days=recency_years * 365)
                df['LODGEMENT_DATE'] = pd.to_datetime(df['LODGEMENT_DATE'], errors='coerce')
                df = df[df['LODGEMENT_DATE'] >= cutoff_date]
                logger.info(f"After recency filter: {len(df):,} records")

        logger.info(f"Filtering complete: {len(df):,} records retained ({len(df)/initial_count*100:.1f}%)")

        return df

    def extract_shakespeare_crescent(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Extract all EPCs for Shakespeare Crescent for case study calibration.

        Args:
            df: Full EPC DataFrame

        Returns:
            DataFrame containing only Shakespeare Crescent records
        """
        case_street = self.config['analysis']['case_street']
        logger.info(f"Extracting data for case street: {case_street}")

        if 'ADDRESS' in df.columns:
            case_df = df[df['ADDRESS'].str.contains(case_street, case=False, na=False)]
        elif 'ADDRESS1' in df.columns:
            case_df = df[df['ADDRESS1'].str.contains(case_street, case=False, na=False)]
        else:
            logger.warning("No address column found for case street extraction")
            return pd.DataFrame()

        logger.info(f"Found {len(case_df)} records for {case_street}")

        # Save case street data separately
        case_output = DATA_RAW_DIR / f"epc_{case_street.lower().replace(' ', '_')}.csv"
        case_df.to_csv(case_output, index=False)
        logger.info(f"Case street data saved to: {case_output}")

        return case_df

    def save_processed_data(self, df: pd.DataFrame, filename: str = "epc_england_wales_filtered.csv"):
        """
        Save processed EPC data.

        Args:
            df: Processed DataFrame
            filename: Output filename
        """
        output_path = DATA_RAW_DIR / filename
        df.to_csv(output_path, index=False)
        logger.info(f"Saved {len(df):,} records to: {output_path}")

        # Also save as parquet for faster loading
        parquet_path = output_path.with_suffix('.parquet')
        df.to_parquet(parquet_path, index=False)
        logger.info(f"Also saved as parquet: {parquet_path}")


def main():
    """Main execution function for EPC data acquisition."""
    logger.info("Starting EPC data acquisition...")

    # Initialize downloader
    downloader = EPCDownloader()

    # Option 1: Download bulk data (creates instructions)
    downloader.download_bulk_data()

    # Option 2: Load existing local data
    df = downloader.load_local_data()

    if not df.empty:
        # Apply filters
        df_filtered = downloader.apply_initial_filters(df)

        # Extract case street data
        case_df = downloader.extract_shakespeare_crescent(df_filtered)

        # Save processed data
        downloader.save_processed_data(df_filtered)

        logger.info("Data acquisition complete!")
        logger.info(f"Final dataset: {len(df_filtered):,} properties")
        logger.info(f"Case street: {len(case_df)} properties")
    else:
        logger.warning("No data loaded. Please follow download instructions.")


if __name__ == "__main__":
    main()
