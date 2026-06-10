import io
import json
import re
import shutil
import urllib.error
import zipfile
from datetime import date as date_cls
from email.message import Message
from pathlib import Path

import pandas as pd
import pytest

from src.acquisition.epc_api_downloader import (
    EPCAPIDownloader,
    EPCDownloadError,
    EPCStockDefinitionError,
)


@pytest.fixture
def tmp_path(request):
    base = Path(".tmp_existing_stock_check") / "pytest_tmp"
    base.mkdir(parents=True, exist_ok=True)
    path = base / re.sub(r"[^A-Za-z0-9_.-]+", "_", request.node.name)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _message_headers(**values):
    headers = Message()
    for name, value in values.items():
        headers[name.replace("_", "-")] = value
    return headers


def _build_test_full_load_zip() -> bytes:
    csv_bytes = io.BytesIO()
    with zipfile.ZipFile(csv_bytes, "w") as zf:
        zf.writestr(
            "certificates-2024.csv",
            "certificateNumber,addressLine1,council,registrationDate,propertyTypeDescription,builtForm,constructionAgeBand\n"
            "1,1 Camden Road,Camden,2024-01-01,House,Mid-Terrace,England and Wales: 1900-1929\n",
        )
    return csv_bytes.getvalue()


def _write_parquet_dataset_dir(dataset_dir: Path, df: pd.DataFrame) -> Path:
    dataset_dir.mkdir(parents=True, exist_ok=True)
    split_point = max(1, len(df) // 2)
    frames = [df.iloc[:split_point].copy(), df.iloc[split_point:].copy()]
    for index, frame in enumerate(frames):
        if frame.empty:
            continue
        frame.to_parquet(dataset_dir / f"part-{index:05d}.parquet", index=False)
    (dataset_dir / "calculation_notes.md").write_text("# Calculation notes\n", encoding="utf-8")
    return dataset_dir


class FakeStreamingResponse:
    def __init__(self, payload, *, code=200, headers=None):
        self.payload = payload
        self.code = code
        self.headers = headers or _message_headers()
        self._offset = 0

    def read(self, size=-1):
        if size is None or size < 0:
            size = len(self.payload) - self._offset
        if self._offset >= len(self.payload):
            return b""
        chunk = self.payload[self._offset:self._offset + size]
        self._offset += size
        return chunk

    def getcode(self):
        return self.code

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeManualRedirectOpener:
    def __init__(self, responses, requests_seen):
        self.responses = list(responses)
        self.requests_seen = requests_seen

    def open(self, request, timeout=60):
        self.requests_seen.append(
            {
                "url": request.full_url,
                "headers": dict(request.header_items()),
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class InMemorySubsetReference:
    def __init__(self, df, parquet_path):
        self._df = df
        self.parquet_path = parquet_path

    def load_dataframe(self):
        return self._df.copy()


def _redirect_http_error(url: str, location: str | None = None) -> urllib.error.HTTPError:
    headers = _message_headers()
    if location is not None:
        headers["Location"] = location
    return urllib.error.HTTPError(
        url=url,
        code=302,
        msg="Found",
        hdrs=headers,
        fp=io.BytesIO(b""),
    )


def _patch_materialize_staged_subset_with_pandas(monkeypatch, downloader):
    def fake_materialize(
        input_dataset,
        output_parquet_path,
        *,
        dataset_name,
        borough_names=None,
        property_types=None,
        apply_stock_definition=False,
        max_results_per_group=None,
        group_column=None,
    ):
        df = input_dataset.load_dataframe()
        if borough_names:
            df = downloader._filter_to_boroughs(df, borough_names)
        if property_types:
            df = downloader._filter_to_property_types(df, property_types)
        if apply_stock_definition:
            df = downloader.apply_edwardian_filters(df)
        return InMemorySubsetReference(df, parquet_path=output_parquet_path)

    monkeypatch.setattr(downloader, "_materialize_staged_subset", fake_materialize)


def test_bearer_auth_header_construction():
    downloader = EPCAPIDownloader(token="abc123")
    headers = downloader._headers()
    assert headers["Authorization"] == "Bearer abc123"
    assert headers["Accept"] == "application/json"


def test_normalize_api_records_maps_search_fields():
    downloader = EPCAPIDownloader(token="abc123")
    df = pd.DataFrame([
        {
            "certificateNumber": "1111",
            "addressLine1": "1 Example Road",
            "currentEnergyEfficiencyBand": "D",
            "registrationDate": "2024-01-02",
            "council": "Camden",
            "uprn": 123,
        }
    ])

    normalized = downloader._normalize_api_records(df, borough_name="Camden")

    assert normalized.loc[0, "CERTIFICATE_NUMBER"] == "1111"
    assert normalized.loc[0, "CURRENT_ENERGY_RATING"] == "D"
    assert normalized.loc[0, "LODGEMENT_DATE"] == "2024-01-02"
    assert normalized.loc[0, "COUNCIL"] == "Camden"


def test_full_load_zip_download_and_filtering(monkeypatch, tmp_path):
    downloader = EPCAPIDownloader(token="abc123", download_mode="full_load")
    monkeypatch.setattr("src.acquisition.epc_api_downloader.DATA_RAW_DIR", tmp_path / "full_load_filtering")
    _patch_materialize_staged_subset_with_pandas(monkeypatch, downloader)

    csv_bytes = io.BytesIO()
    with zipfile.ZipFile(csv_bytes, "w") as zf:
        zf.writestr(
            "2024.csv",
            "certificateNumber,addressLine1,council,registrationDate,propertyTypeDescription,builtForm,constructionAgeBand\n"
            "1,1 Camden Road,Camden,2024-01-01,House,Mid-Terrace,England and Wales: 1900-1929\n"
            "2,2 Oxford Street,Westminster,2024-01-01,House,End-Terrace,England and Wales: before 1900\n"
            "3,3 Camden Road,Camden,2024-01-01,Flat,Mid-Terrace,England and Wales: 1900-1929\n",
        )

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def read(self):
            return self.payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        downloader,
        "_open_download_response",
        lambda url, request_context=None: FakeResponse(csv_bytes.getvalue()),
    )

    df = downloader.download_borough_data("Camden")
    assert len(df) == 1
    assert df.iloc[0]["COUNCIL"] == "Camden"
    assert set(EPCAPIDownloader.STOCK_DEFINITION_COLUMNS).issubset(df.columns)


def test_download_all_london_boroughs_full_load_filters_to_london_houses(monkeypatch, tmp_path):
    downloader = EPCAPIDownloader(token="abc123", download_mode="full_load")
    monkeypatch.setattr("src.acquisition.epc_api_downloader.DATA_RAW_DIR", tmp_path / "full_load_london")
    _patch_materialize_staged_subset_with_pandas(monkeypatch, downloader)

    csv_bytes = io.BytesIO()
    with zipfile.ZipFile(csv_bytes, "w") as zf:
        zf.writestr(
            "2024.csv",
            "certificateNumber,addressLine1,council,registrationDate,propertyTypeDescription,builtForm,constructionAgeBand\n"
            "1,1 Camden Road,Camden,2024-01-01,House,Mid-Terrace,England and Wales: 1900-1929\n"
            "2,2 Oxford Street,Westminster,2024-01-01,House,End-Terrace,England and Wales: before 1900\n"
            "3,3 Broad Street,Bristol,2024-01-01,House,Mid-Terrace,England and Wales: 1900-1929\n"
            "4,4 Camden Road,Camden,2024-01-01,Flat,Mid-Terrace,England and Wales: 1900-1929\n",
        )

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def read(self):
            return self.payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        downloader,
        "_open_download_response",
        lambda url, request_context=None: FakeResponse(csv_bytes.getvalue()),
    )

    df = downloader.download_all_london_boroughs(property_types=["house"])

    assert len(df) == 2
    assert set(df["COUNCIL"]) == {"Camden", "Westminster"}
    assert set(df["PROPERTY_TYPE"]) == {"House"}
    assert set(EPCAPIDownloader.STOCK_DEFINITION_COLUMNS).issubset(df.columns)


def test_apply_edwardian_filters_keeps_only_pre_1930_terraced_houses():
    downloader = EPCAPIDownloader(token="abc123")
    df = pd.DataFrame(
        [
            {
                "UPRN": "keep_mid",
                "PROPERTY_TYPE": "House",
                "BUILT_FORM": "Mid-Terrace",
                "CONSTRUCTION_AGE_BAND": "England and Wales: 1900-1929",
            },
            {
                "UPRN": "drop_flat",
                "PROPERTY_TYPE": "Flat",
                "BUILT_FORM": "Mid-Terrace",
                "CONSTRUCTION_AGE_BAND": "England and Wales: 1900-1929",
            },
            {
                "UPRN": "drop_detached",
                "PROPERTY_TYPE": "House",
                "BUILT_FORM": "Detached",
                "CONSTRUCTION_AGE_BAND": "England and Wales: before 1900",
            },
            {
                "UPRN": "drop_post_1930",
                "PROPERTY_TYPE": "House",
                "BUILT_FORM": "End-Terrace",
                "CONSTRUCTION_AGE_BAND": "1930-1949",
            },
            {
                "UPRN": "keep_end",
                "PROPERTY_TYPE": "House",
                "BUILT_FORM": "Enclosed End-Terrace",
                "CONSTRUCTION_AGE_BAND": "before 1900",
            },
        ]
    )

    filtered = downloader.apply_edwardian_filters(df)

    assert filtered["UPRN"].tolist() == ["keep_mid", "keep_end"]


def test_apply_edwardian_filters_raises_if_required_columns_missing():
    downloader = EPCAPIDownloader(token="abc123")
    df = pd.DataFrame(
        [
            {
                "PROPERTY_TYPE": "House",
                "BUILT_FORM": "Mid-Terrace",
            }
        ]
    )

    with pytest.raises(EPCStockDefinitionError, match="CONSTRUCTION_AGE_BAND"):
        downloader.apply_edwardian_filters(df)


def test_save_data_rejects_filtered_output_identical_to_raw_when_stock_columns_missing(monkeypatch):
    downloader = EPCAPIDownloader(token="abc123")
    output_dir = Path(".tmp_stock_guard")
    output_dir.mkdir(exist_ok=True)
    (output_dir / "epc_london_filtered.csv").unlink(missing_ok=True)
    monkeypatch.setattr("src.acquisition.epc_api_downloader.DATA_RAW_DIR", output_dir)

    raw_df = pd.DataFrame([{"COUNCIL": "Camden"}])

    with pytest.raises(EPCStockDefinitionError, match="Refusing to write epc_london_filtered.csv"):
        downloader.save_data(raw_df.copy(), "epc_london_filtered.csv", raw_df=raw_df)

    assert not (output_dir / "epc_london_filtered.csv").exists()


def test_download_all_london_boroughs_fails_fast_with_borough_context(monkeypatch):
    downloader = EPCAPIDownloader(token="abc123")
    attempted_boroughs = []

    def fake_download_borough_data(borough_name, property_type="house", **kwargs):
        attempted_boroughs.append(borough_name)
        if borough_name == "Camden":
            raise urllib.error.HTTPError(
                url="https://example.test/api/domestic/search",
                code=400,
                msg="Bad Request",
                hdrs=None,
                fp=io.BytesIO(b'{"message":"invalid request for borough"}'),
            )
        return pd.DataFrame([{"COUNCIL": borough_name, "PROPERTY_TYPE": property_type}])

    monkeypatch.setattr(downloader, "download_borough_data", fake_download_borough_data)

    with pytest.raises(EPCDownloadError) as exc_info:
        downloader.download_all_london_boroughs(
            property_types=["house"],
            sample_start_date=date_cls(2024, 1, 1),
            sample_end_date=date_cls(2024, 12, 31),
        )

    error = exc_info.value
    assert error.borough_name == "Camden"
    assert error.property_type == "house"
    assert error.request_mode == "search"
    assert error.http_status == 400
    assert attempted_boroughs[-1] == "Camden"
    assert "City of London" not in attempted_boroughs

    message = str(error)
    assert "Camden" in message
    assert "HTTP 400" in message
    assert "sample_window='2024-01-01 to 2024-12-31'" in message
    assert "request_mode='search'" in message


def test_download_borough_data_distinguishes_network_failures(monkeypatch):
    downloader = EPCAPIDownloader(token="abc123")

    def raise_url_error(request, timeout=60):
        raise urllib.error.URLError("temporary DNS failure")

    monkeypatch.setattr("urllib.request.urlopen", raise_url_error)

    with pytest.raises(EPCDownloadError) as exc_info:
        downloader.download_borough_data(
            "Camden",
            property_type="house",
            sample_start_date=date_cls(2024, 1, 1),
            sample_end_date=date_cls(2024, 12, 31),
            show_progress=False,
        )

    error = exc_info.value
    assert error.failure_kind == "network_error"
    assert error.http_status is None
    assert "Network error while contacting the EPC API" in str(error)
    assert "Camden" in str(error)


def test_download_national_domestic_dataset_ignores_recommendations_and_prunes_years(monkeypatch, tmp_path):
    output_dir = tmp_path / "staged_national_ingest"
    output_dir.mkdir(exist_ok=True)
    monkeypatch.setattr("src.acquisition.epc_api_downloader.DATA_RAW_DIR", output_dir)

    downloader = EPCAPIDownloader(token="abc123", download_mode="full_load")

    csv_bytes = io.BytesIO()
    with zipfile.ZipFile(csv_bytes, "w") as zf:
        zf.writestr(
            "certificates-2014.csv",
            "uprn,lodgement-date,council,property-type,propertyTypeDescription,builtForm,constructionAgeBand\n"
            "old,2014-01-01,Camden,house,House,Mid-Terrace,England and Wales: 1900-1929\n",
        )
        zf.writestr(
            "certificates-2024.csv",
            "uprn,lodgement-date,council,property-type,propertyTypeDescription,builtForm,constructionAgeBand\n"
            "keep,2024-01-01,Camden,house,House,Mid-Terrace,England and Wales: 1900-1929\n",
        )
        zf.writestr(
            "recommendations-2024.csv",
            "uprn,recommendation\nkeep,Insulate loft\n",
        )

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload
            self._offset = 0

        def read(self, size=-1):
            if size is None or size < 0:
                size = len(self.payload) - self._offset
            if self._offset >= len(self.payload):
                return b""
            chunk = self.payload[self._offset:self._offset + size]
            self._offset += size
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        downloader,
        "_open_download_response",
        lambda url, request_context=None: FakeResponse(csv_bytes.getvalue()),
    )

    dataset = downloader.download_national_domestic_dataset(
        sample_start_date=date_cls(2024, 1, 1),
        sample_end_date=date_cls(2024, 12, 31),
    )

    assert dataset.row_count == 1
    assert dataset.metadata["selected_certificate_members"] == ["certificates-2024.csv"]
    assert dataset.metadata["ignored_recommendation_members"] == ["recommendations-2024.csv"]
    assert "certificates-2014.csv" in dataset.metadata["ignored_non_certificate_members"]


