"""
EPC API Data Acquisition Module

Downloads EPC data from the Energy Certificate Data API.
Supports both interactive borough search downloads and bulk full-load downloads.
"""

import csv
from dataclasses import dataclass
import io
import json
import os
import ssl
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import date as date_cls, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import pandas as pd
from dotenv import load_dotenv
from loguru import logger
from tqdm import tqdm

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import DATA_RAW_DIR, get_property_filters, load_config
from src.utils.staged_dataset import (
    DatasetReference,
    copy_parquet_to_csv,
    copy_query_to_parquet,
    create_attempt_directory,
    parquet_dataset_exists,
    parquet_columns,
    parquet_row_count,
    parquet_source_literal,
    require_duckdb,
    sql_identifier,
    sql_literal,
    write_dataset_manifest,
    write_parquet_part,
)

load_dotenv()


class _ManualRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Disable automatic redirects so download auth can be stripped explicitly."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class EPCRequestContext:
    """Structured context for a borough-scoped EPC API request."""

    borough_name: str
    property_type: str
    sample_start_date: Optional[date_cls]
    sample_end_date: Optional[date_cls]
    request_mode: str

    @property
    def sample_window(self) -> str:
        start = self.sample_start_date.isoformat() if self.sample_start_date else "open"
        end = self.sample_end_date.isoformat() if self.sample_end_date else "open"
        return f"{start} to {end}"

    def describe(self) -> str:
        return (
            f"borough='{self.borough_name}', "
            f"property_type='{self.property_type}', "
            f"sample_window='{self.sample_window}', "
            f"request_mode='{self.request_mode}'"
        )


class EPCDownloadError(RuntimeError):
    """Structured EPC acquisition failure with borough-scoped request context."""

    def __init__(
        self,
        message: str,
        *,
        context: EPCRequestContext,
        failure_kind: str,
        http_status: Optional[int] = None,
    ):
        super().__init__(message)
        self.context = context
        self.failure_kind = failure_kind
        self.http_status = http_status
        self.borough_name = context.borough_name
        self.property_type = context.property_type
        self.sample_start_date = context.sample_start_date
        self.sample_end_date = context.sample_end_date
        self.request_mode = context.request_mode

    @staticmethod
    def _http_error_detail(error: urllib.error.HTTPError) -> str:
        parts = []
        if error.reason:
            parts.append(str(error.reason))
        try:
            body = error.read().decode("utf-8", errors="replace").strip()
        except Exception:
            body = ""
        if body:
            compact_body = " ".join(body.split())
            if len(compact_body) > 240:
                compact_body = compact_body[:237] + "..."
            parts.append(f"api_response={compact_body}")
        return "; ".join(parts)

    @classmethod
    def from_http_error(cls, context: EPCRequestContext, error: urllib.error.HTTPError):
        status_text = f"HTTP {error.code}"
        if error.reason:
            status_text = f"{status_text} {error.reason}"
        message = (
            f"EPC API response failure for {context.describe()} "
            f"(status={status_text})"
        )
        detail = cls._http_error_detail(error)
        if detail:
            message = f"{message}: {detail}"
        return cls(
            message,
            context=context,
            failure_kind="api_response",
            http_status=error.code,
        )

    @classmethod
    def from_url_error(cls, context: EPCRequestContext, error: urllib.error.URLError):
        reason = error.reason if getattr(error, "reason", None) else error
        message = (
            f"Network error while contacting the EPC API for {context.describe()}: "
            f"{reason}"
        )
        return cls(
            message,
            context=context,
            failure_kind="network_error",
        )

    @classmethod
    def empty_response(
        cls,
        context: EPCRequestContext,
        *,
        detail: str = "EPC API returned an empty response body.",
    ):
        message = f"{detail} Context: {context.describe()}"
        return cls(
            message,
            context=context,
            failure_kind="empty_response",
        )

    @classmethod
    def unexpected(cls, context: EPCRequestContext, error: Exception):
        message = f"Unexpected EPC download failure for {context.describe()}: {error}"
        return cls(
            message,
            context=context,
            failure_kind="unexpected",
        )


class EPCStockDefinitionError(ValueError):
    """Raised when EPC data cannot support the configured stock definition."""


