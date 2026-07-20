"""Pandas compatibility helpers for safely materialising Arrow-backed data."""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable

import pandas as pd


_ORIGINAL_READ_PARQUET: Callable[..., pd.DataFrame] | None = None


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