def test_download_national_domestic_dataset_counts_skipped_malformed_rows(monkeypatch, tmp_path):
    output_dir = tmp_path / "staged_national_malformed"
    output_dir.mkdir(exist_ok=True)
    monkeypatch.setattr("src.acquisition.epc_api_downloader.DATA_RAW_DIR", output_dir)

    downloader = EPCAPIDownloader(token="abc123", download_mode="full_load")

    csv_bytes = io.BytesIO()
    with zipfile.ZipFile(csv_bytes, "w") as zf:
        zf.writestr(
            "certificates-2024.csv",
            "uprn,lodgement-date,council,propertyTypeDescription,builtForm,constructionAgeBand\n"
            "keep1,2024-01-01,Camden,House,Mid-Terrace,England and Wales: 1900-1929\n"
            "bad,2024-01-02,Camden,House,Mid-Terrace,England and Wales: 1900-1929,unexpected\n"
            "keep2,2024-01-03,Camden,House,End-Terrace,England and Wales: before 1900\n",
        )

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload
            self._offset = 0

        def read(self, size=-1):
            if size is None or size < 0:
                size = len(self.payload) - self._offset
            if self._offset >= len(self.payload):
                return b""
            chunk = self.payload[self._offset:self._offset + size]
            self._offset += size
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        downloader,
        "_open_download_response",
        lambda url, request_context=None: FakeResponse(csv_bytes.getvalue()),
    )

    dataset = downloader.download_national_domestic_dataset(
        sample_start_date=date_cls(2024, 1, 1),
        sample_end_date=date_cls(2024, 12, 31),
    )

    assert dataset.row_count == 2
    assert dataset.metadata["malformed_rows_skipped"] == 1
    processed = dataset.metadata["members_processed"][0]
    assert processed["rows_retained_after_sample_window"] == 2
    assert processed["malformed_rows_skipped"] == 1


