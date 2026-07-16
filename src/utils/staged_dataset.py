"""
Helpers for dataset-backed large-run processing.

The full EPC domestic extract is too large to treat as a single in-memory
DataFrame. This module provides a lightweight reference object plus utilities
for Parquet staging, DuckDB materialisation, and chunked iteration.
"""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Optional

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
from loguru import logger

try:
    import duckdb
except ImportError:  # pragma: no cover - exercised only when dependency missing
    duckdb = None


def _stringify_path(path: Optional[Path]) -> Optional[str]:
    return str(path) if path is not None else None


def _absolute_path_text(path: Path) -> str:
    try:
        return str(Path(path).resolve())
    except Exception:
        return str(path)


def _filesystem_error(path: Path, *, operation: str, error: OSError) -> RuntimeError:
    return RuntimeError(
        f"Filesystem error while {operation} at {_absolute_path_text(path)}: {error}"
    )


def parquet_dataset_source(parquet_path: Path) -> str | list[str]:
    """Return the concrete Parquet source(s) for a file or dataset directory."""
    parquet_path = Path(parquet_path)
    if parquet_path.is_dir():
        sources = [
            path.as_posix()
            for path in sorted(parquet_path.glob("*.parquet"))
            if path.is_file()
        ]
        if not sources:
            raise FileNotFoundError(f"No Parquet files found in dataset directory: {parquet_path}")
        return sources
    return parquet_path.as_posix()


def parquet_dataset_exists(parquet_path: Path) -> bool:
    """Return True when a Parquet file or dataset directory is present."""
    parquet_path = Path(parquet_path)
    if parquet_path.is_file():
        return parquet_path.suffix.casefold() == ".parquet"
    if parquet_path.is_dir():
        return any(path.is_file() for path in parquet_path.glob("*.parquet"))
    return False


def _parquet_dataset(parquet_path: Path) -> ds.Dataset:
    """Build a PyArrow dataset from the staged Parquet source."""
    return ds.dataset(parquet_dataset_source(parquet_path), format="parquet")


@dataclass
class DatasetReference:
    """Reference to a staged dataset on disk."""

    name: str
    parquet_path: Path
    stage: str
    row_count: Optional[int] = None
    csv_path: Optional[Path] = None
    manifest_path: Optional[Path] = None
    sample_start_date: Optional[str] = None
    sample_end_date: Optional[str] = None
    storage_kind: str = "parquet"
    is_large_run: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def exists(self) -> bool:
        return parquet_dataset_exists(self.parquet_path)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "stage": self.stage,
            "row_count": self.row_count,
            "parquet_path": _stringify_path(self.parquet_path),
            "csv_path": _stringify_path(self.csv_path),
            "manifest_path": _stringify_path(self.manifest_path),
            "sample_start_date": self.sample_start_date,
            "sample_end_date": self.sample_end_date,
            "storage_kind": self.storage_kind,
            "is_large_run": self.is_large_run,
            "metadata": self.metadata,
        }

    def load_dataframe(self, columns: Optional[Iterable[str]] = None) -> pd.DataFrame:
        """Load the referenced dataset into memory."""
        return pd.read_parquet(
            parquet_dataset_source(self.parquet_path),
            columns=list(columns) if columns else None,
        )


def ensure_clean_directory(path: Path) -> Path:
    """Remove and recreate a controlled staging directory."""
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_attempt_directory(stage_root: Path) -> Path:
    """Create a unique attempt-scoped staging directory beneath a deterministic root."""
    attempts_root = Path(stage_root) / "attempts"
    attempt_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{uuid.uuid4().hex[:8]}"
    attempt_dir = attempts_root / attempt_id
    try:
        attempts_root.mkdir(parents=True, exist_ok=True)
        attempt_dir.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise _filesystem_error(attempts_root, operation="creating attempt-scoped staging directory", error=exc) from exc
    return attempt_dir


def require_parquet_output(parquet_path: Path, *, operation: str) -> Path:
    """Raise a targeted error when an expected Parquet output is missing."""
    parquet_path = Path(parquet_path)
    if parquet_dataset_exists(parquet_path):
        return parquet_path
    raise FileNotFoundError(
        f"{operation} did not produce a Parquet output at {_absolute_path_text(parquet_path)}"
    )


