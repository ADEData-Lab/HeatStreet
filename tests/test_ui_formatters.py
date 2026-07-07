from pathlib import Path

from src.ui.formatters import (
    format_bytes,
    format_count,
    format_duration,
    format_path,
    format_percent,
    phase_label,
    safe_text,
    status_label,
)


def test_format_count_percent_duration_and_bytes():
    assert format_count(1234567) == "1,234,567"
    assert format_percent(12.345) == "12.3%"
    assert format_duration(4.25) == "4.2s"
    assert format_duration(125) == "2m 05s"
    assert format_bytes(1024) == "1.0 KiB"
    assert format_bytes(1536 * 1024) == "1.5 MiB"


def test_format_path_truncates_from_left():
    path = Path("C:/very/long/path/with/many/segments/output.parquet")
    formatted = format_path(path, max_length=24)
    assert formatted.startswith("...")
    assert formatted.endswith("output.parquet")
    assert len(formatted) <= 24


def test_safe_text_ascii_and_labels():
    assert safe_text("Ready\nNow\t✓") == "Ready Now ?"
    assert safe_text("A\u2013B\u2014C") == "A-B-C"
    assert status_label("in-progress") == "RUN"
    assert status_label("completed") == "DONE"
    assert status_label("skipped") == "SKIP"
    assert phase_label("A" * 80).endswith("...")