def test_materialize_full_load_subset_reuses_cached_stage_with_sidecar_files(monkeypatch, tmp_path):
    output_dir = tmp_path / "staged_national_reuse"
    output_dir.mkdir(exist_ok=True)
    monkeypatch.setattr("src.acquisition.epc_api_downloader.DATA_RAW_DIR", output_dir)

    downloader = EPCAPIDownloader(token="abc123", download_mode="full_load")
    stage_dir = output_dir / "staged" / "domestic_full_load_2024-01-01_2024-12-31"
    dataset_dir = _write_parquet_dataset_dir(
        stage_dir / "raw_certificates_dataset",
        pd.DataFrame(
            [
                {
                    "UPRN": "1",
                    "COUNCIL": "Camden",
                    "PROPERTY_TYPE": "House",
                    "BUILT_FORM": "Mid-Terrace",
                    "CONSTRUCTION_AGE_BAND": "England and Wales: 1900-1929",
                },
                {
                    "UPRN": "2",
                    "COUNCIL": "Bristol",
                    "PROPERTY_TYPE": "Flat",
                    "BUILT_FORM": "Detached",
                    "CONSTRUCTION_AGE_BAND": "1930-1949",
                },
            ]
        ),
    )
    manifest_path = stage_dir / "ingest_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "rows_retained_after_sample_window": 2,
                "selected_certificate_members": ["certificates-2024.csv"],
                "ignored_recommendation_members": [],
                "ignored_non_certificate_members": [],
                "malformed_rows_skipped": 0,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        downloader,
        "_download_file_to_path",
        lambda *args, **kwargs: pytest.fail("cached staged reuse should not download a new full-load ZIP"),
    )

    cached = downloader.download_national_domestic_dataset(
        sample_start_date=date_cls(2024, 1, 1),
        sample_end_date=date_cls(2024, 12, 31),
    )
    subset = downloader.materialize_full_load_subset(
        cached,
        output_dir / "camden_subset.parquet",
        dataset_name="camden_subset",
        borough_names=["Camden"],
        property_types=["house"],
    )

    subset_df = subset.load_dataframe()

    assert cached.parquet_path == dataset_dir
    assert subset.row_count == 1
    assert subset_df["UPRN"].tolist() == ["1"]
    assert subset_df["COUNCIL"].tolist() == ["Camden"]


