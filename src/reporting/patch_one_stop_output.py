"""
Post-process an existing one_stop_output.json using analysis_log.json.

This is used to ensure the consolidated one-stop output remains auditable even when:
- run_metadata.json is missing (common in one-stop-only mode with aggressive cleanup), and/or
- validation_report.json is missing/corrupted (e.g., numpy types causing partial writes).

The patcher updates:
- Section 1 run timings (start/end/runtime) from analysis_log.json
  and sets run_identifier to the analysis start timestamp.
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


def _write_run_metadata(output_dir: Path, analysis_start: Any, analysis_end: Any, runtime_seconds: Any) -> Optional[Path]:
    """
    Write a minimal run_metadata.json derived from analysis_log.json metadata.

    one_stop_report.py expects: run_id, start_time, end_time, runtime_seconds.
    """
    try:
        run_metadata = {
            "run_id": analysis_start,
            "start_time": analysis_start,
            "end_time": analysis_end,
            "runtime_seconds": runtime_seconds,
            "generated_from": "analysis_log.json",
            "generated_at": datetime.now().isoformat(),
        }
        path = Path(output_dir) / "run_metadata.json"
        path.write_text(json.dumps(run_metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        return path
    except Exception as exc:
        logger.warning(f"Could not write run_metadata.json: {exc}")
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


def patch_one_stop_output(
    output_dir: Path,
    one_stop_filename: str = "one_stop_output.json",
    analysis_log_filename: str = "analysis_log.json",
    create_backup: bool = True,
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
    analysis_log = _load_json(analysis_log_path)

    sections = one_stop.get("sections", {})
    if not isinstance(sections, dict):
        logger.warning("Invalid one-stop structure: missing 'sections' dict")
        return None

    # Section 1: run timings from analysis_log metadata
    meta = analysis_log.get("metadata", {}) if isinstance(analysis_log, dict) else {}
    analysis_start = meta.get("analysis_start")
    analysis_end = meta.get("analysis_end")
    runtime_seconds = meta.get("total_duration_seconds")

    run_metadata_path = None
    if analysis_start is not None or analysis_end is not None or runtime_seconds is not None:
        run_metadata_path = _write_run_metadata(output_dir, analysis_start, analysis_end, runtime_seconds)
        if run_metadata_path:
            logger.info(f"Wrote run metadata to {run_metadata_path}")

    if analysis_start is not None:
        _set_datapoint_value(sections, "section_1", "run_identifier", analysis_start)
        _set_datapoint_value(sections, "section_1", "analysis_start_time", analysis_start)
    if analysis_end is not None:
        _set_datapoint_value(sections, "section_1", "analysis_end_time", analysis_end)
    if runtime_seconds is not None:
        _set_datapoint_value(sections, "section_1", "total_runtime_seconds", runtime_seconds)

    # Section 2: validation totals from analysis log phase metrics
    validation_phase = _find_phase(analysis_log, "Data Validation") or {}
    total_raw = _metric_value(validation_phase, "input_records")
    validated = _metric_value(validation_phase, "validated_records")
    duplicates_removed = _metric_value(validation_phase, "duplicates_removed")
    invalid_including_duplicates = _metric_value(validation_phase, "invalid_records")
    negative_energy = _metric_value(validation_phase, "negative_energy_values")
    negative_co2 = _metric_value(validation_phase, "negative_co2_values")

    # Prefer consistent derivations where possible
    try:
        total_raw_int = int(total_raw) if total_raw is not None else None
        validated_int = int(validated) if validated is not None else None
        duplicates_int = int(duplicates_removed) if duplicates_removed is not None else 0

        excluded_total_int = None
        if total_raw_int is not None and validated_int is not None:
            excluded_total_int = max(total_raw_int - validated_int, 0)

        invalid_excl_dupes_int = None
        if excluded_total_int is not None:
            invalid_excl_dupes_int = max(excluded_total_int - duplicates_int, 0)
        elif invalid_including_duplicates is not None:
            invalid_excl_dupes_int = max(int(invalid_including_duplicates) - duplicates_int, 0)

        if total_raw_int is not None:
            _set_datapoint_value(sections, "section_2", "total_raw_records", total_raw_int)
        if validated_int is not None:
            _set_datapoint_value(sections, "section_2", "records_passing_validation", validated_int)
        if excluded_total_int is not None:
            _set_datapoint_value(sections, "section_2", "records_excluded_total", excluded_total_int)

        _set_datapoint_value(sections, "section_2", "duplicates_removed", duplicates_int)

        if invalid_excl_dupes_int is not None:
            _set_datapoint_value(sections, "section_2", "invalid_records", invalid_excl_dupes_int)

        if negative_energy is not None:
            _set_datapoint_value(sections, "section_2", "negative_energy_values", int(negative_energy))
        if negative_co2 is not None:
            _set_datapoint_value(sections, "section_2", "negative_co2_values", int(negative_co2))
    except Exception as exc:
        logger.warning(f"Could not patch Section 2 validation totals: {exc}")

    # Section 6: patch cost-effectiveness bucket completeness if marginal values are missing.
    try:
        if _patch_cost_effectiveness_marginal_bucket(sections):
            logger.info("Patched Section 6 cost-effectiveness buckets with marginal_count/marginal_pct")
    except Exception as exc:
        logger.warning(f"Could not patch Section 6 cost-effectiveness buckets: {exc}")

    # Persist patched output
    one_stop["sections"] = sections

    if create_backup:
        backup_path = _backup_file(one_stop_path)
        if backup_path:
            logger.info(f"Backed up one-stop output to {backup_path}")

    one_stop_path.write_text(json.dumps(one_stop, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Patched one-stop output written to {one_stop_path}")
    return one_stop_path


if __name__ == "__main__":
    patch_one_stop_output(Path("data/outputs"))
