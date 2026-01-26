"""
BEIS Heat Network Planning Database (HNPD) Downloader

Downloads and manages heat network data from UK Government HNPD,
providing up-to-date information on existing and planned heat networks
across the UK.

Data source: https://www.gov.uk/government/publications/heat-networks-planning-database
HNPD Version: January 2024

Author: Heat Street EPC Analysis
Date: 2026-01-18
"""

import csv
from pathlib import Path
from typing import Optional, List, Dict
import subprocess
import sys
import urllib.request
import ssl
from loguru import logger

# Optional imports for GeoDataFrame support
try:
    import geopandas as gpd
    from shapely.geometry import Point
    SPATIAL_AVAILABLE = True
except ImportError:
    SPATIAL_AVAILABLE = False
    logger.warning("geopandas not available - spatial analysis disabled")

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
EXTERNAL_DIR = DATA_DIR / "external"


class HNPDDownloader:
    """Downloads and manages BEIS Heat Network Planning Database."""

    # GOV.UK HNPD URL (January 2024 version)
    HNPD_URL = "https://assets.publishing.service.gov.uk/media/65c9f7b89c5b7f000c951cad/hnpd-january-2024.csv"

    # Tier classification mappings (aligned with HeatStreet tier system)
    TIER_1_STATUSES = [
        "Operational",
        "Under Construction",
        "No Application Required"
    ]

    TIER_2_STATUSES = [
        "Planning Permission Granted",
        "Planning Permission Granted ",  # Note: some records have trailing space
        "Appeal Granted",
        "Secretary of State - Granted"
    ]

    def __init__(self):
        """Initialize the HNPD downloader."""
        logger.info("Initialized HNPD Downloader")
        EXTERNAL_DIR.mkdir(parents=True, exist_ok=True)

    def download_hnpd(self, force_redownload: bool = False) -> bool:
        """
        Download HNPD CSV from GOV.UK.

        Args:
            force_redownload: If True, download even if file exists

        Returns:
            True if successful, False otherwise
        """
        csv_path = EXTERNAL_DIR / "hnpd-january-2024.csv"

        if csv_path.exists() and not force_redownload:
            logger.info(f"HNPD data already downloaded: {csv_path}")
            return True

        logger.info("Downloading BEIS Heat Network Planning Database...")
        logger.info(f"URL: {self.HNPD_URL}")

        try:
            # Prefer a pure-Python download for cross-platform reliability.
            # Some environments (e.g., Windows/conda) may not have `wget` installed.
            def download_with_urllib() -> None:
                context = ssl.create_default_context()
                try:
                    import certifi  # type: ignore
                    context = ssl.create_default_context(cafile=certifi.where())
                except Exception:
                    pass

                with urllib.request.urlopen(self.HNPD_URL, context=context) as response:
                    # Stream to disk to avoid holding full CSV in memory
                    csv_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(csv_path, "wb") as f:
                        while True:
                            chunk = response.read(1024 * 1024)
                            if not chunk:
                                break
                            f.write(chunk)

            try:
                download_with_urllib()
            except Exception as exc:
                logger.warning(f"Python download failed ({exc}). Falling back to system downloaders...")

                # Fallback 1: curl (common on Windows + Linux)
                curl_cmd = [
                    "curl",
                    "-L",
                    "-o", str(csv_path),
                    self.HNPD_URL
                ]
                curl_result = subprocess.run(curl_cmd, capture_output=True, text=True)
                if curl_result.returncode != 0:
                    # Fallback 2: wget (legacy)
                    wget_cmd = [
                        "wget",
                        "--no-check-certificate",
                        "--progress=bar:force",
                        "-O", str(csv_path),
                        self.HNPD_URL
                    ]
                    wget_result = subprocess.run(wget_cmd, capture_output=True, text=True)

                    if wget_result.returncode != 0 and sys.platform.startswith("win"):
                        # Fallback 3: PowerShell Invoke-WebRequest (Windows)
                        ps_cmd = [
                            "powershell",
                            "-NoProfile",
                            "-Command",
                            f"Invoke-WebRequest -Uri '{self.HNPD_URL}' -OutFile '{csv_path}'"
                        ]
                        ps_result = subprocess.run(ps_cmd, capture_output=True, text=True)
                        if ps_result.returncode != 0:
                            logger.error("HNPD download failed via urllib, curl, wget, and Invoke-WebRequest.")
                            logger.error(ps_result.stderr.strip() or ps_result.stdout.strip())
                            return False
                    elif wget_result.returncode != 0:
                        logger.error("HNPD download failed via urllib, curl, and wget.")
                        logger.error(wget_result.stderr.strip() or wget_result.stdout.strip())
                        return False

            size_kb = csv_path.stat().st_size / 1024
            logger.info(f"✓ Downloaded HNPD: {size_kb:.0f} KB")
            return True

        except Exception as e:
            logger.error(f"Error downloading HNPD: {e}")
            return False

    def load_hnpd_csv(self, region_filter: Optional[str] = None) -> List[Dict]:
        """
        Load HNPD CSV and return as list of dictionaries.

        Args:
            region_filter: Optional region name (e.g., "London", "South East")

        Returns:
            List of network records as dictionaries
        """
        csv_path = EXTERNAL_DIR / "hnpd-january-2024.csv"

        if not csv_path.exists():
            logger.error(f"HNPD CSV not found: {csv_path}")
            logger.info("Run download_hnpd() first to download the data")
            return []

        try:
            with open(csv_path, 'r', encoding='latin-1') as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            logger.info(f"Loaded HNPD: {len(rows)} total records")

            if region_filter:
                rows = [r for r in rows if r.get('Region') == region_filter]
                logger.info(f"Filtered to {region_filter}: {len(rows)} records")

            return rows

        except Exception as e:
            logger.error(f"Error loading HNPD CSV: {e}")
            return []

    def load_hnpd_as_geodataframe(self,
                                   region_filter: Optional[str] = None,
                                   status_filter: Optional[List[str]] = None
                                  ) -> Optional['gpd.GeoDataFrame']:
        """
        Load HNPD as GeoDataFrame with point geometries.

        Args:
            region_filter: Optional region (e.g., "London")
            status_filter: Optional list of statuses to include

        Returns:
            GeoDataFrame in EPSG:27700 (British National Grid), or None if spatial not available
        """
        if not SPATIAL_AVAILABLE:
            logger.error("GeoDataFrame conversion requires geopandas")
            return None

        rows = self.load_hnpd_csv(region_filter=region_filter)

        if not rows:
            return None

        # Filter by status if specified
        if status_filter:
            rows = [r for r in rows
                   if r.get('Development Status') in status_filter]
            logger.info(f"Filtered to statuses {status_filter}: {len(rows)} records")

        # Convert to GeoDataFrame
        geometries = []
        valid_rows = []

        for row in rows:
            try:
                x = float(row.get('X-coordinate', ''))
                y = float(row.get('Y-coordinate', ''))
                geometries.append(Point(x, y))
                valid_rows.append(row)
            except (ValueError, TypeError):
                # Skip records without valid coordinates
                continue

        if not valid_rows:
            logger.warning("No records with valid coordinates found")
            return None

        gdf = gpd.GeoDataFrame(valid_rows, geometry=geometries, crs='EPSG:27700')
        logger.info(f"✓ Created GeoDataFrame: {len(gdf)} networks with coordinates")

        return gdf

    def get_tier_1_networks(self, region: Optional[str] = None) -> Optional['gpd.GeoDataFrame']:
        """
        Get existing/under construction networks (Tier 1 sources).

        These are networks that are currently operational or being built,
        representing the most reliable Tier 1 classification sources.

        Args:
            region: Optional region filter (e.g., "London")

        Returns:
            GeoDataFrame of Tier 1 network sources
        """
        return self.load_hnpd_as_geodataframe(
            region_filter=region,
            status_filter=self.TIER_1_STATUSES
        )

    def get_tier_2_networks(self, region: Optional[str] = None) -> Optional['gpd.GeoDataFrame']:
        """
        Get planned networks with permission (Tier 2 sources).

        These are networks that have received planning permission but are
        not yet under construction, representing planned future infrastructure.

        Args:
            region: Optional region filter (e.g., "London")

        Returns:
            GeoDataFrame of Tier 2 network sources
        """
        return self.load_hnpd_as_geodataframe(
            region_filter=region,
            status_filter=self.TIER_2_STATUSES
        )

    def get_data_summary(self) -> Dict:
        """
        Get summary of available HNPD data.

        Returns:
            Dictionary with data availability and statistics
        """
        csv_path = EXTERNAL_DIR / "hnpd-january-2024.csv"

        if not csv_path.exists():
            return {
                'available': False,
                'message': 'HNPD not downloaded yet. Run download_hnpd() first.'
            }

        rows = self.load_hnpd_csv()

        # Count by status
        tier_1_count = len([r for r in rows if r.get('Development Status') in self.TIER_1_STATUSES])
        tier_2_count = len([r for r in rows if r.get('Development Status') in self.TIER_2_STATUSES])

        # Count by region
        regions = list(set(r.get('Region', '') for r in rows if r.get('Region')))
        regions.sort()

        # Count coordinates available
        coords_count = sum(1 for r in rows
                          if r.get('X-coordinate') and r.get('Y-coordinate'))

        return {
            'available': True,
            'total_records': len(rows),
            'tier_1_networks': tier_1_count,
            'tier_2_networks': tier_2_count,
            'coordinates_available': coords_count,
            'coordinate_percentage': (coords_count / len(rows) * 100) if rows else 0,
            'regions': regions,
            'region_count': len(regions),
            'csv_path': str(csv_path),
            'spatial_analysis_available': SPATIAL_AVAILABLE
        }

    def download_and_prepare(self, force_redownload: bool = False) -> bool:
        """
        Complete workflow: download HNPD data.

        Args:
            force_redownload: If True, download even if data already exists

        Returns:
            True if successful, False otherwise
        """
        # Download
        if not self.download_hnpd(force_redownload=force_redownload):
            return False

        # Report summary
        summary = self.get_data_summary()

        if summary['available']:
            logger.info("✓ HNPD data ready:")
            logger.info(f"  - {summary['total_records']} total heat network records")
            logger.info(f"  - {summary['tier_1_networks']} Tier 1 networks (operational/under construction)")
            logger.info(f"  - {summary['tier_2_networks']} Tier 2 networks (planning granted)")
            logger.info(f"  - {summary['coordinates_available']} records with coordinates ({summary['coordinate_percentage']:.1f}%)")
            logger.info(f"  - {summary['region_count']} regions covered")

            if not summary['spatial_analysis_available']:
                logger.warning("  ⚠ Spatial analysis requires geopandas (optional)")

        return True


