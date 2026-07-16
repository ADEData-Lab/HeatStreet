"""
Post-process an existing one_stop_output.json using analysis_log.json.

Only explicit metrics from the matching current run are eligible for patching.
The patcher never invents missing values or creates replacement provenance.

The patcher updates:
- Section 1 run timings and identifier from analysis_log.json.
- Section 2 validation totals (raw/validated/duplicates/invalid/negative counts)
  from the "Data Validation" phase metrics in analysis_log.json.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from src.utils.run_integrity import RunContext, require_current_artifact, stamp_artifact


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        logger.warning(f"JSON not found: {path}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"Could not parse JSON {path}: {exc}")
        return {}


def _backup_file(path: Path) -> Optional[Path]:
    try:
        backup_path = path.with_suffix(path.suffix + f".bak.{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        return backup_path
    except Exception as exc:
        logger.warning(f"Could not create backup for {path}: {exc}")
    return None


def _set_datapoint_value(sections: Dict[str, Any], section_id: str, key: str, value: Any) -> bool:
    section = sections.get(section_id)
    if not isinstance(section, dict):
        return False
    datapoints = section.get("datapoints", [])
    if not isinstance(datapoints, list):
        return False

    for dp in datapoints:
        if isinstance(dp, dict) and dp.get("key") == key:
            dp["value"] = value
            return True
    return False


def _get_datapoint_value(sections: Dict[str, Any], section_id: str, key: str) -> Any:
    section = sections.get(section_id)
    if not isinstance(section, dict):
        return None
    for datapoint in section.get("datapoints", []):
        if isinstance(datapoint, dict) and datapoint.get("key") == key:
            return datapoint.get("value")
    return None


def _find_phase(analysis_log: Dict[str, Any], phase_name: str) -> Optional[Dict[str, Any]]:
    for phase in analysis_log.get("phases", []) or []:
        if isinstance(phase, dict) and phase.get("phase_name") == phase_name:
            return phase
    return None


def _metric_value(phase: Dict[str, Any], metric_key: str) -> Optional[Any]:
    metrics = phase.get("metrics", {}) if isinstance(phase, dict) else {}
    metric = metrics.get(metric_key, {}) if isinstance(metrics, dict) else {}
    if isinstance(metric, dict):
        return metric.get("value")
    return None


def _snake_case(value: Any) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "")).strip("_")
    return cleaned.lower()


def _upsert_datapoint(section: Dict[str, Any], datapoint: Dict[str, Any]) -> bool:
    """Update an existing datapoint by key, or append when missing."""
    key = datapoint.get("key")
    if not key:
        return False

    datapoints = section.get("datapoints")
    if datapoints is None:
        section["datapoints"] = []
        datapoints = section["datapoints"]

    if not isinstance(datapoints, list):
        return False

    for existing in datapoints:
        if isinstance(existing, dict) and existing.get("key") == key:
            existing.update(datapoint)
            return True

    datapoints.append(datapoint)
    return True


def _insert_column(columns: list, column: str, after: str) -> bool:
    if column in columns:
        return False
    try:
        idx = columns.index(after) + 1
    except ValueError:
        columns.append(column)
        return True
    columns.insert(idx, column)
    return True


def _patch_cost_effectiveness_marginal_bucket(sections: Dict[str, Any]) -> bool:
    """Ensure section_6 scenario table includes marginal_count/marginal_pct and sums to totals."""
    section = sections.get("section_6")
    if not isinstance(section, dict):
        return False

    tables = section.get("tables", [])
    if not isinstance(tables, list):
        return False

    patched_any = False

    for table in tables:
        if not isinstance(table, dict):
            continue
        columns = table.get("columns")
        data = table.get("data")
        if not isinstance(columns, list) or not isinstance(data, list):
            continue
        if "cost_effective_count" not in columns or "not_cost_effective_count" not in columns:
            continue

        # Maintain a stable ordering: insert marginal fields after cost_effective_pct when possible.
        inserted = False
        if "cost_effective_pct" in columns:
            inserted |= _insert_column(columns, "marginal_count", "cost_effective_pct")
            inserted |= _insert_column(columns, "marginal_pct", "marginal_count")
        elif "cost_effective_count" in columns:
            inserted |= _insert_column(columns, "marginal_count", "cost_effective_count")
            inserted |= _insert_column(columns, "marginal_pct", "marginal_count")
        else:
            if "marginal_count" not in columns:
                columns.append("marginal_count")
                inserted = True
            if "marginal_pct" not in columns:
                columns.append("marginal_pct")
                inserted = True

        if inserted:
            patched_any = True
            table["columns"] = columns

        for row in data:
            if not isinstance(row, dict):
                continue

            if row.get("scenario_id") == "baseline":
                row.setdefault("marginal_count", None)
                row.setdefault("marginal_pct", None)
                continue

            total = row.get("total_properties")
            ce = row.get("cost_effective_count")
            nce = row.get("not_cost_effective_count")
            if total is None or ce is None or nce is None:
                continue

            try:
                total_int = int(total)
                ce_int = int(ce)
                nce_int = int(nce)
            except (TypeError, ValueError):
                continue

            if total_int <= 0:
                continue

            marginal_int = total_int - ce_int - nce_int
            if marginal_int < 0:
                # Avoid negative values due to rounding/typing artefacts.
                marginal_int = 0

            marginal_pct = (marginal_int / total_int) * 100

            # Write to table
            row["marginal_count"] = marginal_int
            row["marginal_pct"] = marginal_pct
            patched_any = True

            # Also add/update section-level datapoints for convenience
            scenario_label = row.get("scenario") or row.get("scenario_id") or "unknown"
            scenario_suffix = _snake_case(scenario_label)
            usage = f"Scenario {scenario_label} cost-effectiveness"

            _upsert_datapoint(section, {
                "name": f"Marginally cost-effective properties (count) ({scenario_label})",
                "key": f"marginal_count_{scenario_suffix}",
                "value": marginal_int,
                "definition": "Count of marginally cost-effective properties (payback 15-25 years) (count).",
                "denominator": "All properties in scenario",
                "source": "Derived: total_properties - cost_effective_count - not_cost_effective_count (Section 6 scenario table)",
                "usage": usage,
            })
            _upsert_datapoint(section, {
                "name": f"Marginally cost-effective properties (%) ({scenario_label})",
                "key": f"marginal_pct_{scenario_suffix}",
                "value": marginal_pct,
                "definition": "Share of marginally cost-effective properties (payback 15-25 years) (percent).",
                "denominator": "All properties in scenario",
                "source": "Derived: total_properties - cost_effective_count - not_cost_effective_count (Section 6 scenario table)",
                "usage": usage,
            })

        table["data"] = data

    return patched_any


def _patch_epc_lodgements_by_year_band_table(sections: Dict[str, Any], processed_dir: Path) -> bool:
    """
    Ensure the one-stop output includes a lodgements-by-year table in Section 3.

    This supports the interactive HTML dashboard without requiring extra CSV exports.
    """
    section = sections.get("section_3")
    if not isinstance(section, dict):
        return False

    tables = section.get("tables")
    if tables is None:
        section["tables"] = []
        tables = section["tables"]
    if not isinstance(tables, list):
        return False

    if any(isinstance(t, dict) and "lodgements by year" in str(t.get("caption", "")).lower() for t in tables):
        return False

    try:
        import pandas as pd
    except Exception as exc:
        logger.warning(f"Could not import pandas to build lodgements-by-year table: {exc}")
        return False

    parquet_path = Path(processed_dir) / "epc_london_validated.parquet"
    csv_path = Path(processed_dir) / "epc_london_validated.csv"
    cols = ["LODGEMENT_DATE", "INSPECTION_DATE", "CURRENT_ENERGY_RATING"]

    df = None
    try:
        if parquet_path.exists():
            df = pd.read_parquet(parquet_path, columns=cols)
        elif csv_path.exists():
            df = pd.read_csv(csv_path, usecols=cols)
    except Exception as exc:
        logger.warning(f"Could not load validated EPC data for lodgements-by-year table: {exc}")
        return False

    if df is None or df.empty:
        return False

    lodgement = pd.to_datetime(df.get("LODGEMENT_DATE"), errors="coerce")
    inspection = pd.to_datetime(df.get("INSPECTION_DATE"), errors="coerce")
    effective = lodgement.fillna(inspection)
    years = effective.dt.year

    band = df.get("CURRENT_ENERGY_RATING")
    if band is None:
        return False
    band = band.astype("string").fillna("Unknown").str.strip().str.upper()
    band = band.replace({"": "Unknown"})
    band = band.where(band.isin(list("ABCDEFG")), other="Unknown")

    tmp = pd.DataFrame({"year": years, "band": band}).dropna(subset=["year"])
    if tmp.empty:
        return False

    tmp["year"] = tmp["year"].astype(int)
    wide = (
        tmp.groupby(["year", "band"])
        .size()
        .unstack(fill_value=0)
        .sort_index()
    )
    wide.index.name = "year"

    ordered_cols = list("ABCDEFG") + ["Unknown"]
    for c in ordered_cols:
        if c not in wide.columns:
            wide[c] = 0

    wide = wide[ordered_cols].reset_index()

    # Convert to JSON-friendly primitive types
    rows = []
    for rec in wide.to_dict(orient="records"):
        clean = {}
        for k, v in rec.items():
            try:
                clean[k] = int(v)
            except Exception:
                clean[k] = v
        rows.append(clean)

    tables.append({
        "caption": "EPC lodgements by year and EPC band (counts; year from LODGEMENT_DATE, fallback INSPECTION_DATE)",
        "columns": ["year"] + ordered_cols,
        "data": rows,
    })
    section["tables"] = tables
    sections["section_3"] = section
    return True


def patch_one_stop_output(
    output_dir: Path,
    one_stop_filename: str = "one_stop_output.json",
    analysis_log_filename: str = "analysis_log.json",
    create_backup: bool = True,
    run_id: Optional[str] = None,
    dataset_fingerprint: Optional[str] = None,
) -> Optional[Path]:
    """
    Patch one_stop_output.json in-place using analysis_log.json.

    Returns:
        Path to the patched one-stop output, or None if not patched.
    """
    output_dir = Path(output_dir)
    one_stop_path = output_dir / one_stop_filename
    analysis_log_path = output_dir / analysis_log_filename

    if not one_stop_path.exists():
        logger.info(f"Skipping one-stop patch: {one_stop_path} not found")
        return None

    one_stop = _load_json(one_stop_path)
    supplied_context = run_id is not None or dataset_fingerprint is not None
    if supplied_context and not (run_id and dataset_fingerprint):
        raise ValueError("run_id and dataset_fingerprint must be supplied together")
    if not supplied_context:
        report_metadata = one_stop.get("metadata", {})
        run_id = report_metadata.get("run_id")
        dataset_fingerprint = report_metadata.get("dataset_fingerprint")
        if not (run_id and dataset_fingerprint):
            raise RuntimeError("Explicit current-run provenance is required for one-stop patching")
    context = RunContext(run_id, dataset_fingerprint)
    require_current_artifact(one_stop_path, context)
    require_current_artifact(analysis_log_path, context)

    analysis_log = _load_json(analysis_log_path)

    sections = one_stop.get("sections", {})
    if not isinstance(sections, dict):
        logger.warning("Invalid one-stop structure: missing 'sections' dict")
        return None
    if context:
        report_metadata = one_stop.get("metadata", {})
        for key, expected in context.to_dict().items():
            if report_metadata.get(key) != expected:
                raise RuntimeError(
                    f"One-stop provenance mismatch: {key}={report_metadata.get(key)!r}, expected {expected!r}"
                )

    # Section 1: run timings from analysis_log metadata
    meta = analysis_log.get("metadata", {}) if isinstance(analysis_log, dict) else {}
    if context:
        for key, expected in context.to_dict().items():
            if meta.get(key) != expected:
                raise RuntimeError(
                    f"Analysis log provenance mismatch: {key}={meta.get(key)!r}, expected {expected!r}"
                )
    analysis_start = meta.get("analysis_start")
    analysis_end = meta.get("analysis_end")
    runtime_seconds = meta.get("total_duration_seconds")

    changed = False
    if meta.get("run_id") is not None:
        changed |= _set_datapoint_value(sections, "section_1", "run_identifier", meta["run_id"])
    if analysis_start is not None:
        changed |= _set_datapoint_value(sections, "section_1", "analysis_start_time", analysis_start)
    if analysis_end is not None:
        changed |= _set_datapoint_value(sections, "section_1", "analysis_end_time", analysis_end)
    if runtime_seconds is not None:
        changed |= _set_datapoint_value(sections, "section_1", "total_runtime_seconds", runtime_seconds)

    # Section 2: validation totals from analysis log phase metrics
    validation_phase = _find_phase(analysis_log, "Data Validation") or {}
    total_raw = _metric_value(validation_phase, "input_records")
    validated = _metric_value(validation_phase, "validated_records")
    duplicates_removed = _metric_value(validation_phase, "duplicates_removed")
    invalid_including_duplicates = _metric_value(validation_phase, "invalid_records")
    negative_energy = _metric_value(validation_phase, "negative_energy_values")
    negative_co2 = _metric_value(validation_phase, "negative_co2_values")

    if context:
        cohort_metrics = (total_raw, validated, duplicates_removed, invalid_including_duplicates)
        if any(value is not None for value in cohort_metrics):
            if not all(value is not None for value in cohort_metrics):
                raise RuntimeError("Incomplete explicit current-run validation metrics; refusing cohort patch")
            total_check, validated_check, duplicates_check, invalid_check = map(int, cohort_metrics)
            if total_check != validated_check + duplicates_check + invalid_check:
                raise RuntimeError("Current-run validation metrics fail cohort arithmetic")
            report_cohort = _get_datapoint_value(
                sections, "section_2", "records_passing_validation"
            )
            if report_cohort is None or int(report_cohort) != validated_check:
                raise RuntimeError("Current-run validation cohort does not match one-stop cohort")

    # Prefer consistent derivations where possible
    try:
        total_raw_int = int(total_raw) if total_raw is not None else None
        validated_int = int(validated) if validated is not None else None
        duplicates_int = int(duplicates_removed) if duplicates_removed is not None else None
        invalid_int = int(invalid_including_duplicates) if invalid_including_duplicates is not None else None

        excluded_total_int = (
            duplicates_int + invalid_int
            if duplicates_int is not None and invalid_int is not None
            else None
        )

        if total_raw_int is not None:
            changed |= _set_datapoint_value(sections, "section_2", "total_raw_records", total_raw_int)
        if validated_int is not None:
            changed |= _set_datapoint_value(sections, "section_2", "records_passing_validation", validated_int)
        if excluded_total_int is not None:
            changed |= _set_datapoint_value(sections, "section_2", "records_excluded_total", excluded_total_int)

        if duplicates_int is not None:
            changed |= _set_datapoint_value(sections, "section_2", "duplicates_removed", duplicates_int)

        if invalid_int is not None:
            changed |= _set_datapoint_value(sections, "section_2", "invalid_records", invalid_int)

        if negative_energy is not None:
            changed |= _set_datapoint_value(sections, "section_2", "negative_energy_values", int(negative_energy))
        if negative_co2 is not None:
            changed |= _set_datapoint_value(sections, "section_2", "negative_co2_values", int(negative_co2))
    except Exception as exc:
        logger.warning(f"Could not patch Section 2 validation totals: {exc}")

    # Persist patched output
    one_stop["sections"] = sections

    if not changed:
        logger.info("No explicit current-run metrics available for one-stop patching")
        return None

    if create_backup:
        backup_path = _backup_file(one_stop_path)
        if backup_path:
            logger.info(f"Backed up one-stop output to {backup_path}")

    one_stop_path.write_text(json.dumps(one_stop, indent=2, ensure_ascii=False), encoding="utf-8")
    if context:
        stamp_artifact(one_stop_path, context)
    logger.info(f"Patched one-stop output written to {one_stop_path}")
    return one_stop_path


if __name__ == "__main__":
    patch_one_stop_output(Path("data/outputs"))
