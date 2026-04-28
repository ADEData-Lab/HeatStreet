"""
Chunked validation and adjustment helpers for staged Parquet datasets.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, Tuple

from loguru import logger

from src.analysis.methodological_adjustments import MethodologicalAdjustments
from src.cleaning.data_validator import EPCDataValidator
from src.utils.staged_dataset import (
    DatasetReference,
    copy_parquet_to_csv,
    copy_query_to_parquet,
    create_attempt_directory,
    iter_parquet_batches,
    parquet_columns,
    parquet_row_count,
    parquet_source_literal,
    require_duckdb,
    require_parquet_output,
    sql_identifier,
    write_dataset_manifest,
    write_parquet_part,
)


VALIDATION_REPORT_KEYS = (
    "total_records",
    "duplicates_removed",
    "implausible_floor_areas",
    "inconsistent_built_form",
    "missing_critical_fields",
    "construction_date_mismatches",
    "illogical_insulation",
    "negative_energy_values",
    "negative_co2_values",
    "energy_values_clamped",
    "co2_values_clamped",
    "records_passed",
)


def _empty_validation_report() -> Dict[str, int]:
    return {key: 0 for key in VALIDATION_REPORT_KEYS}


def _dedupe_query_for_dataset(input_path: Path) -> str:
    columns = parquet_columns(input_path)
    select_columns = ", ".join(sql_identifier(column) for column in columns)

    dedupe_key = None
    for candidate in ("UPRN", "ADDRESS", "ADDRESS1"):
        if candidate in columns:
            dedupe_key = candidate
            break

    if dedupe_key is None:
        logger.warning("No UPRN/address column found in staged validation input; skipping deduplication")
        return f"SELECT {select_columns} FROM read_parquet({parquet_source_literal(input_path)})"

    order_columns = []
    for candidate in ("LODGEMENT_DATE", "INSPECTION_DATE"):
        if candidate in columns:
            order_columns.append(f"TRY_CAST({sql_identifier(candidate)} AS TIMESTAMP) DESC NULLS LAST")
    if "CERTIFICATE_NUMBER" in columns:
        order_columns.append(f"{sql_identifier('CERTIFICATE_NUMBER')} DESC NULLS LAST")
    if not order_columns:
        order_columns.append(sql_identifier(dedupe_key))

    order_sql = ", ".join(order_columns)
    source = parquet_source_literal(input_path)
    return f"""
        WITH ranked AS (
            SELECT
                {select_columns},
                ROW_NUMBER() OVER (
                    PARTITION BY {sql_identifier(dedupe_key)}
                    ORDER BY {order_sql}
                ) AS _row_number
            FROM read_parquet({source})
        )
        SELECT {select_columns}
        FROM ranked
        WHERE _row_number = 1
    """


def validate_staged_dataset(
    input_dataset: DatasetReference,
    output_csv_path: Path,
    *,
    chunk_size: int = 100_000,
) -> Tuple[DatasetReference, Dict]:
    """
    Validate a staged raw dataset in chunked passes and persist a Parquet-first output.
    """
    staging_root = output_csv_path.parent / f"{output_csv_path.stem}_validation_staging"
    logger.info("Selected validation staging root: {}", staging_root.resolve())
    attempt_dir = create_attempt_directory(staging_root)
    staging_dir = attempt_dir / "validated_chunks_dataset"
    logger.info("Chosen validation attempt directory: {}", attempt_dir.resolve())

    aggregated_report = defaultdict(int)
    part_index = 0

    logger.info(
        "Validating staged dataset '{}' from {} in {}-row chunks",
        input_dataset.name,
        input_dataset.parquet_path,
        chunk_size,
    )

    for chunk in iter_parquet_batches(input_dataset.parquet_path, batch_size=chunk_size):
        validator = EPCDataValidator()

        rows_before = len(chunk)
        chunk = validator._standardize_column_names(chunk)
        chunk = validator.validate_floor_areas(chunk)
        chunk = validator.validate_energy_and_emissions(chunk)
        chunk = validator.validate_built_form(chunk)
        chunk = validator.validate_critical_fields(chunk)
        chunk = validator.validate_construction_dates(chunk)
        chunk = validator.validate_insulation_logic(chunk)
        chunk = validator.standardize_fields(chunk)

        chunk_report = validator.validation_report
        chunk_report["total_records"] = int(rows_before)
        chunk_report["records_passed"] = int(len(chunk))
        chunk_report["duplicates_removed"] = 0

        for key in VALIDATION_REPORT_KEYS:
            aggregated_report[key] += int(chunk_report.get(key, 0))

        write_parquet_part(chunk, staging_dir, part_index, prefix="validated")
        part_index += 1

    if part_index == 0:
        aggregated_report = _empty_validation_report()
        output_parquet_path = output_csv_path.with_suffix(".parquet")
        empty_select_sql = f"SELECT * FROM read_parquet({parquet_source_literal(input_dataset.parquet_path)}) LIMIT 0"
        copy_query_to_parquet(empty_select_sql, output_parquet_path)
        require_parquet_output(output_parquet_path, operation="staged validation empty-output materialization")
        output_csv_reference = None
        if not input_dataset.is_large_run:
            copy_parquet_to_csv(output_parquet_path, output_csv_path)
            output_csv_reference = output_csv_path
        output_dataset = DatasetReference(
            name="validated_epc_dataset",
            parquet_path=output_parquet_path,
            csv_path=output_csv_reference,
            manifest_path=output_parquet_path.with_name(f"{output_parquet_path.stem}_manifest.json"),
            row_count=0,
            stage="validated",
            sample_start_date=input_dataset.sample_start_date,
            sample_end_date=input_dataset.sample_end_date,
            storage_kind="parquet",
            is_large_run=input_dataset.is_large_run,
            metadata={
                "input_dataset": input_dataset.to_dict(),
                "staging_root": str(staging_root.resolve()),
                "attempt_dir": str(attempt_dir.resolve()),
            },
        )
        write_dataset_manifest(output_dataset, extra={"validation_report": dict(aggregated_report)})
        return output_dataset, dict(aggregated_report)

    output_parquet_path = output_csv_path.with_suffix(".parquet")
    copy_query_to_parquet(_dedupe_query_for_dataset(staging_dir), output_parquet_path)
    require_parquet_output(output_parquet_path, operation="staged validation output materialization")
    output_csv_reference = None
    if input_dataset.is_large_run:
        logger.info(
            "Skipping processed CSV export for large staged validation output: {}",
            output_csv_path.resolve(),
        )
    else:
        copy_parquet_to_csv(output_parquet_path, output_csv_path)
        output_csv_reference = output_csv_path

    final_row_count = parquet_row_count(output_parquet_path)
    aggregated_report["duplicates_removed"] = max(
        aggregated_report["records_passed"] - final_row_count,
        0,
    )
    aggregated_report["records_passed"] = int(final_row_count)

    output_dataset = DatasetReference(
        name="validated_epc_dataset",
        parquet_path=output_parquet_path,
        csv_path=output_csv_reference,
        manifest_path=output_parquet_path.with_name(f"{output_parquet_path.stem}_manifest.json"),
        row_count=int(final_row_count),
        stage="validated",
        sample_start_date=input_dataset.sample_start_date,
        sample_end_date=input_dataset.sample_end_date,
        storage_kind="parquet",
        is_large_run=input_dataset.is_large_run,
        metadata={
            "input_dataset": input_dataset.to_dict(),
            "chunk_size": chunk_size,
            "staging_dir": str(staging_dir),
            "staging_root": str(staging_root.resolve()),
            "attempt_dir": str(attempt_dir.resolve()),
        },
    )
    write_dataset_manifest(output_dataset, extra={"validation_report": dict(aggregated_report)})
    logger.info(
        "Validated staged dataset rows retained: {} (parquet={}, manifest={})",
        final_row_count,
        output_parquet_path.resolve(),
        output_dataset.manifest_path.resolve(),
    )
    return output_dataset, dict(aggregated_report)


def _summarize_adjusted_dataset(parquet_path: Path) -> Dict:
    """Generate methodological adjustment summary from Parquet via DuckDB."""
    db = require_duckdb()
    source = parquet_source_literal(parquet_path)
    conn = db.connect()
    try:
        metrics = conn.execute(
            f"""
            SELECT
                COUNT(*) AS record_count,
                SUM(CASE WHEN prebound_factor != 1.0 THEN 1 ELSE 0 END) AS properties_adjusted,
                AVG(prebound_factor) AS mean_prebound_factor,
                AVG(rebound_factor) AS mean_rebound_factor,
                AVG(estimated_flow_temp) AS mean_flow_temp,
                AVG(CASE WHEN CAST(emitter_upgrade_need AS VARCHAR) != 'none' THEN 1 ELSE 0 END) * 100 AS pct_need_emitter_upgrade,
                AVG(sap_uncertainty) AS mean_uncertainty
            FROM read_parquet({source})
            """
        ).fetchone()
    finally:
        conn.close()

    record_count = int(metrics[0] or 0)
    mean_prebound = float(metrics[2]) if metrics[2] is not None else None
    mean_rebound = float(metrics[3]) if metrics[3] is not None else None
    mean_flow_temp = float(metrics[4]) if metrics[4] is not None else None
    pct_need_emitter_upgrade = float(metrics[5]) if metrics[5] is not None else None
    mean_uncertainty = float(metrics[6]) if metrics[6] is not None else None

    summary = {
        "prebound_adjustment": {},
        "rebound_adjustment": {},
        "flow_temperature": {},
        "uncertainty": {},
    }

    if record_count:
        if mean_prebound is not None:
            summary["prebound_adjustment"] = {
                "applied": True,
                "properties_adjusted": int(metrics[1] or 0),
                "mean_factor": mean_prebound,
                "description": "Adjusts EPC-modeled consumption to realistic baseline (Few et al., 2023)",
            }
        if mean_rebound is not None:
            comfort_taking_pct = (1 - mean_rebound) * 100
            summary["rebound_adjustment"] = {
                "applied": True,
                "mean_factor": mean_rebound,
                "comfort_taking_pct": comfort_taking_pct,
                "description": (
                    "Adjusts modeled savings for comfort-taking (rebound effect). "
                    "Under-heated homes take some savings as improved thermal comfort rather than reduced fuel consumption."
                ),
                "methodology_note": (
                    f"Average {comfort_taking_pct:.1f}% of theoretical savings expected to be taken as comfort improvement rather than energy reduction"
                ),
            }
        if mean_flow_temp is not None:
            summary["flow_temperature"] = {
                "applied": True,
                "mean_flow_temp": mean_flow_temp,
                "pct_need_emitter_upgrade": pct_need_emitter_upgrade or 0.0,
                "description": "Estimates required flow temperature for heat pump efficiency",
            }
        if mean_uncertainty is not None:
            summary["uncertainty"] = {
                "applied": True,
                "mean_uncertainty": mean_uncertainty,
                "description": "EPC measurement error (Crawley et al., 2019)",
            }

    return summary


def apply_adjustments_staged_dataset(
    input_dataset: DatasetReference,
    output_csv_path: Path,
    *,
    chunk_size: int = 100_000,
) -> Tuple[DatasetReference, Dict]:
    """
    Apply methodological adjustments to a staged validated dataset in chunks.
    """
    staging_root = output_csv_path.parent / f"{output_csv_path.stem}_adjustment_staging"
    logger.info("Selected adjustment staging root: {}", staging_root.resolve())
    attempt_dir = create_attempt_directory(staging_root)
    staging_dir = attempt_dir / "adjusted_chunks_dataset"
    logger.info("Chosen adjustment attempt directory: {}", attempt_dir.resolve())

    logger.info(
        "Applying staged methodological adjustments for '{}' from {} in {}-row chunks",
        input_dataset.name,
        input_dataset.parquet_path,
        chunk_size,
    )

    part_index = 0
    for chunk in iter_parquet_batches(input_dataset.parquet_path, batch_size=chunk_size):
        adjuster = MethodologicalAdjustments()
        adjusted_chunk = adjuster.apply_all_adjustments(chunk)
        write_parquet_part(adjusted_chunk, staging_dir, part_index, prefix="adjusted")
        part_index += 1

    output_parquet_path = output_csv_path.with_suffix(".parquet")
    if part_index == 0:
        empty_select_sql = f"SELECT * FROM read_parquet({parquet_source_literal(input_dataset.parquet_path)}) LIMIT 0"
        copy_query_to_parquet(empty_select_sql, output_parquet_path)
        require_parquet_output(output_parquet_path, operation="staged adjustment empty-output materialization")
        output_csv_reference = None
        if not input_dataset.is_large_run:
            copy_parquet_to_csv(output_parquet_path, output_csv_path)
            output_csv_reference = output_csv_path
        output_dataset = DatasetReference(
            name="adjusted_epc_dataset",
            parquet_path=output_parquet_path,
            csv_path=output_csv_reference,
            manifest_path=output_parquet_path.with_name(f"{output_parquet_path.stem}_manifest.json"),
            row_count=0,
            stage="adjusted",
            sample_start_date=input_dataset.sample_start_date,
            sample_end_date=input_dataset.sample_end_date,
            storage_kind="parquet",
            is_large_run=input_dataset.is_large_run,
            metadata={
                "input_dataset": input_dataset.to_dict(),
                "staging_root": str(staging_root.resolve()),
                "attempt_dir": str(attempt_dir.resolve()),
            },
        )
        write_dataset_manifest(output_dataset, extra={"adjustment_summary": {}})
        return output_dataset, {}

    select_sql = f"SELECT * FROM read_parquet({parquet_source_literal(staging_dir)})"
    copy_query_to_parquet(select_sql, output_parquet_path)
    require_parquet_output(output_parquet_path, operation="staged adjustment output materialization")
    output_csv_reference = None
    if input_dataset.is_large_run:
        logger.info(
            "Skipping processed CSV export for large staged adjustment output: {}",
            output_csv_path.resolve(),
        )
    else:
        copy_parquet_to_csv(output_parquet_path, output_csv_path)
        output_csv_reference = output_csv_path

    output_dataset = DatasetReference(
        name="adjusted_epc_dataset",
        parquet_path=output_parquet_path,
        csv_path=output_csv_reference,
        manifest_path=output_parquet_path.with_name(f"{output_parquet_path.stem}_manifest.json"),
        row_count=parquet_row_count(output_parquet_path),
        stage="adjusted",
        sample_start_date=input_dataset.sample_start_date,
        sample_end_date=input_dataset.sample_end_date,
        storage_kind="parquet",
        is_large_run=input_dataset.is_large_run,
        metadata={
            "input_dataset": input_dataset.to_dict(),
            "chunk_size": chunk_size,
            "staging_dir": str(staging_dir),
            "staging_root": str(staging_root.resolve()),
            "attempt_dir": str(attempt_dir.resolve()),
        },
    )

    adjustment_summary = _summarize_adjusted_dataset(output_parquet_path)
    write_dataset_manifest(output_dataset, extra={"adjustment_summary": adjustment_summary})
    logger.info(
        "Adjusted staged dataset rows retained: {} (parquet={}, manifest={})",
        output_dataset.row_count,
        output_parquet_path.resolve(),
        output_dataset.manifest_path.resolve(),
    )
    return output_dataset, adjustment_summary
