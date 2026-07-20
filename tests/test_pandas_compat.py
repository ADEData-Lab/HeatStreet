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
               