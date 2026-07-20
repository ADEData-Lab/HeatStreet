"""Regression tests for HNPD ingestion and proximity tier assignment."""

from __future__ import annotations

import copy
import csv

import geopandas as gpd
from shapely.geometry import Point

from config.config import load_config
from src.acquisition.hnpd_downloader import HNPDDownloader
from src.spatial.heat_network_analysis import HeatNetworkAnalyzer


def _write_hnpd_csv(path, rows):
    headers = [
        "\ufeffRef ID",
        " Region ",
        "Development Status",
        "Development Status (short)",
        "X-coordinate",
        "Y-coordinate",
        "Site Name",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)


def _test_config(filename):
    return {
        "data_sources": {
            "heat_networks": {
                "hnpd": {
                    "url": f"https://example.test/{filename}",
                    "filename": filename,
                    "region_filter": "London",
                    "tier_1_statuses": ["Operational", "Under Construction"],
                    "tier_2_statuses": ["Planning Permission Granted"],
                }
            }
        }
    }


def test_hnpd_loader_normalises_headers_regions_statuses_and_coordinates(tmp_path):
    csv_path = tmp_path / "hnpd.csv"
    _write_hnpd_csv(
        csv_path,
        [
            [
                "1",
                " london ",
                "Planning Permission Granted ",
                "Awaiting Construction",
                "536540",
                "176850",
                "Planned scheme",
            ],
            [
                "2",
                "LONDON",
                "Under Construction",
                "Under Construction",
                "520253",
                "182801",
                "Existing scheme",
            ],
            [
                "3",
                "London",
                "Not set",
                "Operational",
                "542539",
                "174571",
                "Short-status fallback",
            ],
            [
                "4",
                "South East",
                "Operational",
                "Operational",
                "558364",
                "139982",
                "Outside region",
            ],
        ],
    )

    downloader = HNPDDownloader(
        _test_config(csv_path.name),
        external_dir=tmp_path,
    )

    validation = downloader.validate_hnpd_file()
    assert validation["valid"] is True
    assert validation["coordinates_available"] == 4

    london_rows = downloader.load_hnpd_csv(region_filter=" London ")
    assert len(london_rows) == 3

    tier_1 = downloader.get_tier_1_networks(region="london")
    tier_2 = downloader.get_tier_2_networks(region="LONDON")

    assert tier_1 is not None
    assert tier_2 is not None
    assert set(tier_1["Site Name"]) == {
        "Existing scheme",
        "Short-status fallback",
    }
    assert tier_2["Site Name"].tolist() == ["Planned scheme"]
    assert tier_1.crs.to_epsg() == 27700
    assert tier_2.crs.to_epsg() == 27700


def test_existing_invalid_hnpd_file_is_not_reported_as_available(tmp_path):
    csv_path = tmp_path / "hnpd.csv"
    csv_path.write_text("<html>not a csv</html>", encoding="utf-8")

    downloader = HNPDDownloader(
        _test_config(csv_path.name),
        external_dir=tmp_path,
    )

    summary = downloader.get_data_summary()
    assert summary["available"] is False
    assert (
        "no data rows" in summary["message"].lower()
        or "missing required columns" in summary["message"].lower()
    )


def test_hnpd_points_assign_properties_to_configured_proximity_tiers():
    config = copy.deepcopy(load_config())
    config.setdefault("spatial", {})["disable"] = True
    analyzer = HeatNetworkAnalyzer(config=config)

    properties = gpd.GeoDataFrame(
        {
            "property_id": ["existing-nearby", "planned-nearby", "not-nearby"],
            "geometry": [
                Point(530100, 180000),
                Point(531400, 180000),
                Point(533000, 180000),
            ],
        },
        crs="EPSG:27700",
    )
    existing = gpd.GeoDataFrame(
        {"scheme": ["existing"], "geometry": [Point(530000, 180000)]},
        crs="EPSG:27700",
    )
    planned = gpd.GeoDataFrame(
        {"scheme": ["planned"], "geometry": [Point(531000, 180000)]},
        crs="EPSG:27700",
    )

    classified = analyzer.classify_heat_network_tiers(
        properties,
        heat_networks=existing,
        heat_zones=planned,
    ).set_index("property_id")

    assert classified.loc["existing-nearby", "tier_number"] == 1
    assert classified.loc["planned-nearby", "tier_number"] == 2
    assert classified.loc["not-nearby", "tier_number"] == 5
