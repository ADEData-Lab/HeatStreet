"""
EPC API Data Acquisition Module

Downloads EPC data directly from the UK EPC Register API.
Handles data for London boroughs with filters for Edwardian terraced housing.
"""

import os
import base64
import urllib.request
from urllib.parse import urlencode
import pandas as pd
import io
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime
from tqdm import tqdm
from loguru import logger
from dotenv import load_dotenv

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import (
    load_config,
    DATA_RAW_DIR,
    get_london_boroughs,
    get_property_filters
)

# Load environment variables
load_dotenv()


class EPCAPIDownloader:
    """
    Downloads EPC data from the UK EPC Register API.

    Requires API credentials from https://epc.opendatacommunities.org/
    """

    BASE_URL = "https://epc.opendatacommunities.org/api/v1/domestic/search"

    # London borough local authority codes
    LONDON_LA_CODES = {
        'Barking and Dagenham': 'E09000002',
        'Barnet': 'E09000003',
        'Bexley': 'E09000004',
        'Brent': 'E09000005',
        'Bromley': 'E09000006',
        'Camden': 'E09000007',
        'City of London': 'E09000001',
        'Croydon': 'E09000008',
        'Ealing': 'E09000009',
        'Enfield': 'E09000010',
        'Greenwich': 'E09000011',
        'Hackney': 'E09000012',
        'Hammersmith and Fulham': 'E09000013',
        'Haringey': 'E09000014',
        'Harrow': 'E09000015',
        'Havering': 'E09000016',
        'Hillingdon': 'E09000017',
        'Hounslow': 'E09000018',
        'Islington': 'E09000019',
        'Kensington and Chelsea': 'E09000020',
        'Kingston upon Thames': 'E09000021',
        'Lambeth': 'E09000022',
        'Lewisham': 'E09000023',
        'Merton': 'E09000024',
        'Newham': 'E09000025',
        'Redbridge': 'E09000026',
        'Richmond upon Thames': 'E09000027',
        'Southwark': 'E09000028',
        'Sutton': 'E09000029',
        'Tower Hamlets': 'E09000030',
        'Waltham Forest': 'E09000031',
        'Wandsworth': 'E09000032',
        'Westminster': 'E09000033'
    }

    def __init__(self, email: Optional[str] = None, api_key: Optional[str] = None):
        """
        Initialize EPC API downloader.

        Args:
            email: API email (from environment if not provided)
            api_key: API key (from environment if not provided)
        """
        self.config = load_config()
        self.property_filters = get_property_filters()

        # Get credentials from environment or parameters
        self.email = email or os.getenv('EPC_API_EMAIL')
        self.api_key = api_key or os.getenv('EPC_API_KEY')

        if not self.email or not self.api_key:
            raise ValueError(
                "API credentials not found. Please set EPC_API_EMAIL and EPC_API_KEY "
                "in your .env file or pass them as parameters."
            )

        # Generate authorization token
        self.auth_token = self._generate_auth_token()

        # Ensure output directory exists
        DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)

        logger.info(f"Initialized EPC API Downloader for {len(self.LONDON_LA_CODES)} London boroughs")
        logger.info(f"Authenticated as: {self.email}")

    def _generate_auth_token(self) -> str:
        """
        Generate Base64-encoded authorization token.

        Returns:
            Base64-encoded auth token
        """
        # Combine email and API key
        credentials = f"{self.email}:{self.api_key}"

        # Encode to base64
        token = base64.b64encode(credentials.encode()).decode()

        return token

    def download_borough_data(
        self,
        borough_name: str,
        property_type: str = 'house',
        from_year: int = 2015,
        max_results: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Download EPC data for a specific London borough.

        Args:
            borough_name: Name of the London borough
            property_type: Property type filter (default: 'house')
            from_year: Earliest year for certificates (default: 2015)
            max_results: Maximum number of results to download (None = all)

        Returns:
            DataFrame containing EPC data
        """
        # Get local authority code
        la_code = self.LONDON_LA_CODES.get(borough_name)
        if not la_code:
            logger.error(f"Unknown borough: {borough_name}")
            return pd.DataFrame()

        logger.info(f"Downloading EPC data for {borough_name} (LA: {la_code})...")

        # Build query parameters
        query_params = {
            'local-authority': la_code,
            'property-type': property_type,
            'from-year': from_year,
            'size': 5000  # Max page size
        }

        all_data = []
        search_after = None
        page_count = 0
        total_records = 0

        # Set up progress bar
        pbar = tqdm(desc=f"{borough_name}", unit=" records")

        try:
            while True:
                # Add search-after if not first request
                if search_after:
                    query_params['search-after'] = search_after

                # Make API request
                data, next_search_after = self._make_api_request(query_params)

                if data is None or data.empty:
                    break

                all_data.append(data)
                page_count += 1
                total_records += len(data)
                pbar.update(len(data))

                # Check if we've hit max_results
                if max_results and total_records >= max_results:
                    logger.info(f"Reached max_results limit ({max_results})")
                    break

                # Check if there are more results
                if not next_search_after:
                    break

                search_after = next_search_after

        except Exception as e:
            logger.error(f"Error downloading data for {borough_name}: {e}")

        finally:
            pbar.close()

        if all_data:
            df = pd.concat(all_data, ignore_index=True)
            logger.info(f"Downloaded {len(df):,} records for {borough_name} in {page_count} pages")
            return df
        else:
            logger.warning(f"No data downloaded for {borough_name}")
            return pd.DataFrame()

    def _make_api_request(self, query_params: Dict) -> tuple:
        """
        Make a single API request with pagination.

        Args:
            query_params: Query parameters for the API

        Returns:
            Tuple of (DataFrame, next_search_after)
        """
        # Set up headers
        headers = {
            'Accept': 'text/csv',
            'Authorization': f'Basic {self.auth_token}'
        }

        # Build full URL
        encoded_params = urlencode(query_params)
        full_url = f"{self.BASE_URL}?{encoded_params}"

        try:
            # Make request
            request = urllib.request.Request(full_url, headers=headers)

            with urllib.request.urlopen(request, timeout=60) as response:
                # Read response body
                response_body = response.read().decode('utf-8')

                # Get next search-after from headers
                next_search_after = response.getheader('X-Next-Search-After')

                # Parse CSV data
                if response_body:
                    df = pd.read_csv(io.StringIO(response_body))
                    return df, next_search_after
                else:
                    return pd.DataFrame(), None

        except urllib.error.HTTPError as e:
            logger.error(f"HTTP Error {e.code}: {e.reason}")
            return None, None
        except urllib.error.URLError as e:
            logger.error(f"URL Error: {e.reason}")
            return None, None
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return None, None

    def download_all_london_boroughs(
        self,
        property_types: Optional[List[str]] = None,
        from_year: int = 2015,
        max_results_per_borough: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Download EPC data for all London boroughs.

        Args:
            property_types: List of property types to download (default: ['house'])
            from_year: Earliest year for certificates (default: 2015)
            max_results_per_borough: Max results per borough (None = all)

        Returns:
            Combined DataFrame for all boroughs
        """
        if property_types is None:
            property_types = ['house']

        logger.info(f"Downloading EPC data for all {len(self.LONDON_LA_CODES)} London boroughs...")
        logger.info(f"Property types: {property_types}")
        logger.info(f"From year: {from_year}")

        all_borough_data = []

        for borough_name in self.LONDON_LA_CODES.keys():
            for property_type in property_types:
                df = self.download_borough_data(
                    borough_name=borough_name,
                    property_type=property_type,
                    from_year=from_year,
                    max_results=max_results_per_borough
                )

                if not df.empty:
                    df['borough'] = borough_name
                    all_borough_data.append(df)

        if all_borough_data:
            combined_df = pd.concat(all_borough_data, ignore_index=True)
            logger.info(f"Total records downloaded: {len(combined_df):,}")
            return combined_df
        else:
            logger.warning("No data downloaded")
            return pd.DataFrame()

    def apply_edwardian_filters(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply filters for Edwardian terraced housing.

        Args:
            df: Raw EPC DataFrame

        Returns:
            Filtered DataFrame
        """
        logger.info("Applying Edwardian terraced housing filters...")
        initial_count = len(df)

        if df.empty:
            return df

        # Filter by construction period (pre-1930)
        if 'CONSTRUCTION_AGE_BAND' in df.columns:
            pre_1930_bands = [
                'before 1900',
                'England and Wales: before 1900',
                '1900-1929',
                'England and Wales: 1900-1929',
                '1900-1920',
                '1920-1929'
            ]
            df = df[df['CONSTRUCTION_AGE_BAND'].isin(pre_1930_bands)]
            logger.info(f"After construction period filter: {len(df):,} records")

        # Filter by built form (terraced)
        if 'BUILT_FORM' in df.columns:
            terrace_forms = ['Mid-Terrace', 'End-Terrace', 'Enclosed Mid-Terrace', 'Enclosed End-Terrace']
            df = df[df['BUILT_FORM'].isin(terrace_forms)]
            logger.info(f"After built form filter: {len(df):,} records")

        # Exclude flats
        if 'PROPERTY_TYPE' in df.columns:
            df = df[df['PROPERTY_TYPE'] != 'Flat']
            logger.info(f"After property type filter: {len(df):,} records")

        logger.info(f"Filtering complete: {len(df):,} / {initial_count:,} records retained ({len(df)/initial_count*100:.1f}%)")

        return df

    def save_data(self, df: pd.DataFrame, filename: str):
        """
        Save downloaded data to file.

        Args:
            df: DataFrame to save
            filename: Output filename
        """
        # Save as CSV (always works)
        csv_path = DATA_RAW_DIR / filename
        df.to_csv(csv_path, index=False)
        logger.info(f"Saved {len(df):,} records to: {csv_path}")

        # Try to save as parquet for faster loading (optional)
        try:
            parquet_path = csv_path.with_suffix('.parquet')
            # Convert problematic columns to strings to avoid type issues
            df_parquet = df.copy()
            for col in df_parquet.columns:
                if df_parquet[col].dtype == 'object':
                    # Convert mixed-type object columns to strings
                    df_parquet[col] = df_parquet[col].astype(str)

            df_parquet.to_parquet(parquet_path, index=False)
            logger.info(f"Also saved as parquet: {parquet_path}")
        except Exception as e:
            logger.warning(f"Could not save as parquet (not critical): {e}")
            logger.info("CSV file saved successfully - parquet is optional for performance only")


def main():
    """Main execution function for EPC API data acquisition."""
    logger.info("Starting EPC API data acquisition...")

    try:
        # Initialize downloader
        downloader = EPCAPIDownloader()

        # Download data for all London boroughs
        # Start with last 10 years of house data
        df = downloader.download_all_london_boroughs(
            property_types=['house'],
            from_year=2015,
            max_results_per_borough=None  # Download all
        )

        if not df.empty:
            # Save raw data
            downloader.save_data(df, "epc_london_raw.csv")

            # Apply Edwardian filters
            df_filtered = downloader.apply_edwardian_filters(df)

            # Save filtered data
            downloader.save_data(df_filtered, "epc_london_edwardian_filtered.csv")

            logger.info("Data acquisition complete!")
            logger.info(f"Raw dataset: {len(df):,} properties")
            logger.info(f"Filtered dataset: {len(df_filtered):,} properties")
        else:
            logger.error("No data downloaded")

    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        logger.info("\nTo use the API downloader:")
        logger.info("1. Copy .env.example to .env")
        logger.info("2. Add your EPC API credentials to .env")
        logger.info("3. Get credentials from: https://epc.opendatacommunities.org/")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()
