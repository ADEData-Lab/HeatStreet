"""Shared utility initialisation for HeatStreet."""

from src.utils.pandas_compat import install_safe_read_parquet

# Staged EPC datasets can materialise as Arrow-backed pandas extension arrays on
# Windows. Detach those buffers immediately after every Parquet read so ordinary
# reporting operations do not fail later with an Arrow buffer bounds error.
install_safe_read_parquet()
