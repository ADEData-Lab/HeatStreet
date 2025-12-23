"""
DESNZ Heat Network Planning Data Downloader

Downloads and manages heat network planning data from DESNZ for UK-wide
heat network analysis.
"""

import os
import subprocess
import zipfile
from pathlib import Path
from typing import Dict, List, Optional
from loguru import logger

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
EXTERNAL_DIR = DATA_DIR / "external"
GIS_DIR = EXTERNAL_DIR / "desnz_heat_network_planning"
DEFAULT_CSV_NAME = "hnpd-january-2024.csv"


class DESNZHeatNetworkDownloader:
    """Downloads and manages DESNZ heat network planning data."""

    DEFAULT_GIS_DATA_URL = (
        "https://assets.publishing.service.gov.uk/media/65c9f7b89c5b7f000c951cad/hnpd-january-2024.csv"
    )
    GIS_DATA_URL = os.getenv("DESNZ_HEAT_NETWORK_DATA_URL", DEFAULT_GIS_DATA_URL)
    CSV_DATA_PATH = os.getenv("DESNZ_HEAT_NETWORK_CSV_PATH")

    def __init__(self):
        """Initialize the DESNZ heat network data downloader."""
        logger.info("Initialized DESNZ Heat Network Data Downloader")

        EXTERNAL_DIR.mkdir(parents=True, exist_ok=True)
        GIS_DIR.mkdir(parents=True, exist_ok=True)

    def download_gis_data(self, force_redownload: bool = False) -> bool:
        """
        Download the DESNZ heat network planning dataset.

        Args:
            force_redownload: If True, download even if data already exists

        Returns:
            True if successful, False otherwise
        """
        if not self.GIS_DATA_URL:
            logger.warning(
                "DESNZ heat network data URL not configured. "
                "Set DESNZ_HEAT_NETWORK_DATA_URL or download manually into "
                "data/external/desnz_heat_network_planning."
            )
            return False

        is_csv_url = self.GIS_DATA_URL.lower().endswith(".csv")
        zip_path = EXTERNAL_DIR / "desnz_heat_network_planning.zip"
        csv_path = EXTERNAL_DIR / DEFAULT_CSV_NAME

        if is_csv_url and csv_path.exists() and not force_redownload:
            logger.info(f"DESNZ data already downloaded: {csv_path}")
            return True

        if zip_path.exists() and not force_redownload and not is_csv_url:
            logger.info(f"DESNZ data already downloaded: {zip_path}")
            return True

        logger.info("Downloading DESNZ heat network planning data...")
        logger.info(f"URL: {self.GIS_DATA_URL}")

        try:
            output_path = csv_path if is_csv_url else zip_path
            cmd = [
                "wget",
                "--no-check-certificate",
                "--progress=bar:force",
                "-O",
                str(output_path),
                self.GIS_DATA_URL,
            ]

            result = subprocess.run(cmd, capture_output=False, text=True)

            if result.returncode == 0:
                logger.info(
                    f"✓ Downloaded DESNZ data: {output_path.stat().st_size / 1024 / 1024:.1f} MB"
                )
                return True
            logger.error(f"Download failed with exit code {result.returncode}")
            return False

        except Exception as exc:
            logger.error(f"Error downloading DESNZ data: {exc}")
            return False

    def extract_gis_data(self, force_extract: bool = False) -> bool:
        """
        Extract the DESNZ data zip file.

        Args:
            force_extract: If True, extract even if already extracted

        Returns:
            True if successful, False otherwise
        """
        zip_path = EXTERNAL_DIR / "desnz_heat_network_planning.zip"
        extract_path = GIS_DIR

        if extract_path.exists() and any(extract_path.iterdir()) and not force_extract:
            logger.info(f"DESNZ data already extracted: {extract_path}")
            return True

        if not zip_path.exists():
            logger.error(f"Zip file not found: {zip_path}")
            return False

        logger.info("Extracting DESNZ heat network planning data...")

        try:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(GIS_DIR)

            logger.info(f"✓ Extracted DESNZ data to: {extract_path}")
            return True

        except Exception as exc:
            logger.error(f"Error extracting DESNZ data: {exc}")
            return False

    def _find_first_layer(self, directory: Path) -> Optional[Path]:
        """Find the first supported GIS layer in a directory."""
        if not directory.exists():
            return None
        for extension in ("*.gpkg", "*.geojson", "*.shp"):
            matches = sorted(directory.glob(extension))
            if matches:
                return matches[0]
        return None

    def get_network_files(self) -> Dict[str, Path]:
        """
        Get paths to heat network layers.

        Returns:
            Dictionary with keys for network layers.
        """
        networks_dir = GIS_DIR / "networks"
        zones_dir = GIS_DIR / "zones"

        network_layer = self._find_first_layer(networks_dir)
        zone_layer = self._find_first_layer(zones_dir)

        files = {}
        if network_layer:
            files["existing"] = network_layer
        if zone_layer:
            files["zones"] = zone_layer

        return files

    def get_csv_network_path(self, csv_path: Optional[Path] = None) -> Optional[Path]:
        """
        Get the CSV fallback path for heat network data.

        Args:
            csv_path: Optional explicit CSV path to use.

        Returns:
            Path to CSV file if present, otherwise None.
        """
        candidate_path = None
        if csv_path:
            candidate_path = csv_path
        elif self.CSV_DATA_PATH:
            candidate_path = Path(self.CSV_DATA_PATH)
        else:
            candidate_path = EXTERNAL_DIR / DEFAULT_CSV_NAME

        if candidate_path and candidate_path.exists():
            return candidate_path
        return None

    def download_and_prepare(self, force_redownload: bool = False) -> bool:
        """
        Complete workflow: download and extract DESNZ data.

        Args:
            force_redownload: If True, download even if data already exists

        Returns:
            True if successful, False otherwise
        """
        if not self.download_gis_data(force_redownload=force_redownload):
            return False

        if self.GIS_DATA_URL.lower().endswith(".csv"):
            logger.info("✓ DESNZ CSV download ready (no extraction needed)")
            return True

        if not self.extract_gis_data(force_extract=force_redownload):
            return False

        networks = self.get_network_files()

        logger.info("✓ DESNZ heat network data ready:")
        logger.info(f"  - {len(networks)} network layers")

        return True

    def get_data_summary(self) -> dict:
        """
        Get summary of available DESNZ data.

        Returns:
            Dictionary with data summary
        """
        csv_path = self.get_csv_network_path()
        if not GIS_DIR.exists() or not any(GIS_DIR.iterdir()):
            return {
                "available": False,
                "csv_available": csv_path is not None,
                "csv_path": str(csv_path) if csv_path else None,
                "message": "DESNZ data not downloaded yet",
            }

        networks = self.get_network_files()

        return {
            "available": True,
            "network_files": len(networks),
            "networks": list(networks.keys()),
            "data_path": str(GIS_DIR),
            "csv_available": csv_path is not None,
            "csv_path": str(csv_path) if csv_path else None,
        }


def main():
    """Example usage."""
    downloader = DESNZHeatNetworkDownloader()
    success = downloader.download_and_prepare()

    if success:
        summary = downloader.get_data_summary()
        print("\nDESNZ Data Summary:")
        print(f"  Available: {summary['available']}")
        print(f"  Network files: {summary['network_files']}")
        print(f"  Networks: {', '.join(summary['networks'])}")


if __name__ == "__main__":
    main()
