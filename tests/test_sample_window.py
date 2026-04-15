from datetime import date
from pathlib import Path

import pandas as pd

from run_analysis import (
    compute_sample_start_date,
    sample_window_matches,
    validate_start_date,
    write_sample_window_metadata,
)
from src.acquisition.epc_api_downloader import EPCAPIDownloader


def test_compute_sample_start_date_uses_exact_ten_year_window():
    assert compute_sample_start_date(date(2026, 3, 27)) == date(2016, 3, 27)


def test_compute_sample_start_date_handles_leap_day():
    assert compute_sample_start_date(date(2024, 2, 29)) == date(2014, 2, 28)


def test_validate_start_date_rejects_dates_after_end_date():
    assert validate_start_date("2026-03-28", date(2026, 3, 27)) == (
        "Start date cannot be after end date (2026-03-27)"
    )


def test_sample_window_matches_requires_exact_metadata_match(tmp_path):
    dataset_path = tmp_path / "epc_london_filtered.csv"
    dataset_path.write_text("id\n1\n", encoding="utf-8")

    write_sample_window_metadata(
        dataset_path,
        sample_start_date=date(2016, 3, 27),
        sample_end_date=date(2026, 3, 27),
        dataset_type="filtered_epc_download",
    )

    assert sample_window_matches(
        dataset_path,
        sample_start_date=date(2016, 3, 27),
        sample_end_date=date(2026, 3, 27),
    )
    assert not sample_window_matches(
        dataset_path,
        sample_start_date=date(2016, 3, 26),
        sample_end_date=date(2026, 3, 27),
    )


def test_apply_sample_window_filter_is_inclusive_and_falls_back_to_inspection_date():
    downloader = EPCAPIDownloader(email="user@example.com", api_key="abcdefghij")
    df = pd.DataFrame(
        [
            {
                "uprn": "inside_lodgement",
                "lodgement-date": "2020-01-15",
                "inspection-date": "2020-01-10",
            },
            {
                "uprn": "inside_inspection_fallback",
                "lodgement-date": None,
                "inspection-date": "2016-03-27",
            },
            {
                "uprn": "before_window",
                "lodgement-date": "2016-03-26",
                "inspection-date": "2016-03-26",
            },
            {
                "uprn": "after_window",
                "lodgement-date": "2026-03-28",
                "inspection-date": "2026-03-28",
            },
            {
                "uprn": "on_end_boundary",
                "lodgement-date": "2026-03-27",
                "inspection-date": "2026-03-27",
            },
        ]
    )

    filtered = downloader._apply_sample_window_filter(
        df,
        sample_start_date=date(2016, 3, 27),
        sample_end_date=date(2026, 3, 27),
    )

    assert filtered["uprn"].tolist() == [
        "inside_lodgement",
        "inside_inspection_fallback",
        "on_end_boundary",
    ]
