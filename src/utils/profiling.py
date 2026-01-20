"""
Profiling Utilities for HeatStreet Pipeline

Provides lightweight instrumentation for timing and memory monitoring,
controlled by the HEATSTREET_PROFILE environment variable.

Usage:
    export HEATSTREET_PROFILE=1  # Enable profiling
    python run_analysis.py       # See timing/memory logs

Key functions:
    - get_rss_mb(): Get current process RSS in MB
    - log_memory(label): Log memory usage at a checkpoint
    - timed_section(name): Context manager for timing code blocks
    - profile_enabled(): Check if profiling is enabled
"""

import os
import time
from contextlib import contextmanager
from typing import Optional
from loguru import logger


def profile_enabled() -> bool:
    """Check if profiling is enabled via HEATSTREET_PROFILE environment variable."""
    return os.environ.get('HEATSTREET_PROFILE', '').lower() in ('1', 'true', 'yes')


def get_rss_mb() -> float:
    """
    Get current process Resident Set Size (RSS) in megabytes.

    Uses psutil if available, otherwise falls back to /proc/self/status on Linux.
    Returns 0.0 if memory info cannot be retrieved.
    """
    # Try psutil first (cross-platform)
    try:
        import psutil
        process = psutil.Process()
        return process.memory_info().rss / (1024 * 1024)
    except ImportError:
        pass

    # Fallback to /proc/self/status on Linux
    try:
        with open('/proc/self/status', 'r') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    # Format: "VmRSS:    123456 kB"
                    parts = line.split()
                    if len(parts) >= 2:
                        kb = int(parts[1])
                        return kb / 1024
    except (OSError, IOError, ValueError):
        pass

    return 0.0


def log_memory(label: str, force: bool = False) -> float:
    """
    Log current memory usage with a label.

    Args:
        label: Description of the checkpoint
        force: If True, log even when HEATSTREET_PROFILE is not set

    Returns:
        Current RSS in MB
    """
    if not force and not profile_enabled():
        return 0.0

    rss_mb = get_rss_mb()
    if rss_mb > 0:
        logger.info(f"[MEMORY] {label}: {rss_mb:.1f} MB RSS")
    return rss_mb


@contextmanager
def timed_section(name: str, force: bool = False):
    """
    Context manager that logs the time spent in a code section.

    Args:
        name: Name of the section being timed
        force: If True, log even when HEATSTREET_PROFILE is not set

    Usage:
        with timed_section("Data loading"):
            data = load_data()
    """
    if not force and not profile_enabled():
        yield
        return

    start_time = time.time()
    start_rss = get_rss_mb()
    logger.info(f"[PROFILE] {name} - START (RSS: {start_rss:.1f} MB)")

    try:
        yield
    finally:
        elapsed = time.time() - start_time
        end_rss = get_rss_mb()
        delta_rss = end_rss - start_rss
        delta_str = f"+{delta_rss:.1f}" if delta_rss >= 0 else f"{delta_rss:.1f}"
        logger.info(f"[PROFILE] {name} - DONE in {elapsed:.2f}s (RSS: {end_rss:.1f} MB, {delta_str} MB)")


def log_dataframe_info(df, name: str = "DataFrame", force: bool = False) -> None:
    """
    Log basic info about a DataFrame for debugging.

    Args:
        df: pandas DataFrame or GeoDataFrame
        name: Name to identify the DataFrame
        force: If True, log even when HEATSTREET_PROFILE is not set
    """
    if not force and not profile_enabled():
        return

    try:
        import pandas as pd
        if not isinstance(df, pd.DataFrame):
            return

        rows = len(df)
        cols = len(df.columns)
        memory_mb = df.memory_usage(deep=True).sum() / (1024 * 1024)
        logger.info(f"[PROFILE] {name}: {rows:,} rows, {cols} cols, ~{memory_mb:.1f} MB")
    except Exception:
        pass


def log_dtype(series_or_col, name: str = "Column", force: bool = False) -> None:
    """
    Log the dtype of a Series or column for debugging join issues.

    Args:
        series_or_col: pandas Series or column
        name: Name to identify the column
        force: If True, log even when HEATSTREET_PROFILE is not set
    """
    if not force and not profile_enabled():
        return

    try:
        dtype = series_or_col.dtype
        logger.info(f"[PROFILE] {name} dtype: {dtype}")
    except Exception:
        pass


# Configuration getters for scaling parameters
def get_worker_count(default: int = 2) -> int:
    """
    Get worker count from HEATSTREET_WORKERS env var.

    Args:
        default: Default worker count if env var not set

    Returns:
        Number of workers to use for parallel processing
    """
    try:
        return int(os.environ.get('HEATSTREET_WORKERS', default))
    except (ValueError, TypeError):
        return default


def get_chunk_size(default: int = 50000) -> int:
    """
    Get chunk size from HEATSTREET_CHUNK_SIZE env var.

    Args:
        default: Default chunk size if env var not set

    Returns:
        Number of rows per chunk for batch processing
    """
    try:
        return int(os.environ.get('HEATSTREET_CHUNK_SIZE', default))
    except (ValueError, TypeError):
        return default
