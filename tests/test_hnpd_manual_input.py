"""Regression tests for the manually supplied HNPD input contract."""

from __future__ import annotations

import csv

from src.acquisition.hnpd_downloader import HNPDDownloader


EXPECTED_FILENAME = "heat_networks_procurement_pipeline_Q1_2026.csv"


def _config():
    return {
        "data_sources": {
            "heat_networks": {
                "hnpd": {
                    "filename": EXPECTED_FILENAME,
                    "download_page": "https://www.gov.uk/government/publications/heat-networks-pipelines",
                    "region_filter": "London",
                    "tier_1_statuses": ["Operational", "Under Construction"],
                    "tier_2_statuses": ["Planning Permission Granted", "Appeal Granted"],
                }
            }
        }
    }


def test_missing_hnpd_file_gives_manual_download_instructions(tmp_path):
    downloader = HNPDDownloader(_config(), external_dir=tmp_path)

    summary = downloader.get_data_summary()

    assert summary["available"] is False
    assert EXPECTED_FILENAME in summary["message"]
    assert str(tmp_path) in summary["message"]
    assert "Download it manually" in summary["message"]
    assert "heat-networks-pipelines" in summary["message"]
    assert downloader.download_and_prepare() is False


def test_q1_2026_schema_is_accepted_and_fingerprinted(tmp_path):
    csv_path = tmp_path / EXPECTED_FILENAME
    headers = [
        "Ref ID",
        "Site Name",
        "Region",
        "Development Status",
        "Development Status (short)",
        "X-coordinate",
        "Y-coordinate",
    ]
    rows = [
        ["1", "Existing London scheme", "London", "Operational", "Operational", "530000", "180000"],
        ["2", "Planned London scheme", "London", "Planning Permission Granted", "Awaiting Construction", "531000", "181000"],
        ["3", "Outside London", "South East", "Under Construction", "Under Construction", "550000", "150000"],
    ]
    with csv_path.open("w", encoding="latin-1", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)

    downloader = HNPDDownloader(_config(), external_dir=tmp_path)
    validation = downloader.validate_hnpd_file()
    summary = downloader.get_data_summary()

    assert validation["valid"] is True
    assert validation["rows"] == 3
    assert validation["london_rows"] == 2
    assert validation["london_coordinates_available"] == 2
    assert len(validation["sha256"]) == 64
    assert validation["size_bytes"] == csv_path.stat().st_size
    assert summary["tier_1_networks"] == 2
    assert summary["tier_2_networks"] == 1