class EPCAPIDownloader:
    """Download EPC data from the Energy Certificate Data API."""

    BASE_URL = "https://api.get-energy-performance-data.communities.gov.uk"
    API_HOST = urllib.parse.urlparse(BASE_URL).netloc.casefold()
    SEARCH_URL = f"{BASE_URL}/api/domestic/search"
    FULL_LOAD_URL = f"{BASE_URL}/api/files/domestic/csv"
    DEFAULT_PAGE_SIZE = 5000
    FULL_LOAD_CHUNK_SIZE = 100_000
    REDIRECT_STATUS_CODES = (301, 302, 303, 307, 308)
    MAX_DOWNLOAD_REDIRECTS = 10
    STOCK_DEFINITION_COLUMNS = (
        "PROPERTY_TYPE",
        "BUILT_FORM",
        "CONSTRUCTION_AGE_BAND",
    )
    TERRACE_FORMS = (
        "Mid-Terrace",
        "End-Terrace",
        "Enclosed Mid-Terrace",
        "Enclosed End-Terrace",
    )
    PRE_1930_AGE_BANDS = (
        "before 1900",
        "England and Wales: before 1900",
        "1900-1929",
        "England and Wales: 1900-1929",
        "1900-1920",
        "1920-1929",
    )
    BOROUGH_COLUMN_CANDIDATES = (
        "COUNCIL",
        "BOROUGH",
        "LOCAL_AUTHORITY_LABEL",
        "LOCAL_AUTHORITY",
    )

    @staticmethod
    def _emit_progress(progress_callback: Optional[Callable[[Dict[str, Any]], None]], event: Dict[str, Any]) -> None:
        """Emit a structured progress event without coupling acquisition to a UI."""
        if progress_callback is None:
            return
        try:
            progress_callback(dict(event))
        except Exception as exc:
            logger.debug(f"Ignoring EPC progress callback failure: {exc}")

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

    def __init__(self, token: Optional[str] = None, download_mode: str = "search", timeout: int = 60):
        self.config = load_config()
        self.property_filters = get_property_filters()
        self.token = token or os.getenv("EPC_API_TOKEN")
        if not self.token:
            raise ValueError("API token not found. Please set EPC_API_TOKEN in your .env file or pass it as a parameter.")
        self.download_mode = download_mode
        self.timeout = timeout
        self._full_load_cache: Optional[pd.DataFrame] = None
        self._full_load_stage_cache: Optional[DatasetReference] = None
        DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(f"Initialized EPC API Downloader using {self.download_mode} mode")

    def _headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

    @staticmethod
    def _create_ssl_context() -> ssl.SSLContext:
        """Create a TLS context without relying on the Windows certificate store."""
        try:
            import certifi
        except ImportError:
            return ssl.create_default_context()

        return ssl.create_default_context(cafile=certifi.where())

    @classmethod
    def _is_first_party_api_url(cls, url: str) -> bool:
        return urllib.parse.urlparse(url).netloc.casefold() == cls.API_HOST

    @staticmethod
    def _is_signed_download_url(url: str) -> bool:
        return "x-amz-" in urllib.parse.urlparse(url).query.casefold()

    @classmethod
    def _should_send_download_auth(cls, url: str) -> bool:
        return cls._is_first_party_api_url(url) and not cls._is_signed_download_url(url)

    def _download_headers_for_url(self, url: str) -> Dict[str, str]:
        return self._headers() if self._should_send_download_auth(url) else {}

    @staticmethod
    def _close_response(response) -> None:
        close = getattr(response, "close", None)
        if callable(close):
            close()

    @staticmethod
    def _raise_unexpected_download_error(
        message: str,
        request_context: Optional[EPCRequestContext] = None,
    ) -> None:
        if request_context is not None:
            raise EPCDownloadError.unexpected(request_context, RuntimeError(message))
        raise RuntimeError(message)

    def _open_download_response(
        self,
        url: str,
        request_context: Optional[EPCRequestContext] = None,
    ):
        opener = urllib.request.build_opener(
            _ManualRedirectHandler(),
            urllib.request.HTTPSHandler(context=self._create_ssl_context()),
        )
        current_url = url

        for _ in range(self.MAX_DOWNLOAD_REDIRECTS + 1):
            request = urllib.request.Request(
                current_url,
                headers=self._download_headers_for_url(current_url),
            )
            try:
                response = opener.open(request, timeout=self.timeout)
            except urllib.error.HTTPError as e:
                if e.code not in self.REDIRECT_STATUS_CODES:
                    if request_context is not None:
                        raise EPCDownloadError.from_http_error(request_context, e) from e
                    raise
                response = e
            except urllib.error.URLError as e:
                if request_context is not None:
                    raise EPCDownloadError.from_url_error(request_context, e) from e
                raise

            status_code = getattr(response, "code", None) or response.getcode()
            if status_code not in self.REDIRECT_STATUS_CODES:
                return response

            location = response.headers.get("Location")
            self._close_response(response)
            if not location:
                self._raise_unexpected_download_error(
                    f"EPC full-load download redirect from {current_url} did not include a Location header.",
                    request_context=request_context,
                )

            next_url = urllib.parse.urljoin(current_url, location)
            if (
                self._should_send_download_auth(current_url)
                and not self._should_send_download_auth(next_url)
            ):
                logger.debug(
                    "EPC full-load download received a signed or cross-host URL; "
                    "continuing without Authorization header: {}",
                    next_url,
                )
            current_url = next_url

        self._raise_unexpected_download_error(
            f"EPC full-load download exceeded {self.MAX_DOWNLOAD_REDIRECTS} redirects starting from {url}.",
            request_context=request_context,
        )

    def _build_request_context(
        self,
        borough_name: str,
        property_type: str,
        sample_start_date: Optional[date_cls],
        sample_end_date: Optional[date_cls],
    ) -> EPCRequestContext:
        return EPCRequestContext(
            borough_name=borough_name,
            property_type=property_type,
            sample_start_date=sample_start_date,
            sample_end_date=sample_end_date,
            request_mode=self.download_mode,
        )

    def _request_json(
        self,
        url: str,
        params: Dict,
        retries: int = 6,
        request_context: Optional[EPCRequestContext] = None,
    ) -> Dict:
        query = urllib.parse.urlencode(params, doseq=True)
        full_url = f"{url}?{query}" if query else url
        request = urllib.request.Request(full_url, headers=self._headers())
        backoff = 1.0
        for attempt in range(retries):
            try:
                try:
                    response_context = self._create_ssl_context()
                    response = urllib.request.urlopen(
                        request,
                        timeout=self.timeout,
                        context=response_context,
                    )
                except TypeError:
                    response = urllib.request.urlopen(request, timeout=self.timeout)

                with response:
                    payload = response.read().decode("utf-8")
                    if not payload.strip():
                        if request_context is None:
                            return {}
                        raise EPCDownloadError.empty_response(
                            request_context,
                            detail="EPC API returned an empty JSON response body.",
                        )
                    return json.loads(payload) if payload else {}
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < retries - 1:
                    retry_after = e.headers.get("Retry-After")
                    sleep_for = float(retry_after) if retry_after and retry_after.isdigit() else backoff
                    logger.warning(f"Rate limited by EPC API; retrying in {sleep_for:.1f}s")
                    time.sleep(sleep_for)
                    backoff = min(backoff * 2, 60)
                    continue
                if request_context is not None:
                    raise EPCDownloadError.from_http_error(request_context, e) from e
                raise
            except urllib.error.URLError as e:
                if request_context is not None:
                    raise EPCDownloadError.from_url_error(request_context, e) from e
                raise
            except ssl.SSLError as e:
                if request_context is not None:
                    raise EPCDownloadError.unexpected(request_context, e) from e
                raise
            except json.JSONDecodeError as e:
                if request_context is not None:
                    raise EPCDownloadError.unexpected(request_context, e) from e
                raise

    def _download_file(
        self,
        url: str,
        request_context: Optional[EPCRequestContext] = None,
    ) -> bytes:
        try:
            with self._open_download_response(url, request_context=request_context) as response:
                payload = response.read()
                if payload:
                    return payload
                if request_context is not None:
                    raise EPCDownloadError.empty_response(
                        request_context,
                        detail="EPC API returned an empty file download.",
                    )
                return payload
        except urllib.error.HTTPError as e:
            if request_context is not None:
                raise EPCDownloadError.from_http_error(request_context, e) from e
            raise
        except urllib.error.URLError as e:
            if request_context is not None:
                raise EPCDownloadError.from_url_error(request_context, e) from e
            raise

    def _download_file_to_path(
        self,
        url: str,
        destination: Path,
        request_context: Optional[EPCRequestContext] = None,
    ) -> Path:
        """Stream a file download directly to disk."""
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with self._open_download_response(url, request_context=request_context) as response:
                with open(destination, "wb") as output_file:
                    supports_sized_read = True
                    while True:
                        if supports_sized_read:
                            try:
                                chunk = response.read(1024 * 1024)
                            except TypeError:
                                supports_sized_read = False
                                chunk = response.read()
                        else:
                            chunk = response.read()
                        if not chunk:
                            break
                        output_file.write(chunk)
                        if not supports_sized_read:
                            break

            if destination.exists() and destination.stat().st_size > 0:
                return destination

            if request_context is not None:
                raise EPCDownloadError.empty_response(
                    request_context,
                    detail="EPC API returned an empty file download.",
                )
            return destination
        except ssl.SSLError as e:
            self._raise_unexpected_download_error(
                f"TLS error while streaming EPC full-load download to {destination.resolve()}: {e}",
                request_context=request_context,
            )
        except OSError as e:
            self._raise_unexpected_download_error(
                f"Filesystem error while streaming EPC full-load download to {destination.resolve()}: {e}",
                request_context=request_context,
            )
        except urllib.error.HTTPError as e:
            if request_context is not None:
                raise EPCDownloadError.from_http_error(request_context, e) from e
            raise
        except urllib.error.URLError as e:
            if request_context is not None:
                raise EPCDownloadError.from_url_error(request_context, e) from e
            raise

    def _normalize_api_records(self, df: pd.DataFrame, borough_name: Optional[str] = None) -> pd.DataFrame:
        if df.empty:
            return df
        rename_map = {
            "certificateNumber": "CERTIFICATE_NUMBER",
            "addressLine1": "ADDRESS_LINE1",
            "addressLine2": "ADDRESS_LINE2",
            "addressLine3": "ADDRESS_LINE3",
            "addressLine4": "ADDRESS_LINE4",
            "postcode": "POSTCODE",
            "postTown": "POST_TOWN",
            "council": "COUNCIL",
            "constituency": "CONSTITUENCY",
            "currentEnergyEfficiencyBand": "CURRENT_ENERGY_RATING",
            "currentEnergyEfficiencyRating": "CURRENT_ENERGY_RATING",
            "registrationDate": "LODGEMENT_DATE",
            "lodgementDate": "LODGEMENT_DATE",
            "inspectionDate": "INSPECTION_DATE",
            "uprn": "UPRN",
            "propertyType": "PROPERTY_TYPE",
            "builtForm": "BUILT_FORM",
            "constructionAgeBand": "CONSTRUCTION_AGE_BAND",
            "propertyTypeDescription": "PROPERTY_TYPE",
        }
        df = df.rename(columns={c: rename_map.get(c, c) for c in df.columns})
        df.columns = [c.replace("-", "_").upper() for c in df.columns]
        if df.columns.duplicated().any():
            df = df.loc[:, ~df.columns.duplicated()].copy()
        return df

    @staticmethod
    def _normalize_column_labels(columns: Iterable) -> List[str]:
        return [str(column).replace("-", "_").upper() for column in columns]

    @classmethod
    def get_missing_stock_definition_columns(cls, df: pd.DataFrame) -> List[str]:
        normalized_columns = set(cls._normalize_column_labels(df.columns))
        return [
            column
            for column in cls.STOCK_DEFINITION_COLUMNS
            if column not in normalized_columns
        ]

    @classmethod
    def ensure_stock_definition_columns(cls, df: pd.DataFrame) -> None:
        missing_columns = cls.get_missing_stock_definition_columns(df)
        if missing_columns:
            missing = ", ".join(missing_columns)
            raise EPCStockDefinitionError(
                "Cannot define the London pre-1930 terraced house stock because "
                f"the EPC data is missing required columns: {missing}. "
                "Use the full-load EPC CSV source for stock-definition filtering."
            )

    @classmethod
    def _resolve_borough_column(cls, df: pd.DataFrame) -> Optional[str]:
        normalized_lookup = {
            normalized: original
            for original, normalized in zip(df.columns, cls._normalize_column_labels(df.columns))
        }
        for candidate in cls.BOROUGH_COLUMN_CANDIDATES:
            if candidate in normalized_lookup:
                return normalized_lookup[candidate]
        return None

    @classmethod
    def _borough_tokens(cls, borough_names: Iterable[str]) -> set[str]:
        tokens = set()
        for borough_name in borough_names:
            tokens.add(str(borough_name).strip().casefold())
            code = cls.LONDON_LA_CODES.get(borough_name)
            if code:
                tokens.add(code.casefold())
        return tokens

    @classmethod
    def _filter_to_boroughs(cls, df: pd.DataFrame, borough_names: Iterable[str]) -> pd.DataFrame:
        borough_column = cls._resolve_borough_column(df)
        if borough_column is None:
            raise EPCStockDefinitionError(
                "Cannot restrict the EPC full-load extract to London because no borough/council "
                "column was found."
            )
        tokens = cls._borough_tokens(borough_names)
        mask = (
            df[borough_column]
            .astype(str)
            .str.strip()
            .str.casefold()
            .isin(tokens)
        )
        return df.loc[mask].copy()

    @classmethod
    def _filter_to_property_types(
        cls,
        df: pd.DataFrame,
        property_types: Optional[Iterable[str]],
    ) -> pd.DataFrame:
        if not property_types:
            return df
        normalized_lookup = {
            normalized: original
            for original, normalized in zip(df.columns, cls._normalize_column_labels(df.columns))
        }
        property_column = normalized_lookup.get("PROPERTY_TYPE")
        if property_column is None:
            raise EPCStockDefinitionError(
                "Cannot restrict the EPC full-load extract to London houses because "
                "PROPERTY_TYPE is missing."
            )
        requested_types = {
            str(property_type).strip().casefold()
            for property_type in property_types
            if property_type is not None
        }
        mask = (
            df[property_column]
            .astype(str)
            .str.strip()
            .str.casefold()
            .isin(requested_types)
        )
        return df.loc[mask].copy()

    @staticmethod
    def _extract_member_year(member_name: str) -> Optional[int]:
        """Extract a candidate year from a ZIP member name."""
        stem = Path(member_name).stem
        tokens = str(stem).replace("_", "-").split("-")
        for token in reversed(tokens):
            if token.isdigit() and len(token) == 4:
                year = int(token)
                if 1900 <= year <= 2100:
                    return year
        return None

    def _member_overlaps_sample_window(
        self,
        member_name: str,
        sample_start_date: Optional[date_cls],
        sample_end_date: Optional[date_cls],
    ) -> bool:
        """Return True when a certificate member plausibly overlaps the requested window."""
        if sample_start_date is None and sample_end_date is None:
            return True

        member_year = self._extract_member_year(member_name)
        if member_year is None:
            return True

        start_year = sample_start_date.year if sample_start_date else member_year
        end_year = sample_end_date.year if sample_end_date else member_year
        return start_year <= member_year <= end_year

    @staticmethod
    def _count_member_data_lines(zf: zipfile.ZipFile, member_name: str) -> int:
        """Approximate the number of data rows in a CSV member for audit logging."""
        with zf.open(member_name) as raw_file:
            text_file = io.TextIOWrapper(raw_file, encoding="utf-8-sig", errors="replace", newline="")
            line_count = sum(1 for _ in text_file)
        return max(line_count - 1, 0)

    @staticmethod
    def _normalize_lookup(columns: Iterable[str]) -> Dict[str, str]:
        return {
            normalized: original
            for original, normalized in zip(columns, EPCAPIDownloader._normalize_column_labels(columns))
        }

    def _resolve_available_column(self, columns: Iterable[str], candidates: Iterable[str]) -> Optional[str]:
        lookup = self._normalize_lookup(columns)
        for candidate in candidates:
            if candidate in lookup:
                return lookup[candidate]
        return None

    @staticmethod
    def _membership_sql(column_name: str, values: Iterable[str]) -> str:
        normalized_values = [sql_literal(str(value).strip().casefold()) for value in values if value is not None]
        if not normalized_values:
            return "TRUE"
        return (
            f"LOWER(TRIM(CAST({sql_identifier(column_name)} AS VARCHAR))) "
            f"IN ({', '.join(normalized_values)})"
        )

    def _full_load_stage_dir(
        self,
        sample_start_date: Optional[date_cls],
        sample_end_date: Optional[date_cls],
    ) -> Path:
        start_label = sample_start_date.isoformat() if sample_start_date else "open"
        end_label = sample_end_date.isoformat() if sample_end_date else "open"
        return DATA_RAW_DIR / "staged" / f"domestic_full_load_{start_label}_{end_label}"

    @staticmethod
    def _path_text(path: Path) -> str:
        try:
            return str(Path(path).resolve())
        except Exception:
            return str(path)

    def _validate_downloaded_zip_artifact(
        self,
        download_zip_path: Path,
        *,
        request_context: Optional[EPCRequestContext] = None,
    ) -> int:
        if not download_zip_path.exists():
            self._raise_unexpected_download_error(
                f"Downloaded EPC full-load ZIP artifact is missing at {self._path_text(download_zip_path)} (size_bytes=0).",
                request_context=request_context,
            )

        file_size = int(download_zip_path.stat().st_size)
        logger.info(
            "Downloaded EPC full-load ZIP size before validation: {} bytes ({})",
            file_size,
            self._path_text(download_zip_path),
        )
        if file_size <= 0 or not zipfile.is_zipfile(download_zip_path):
            self._raise_unexpected_download_error(
                f"Downloaded EPC full-load ZIP artifact is invalid at {self._path_text(download_zip_path)} "
                f"(size_bytes={file_size}).",
                request_context=request_context,
            )
        return file_size

    def _log_full_load_reuse_rejected(
        self,
        stage_dir: Path,
        *,
        reason: str,
        detail: Optional[str] = None,
    ) -> None:
        message = f"Reusable staged full-load manifest rejected for {self._path_text(stage_dir)}: {reason}"
        if detail:
            message = f"{message} ({detail})"
        logger.info(message)

    def _load_reusable_full_load_dataset(
        self,
        *,
        stage_dir: Path,
        manifest_path: Path,
        sample_start_date: Optional[date_cls],
        sample_end_date: Optional[date_cls],
        force_refresh: bool,
    ) -> Optional[DatasetReference]:
        if force_refresh:
            self._log_full_load_reuse_rejected(stage_dir, reason="force refresh requested")
            return None

        attempts_root = stage_dir / "attempts"
        if not manifest_path.exists():
            has_prior_attempts = attempts_root.exists() and any(attempts_root.iterdir())
            self._log_full_load_reuse_rejected(
                stage_dir,
                reason="incomplete prior attempt" if has_prior_attempts else "missing manifest",
            )
            return None

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._log_full_load_reuse_rejected(
                stage_dir,
                reason="invalid manifest JSON",
                detail=str(exc),
            )
            return None

        expected_start = sample_start_date.isoformat() if sample_start_date else None
        expected_end = sample_end_date.isoformat() if sample_end_date else None
        manifest_start = manifest.get("sample_start_date")
        manifest_end = manifest.get("sample_end_date")
        if (
            (manifest_start is not None and manifest_start != expected_start)
            or (manifest_end is not None and manifest_end != expected_end)
        ):
            self._log_full_load_reuse_rejected(
                stage_dir,
                reason="sample-window mismatch",
                detail=(
                    f"manifest={manifest_start}..{manifest_end}, "
                    f"requested={expected_start}..{expected_end}"
                ),
            )
            return None

        if manifest.get("status") not in (None, "complete"):
            self._log_full_load_reuse_rejected(
                stage_dir,
                reason="incomplete prior attempt",
                detail=f"status={manifest.get('status')}",
            )
            return None

        dataset_path_value = manifest.get("dataset_path")
        dataset_path = Path(dataset_path_value) if dataset_path_value else stage_dir / "raw_certificates_dataset"
        if not parquet_dataset_exists(dataset_path):
            self._log_full_load_reuse_rejected(
                stage_dir,
                reason="missing Parquet",
                detail=self._path_text(dataset_path),
            )
            return None

        try:
            row_count = int(
                manifest.get("rows_retained_after_sample_window")
                or manifest.get("row_count")
                or parquet_row_count(dataset_path)
            )
        except Exception:
            row_count = parquet_row_count(dataset_path)

        cached = DatasetReference(
            name="national_domestic_certificate_ingest",
            parquet_path=dataset_path,
            manifest_path=manifest_path,
            row_count=row_count,
            stage="raw_national_ingest",
            sample_start_date=expected_start,
            sample_end_date=expected_end,
            storage_kind="parquet_dataset",
            is_large_run=True,
            metadata=manifest,
        )
        logger.info(
            "Reusable staged full-load manifest accepted: manifest={}, dataset={}",
            self._path_text(manifest_path),
            self._path_text(dataset_path),
        )
        return cached

    def download_national_domestic_dataset(
        self,
        request_context: Optional[EPCRequestContext] = None,
        sample_start_date: Optional[date_cls] = None,
        sample_end_date: Optional[date_cls] = None,
        chunk_size: int = FULL_LOAD_CHUNK_SIZE,
        force_refresh: bool = False,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> DatasetReference:
        """Stage the domestic full-load ZIP into a certificate-only Parquet dataset."""
        request_context = request_context or self._build_request_context(
            borough_name="National",
            property_type="domestic",
            sample_start_date=sample_start_date,
            sample_end_date=sample_end_date,
        )
        if self._full_load_stage_cache is not None and not force_refresh:
            cached = self._full_load_stage_cache
            if (
                cached.sample_start_date == (sample_start_date.isoformat() if sample_start_date else None)
                and cached.sample_end_date == (sample_end_date.isoformat() if sample_end_date else None)
                and cached.exists()
            ):
                self._emit_progress(
                    progress_callback,
                    {
                        "event": "reusable_staged_dataset_accepted",
                        "stage_dir": self._path_text(cached.parquet_path.parent),
                        "manifest_path": self._path_text(cached.manifest_path) if cached.manifest_path else None,
                        "dataset_path": self._path_text(cached.parquet_path),
                        "row_count": cached.row_count,
                    },
                )
                return cached

        stage_dir = self._full_load_stage_dir(sample_start_date, sample_end_date)
        manifest_path = stage_dir / "ingest_manifest.json"
        stage_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Selected national full-load stage root: {}", self._path_text(stage_dir))

        reusable_dataset = self._load_reusable_full_load_dataset(
            stage_dir=stage_dir,
            manifest_path=manifest_path,
            sample_start_date=sample_start_date,
            sample_end_date=sample_end_date,
            force_refresh=force_refresh,
        )
        if reusable_dataset is not None:
            self._full_load_stage_cache = reusable_dataset
            self._emit_progress(
                progress_callback,
                {
                    "event": "reusable_staged_dataset_accepted",
                    "stage_dir": self._path_text(stage_dir),
                    "manifest_path": self._path_text(manifest_path),
                    "dataset_path": self._path_text(reusable_dataset.parquet_path),
                    "row_count": reusable_dataset.row_count,
                },
            )
            logger.info(
                "Returning staged national domestic dataset parquet={} manifest={}",
                self._path_text(reusable_dataset.parquet_path),
                self._path_text(manifest_path),
            )
            return reusable_dataset

        attempt_dir = create_attempt_directory(stage_dir)
        dataset_dir = attempt_dir / "raw_certificates_dataset"
        download_zip_path = attempt_dir / "domestic_full_load.zip"
        logger.info("Chosen national full-load attempt directory: {}", self._path_text(attempt_dir))
        self._emit_progress(
            progress_callback,
            {
                "event": "attempt_directory_created",
                "stage_dir": self._path_text(stage_dir),
                "attempt_dir": self._path_text(attempt_dir),
            },
        )

        logger.info("Streaming EPC domestic full-load ZIP to {}", download_zip_path)
        self._emit_progress(
            progress_callback,
            {
                "event": "zip_download_started",
                "url": self.FULL_LOAD_URL,
                "download_zip_path": self._path_text(download_zip_path),
            },
        )
        self._download_file_to_path(self.FULL_LOAD_URL, download_zip_path, request_context=request_context)
        zip_size = self._validate_downloaded_zip_artifact(download_zip_path, request_context=request_context)
        self._emit_progress(
            progress_callback,
            {
                "event": "zip_validation_complete",
                "download_zip_path": self._path_text(download_zip_path),
                "size_bytes": zip_size,
            },
        )

        manifest: Dict[str, object] = {
            "source_url": self.FULL_LOAD_URL,
            "sample_start_date": sample_start_date.isoformat() if sample_start_date else None,
            "sample_end_date": sample_end_date.isoformat() if sample_end_date else None,
            "stage_dir": self._path_text(stage_dir),
            "attempt_dir": self._path_text(attempt_dir),
            "dataset_path": self._path_text(dataset_dir),
            "download_zip_path": self._path_text(download_zip_path),
            "members_processed": [],
            "selected_certificate_members": [],
            "ignored_recommendation_members": [],
            "ignored_non_certificate_members": [],
            "rows_read": 0,
            "rows_retained_after_sample_window": 0,
            "malformed_rows_skipped": 0,
            "normalized_columns": [],
            "status": "complete",
        }

        part_index = 0
        with zipfile.ZipFile(download_zip_path) as zf:
            csv_members = [member for member in zf.namelist() if member.lower().endswith(".csv")]
            certificate_members = []
            recommendation_members = []
            other_members = []

            for member in csv_members:
                member_name = Path(member).name.lower()
                if "recommendation" in member_name:
                    recommendation_members.append(member)
                elif "certificate" in member_name or member_name.endswith(".csv"):
                    if self._member_overlaps_sample_window(member, sample_start_date, sample_end_date):
                        certificate_members.append(member)
                    else:
                        other_members.append(member)
                else:
                    other_members.append(member)

            manifest["selected_certificate_members"] = certificate_members
            manifest["ignored_recommendation_members"] = recommendation_members
            manifest["ignored_non_certificate_members"] = other_members
            self._emit_progress(
                progress_callback,
                {
                    "event": "member_selection_complete",
                    "selected_certificate_members": list(certificate_members),
                    "ignored_recommendation_members": list(recommendation_members),
                    "ignored_non_certificate_members": list(other_members),
                },
            )

            for member in certificate_members:
                approx_member_rows = self._count_member_data_lines(zf, member)
                rows_retained = 0
                parsed_rows = 0
                self._emit_progress(
                    progress_callback,
                    {
                        "event": "member_started",
                        "member": member,
                        "approx_rows_in_file": int(approx_member_rows),
                        "member_year": self._extract_member_year(member),
                    },
                )

                with zf.open(member) as raw_file:
                    chunk_iter = pd.read_csv(
                        raw_file,
                        chunksize=chunk_size,
                        on_bad_lines="skip",
                    )
                    for chunk in chunk_iter:
                        chunk_rows_read = len(chunk)
                        parsed_rows += chunk_rows_read
                        chunk = self._normalize_api_records(chunk)
                        if not manifest["normalized_columns"]:
                            manifest["normalized_columns"] = list(chunk.columns)
                        chunk = self._apply_sample_window_filter(
                            chunk,
                            sample_start_date,
                            sample_end_date,
                            log_prefix=f"full-load member {Path(member).name}",
                        )
                        rows_retained += len(chunk)
                        self._emit_progress(
                            progress_callback,
                            {
                                "event": "chunk_parsed",
                                "member": member,
                                "rows_read": int(chunk_rows_read),
                                "parsed_rows_total": int(parsed_rows),
                                "rows_retained": int(len(chunk)),
                                "rows_retained_total": int(rows_retained),
                            },
                        )
                        if not chunk.empty:
                            part_path = write_parquet_part(chunk, dataset_dir, part_index, prefix="certificates")
                            self._emit_progress(
                                progress_callback,
                                {
                                    "event": "parquet_part_written",
                                    "member": member,
                                    "part_index": int(part_index),
                                    "rows": int(len(chunk)),
                                    "path": self._path_text(part_path),
                                },
                            )
                            part_index += 1

                skipped_rows = max(approx_member_rows - parsed_rows, 0)
                manifest["rows_read"] += int(parsed_rows)
                manifest["rows_retained_after_sample_window"] += int(rows_retained)
                manifest["malformed_rows_skipped"] += int(skipped_rows)
                manifest["members_processed"].append(
                    {
                        "member": member,
                        "approx_rows_in_file": int(approx_member_rows),
                        "rows_read": int(parsed_rows),
                        "rows_retained_after_sample_window": int(rows_retained),
                        "malformed_rows_skipped": int(skipped_rows),
                        "member_year": self._extract_member_year(member),
                    }
                )
                self._emit_progress(
                    progress_callback,
                    {
                        "event": "member_complete",
                        "member": member,
                        "approx_rows_in_file": int(approx_member_rows),
                        "rows_read": int(parsed_rows),
                        "rows_retained_after_sample_window": int(rows_retained),
                        "malformed_rows_skipped": int(skipped_rows),
                        "member_year": self._extract_member_year(member),
                    },
                )

        if part_index == 0:
            raise EPCDownloadError.empty_response(
                request_context,
                detail="EPC API full-load ZIP download succeeded but no certificate rows matched the requested sample window.",
            )
        if not parquet_dataset_exists(dataset_dir):
            self._raise_unexpected_download_error(
                f"Staged EPC full-load ingest did not produce a Parquet dataset at {self._path_text(dataset_dir)}.",
                request_context=request_context,
            )

        dataset_ref = DatasetReference(
            name="national_domestic_certificate_ingest",
            parquet_path=dataset_dir,
            manifest_path=manifest_path,
            row_count=int(manifest["rows_retained_after_sample_window"]),
            stage="raw_national_ingest",
            sample_start_date=sample_start_date.isoformat() if sample_start_date else None,
            sample_end_date=sample_end_date.isoformat() if sample_end_date else None,
            storage_kind="parquet_dataset",
            is_large_run=True,
            metadata=manifest,
        )
        write_dataset_manifest(dataset_ref)
        self._full_load_stage_cache = dataset_ref
        self._emit_progress(
            progress_callback,
            {
                "event": "dataset_reference_created",
                "name": dataset_ref.name,
                "parquet_path": self._path_text(dataset_ref.parquet_path),
                "manifest_path": self._path_text(manifest_path),
                "row_count": dataset_ref.row_count,
            },
        )
        logger.info(
            "Staged {} certificate rows from {} members; ignored {} recommendation members; skipped ~{} malformed rows",
            dataset_ref.row_count,
            len(certificate_members),
            len(recommendation_members),
            manifest["malformed_rows_skipped"],
        )
        logger.info(
            "Returning staged national domestic dataset parquet={} manifest={}",
            self._path_text(dataset_ref.parquet_path),
            self._path_text(manifest_path),
        )
        return dataset_ref

    def _materialize_staged_subset(
        self,
        input_dataset: DatasetReference,
        output_parquet_path: Path,
        *,
        dataset_name: str,
        borough_names: Optional[Iterable[str]] = None,
        property_types: Optional[Iterable[str]] = None,
        apply_stock_definition: bool = False,
        max_results_per_group: Optional[int] = None,
        group_column: Optional[str] = None,
    ) -> DatasetReference:
        """Use DuckDB to materialize a filtered subset of a staged Parquet dataset."""
        require_duckdb()

        columns = parquet_columns(input_dataset.parquet_path)
        borough_column = self._resolve_available_column(columns, self.BOROUGH_COLUMN_CANDIDATES)
        property_column = self._resolve_available_column(columns, ("PROPERTY_TYPE",))

        conditions = []
        if borough_names:
            if borough_column is None:
                raise EPCStockDefinitionError(
                    "Cannot restrict the staged full-load extract because no borough/council column was found."
                )
            conditions.append(self._membership_sql(borough_column, borough_names))

        if property_types:
            if property_column is None:
                raise EPCStockDefinitionError(
                    "Cannot restrict the staged full-load extract because PROPERTY_TYPE is missing."
                )
            conditions.append(self._membership_sql(property_column, property_types))

        if apply_stock_definition:
            if property_column is None:
                raise EPCStockDefinitionError("Cannot apply stock definition because PROPERTY_TYPE is missing.")
            built_form_column = self._resolve_available_column(columns, ("BUILT_FORM",))
            age_band_column = self._resolve_available_column(columns, ("CONSTRUCTION_AGE_BAND",))
            if built_form_column is None or age_band_column is None:
                raise EPCStockDefinitionError(
                    "Cannot apply stock definition because BUILT_FORM or CONSTRUCTION_AGE_BAND is missing."
                )

            conditions.append(self._membership_sql(property_column, ("house",)))
            conditions.append(self._membership_sql(built_form_column, self.TERRACE_FORMS))
            conditions.append(self._membership_sql(age_band_column, self.PRE_1930_AGE_BANDS))

        where_sql = " AND ".join(conditions) if conditions else "TRUE"
        source = parquet_source_literal(input_dataset.parquet_path)
        base_sql = f"SELECT * FROM read_parquet({source}) WHERE {where_sql}"

        if max_results_per_group is not None and group_column:
            if group_column not in columns:
                raise EPCStockDefinitionError(
                    f"Cannot apply max_results_per_group because {group_column} is missing."
                )
            select_sql = f"""
                WITH numbered AS (
                    SELECT
                        *,
                        ROW_NUMBER() OVER (
                            PARTITION BY {sql_identifier(group_column)}
                            ORDER BY {sql_identifier(group_column)}
                        ) AS _row_number
                    FROM ({base_sql})
                )
                SELECT * EXCLUDE (_row_number)
                FROM numbered
                WHERE _row_number <= {int(max_results_per_group)}
            """
        else:
            select_sql = base_sql

        copy_query_to_parquet(select_sql, output_parquet_path)
        csv_path = output_parquet_path.with_suffix(".csv")
        copy_parquet_to_csv(output_parquet_path, csv_path)

        dataset_ref = DatasetReference(
            name=dataset_name,
            parquet_path=output_parquet_path,
            csv_path=csv_path,
            manifest_path=output_parquet_path.with_name(f"{output_parquet_path.stem}_manifest.json"),
            row_count=parquet_row_count(output_parquet_path),
            stage=dataset_name,
            sample_start_date=input_dataset.sample_start_date,
            sample_end_date=input_dataset.sample_end_date,
            storage_kind="parquet",
            is_large_run=input_dataset.is_large_run,
            metadata={
                "input_dataset": input_dataset.to_dict(),
                "borough_names": list(borough_names) if borough_names else None,
                "property_types": list(property_types) if property_types else None,
                "apply_stock_definition": apply_stock_definition,
            },
        )
        write_dataset_manifest(dataset_ref)
        return dataset_ref

    def materialize_full_load_subset(
        self,
        input_dataset: DatasetReference,
        output_parquet_path: Path,
        *,
        dataset_name: str,
        borough_names: Optional[Iterable[str]] = None,
        property_types: Optional[Iterable[str]] = None,
        apply_stock_definition: bool = False,
        max_results_per_group: Optional[int] = None,
        group_column: Optional[str] = None,
    ) -> DatasetReference:
        """Public wrapper for staged Parquet subset materialisation."""
        return self._materialize_staged_subset(
            input_dataset,
            output_parquet_path,
            dataset_name=dataset_name,
            borough_names=borough_names,
            property_types=property_types,
            apply_stock_definition=apply_stock_definition,
            max_results_per_group=max_results_per_group,
            group_column=group_column,
        )

    def _get_full_load_dataframe(
        self,
        request_context: Optional[EPCRequestContext] = None,
    ) -> pd.DataFrame:
        """
        Compatibility helper for older callers.

        National-scale callers should use `download_national_domestic_dataset()`
        or `_materialize_staged_subset()` instead of loading the full extract into memory.
        """
        staged = self.download_national_domestic_dataset(request_context=request_context)
        logger.warning(
            "Loading the staged full-load dataset into memory for compatibility. "
            "Prefer dataset-backed callers for large runs."
        )
        return staged.load_dataframe()

    @staticmethod
    def _effective_sample_window(
        from_year: int,
        sample_start_date: Optional[date_cls],
        sample_end_date: Optional[date_cls],
    ) -> Tuple[Optional[date_cls], Optional[date_cls]]:
        start_date = sample_start_date or date_cls(from_year, 1, 1)
        return start_date, sample_end_date

    def _build_search_params(
        self,
        borough_name: str,
        property_type: str,
        from_year: int,
        sample_start_date: Optional[date_cls],
        sample_end_date: Optional[date_cls],
        current_page: int,
        page_size: int,
    ) -> Dict:
        params = {
            "council[]": [borough_name],
            "current_page": current_page,
            "page_size": page_size,
        }
        if sample_start_date:
            params["date_start"] = sample_start_date.isoformat()
        else:
            params["date_start"] = date_cls(from_year, 1, 1).isoformat()
        if sample_end_date:
            params["date_end"] = sample_end_date.isoformat()
        if property_type:
            params["property_type"] = property_type
        return params

    @staticmethod
    def _coerce_int(value) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _get_reported_last_page(self, pagination: Dict, page_size: int) -> Optional[int]:
        for key in (
            "totalPages",
            "total_pages",
            "pageCount",
            "page_count",
            "lastPage",
            "last_page",
            "maxPage",
            "max_page",
            "pages",
        ):
            parsed = self._coerce_int(pagination.get(key))
            if parsed:
                return parsed

        for key in ("totalRecords", "total_records", "total", "count", "results"):
            total_records = self._coerce_int(pagination.get(key))
            if total_records is not None and total_records >= 0 and page_size > 0:
                return max(1, (total_records + page_size - 1) // page_size)

        return None

    @staticmethod
    def _is_terminal_out_of_range_pagination_error(error: EPCDownloadError) -> bool:
        if error.http_status != 400 or error.request_mode != "search":
            return False
        message = str(error).lower()
        return "page number" in message and "out of range" in message

    def download_borough_data(
        self,
        borough_name: str,
        property_type: str = 'house',
        from_year: int = 2015,
        sample_start_date: Optional[date_cls] = None,
        sample_end_date: Optional[date_cls] = None,
        max_results: Optional[int] = None,
        log_borough: bool = True,
        show_progress: bool = True,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> pd.DataFrame:
        if borough_name not in self.LONDON_LA_CODES:
            logger.error(f"Unknown borough: {borough_name}")
            return pd.DataFrame()
        if log_borough:
            logger.info(f"Downloading EPC data for {borough_name}...")
        effective_start_date = sample_start_date
        effective_end_date = sample_end_date
        if self.download_mode == "full_load":
            effective_start_date, effective_end_date = self._effective_sample_window(
                from_year,
                sample_start_date,
                sample_end_date,
            )
        request_context = self._build_request_context(
            borough_name=borough_name,
            property_type=property_type,
            sample_start_date=effective_start_date,
            sample_end_date=effective_end_date,
        )
        if self.download_mode == "full_load":
            return self._download_borough_from_full_load(
                borough_name,
                property_type=property_type,
                sample_start_date=effective_start_date,
                sample_end_date=effective_end_date,
                request_context=request_context,
                progress_callback=progress_callback,
            )
        all_records: List[pd.DataFrame] = []
        current_page = 1
        page_size = self.DEFAULT_PAGE_SIZE
        total_records = 0
        pbar = tqdm(desc=f"{borough_name}", unit=" records", disable=not show_progress)
        try:
            while True:
                params = self._build_search_params(
                    borough_name=borough_name,
                    property_type=property_type,
                    from_year=from_year,
                    sample_start_date=sample_start_date,
                    sample_end_date=sample_end_date,
                    current_page=current_page,
                    page_size=page_size,
                )
                try:
                    payload = self._request_json(
                        self.SEARCH_URL,
                        params,
                        request_context=request_context,
                    )
                except EPCDownloadError as e:
                    if all_records and self._is_terminal_out_of_range_pagination_error(e):
                        logger.warning(
                            f"{borough_name}: EPC API reported out-of-range terminal page "
                            f"{current_page}; treating previous page as end of pagination"
                        )
                        break
                    raise
                records = payload.get("data", [])
                if not records:
                    break
                df_page = self._normalize_api_records(pd.DataFrame(records), borough_name=borough_name)
                all_records.append(df_page)
                total_records += len(df_page)
                pbar.update(len(df_page))
                pagination = payload.get("pagination", {})
                next_page = self._coerce_int(pagination.get("nextPage"))
                reported_current_page = (
                    self._coerce_int(pagination.get("currentPage"))
                    or self._coerce_int(pagination.get("current_page"))
                    or current_page
                )
                last_page = self._get_reported_last_page(pagination, page_size)
                if max_results and total_records >= max_results:
                    break
                if not next_page:
                    break
                if last_page is not None and reported_current_page >= last_page:
                    logger.debug(
                        f"{borough_name}: stopping pagination at reported last page "
                        f"{reported_current_page} of {last_page}"
                    )
                    break
                if last_page is not None and next_page > last_page:
                    logger.warning(
                        f"{borough_name}: API returned nextPage={next_page} beyond reported "
                        f"last page {last_page}; stopping pagination cleanly"
                    )
                    break
                if next_page <= reported_current_page:
                    logger.warning(
                        f"{borough_name}: API returned non-incrementing nextPage={next_page} "
                        f"from current page {reported_current_page}; stopping pagination cleanly"
                    )
                    break
                current_page = int(next_page)
        except EPCDownloadError:
            raise
        except urllib.error.HTTPError as e:
            raise EPCDownloadError.from_http_error(request_context, e) from e
        except urllib.error.URLError as e:
            raise EPCDownloadError.from_url_error(request_context, e) from e
        except Exception as e:
            raise EPCDownloadError.unexpected(request_context, e) from e
        finally:
            pbar.close()
        if not all_records:
            return pd.DataFrame()
        df = pd.concat(all_records, ignore_index=True)
        return self._apply_sample_window_filter(df, sample_start_date, sample_end_date, borough_name)

    def _download_borough_from_full_load(
        self,
        borough_name: str,
        property_type: str,
        sample_start_date: Optional[date_cls],
        sample_end_date: Optional[date_cls],
        request_context: Optional[EPCRequestContext] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> pd.DataFrame:
        staged = self.download_national_domestic_dataset(
            request_context=request_context,
            sample_start_date=sample_start_date,
            sample_end_date=sample_end_date,
            progress_callback=progress_callback,
        )
        output_parquet_path = DATA_RAW_DIR / f"epc_{borough_name.lower().replace(' ', '_')}_full_load.parquet"
        subset = self._materialize_staged_subset(
            staged,
            output_parquet_path,
            dataset_name=f"{borough_name}_full_load_subset",
            borough_names=[borough_name],
            property_types=[property_type] if property_type else None,
        )
        return subset.load_dataframe()

    def _apply_sample_window_filter(
        self,
        df: pd.DataFrame,
        sample_start_date: Optional[date_cls] = None,
        sample_end_date: Optional[date_cls] = None,
        log_prefix: str = "download",
    ) -> pd.DataFrame:
        if df.empty or (sample_start_date is None and sample_end_date is None):
            return df
        lodgement_col = next((col for col in ['LODGEMENT_DATE', 'lodgement-date'] if col in df.columns), None)
        inspection_col = next((col for col in ['INSPECTION_DATE', 'inspection-date'] if col in df.columns), None)
        if lodgement_col is None and inspection_col is None:
            logger.warning(f"{log_prefix}: no lodgement/inspection date columns found")
            return df
        lodgement_dates = pd.to_datetime(df[lodgement_col], errors='coerce') if lodgement_col else pd.Series(pd.NaT, index=df.index)
        inspection_dates = pd.to_datetime(df[inspection_col], errors='coerce') if inspection_col else pd.Series(pd.NaT, index=df.index)
        effective_dates = lodgement_dates.fillna(inspection_dates)
        mask = effective_dates.notna()
        if sample_start_date is not None:
            mask &= effective_dates.dt.date >= sample_start_date
        if sample_end_date is not None:
            mask &= effective_dates.dt.date <= sample_end_date
        filtered_df = df.loc[mask].copy()
        logger.info(
            f"{log_prefix}: Applied exact sample window filter "
            f"{sample_start_date.isoformat() if sample_start_date else 'open'} to "
            f"{sample_end_date.isoformat() if sample_end_date else 'open'}; "
            f"retained {len(filtered_df):,} / {len(df):,} records"
        )
        return filtered_df

    def download_all_london_boroughs(
        self,
        property_types: Optional[List[str]] = None,
        from_year: int = 2015,
        sample_start_date: Optional[date_cls] = None,
        sample_end_date: Optional[date_cls] = None,
        max_results_per_borough: Optional[int] = None,
        max_workers: int = 4,
        log_boroughs: bool = True,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> pd.DataFrame:
        property_types = property_types or ['house']
        if self.download_mode == "full_load":
            effective_start_date, effective_end_date = self._effective_sample_window(
                from_year,
                sample_start_date,
                sample_end_date,
            )
            request_context = self._build_request_context(
                borough_name="London",
                property_type=",".join(property_types),
                sample_start_date=effective_start_date,
                sample_end_date=effective_end_date,
            )
            staged = self.download_national_domestic_dataset(
                request_context=request_context,
                sample_start_date=effective_start_date,
                sample_end_date=effective_end_date,
                progress_callback=progress_callback,
            )
            raw_output = DATA_RAW_DIR / "epc_london_raw.parquet"
            subset = self._materialize_staged_subset(
                staged,
                raw_output,
                dataset_name="london_house_full_load",
                borough_names=self.LONDON_LA_CODES.keys(),
                property_types=property_types,
            )
            if max_results_per_borough is not None:
                columns = parquet_columns(subset.parquet_path)
                borough_column = self._resolve_available_column(columns, self.BOROUGH_COLUMN_CANDIDATES)
                if borough_column is None:
                    raise EPCStockDefinitionError(
                        "Cannot apply max_results_per_borough because the staged London full-load extract "
                        "has no borough/council column."
                    )
                subset = self._materialize_staged_subset(
                    subset,
                    DATA_RAW_DIR / "epc_london_raw_limited.parquet",
                    dataset_name="london_house_full_load",
                    max_results_per_group=max_results_per_borough,
                    group_column=borough_column,
                )
            return subset.load_dataframe()

        frames = []
        for borough in self.LONDON_LA_CODES:
            for property_type in property_types:
                request_context = self._build_request_context(
                    borough_name=borough,
                    property_type=property_type,
                    sample_start_date=sample_start_date,
                    sample_end_date=sample_end_date,
                )
                try:
                    df = self.download_borough_data(
                        borough_name=borough,
                        property_type=property_type,
                        from_year=from_year,
                        sample_start_date=sample_start_date,
                        sample_end_date=sample_end_date,
                        max_results=max_results_per_borough,
                        log_borough=log_boroughs,
                        show_progress=log_boroughs,
                    )
                except EPCDownloadError as e:
                    logger.error(f"Fail-fast borough download abort: {e}")
                    raise
                except urllib.error.HTTPError as e:
                    wrapped_error = EPCDownloadError.from_http_error(request_context, e)
                    logger.error(f"Fail-fast borough download abort: {wrapped_error}")
                    raise wrapped_error from e
                except urllib.error.URLError as e:
                    wrapped_error = EPCDownloadError.from_url_error(request_context, e)
                    logger.error(f"Fail-fast borough download abort: {wrapped_error}")
                    raise wrapped_error from e
                except Exception as e:
                    wrapped_error = EPCDownloadError.unexpected(request_context, e)
                    logger.error(f"Fail-fast borough download abort: {wrapped_error}")
                    raise wrapped_error from e
                if not df.empty:
                    frames.append(df)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def apply_edwardian_filters(self, df: pd.DataFrame) -> pd.DataFrame:
        logger.info("Applying pre-1930 terraced house stock filters...")
        df = df.copy()
        df.columns = df.columns.str.replace('-', '_').str.upper()
        initial_count = len(df)
        if df.empty:
            return df
        self.ensure_stock_definition_columns(df)

        property_mask = (
            df['PROPERTY_TYPE']
            .astype(str)
            .str.strip()
            .str.casefold()
            .eq('house')
        )
        construction_mask = (
            df['CONSTRUCTION_AGE_BAND']
            .astype(str)
            .str.strip()
            .str.casefold()
            .isin({band.casefold() for band in self.PRE_1930_AGE_BANDS})
        )
        terrace_mask = (
            df['BUILT_FORM']
            .astype(str)
            .str.strip()
            .str.casefold()
            .isin({form.casefold() for form in self.TERRACE_FORMS})
        )
        df = df.loc[property_mask & construction_mask & terrace_mask].copy()
        if initial_count:
            logger.info(f"Filtering complete: {len(df):,} / {initial_count:,} records retained ({len(df)/initial_count*100:.1f}%)")
        return df

    def save_data(
        self,
        df: pd.DataFrame,
        filename: str,
        raw_df: Optional[pd.DataFrame] = None,
    ):
        if filename == "epc_london_filtered.csv" and raw_df is not None:
            missing_columns = self.get_missing_stock_definition_columns(raw_df)
            if len(df) == len(raw_df) and missing_columns:
                missing = ", ".join(missing_columns)
                raise EPCStockDefinitionError(
                    "Refusing to write epc_london_filtered.csv because it matches the raw London "
                    "house dataset and the required stock-definition columns are missing: "
                    f"{missing}."
                )

        csv_path = DATA_RAW_DIR / filename
        df.to_csv(csv_path, index=False)
        logger.info(f"Saved {len(df):,} records to: {csv_path}")
        try:
            parquet_path = csv_path.with_suffix('.parquet')
            df_parquet = df.copy()
            for col in df_parquet.columns:
                if df_parquet[col].dtype == 'object':
                    df_parquet[col] = df_parquet[col].astype(str)
            df_parquet.to_parquet(parquet_path, index=False)
        except Exception as e:
            logger.warning(f"Could not save as parquet: {e}")


def main():
    logger.info("Starting EPC API data acquisition...")
    downloader = EPCAPIDownloader(download_mode="full_load")
    df = downloader.download_all_london_boroughs(property_types=['house'], from_year=2015)
    if not df.empty:
        downloader.save_data(df, "epc_london_raw.csv")
        df_filtered = downloader.apply_edwardian_filters(df)
        downloader.save_data(df_filtered, "epc_london_filtered.csv", raw_df=df)
        logger.info("Data acquisition complete!")


if __name__ == "__main__":
    main()
