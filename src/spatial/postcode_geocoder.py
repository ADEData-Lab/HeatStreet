"""
UK Postcode Geocoding Module

Converts UK postcodes to latitude/longitude coordinates using free APIs.
Supports multiple geocoding providers with fallback options.
"""

import pandas as pd
import numpy as np
import requests
import time
from pathlib import Path
from typing import Optional, Tuple, List
from loguru import logger
from tqdm import tqdm
import geopandas as gpd
from shapely.geometry import Point
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from src.utils.profiling import log_memory


class PostcodeGeocoder:
    """
    Geocodes UK postcodes to latitude/longitude coordinates.

    Uses free UK postcode APIs with rate limiting and caching.
    """

    # Free UK Postcode API (no authentication required)
    POSTCODES_IO_URL = "https://api.postcodes.io/postcodes"

    def __init__(self, cache_file: Optional[Path] = None):
        """
        Initialize postcode geocoder.

        Args:
            cache_file: Optional path to cache geocoded results
        """
        self.cache_file = cache_file
        self.cache = {}

        if cache_file and cache_file.exists():
            logger.info(f"Loading geocoding cache from {cache_file}")
            cache_df = pd.read_csv(cache_file)
            self.cache = dict(zip(cache_df['postcode'],
                                 zip(cache_df['latitude'], cache_df['longitude'])))
            logger.info(f"Loaded {len(self.cache):,} cached postcodes")

    def clean_postcode(self, postcode: str) -> str:
        """
        Clean and standardize UK postcode format.

        Args:
            postcode: Raw postcode string

        Returns:
            Cleaned postcode (uppercase, single space)
        """
        if pd.isna(postcode):
            return None

        # Remove extra whitespace and convert to uppercase
        postcode = str(postcode).strip().upper()

        # Remove all spaces
        postcode = postcode.replace(' ', '')

        # Add space before last 3 characters (standard UK format)
        if len(postcode) >= 5:
            postcode = postcode[:-3] + ' ' + postcode[-3:]

        return postcode

    def geocode_single(self, postcode: str, use_cache: bool = True) -> Optional[Tuple[float, float]]:
        """
        Geocode a single postcode.

        Args:
            postcode: UK postcode to geocode
            use_cache: Use cached results if available

        Returns:
            Tuple of (latitude, longitude) or None if failed
        """
        # Clean postcode
        postcode = self.clean_postcode(postcode)

        if not postcode:
            return None

        # Check cache
        if use_cache and postcode in self.cache:
            return self.cache[postcode]

        try:
            # Call postcodes.io API
            response = requests.get(f"{self.POSTCODES_IO_URL}/{postcode}", timeout=5)

            if response.status_code == 200:
                data = response.json()

                if data['status'] == 200 and data['result']:
                    lat = data['result']['latitude']
                    lon = data['result']['longitude']

                    # Cache result
                    self.cache[postcode] = (lat, lon)

                    return (lat, lon)

            return None

        except Exception as e:
            logger.debug(f"Error geocoding {postcode}: {e}")
            return None

    def geocode_batch(self, postcodes: List[str], batch_size: int = 100, max_workers: int = 4) -> dict:
        """
        Geocode multiple postcodes using parallel batch API calls.

        Args:
            postcodes: List of UK postcodes
            batch_size: Number of postcodes per batch (max 100)
            max_workers: Number of parallel API request threads (default: 4)

        Returns:
            Dictionary mapping postcode to (lat, lon) tuple
        """
        results = {}
        results_lock = threading.Lock()

        # Clean postcodes
        postcodes = [self.clean_postcode(pc) for pc in postcodes if pd.notna(pc)]
        postcodes = [pc for pc in postcodes if pc]  # Remove None values

        # Check cache first
        uncached = []
        for pc in postcodes:
            if pc in self.cache:
                results[pc] = self.cache[pc]
            else:
                uncached.append(pc)

        if not uncached:
            return results

        logger.info(f"Geocoding {len(uncached):,} postcodes (parallel batch mode with {max_workers} workers)...")

        # Split into batches
        batches = [uncached[i:i+batch_size] for i in range(0, len(uncached), batch_size)]

        def geocode_single_batch(batch: List[str], batch_idx: int):
            """Geocode a single batch of postcodes."""
            batch_results = {}
            try:
                # Call batch API
                response = requests.post(
                    self.POSTCODES_IO_URL,
                    json={"postcodes": batch},
                    timeout=10
                )

                if response.status_code == 200:
                    data = response.json()

                    if data['status'] == 200:
                        for item in data['result']:
                            if item['result']:
                                postcode = item['query']
                                lat = item['result']['latitude']
                                lon = item['result']['longitude']

                                batch_results[postcode] = (lat, lon)

                # Small delay between batches to be nice to free API
                time.sleep(0.05)

                return batch_results, batch_idx

            except Exception as e:
                logger.warning(f"Error geocoding batch {batch_idx}: {e}")
                return {}, batch_idx

        # Process batches in parallel using ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(geocode_single_batch, batch, idx): idx
                for idx, batch in enumerate(batches)
            }

            # Track progress with tqdm
            with tqdm(total=len(batches), desc="Geocoding batches") as pbar:
                for future in as_completed(futures):
                    try:
                        batch_results, batch_idx = future.result()

                        # Add results to main results dict (thread-safe)
                        with results_lock:
                            results.update(batch_results)
                            self.cache.update(batch_results)

                        pbar.update(1)

                    except Exception as e:
                        logger.error(f"Batch processing failed: {e}")
                        pbar.update(1)

        # Save cache
        if self.cache_file:
            self._save_cache()

        return results

    def geocode_dataframe_inplace(
        self,
        df: pd.DataFrame,
        postcode_column: str = 'POSTCODE',
        batch_mode: bool = True
    ) -> pd.DataFrame:
        """
        Geocode postcodes and add lat/lon columns IN-PLACE (memory-efficient).

        This method avoids DataFrame.copy() and uses Series.map() for minimal
        memory overhead. Suitable for large datasets (700k+ rows) on 16GB systems.

        Args:
            df: DataFrame with postcode column (modified in-place)
            postcode_column: Name of postcode column
            batch_mode: Use batch API (much faster)

        Returns:
            The same DataFrame with LATITUDE and LONGITUDE columns added (float32)
        """
        log_memory("Geocoding START", force=True)
        logger.info(f"Geocoding {len(df):,} properties from postcode column: {postcode_column}")

        if postcode_column not in df.columns:
            logger.error(f"Column '{postcode_column}' not found in DataFrame")
            return df

        # Get unique postcodes and geocode them
        unique_postcodes = df[postcode_column].dropna().unique()
        logger.info(f"Found {len(unique_postcodes):,} unique postcodes")

        # Geocode unique postcodes (this populates self.cache)
        if batch_mode:
            coords_map = self.geocode_batch(unique_postcodes)
        else:
            coords_map = {}
            for pc in tqdm(unique_postcodes, desc="Geocoding"):
                result = self.geocode_single(pc)
                if result:
                    coords_map[self.clean_postcode(pc)] = result
                time.sleep(0.05)

        logger.info(f"Successfully geocoded {len(coords_map):,} postcodes ({len(coords_map)/max(1,len(unique_postcodes))*100:.1f}%)")

        # Create lookup Series indexed by cleaned postcode (for fast map)
        # Extract lat/lon into separate Series with float32 dtype
        postcodes_list = list(coords_map.keys())
        lat_values = np.array([coords_map[pc][0] for pc in postcodes_list], dtype=np.float32)
        lon_values = np.array([coords_map[pc][1] for pc in postcodes_list], dtype=np.float32)

        postcode_to_lat = pd.Series(lat_values, index=postcodes_list)
        postcode_to_lon = pd.Series(lon_values, index=postcodes_list)

        log_memory("Before postcode mapping", force=True)

        # Clean postcodes in input df (no copy - creates new column)
        df['POSTCODE_CLEAN'] = df[postcode_column].apply(self.clean_postcode)

        # Map lat/lon using Series.map (memory-efficient, no DataFrame copy)
        df['LATITUDE'] = df['POSTCODE_CLEAN'].map(postcode_to_lat).astype(np.float32)
        df['LONGITUDE'] = df['POSTCODE_CLEAN'].map(postcode_to_lon).astype(np.float32)

        # Drop temporary column
        df.drop(columns=['POSTCODE_CLEAN'], inplace=True)

        rss_after = log_memory("After postcode mapping", force=True)

        geocoded_count = df['LATITUDE'].notna().sum()
        logger.info(f"✓ Added coordinates to {geocoded_count:,} of {len(df):,} properties ({geocoded_count/len(df)*100:.1f}%)")

        return df

    def geocode_dataframe(self,
                         df: pd.DataFrame,
                         postcode_column: str = 'POSTCODE',
                         batch_mode: bool = True) -> gpd.GeoDataFrame:
        """
        Geocode all postcodes in a DataFrame.

        Args:
            df: DataFrame with postcode column
            postcode_column: Name of postcode column
            batch_mode: Use batch API (much faster)

        Returns:
            GeoDataFrame with geometry column
        """
        logger.info(f"Geocoding {len(df):,} properties from postcode column: {postcode_column}")

        if postcode_column not in df.columns:
            logger.error(f"Column '{postcode_column}' not found in DataFrame")
            available = ', '.join(df.columns[:10].tolist())
            logger.error(f"Available columns: {available}...")
            return None

        # Get unique postcodes
        unique_postcodes = df[postcode_column].unique()
        logger.info(f"Found {len(unique_postcodes):,} unique postcodes")

        # Geocode
        if batch_mode:
            coords_map = self.geocode_batch(unique_postcodes)
        else:
            coords_map = {}
            for pc in tqdm(unique_postcodes, desc="Geocoding"):
                result = self.geocode_single(pc)
                if result:
                    coords_map[self.clean_postcode(pc)] = result
                time.sleep(0.05)  # Rate limiting

        logger.info(f"Successfully geocoded {len(coords_map):,} postcodes ({len(coords_map)/len(unique_postcodes)*100:.1f}%)")

        # Add coordinates to dataframe
        df_copy = df.copy()
        df_copy['POSTCODE_CLEAN'] = df_copy[postcode_column].apply(self.clean_postcode)

        def get_coords(pc):
            return coords_map.get(pc, (None, None))

        coords = df_copy['POSTCODE_CLEAN'].apply(get_coords)
        df_copy['LATITUDE'] = coords.apply(lambda x: x[0] if x else None)
        df_copy['LONGITUDE'] = coords.apply(lambda x: x[1] if x else None)

        # Create geometry
        geometry = [
            Point(lon, lat) if pd.notna(lon) and pd.notna(lat) else None
            for lon, lat in zip(df_copy['LONGITUDE'], df_copy['LATITUDE'])
        ]

        gdf = gpd.GeoDataFrame(df_copy, geometry=geometry, crs='EPSG:4326')

        # Remove properties without coordinates
        initial_count = len(gdf)
        gdf = gdf[gdf.geometry.notna()].copy()

        success_rate = len(gdf) / initial_count * 100
        logger.info(f"✓ Geocoded {len(gdf):,} of {initial_count:,} properties ({success_rate:.1f}%)")

        return gdf

    def _save_cache(self):
        """Save geocoding cache to file."""
        if not self.cache_file:
            return

        cache_df = pd.DataFrame([
            {'postcode': pc, 'latitude': lat, 'longitude': lon}
            for pc, (lat, lon) in self.cache.items()
        ])

        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_df.to_csv(self.cache_file, index=False)
        logger.debug(f"Saved {len(cache_df):,} postcodes to cache")


