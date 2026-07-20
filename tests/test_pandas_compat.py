"""Regression tests for Arrow-backed pandas materialisation."""

from __future__ import annotations

import pandas as pd

from src.utils.pandas_compat import (
    detach_arrow_backed_columns,
    install_safe_read_parquet,
)


def test_detach_arrow_backed_string_columns_uses_python_storage():
    frame = pd.DataFrame(
        {
            "ADDRESS1": pd.Series(
                ["1 Shakespeare Crescent", None, "3 Shakespeare Crescent"],
                dtype="string[pyarrow]",
            ),
            "value": [1, 2, 3],
        }
    )

    detached = detach_arrow_backed_columns(frame)

    assert str(detached["ADDRESS1"].dtype) == "string"
    assert getattr(detached["ADDRESS1"].dtype, "storage", None) == "python"
    assert detached["ADDRESS1"].str.contains("Shakespeare", na=False).tolist() == [
        True,
        False,
        True,
    ]
    assert detached["value"].tolist() == [1, 2, 3]


def test_install_safe_read_parquet_is_idempotent():
    install_safe_read_parquet()
    wrapped = pd.read_parquet

    install_safe_read_parquet()

    assert pd.read_parquet is wrapped
    assert getattr(pd.read_parquet, "_heatstreet_safe_read", False) is True


def test_boolean_series_equals_ignores_backend_dtype_when_values_match():
    left = pd.Series([True, False, True], dtype=bool)
    right = pd.Series([True, False, True], dtype="boolean")

    assert left.equals(right) is True


def test_boolean_series_equals_still_detects_value_mismatch():
    left = pd.Series([True, False, True], dtype=bool)
    right = pd.Series([True, True, True], dtype="boolean")

    assert left.equals(right) is False
