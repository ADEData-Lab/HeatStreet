import io
import re
import shutil
import ssl
import urllib.error
from pathlib import Path

import pytest

from src.acquisition.london_gis_downloader import (
    LondonGISDownloadError,
    LondonGISDownloader,
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


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self, size=-1):
        if size is None or size < 0:
            return self.payload
        chunk = self.payload[:size]
        self.payload = self.payload[size:]
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _patch_gis_paths(monkeypatch, tmp_path):
    external_dir = tmp_path / "external"
    gis_dir = external_dir / "london_gis"
    monkeypatch.setattr("src.acquisition.london_gis_downloader.EXTERNAL_DIR", external_dir)
    monkeypatch.setattr("src.acquisition.london_gis_downloader.GIS_DIR", gis_dir)
    return external_dir


def test_extract_download_url_from_resource_page_html():
    resource_page_html = """
    <html>
      <body>
        <a href="/download/new-resource-id/updated-resource/GIS_All_Data.zip">Download GIS package</a>
      </body>
    </html>
    """

    resolved = LondonGISDownloader._extract_download_url_from_html(
        resource_page_html,
        base_url=LondonGISDownloader.GIS_RESOURCE_PAGE_URL,
    )

    assert resolved == "https://data.london.gov.uk/download/new-resource-id/updated-resource/GIS_All_Data.zip"


def test_resource_page_url_is_not_stale_direct_download():
    assert "/download/2ogw5/" not in LondonGISDownloader.GIS_RESOURCE_PAGE_URL
    assert all("/download/2ogw5/" not in url for url in LondonGISDownloader.GIS_FALLBACK_DOWNLOAD_URLS)


def test_resolve_download_url_distinguishes_resource_page_fetch_failures(monkeypatch, tmp_path):
    _patch_gis_paths(monkeypatch, tmp_path)
    downloader = LondonGISDownloader()

    def raise_url_error(request, context=None, timeout=60):
        raise urllib.error.URLError("temporary London Datastore outage")

    monkeypatch.setattr("urllib.request.urlopen", raise_url_error)

    with pytest.raises(LondonGISDownloadError) as exc_info:
        downloader.resolve_download_url()

    assert exc_info.value.failure_kind == "resource_page_fetch"
    assert "resource page" in str(exc_info.value)


def test_resolve_download_url_distinguishes_download_link_parse_failures(monkeypatch, tmp_path):
    _patch_gis_paths(monkeypatch, tmp_path)
    downloader = LondonGISDownloader()

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, context=None, timeout=60: FakeResponse(b"<html><body>No GIS zip here</body></html>"),
    )

    with pytest.raises(LondonGISDownloadError) as exc_info:
        downloader.resolve_download_url()

    assert exc_info.value.failure_kind == "download_link_parse"
    assert "GIS_All_Data.zip" in str(exc_info.value)


def test_download_gis_data_distinguishes_file_download_failures(monkeypatch, tmp_path):
    external_dir = _patch_gis_paths(monkeypatch, tmp_path)
    downloader = LondonGISDownloader()
    resolved_url = "https://downloads.example.com/current/GIS_All_Data.zip"

    monkeypatch.setattr(
        LondonGISDownloader,
        "resolve_download_url",
        lambda self: resolved_url,
    )

    def raise_http_error(request, context=None, timeout=300):
        raise urllib.error.HTTPError(
            url=resolved_url,
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=io.BytesIO(b"missing"),
        )

    monkeypatch.setattr("urllib.request.urlopen", raise_http_error)

    assert downloader.download_gis_data(force_redownload=True) is False
    assert downloader.last_error is not None
    assert downloader.last_error.failure_kind == "file_download"
    assert "GIS_All_Data.zip" in str(downloader.last_error)
    assert not (external_dir / "GIS_All_Data.zip").exists()


def test_download_gis_data_falls_back_to_direct_url_when_resource_page_fetch_is_blocked(monkeypatch, tmp_path):
    external_dir = _patch_gis_paths(monkeypatch, tmp_path)
    downloader = LondonGISDownloader()
    requests_seen = []
    fallback_url = LondonGISDownloader.GIS_FALLBACK_DOWNLOAD_URLS[0]

    def fake_urlopen(request, context=None, timeout=60):
        requests_seen.append(
            {
                "url": request.full_url,
                "headers": dict(request.header_items()),
            }
        )
        if request.full_url in LondonGISDownloader.GIS_RESOURCE_PAGE_CANDIDATES:
            raise urllib.error.HTTPError(
                url=request.full_url,
                code=403,
                msg="Forbidden",
                hdrs=None,
                fp=io.BytesIO(b"blocked"),
            )
        if request.full_url == fallback_url:
            return FakeResponse(b"zip-payload")
        raise AssertionError(f"Unexpected URL: {request.full_url}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert downloader.download_gis_data(force_redownload=True) is True
    assert (external_dir / "GIS_All_Data.zip").read_bytes() == b"zip-payload"
    assert any(entry["url"] == fallback_url for entry in requests_seen)
    assert all(
        next(
            value
            for key, value in entry["headers"].items()
            if key.lower() == "user-agent"
        ).startswith("Mozilla/5.0")
        for entry in requests_seen
    )


def test_download_gis_data_handles_ssl_context_creation_failure(monkeypatch, tmp_path):
    external_dir = _patch_gis_paths(monkeypatch, tmp_path)
    downloader = LondonGISDownloader()

    monkeypatch.setattr(
        "ssl.create_default_context",
        lambda: (_ for _ in ()).throw(ssl.SSLError("[ASN1: NOT_ENOUGH_DATA] not enough data")),
    )

    assert downloader.download_gis_data(force_redownload=True) is False
    assert downloader.last_error is not None
    assert downloader.last_error.failure_kind == "file_download"
    assert "ASN1" in str(downloader.last_error)
    assert not (external_dir / "GIS_All_Data.zip").exists()