def test_download_national_domestic_dataset_follows_signed_redirect_without_forwarding_auth(monkeypatch, tmp_path):
    output_dir = tmp_path / "full_load_redirect_signed"
    output_dir.mkdir(exist_ok=True)
    monkeypatch.setattr("src.acquisition.epc_api_downloader.DATA_RAW_DIR", output_dir)

    downloader = EPCAPIDownloader(token="abc123", download_mode="full_load")
    requests_seen = []
    signed_url = (
        "https://epc-downloads.s3.amazonaws.com/domestic/certificates.zip"
        "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=test"
    )

    monkeypatch.setattr(
        "urllib.request.build_opener",
        lambda *args: FakeManualRedirectOpener(
            [
                _redirect_http_error(downloader.FULL_LOAD_URL, signed_url),
                FakeStreamingResponse(_build_test_full_load_zip()),
            ],
            requests_seen,
        ),
    )

    dataset = downloader.download_national_domestic_dataset(
        sample_start_date=date_cls(2024, 1, 1),
        sample_end_date=date_cls(2024, 12, 31),
        force_refresh=True,
    )

    assert dataset.row_count == 1
    assert requests_seen[0]["url"] == downloader.FULL_LOAD_URL
    assert requests_seen[0]["headers"]["Authorization"] == "Bearer abc123"
    assert requests_seen[0]["headers"]["Accept"] == "application/json"
    assert requests_seen[1]["url"] == signed_url
    assert "Authorization" not in requests_seen[1]["headers"]
    assert "Accept" not in requests_seen[1]["headers"]


