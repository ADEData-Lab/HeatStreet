"""Validate and load the manually supplied Heat Network Planning Database CSV."""

from __future__ import annotations

import csv
import hashlib
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

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
    """Validate the local HNPD CSV and expose Tier 1 and Tier 2 scheme points.

    The current government publication is downloaded manually because the asset URL
    and filename change between quarterly releases. HeatStreet deliberately does not
    download a historic fallback when the configured file is absent.
    """

    DEFAULT_FILENAME = "heat_networks_procurement_pipeline_Q1_2026.csv"
    DOWNLOAD_PAGE = "https://www.gov.uk/government/publications/heat-networks-pipelines"
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
        "Ref ID",
        "Site Name",
        "Region",
        "Development Status",
        "Development Status (short)",
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
        self.filename = str(hnpd_cfg.get("filename") or self.DEFAULT_FILENAME)
        self.download_page = str(hnpd_cfg.get("download_page") or self.DOWNLOAD_PAGE)
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
        logger.info(f"Initialized HNPD loader ({self.csv_path})")

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

    def manual_download_instructions(self) -> str:
        return (
            "HeatStreet requires the current Heat Networks Planning Database CSV. "
            f"Download it manually from {self.download_page} and save it as "
            f"{self.csv_path}. Do not rename a different quarterly release to this "
            "filename without updating config/config.yaml and validating its schema."
        )

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
            return {
                "valid": False,
                "reason": self.manual_download_instructions(),
                "csv_path": str(self.csv_path),
            }
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

        valid_coordinates = 0
        london_rows = 0
        london_valid_coordinates = 0
        for row in rows:
            is_london = self._normalise(self._field(row, "Region")) == "london"
            if is_london:
                london_rows += 1
            x = self._coordinate(self._field(row, "X-coordinate"))
            y = self._coordinate(self._field(row, "Y-coordinate"))
            if x is not None and y is not None and self._plausible_bng(x, y):
                valid_coordinates += 1
                if is_london:
                    london_valid_coordinates += 1

        if valid_coordinates == 0:
            return {
                "valid": False,
                "reason": "HNPD CSV contains no valid British National Grid coordinates",
                "rows": len(rows),
            }
        if self._normalise(self.default_region_filter) == "london" and london_valid_coordinates == 0:
            return {
                "valid": False,
                "reason": "HNPD CSV contains no valid London rows with British National Grid coordinates",
                "rows": len(rows),
            }

        digest = hashlib.sha256(self.csv_path.read_bytes()).hexdigest()
        return {
            "valid": True,
            "reason": "ok",
            "rows": len(rows),
            "coordinates_available": valid_coordinates,
            "london_rows": london_rows,
            "london_coordinates_available": london_valid_coordinates,
            "sha256": digest,
            "size_bytes": self.csv_path.stat().st_size,
            "filename": self.csv_path.name,
        }

    def download_hnpd(self, force_redownload: bool = False) -> bool:
        """Compatibility entry point. HNPD must now be downloaded manually."""
        validation = self.validate_hnpd_file()
        if validation.get("valid"):
            logger.info(f"HNPD file is present and valid: {self.csv_path}")
            return True
        logger.error(validation["reason"])
        return False

    def download_and_prepare(self, force_redownload: bool = False) -> bool:
        return self.download_hnpd(force_redownload=force_redownload)

    def require_local_file(self) -> Dict[str, Any]:
        validation = self.validate_hnpd_file()
        if not validation.get("valid"):
            raise FileNotFoundError(validation["reason"])
        logger.info(
            f"Validated HNPD input: {validation['rows']:,} rows, "
            f"{validation['london_rows']:,} London rows, "
            f"{validation['london_coordinates_available']:,} London coordinate pairs, "
            f"SHA-256 {validation['sha256']}"
        )
        return validation

    def load_hnpd_csv(self, region_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        self.require_local_file()
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
                raise RuntimeError(
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
            raise RuntimeError("GeoDataFrame conversion requires geopandas")
        rows = self.load_hnpd_csv(region_filter=region_filter)
        if status_filter:
            allowed = {self._normalise(value) for value in status_filter}
            available_statuses = Counter(self._status(row).strip() for row in rows)
            rows = [row for row in rows if self._normalise(self._status(row)) in allowed]
            logger.info(f"Filtered to statuses {list(status_filter)}: {len(rows):,} records")
            if not rows:
                raise RuntimeError(
                    "No HNPD rows matched the configured status filter; "
                    f"statuses present after region filtering: {dict(available_statuses)}"
                )

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
            raise RuntimeError("Matching HNPD rows contain no valid British National Grid coordinates")

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
                "download_page": self.download_page,
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
            "region_counts": {region_names[key]: count for key, count in region_counts.items()},
            "csv_path": str(self.csv_path),
            "download_page": self.download_page,
            "spatial_analysis_available": SPATIAL_AVAILABLE,
            "validation": validation,
        }


def main() -> None:
    downloader = HNPDDownloader()
    downloader.require_local_file()
    print(downloader.get_data_summary())


if __name__ == "__main__":
    main()