def geocode_uk_postcodes(df: pd.DataFrame,
                        postcode_column: str = 'POSTCODE',
                        cache_file: Optional[Path] = None) -> gpd.GeoDataFrame:
    """
    Convenience function to geocode UK postcodes in a DataFrame.

    Args:
        df: DataFrame with postcode column
        postcode_column: Name of postcode column (default: 'POSTCODE')
        cache_file: Optional path to cache file (speeds up repeated runs)

    Returns:
        GeoDataFrame with geometry column

    Example:
        >>> df = pd.read_csv('epc_data.csv')
        >>> gdf = geocode_uk_postcodes(df, postcode_column='POSTCODE')
        >>> gdf.to_file('properties.geojson', driver='GeoJSON')
    """
    geocoder = PostcodeGeocoder(cache_file=cache_file)
    return geocoder.geocode_dataframe(df, postcode_column=postcode_column)


if __name__ == "__main__":
    # Example usage
    import sys
    sys.path.append(str(Path(__file__).parent.parent.parent))
    from config.config import DATA_RAW_DIR

    # Test with sample postcodes
    test_postcodes = [
        "SW1A 1AA",  # 10 Downing Street
        "EC4M 7RF",  # St Paul's Cathedral
        "WC2N 5DU",  # Trafalgar Square
        "N1 9AG",    # Islington
    ]

    geocoder = PostcodeGeocoder()

    print("\nTesting single geocoding:")
    for pc in test_postcodes:
        coords = geocoder.geocode_single(pc)
        print(f"{pc}: {coords}")

    print("\nTesting batch geocoding:")
    results = geocoder.geocode_batch(test_postcodes)
    for pc, coords in results.items():
        print(f"{pc}: {coords}")
