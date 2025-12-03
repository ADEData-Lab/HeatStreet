"""
London GIS Data Downloader

Downloads and manages GIS data from London Datastore, including:
- Heat load data (building-level demand) for all 33 boroughs
- Existing district heating networks
- Potential district heating networks
- Heat supply sources
- London Development Database

Author: Heat Street EPC Analysis
Date: 2025-12-03
"""

import os
import subprocess
import zipfile
from pathlib import Path
from typing import Optional, List
from loguru import logger

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
EXTERNAL_DIR = DATA_DIR / "external"
GIS_DIR = EXTERNAL_DIR / "london_gis"


class LondonGISDownloader:
    """Downloads and manages London GIS data from London Datastore."""

    # London Datastore URL for the complete GIS dataset
    GIS_DATA_URL = "https://data.london.gov.uk/download/2ogw5/1c75726b-0b5e-4f2c-9fd6-25fc83b32454/GIS_All_Data.zip"

    def __init__(self):
        """Initialize the London GIS downloader."""
        logger.info("Initialized London GIS Downloader")

        # Create directories if they don't exist
        EXTERNAL_DIR.mkdir(parents=True, exist_ok=True)
        GIS_DIR.mkdir(parents=True, exist_ok=True)

    def download_gis_data(self, force_redownload: bool = False) -> bool:
        """
        Download the complete GIS dataset from London Datastore.

        Args:
            force_redownload: If True, download even if data already exists

        Returns:
            True if successful, False otherwise
        """
        zip_path = EXTERNAL_DIR / "GIS_All_Data.zip"

        # Check if already downloaded
        if zip_path.exists() and not force_redownload:
            logger.info(f"GIS data already downloaded: {zip_path}")
            return True

        logger.info(f"Downloading London GIS data from London Datastore...")
        logger.info(f"URL: {self.GIS_DATA_URL}")

        try:
            # Use wget with --no-check-certificate to handle SSL issues
            cmd = [
                'wget',
                '--no-check-certificate',
                '--progress=bar:force',
                '-O', str(zip_path),
                self.GIS_DATA_URL
            ]

            result = subprocess.run(cmd, capture_output=False, text=True)

            if result.returncode == 0:
                logger.info(f"✓ Downloaded GIS data: {zip_path.stat().st_size / 1024 / 1024:.1f} MB")
                return True
            else:
                logger.error(f"Download failed with exit code {result.returncode}")
                return False

        except Exception as e:
            logger.error(f"Error downloading GIS data: {e}")
            return False

    def extract_gis_data(self, force_extract: bool = False) -> bool:
        """
        Extract the GIS data zip file.

        Args:
            force_extract: If True, extract even if already extracted

        Returns:
            True if successful, False otherwise
        """
        zip_path = EXTERNAL_DIR / "GIS_All_Data.zip"
        extract_path = EXTERNAL_DIR / "GIS_All_Data"

        # Check if already extracted
        if extract_path.exists() and not force_extract:
            logger.info(f"GIS data already extracted: {extract_path}")
            return True

        if not zip_path.exists():
            logger.error(f"Zip file not found: {zip_path}")
            return False

        logger.info(f"Extracting GIS data...")

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(EXTERNAL_DIR)

            logger.info(f"✓ Extracted GIS data to: {extract_path}")
            return True

        except Exception as e:
            logger.error(f"Error extracting GIS data: {e}")
            return False

    def get_heat_load_files(self, borough: Optional[str] = None) -> List[Path]:
        """
        Get paths to heat load shapefiles.

        Args:
            borough: Optional borough name to filter by

        Returns:
            List of shapefile paths
        """
        heat_load_dir = EXTERNAL_DIR / "GIS_All_Data" / "Heat Loads"

        if not heat_load_dir.exists():
            logger.warning(f"Heat load directory not found: {heat_load_dir}")
            return []

        # Get all shapefiles
        shapefiles = list(heat_load_dir.glob("*.shp"))

        # Filter by borough if specified
        if borough:
            borough_clean = borough.replace(' ', '_')
            shapefiles = [f for f in shapefiles if borough_clean in f.name]

        return shapefiles

    def get_network_files(self) -> dict:
        """
        Get paths to district heating network shapefiles.

        Returns:
            Dictionary with network types as keys and file paths as values
        """
        network_dir = EXTERNAL_DIR / "GIS_All_Data" / "Networks"

        if not network_dir.exists():
            logger.warning(f"Network directory not found: {network_dir}")
            return {}

        networks = {
            'existing': network_dir / "2.3.1_Existing_DH_Networks.shp",
            'potential_transmission': network_dir / "2.3.2.1_Potential_DH_Transmission_Line.shp",
            'potential_networks': network_dir / "2.3.2.2._Potential_DH_Networks.shp",
            'potential_2005': network_dir / "2.3.2.3_Potential_Networks_2005_Study.shp"
        }

        # Only return files that exist
        return {k: v for k, v in networks.items() if v.exists()}

    def get_heat_supply_files(self, borough: Optional[str] = None) -> List[Path]:
        """
        Get paths to heat supply shapefiles.

        Args:
            borough: Optional borough name to filter by

        Returns:
            List of shapefile paths
        """
        heat_supply_dir = EXTERNAL_DIR / "GIS_All_Data" / "Heat Supply"

        if not heat_supply_dir.exists():
            logger.warning(f"Heat supply directory not found: {heat_supply_dir}")
            return []

        # Get all shapefiles
        shapefiles = list(heat_supply_dir.glob("*.shp"))

        # Filter by borough if specified
        if borough:
            borough_clean = borough.replace(' ', '_')
            shapefiles = [f for f in shapefiles if borough_clean in f.name]

        return shapefiles

    def download_and_prepare(self, force_redownload: bool = False) -> bool:
        """
        Complete workflow: download and extract GIS data.

        Args:
            force_redownload: If True, download even if data already exists

        Returns:
            True if successful, False otherwise
        """
        # Download
        if not self.download_gis_data(force_redownload=force_redownload):
            return False

        # Extract
        if not self.extract_gis_data(force_extract=force_redownload):
            return False

        # Report what's available
        heat_loads = self.get_heat_load_files()
        networks = self.get_network_files()
        heat_supply = self.get_heat_supply_files()

        logger.info("✓ London GIS data ready:")
        logger.info(f"  - {len(heat_loads)} heat load files (by borough)")
        logger.info(f"  - {len(networks)} district heating network files")
        logger.info(f"  - {len(heat_supply)} heat supply files")

        return True

    def get_data_summary(self) -> dict:
        """
        Get summary of available GIS data.

        Returns:
            Dictionary with data summary
        """
        extract_path = EXTERNAL_DIR / "GIS_All_Data"

        if not extract_path.exists():
            return {
                'available': False,
                'message': 'GIS data not downloaded yet'
            }

        heat_loads = self.get_heat_load_files()
        networks = self.get_network_files()
        heat_supply = self.get_heat_supply_files()

        return {
            'available': True,
            'heat_load_files': len(heat_loads),
            'network_files': len(networks),
            'heat_supply_files': len(heat_supply),
            'networks': list(networks.keys()),
            'data_path': str(extract_path)
        }


def main():
    """Example usage."""
    downloader = LondonGISDownloader()

    # Download and prepare data
    success = downloader.download_and_prepare()

    if success:
        # Show summary
        summary = downloader.get_data_summary()
        print("\nGIS Data Summary:")
        print(f"  Available: {summary['available']}")
        print(f"  Heat load files: {summary['heat_load_files']}")
        print(f"  Network files: {summary['network_files']}")
        print(f"  Heat supply files: {summary['heat_supply_files']}")
        print(f"  Networks: {', '.join(summary['networks'])}")

        # Show network file paths
        networks = downloader.get_network_files()
        print("\nDistrict Heating Network Files:")
        for name, path in networks.items():
            print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
