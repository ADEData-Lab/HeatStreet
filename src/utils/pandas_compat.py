"""Pandas compatibility helpers for safely materialising Arrow-backed data."""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable

import pandas as pd


_ORIGINAL_READ_PARQUET: Callable[..., pd.DataFrame] | None = None
_ORIGINAL_SERIES_EQUALS: Callable[..., bool] | None = None


def detach_arrow_backed_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a DataFrame whose Arrow-backed extension columns use Python storage.

    Some Windows pandas/pyarrow combinations can successfully read a staged Parquet
    dataset but then raise ``Out of bounds on buffer access (axis 0)`` during ordinary
    string filtering or grouping. Converting Arrow-backed extension columns to Python
    backed equivalents immediately after materialisation removes that dependency on the
    original Arrow buffers while preserving null values and column semantics.
    """
    if df is None or df.empty:
        return df

    detached = df.copy(deep=True)
    for column in detached.columns:
        dtype = detached[column].dtype
        dtype_text = str(dtype).casefold()
        storage = str(getattr(dtype, "storage", "")).casefold()
        is_arrow_backed = "pyarrow" in dtype_text or storage == "pyarrow"
        if not is_arrow_backed:
            continue

        if pd.api.types.is_string_dtype(dtype):
            detached[column] = detached[column].astype("string[python]")
        else:
            detached[column] = detached[column].astype(object)

    return detached


def install_safe_read_parquet() -> None:
    """Wrap ``pandas.read_parquet`` so staged datasets are detached on read."""
    global _ORIGINAL_READ_PARQUET
    if getattr(pd.read_parquet, "_heatstreet_safe_read", False):
        return

    _ORIGINAL_READ_PARQUET = pd.read_parquet

    @wraps(_ORIGINAL_READ_PARQUET)
    def safe_read_parquet(*args: Any, **kwargs: Any) -> pd.DataFrame:
        frame = _ORIGINAL_READ_PARQUET(*args, **kwargs)
        return detach_arrow_backed_columns(frame)

    safe_read_parquet._heatstreet_safe_read = True  # type: ignore[attr-defined]
    pd.read_parquet = safe_read_parquet


def install_boolean_series_equals_compat() -> None:
    """Make Boolean ``Series.equals`` compare values rather than storage backends.

    Pandas can report unequal Series when one Boolean mask uses NumPy storage and the
    other uses a nullable or Arrow-backed Boolean dtype, even though their indexes and
    elementwise values are identical. HeatStreet semantic QA compares technology masks
    produced through both routes. Normalising only Boolean-like operands to pandas'
    nullable Boolean dtype avoids false publication failures while preserving the
    standard pandas behaviour for all other Series.
    """
    global _ORIGINAL_SERIES_EQUALS
    if getattr(pd.Series.equals, "_heatstreet_boolean_compat", False):
        return

    _ORIGINAL_SERIES_EQUALS = pd.Series.equals

    @wraps(_ORIGINAL_SERIES_EQUALS)
    def compatible_equals(left: pd.Series, right: object) -> bool:
        result = _ORIGINAL_SERIES_EQUALS(left, right)
        if result or not isinstance(right, pd.Series):
            return result
        if not left.index.equals(right.index):
            return False
        if not (
            pd.api.types.is_bool_dtype(left.dtype)
            and pd.api.types.is_bool_dtype(right.dtype)
        ):
            return False
        return left.astype("boolean").equals(right.astype("boolean"))

    compatible_equals._heatstreet_boolean_compat = True  # type: ignore[attr-defined]
    pd.Series.equals = compatible_equals