def main():
    """Example usage and testing."""
    downloader = HNPDDownloader()

    # Download data
    print("=" * 60)
    print("HNPD Downloader Test")
    print("=" * 60)

    success = downloader.download_and_prepare()

    if success:
        # Show summary
        summary = downloader.get_data_summary()
        print("\n" + "=" * 60)
        print("HNPD Data Summary")
        print("=" * 60)
        print(f"Total records: {summary['total_records']}")
        print(f"Tier 1 networks: {summary['tier_1_networks']}")
        print(f"Tier 2 networks: {summary['tier_2_networks']}")
        print(f"Regions: {summary['region_count']}")
        print(f"Coordinates available: {summary['coordinates_available']} ({summary['coordinate_percentage']:.1f}%)")
        print(f"Spatial analysis: {'Available' if summary['spatial_analysis_available'] else 'Not available (install geopandas)'}")

        # Show regions
        print("\nRegions covered:")
        for region in summary['regions'][:10]:
            print(f"  - {region}")
        if len(summary['regions']) > 10:
            print(f"  ... and {len(summary['regions']) - 10} more")

        # Load London networks if spatial available
        if SPATIAL_AVAILABLE:
            print("\n" + "=" * 60)
            print("London Heat Networks (Tier 1)")
            print("=" * 60)

            london_tier1 = downloader.get_tier_1_networks(region="London")
            if london_tier1 is not None and len(london_tier1) > 0:
                print(f"Found {len(london_tier1)} Tier 1 networks in London\n")
                display_cols = ['Site Name', 'Development Status', 'Post Code',
                              'Number of customer connections']
                available_cols = [c for c in display_cols if c in london_tier1.columns]
                print(london_tier1[available_cols].head(10).to_string(index=False))
            else:
                print("No Tier 1 networks found in London")

            print("\n" + "=" * 60)
            print("London Heat Networks (Tier 2)")
            print("=" * 60)

            london_tier2 = downloader.get_tier_2_networks(region="London")
            if london_tier2 is not None and len(london_tier2) > 0:
                print(f"Found {len(london_tier2)} Tier 2 networks in London\n")
                print(london_tier2[available_cols].head(10).to_string(index=False))
            else:
                print("No Tier 2 networks found in London")
    else:
        print("\n❌ Failed to download HNPD data")


if __name__ == "__main__":
    main()