def test_download_national_domestic_dataset_strips_auth_on_cross_host_redirect(monkeypatch, tmp_path):
    output_dir = tmp_path / "full_load_redirect_cross_host"
    output_dir.mkdir(exist_ok=True)
    monkeypatch.setattr("src.acquisition.epc_api_downloader.DATA_RAW_DIR", output_dir)

    downloader = EPCAPIDownloader(token="abc123", download_mode="full_load")
    requests_seen = []
    redirected_url = "https://downloads.example.com/domestic/certificates.zip"

    monkeypatch.setattr(
        "urllib.request.build_opener",
        lambda *args: FakeManualRedirectOpener(
            [
                _redirect_http_error(downloader.FULL_LOAD_URL, redirected_url),
                FakeStreamingResponse(_build_test_full_load_zip()),
            ],
            requests_seen,
        ),
    )

    dataset = downloader.download_national_domestic_dataset(
        sample_start_date=date_cls(2024, 1, 1),
        sample_end_date=date_cls(2024, 12, 31),
        force_refresh=True,
    )

    assert dataset.row_count == 1
    assert requests_seen[0]["headers"]["Authorization"] == "Bearer abc123"
    assert requests_seen[1]["url"] == redirected_url
    assert "Authorization" not in requests_seen[1]["headers"]