def prepare_dataframe_for_parquet(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize object/category columns for robust Parquet writes."""
    df_out = df.copy()
    for column in df_out.columns:
        if pd.api.types.is_categorical_dtype(df_out[column]):
            df_out[column] = df_out[column].astype(str)
        elif df_out[column].dtype == "object":
            non_null = df_out[column].dropna()
            if not non_null.empty and non_null.map(
                lambda value: isinstance(value, (bool, np.bool_))
            ).all():
                # PyArrow returns nullable Boolean columns as object Series when
                # converting batches to pandas. Preserve their logical type on
                # the next staged write instead of turning True/False into text.
                df_out[column] = df_out[column].astype("boolean")
            else:
                df_out[column] = df_out[column].astype(str)
    return df_out


def write_parquet_part(
    df: pd.DataFrame,
    dataset_dir: Path,
    part_index: int,
    *,
    prefix: str = "part",
) -> Path:
    """Write a chunk into a Parquet dataset directory."""
    try:
        dataset_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise _filesystem_error(dataset_dir, operation="creating Parquet dataset directory", error=exc) from exc
    output_path = dataset_dir / f"{prefix}-{part_index:05d}.parquet"
    try:
        prepare_dataframe_for_parquet(df).to_parquet(output_path, index=False)
    except OSError as exc:
        raise _filesystem_error(output_path, operation="writing Parquet dataset part", error=exc) from exc
    return output_path


def iter_parquet_batches(
    parquet_path: Path,
    *,
    batch_size: int = 100_000,
    columns: Optional[Iterable[str]] = None,
) -> Iterator[pd.DataFrame]:
    """Yield pandas batches from a Parquet file or dataset directory."""
    dataset = _parquet_dataset(parquet_path)
    for batch in dataset.to_batches(batch_size=batch_size, columns=list(columns) if columns else None):
        yield batch.to_pandas()


def parquet_row_count(parquet_path: Path) -> int:
    """Count rows in a Parquet file or dataset directory."""
    dataset = _parquet_dataset(parquet_path)
    return int(dataset.count_rows())


def parquet_columns(parquet_path: Path) -> list[str]:
    """Return column names for a Parquet file or dataset directory."""
    dataset = _parquet_dataset(parquet_path)
    return list(dataset.schema.names)


def write_dataset_manifest(dataset: DatasetReference, extra: Optional[Dict[str, Any]] = None) -> None:
    """Persist the dataset reference and any extra metadata to JSON."""
    if dataset.manifest_path is None:
        return

    payload = dataset.to_dict()
    if extra:
        payload.update(extra)

    try:
        dataset.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        dataset.manifest_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        raise _filesystem_error(dataset.manifest_path, operation="writing dataset manifest", error=exc) from exc


def require_duckdb():
    """Return the DuckDB module or raise a targeted error."""
    global duckdb
    if duckdb is None:
        try:
            import duckdb as duckdb_module
        except ImportError:
            duckdb_module = None
        duckdb = duckdb_module
    if duckdb is None:
        raise RuntimeError(
            "DuckDB is required for staged full-load EPC processing. "
            "Install dependencies from requirements.txt to enable national-scale runs."
        )
    return duckdb


def sql_identifier(name: str) -> str:
    """Quote a SQL identifier for DuckDB."""
    return '"' + str(name).replace('"', '""') + '"'


def sql_literal(value: Any) -> str:
    """Quote a SQL literal for DuckDB."""
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def parquet_source_literal(parquet_path: Path) -> str:
    """Return a DuckDB-safe read_parquet source expression."""
    source = parquet_dataset_source(parquet_path)
    if isinstance(source, list):
        return "[" + ", ".join(sql_literal(path) for path in source) + "]"
    return sql_literal(source)


def copy_query_to_parquet(select_sql: str, output_path: Path) -> Path:
    """Materialize a query result to a Parquet file via DuckDB."""
    db = require_duckdb()
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.unlink(missing_ok=True)
    except OSError as exc:
        raise _filesystem_error(output_path, operation="preparing Parquet output path", error=exc) from exc
    sql = (
        f"COPY ({select_sql}) TO {sql_literal(output_path.as_posix())} "
        "(FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    conn = db.connect()
    try:
        conn.execute(sql)
    finally:
        conn.close()
    require_parquet_output(output_path, operation="DuckDB Parquet materialization")
    logger.info("Materialized DuckDB query to Parquet: {}", output_path)
    return output_path


def copy_parquet_to_csv(parquet_path: Path, csv_path: Path) -> Path:
    """Export a Parquet dataset to CSV without loading it fully into pandas."""
    db = require_duckdb()
    try:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.unlink(missing_ok=True)
    except OSError as exc:
        raise _filesystem_error(csv_path, operation="preparing CSV output path", error=exc) from exc
    source = parquet_source_literal(parquet_path)
    sql = (
        f"COPY (SELECT * FROM read_parquet({source})) "
        f"TO {sql_literal(csv_path.as_posix())} (HEADER, DELIMITER ',')"
    )
    conn = db.connect()
    try:
        conn.execute(sql)
    finally:
        conn.close()
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV export did not produce an output at {_absolute_path_text(csv_path)}")
    logger.info("Exported Parquet dataset to CSV: {}", csv_path)
    return csv_path
