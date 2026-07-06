"""
London GIS Data Downloader

Downloads and manages GIS data from London Datastore, including:
- Heat load data (building-level demand) for all 33 boroughs
- Existing district heating networks
- Potential district heating networks
- Heat supply sources
- London Development Database
"""

import html
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Optional

from loguru import logger

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
EXTERNAL_DIR = DATA_DIR / "external"
GIS_DIR = EXTERNAL_DIR / "london_gis"


class _HrefExtractor(HTMLParser):
    """Collect anchor href values from a London Datastore HTML page."""

    def __init__(self):
        super().__init__()
        self.hrefs: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and value:
                self.hrefs.append(value)


class LondonGISDownloadError(RuntimeError):
    """Structured London GIS download failure."""

    def __init__(self, message: str, *, failure_kind: str):
        super().__init__(message)
        self.failure_kind = failure_kind


class LondonGISDownloader:
    """Downloads and manages London GIS data from London Datastore."""

    GIS_RESOURCE_PAGE_URL = "https://data.london.gov.uk/dataset/london-heat-map"
    GIS_RESOURCE_PAGE_CANDIDATES = (
        "https://data.london.gov.uk/dataset/london-heat-map",
        "https://data.london.gov.uk/dataset/london-heat-map/?resource=182a2cff-3b45-4805-a29b-4f183e17cb78",
        "https://data.london.gov.uk/dataset/london-heat-map/resource/18ef108d-fb08-4cb2-8643-4ec2c67105e5",
    )
    GIS_FALLBACK_DOWNLOAD_URLS = (
        "https://data.london.gov.uk/download/london-heat-map/1c75726b-0b5e-4f2c-9fd6-25fc83b32454/GIS_All_Data.zip",
    )
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    )

    def __init__(self):
        """Initialize the London GIS downloader."""
        logger.info("Initialized London GIS Downloader")
        self.last_error: Optional[LondonGISDownloadError] = None

        # Create directories if they don't exist
        EXTERNAL_DIR.mkdir(parents=True, exist_ok=True)
        GIS_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _is_gis_zip_url(url: str) -> bool:
        path = urllib.parse.urlparse(url).path
        return Path(path).name.casefold() == "gis_all_data.zip"

    @classmethod
    def _normalize_candidate_url(cls, candidate: str, *, base_url: str) -> str:
        normalized = html.unescape(candidate).replace("\\/", "/").strip()
        if normalized.startswith("//"):
            normalized = f"https:{normalized}"
        return urllib.parse.urljoin(base_url, normalized)

    @classmethod
    def _extract_download_url_from_html(cls, resource_page_html: str, *, base_url: str) -> str:
        extractor = _HrefExtractor()
        extractor.feed(resource_page_html)

        candidates = list(extractor.hrefs)
        candidates.extend(
            match.group(1)
            for match in re.finditer(
                r'["\']([^"\']*GIS_All_Data\.zip[^"\']*)["\']',
                resource_page_html,
                flags=re.IGNORECASE,
            )
        )

        for candidate in candidates:
            resolved = cls._normalize_candidate_url(candidate, base_url=base_url)
            if cls._is_gis_zip_url(resolved):
                return resolved

        raise LondonGISDownloadError(
            "Could not find a GIS_All_Data.zip download link on the London Datastore resource page.",
            failure_kind="download_link_parse",
        )

    @classmethod
    def _page_headers(cls, *, referer: Optional[str] = None) -> dict:
        return {
            "User-Agent": cls.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": referer or cls.GIS_RESOURCE_PAGE_URL,
            "Upgrade-Insecure-Requests": "1",
        }

    @classmethod
    def _download_headers(cls, *, referer: Optional[str] = None) -> dict:
        return {
            "User-Agent": cls.USER_AGENT,
            "Accept": "application/zip,application/octet-stream;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
            "Referer": referer or cls.GIS_RESOURCE_PAGE_URL,
        }

    def _fetch_resource_page_html(self, resource_page_url: str) -> str:
        try:
            ssl_context = ssl.create_default_context()
            request = urllib.request.Request(
                resource_page_url,
                headers=self._page_headers(referer=self.GIS_RESOURCE_PAGE_URL),
            )
            with urllib.request.urlopen(request, context=ssl_context, timeout=60) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            raise LondonGISDownloadError(
                f"Failed to fetch London Datastore resource page {resource_page_url}: "
                f"HTTP {e.code} {e.reason}",
                failure_kind="resource_page_fetch",
            ) from e
        except urllib.error.URLError as e:
            raise LondonGISDownloadError(
                f"Failed to fetch London Datastore resource page {resource_page_url}: {e.reason}",
                failure_kind="resource_page_fetch",
            ) from e
        except Exception as e:
            raise LondonGISDownloadError(
                f"Failed to fetch London Datastore resource page {resource_page_url}: {e}",
                failure_kind="resource_page_fetch",
            ) from e

    def _download_url_to_path(self, download_url: str, zip_path: Path) -> None:
        try:
            ssl_context = ssl.create_default_context()
            request = urllib.request.Request(
                download_url,
                headers=self._download_headers(referer=self.GIS_RESOURCE_PAGE_URL),
            )
            with urllib.request.urlopen(request, context=ssl_context, timeout=300) as response, open(zip_path, "wb") as output_file:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output_file.write(chunk)
        except urllib.error.HTTPError as e:
            raise LondonGISDownloadError(
                f"Failed to download GIS_All_Data.zip from {download_url}: "
                f"HTTP {e.code} {e.reason}",
                failure_kind="file_download",
            ) from e
        except urllib.error.URLError as e:
            raise LondonGISDownloadError(
                f"Failed to download GIS_All_Data.zip from {download_url}: {e.reason}",
                failure_kind="file_download",
            ) from e
        except Exception as e:
            raise LondonGISDownloadError(
                f"Failed to download GIS_All_Data.zip from {download_url}: {e}",
                failure_kind="file_download",
            ) from e

    def resolve_download_url(self) -> str:
        """Resolve the current GIS ZIP download URL from the London Datastore page."""
        last_error: Optional[LondonGISDownloadError] = None

        for resource_page_url in self.GIS_RESOURCE_PAGE_CANDIDATES:
            try:
                resource_page_html = self._fetch_resource_page_html(resource_page_url)
                return self._extract_download_url_from_html(
                    resource_page_html,
                    base_url=resource_page_url,
                )
            except LondonGISDownloadError as e:
                last_error = e
                logger.warning(f"Could not resolve GIS download URL from {resource_page_url}: {e}")

        if last_error is not None:
            raise last_error

        raise LondonGISDownloadError(
            "Could not resolve the London GIS download URL from the London Datastore resource pages.",
            failure_kind="download_link_parse",
        )

    def download_gis_data(self, force_redownload: bool = False) -> bool:
        """
        Download the complete GIS dataset from London Datastore.

        Args:
            force_redownload: If True, download even if data already exists

        Returns:
            True if successful, False otherwise
        """
        self.last_error = None
        zip_path = EXTERNAL_DIR / "GIS_All_Data.zip"

        # Check if already downloaded
        if zip_path.exists() and not force_redownload:
            logger.info(f"GIS data already downloaded: {zip_path}")
            return True

        resolution_error: Optional[LondonGISDownloadError] = None
        download_errors: List[LondonGISDownloadError] = []
        logger.info("Resolving London GIS data download URL from London Datastore...")

        try:
            download_candidates = [self.resolve_download_url()]
        except LondonGISDownloadError as e:
            resolution_error = e
            download_candidates = []
            logger.warning(
                "London GIS resource-page resolution failed; trying direct download fallback(s): {}",
                e,
            )

        for fallback_url in self.GIS_FALLBACK_DOWNLOAD_URLS:
            if fallback_url not in download_candidates:
                download_candidates.append(fallback_url)

        for download_url in download_candidates:
            try:
                self._download_url_to_path(download_url, zip_path)
                logger.info(f"Downloaded GIS data: {zip_path.stat().st_size / 1024 / 1024:.1f} MB")
                if resolution_error and download_url in self.GIS_FALLBACK_DOWNLOAD_URLS:
                    logger.info(f"Downloaded London GIS data via direct fallback URL: {download_url}")
                return True
            except LondonGISDownloadError as e:
                download_errors.append(e)
                logger.error(str(e))

        zip_path.unlink(missing_ok=True)
        if resolution_error is not None and download_errors:
            self.last_error = LondonGISDownloadError(
                f"{resolution_error} Fallback download attempts also failed: "
                + "; ".join(str(error) for error in download_errors),
                failure_kind=download_errors[-1].failure_kind,
            )
        elif download_errors:
            self.last_error = download_errors[-1]
        else:
            self.last_error = resolution_error or LondonGISDownloadError(
                "London GIS download failed for an unknown reason.",
                failure_kind="file_download",
            )
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
            self.last_error = LondonGISDownloadError(
                f"GIS zip file not found: {zip_path}",
                failure_kind="file_download",
            )
            logger.error(str(self.last_error))
            return False

        logger.info("Extracting GIS data...")

        try:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(EXTERNAL_DIR)

            logger.info(f"Extracted GIS data to: {extract_path}")
            return True

        except Exception as e:
            self.last_error = LondonGISDownloadError(
                f"Failed to extract London GIS ZIP {zip_path}: {e}",
                failure_kind="extract",
            )
            logger.error(str(self.last_error))
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
            borough_clean = borough.replace(" ", "_")
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
            "existing": network_dir / "2.3.1_Existing_DH_Networks.shp",
            "potential_transmission": network_dir / "2.3.2.1_Potential_DH_Transmission_Line.shp",
            "potential_networks": network_dir / "2.3.2.2._Potential_DH_Networks.shp",
            "potential_2005": network_dir / "2.3.2.3_Potential_Networks_2005_Study.shp",
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
            borough_clean = borough.replace(" ", "_")
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

        logger.info("London GIS data ready:")
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
                "available": False,
                "message": "GIS data not downloaded yet",
            }

        heat_loads = self.get_heat_load_files()
        networks = self.get_network_files()
        heat_supply = self.get_heat_supply_files()

        return {
            "available": True,
            "heat_load_files": len(heat_loads),
            "network_files": len(networks),
            "heat_supply_files": len(heat_supply),
            "networks": list(networks.keys()),
            "data_path": str(extract_path),
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
