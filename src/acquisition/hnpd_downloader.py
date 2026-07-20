"""Download, validate, and load Heat Network Planning Database data."""

from __future__ import annotations

import csv
import ssl
import subprocess
import sys
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import urlparse

from loguru import logger

try:
    import geopandas as gpd
    from shapely.geometry import Point

    SPATIAL_AVAILABLE = True
except ImportError:
    SPATIAL_AVAILABLE = False
    logger.warning("geopandas not available - spatial analysis disabled")


PROJECT_ROOT = Path(__file__).parent.parent.parent
EXTERNAL_DIR = PROJECT_ROOT / "data" / "external"


class HNPDDownloader:
    """Manage the HNPD CSV and expose Tier 1 and Tier 2 scheme points."""

    HNPD_URL = (
        "https://assets.publishing.service.gov.uk/media/"
        "65c9f7b89c5b7f000c951cad/hnpd-january-2024.csv"
    )
    DEFAULT_FILENAME = "hnpd-january-2024.csv"
    TIER_1_STATUSES = (
        "Operational",
        "Under Construction",
        "No Application Required",
        "No Application Made",
    )
    TIER_2_STATUSES = (
        "Planning Permission Granted",
        "Appeal Granted",
        "Secretary of State - Granted",
    )
    REQUIRED_COLUMNS = (
        "Region",
        "Development Status",
        "X-coordinate",
        "Y-coordinate",
    )

    def __init__(
        self,
        config: Optional[Mapping[str, Any]] = None,
        *,
        external_dir: Optional[Path] = None,
    ) -> None:
        if config is None:
            try:
                from config.config import load_config

                config = load_config()
            except Exception as exc:
                logger.debug(f"Using default HNPD configuration: {exc}")
                config = {}

        hnpd_cfg = (
            (config or {})
            .get("data_sources", {})
            .get("heat_networks", {})
            .get("hnpd", {})
        )
        self.url = str(hnpd_cfg.get("url") or self.HNPD_URL)
        self.filename = str(
            hnpd_cfg.get("filename")
            or Path(urlparse(self.url).path).name
            or self.DEFAULT_FILENAME
        )
        self.external_dir = Path(external_dir or EXTERNAL_DIR)
        self.csv_path = self.external_dir / self.filename
        self.default_region_filter = hnpd_cfg.get("region_filter")
        self.tier_1_statuses = self._merge_statuses(
            hnpd_cfg.get("tier_1_statuses") or (), self.TIER_1_STATUSES
        )
        self.tier_2_statuses = self._merge_statuses(
            hnpd_cfg.get("tier_2_statuses") or (), self.TIER_2_STATUSES
        )
        self.external_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Initialized HNPD Downloader ({self.csv_path})")

    @staticmethod
    def _normalise(value: Any) -> str:
        text = str(value or "").replace("\ufeff", "").replace("\xa0", " ")
        return " ".join(text.split()).casefold()

    @classmethod
    def _merge_statuses(
        cls, configured: Sequence[str], defaults: Sequence[str]
    ) -> List[str]:
        result: List[str] = []
        seen = set()
        for status in [*configured, *defaults]:
            key = cls._normalise(status)
            if key and key not in seen:
                result.append(str(status).strip())
                seen.add(key)
        return result

    @classmethod
    def _clean_row(cls, row: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            " ".join(str(key or "").replace("\ufeff", "").split()): value
            for key, value in row.items()
            if key is not None
        }

    @classmethod
    def _field(cls, row: Mapping[str, Any], name: str) -> Any:
        target = cls._normalise(name)
        for key, value in row.items():
            if cls._normalise(key) == target:
                return value
        return None

    @classmethod
    def _status(cls, row: Mapping[str, Any]) -> str:
        detailed = cls._field(row, "Development Status")
        if cls._normalise(detailed) not in {"", "not set", "none", "nan"}:
            return str(detailed)
        return str(cls._field(row, "Development Status (short)") or "")

    @classmethod
    def _coordinate(cls, value: Any) -> Optional[float]:
        text = str(value or "").strip().replace(",", "")
        if cls._normalise(text) in {"", "not set", "none", "nan", "n/a"}:
            return None
        try:
            return float(text)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _plausible_bng(x: float, y: float) -> bool:
        return 0 <= x <= 700_000 and 0 <= y <= 1_300_000

    def _read_rows(self) -> List[Dict[str, Any]]:
        if not self.csv_path.exists():
            return []
        last_decode_error: Optional[Exception] = None
        for encoding in ("utf-8-sig", "latin-1"):
            try:
                with self.csv_path.open("r", encoding=encoding, newline="") as stream:
                    reader = csv.DictReader(stream)
                    if reader.fieldnames is None:
                        return []
                    return [self._clean_row(row) for row in reader]
            except UnicodeDecodeError as exc:
                last_decode_error = exc
        if last_decode_error:
            raise last_decode_error
        return []

    def validate_hnpd_file(self) -> Dict[str, Any]:
        if not self.csv_path.exists():
            return {"valid": False, "reason": f"HNPD CSV not found: {self.csv_path}"}
        try:
            rows = self._read_rows()
        except Exception as exc:
            return {"valid": False, "reason": f"HNPD CSV could not be parsed: {exc}"}
        if not rows:
            return {"valid": False, "reason": "HNPD CSV contains no data rows"}

        available_headers = {self._normalise(key) for key in rows[0]}
        missing = [
            name for name in self.REQUIRED_COLUMNS
            if self._normalise(name) not in available_headers
        ]
        if missing:
            return {
                "valid": False,
                "reason": f"HNPD CSV is missing required columns: {missing}",
                "rows": len(rows),
            }

        coordinates = 0
        for row in rows:
            x = self._coordinate(self._field(row, "X-coordinate"))
            y = self._coordinate(self._field(row, "Y-coordinate"))
            if x is not None and y is not None and self._plausible_bng(x, y):
                coordinates += 1
        if coordinates == 0:
            return {
                "valid": False,
                "reason": "HNPD CSV contains no valid British National Grid coordinates",
                "rows": len(rows),
            }
        return {
            "valid": True,
            "reason": "ok",
            "rows": len(rows),
            "coordinates_available": coordinates,
        }

    def download_hnpd(self, force_redownload: bool = False) -> bool:
        if self.csv_path.exists() and not force_redownload:
            validation = self.validate_hnpd_file()
            if validation.get("valid"):
                logger.info(f"HNPD data already downloaded and valid: {self.csv_path}")
                return True
            logger.warning(
                f"Existing HNPD file is invalid and will be replaced: {validation['reason']}"
            )

        temp_path = self.csv_path.with_suffix(self.csv_path.suffix + ".part")
        temp_path.unlink(missing_ok=True)
        logger.info(f"Downloading HNPD from {self.url}")
        try:
            try:
                context = ssl.create_default_context()
                try:
                    import certifi  # type: ignore

                    context = ssl.create_default_context(cafile=certifi.where())
                except Exception:
                    pass
                with urllib.request.urlopen(self.url, context=context) as response:
                    with temp_path.open("wb") as stream:
                        while chunk := response.read(1024 * 1024):
                            stream.write(chunk)
            except Exception as exc:
                logger.warning(f"Python download failed ({exc}); trying system tools")
                if not self._system_download(temp_path):
                    return False

            if not temp_path.exists() or temp_path.stat().st_size == 0:
                logger.error("HNPD download produced an empty file")
                return False

            original_path = self.csv_path
            self.csv_path = temp_path
            validation = self.validate_hnpd_file()
            self.csv_path = original_path
            if not validation.get("valid"):
                logger.error(f"Downloaded HNPD failed validation: {validation['reason']}")
                return False
            temp_path.replace(original_path)
            logger.info(
                f"Downloaded and validated {validation['rows']:,} HNPD records, "
                f"including {validation['coordinates_available']:,} with coordinates"
            )
            return True
        except Exception as exc:
            logger.error(f"Error downloading HNPD: {exc}")
            return False
        finally:
            self.csv_path = self.external_dir / self.filename
            temp_path.unlink(missing_ok=True)

    def _system_download(self, output_path: Path) -> bool:
        commands = [
            ["curl", "-L", "--fail", "-o", str(output_path), self.url],
            ["wget", "--no-check-certificate", "-O", str(output_path), self.url],
        ]
        if sys.platform.startswith("win"):
            commands.append([
                "powershell", "-NoProfile", "-Command",
                f"Invoke-WebRequest -Uri '{self.url}' -OutFile '{output_path}'",
            ])
        for command in commands:
            try:
                result = subprocess.run(command, capture_output=True, text=True)
            except FileNotFoundError:
                continue
            if result.returncode == 0 and output_path.exists() and output_path.stat().st_size:
                return True
            logger.debug(result.stderr.strip() or result.stdout.strip())
        logger.error("HNPD download failed using urllib and available system tools")
        return False

    def load_hnpd_csv(self, region_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        validation = self.validate_hnpd_file()
        if not validation.get("valid"):
            logger.error(validation["reason"])
            return []
        rows = self._read_rows()
        logger.info(f"Loaded HNPD: {len(rows):,} total records")
        if region_filter:
            target = self._normalise(region_filter)
            rows = [
                row for row in rows
                if self._normalise(self._field(row, "Region")) == target
            ]
            logger.info(f"Filtered to {region_filter}: {len(rows):,} records")
            if not rows:
                logger.error(
                    f"No HNPD rows matched region {region_filter!r}; "
                    f"available regions are {self.get_data_summary().get('regions', [])}"
                )
        return rows

    def load_hnpd_as_geodataframe(
        self,
        region_filter: Optional[str] = None,
        status_filter: Optional[Sequence[str]] = None,
    ) -> Optional["gpd.GeoDataFrame"]:
        if not SPATIAL_AVAILABLE:
            logger.error("GeoDataFrame conversion requires geopandas")
            return None
        rows = self.load_hnpd_csv(region_filter=region_filter)
        if not rows:
            return None

        if status_filter:
            allowed = {self._normalise(value) for value in status_filter}
            available_statuses = Counter(self._status(row).strip() for row in rows)
            rows = [row for row in rows if self._normalise(self._status(row)) in allowed]
            logger.info(f"Filtered to statuses {list(status_filter)}: {len(rows):,} records")
            if not rows:
                logger.error(
                    "No HNPD rows matched the configured status filter; "
                    f"statuses present after region filtering: {dict(available_statuses)}"
                )
                return None

        geometries = []
        valid_rows = []
        invalid_coordinates = 0
        for row in rows:
            x = self._coordinate(self._field(row, "X-coordinate"))
            y = self._coordinate(self._field(row, "Y-coordinate"))
            if x is None or y is None or not self._plausible_bng(x, y):
                invalid_coordinates += 1
                continue
            geometries.append(Point(x, y))
            valid_rows.append(row)
        if not valid_rows:
            logger.error("Matching HNPD rows contain no valid British National Grid coordinates")
            return None

        gdf = gpd.GeoDataFrame(valid_rows, geometry=geometries, crs="EPSG:27700")
        bounds = tuple(round(value) for value in gdf.total_bounds)
        logger.info(
            f"Created HNPD GeoDataFrame with {len(gdf):,} schemes; "
            f"discarded {invalid_coordinates:,}; bounds={bounds}"
        )
        return gdf

    def get_tier_1_networks(self, region: Optional[str] = None):
        return self.load_hnpd_as_geodataframe(region, self.tier_1_statuses)

    def get_tier_2_networks(self, region: Optional[str] = None):
        return self.load_hnpd_as_geodataframe(region, self.tier_2_statuses)

    def get_data_summary(self) -> Dict[str, Any]:
        validation = self.validate_hnpd_file()
        if not validation.get("valid"):
            return {
                "available": False,
                "message": validation["reason"],
                "csv_path": str(self.csv_path),
                "validation": validation,
            }
        rows = self._read_rows()
        tier_1 = {self._normalise(value) for value in self.tier_1_statuses}
        tier_2 = {self._normalise(value) for value in self.tier_2_statuses}
        region_names: Dict[str, str] = {}
        region_counts: Counter[str] = Counter()
        for row in rows:
            raw_region = str(self._field(row, "Region") or "").strip()
            key = self._normalise(raw_region)
            if key:
                region_names.setdefault(key, raw_region)
                region_counts[key] += 1
        return {
            "available": True,
            "total_records": len(rows),
            "tier_1_networks": sum(self._normalise(self._status(row)) in tier_1 for row in rows),
            "tier_2_networks": sum(self._normalise(self._status(row)) in tier_2 for row in rows),
            "coordinates_available": validation["coordinates_available"],
            "coordinate_percentage": validation["coordinates_available"] / len(rows) * 100,
            "regions": sorted(region_names.values(), key=str.casefold),
            "region_count": len(region_names),
            "region_counts": {
                region_names[key]: count for key, count in region_counts.items()
            },
            "csv_path": str(self.csv_path),
            "source_url": self.url,
            "spatial_analysis_available": SPATIAL_AVAILABLE,
            "validation": validation,
        }

    def download_and_prepare(self, force_redownload: bool = False) -> bool:
        if not self.download_hnpd(force_redownload=force_redownload):
            return False
        summary = self.get_data_summary()
        if not summary.get("available"):
            logger.error(summary.get("message", "HNPD input unavailable"))
            return False
        logger.info(
            f"HNPD ready: {summary['total_records']:,} records, "
            f"{summary['tier_1_networks']:,} Tier 1 sources, "
            f"{summary['tier_2_networks']:,} Tier 2 sources, "
            f"{summary['coordinates_available']:,} coordinate pairs"
        )
        if summary["tier_1_networks"] + summary["tier_2_networks"] == 0:
            logger.error("HNPD has no records matching the configured Tier 1 or Tier 2 statuses")
            return False
        return True


def main() -> None:
    downloader = HNPDDownloader()
    if not downloader.download_and_prepare():
        raise SystemExit(1)
    print(downloader.get_data_summary())


if __name__ == "__main__":
    main()