def test_download_national_domestic_dataset_raises_clear_error_when_redirect_location_missing(monkeypatch, tmp_path):
    output_dir = tmp_path / "full_load_redirect_missing_location"
    output_dir.mkdir(exist_ok=True)
    monkeypatch.setattr("src.acquisition.epc_api_downloader.DATA_RAW_DIR", output_dir)

    downloader = EPCAPIDownloader(token="abc123", download_mode="full_load")
    requests_seen = []

    monkeypatch.setattr(
        "urllib.request.build_opener",
        lambda *args: FakeManualRedirectOpener(
            [_redirect_http_error(downloader.FULL_LOAD_URL)],
            requests_seen,
        ),
    )

    with pytest.raises(EPCDownloadError, match="Location header") as exc_info:
        downloader.download_national_domestic_dataset(
            sample_start_date=date_cls(2024, 1, 1),
            sample_end_date=date_cls(2024, 12, 31),
            force_refresh=True,
        )

    assert exc_info.value.failure_kind == "unexpected"
    assert requests_seen[0]["headers"]["Authorization"] == "Bearer abc123"


def test_download_borough_data_stops_when_next_page_overshoots_reported_last_page(monkeypatch):
    downloader = EPCAPIDownloader(token="abc123")
    requested_pages = []

    def fake_request_json(url, params, retries=6, request_context=None):
        page = params["current_page"]
        requested_pages.append(page)
        return {
            "data": [
                {
                    "certificateNumber": str(page),
                    "council": "Kensington and Chelsea",
                    "registrationDate": "2024-01-01",
                }
            ],
            "pagination": {
                "currentPage": page,
                "nextPage": page + 1,
                "totalPages": 13,
            },
        }

    monkeypatch.setattr(downloader, "_request_json", fake_request_json)

    df = downloader.download_borough_data(
        "Kensington and Chelsea",
        property_type="house",
        show_progress=False,
    )

    assert len(df) == 13
    assert requested_pages == list(range(1, 14))


def test_download_borough_data_treats_terminal_out_of_range_page_as_end_of_pagination(monkeypatch):
    downloader = EPCAPIDownloader(token="abc123")
    requested_pages = []

    def fake_request_json(url, params, retries=6, request_context=None):
        page = params["current_page"]
        requested_pages.append(page)
        if page <= 13:
            return {
                "data": [
                    {
                        "certificateNumber": str(page),
                        "council": "Kensington and Chelsea",
                        "registrationDate": "2024-01-01",
                    }
                ],
                "pagination": {
                    "nextPage": page + 1,
                },
            }

        raise EPCDownloadError.from_http_error(
            request_context,
            urllib.error.HTTPError(
                url="https://example.test/api/domestic/search",
                code=400,
                msg="Bad Request",
                hdrs=None,
                fp=io.BytesIO(
                    b'{"data":{"error":"The requested page number 14 is out of range. Please provide a page number between 1 and 13."}}'
                ),
            ),
        )

    monkeypatch.setattr(downloader, "_request_json", fake_request_json)

    df = downloader.download_borough_data(
        "Kensington and Chelsea",
        property_type="house",
        show_progress=False,
    )

    assert len(df) == 13
    assert requested_pages == list(range(1, 15))
