"""
Heat Street EPC Analysis - Complete Interactive Pipeline

Runs the entire analysis from data download to report generation
with interactive prompts and progress indicators.
"""

import os
import io
import json
import shutil
import sys
import subprocess
import argparse
import importlib
import inspect
import gc
import re
import platform
import contextlib
import warnings
import hashlib
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union
from datetime import date as date_cls, datetime, timedelta
from dataclasses import replace
from loguru import logger
import questionary
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel
from rich import print as rprint
import time

# Add src to path
sys.path.append(str(Path(__file__).parent))

from config.config import load_config, ensure_directories, DATA_RAW_DIR, DATA_PROCESSED_DIR, DATA_OUTPUTS_DIR
from src.acquisition.epc_api_downloader import (
    EPCAPIDownloader,
    EPCDownloadError,
    EPCStockDefinitionError,
)
from src.acquisition.hnpd_downloader import HNPDDownloader
from src.cleaning.data_validator import EPCDataValidator
from src.analysis.archetype_analysis import ArchetypeAnalyzer
from src.modeling.scenario_model import ScenarioModeler
from src.modeling.pathway_model import PathwayModeler
from src.reporting.comparisons import ComparisonReporter
from src.utils.analysis_logger import AnalysisLogger
from src.utils.staged_dataset import DatasetReference, parquet_row_count
from src.utils.staged_processing import (
    apply_adjustments_staged_dataset,
    validate_staged_dataset,
)
from src.utils.diagnostic_phase import DiagnosticPathwayPhaseError
from src.utils.run_integrity import (
    ArtifactManifest,
    RunContext,
    fingerprint_dataset,
    publish_run_outputs,
    stamp_artifact,
    stamp_artifact_tree,
)
from src.ui import create_dashboard
from src.ui.formatters import format_duration


console = Console()

EXIT_SUCCESS = 0
EXIT_ANALYSIS_FAILED = 1
EXIT_CANCELLED = 130
REPO_ROOT = Path(__file__).resolve().parent
_hp_hn_comparison_outputs_cache: Optional[Dict[str, Any]] = None
_active_run_context: Optional[RunContext] = None
_active_authoritative_cohort_size: Optional[int] = None
_public_outputs_dir: Optional[Path] = None
_run_path_redirections: list[tuple[object, str, object]] = []

PHASE_ACQUISITION = "Acquisition"
PHASE_VALIDATION = "Validation"
PHASE_MODELLING = "Modelling"
PHASE_OUTPUTS = "Outputs"

EXPECTED_STAGED_DOWNLOAD_DATA_MARKERS = (
    "download_national_domestic_dataset(",
    "materialize_full_load_subset(",
    'Using staged Parquet processing for the national EPC full-load extract',
)

EXPECTED_STAGED_NATIONAL_DOWNLOADER_MARKERS = (
    "create_attempt_directory(stage_dir)",
    "write_parquet_part(",
    "ignored_recommendation_members",
    "rows_retained_after_sample_window",
)


class AnalysisCancelled(Exception):
    """User cancelled the interactive analysis flow."""


def _configure_run_directories(
    context: RunContext,
    analysis_logger: AnalysisLogger,
    *,
    isolate_processed: bool,
) -> Path:
    """Redirect run writes away from the public output tree."""
    global DATA_OUTPUTS_DIR, DATA_PROCESSED_DIR, _public_outputs_dir, _run_path_redirections

    public_outputs = Path(DATA_OUTPUTS_DIR)
    public_processed = Path(DATA_PROCESSED_DIR)
    run_root = public_outputs.parent / "runs" / context.run_id
    run_outputs = run_root / "outputs"
    run_processed = run_root / "processed"

    old_outputs = public_outputs
    old_processed = public_processed
    changed: set[tuple[int, str]] = set()
    _run_path_redirections = []
    for module in list(sys.modules.values()):
        if module is None:
            continue
        try:
            if getattr(module, "DATA_OUTPUTS_DIR", None) == old_outputs:
                key = (id(module), "DATA_OUTPUTS_DIR")
                if key not in changed:
                    _run_path_redirections.append((module, "DATA_OUTPUTS_DIR", old_outputs))
                    changed.add(key)
                setattr(module, "DATA_OUTPUTS_DIR", run_outputs)
            if isolate_processed and getattr(module, "DATA_PROCESSED_DIR", None) == old_processed:
                key = (id(module), "DATA_PROCESSED_DIR")
                if key not in changed:
                    _run_path_redirections.append((module, "DATA_PROCESSED_DIR", old_processed))
                    changed.add(key)
                setattr(module, "DATA_PROCESSED_DIR", run_processed)
        except Exception:
            continue

    DATA_OUTPUTS_DIR = run_outputs
    if isolate_processed:
        DATA_PROCESSED_DIR = run_processed
    _public_outputs_dir = public_outputs
    run_outputs.mkdir(parents=True, exist_ok=True)
    run_processed.mkdir(parents=True, exist_ok=True)
    (run_root / "logs").mkdir(parents=True, exist_ok=True)
    analysis_logger.output_dir = run_outputs
    return run_root


def _restore_run_directories() -> None:
    """Undo process-local compatibility redirects after a run completes."""
    global DATA_OUTPUTS_DIR, DATA_PROCESSED_DIR, _run_path_redirections
    for module, attribute, original_value in reversed(_run_path_redirections):
        try:
            setattr(module, attribute, original_value)
        except Exception:
            continue
    _run_path_redirections = []


def _write_current_run_metadata(
    analysis_logger: AnalysisLogger,
    context: RunContext,
    cohort_size: int,
) -> Path:
    metadata_path = Path(DATA_OUTPUTS_DIR) / "run_metadata.json"
    payload = {
        **context.to_dict(),
        "start_time": analysis_logger.metadata.get("analysis_start") or context.analysis_start,
        "end_time": analysis_logger.metadata.get("analysis_end") or context.analysis_end,
        "runtime_seconds": analysis_logger.metadata.get("total_duration_seconds") or context.runtime_seconds,
        "authoritative_cohort_size": int(cohort_size),
    }
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    stamp_artifact(metadata_path, context, record_count=cohort_size)
    return metadata_path


def _register_current_artifacts(context: RunContext) -> ArtifactManifest:
    """Register the explicit current-run artifacts; never discover shared outputs."""
    manifest = ArtifactManifest.load(context)
    artifact_map = {
        "run_metadata": (Path(DATA_OUTPUTS_DIR) / "run_metadata.json", "provenance", True, "client"),
        "validation_report": (Path(DATA_PROCESSED_DIR) / "validation_report.json", "validation", True, "client"),
        "published_validation_report": (Path(DATA_OUTPUTS_DIR) / "validation_report.json", "client_outputs", True, "client"),
        "adjustment_summary": (Path(DATA_PROCESSED_DIR) / "methodological_adjustments_summary.json", "adjustments", True, "client"),
        "adjusted_dataset": (Path(DATA_PROCESSED_DIR) / "epc_london_adjusted.parquet", "adjustments", True, "internal"),
        "archetype_analysis": (Path(DATA_OUTPUTS_DIR) / "archetype_analysis_results.json", "analysis", True, "client"),
        "readiness": (Path(DATA_OUTPUTS_DIR) / "retrofit_readiness_analysis.csv", "analysis", True, "client"),
        "spatial_suitability": (Path(DATA_OUTPUTS_DIR) / "pathway_suitability_by_tier.csv", "analysis", True, "client"),
        "internal_scenarios": (Path(DATA_OUTPUTS_DIR) / "internal_scenario_results.csv", "modelling", True, "internal"),
        "client_scenarios": (Path(DATA_OUTPUTS_DIR) / "scenario_results_summary.csv", "modelling", True, "client"),
        "diagnostic_pathway_properties": (Path(DATA_OUTPUTS_DIR) / "pathway_results_by_property.parquet", "diagnostic_pathways", True, "internal"),
        "diagnostic_pathways": (Path(DATA_OUTPUTS_DIR) / "pathway_results_summary.csv", "diagnostic_pathways", True, "internal"),
        "diagnostic_hp_hn_comparison": (Path(DATA_OUTPUTS_DIR) / "comparisons" / "hn_vs_hp_comparison.csv", "diagnostic_pathways", True, "internal"),
        "run_comparison": (Path(DATA_OUTPUTS_DIR) / "old_vs_corrected_comparison.csv", "verification", False, "internal"),
        "borough_breakdown": (Path(DATA_OUTPUTS_DIR) / "borough_breakdown.csv", "reporting", True, "client"),
        "borough_priority": (Path(DATA_OUTPUTS_DIR) / "reports" / "borough_priority_ranking.csv", "reporting", True, "client"),
        "tenure_segmentation": (Path(DATA_OUTPUTS_DIR) / "reports" / "tenure_segmentation.csv", "reporting", True, "client"),
        "network_thresholds": (Path(DATA_OUTPUTS_DIR) / "heat_network_connection_thresholds.csv", "reporting", True, "client"),
        "case_street_extract": (Path(DATA_OUTPUTS_DIR) / "shakespeare_crescent_extract.csv", "reporting", True, "client"),
        "case_street_summary": (Path(DATA_OUTPUTS_DIR) / "shakespeare_crescent_summary.txt", "reporting", True, "client"),
        "subsidy_detailed": (Path(DATA_OUTPUTS_DIR) / "subsidy_sensitivity_analysis.csv", "modelling", True, "client"),
        "subsidy_simplified": (Path(DATA_OUTPUTS_DIR) / "subsidy_sensitivity_analysis_simple_gbp.csv", "reporting", True, "client"),
        "one_stop_json": (Path(DATA_OUTPUTS_DIR) / "one_stop_output.json", "client_outputs", True, "client"),
        "dashboard_data": (Path(DATA_OUTPUTS_DIR) / "dashboard" / "dashboard-data.json", "client_outputs", True, "client"),
        "dashboard_html": (Path(DATA_OUTPUTS_DIR) / "one_stop_dashboard.html", "client_outputs", True, "client"),
        "analysis_compendium": (Path(DATA_OUTPUTS_DIR) / "analysis_outputs_compendium.xlsx", "client_outputs", True, "client"),
    }
    for logical_name, (path, phase, required, scope) in artifact_map.items():
        if path.is_file():
            manifest.register(
                logical_name,
                path,
                phase=phase,
                required=required,
                publication_scope=scope,
                cohort=context.authoritative_cohort,
            )
    return manifest


def _require_contract(manifest: ArtifactManifest, logical_names: list[str]) -> None:
    """Validate explicit required artifacts through the active manifest."""
    manifest.require(logical_names)


def _register_required_artifacts(
    context: RunContext,
    *,
    phase: str,
    artifacts: list[tuple[str, Path, str]],
) -> ArtifactManifest:
    """Stamp, register, and immediately require a mandatory phase artifact set."""
    manifest = ArtifactManifest.load(context)
    for logical_name, path, publication_scope in artifacts:
        path = Path(path)
        if path.is_file():
            stamp_artifact(path, context)
            manifest.register(
                logical_name,
                path,
                phase=phase,
                required=True,
                publication_scope=publication_scope,
                cohort=context.authoritative_cohort,
            )
    _require_contract(manifest, [name for name, _, _ in artifacts])
    return manifest


def _load_adjusted_phase_frame(phase_name: str):
    """Load the run-scoped adjusted Parquet boundary for an analytical phase."""
    import pandas as pd

    path = Path(DATA_PROCESSED_DIR) / "epc_london_adjusted.parquet"
    if not path.is_file():
        raise RuntimeError(f"{phase_name} requires the authoritative adjusted Parquet: {path}")
    frame = pd.read_parquet(path)
    expected = _active_authoritative_cohort_size
    if expected is not None and len(frame) != int(expected):
        raise RuntimeError(
            f"{phase_name} adjusted-Parquet cohort mismatch: rows={len(frame)}, expected={expected}"
        )
    return frame


def _checkpoint(analysis_logger: Optional[AnalysisLogger], status: str = "running") -> None:
    if analysis_logger is not None and hasattr(analysis_logger, "save_checkpoint"):
        analysis_logger.save_checkpoint(status=status)


def _mark_active_run_failed() -> None:
    """Persist failed lifecycle state without finalizing or publishing the run."""
    global _active_run_context
    if _active_run_context is None:
        return
    _active_run_context = _active_run_context.fail()
    try:
        ArtifactManifest.load(_active_run_context).save()
    except Exception:
        logger.exception("Could not persist failed run context")


def _ui_call(ui, method_name: str, *args, **kwargs):
    """Call a dashboard method without allowing UI errors into the pipeline."""
    if ui is None:
        return None
    try:
        method = getattr(ui, method_name, None)
        if method is None:
            return None
        return method(*args, **kwargs)
    except Exception:
        return None


@contextlib.contextmanager
def _ui_suspend(ui, message: str = ""):
    """Temporarily suspend Live rendering around an interactive prompt."""
    if ui is None or not hasattr(ui, "suspend_for_prompt"):
        yield
        return
    manager = ui.suspend_for_prompt(message)
    if manager is None:
        yield
        return
    with manager:
        yield


def _ui_phase_started(ui, name: str, message: str = "") -> None:
    _ui_call(ui, "phase_started", name, message)


def _ui_phase_progress(ui, name: str, message: str) -> None:
    _ui_call(ui, "phase_progress", name, message)


def _ui_phase_completed(ui, name: str, message: str = "") -> None:
    _ui_call(ui, "phase_completed", name, message)


def _ui_phase_failed(ui, name: str, message: str = "") -> None:
    _ui_call(ui, "phase_failed", name, message)


def _ui_phase_skipped(ui, name: str, message: str = "") -> None:
    _ui_call(ui, "phase_skipped", name, message)


def _ui_metric(ui, key: str, value: Any, group: Optional[str] = None) -> None:
    _ui_call(ui, "metric", key, value, group=group)


def _ui_output(ui, label: str, path: Any) -> None:
    _ui_call(ui, "output", label, path)


def _ui_warning(ui, message: str) -> None:
    _ui_call(ui, "warning", message)


def _ui_info(ui, message: str) -> None:
    _ui_call(ui, "info", message)


def _ui_suppresses_progress(ui) -> bool:
    """Return True when external progress bars should stay silent."""
    return bool(getattr(ui, "suppress_external_progress", False))


def _ui_scenario_started(ui, name: str) -> None:
    _ui_call(ui, "scenario_started", name)


def _ui_scenario_progress(ui, name: str, completed=None, total=None, metrics=None) -> None:
    _ui_call(ui, "scenario_progress", name, completed=completed, total=total, metrics=metrics)


def _ui_scenario_completed(ui, name: str, metrics=None, outputs=None) -> None:
    _ui_call(ui, "scenario_completed", name, metrics=metrics, outputs=outputs)


def _tui_prompt(ui, prompt_type: str, **kwargs) -> Optional[Any]:
    """Request a TUI modal prompt if the UI supports it; return None to fall back."""
    if ui is None:
        return None
    prompt_fn = getattr(ui, "prompt_request", None)
    if prompt_fn is None:
        return None
    try:
        return prompt_fn(prompt_type, **kwargs)
    except Exception:
        logger.warning("TUI prompt_request raised; falling back to questionary", exc_info=True)
        return None


def _render_console_message(objects: tuple[Any, ...], kwargs: Dict[str, Any]) -> str:
    """Render Rich console print arguments to plain text for dashboard events."""
    buffer = io.StringIO()
    capture = Console(file=buffer, force_terminal=False, color_system=None, width=100)
    allowed_kwargs = {
        key: value
        for key, value in kwargs.items()
        if key
        in {
            "style",
            "justify",
            "overflow",
            "no_wrap",
            "emoji",
            "markup",
            "highlight",
            "soft_wrap",
            "new_line_start",
            "crop",
        }
    }
    try:
        capture.print(*objects, **allowed_kwargs)
    except Exception:
        return " ".join(str(obj) for obj in objects)
    return buffer.getvalue().strip()


@contextlib.contextmanager
def _route_console_output_for_tui(ui):
    """Route routine console prints into the full TUI while Rich Live is active."""
    if not (
        getattr(ui, "route_console_output", False)
        and not getattr(ui, "verbose", False)
    ):
        yield
        return

    original_print = console.print
    original_clear = console.clear
    original_rprint = globals().get("rprint")

    def passthrough_allowed() -> bool:
        return bool(getattr(ui, "allow_console_output", False)) or not bool(
            getattr(ui, "is_live_active", False)
        )

    def routed_print(*objects, **kwargs):
        if passthrough_allowed():
            return original_print(*objects, **kwargs)
        text = _render_console_message(objects, kwargs)
        if not text:
            return None
        lowered = text.lower()
        if any(token in lowered for token in ("warning", "failed", "error", "could not", "cannot")):
            _ui_warning(ui, text)
        else:
            _ui_info(ui, text)
        return None

    def routed_clear(*args, **kwargs):
        if passthrough_allowed():
            return original_clear(*args, **kwargs)
        return None

    console.print = routed_print
    console.clear = routed_clear
    globals()["rprint"] = routed_print
    try:
        yield
    finally:
        console.print = original_print
        console.clear = original_clear
        if original_rprint is not None:
            globals()["rprint"] = original_rprint


@contextlib.contextmanager
def _configure_tui_logging(ui):
    """Keep loguru/Python warning output away from the live screen."""
    if not getattr(ui, "is_full_tui", False):
        yield
        return

    DATA_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = DATA_OUTPUTS_DIR / "mission_control.log"
    original_showwarning = warnings.showwarning

    try:
        logger.remove()
    except ValueError:
        pass
    logger.add(log_path, level="INFO", encoding="utf-8", backtrace=False, diagnose=False)

    def showwarning(message, category, filename, lineno, file=None, line=None):
        summary = f"{category.__name__}: {message}"
        _ui_warning(ui, summary)
        logger.warning(f"{summary} ({filename}:{lineno})")

    warnings.showwarning = showwarning
    try:
        yield
    finally:
        warnings.showwarning = original_showwarning
        try:
            logger.remove()
        except ValueError:
            pass
        logger.add(sys.stderr, level="DEBUG")


@contextlib.contextmanager
def _external_progress_context(ui):
    """Disable external tqdm-style progress output under the full TUI."""
    if not _ui_suppresses_progress(ui):
        yield
        return

    previous = os.environ.get("TQDM_DISABLE")
    os.environ["TQDM_DISABLE"] = "1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("TQDM_DISABLE", None)
        else:
            os.environ["TQDM_DISABLE"] = previous


def _call_with_optional_ui(func, *args, ui=None, **kwargs):
    """Call a function with only keyword arguments supported by its signature."""
    try:
        signature = inspect.signature(func)
        parameters = signature.parameters
        accepts_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
        if ui is not None and ("ui" in parameters or accepts_kwargs):
            kwargs["ui"] = ui
        if not accepts_kwargs:
            kwargs = {key: value for key, value in kwargs.items() if key in parameters}
    except (TypeError, ValueError):
        if ui is not None:
            kwargs["ui"] = ui
    return func(*args, **kwargs)


def _make_epc_progress_callback(ui):
    """Translate acquisition callback dictionaries into dashboard metrics."""
    if ui is None:
        return None

    counters: Dict[str, int] = {
        "certificate members selected": 0,
        "recommendation members ignored": 0,
        "members processed": 0,
        "rows read": 0,
        "rows retained": 0,
        "malformed rows skipped": 0,
        "Parquet parts written": 0,
    }

    def _update_acq_state(key: str, value) -> None:
        """Update DashboardState.acquisition directly if the UI has rich state."""
        try:
            state = getattr(ui, "state", None) or getattr(getattr(ui, "_base", None), "state", None)
            if state is not None:
                acq = getattr(state, "acquisition", None)
                if acq is not None:
                    setattr(acq, key, value)
        except Exception:
            pass

    def callback(event: Dict[str, Any]) -> None:
        try:
            event_type = event.get("event")
            if event_type == "reusable_staged_dataset_accepted":
                _ui_info(ui, "Reusable staged EPC full-load dataset accepted")
                if event.get("row_count") is not None:
                    row_count = event.get("row_count")
                    _ui_metric(ui, "rows retained", row_count, group=PHASE_ACQUISITION)
                    _update_acq_state("rows_retained", row_count)
                if event.get("dataset_path"):
                    _ui_output(ui, "Reusable EPC staged dataset", event.get("dataset_path"))
            elif event_type == "attempt_directory_created":
                _ui_info(ui, "Created EPC full-load attempt directory")
            elif event_type == "zip_download_started":
                _ui_phase_progress(ui, "Data Download", "Downloading EPC full-load ZIP")
                _update_acq_state("zip_status", "downloading")
            elif event_type == "zip_validation_complete":
                size = event.get("size_bytes", 0)
                _ui_metric(ui, "EPC ZIP bytes", size, group=PHASE_ACQUISITION)
                _update_acq_state("zip_bytes_total", size)
                _update_acq_state("zip_status", "done")
            elif event_type == "member_selection_complete":
                selected = len(event.get("selected_certificate_members") or [])
                ignored = len(event.get("ignored_recommendation_members") or [])
                counters["certificate members selected"] = selected
                counters["recommendation members ignored"] = ignored
                _ui_metric(ui, "certificate members selected", selected, group=PHASE_ACQUISITION)
                _ui_metric(ui, "recommendation members ignored", ignored, group=PHASE_ACQUISITION)
                _update_acq_state("members_selected", selected)
                _update_acq_state("members_ignored", ignored)
            elif event_type == "member_started":
                _ui_phase_progress(ui, "Data Download", f"Reading {event.get('member')}")
            elif event_type == "chunk_parsed":
                counters["rows read"] += int(event.get("rows_read", 0) or 0)
                counters["rows retained"] += int(event.get("rows_retained", 0) or 0)
                _ui_metric(ui, "rows read", counters["rows read"], group=PHASE_ACQUISITION)
                _ui_metric(ui, "rows retained", counters["rows retained"], group=PHASE_ACQUISITION)
                _update_acq_state("rows_read", counters["rows read"])
                _update_acq_state("rows_retained", counters["rows retained"])
            elif event_type == "parquet_part_written":
                counters["Parquet parts written"] += 1
                _ui_metric(ui, "Parquet parts written", counters["Parquet parts written"], group=PHASE_ACQUISITION)
                _update_acq_state("parquet_parts", counters["Parquet parts written"])
            elif event_type == "member_complete":
                counters["members processed"] += 1
                malformed = int(event.get("malformed_rows_skipped", 0) or 0)
                counters["malformed rows skipped"] += malformed
                _ui_metric(ui, "members processed", counters["members processed"], group=PHASE_ACQUISITION)
                _ui_metric(ui, "malformed rows skipped", counters["malformed rows skipped"], group=PHASE_ACQUISITION)
                _update_acq_state("members_processed", counters["members processed"])
                _update_acq_state("rows_malformed", counters["malformed rows skipped"])
            elif event_type == "dataset_reference_created":
                row_count = event.get("row_count", 0)
                _ui_metric(ui, "rows retained", row_count, group=PHASE_ACQUISITION)
                _ui_output(ui, "National EPC staged dataset", event.get("parquet_path"))
                _update_acq_state("rows_retained", row_count)
            elif event_type in ("stock_filtered", "subset_materialized"):
                count = event.get("row_count") or event.get("record_count")
                if count is not None:
                    key = "london_records" if event_type == "subset_materialized" else "stock_records"
                    _update_acq_state(key, count)
        except Exception:
            return None

    return callback


def _make_pathway_progress_callback(ui):
    """Translate property_progress events into dashboard progress updates for pathway modeling."""
    if ui is None:
        return None

    def callback(event: Dict[str, Any]) -> None:
        try:
            if event.get("event") != "property_progress":
                return
            current = event.get("current", 0)
            total = event.get("total", 0)
            rate = event.get("rows_per_second", 0.0)
            eta = event.get("eta_seconds")
            rate_str = f"  {rate:.2f}/s" if rate > 0 else ""
            eta_str = "calculating..." if eta is None else format_duration(eta)
            msg = f"Pathway {current}/{total}{rate_str}  ETA {eta_str}"
            _ui_phase_progress(ui, "Pathway Modeling", msg)
            _ui_call(ui, "progress", current, total)
        except Exception:
            pass

    return callback


def _make_scenario_progress_callback(ui):
    """Translate scenario_* events into dashboard updates during scenario modeling."""
    if ui is None:
        return None

    def callback(event: Dict[str, Any]) -> None:
        try:
            event_type = event.get("event")
            scenario_name = event.get("scenario_name", "")

            if event_type == "scenario_started":
                _ui_scenario_started(ui, scenario_name)
                _ui_phase_progress(ui, "Scenario Modeling", f"Modeling {scenario_name}...")

            elif event_type == "scenario_chunk_progress":
                chunk_idx = event.get("chunk_idx", 0)
                num_chunks = event.get("num_chunks", 0)
                props_done = event.get("properties_done", 0)
                total_props = event.get("total_properties", 0)
                msg = f"{scenario_name}: chunk {chunk_idx}/{num_chunks}  {props_done:,}/{total_props:,} properties"
                _ui_phase_progress(ui, "Scenario Modeling", msg)
                _ui_scenario_progress(ui, scenario_name, completed=props_done, total=total_props)

            elif event_type == "scenario_completed":
                _ui_scenario_completed(ui, scenario_name)
        except Exception:
            pass

    return callback


def _add_metric(
    analysis_logger: Optional[AnalysisLogger],
    ui,
    key: str,
    value: Any,
    description: str = "",
    *,
    group: Optional[str] = None,
) -> None:
    """Mirror an audit metric into the dashboard where available."""
    if analysis_logger:
        analysis_logger.add_metric(key, value, description)
    _ui_metric(ui, key, value, group=group)


def _register_output(
    analysis_logger: Optional[AnalysisLogger],
    ui,
    output_path: Union[str, Path],
    output_type: str,
    description: str,
) -> bool:
    """Register an output with the audit logger and the optional dashboard."""
    registered = add_analysis_output_if_exists(analysis_logger, output_path, output_type, description)
    if registered:
        _ui_output(ui, description or output_type, output_path)
    return registered


def _safe_resolve_path(value: Optional[Union[str, Path]]) -> Optional[str]:
    """Return a normalized absolute path string when possible."""
    if not value:
        return None

    try:
        return str(Path(value).resolve())
    except Exception:
        return str(value)


def _get_source_location(target) -> Tuple[Optional[str], Optional[int]]:
    """Return the resolved source file and first line number for a callable."""
    try:
        source_file = inspect.getsourcefile(target) or inspect.getfile(target)
        _, start_line = inspect.getsourcelines(target)
    except (OSError, TypeError):
        return None, None

    return _safe_resolve_path(source_file), int(start_line)


def _get_source_text(target) -> Optional[str]:
    """Return source text for a callable when inspect can resolve it."""
    try:
        return inspect.getsource(target)
    except (OSError, TypeError):
        return None


def _path_within_repo(path_value: Optional[str]) -> bool:
    """Return True when a path resolves inside the active repo root."""
    if not path_value:
        return False

    try:
        Path(path_value).resolve().relative_to(REPO_ROOT)
        return True
    except Exception:
        return False


def _resolve_git_commit_hash() -> Optional[str]:
    """Resolve the active git commit hash when available."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None

    if result.returncode != 0:
        return None

    commit_hash = result.stdout.strip()
    return commit_hash or None


def _missing_source_markers(source_text: Optional[str], markers: tuple[str, ...]) -> list[str]:
    """Return the expected staged markers that are absent from a source block."""
    if source_text is None:
        return list(markers)
    return [marker for marker in markers if marker not in source_text]


def collect_runtime_identity() -> Dict[str, Any]:
    """Collect interpreter, checkout, and source-location details for startup diagnostics."""
    download_data_file, download_data_line = _get_source_location(download_data)
    national_dataset_file, national_dataset_line = _get_source_location(
        EPCAPIDownloader.download_national_domestic_dataset
    )
    downloader_module = inspect.getmodule(EPCAPIDownloader)

    return {
        "repo_root": str(REPO_ROOT),
        "python_executable": _safe_resolve_path(sys.executable),
        "working_directory": _safe_resolve_path(Path.cwd()),
        "run_analysis_file": _safe_resolve_path(__file__),
        "epc_api_downloader_file": _safe_resolve_path(getattr(downloader_module, "__file__", None)),
        "download_data_source_file": download_data_file,
        "download_data_line": download_data_line,
        "download_national_domestic_dataset_source_file": national_dataset_file,
        "download_national_domestic_dataset_line": national_dataset_line,
        "git_commit_hash": _resolve_git_commit_hash(),
        "conda_env_name": os.getenv("CONDA_DEFAULT_ENV") or None,
        "conda_prefix": _safe_resolve_path(os.getenv("CONDA_PREFIX")),
    }


def run_startup_preflight(runtime_identity: Dict[str, Any]) -> Dict[str, Any]:
    """
    Verify that the live runtime resolves to the staged national-ingest path.

    This is intentionally strict so old in-memory full-load behavior cannot run
    silently from the wrong interpreter, checkout, or import path.
    """
    checks = []
    issues = []

    def add_check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    download_data_source = _get_source_text(download_data)
    missing_download_markers = _missing_source_markers(
        download_data_source,
        EXPECTED_STAGED_DOWNLOAD_DATA_MARKERS,
    )
    download_location = (
        f"{runtime_identity.get('download_data_source_file') or 'unknown'}:"
        f"{runtime_identity.get('download_data_line') or 'unknown'}"
    )
    download_data_ok = not missing_download_markers and _path_within_repo(
        runtime_identity.get("download_data_source_file")
    )
    if download_data_ok:
        add_check(
            "download_data() staged implementation",
            True,
            f"resolved to {download_location}",
        )
    else:
        detail_parts = [f"resolved to {download_location}"]
        if missing_download_markers:
            detail_parts.append(
                "missing staged markers: " + ", ".join(missing_download_markers)
            )
        if not _path_within_repo(runtime_identity.get("download_data_source_file")):
            detail_parts.append("source file is outside the active repo root")
        detail = "; ".join(detail_parts)
        add_check("download_data() staged implementation", False, detail)
        issues.append(
            "download_data() did not resolve to the staged national-ingest block. "
            f"{detail}."
        )

    national_source = _get_source_text(EPCAPIDownloader.download_national_domestic_dataset)
    missing_national_markers = _missing_source_markers(
        national_source,
        EXPECTED_STAGED_NATIONAL_DOWNLOADER_MARKERS,
    )
    national_location = (
        f"{runtime_identity.get('download_national_domestic_dataset_source_file') or 'unknown'}:"
        f"{runtime_identity.get('download_national_domestic_dataset_line') or 'unknown'}"
    )
    national_ok = not missing_national_markers and _path_within_repo(
        runtime_identity.get("download_national_domestic_dataset_source_file")
    )
    if national_ok:
        add_check(
            "download_national_domestic_dataset() staged implementation",
            True,
            f"resolved to {national_location}",
        )
    else:
        detail_parts = [f"resolved to {national_location}"]
        if missing_national_markers:
            detail_parts.append(
                "missing staged markers: " + ", ".join(missing_national_markers)
            )
        if not _path_within_repo(runtime_identity.get("download_national_domestic_dataset_source_file")):
            detail_parts.append("source file is outside the active repo root")
        detail = "; ".join(detail_parts)
        add_check(
            "download_national_domestic_dataset() staged implementation",
            False,
            detail,
        )
        issues.append(
            "EPCAPIDownloader.download_national_domestic_dataset() did not resolve "
            f"to the dataset-backed staged implementation. {detail}."
        )

    for module_name in ("src.utils.staged_dataset", "src.utils.staged_processing"):
        try:
            module = importlib.import_module(module_name)
            module_file = _safe_resolve_path(getattr(module, "__file__", None))
            add_check(
                f"import {module_name}",
                True,
                module_file or "imported successfully",
            )
        except Exception as exc:
            add_check(f"import {module_name}", False, str(exc))
            issues.append(
                f"{module_name} could not be imported in this runtime: {exc}"
            )

    try:
        duckdb_module = importlib.import_module("duckdb")
        duckdb_file = _safe_resolve_path(getattr(duckdb_module, "__file__", None))
        add_check(
            "import duckdb",
            True,
            duckdb_file or "imported successfully",
        )
    except Exception as exc:
        add_check("import duckdb", False, str(exc))
        issues.append(
            "duckdb is not importable, so staged national EPC ingest cannot run: "
            f"{exc}"
        )

    return {
        "status": "passed" if not issues else "failed",
        "ok": not issues,
        "checks": checks,
        "issues": issues,
        "likely_causes": [
            "different checkout",
            "stale installed package or alternate import path",
            "wrong interpreter",
            "stale copied script outside the repo root",
        ],
    }


def persist_startup_diagnostics(
    analysis_logger: Optional[AnalysisLogger],
    runtime_identity: Dict[str, Any],
    preflight: Dict[str, Any],
) -> None:
    """Persist startup diagnostics into analysis-log metadata."""
    if analysis_logger is None:
        return

    analysis_logger.set_metadata("runtime_identity", runtime_identity)
    analysis_logger.set_metadata("startup_preflight", preflight)
    analysis_logger.set_metadata(
        "runtime_python_executable",
        runtime_identity.get("python_executable"),
    )
    analysis_logger.set_metadata(
        "runtime_working_directory",
        runtime_identity.get("working_directory"),
    )
    analysis_logger.set_metadata(
        "runtime_run_analysis_file",
        runtime_identity.get("run_analysis_file"),
    )
    analysis_logger.set_metadata(
        "runtime_epc_api_downloader_file",
        runtime_identity.get("epc_api_downloader_file"),
    )
    analysis_logger.set_metadata(
        "runtime_download_data_source",
        (
            f"{runtime_identity.get('download_data_source_file')}:"
            f"{runtime_identity.get('download_data_line')}"
        ),
    )
    analysis_logger.set_metadata(
        "runtime_download_national_domestic_dataset_source",
        (
            f"{runtime_identity.get('download_national_domestic_dataset_source_file')}:"
            f"{runtime_identity.get('download_national_domestic_dataset_line')}"
        ),
    )
    analysis_logger.set_metadata(
        "runtime_git_commit_hash",
        runtime_identity.get("git_commit_hash") or "unavailable",
    )
    analysis_logger.set_metadata(
        "runtime_conda_env_name",
        runtime_identity.get("conda_env_name") or "not set",
    )
    analysis_logger.set_metadata(
        "runtime_conda_prefix",
        runtime_identity.get("conda_prefix") or "not set",
    )
    analysis_logger.set_metadata(
        "startup_preflight_status",
        preflight.get("status"),
    )


def emit_startup_diagnostics(
    analysis_logger: Optional[AnalysisLogger] = None,
    runtime_identity: Optional[Dict[str, Any]] = None,
    preflight: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Print and persist the runtime identity plus staged-path preflight checks."""
    runtime_identity = runtime_identity or collect_runtime_identity()
    preflight = preflight or run_startup_preflight(runtime_identity)
    persist_startup_diagnostics(analysis_logger, runtime_identity, preflight)

    conda_env = runtime_identity.get("conda_env_name") or "not set"
    git_commit = runtime_identity.get("git_commit_hash") or "unavailable"
    status_text = "PASSED" if preflight.get("ok") else "FAILED"
    status_color = "green" if preflight.get("ok") else "red"

    lines = [
        "[bold]Runtime Identity[/bold]",
        f"Python executable: {runtime_identity.get('python_executable') or 'unknown'}",
        f"Working directory: {runtime_identity.get('working_directory') or 'unknown'}",
        f"run_analysis.__file__: {runtime_identity.get('run_analysis_file') or 'unknown'}",
        (
            "src.acquisition.epc_api_downloader.__file__: "
            f"{runtime_identity.get('epc_api_downloader_file') or 'unknown'}"
        ),
        (
            "download_data(): "
            f"{runtime_identity.get('download_data_source_file') or 'unknown'}:"
            f"{runtime_identity.get('download_data_line') or 'unknown'}"
        ),
        (
            "download_national_domestic_dataset(): "
            f"{runtime_identity.get('download_national_domestic_dataset_source_file') or 'unknown'}:"
            f"{runtime_identity.get('download_national_domestic_dataset_line') or 'unknown'}"
        ),
        f"Git commit: {git_commit}",
        f"Conda env: {conda_env}",
        "",
        f"[bold]Startup Preflight: {status_text}[/bold]",
    ]

    for check in preflight.get("checks", []):
        prefix = "[green]OK[/green]" if check.get("ok") else "[red]X[/red]"
        lines.append(f"{prefix} {check.get('name')}: {check.get('detail')}")

    if preflight.get("issues"):
        lines.extend(
            [
                "",
                "[bold]Failures[/bold]",
                *[f"- {issue}" for issue in preflight.get("issues", [])],
                "",
                "[bold]Likely causes[/bold]",
                *[f"- {cause}" for cause in preflight.get("likely_causes", [])],
                "",
                "The pipeline will stop before any prompts or Phase 1 work.",
                "Use the runtime mismatch workflow in README, and on Windows rerun via .\\run-conda.ps1 or run-conda.bat.",
            ]
        )

    console.print(
        Panel.fit(
            "\n".join(lines),
            title="Startup Diagnostics",
            border_style=status_color,
        )
    )
    console.print()

    return runtime_identity, preflight


def save_startup_failure_log(analysis_logger: Optional[AnalysisLogger]) -> Optional[Path]:
    """Persist a metadata-only analysis log when startup fails before Phase 1."""
    if analysis_logger is None or not hasattr(analysis_logger, "save_log"):
        return None

    try:
        return Path(analysis_logger.save_log())
    except Exception as exc:
        logger.warning(f"Could not save startup diagnostics log: {exc}")
        return None


def validate_epc_token(token: str) -> Union[bool, str]:
    """
    Validate EPC API bearer token format.

    Returns:
        True if valid, error message string if invalid
    """
    if not token or not token.strip():
        return "Bearer token cannot be empty"

    cleaned = token.strip()
    if len(cleaned) < 16:
        return "Bearer token looks too short"

    if not re.match(r"^[A-Za-z0-9._~+/=-]+$", cleaned):
        return "Bearer token contains invalid characters"

    return True


def write_epc_token_env(token: str, env_path: Union[str, Path] = ".env") -> None:
    """Persist the EPC bearer token using the configured EPC_API_TOKEN name."""
    Path(env_path).write_text(
        "# EPC API Credentials\n"
        f"EPC_API_TOKEN={token.strip()}\n",
        encoding="utf-8",
    )


def parse_iso_date(value: str) -> date_cls:
    """Parse an ISO YYYY-MM-DD date string."""
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def _argparse_iso_date(value: str) -> date_cls:
    """Parse a CLI ISO date with an argparse-friendly error."""
    try:
        return parse_iso_date(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def parse_args(argv=None) -> argparse.Namespace:
    """Parse HeatStreet Studio runner arguments."""
    parser = argparse.ArgumentParser(
        description="Run the HeatStreet Studio analysis pipeline.",
    )
    tui_group = parser.add_mutually_exclusive_group()
    tui_group.add_argument(
        "--tui",
        dest="tui_mode",
        nargs="?",
        const="textual",
        choices=["textual", "rich"],
        metavar="MODE",
        help="TUI mode: textual (default) or rich. --tui alone selects textual.",
    )
    tui_group.add_argument(
        "--no-tui",
        dest="no_tui",
        action="store_true",
        help="Disable all terminal UI output.",
    )
    parser.set_defaults(tui_mode=None, no_tui=False)

    parser.add_argument("--simple-tui", action="store_true", help="Use a stable line-oriented terminal dashboard.")
    parser.add_argument(
        "--tui-refresh-rate",
        type=int,
        metavar="N",
        help="Rich dashboard refresh rate in frames per second; supported values are clamped to 2-4.",
    )

    parser.add_argument("--quiet", action="store_true", help="Suppress live dashboard and routine fallback chatter.")
    parser.add_argument("--verbose", action="store_true", help="Show expanded diagnostic detail in fallback output.")

    open_group = parser.add_mutually_exclusive_group()
    open_group.add_argument("--open-results", dest="open_results", action="store_true", help="Open the outputs folder after a successful run.")
    open_group.add_argument("--no-open", dest="open_results", action="store_false", help="Do not open the outputs folder after the run.")
    parser.set_defaults(open_results=False)

    parser.add_argument("--sample-start", type=_argparse_iso_date, help="Inclusive EPC sample start date (YYYY-MM-DD).")
    parser.add_argument("--sample-end", type=_argparse_iso_date, help="Inclusive EPC sample end date (YYYY-MM-DD).")

    data_group = parser.add_mutually_exclusive_group()
    data_group.add_argument("--use-existing", action="store_true", help="Use matching existing raw data without prompting.")
    data_group.add_argument("--fresh", action="store_true", help="Force a fresh EPC download even when matching raw data exists.")

    report_group = parser.add_mutually_exclusive_group()
    report_group.add_argument("--one-stop-only", action="store_true", help="Generate only one-stop reporting outputs for this run.")
    report_group.add_argument("--full-reports", action="store_true", help="Generate the full report set for this run.")

    parser.add_argument(
        "--download-scope",
        choices=["full-london", "single-borough"],
        help="EPC acquisition scope. single-borough prompts for --borough when omitted.",
    )
    parser.add_argument("--borough", help="London borough name for --download-scope single-borough.")
    parser.add_argument("--production", action="store_true", help="Require complete production provenance and enable publication.")
    parser.add_argument("--development-fixture", type=Path, help="Validated Parquet fixture; skips acquisition and validation.")
    parser.add_argument("--source-run-id", help="Source run identifier for a development fixture.")
    parser.add_argument("--source-fixture-sha256", help="Expected SHA-256 for a development fixture.")
    parser.add_argument("--refresh-hnpd", action="store_true", help="Refresh HNPD inputs for a production run.")
    parser.add_argument("--no-publish", action="store_true", help="Keep outputs run-scoped and do not update the latest publication.")

    args = parser.parse_args(argv)
    if args.sample_start and args.sample_end and args.sample_start > args.sample_end:
        parser.error("--sample-start cannot be after --sample-end")
    if args.borough and args.download_scope is None:
        args.download_scope = "single-borough"
    if args.production and args.development_fixture:
        parser.error("--production and --development-fixture are mutually exclusive")
    if args.development_fixture and not (args.source_run_id and args.source_fixture_sha256):
        parser.error("--development-fixture requires --source-run-id and --source-fixture-sha256")

    # Backwards-compatibility shim: expose args.tui as a bool for legacy code
    # that predates tui_mode/no_tui. create_dashboard() reads tui_mode/no_tui.
    if args.no_tui:
        args.tui = False
    elif args.tui_mode is not None:
        args.tui = True
    else:
        args.tui = None

    return args


def validate_end_date(value: str) -> Union[bool, str]:
    """Validate sample end date input."""
    if not value or not value.strip():
        return "End date cannot be empty"

    try:
        parse_iso_date(value)
    except ValueError:
        return "Please enter a valid date in YYYY-MM-DD format"

    return True


def validate_start_date(value: str, sample_end_date: date_cls) -> Union[bool, str]:
    """Validate sample start date input against the selected end date."""
    if not value or not value.strip():
        return "Start date cannot be empty"

    try:
        sample_start_date = parse_iso_date(value)
    except ValueError:
        return "Please enter a valid date in YYYY-MM-DD format"

    if sample_start_date > sample_end_date:
        return f"Start date cannot be after end date ({sample_end_date.isoformat()})"

    return True


def compute_sample_start_date(sample_end_date: date_cls) -> date_cls:
    """
    Compute the exact inclusive 10-year sample start date.

    Uses the same calendar day 10 years earlier, with a leap-year fallback to
    28 February when needed.
    """
    try:
        return sample_end_date.replace(year=sample_end_date.year - 10)
    except ValueError:
        return sample_end_date.replace(year=sample_end_date.year - 10, day=28)


def prompt_sample_end_date(ui=None) -> date_cls:
    """Prompt for the sample end date, defaulting to yesterday for API safety."""
    default_value = (date_cls.today() - timedelta(days=1)).isoformat()

    # Try TUI modal first
    tui_result = _tui_prompt(
        ui, "text",
        title="Sample window",
        message="Sample end date (YYYY-MM-DD):",
        default=default_value,
        validate_fn=validate_end_date,
    )
    if tui_result is not None:
        return parse_iso_date(tui_result)

    # Questionary fallback
    with _ui_suspend(ui, "Waiting for sample end date"):
        sample_end_text = questionary.text(
            "Sample end date (YYYY-MM-DD):",
            default=default_value,
            validate=validate_end_date,
        ).ask()

    if sample_end_text is None:
        raise KeyboardInterrupt("Sample end date input cancelled")

    return parse_iso_date(sample_end_text)


def prompt_sample_window(ui=None) -> Tuple[date_cls, date_cls]:
    """Prompt for a fully configurable sample window."""
    sample_end_date = prompt_sample_end_date(ui=ui)
    default_start_date = compute_sample_start_date(sample_end_date).isoformat()

    # Try TUI modal first
    tui_result = _tui_prompt(
        ui, "text",
        title="Sample window",
        message="Sample start date (YYYY-MM-DD):",
        default=default_start_date,
        validate_fn=lambda value: validate_start_date(value, sample_end_date),
    )
    if tui_result is not None:
        sample_start_date = parse_iso_date(tui_result)
        return sample_start_date, sample_end_date

    # Questionary fallback
    with _ui_suspend(ui, "Waiting for sample start date"):
        sample_start_text = questionary.text(
            "Sample start date (YYYY-MM-DD):",
            default=default_start_date,
            validate=lambda value: validate_start_date(value, sample_end_date),
        ).ask()

    if sample_start_text is None:
        raise KeyboardInterrupt("Sample start date input cancelled")

    sample_start_date = parse_iso_date(sample_start_text)
    return sample_start_date, sample_end_date


def metadata_sidecar_path(file_path: Path) -> Path:
    """Return the sidecar metadata path for a dataset."""
    return file_path.with_name(f"{file_path.stem}_metadata.json")


def write_sample_window_metadata(
    file_path: Path,
    sample_start_date: date_cls,
    sample_end_date: date_cls,
    dataset_type: str,
) -> None:
    """Persist sample-window metadata for a dataset."""
    if not file_path.exists():
        logger.debug(f"Skipping sample-window metadata for missing dataset: {file_path}")
        return
    metadata = {
        "dataset_path": str(file_path),
        "dataset_type": dataset_type,
        "sample_start_date": sample_start_date.isoformat(),
        "sample_end_date": sample_end_date.isoformat(),
        "written_at": datetime.now().isoformat(),
    }
    metadata_sidecar_path(file_path).write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )


def read_sample_window_metadata(file_path: Path):
    """Load dataset sidecar metadata if present."""
    metadata_path = metadata_sidecar_path(file_path)
    if not metadata_path.exists():
        return None

    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Could not read sample window metadata from {metadata_path}: {e}")
        return None


def sample_window_matches(file_path: Path, sample_start_date: date_cls, sample_end_date: date_cls) -> bool:
    """Return True when dataset metadata matches the requested sample window."""
    metadata = read_sample_window_metadata(file_path)
    if not metadata:
        return False

    return (
        metadata.get("sample_start_date") == sample_start_date.isoformat()
        and metadata.get("sample_end_date") == sample_end_date.isoformat()
    )


def is_dataset_reference(value) -> bool:
    """Return True when the value is a staged dataset reference."""
    return isinstance(value, DatasetReference)


def dataset_record_count(value) -> int:
    """Return a row count for a dataframe or staged dataset."""
    if is_dataset_reference(value):
        if value.row_count is not None:
            return int(value.row_count)
        return parquet_row_count(value.parquet_path)
    return len(value) if value is not None else 0


def dataset_is_empty(value) -> bool:
    """Return True when a dataframe or staged dataset has no rows."""
    return dataset_record_count(value) == 0


def ensure_dataframe(value, *, stage_name: str, ui=None):
    """Materialize a staged dataset into memory when a downstream phase needs a dataframe."""
    if not is_dataset_reference(value):
        return value

    _ui_phase_progress(ui, "Materialization", f"Materializing {stage_name}")
    console.print(f"[cyan]Materializing {stage_name} from staged Parquet at {value.parquet_path}...[/cyan]")
    try:
        df = value.load_dataframe()
    except MemoryError as exc:
        raise RuntimeError(
            f"{stage_name} could not be materialized due to memory limits. "
            f"Staged dataset: {value.parquet_path}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(
            f"{stage_name} could not be materialized from staged dataset {value.parquet_path}: {exc}"
        ) from exc

    console.print(f"[green]OK[/green] Loaded {len(df):,} records from staged dataset")
    _ui_metric(ui, f"{stage_name} records", len(df), group=PHASE_ACQUISITION)
    return df


def normalize_validation_report(report: Optional[Dict[str, Any]], *, input_dataset, validated_dataset) -> Dict[str, Any]:
    """Normalize validation counts for dataframes and staged datasets."""
    normalized_report = dict(report or {})
    total_records = int(normalized_report.get("total_records", dataset_record_count(input_dataset)) or 0)
    duplicates_removed = int(normalized_report.get("duplicates_removed", 0) or 0)
    records_passed = int(
        normalized_report.get(
            "records_passed",
            normalized_report.get("valid_records", dataset_record_count(validated_dataset)),
        ) or 0
    )
    invalid_records = max(total_records - duplicates_removed - records_passed, 0)

    normalized_report["total_records"] = total_records
    normalized_report["duplicates_removed"] = duplicates_removed
    normalized_report["records_passed"] = records_passed
    normalized_report["valid_records"] = records_passed
    normalized_report["invalid_records"] = invalid_records
    return normalized_report


def write_json_report(file_path: Path, payload: Dict[str, Any]) -> None:
    """Write a JSON report with numpy-safe serialization."""
    from src.utils.analysis_logger import convert_to_json_serializable

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(convert_to_json_serializable(payload), f, indent=2)


def add_analysis_output_if_exists(
    analysis_logger: Optional[AnalysisLogger],
    file_path: Optional[Union[str, Path]],
    output_type: str,
    description: str,
) -> bool:
    """Register an analysis output only when the path currently exists."""
    if analysis_logger is None or not file_path:
        return False

    path = Path(file_path)
    if not path.exists():
        logger.debug(f"Skipping analysis output registration for missing {output_type}: {path}")
        return False

    analysis_logger.add_output(str(path), output_type, description)
    return True


def is_one_stop_only(config=None) -> bool:
    """Return True when reporting is restricted to the one-stop markdown output."""
    config = config or load_config()
    return bool(config.get("reporting", {}).get("one_stop_only", False))


def print_header():
    """Print welcome header."""
    console.clear()
    rprint(Panel.fit(
        "[bold cyan]Heat Street EPC Analysis[/bold cyan]\n"
        "[white]Complete Interactive Pipeline[/white]\n"
        "[dim]London Edwardian Terraced Housing Analysis[/dim]",
        border_style="cyan"
    ))
    print()


def check_credentials(ui=None):
    """Check if the API token is configured."""
    token = os.getenv('EPC_API_TOKEN')

    if not token:
        _ui_warning(ui, "EPC API token missing")
        console.print("[yellow]⚠[/yellow]  API token not found in .env file", style="yellow")
        console.print()

        if not Path('.env').exists():
            console.print("Creating .env file from template...")
            if Path('.env.example').exists():
                import shutil
                shutil.copy('.env.example', '.env')
                console.print("[green]✓[/green] Created .env file")
            else:
                # Create .env file
                with open('.env', 'w') as f:
                    f.write("# EPC API Credentials\n")
                    f.write("EPC_API_TOKEN=\n")
                console.print("[green]✓[/green] Created .env file")

        console.print()
        console.print("[cyan]Please enter your EPC API bearer token:[/cyan]")
        console.print("[dim]Get the token from your my account page on the Energy Certificate Data API service.[/dim]")
        console.print()

        with _ui_suspend(ui, "Waiting for EPC API token"):
            token = questionary.password(
                "Bearer token:",
                validate=validate_epc_token
            ).ask()

        if token is None:
            console.print("[yellow]Credential input cancelled[/yellow]")
            return False

        try:
            write_epc_token_env(token, '.env')
        except FileNotFoundError:
            console.print("[red]×[/red] Could not save .env because the file path was not found", style="red")
            return False
        except PermissionError:
            console.print("[red]×[/red] Permission denied while saving .env", style="red")
            return False

        # Reload environment
        from dotenv import load_dotenv
        load_dotenv(override=True)

        console.print("[green]✓[/green] API token saved to .env file")
        console.print()

    _ui_metric(ui, "EPC API token", "configured", group=PHASE_ACQUISITION)
    return True


def ask_hnpd_download(ui=None):
    """Ask if user wants to download BEIS Heat Network Planning Database."""
    console.print()
    console.print("[cyan]BEIS Heat Network Planning Database (Recommended)[/cyan]")
    console.print()
    console.print("The HNPD provides current heat network data (January 2024) for:")
    console.print("  • Operational heat networks across the UK")
    console.print("  • Networks under construction")
    console.print("  • Planned networks with planning permission")
    console.print("  • Current external evidence for Tier 1-2 heat network proximity")
    console.print()

    # Check if already downloaded
    hnpd_downloader = HNPDDownloader()
    summary = hnpd_downloader.get_data_summary()

    if summary['available']:
        console.print("[green]✓[/green] HNPD data already downloaded")
        _ui_metric(ui, "HNPD", "available", group=PHASE_ACQUISITION)
        console.print(f"    Total records: {summary['total_records']}")
        console.print(f"    Tier 1 networks: {summary['tier_1_networks']} (operational/under construction)")
        console.print(f"    Tier 2 networks: {summary['tier_2_networks']} (planning granted)")
        console.print(f"    Regions covered: {summary['region_count']}")
        return True

    download = True  # Automatically download HNPD data

    if download:
        console.print()
        console.print("[cyan]Downloading BEIS Heat Network Planning Database...[/cyan]")

        if hnpd_downloader.download_and_prepare():
            _ui_metric(ui, "HNPD", "downloaded", group=PHASE_ACQUISITION)
            console.print("[green]✓[/green] HNPD data downloaded and ready")
            summary = hnpd_downloader.get_data_summary()
            console.print(f"    {summary['total_records']} heat network records loaded")
            console.print(f"    {summary['tier_1_networks']} Tier 1 + {summary['tier_2_networks']} Tier 2 networks")
            return True
        else:
            _ui_warning(
                ui,
                "HNPD download failed; network-proximity tiers may be unavailable, but density-based tiers can still run",
            )
            console.print(
                "[yellow]⚠[/yellow] HNPD download failed "
                "(Tier 1-2 network proximity evidence may be unavailable; "
                "Tier 3-5 density-based classification can still run)"
            )
            return False

    console.print(
        "[yellow]⚠[/yellow] Skipping HNPD download "
        "(Tier 1-2 network proximity evidence may be unavailable; "
        "Tier 3-5 density-based classification can still run)"
    )
    return False


def download_data(
    analysis_logger: AnalysisLogger = None,
    sample_start_date: date_cls = None,
    sample_end_date: date_cls = None,
    ui=None,
    download_scope: Optional[str] = None,
    borough: Optional[str] = None,
):
    """Download EPC data via API."""
    console.print()
    console.print(Panel("[bold]Phase 1: Data Download[/bold]", border_style="blue"))
    console.print()
    _ui_phase_started(ui, "Data Download", "Preparing EPC acquisition")

    from_year = sample_start_date.year if sample_start_date else 2015

    scope_map = {
        "full-london": "All London boroughs (full dataset)",
        "single-borough": "Single borough (testing)",
    }
    download_scope = scope_map.get(download_scope, download_scope)
    if download_scope is None:
        _scope_choices = ["All London boroughs (full dataset)", "Single borough (testing)"]
        tui_scope = _tui_prompt(
            ui, "select",
            title="Download scope",
            message="Select EPC download scope:",
            choices=_scope_choices,
        )
        if tui_scope is not None:
            download_scope = tui_scope
        else:
            with _ui_suspend(ui, "Waiting for EPC download scope"):
                download_scope = questionary.select(
                    "Select download scope:",
                    choices=_scope_choices,
                ).ask()

    if not download_scope:
        raise AnalysisCancelled("Download cancelled by user")

    selected_borough = borough
    if download_scope == "Single borough (testing)":
        if not selected_borough:
            _borough_list = sorted(EPCAPIDownloader.LONDON_LA_CODES.keys())
            tui_borough = _tui_prompt(
                ui, "select",
                title="Borough selection",
                message="Select London borough:",
                choices=_borough_list,
            )
            if tui_borough is not None:
                selected_borough = tui_borough
            else:
                with _ui_suspend(ui, "Waiting for borough selection"):
                    selected_borough = questionary.autocomplete(
                        "Select borough:",
                        choices=list(EPCAPIDownloader.LONDON_LA_CODES.keys()),
                    ).ask()

        if not selected_borough:
            raise AnalysisCancelled("Download cancelled by user")
        _ui_metric(ui, "Download scope", selected_borough, group=PHASE_ACQUISITION)
    else:
        _ui_metric(ui, "Download scope", "full London", group=PHASE_ACQUISITION)

    download_mode = "full_load"
    downloader = EPCAPIDownloader(download_mode=download_mode)

    if analysis_logger:
        analysis_logger.start_phase(
            "Data Download",
            "Download EPC data and define the London pre-1930 terraced house stock"
        )

    try:
        if selected_borough:
            console.print(
                f"[cyan]Using EPC full-load CSV extract as the stock-definition source for {selected_borough}...[/cyan]"
            )
            console.print(
                "[cyan]This still stages the national extract, then subsets it to the selected borough.[/cyan]"
            )
            console.print(f"[cyan]Downloading {selected_borough} only...[/cyan]")
            df = downloader.download_borough_data(
                selected_borough,
                property_type='house',
                from_year=from_year,
                sample_start_date=sample_start_date,
                sample_end_date=sample_end_date,
                max_results=None,
                log_borough=True,
                show_progress=not _ui_suppresses_progress(ui),
                progress_callback=_make_epc_progress_callback(ui),
            )
        elif hasattr(downloader, "download_national_domestic_dataset"):
            console.print("[cyan]Using staged Parquet processing for the national EPC full-load extract...[/cyan]")
            console.print("[cyan]Streaming certificate members to disk and excluding recommendation files before filtering...[/cyan]")

            national_stage = downloader.download_national_domestic_dataset(
                sample_start_date=sample_start_date,
                sample_end_date=sample_end_date,
                progress_callback=_make_epc_progress_callback(ui),
            )
            ingest_manifest = national_stage.metadata
            selected_members = ingest_manifest.get("selected_certificate_members", [])
            ignored_recommendations = ingest_manifest.get("ignored_recommendation_members", [])
            malformed_rows = int(ingest_manifest.get("malformed_rows_skipped", 0) or 0)

            if selected_members:
                console.print("[cyan]Selected certificate members:[/cyan]")
                for member in selected_members:
                    console.print(f"    {member}")

            if ignored_recommendations:
                console.print("[cyan]Ignored recommendation members:[/cyan]")
                for member in ignored_recommendations:
                    console.print(f"    {member}")

            console.print(f"[cyan]Approximate malformed rows skipped during ingest:[/cyan] {malformed_rows:,}")
            console.print(f"[cyan]Raw staged dataset:[/cyan] {national_stage.parquet_path}")
            if national_stage.manifest_path:
                console.print(f"[cyan]Ingest manifest:[/cyan] {national_stage.manifest_path}")

            raw_ref = downloader.materialize_full_load_subset(
                national_stage,
                DATA_RAW_DIR / "epc_london_raw.parquet",
                dataset_name="raw_london_house_dataset",
                borough_names=EPCAPIDownloader.LONDON_LA_CODES.keys(),
                property_types=["house"],
            )
            filtered_ref = downloader.materialize_full_load_subset(
                raw_ref,
                DATA_RAW_DIR / "epc_london_filtered.parquet",
                dataset_name="filtered_london_pre_1930_terraced_dataset",
                apply_stock_definition=True,
            )

            raw_record_count = dataset_record_count(raw_ref)
            filtered_record_count = dataset_record_count(filtered_ref)
            if filtered_record_count == 0:
                console.print(
                    f"[red]x[/red] No London stock records retained after staged filtering. "
                    f"Staged dataset: {filtered_ref.parquet_path}",
                    style="red",
                )
                if analysis_logger:
                    analysis_logger.complete_phase(success=False, message=f"No data retained in {filtered_ref.parquet_path}")
                return None

            console.print(f"[green]OK[/green] Raw London house records: {raw_record_count:,}")
            console.print(f"[green]OK[/green] Filtered London pre-1930 terraced house records: {filtered_record_count:,}")
            console.print(f"[cyan]Filtered staged dataset:[/cyan] {filtered_ref.parquet_path}")
            _ui_metric(ui, "raw London records", raw_record_count, group=PHASE_ACQUISITION)
            _ui_metric(ui, "filtered stock records", filtered_record_count, group=PHASE_ACQUISITION)
            _ui_output(ui, "Filtered EPC staged dataset", filtered_ref.parquet_path)

            if sample_start_date and sample_end_date:
                for output_path, dataset_type in (
                    (DATA_RAW_DIR / "epc_london_raw.csv", "raw_epc_download"),
                    (DATA_RAW_DIR / "epc_london_raw.parquet", "raw_epc_download_parquet"),
                    (DATA_RAW_DIR / "epc_london_filtered.csv", "filtered_epc_download"),
                    (DATA_RAW_DIR / "epc_london_filtered.parquet", "filtered_epc_download_parquet"),
                ):
                    write_sample_window_metadata(
                        output_path,
                        sample_start_date,
                        sample_end_date,
                        dataset_type,
                    )

            if analysis_logger:
                analysis_logger.add_metric("raw_records_downloaded", raw_record_count, "House records from staged EPC source before pre-1930 terraced filtering")
                analysis_logger.add_metric("raw_house_records", raw_record_count, "House records before pre-1930 terraced filtering")
                analysis_logger.add_metric("filtered_records", filtered_record_count, "London pre-1930 terraced houses after filtering")
                analysis_logger.add_metric("filtered_pre_1930_terraced_house_records", filtered_record_count, "London pre-1930 terraced house records after filtering")
                analysis_logger.add_metric("filter_rate", filtered_record_count / raw_record_count * 100, "Percentage retained after filtering")
                analysis_logger.add_metric("from_year", from_year)
                analysis_logger.add_metric("ignored_recommendation_members", len(ignored_recommendations), "Recommendation CSV members excluded from staged ingest")
                analysis_logger.add_metric("malformed_rows_skipped", malformed_rows, "Malformed certificate rows skipped during staged ingest")
                if sample_start_date:
                    analysis_logger.add_metric("sample_start_date", sample_start_date.isoformat(), "Exact inclusive sample start date")
                if sample_end_date:
                    analysis_logger.add_metric("sample_end_date", sample_end_date.isoformat(), "Exact inclusive sample end date")
                add_analysis_output_if_exists(analysis_logger, national_stage.parquet_path, "parquet", "Raw staged national domestic certificate dataset")
                if national_stage.manifest_path:
                    add_analysis_output_if_exists(analysis_logger, national_stage.manifest_path, "json", "National domestic ingest manifest")
                add_analysis_output_if_exists(analysis_logger, raw_ref.parquet_path, "parquet", "Raw London house records from staged EPC source")
                add_analysis_output_if_exists(analysis_logger, raw_ref.csv_path, "csv", "Raw London house records from staged EPC source")
                add_analysis_output_if_exists(analysis_logger, filtered_ref.parquet_path, "parquet", "Filtered London pre-1930 terraced houses")
                add_analysis_output_if_exists(analysis_logger, filtered_ref.csv_path, "csv", "Filtered London pre-1930 terraced houses")
                analysis_logger.complete_phase(
                    success=True,
                    message=(
                        f"Prepared {raw_record_count:,} staged London house records and retained "
                        f"{filtered_record_count:,} London pre-1930 terraced houses"
                    ),
                )

            _ui_phase_completed(
                ui,
                "Data Download",
                f"Prepared {filtered_record_count:,} London pre-1930 terraced house records",
            )
            return filtered_ref
        else:
            console.print(
                "[yellow]WARNING[/yellow] Falling back to the legacy in-memory full-load path. "
                "This is a non-production compatibility path and should not be used for national runs.",
                style="yellow",
            )
            logger.warning(
                "Falling back to the legacy in-memory full-load EPC path. "
                "Startup preflight should normally prevent this path from running."
            )
            console.print("[cyan]Using EPC full-load CSV extract for London stock definition...[/cyan]")
            console.print("[cyan]Downloading ALL London boroughs (this will take a while)...[/cyan]")
            df = downloader.download_all_london_boroughs(
                property_types=['house'],
                from_year=from_year,
                sample_start_date=sample_start_date,
                sample_end_date=sample_end_date,
                max_results_per_borough=None,
                log_boroughs=False,
            )

        if df.empty:
            console.print("[red]✗[/red] No data downloaded", style="red")
            if analysis_logger:
                analysis_logger.complete_phase(success=False, message="No data downloaded from API")
            return None

        if selected_borough:
            console.print(f"[green]✓[/green] Raw {selected_borough} house records: {len(df):,}")
        else:
            console.print(f"[green]✓[/green] Raw London house records: {len(df):,}")

        if analysis_logger:
            analysis_logger.add_metric("raw_records_downloaded", len(df), "House records from EPC source before pre-1930 terraced filtering")
            analysis_logger.add_metric("raw_house_records", len(df), "House records before pre-1930 terraced filtering")
            analysis_logger.add_metric("from_year", from_year)
            if sample_start_date:
                analysis_logger.add_metric("sample_start_date", sample_start_date.isoformat(), "Exact inclusive sample start date")
            if sample_end_date:
                analysis_logger.add_metric("sample_end_date", sample_end_date.isoformat(), "Exact inclusive sample end date")

        # Apply stock filters
        filter_scope = "London" if not selected_borough else selected_borough
        console.print(f"[cyan]Applying pre-1930 terraced house filters for {filter_scope}...[/cyan]")
        df_filtered = downloader.apply_edwardian_filters(df)
        if selected_borough:
            console.print(f"[green]✓[/green] Filtered {selected_borough} pre-1930 terraced house records: {len(df_filtered):,}")
        else:
            console.print(f"[green]✓[/green] Filtered London pre-1930 terraced house records: {len(df_filtered):,}")

        if analysis_logger:
            analysis_logger.add_metric("filtered_records", len(df_filtered), "London pre-1930 terraced houses after filtering")
            analysis_logger.add_metric("filtered_pre_1930_terraced_house_records", len(df_filtered), "London pre-1930 terraced house records after filtering")
            analysis_logger.add_metric("filter_rate", len(df_filtered) / len(df) * 100, "Percentage retained after filtering")

        raw_filename = "epc_london_raw.csv"
        filtered_filename = "epc_london_filtered.csv"
        if selected_borough:
            borough_slug = selected_borough.lower().replace(" ", "_")
            raw_filename = f"epc_{borough_slug}_raw.csv"
            filtered_filename = f"epc_{borough_slug}_filtered.csv"

        # Save data
        console.print("[cyan]Saving data...[/cyan]")
        downloader.save_data(df, raw_filename)
        downloader.save_data(df_filtered, filtered_filename, raw_df=df)
        if sample_start_date and sample_end_date:
            write_sample_window_metadata(
                DATA_RAW_DIR / raw_filename,
                sample_start_date,
                sample_end_date,
                "raw_epc_download",
            )
            write_sample_window_metadata(
                DATA_RAW_DIR / filtered_filename,
                sample_start_date,
                sample_end_date,
                "filtered_epc_download",
            )
        console.print(f"[green]✓[/green] Data saved to data/raw/")

        if analysis_logger:
            analysis_logger.add_output(f"data/raw/{raw_filename}", "csv", "Raw house records from EPC data")
            analysis_logger.add_output(f"data/raw/{filtered_filename}", "csv", "Filtered pre-1930 terraced houses")
            analysis_logger.complete_phase(
                success=True,
                message=(
                    f"Prepared {len(df):,} house records and retained "
                    f"{len(df_filtered):,} "
                    f"{'London' if not selected_borough else selected_borough} pre-1930 terraced houses"
                ),
            )

        _ui_metric(ui, "raw London records", len(df), group=PHASE_ACQUISITION)
        _ui_metric(ui, "filtered stock records", len(df_filtered), group=PHASE_ACQUISITION)
        _ui_phase_completed(
            ui,
            "Data Download",
            f"Prepared {len(df_filtered):,} pre-1930 terraced house records",
        )
        return df_filtered

    except AnalysisCancelled:
        raise
    except EPCStockDefinitionError as e:
        _ui_phase_failed(ui, "Data Download", f"Stock definition failed: {e}")
        console.print(f"[red]✗[/red] Stock definition failed: {e}", style="red")
        if analysis_logger:
            analysis_logger.complete_phase(success=False, message=f"StockDefinitionError: {e}")
        return None
    except EPCDownloadError as e:
        _ui_phase_failed(ui, "Data Download", f"EPC download failed: {e}")
        console.print(f"[red]✗[/red] EPC download failed: {e}", style="red")
        if analysis_logger:
            analysis_logger.complete_phase(success=False, message=str(e))
        return None
    except ValueError as e:
        _ui_phase_failed(ui, "Data Download", f"Value error: {e}")
        console.print(f"[red]✗[/red] Error: {e}", style="red")
        if analysis_logger:
            analysis_logger.complete_phase(success=False, message=f"ValueError: {e}")
        return None
    except Exception as e:
        _ui_phase_failed(ui, "Data Download", f"Unexpected error: {e}")
        console.print(f"[red]✗[/red] Unexpected error: {e}", style="red")
        if analysis_logger:
            analysis_logger.complete_phase(success=False, message=f"Error: {e}")
        return None


def validate_data(
    df,
    analysis_logger: AnalysisLogger = None,
    sample_start_date: date_cls = None,
    sample_end_date: date_cls = None,
    ui=None,
    strict_schema_conflicts: bool = False,
):
    """Validate and clean data."""
    console.print()
    console.print(Panel("[bold]Phase 2: Data Validation[/bold]", border_style="blue"))
    console.print()
    _ui_phase_started(ui, "Data Validation", "Running quality assurance checks")

    if analysis_logger:
        analysis_logger.start_phase(
            "Data Validation",
            "Run quality assurance checks and remove invalid/duplicate records"
        )

    console.print("[cyan]Running quality assurance checks...[/cyan]")

    if is_dataset_reference(df):
        console.print("[cyan]Validating from staged Parquet dataset instead of a monolithic in-memory dataframe...[/cyan]")
        output_file = DATA_PROCESSED_DIR / "epc_london_validated.csv"
        validated_dataset, report = _call_with_optional_ui(
            validate_staged_dataset,
            df,
            output_file,
            strict_schema_conflicts=strict_schema_conflicts,
        )
        report = normalize_validation_report(
            report,
            input_dataset=df,
            validated_dataset=validated_dataset,
        )
        records_passed = report["records_passed"]
        invalid_records = report["invalid_records"]

        if sample_start_date and sample_end_date:
            for output_path, dataset_type in (
                (output_file, "validated_epc_dataset"),
                (output_file.with_suffix(".parquet"), "validated_epc_dataset_parquet"),
            ):
                write_sample_window_metadata(
                    output_path,
                    sample_start_date,
                    sample_end_date,
                    dataset_type,
                )

        validator = EPCDataValidator()
        validator.validation_report.update(report)
        _call_with_optional_ui(
            validator.save_validation_report,
            output_path=DATA_PROCESSED_DIR / "validation_report.txt",
        )

        try:
            validation_report_json = DATA_PROCESSED_DIR / "validation_report.json"
            write_json_report(validation_report_json, report)
        except Exception as e:
            logger.debug(f"Could not save validation report JSON: {e}")

        console.print("[green]OK[/green] Validation complete")
        if report.get("total_records", 0):
            console.print(
                f"    Records passed: {records_passed:,} "
                f"({records_passed/report['total_records']*100:.1f}%)"
            )
        console.print(f"    Duplicates removed: {report.get('duplicates_removed', 0):,}")
        console.print(f"    Invalid records: {invalid_records:,}")
        console.print("[green]OK[/green] Validated data saved")
        _ui_metric(ui, "input records", report.get('total_records', 0), group=PHASE_VALIDATION)
        _ui_metric(ui, "passed records", records_passed, group=PHASE_VALIDATION)
        _ui_metric(ui, "duplicates removed", report.get('duplicates_removed', 0), group=PHASE_VALIDATION)
        _ui_metric(ui, "invalid records", invalid_records, group=PHASE_VALIDATION)
        if report.get('total_records', 0):
            _ui_metric(ui, "validation rate", records_passed/report['total_records']*100, group=PHASE_VALIDATION)
        _ui_metric(ui, "negative energy values", report.get('negative_energy_values', 0), group=PHASE_VALIDATION)
        _ui_metric(ui, "negative CO2 values", report.get('negative_co2_values', 0), group=PHASE_VALIDATION)

        if analysis_logger:
            analysis_logger.add_metric("input_records", report.get('total_records', 0), "Records before validation")
            analysis_logger.add_metric("validated_records", records_passed, "Records after validation")
            analysis_logger.add_metric("duplicates_removed", report.get('duplicates_removed', 0), "Duplicate records removed")
            analysis_logger.add_metric("invalid_records", invalid_records, "Invalid records removed")
            if report.get('total_records', 0):
                analysis_logger.add_metric(
                    "validation_rate",
                    records_passed/report['total_records']*100,
                    "Percentage of records passing validation",
                )
            analysis_logger.add_metric("negative_energy_values", report.get('negative_energy_values', 0), "Records with negative ENERGY_CONSUMPTION_CURRENT")
            analysis_logger.add_metric("negative_co2_values", report.get('negative_co2_values', 0), "Records with negative CO2_EMISSIONS_CURRENT")
            add_analysis_output_if_exists(analysis_logger, validated_dataset.csv_path, "csv", "Validated EPC dataset")
            add_analysis_output_if_exists(analysis_logger, validated_dataset.parquet_path, "parquet", "Validated EPC dataset (Parquet)")
            add_analysis_output_if_exists(analysis_logger, DATA_PROCESSED_DIR / "validation_report.txt", "report", "Data validation report")
            add_analysis_output_if_exists(analysis_logger, validation_report_json, "report", "Data validation report (JSON)")
            analysis_logger.complete_phase(success=True, message=f"{records_passed:,} records validated")

        _ui_output(ui, "Validated EPC dataset", validated_dataset.parquet_path)
        _ui_output(ui, "Validation report", validation_report_json)
        _ui_phase_completed(ui, "Data Validation", f"{records_passed:,} records validated")
        return validated_dataset, report

    validator = EPCDataValidator(strict_schema_conflicts=strict_schema_conflicts)
    df_validated, report = validator.validate_dataset(df)
    report = normalize_validation_report(
        report,
        input_dataset=df,
        validated_dataset=df_validated,
    )
    records_passed = report["records_passed"]
    invalid_records = report["invalid_records"]

    console.print(f"[green]✓[/green] Validation complete")
    console.print(f"    Records passed: {records_passed:,} ({records_passed/report['total_records']*100:.1f}%)")
    console.print(f"    Duplicates removed: {report['duplicates_removed']:,}")
    console.print(f"    Invalid records: {invalid_records:,}")

    if analysis_logger:
        analysis_logger.add_metric("input_records", report['total_records'], "Records before validation")
        analysis_logger.add_metric("validated_records", records_passed, "Records after validation")
        analysis_logger.add_metric("duplicates_removed", report['duplicates_removed'], "Duplicate records removed")
        analysis_logger.add_metric("invalid_records", invalid_records, "Invalid records removed")
        analysis_logger.add_metric("validation_rate", records_passed/report['total_records']*100, "Percentage of records passing validation")
        analysis_logger.add_metric("negative_energy_values", report.get('negative_energy_values', 0), "Records with negative ENERGY_CONSUMPTION_CURRENT")
        analysis_logger.add_metric("negative_co2_values", report.get('negative_co2_values', 0), "Records with negative CO2_EMISSIONS_CURRENT")

    # Save validated data
    import pandas as pd
    output_file = DATA_PROCESSED_DIR / "epc_london_validated.csv"
    df_validated.to_csv(output_file, index=False)
    if sample_start_date and sample_end_date:
        write_sample_window_metadata(
            output_file,
            sample_start_date,
            sample_end_date,
            "validated_epc_dataset",
        )

    # Try to save parquet (optional for performance)
    try:
        parquet_file = output_file.with_suffix('.parquet')
        # Convert object/categorical columns to strings for parquet compatibility
        # Save original dtypes to restore after
        cat_cols = df_validated.select_dtypes(include=['category']).columns.tolist()
        obj_cols = df_validated.select_dtypes(include=['object']).columns.tolist()
        cols_to_convert = cat_cols + obj_cols

        if cols_to_convert:
            original_dtypes = {col: df_validated[col].dtype for col in cols_to_convert}
            for col in cols_to_convert:
                df_validated[col] = df_validated[col].astype(str)

        df_validated.to_parquet(parquet_file, index=False)

        # Restore original dtypes
        if cols_to_convert:
            for col, dtype in original_dtypes.items():
                if col in df_validated.columns:
                    df_validated[col] = df_validated[col].astype(dtype)
    except Exception as e:
        console.print(f"[yellow]Note: Could not save parquet format (CSV saved successfully)[/yellow]")
        logger.debug(f"Parquet save failed: {e}")

    validator.save_validation_report()
    try:
        validation_report_json = DATA_PROCESSED_DIR / "validation_report.json"
        write_json_report(validation_report_json, report)
    except Exception as e:
        logger.debug(f"Could not save validation report JSON: {e}")

    console.print(f"[green]✓[/green] Validated data saved")

    _ui_metric(ui, "input records", report['total_records'], group=PHASE_VALIDATION)
    _ui_metric(ui, "passed records", records_passed, group=PHASE_VALIDATION)
    _ui_metric(ui, "duplicates removed", report['duplicates_removed'], group=PHASE_VALIDATION)
    _ui_metric(ui, "invalid records", invalid_records, group=PHASE_VALIDATION)
    _ui_metric(ui, "validation rate", records_passed/report['total_records']*100, group=PHASE_VALIDATION)
    _ui_metric(ui, "negative energy values", report.get('negative_energy_values', 0), group=PHASE_VALIDATION)
    _ui_metric(ui, "negative CO2 values", report.get('negative_co2_values', 0), group=PHASE_VALIDATION)
    _ui_output(ui, "Validated EPC dataset", output_file)
    _ui_output(ui, "Validation report", DATA_PROCESSED_DIR / "validation_report.json")

    if analysis_logger:
        analysis_logger.add_output(str(output_file), "csv", "Validated EPC dataset")
        analysis_logger.add_output("data/processed/validation_report.txt", "report", "Data validation report")
        analysis_logger.add_output("data/processed/validation_report.json", "report", "Data validation report (JSON)")
        analysis_logger.complete_phase(success=True, message=f"{records_passed:,} records validated")

    _ui_phase_completed(ui, "Data Validation", f"{records_passed:,} records validated")
    return df_validated, report


def apply_methodological_adjustments(
    df,
    analysis_logger: AnalysisLogger = None,
    sample_start_date: date_cls = None,
    sample_end_date: date_cls = None,
    ui=None,
):
    """Apply evidence-based methodological adjustments."""
    console.print()
    console.print(Panel("[bold]Phase 2.5: Methodological Adjustments[/bold]", border_style="blue"))
    console.print()
    _ui_phase_started(ui, "Methodological Adjustments", "Applying evidence-based adjustments")

    if analysis_logger:
        analysis_logger.start_phase(
            "Methodological Adjustments",
            "Apply evidence-based adjustments (prebound effect, heat pump flow temp, uncertainty)"
        )

    from src.analysis.methodological_adjustments import MethodologicalAdjustments

    console.print("[cyan]Applying evidence-based adjustments...[/cyan]")

    if is_dataset_reference(df):
        console.print("[cyan]Applying adjustments from staged Parquet instead of rewriting a full dataframe in memory...[/cyan]")
        output_file = DATA_PROCESSED_DIR / "epc_london_adjusted.csv"
        adjusted_dataset, summary = apply_adjustments_staged_dataset(df, output_file)
        adjusted_record_count = dataset_record_count(adjusted_dataset)

        if sample_start_date and sample_end_date:
            for output_path, dataset_type in (
                (output_file, "adjusted_epc_dataset"),
                (output_file.with_suffix(".parquet"), "adjusted_epc_dataset_parquet"),
            ):
                write_sample_window_metadata(
                    output_path,
                    sample_start_date,
                    sample_end_date,
                    dataset_type,
                )

        try:
            summary_path = DATA_PROCESSED_DIR / "methodological_adjustments_summary.json"
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)
        except Exception as e:
            logger.debug(f"Could not save adjustment summary JSON: {e}")

        console.print("[green]OK[/green] Methodological adjustments applied")
        adjustments_applied = []
        if summary.get('prebound_adjustment', {}).get('applied'):
            console.print("    - Prebound effect adjustment (Few et al., 2023)")
            adjustments_applied.append("Prebound effect")
        if summary.get('flow_temperature', {}).get('applied'):
            console.print("    - Heat pump flow temperature model")
            adjustments_applied.append("Flow temperature")
        if summary.get('uncertainty', {}).get('applied'):
            console.print("    - Measurement uncertainty (Crawley et al., 2019)")
            adjustments_applied.append("Measurement uncertainty")

        _ui_metric(ui, "adjustments applied", len(adjustments_applied), group=PHASE_VALIDATION)
        _ui_metric(ui, "records adjusted", adjusted_record_count, group=PHASE_VALIDATION)
        if adjustments_applied:
            _ui_metric(ui, "adjustment names", ", ".join(adjustments_applied), group=PHASE_VALIDATION)
        _ui_output(ui, "Adjusted EPC dataset", adjusted_dataset.parquet_path)
        _ui_output(ui, "Adjustment summary", DATA_PROCESSED_DIR / "methodological_adjustments_summary.json")

        if analysis_logger:
            analysis_logger.add_metric("adjustments_applied", len(adjustments_applied), f"Applied: {', '.join(adjustments_applied)}")
            analysis_logger.add_metric("records_adjusted", adjusted_record_count, "Records with adjustments")
            analysis_logger.add_output(str(output_file), "csv", "Adjusted EPC dataset")
            analysis_logger.add_output("data/processed/methodological_adjustments_summary.json", "report", "Methodological adjustments summary (JSON)")
            analysis_logger.add_output(str(output_file.with_suffix(".parquet")), "parquet", "Adjusted EPC dataset (Parquet)")
            analysis_logger.complete_phase(success=True, message=f"{len(adjustments_applied)} methodological adjustments applied")

        _ui_phase_completed(ui, "Methodological Adjustments", f"{len(adjustments_applied)} adjustments applied")
        return adjusted_dataset, summary

    adjuster = MethodologicalAdjustments()

    # Apply all adjustments in sequence
    df_adjusted = adjuster.apply_all_adjustments(df)
    adjusted_record_count = dataset_record_count(df_adjusted)

    # Generate summary
    summary = adjuster.generate_adjustment_summary(df_adjusted)
    output_file = DATA_PROCESSED_DIR / "epc_london_adjusted.csv"
    df_adjusted.to_csv(output_file, index=False)
    if sample_start_date and sample_end_date:
        write_sample_window_metadata(
            output_file,
            sample_start_date,
            sample_end_date,
            "adjusted_epc_dataset",
        )
    parquet_file = None
    try:
        parquet_file = output_file.with_suffix(".parquet")
        # Convert object/categorical columns to strings for parquet compatibility
        cat_cols = df_adjusted.select_dtypes(include=['category']).columns.tolist()
        obj_cols = df_adjusted.select_dtypes(include=['object']).columns.tolist()
        cols_to_convert = cat_cols + obj_cols

        if cols_to_convert:
            original_dtypes = {col: df_adjusted[col].dtype for col in cols_to_convert}
            for col in cols_to_convert:
                df_adjusted[col] = df_adjusted[col].astype(str)

        df_adjusted.to_parquet(parquet_file, index=False)

        # Restore original dtypes
        if cols_to_convert:
            for col, dtype in original_dtypes.items():
                if col in df_adjusted.columns:
                    df_adjusted[col] = df_adjusted[col].astype(dtype)
    except Exception as e:
        parquet_file = None
        logger.debug(f"Could not save adjusted parquet: {e}")

    try:
        summary_path = DATA_PROCESSED_DIR / "methodological_adjustments_summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
    except Exception as e:
        logger.debug(f"Could not save adjustment summary JSON: {e}")

    console.print(f"[green]✓[/green] Methodological adjustments applied")
    adjustments_applied = []
    if summary.get('prebound_adjustment', {}).get('applied'):
        console.print(f"    • Prebound effect adjustment (Few et al., 2023)")
        adjustments_applied.append("Prebound effect")
    if summary.get('flow_temperature', {}).get('applied'):
        console.print(f"    • Heat pump flow temperature model")
        adjustments_applied.append("Flow temperature")
    if summary.get('uncertainty', {}).get('applied'):
        console.print(f"    • Measurement uncertainty (Crawley et al., 2019)")
        adjustments_applied.append("Measurement uncertainty")

    _ui_metric(ui, "adjustments applied", len(adjustments_applied), group=PHASE_VALIDATION)
    _ui_metric(ui, "records adjusted", adjusted_record_count, group=PHASE_VALIDATION)
    if adjustments_applied:
        _ui_metric(ui, "adjustment names", ", ".join(adjustments_applied), group=PHASE_VALIDATION)
    _ui_output(ui, "Adjusted EPC dataset", parquet_file if parquet_file and parquet_file.exists() else output_file)
    _ui_output(ui, "Adjustment summary", DATA_PROCESSED_DIR / "methodological_adjustments_summary.json")

    if analysis_logger:
        analysis_logger.add_metric("adjustments_applied", len(adjustments_applied), f"Applied: {', '.join(adjustments_applied)}")
        analysis_logger.add_metric("records_adjusted", adjusted_record_count, "Records with adjustments")
        analysis_logger.add_output(str(output_file), "csv", "Adjusted EPC dataset")
        analysis_logger.add_output("data/processed/methodological_adjustments_summary.json", "report", "Methodological adjustments summary (JSON)")
        if parquet_file and parquet_file.exists():
            analysis_logger.add_output(str(parquet_file), "parquet", "Adjusted EPC dataset (Parquet)")
        analysis_logger.complete_phase(success=True, message=f"{len(adjustments_applied)} methodological adjustments applied")

    _ui_phase_completed(ui, "Methodological Adjustments", f"{len(adjustments_applied)} adjustments applied")
    return df_adjusted, summary


def ensure_hp_hn_comparison_outputs(df=None, analysis_logger: AnalysisLogger = None, ui=None):
    """Execute the required diagnostic phase and surface both attempt failures."""
    global _hp_hn_comparison_outputs_cache

    from src.utils.diagnostic_phase import run_diagnostic_phase

    phase_name = "Diagnostic Pathway Modeling"
    cohort_size = (
        int(_active_run_context.authoritative_cohort)
        if _active_run_context is not None and _active_run_context.authoritative_cohort is not None
        else (len(df) if df is not None else 0)
    )
    if analysis_logger:
        analysis_logger.start_phase(
            phase_name,
            "Generate and validate property pathways, diagnostic summary, and HP/HN comparisons",
        )
    _ui_phase_started(ui, phase_name, f"Analyzing diagnostic pathways for {cohort_size:,} properties")

    def log_failure(attempt: int, exc: Exception) -> None:
        logger.exception(f"Diagnostic pathway attempt {attempt} failed: {exc}")

    try:
        result = run_diagnostic_phase(
            df,
            context=_active_run_context,
            outputs_dir=Path(DATA_OUTPUTS_DIR),
            processed_dir=Path(DATA_PROCESSED_DIR),
            pathway_modeler_class=PathwayModeler,
            comparison_reporter_class=ComparisonReporter,
            progress_callback=_make_pathway_progress_callback(ui),
            on_attempt_failure=log_failure,
        )
    except Exception as exc:
        _hp_hn_comparison_outputs_cache = None
        if analysis_logger:
            analysis_logger.complete_phase(success=False, message=str(exc))
        _ui_phase_failed(ui, phase_name, str(exc))
        raise

    _hp_hn_comparison_outputs_cache = {"status": "success", "result": result}
    if analysis_logger:
        analysis_logger.add_output(str(result["property_results"]), "parquet", "Pathway results by property")
        analysis_logger.add_output(str(result["summary"]), "csv", "Pathway results summary")
        analysis_logger.add_output(str(result["comparison_csv"]), "csv", "HP vs HN comparison table")
        if result.get("comparison_snippet"):
            analysis_logger.add_output(str(result["comparison_snippet"]), "md", "HP vs HN markdown snippet")
        message = (
            "Validated registered diagnostic artifacts"
            if not result.get("rebuilt")
            else f"Diagnostic artifacts validated on attempt {result.get('attempt', 1)}"
        )
        analysis_logger.complete_phase(success=True, message=message)
    _ui_phase_completed(ui, phase_name, "Diagnostic pathway artifacts validated")
    return result


def analyze_archetype(df, analysis_logger: AnalysisLogger = None, ui=None):
    """Run archetype characterization."""
    console.print()
    console.print(Panel("[bold]Phase 3: Archetype Analysis[/bold]", border_style="blue"))
    console.print()
    _ui_phase_started(ui, "Archetype Analysis", "Analyzing property characteristics")

    if analysis_logger:
        analysis_logger.start_phase(
            "Archetype Analysis",
            "Characterize Edwardian housing stock by EPC bands, insulation, heating systems, etc."
        )

    console.print("[cyan]Analyzing property characteristics...[/cyan]")

    analyzer = ArchetypeAnalyzer()
    results = analyzer.analyze_archetype(df)
    analyzer.save_results()
    _ui_metric(ui, "properties", len(df), group=PHASE_MODELLING)

    console.print(f"[green]✓[/green] Archetype analysis complete")

    # Show key findings
    if 'epc_bands' in results and results['epc_bands'] and 'frequency' in results['epc_bands']:
        console.print()
        console.print("[cyan]EPC Band Distribution:[/cyan]")
        for band in ['D', 'E', 'F', 'G']:
            if band in results['epc_bands']['frequency']:
                count = results['epc_bands']['frequency'][band]
                pct = results['epc_bands']['percentage'][band]
                console.print(f"    Band {band}: {count:,} ({pct:.1f}%)")
                _ui_metric(ui, f"EPC band {band}", count, group=PHASE_MODELLING)

        if analysis_logger:
            for band in ['D', 'E', 'F', 'G']:
                if band in results['epc_bands']['frequency']:
                    count = results['epc_bands']['frequency'][band]
                    pct = results['epc_bands']['percentage'][band]
                    analysis_logger.add_metric(f"epc_band_{band}", count, f"Band {band}: {pct:.1f}%")
    else:
        console.print()
        console.print("[yellow]Note: EPC band distribution analysis could not be completed (missing required columns)[/yellow]")

    if analysis_logger:
        analysis_logger.add_output("data/outputs/archetype_analysis_results.txt", "report", "Archetype characterization results")
        analysis_logger.complete_phase(success=True, message="Archetype characterization complete")

    if results:
        _ui_metric(ui, "archetype result sections", len(results), group=PHASE_MODELLING)
    _ui_output(ui, "Archetype results", "data/outputs/archetype_analysis_results.txt")
    _ui_phase_completed(ui, "Archetype Analysis", "Archetype characterization complete")
    return results


def model_scenarios(df, analysis_logger: AnalysisLogger = None, ui=None):
    """Run scenario modeling."""
    console.print()
    console.print(Panel("[bold]Phase 4: Scenario Modeling[/bold]", border_style="blue"))
    console.print()
    _ui_phase_started(ui, "Scenario Modeling", "Modeling decarbonization scenarios")

    if analysis_logger:
        analysis_logger.start_phase(
            "Scenario Modeling",
            "Model decarbonization scenarios (heat pump, hybrid, district heating) and subsidy sensitivity"
        )

    console.print("[cyan]Modeling decarbonization scenarios...[/cyan]")

    modeler = ScenarioModeler()
    scenario_cb = _make_scenario_progress_callback(ui)
    scenario_results = _call_with_optional_ui(
        modeler.model_all_scenarios,
        df,
        progress_callback=scenario_cb,
    )

    console.print(f"[green]✓[/green] Scenario modeling complete")

    # Show summary
    console.print()
    console.print("[cyan]Scenario Summary:[/cyan]")
    if scenario_results:
        for scenario, results in scenario_results.items():
            if 'capital_cost_per_property' in results:
                cost_per_property = results['capital_cost_per_property']
                _ui_metric(ui, f"{scenario} status", "complete", group=PHASE_MODELLING)
                _ui_metric(ui, f"{scenario} cost/property", cost_per_property, group=PHASE_MODELLING)
                console.print(f"    {scenario}: £{results['capital_cost_per_property']:,.0f} per property")
                if analysis_logger:
                    analysis_logger.add_metric(f"scenario_{scenario}_cost", cost_per_property, f"Capital cost per property")
            else:
                console.print(f"    {scenario}: Analysis incomplete (missing required data)")
                _ui_metric(ui, f"{scenario} status", "skipped", group=PHASE_MODELLING)
    else:
        console.print("[yellow]Note: Scenario modeling could not be completed (missing required columns)[/yellow]")
        _ui_warning(ui, "Scenario modeling could not be completed")

    # Subsidy analysis
    console.print()
    console.print("[cyan]Running subsidy sensitivity analysis...[/cyan]")
    subsidy_results_by_scenario = modeler.model_subsidy_sensitivity_multi(
        df,
        scenario_names=["heat_pump", "hybrid", "heat_network"],
    )
    # Keep legacy single-scenario dict for downstream plotting/report functions.
    subsidy_results = subsidy_results_by_scenario.get("heat_pump", {})

    save_paths = modeler.save_results()
    console.print(f"[green]✓[/green] Results saved")
    if save_paths.get('property_path'):
        console.print(f"    • Property-level results: {save_paths['property_path']}")
    if save_paths.get('summary_path'):
        console.print(f"    • Scenario summary: {save_paths['summary_path']}")

    # Generate the fabric tipping point figure (PNG + editable SVG).
    try:
        from src.reporting.visualizations import ReportGenerator

        viz = ReportGenerator()
        viz.plot_fabric_tipping_point_analysis()
        console.print("[green]✓[/green] Tipping point chart saved to data/outputs/figures/")

        if analysis_logger:
            tipping_png = DATA_OUTPUTS_DIR / "figures" / "tipping_point.png"
            tipping_svg = DATA_OUTPUTS_DIR / "figures" / "tipping_point.svg"
            if tipping_png.exists():
                analysis_logger.add_output(
                    "data/outputs/figures/tipping_point.png",
                    "png",
                    "Fabric tipping point analysis (chart)",
                )
            if tipping_svg.exists():
                analysis_logger.add_output(
                    "data/outputs/figures/tipping_point.svg",
                    "svg",
                    "Fabric tipping point analysis (vector)",
                )
    except Exception as e:
        console.print(f"[yellow]⚠ Could not generate tipping point chart: {e}[/yellow]")
        logger.exception("Tipping point chart generation failed")

    if analysis_logger:
        analysis_logger.add_metric("scenarios_modeled", len(scenario_results), "Decarbonization scenarios analyzed")
        analysis_logger.add_output("data/outputs/scenario_modeling_results.txt", "report", "Scenario modeling results")
        if save_paths.get('property_path'):
            analysis_logger.add_output(str(save_paths['property_path']), "parquet", "Scenario results by property")
        if save_paths.get('summary_path'):
            analysis_logger.add_output(str(save_paths['summary_path']), "csv", "Scenario results summary")
        analysis_logger.complete_phase(success=True, message=f"{len(scenario_results)} scenarios modeled successfully")

    _ui_metric(ui, "scenarios modeled", len(scenario_results), group=PHASE_MODELLING)
    if save_paths.get('property_path'):
        _ui_output(ui, "Scenario property results", save_paths['property_path'])
    if save_paths.get('summary_path'):
        _ui_output(ui, "Scenario summary", save_paths['summary_path'])
    _ui_phase_completed(ui, "Scenario Modeling", f"{len(scenario_results)} scenarios modeled")
    return scenario_results, subsidy_results


def analyze_retrofit_readiness(df, analysis_logger: AnalysisLogger = None, one_stop_only: bool = False, ui=None):
    """Analyze heat pump retrofit readiness."""
    console.print()
    console.print(Panel("[bold]Phase 4.3: Retrofit Readiness Analysis[/bold]", border_style="blue"))
    console.print()
    _ui_phase_started(ui, "Retrofit Readiness Analysis", "Assessing heat pump readiness")

    if analysis_logger:
        analysis_logger.start_phase(
            "Retrofit Readiness Analysis",
            "Assess heat pump readiness, fabric pre-requisites, and retrofit costs"
        )

    console.print("[cyan]Assessing heat pump readiness and barriers...[/cyan]")
    console.print()
    console.print("This phase analyzes:")
    console.print("  • Current heat pump suitability")
    console.print("  • Required fabric pre-requisites")
    console.print("  • Pre-retrofit cost barriers")
    console.print("  • Heat demand before/after fabric improvements")
    console.print()

    try:
        from src.analysis.retrofit_readiness import RetrofitReadinessAnalyzer

        from src.utils.readiness_phase import run_readiness_phase

        def log_failure(attempt: int, exc: Exception) -> None:
            logger.exception(f"Retrofit readiness attempt {attempt} failed: {exc}")

        result = run_readiness_phase(
            df,
            context=_active_run_context,
            outputs_dir=Path(DATA_OUTPUTS_DIR),
            processed_dir=Path(DATA_PROCESSED_DIR),
            analyzer_class=RetrofitReadinessAnalyzer,
            on_attempt_failure=log_failure,
        )
        df_readiness = result["readiness_frame"]
        summary = result["summary"]

        # Display key findings
        console.print("[green]✓[/green] Retrofit readiness analysis complete")
        console.print()
        console.print("[cyan]Key Findings:[/cyan]")
        console.print(f"  Tier 1 (Ready Now): {summary['tier_distribution'].get(1, 0):,} properties ({summary['tier_percentages'].get(1, 0):.1f}%)")
        console.print(f"  Tier 2 (Minor Work): {summary['tier_distribution'].get(2, 0):,} properties ({summary['tier_percentages'].get(2, 0):.1f}%)")
        console.print(f"  Tier 3 (Major Work): {summary['tier_distribution'].get(3, 0):,} properties ({summary['tier_percentages'].get(3, 0):.1f}%)")
        console.print(f"  Tier 4 (Challenging): {summary['tier_distribution'].get(4, 0):,} properties ({summary['tier_percentages'].get(4, 0):.1f}%)")
        console.print(f"  Tier 5 (Not Suitable): {summary['tier_distribution'].get(5, 0):,} properties ({summary['tier_percentages'].get(5, 0):.1f}%)")
        console.print()
        console.print(f"  Solid wall barrier: {summary['needs_solid_wall_insulation']:,} properties need SWI")
        console.print(f"  Mean fabric cost: £{summary['mean_fabric_cost']:,.0f}")
        console.print(f"  Total retrofit investment: £{summary['total_retrofit_cost']/1e6:.1f}M")
        console.print()

        for tier in range(1, 6):
            _ui_metric(
                ui,
                f"retrofit tier {tier}",
                summary['tier_distribution'].get(tier, 0),
                group=PHASE_MODELLING,
            )
        _ui_metric(ui, "solid wall barrier count", summary['needs_solid_wall_insulation'], group=PHASE_MODELLING)
        _ui_metric(ui, "mean fabric cost", summary['mean_fabric_cost'], group=PHASE_MODELLING)
        _ui_metric(ui, "total retrofit investment", summary['total_retrofit_cost'], group=PHASE_MODELLING)

        if analysis_logger:
            for tier in range(1, 6):
                count = summary['tier_distribution'].get(tier, 0)
                pct = summary['tier_percentages'].get(tier, 0)
            analysis_logger.add_metric(f"retrofit_tier_{tier}", count, f"{pct:.1f}% of properties")
            analysis_logger.add_metric("mean_fabric_cost", summary['mean_fabric_cost'], "Average fabric improvement cost per property")
            analysis_logger.add_metric("total_retrofit_cost", summary['total_retrofit_cost'], "Total retrofit investment needed")

        viz = None
        try:
            from src.reporting.visualizations import ReportGenerator

            viz = ReportGenerator()
        except Exception as e:
            console.print(f"[yellow]⚠ Could not initialise visualizations: {e}[/yellow]")
            logger.exception("Visualization initialization failed")

        if viz is not None:
            # Always generate the EPC lodgements-by-year figure (used in the report).
            try:
                console.print("[cyan]Creating EPC lodgement visualizations...[/cyan]")
                viz.plot_epc_lodgements_by_year_band(df)
                console.print("[green]✓[/green] EPC lodgement charts saved to data/outputs/figures/")

                if analysis_logger:
                    counts_png = DATA_OUTPUTS_DIR / "figures" / "epc_lodgement_year_band_stacked_counts.png"
                    share_png = DATA_OUTPUTS_DIR / "figures" / "epc_lodgement_year_band_stacked_share.png"
                    if counts_png.exists():
                        analysis_logger.add_output(
                            "data/outputs/figures/epc_lodgement_year_band_stacked_counts.png",
                            "png",
                            "EPC lodgements by year (counts; bands stacked)",
                        )
                    if share_png.exists():
                        analysis_logger.add_output(
                            "data/outputs/figures/epc_lodgement_year_band_stacked_share.png",
                            "png",
                            "EPC lodgements by year (share; bands stacked)",
                        )
            except Exception as e:
                console.print(f"[yellow]⚠ Could not generate EPC lodgement charts: {e}[/yellow]")
                logger.exception("EPC lodgement chart generation failed")

        if not one_stop_only and viz is not None:
            # Generate retrofit readiness visualizations (heavier charts).
            console.print("[cyan]Creating retrofit readiness visualizations...[/cyan]")
            try:
                viz.plot_retrofit_readiness_dashboard(df_readiness, summary)
                viz.plot_fabric_cost_distribution(df_readiness)
                viz.plot_heat_demand_scatter(df_readiness)
                console.print("[green]✓[/green] Visualizations saved to data/outputs/figures/")
            except Exception as e:
                console.print(f"[yellow]⚠ Could not generate retrofit readiness charts: {e}[/yellow]")
                logger.exception("Retrofit readiness chart generation failed")

        if analysis_logger:
            analysis_logger.add_output("data/outputs/retrofit_readiness_analysis.csv", "csv", "Property-level retrofit readiness")
            analysis_logger.add_output("data/outputs/reports/retrofit_readiness_summary.txt", "report", "Retrofit readiness summary")
            if not one_stop_only:
                analysis_logger.add_output("data/outputs/figures/retrofit_readiness_dashboard.png", "png", "Retrofit readiness visualization")
            analysis_logger.complete_phase(success=True, message="Retrofit readiness assessment complete")

        _ui_output(ui, "Retrofit readiness results", "data/outputs/retrofit_readiness_analysis.csv")
        _ui_phase_completed(ui, "Retrofit Readiness Analysis", "Retrofit readiness assessment complete")
        return df_readiness, summary

    except Exception as e:
        _ui_phase_failed(ui, "Retrofit Readiness Analysis", f"Retrofit readiness failed: {e}")
        console.print(f"[yellow]⚠ Retrofit readiness analysis failed: {e}[/yellow]")
        logger.error(f"Retrofit readiness error: {e}")
        if analysis_logger:
            analysis_logger.complete_phase(success=False, message=f"Error: {e}")
        raise


def run_spatial_analysis(df, analysis_logger: AnalysisLogger = None, one_stop_only: bool = False, ui=None):
    """Run required spatial classification; rendered map formats are optional."""
    console.print()
    console.print(Panel("[bold]Phase 4.5: Spatial Analysis[/bold]", border_style="blue"))
    console.print()
    _ui_phase_started(ui, "Spatial Analysis", "Checking spatial dependencies")

    console.print("[cyan]Heat Network Tier Classification[/cyan]")
    console.print()
    console.print("This phase requires GDAL/geopandas for spatial analysis.")
    console.print("If not installed, this phase will be skipped.")
    console.print()

    def get_spatial_dependency_status():
        """Return missing modules plus available vector IO backends."""
        missing = []
        for module_name in ("geopandas", "shapely", "pyproj"):
            try:
                __import__(module_name)
            except ImportError:
                missing.append(module_name)

        available_backends = []
        for backend_name in ("pyogrio", "fiona"):
            try:
                __import__(backend_name)
                available_backends.append(backend_name)
            except ImportError:
                continue

        if not available_backends:
            missing.append("pyogrio-or-fiona")

        return missing, available_backends

    def get_windows_conda_shell_status() -> tuple[list[str], list[str], str]:
        """Inspect whether the current Windows shell is a clean Conda spatial environment."""
        issues = []
        warnings = []
        conda_env = os.getenv("CONDA_DEFAULT_ENV", "")
        conda_prefix = os.getenv("CONDA_PREFIX", "")
        python_on_path = shutil.which("python") or ""
        pip_on_path = shutil.which("pip") or ""
        python_executable = str(Path(sys.executable).resolve())
        prefix_path = str(Path(conda_prefix).resolve()) if conda_prefix else ""

        if not shutil.which("conda"):
            issues.append("conda is not available on PATH")
        if not conda_env or conda_env.lower() == "base":
            issues.append("no dedicated Conda environment is active")
        if not conda_prefix:
            issues.append("CONDA_PREFIX is not set")
        if prefix_path and not python_executable.lower().startswith(prefix_path.lower()):
            issues.append(
                f"python is running from {python_executable}, not from the active Conda prefix {prefix_path}"
            )
        if prefix_path and python_on_path:
            resolved_python = str(Path(python_on_path).resolve())
            if not resolved_python.lower().startswith(prefix_path.lower()):
                issues.append(f"python on PATH resolves to {resolved_python}, not to {prefix_path}")
        if prefix_path and pip_on_path:
            resolved_pip = str(Path(pip_on_path).resolve())
            if not resolved_pip.lower().startswith(prefix_path.lower()):
                issues.append(f"pip on PATH resolves to {resolved_pip}, not to {prefix_path}")

        if sys.version_info[:2] not in {(3, 11), (3, 12)}:
            issues.append(
                f"Python {sys.version_info.major}.{sys.version_info.minor} is unsupported for the Windows spatial workflow"
            )

        for label, candidate in (("python", python_on_path), ("pip", pip_on_path)):
            if candidate and "appdata\\roaming\\python" in candidate.lower():
                warnings.append(f"{label} is resolving from user site: {candidate}")

        return issues, warnings, conda_env

    def print_windows_spatial_guidance():
        """Print the supported Windows recovery path and diagnosis commands."""
        console.print("[cyan]Supported Windows fix:[/cyan]")
        console.print("  conda env create -f environment.yml")
        console.print("  conda activate heatstreet")
        console.print(r"  .\run-conda.ps1")
        console.print()
        console.print("[cyan]Diagnosis commands:[/cyan]")
        console.print("  where python")
        console.print("  where pip")
        console.print("  conda info")
        console.print(r'  conda list | findstr /i "python geopandas fiona gdal shapely"')
        console.print()
        console.print(
            "If pip is trying to build Fiona/GDAL and asks for GDAL_VERSION or gdal-config, "
            "you are on the unsupported Windows pip path."
        )

    def check_spatial_dependencies():
        """Check for required spatial libraries before running analysis."""
        missing_modules, available_backends = get_spatial_dependency_status()
        if not missing_modules:
            _ui_metric(ui, "spatial dependencies", "available", group=PHASE_MODELLING)
            return True

        _ui_warning(ui, f"Spatial dependencies missing: {', '.join(missing_modules)}")
        console.print()
        console.print("[yellow]⚠ Spatial libraries missing[/yellow]")
        console.print(f"Missing modules/backend: {', '.join(missing_modules)}")
        if available_backends:
            console.print(f"Detected spatial IO backend(s): {', '.join(available_backends)}")
        console.print("Map outputs require the spatial stack to be available.")
        console.print()

        if platform.system() == "Windows":
            issues, warnings, conda_env = get_windows_conda_shell_status()
            for warning in warnings:
                console.print(f"[yellow]⚠ {warning}[/yellow]")

            if issues:
                console.print("[yellow]This shell is not a supported Windows spatial environment.[/yellow]")
                for issue in issues:
                    console.print(f"  - {issue}")
                console.print()
                print_windows_spatial_guidance()

                choice = _tui_prompt(
                    ui, "select",
                    title="Spatial dependencies missing",
                    message="How would you like to proceed?",
                    choices=["abort", "skip"],
                    labels=["Pause/abort so I can fix the Conda environment", "Continue without spatial results"],
                )
                if choice is None:
                    with _ui_suspend(ui, "Waiting for spatial dependency decision"):
                        raw = questionary.select(
                            "How would you like to proceed?",
                            choices=[
                                questionary.Choice("Pause/abort so I can fix the Conda environment", value="abort"),
                                questionary.Choice("Continue without spatial results", value="skip"),
                            ],
                        ).ask()
                        choice = raw
            else:
                install_command = (
                    f"conda install -n {conda_env} -c conda-forge "
                    "geopandas fiona gdal pyproj shapely rtree pyogrio folium"
                )
                console.print(f"Recommended Windows fix: [bold]{install_command}[/bold]")
                console.print()
                choice = _tui_prompt(
                    ui, "select",
                    title="Spatial dependencies missing",
                    message="How would you like to proceed?",
                    choices=["install", "abort", "skip"],
                    labels=[
                        "Attempt to install spatial dependencies now (conda)",
                        "Pause/abort to install manually",
                        "Continue without spatial results",
                    ],
                )
                if choice is None:
                    with _ui_suspend(ui, "Waiting for spatial dependency decision"):
                        raw = questionary.select(
                            "How would you like to proceed?",
                            choices=[
                                questionary.Choice("Attempt to install spatial dependencies now (conda)", value="install"),
                                questionary.Choice("Pause/abort to install manually", value="abort"),
                                questionary.Choice("Continue without spatial results", value="skip"),
                            ],
                        ).ask()
                        choice = raw

                if choice == "install":
                    console.print()
                    console.print("[cyan]Attempting to install spatial dependencies from conda-forge...[/cyan]")
                    result = subprocess.run(
                        [
                            "conda",
                            "install",
                            "-n",
                            conda_env,
                            "-c",
                            "conda-forge",
                            "geopandas",
                            "fiona",
                            "gdal",
                            "pyproj",
                            "shapely",
                            "rtree",
                            "pyogrio",
                            "folium",
                            "-y",
                        ],
                        capture_output=True,
                        text=True,
                    )

                    if result.returncode == 0:
                        console.print("[green]✓[/green] Spatial dependencies installed. Re-checking...")
                        return check_spatial_dependencies()

                    console.print("[yellow]⚠ Could not install spatial dependencies automatically.[/yellow]")
                    print_windows_spatial_guidance()
        else:
            install_command = "pip install -r requirements-spatial.txt"
            console.print(f"Recommended fix for this environment: [bold]{install_command}[/bold]")
            console.print()
            choice = _tui_prompt(
                ui, "select",
                title="Spatial dependencies missing",
                message="How would you like to proceed?",
                choices=["install", "abort", "skip"],
                labels=[
                    "Attempt to install requirements-spatial.txt now (pip)",
                    "Pause/abort to install manually",
                    "Continue without spatial results",
                ],
            )
            if choice is None:
                with _ui_suspend(ui, "Waiting for spatial dependency decision"):
                    raw = questionary.select(
                        "How would you like to proceed?",
                        choices=[
                            questionary.Choice("Attempt to install requirements-spatial.txt now (pip)", value="install"),
                            questionary.Choice("Pause/abort to install manually", value="abort"),
                            questionary.Choice("Continue without spatial results", value="skip"),
                        ],
                    ).ask()
                    choice = raw

            if choice == "install":
                console.print()
                console.print("[cyan]Attempting to install spatial dependencies...[/cyan]")
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-r", "requirements-spatial.txt"],
                    capture_output=True,
                    text=True,
                )

                if result.returncode == 0:
                    console.print("[green]✓[/green] Spatial dependencies installed. Re-checking...")
                    return check_spatial_dependencies()

                console.print("[yellow]⚠ Could not install spatial dependencies automatically.[/yellow]")
                console.print("Install manually with: pip install -r requirements-spatial.txt")

        if choice == "abort":
            console.print("[yellow]Analysis paused. Install the spatial dependencies and re-run the spatial phase.[/yellow]")
            if analysis_logger:
                analysis_logger.skip_phase(
                    "Spatial Analysis", "User paused to install GIS dependencies before continuing",
                )
            raise SystemExit(EXIT_CANCELLED)

        console.print("[yellow]Continuing without spatial analysis. Map outputs will be absent.[/yellow]")
        if analysis_logger:
            analysis_logger.skip_phase(
                "Spatial Analysis", "Spatial dependencies missing; map outputs will not be generated",
            )
        _ui_phase_skipped(ui, "Spatial Analysis", "Spatial dependencies missing")
        return False

    if not check_spatial_dependencies():
        _ui_phase_skipped(ui, "Spatial Analysis", "Spatial analysis skipped")
        return None, None

    try:
        from src.spatial.heat_network_analysis import HeatNetworkAnalyzer

        if analysis_logger:
            analysis_logger.start_phase(
                "Spatial Analysis",
                "Geocode properties and classify into heat network tiers based on heat density"
            )

        analyzer = HeatNetworkAnalyzer(
            processed_dir=Path(DATA_PROCESSED_DIR),
            output_dir=Path(DATA_OUTPUTS_DIR),
        )

        console.print("[cyan]Running spatial analysis...[/cyan]")
        console.print("  • Geocoding properties from lat/lon coordinates")
        console.print("  • Loading HNPD heat network data")
        console.print("  • Calculating heat density (GWh/km²)")
        console.print("  • Classifying into 5 heat network tiers")
        console.print()

        with _external_progress_context(ui):
            properties_classified, pathway_summary = analyzer.run_complete_analysis(
                df, auto_download_gis=True, create_maps=not one_stop_only
            )

        if properties_classified is not None and pathway_summary is not None:
            console.print(f"[green]✓[/green] Spatial analysis complete!")
            console.print()
            console.print("[cyan]Heat Network Tier Summary:[/cyan]")

            # Show tier counts
            for _, row in pathway_summary.iterrows():
                tier_name = row['Tier']
                count = row['Property Count']
                pct = row['Percentage']
                pathway = row['Recommended Pathway']
                console.print(f"    {tier_name}: {count:,} ({pct:.1f}%) → {pathway}")

            console.print()
            console.print(f"[cyan]📁 Outputs:[/cyan]")
            console.print(f"    • GeoJSON: data/processed/epc_with_heat_network_tiers.geojson")
            console.print(f"    • CSV: data/outputs/pathway_suitability_by_tier.csv")
            if not one_stop_only:
                console.print(f"    • Interactive Map: data/outputs/maps/heat_network_tiers.html")

            if analysis_logger:
                analysis_logger.add_metric("properties_geocoded", len(properties_classified), "Properties with spatial classification")
                analysis_logger.add_output("data/processed/epc_with_heat_network_tiers.geojson", "geojson", "Geocoded properties with heat network tiers")
                analysis_logger.add_output("data/outputs/pathway_suitability_by_tier.csv", "csv", "Pathway suitability by tier")
                if not one_stop_only:
                    map_html = Path("data/outputs/maps/heat_network_tiers.html")
                    map_png = map_html.with_suffix('.png')
                    map_pdf = map_html.with_suffix('.pdf')

                    analysis_logger.add_output("data/outputs/maps/heat_network_tiers.html", "html", "Interactive heat network tier map")

                    if map_png.exists():
                        analysis_logger.add_output(str(map_png), "png", "Heat network tier map (image)")
                    if map_pdf.exists():
                        analysis_logger.add_output(str(map_pdf), "pdf", "Heat network tier map (PDF)")
                analysis_logger.complete_phase(success=True, message="Spatial analysis with heat network classification complete")

            _ui_metric(ui, "properties geocoded", len(properties_classified), group=PHASE_MODELLING)
            _ui_output(ui, "Spatial GeoJSON", "data/processed/epc_with_heat_network_tiers.geojson")
            _ui_output(ui, "Pathway suitability by tier", "data/outputs/pathway_suitability_by_tier.csv")
            if not one_stop_only:
                _ui_output(ui, "Heat network map", "data/outputs/maps/heat_network_tiers.html")
            _ui_phase_completed(ui, "Spatial Analysis", "Spatial heat-network classification complete")
            return properties_classified, pathway_summary
        else:
            console.print("[yellow]⚠ Spatial analysis could not complete[/yellow]")
            if analysis_logger:
                analysis_logger.complete_phase(success=False, message="Spatial analysis could not complete")
            _ui_phase_failed(ui, "Spatial Analysis", "Spatial analysis could not complete")
            return None, None

    except ImportError as e:
        _ui_phase_skipped(ui, "Spatial Analysis", "GDAL/geopandas not installed")
        console.print()
        console.print("[yellow]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/yellow]")
        console.print("[yellow]⚠ GDAL/geopandas not installed - Skipping spatial analysis[/yellow]")
        console.print("[yellow]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/yellow]")
        console.print()
        console.print("[cyan]To enable spatial analysis:[/cyan]")
        if platform.system() == "Windows":
            console.print("  [bold]Windows (Supported path):[/bold]")
            console.print("    conda env create -f environment.yml")
            console.print("    conda activate heatstreet")
            console.print(r"    .\run-conda.ps1")
            console.print()
            console.print("  [bold]Diagnosis:[/bold]")
            console.print("    where python")
            console.print("    where pip")
            console.print("    conda info")
            console.print(r'    conda list | findstr /i "python geopandas fiona gdal shapely"')
            console.print()
            console.print("  Python 3.11 or 3.12 is supported on Windows for the spatial stack.")
            console.print("  Python 3.13 and 3.14 are not a supported default here yet.")
        else:
            console.print("  [bold]Linux/Mac:[/bold]")
            console.print("    pip install -r requirements-spatial.txt")
        console.print()
        console.print("[cyan]The rest of the analysis will continue without spatial features.[/cyan]")
        console.print()
        if analysis_logger:
            analysis_logger.skip_phase("Spatial Analysis", "GDAL/geopandas not installed")
        return None, None

    except Exception as e:
        _ui_phase_failed(ui, "Spatial Analysis", f"Spatial analysis error: {e}")
        console.print(f"[yellow]⚠ Spatial analysis error: {e}[/yellow]")
        console.print("[cyan]Continuing without spatial analysis...[/cyan]")
        if analysis_logger:
            analysis_logger.complete_phase(success=False, message=f"Error: {e}")
        return None, None


def generate_reports(
    archetype_results,
    scenario_results,
    subsidy_results=None,
    df_validated=None,
    pathway_summary=None,
    analysis_logger: AnalysisLogger = None,
    ui=None,
    one_stop_only: Optional[bool] = None,
):
    """Generate final reports and visualizations."""
    console.print()
    console.print(Panel("[bold]Phase 5: Report Generation[/bold]", border_style="blue"))
    console.print()
    _ui_phase_started(ui, "Report Generation", "Generating reports and visualizations")

    effective_one_stop_only = is_one_stop_only() if one_stop_only is None else one_stop_only
    if effective_one_stop_only:
        console.print("[cyan]One-stop reporting enabled; skipping additional report outputs.[/cyan]")
        if analysis_logger:
            analysis_logger.skip_phase("Report Generation", "One-stop report output enabled")
        _ui_phase_skipped(ui, "Report Generation", "One-stop report output enabled")
        return []

    if analysis_logger:
        analysis_logger.start_phase(
            "Report Generation",
            "Generate comprehensive reports, visualizations, and Excel workbook"
        )

    console.print("[cyan]Generating comprehensive reports and visualizations...[/cyan]")

    from src.reporting.visualizations import ReportGenerator

    generator = ReportGenerator()
    reports_created = []

    # 1. EPC Band Distribution
    if archetype_results and 'epc_bands' in archetype_results and archetype_results['epc_bands']:
        try:
            generator.plot_epc_band_distribution(archetype_results['epc_bands'])
            reports_created.append("✓ EPC band distribution chart")
        except Exception as e:
            console.print(f"[yellow]⚠ Could not generate EPC band chart: {e}[/yellow]")

    # 2. SAP Score Distribution
    if df_validated is not None and 'CURRENT_ENERGY_EFFICIENCY' in df_validated.columns:
        try:
            import pandas as pd
            sap_scores = df_validated['CURRENT_ENERGY_EFFICIENCY'].dropna()
            if len(sap_scores) > 0:
                generator.plot_sap_score_distribution(sap_scores)
                reports_created.append("✓ SAP score distribution histogram")
        except Exception as e:
            console.print(f"[yellow]⚠ Could not generate SAP score chart: {e}[/yellow]")

    # 3. Scenario Comparison
    if scenario_results and len(scenario_results) > 0:
        try:
            generator.plot_scenario_comparison(scenario_results)
            reports_created.append("✓ Scenario comparison charts")
        except Exception as e:
            console.print(f"[yellow]⚠ Could not generate scenario comparison: {e}[/yellow]")

    # 4. Subsidy Sensitivity Analysis
    if subsidy_results and len(subsidy_results) > 0:
        try:
            generator.plot_subsidy_sensitivity(subsidy_results)
            reports_created.append("✓ Subsidy sensitivity analysis")
        except Exception as e:
            console.print(f"[yellow]⚠ Could not generate subsidy chart: {e}[/yellow]")

    # 5. Text and Markdown Summary Reports
    if archetype_results and scenario_results:
        try:
            # Use real pathway summary from spatial analysis if available
            import pandas as pd

            if pathway_summary is not None and len(pathway_summary) > 0:
                # Use actual spatial analysis results
                tier_summary = pathway_summary
                console.print("[cyan]Using real heat network tier data from spatial analysis[/cyan]")
            else:
                # Fallback: placeholder tier summary (if spatial analysis was skipped)
                tier_summary = pd.DataFrame({
                    'Tier': ['Tier 5 (All properties - spatial analysis not run)'],
                    'Property Count': [len(df_validated) if df_validated is not None else 0],
                    'Percentage': [100.0],
                    'Recommended Pathway': ['Heat Pump (default recommendation)']
                })

            generator.generate_summary_report(archetype_results, scenario_results, tier_summary)
            reports_created.append("✓ Executive summary report (text)")
            generator.generate_markdown_summary(archetype_results, scenario_results, tier_summary)
            reports_created.append("✓ Executive summary report (Markdown)")
        except Exception as e:
            console.print(f"[yellow]⚠ Could not generate summary report: {e}[/yellow]")

    # 6. Excel Export
    if archetype_results and scenario_results:
        try:
            generator.export_to_excel(
                archetype_results=archetype_results,
                scenario_results=scenario_results,
                subsidy_results=subsidy_results,
                df_properties=df_validated
            )
            reports_created.append("✓ Excel workbook with all results")
        except Exception as e:
            console.print(f"[yellow]⚠ Could not generate Excel export: {e}[/yellow]")

    console.print()
    console.print(f"[green]✓[/green] Report generation complete!")
    console.print()

    if reports_created:
        console.print("[cyan]Generated outputs:[/cyan]")
        for report in reports_created:
            console.print(f"    {report}")
    else:
        console.print("[yellow]No reports could be generated (missing data)[/yellow]")

    console.print()
    console.print(f"[cyan]📁 Output location:[/cyan] data/outputs/")
    console.print(f"    • Figures: data/outputs/figures/")
    console.print(f"    • Reports: data/outputs/reports/")
    console.print(f"    • Results: data/outputs/*.txt")

    if analysis_logger:
        analysis_logger.add_metric("reports_generated", len(reports_created), f"{len(reports_created)} reports and visualizations")
        for report in reports_created:
            # Extract file types from report descriptions
            if "chart" in report.lower() or "histogram" in report.lower():
                analysis_logger.add_output("data/outputs/figures/", "png", report.replace("✓ ", ""))
        analysis_logger.add_output("data/outputs/heat_street_analysis_results.xlsx", "xlsx", "Comprehensive Excel workbook")
        analysis_logger.add_output("data/outputs/reports/executive_summary.txt", "report", "Executive summary (text)")
        analysis_logger.add_output("data/outputs/reports/executive_summary.md", "report", "Executive summary (Markdown)")
        analysis_logger.complete_phase(success=True, message=f"{len(reports_created)} reports and visualizations generated")

    _ui_metric(ui, "reports generated", len(reports_created), group=PHASE_OUTPUTS)
    _ui_output(ui, "Figures", "data/outputs/figures/")
    _ui_output(ui, "Reports", "data/outputs/reports/")
    _ui_output(ui, "Workbook", "data/outputs/heat_street_analysis_results.xlsx")
    _ui_phase_completed(ui, "Report Generation", f"{len(reports_created)} reports generated")
    return True


def generate_one_stop_report(df=None, analysis_logger: AnalysisLogger = None, ui=None):
    """Generate the one-stop JSON report."""
    console.print()
    console.print(Panel("[bold]Phase 5: One-Stop Report[/bold]", border_style="blue"))
    console.print()
    console.print("[cyan]Generating one-stop JSON report...[/cyan]")
    _ui_phase_started(ui, "One-Stop Report", "Generating one-stop JSON report")

    if _active_run_context is not None:
        _write_current_run_metadata(
            analysis_logger,
            _active_run_context,
            int(_active_authoritative_cohort_size),
        )
        stamp_artifact_tree([Path(DATA_OUTPUTS_DIR)], _active_run_context)
        processed_artifacts = [
            Path(DATA_PROCESSED_DIR) / "validation_report.json",
            Path(DATA_PROCESSED_DIR) / "methodological_adjustments_summary.json",
            Path(DATA_PROCESSED_DIR) / "epc_london_validated.csv",
            Path(DATA_PROCESSED_DIR) / "epc_london_validated.parquet",
            Path(DATA_PROCESSED_DIR) / "epc_london_adjusted.csv",
            Path(DATA_PROCESSED_DIR) / "epc_london_adjusted.parquet",
        ]
        for artifact in processed_artifacts:
            if artifact.is_file():
                stamp_artifact(artifact, _active_run_context)
        manifest = _register_current_artifacts(_active_run_context)
        _require_contract(
            manifest,
            [
                "run_metadata", "validation_report", "adjustment_summary",
                "archetype_analysis", "readiness", "spatial_suitability",
                "internal_scenarios", "client_scenarios", "diagnostic_pathways",
                "borough_breakdown", "borough_priority", "tenure_segmentation",
                "network_thresholds", "case_street_extract", "case_street_summary",
                "subsidy_detailed", "subsidy_simplified",
            ],
        )

    from src.reporting.one_stop_report import OneStopReportGenerator

    generator_kwargs: Dict[str, Any] = {}
    if _active_run_context is not None:
        generator_kwargs.update(
            output_dir=Path(DATA_OUTPUTS_DIR),
            processed_dir=Path(DATA_PROCESSED_DIR),
            run_id=_active_run_context.run_id,
            dataset_fingerprint=_active_run_context.dataset_fingerprint,
            authoritative_cohort_size=_active_authoritative_cohort_size,
            run_context=_active_run_context,
        )
    generator = OneStopReportGenerator(**generator_kwargs)
    output_path = generator.generate()
    if _active_run_context is not None:
        shutil.copy2(
            Path(DATA_PROCESSED_DIR) / "validation_report.json",
            Path(DATA_OUTPUTS_DIR) / "validation_report.json",
        )
        stamp_artifact(Path(DATA_OUTPUTS_DIR) / "validation_report.json", _active_run_context)
        current_manifest = _register_current_artifacts(_active_run_context)
        current_manifest.require(["one_stop_json", "published_validation_report"])

    console.print(f"[green]✓[/green] One-stop report generated: {output_path}")

    if analysis_logger:
        analysis_logger.add_output("data/outputs/one_stop_output.json", "json", "One-stop report")

    _ui_output(ui, "One-stop JSON", output_path)
    _ui_phase_completed(ui, "One-Stop Report", "One-stop JSON report generated")
    return output_path


def cleanup_reporting_outputs():
    """
    Archive non-core report artifacts for one-stop mode.

    Historically, one-stop mode aggressively deleted intermediate reporting outputs to
    leave only the consolidated one-stop JSON. That makes QA/auditing harder, because
    the one-stop output still references source CSV/JSON files that no longer exist.

    Instead of deleting, move everything except the core outputs into:
      data/outputs/bin/<run_timestamp>/

    Returns:
        Path to the archive directory, or None if nothing was moved.
    """
    from datetime import datetime

    outputs_dir = Path(DATA_OUTPUTS_DIR)

    preserved_files = {
        "one_stop_output.json",
        "one_stop_dashboard.html",
        "analysis_log.txt",
        "analysis_log.json",
        "run_metadata.json",
        "analysis_outputs_compendium.xlsx",
    }

    # Prefer using analysis_log.json metadata for a stable run identifier.
    run_id = None
    try:
        analysis_log_path = outputs_dir / "analysis_log.json"
        if analysis_log_path.exists():
            run_id = (json.loads(analysis_log_path.read_text(encoding="utf-8")) or {}).get("metadata", {}).get("analysis_start")
    except Exception:
        run_id = None

    run_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if run_id:
        try:
            run_stamp = datetime.fromisoformat(str(run_id)).strftime("%Y%m%d-%H%M%S")
        except Exception:
            pass

    archive_root = outputs_dir / "bin"
    archive_root.mkdir(parents=True, exist_ok=True)

    archive_dir = archive_root / f"run_{run_stamp}"
    if archive_dir.exists():
        archive_dir = archive_root / f"run_{run_stamp}_{datetime.now().strftime('%f')}"
    archive_dir.mkdir(parents=True, exist_ok=True)

    moved = []
    if outputs_dir.exists():
        for path in outputs_dir.iterdir():
            if path.name in preserved_files or path.name == "bin":
                continue
            if path.name == "figures" and path.is_dir():
                # Keep figures in place for easy access, but also copy to the archive for auditability.
                try:
                    dest = archive_dir / path.name
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(path, dest)
                    moved.append({"from": str(path), "to": str(dest), "mode": "copy"})
                except Exception as exc:
                    logger.warning(f"Could not copy figures directory {path} to archive: {exc}")
                continue
            try:
                dest = archive_dir / path.name
                shutil.move(str(path), str(dest))
                moved.append({"from": str(path), "to": str(dest)})
            except Exception as exc:
                logger.warning(f"Could not archive output {path}: {exc}")

    if not moved:
        return None

    try:
        manifest = {
            "archived_at": datetime.now().isoformat(),
            "run_id": run_id,
            "archive_dir": str(archive_dir),
            "moved": moved,
        }
        (archive_dir / "archive_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning(f"Could not write archive manifest: {exc}")

    return archive_dir


def generate_additional_reports(df_raw, df_validated, validation_report, archetype_results, scenario_results, analysis_logger: AnalysisLogger = None, ui=None):
    """Generate additional specialized reports for client presentation."""
    console.print()
    console.print(Panel("[bold]Phase 5.5: Additional Reports[/bold]", border_style="blue"))
    console.print()
    _ui_phase_started(ui, "Additional Reports", "Generating supporting report tables")

    if analysis_logger:
        analysis_logger.start_phase(
            "Additional Reports",
            "Generate specialized reports (case streets, borough breakdown, borough priority, tenure segmentation, data quality, subsidy analysis)"
        )

    from src.analysis.additional_reports import AdditionalReports
    from pathlib import Path

    reporter = AdditionalReports()
    reports_created = []

    output_dir = Path(DATA_OUTPUTS_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # 1. Shakespeare Crescent Extract
    try:
        console.print("[cyan]Extracting Shakespeare Crescent data...[/cyan]")
        case_street_path = output_dir / "shakespeare_crescent_extract.csv"
        case_street_df, case_street_summary = reporter.extract_case_street(
            df_validated,
            street_name="Shakespeare Crescent",
            output_path=case_street_path,
            summary_path=output_dir / "shakespeare_crescent_summary.txt",
        )
        if len(case_street_df) > 0:
            reports_created.append(f"✓ Shakespeare Crescent extract ({len(case_street_df)} properties)")
        else:
            console.print("[yellow]  No properties found on Shakespeare Crescent[/yellow]")
    except Exception as e:
        console.print(f"[yellow]⚠ Could not generate case street extract: {e}[/yellow]")
        case_street_df, case_street_summary = None, None

    # 2. Borough-level Breakdown
    try:
        console.print("[cyan]Generating borough-level breakdown...[/cyan]")
        borough_path = output_dir / "borough_breakdown.csv"
        borough_df = reporter.generate_borough_breakdown(
            df_validated,
            output_path=borough_path
        )
        reports_created.append(f"✓ Borough breakdown ({len(borough_df)} boroughs)")
    except Exception as e:
        console.print(f"[yellow]⚠ Could not generate borough breakdown: {e}[/yellow]")
        borough_df = None

    # 2.5 Borough Priority Ranking
    try:
        console.print("[cyan]Generating borough priority ranking...[/cyan]")
        borough_priority_path = reports_dir / "borough_priority_ranking.csv"
        borough_priority_summary_path = reports_dir / "borough_priority_ranking.txt"
        borough_priority_df = reporter.generate_borough_priority_ranking(
            df_validated,
            output_path=borough_priority_path,
            summary_path=borough_priority_summary_path,
            source_label="data/processed/epc_london_adjusted.csv",
        )
        reports_created.append(f"✓ Borough priority ranking ({len(borough_priority_df)} boroughs)")
    except Exception as e:
        console.print(f"[yellow]⚠ Could not generate borough priority ranking: {e}[/yellow]")
        borough_priority_df = None

    # 2.6 Tenure Segmentation
    try:
        console.print("[cyan]Generating tenure segmentation analysis...[/cyan]")
        tenure_segmentation_path = reports_dir / "tenure_segmentation.csv"
        tenure_segmentation_summary_path = reports_dir / "tenure_segmentation.txt"
        tenure_segmentation_df = reporter.generate_tenure_segmentation(
            df_validated,
            output_path=tenure_segmentation_path,
            summary_path=tenure_segmentation_summary_path,
            source_label="data/processed/epc_london_adjusted.csv",
        )
        reports_created.append(f"✓ Tenure segmentation ({len(tenure_segmentation_df)} tenure groups)")
    except Exception as e:
        console.print(f"[yellow]⚠ Could not generate tenure segmentation analysis: {e}[/yellow]")
        tenure_segmentation_df = None

    # 3. Data Quality Report
    try:
        console.print("[cyan]Generating data quality report...[/cyan]")
        quality_path = output_dir / "data_quality_report.txt"
        quality_report = reporter.generate_data_quality_report(
            df_raw,
            df_validated,
            validation_report,
            output_path=quality_path
        )
        reports_created.append("✓ Data quality report")
    except Exception as e:
        console.print(f"[yellow]⚠ Could not generate data quality report: {e}[/yellow]")

    # 4. Subsidy Sensitivity Analysis
    try:
        console.print("[cyan]Running subsidy sensitivity analysis...[/cyan]")
        subsidy_path = output_dir / "subsidy_sensitivity_analysis_simple_gbp.csv"
        reporter.subsidy_sensitivity_analysis(
            df_validated,
            scenario_results,
            subsidy_levels=[0, 5000, 7500, 10000, 15000],
            output_path=subsidy_path
        )
        reports_created.append("✓ Subsidy sensitivity analysis")
    except Exception as e:
        console.print(f"[yellow]⚠ Could not generate subsidy sensitivity: {e}[/yellow]")

    # 5. Heat Network Connection Thresholds
    threshold_df = None
    try:
        console.print("[cyan]Analyzing heat network connection thresholds...[/cyan]")
        threshold_path = output_dir / "heat_network_connection_thresholds.csv"
        if 'heat_network_tier' in df_validated.columns:
            threshold_df = reporter.analyze_heat_network_connection_thresholds(
                df_validated,
                tier_field='heat_network_tier',
                tier_values=['Tier 3: High heat density', 'Tier 4: Medium heat density'],
                output_path=threshold_path
            )
            reports_created.append("✓ Heat network connection threshold analysis")
        else:
            console.print("[yellow]  Heat network tier not found, skipping threshold analysis[/yellow]")
    except Exception as e:
        console.print(f"[yellow]⚠ Could not generate connection thresholds: {e}[/yellow]")
        threshold_df = None

    console.print()
    console.print(f"[green]✓[/green] Additional reports complete!")
    console.print()

    if reports_created:
        console.print("[cyan]Generated reports:[/cyan]")
        for report in reports_created:
            console.print(f"    {report}")

    if analysis_logger:
        analysis_logger.add_metric("additional_reports", len(reports_created), f"{len(reports_created)} specialized reports")
        analysis_logger.add_output("data/outputs/shakespeare_crescent_extract.csv", "csv", "Case street extract")
        analysis_logger.add_output("data/outputs/borough_breakdown.csv", "csv", "Borough-level breakdown")
        analysis_logger.add_output("data/outputs/reports/borough_priority_ranking.csv", "csv", "Borough-level priority ranking")
        analysis_logger.add_output("data/outputs/reports/borough_priority_ranking.txt", "report", "Borough priority ranking summary")
        analysis_logger.add_output("data/outputs/reports/tenure_segmentation.csv", "csv", "Tenure segmentation analysis")
        analysis_logger.add_output("data/outputs/reports/tenure_segmentation.txt", "report", "Tenure segmentation summary")
        analysis_logger.add_output("data/outputs/heat_network_connection_thresholds.csv", "csv", "Heat network connection threshold analysis")
        analysis_logger.add_output("data/outputs/subsidy_sensitivity_analysis_simple_gbp.csv", "csv", "Subsidy sensitivity analysis (simple, GBP levels)")
        analysis_logger.add_output("data/outputs/data_quality_report.txt", "report", "Data quality assessment")
        analysis_logger.complete_phase(success=True, message=f"{len(reports_created)} additional specialized reports generated")

    _ui_metric(ui, "additional reports", len(reports_created), group=PHASE_OUTPUTS)
    _ui_output(ui, "Borough breakdown", "data/outputs/borough_breakdown.csv")
    _ui_output(ui, "Tenure segmentation", "data/outputs/reports/tenure_segmentation.csv")
    _ui_phase_completed(ui, "Additional Reports", f"{len(reports_created)} additional reports generated")
    return {
        "case_street_df": case_street_df,
        "case_street_summary": case_street_summary,
        "borough_breakdown": borough_df,
        "borough_priority_ranking": borough_priority_df,
        "tenure_segmentation": tenure_segmentation_df,
        "heat_network_thresholds": threshold_df,
    }


def package_dashboard_assets(
    archetype_results,
    scenario_results,
    readiness_summary,
    pathway_summary=None,
    additional_reports=None,
    subsidy_results=None,
    df_validated=None,
    analysis_logger: AnalysisLogger = None,
    ui=None,
):
    """Export dashboard JSON data into outputs and the React app.

    This phase consolidates all analysis outputs into a single JSON file
    that addresses all 12 CLIENT_QUESTIONS sections:
    1. Fabric Detail Granularity
    2. Retrofit Measures & Packages
    3. Radiator Upsizing
    4. Window Upgrades (Double vs Triple)
    5. Payback Times
    6. Pathways & Hybrid Scenarios
    7. EPC Data Robustness (Anomalies & Uncertainty)
    8. Fabric Tipping Point Curve
    9. Load Profiles & System Impacts
    10. Heat Network Penetration & Price Sensitivity
    11. Tenure Filtering
    12. Documentation & Tests
    """
    console.print()
    console.print(Panel("[bold]Phase 6: Dashboard Packaging[/bold]", border_style="blue"))
    console.print()
    _ui_phase_started(ui, "Dashboard Packaging", "Exporting dashboard dataset")

    if analysis_logger:
        analysis_logger.start_phase(
            "Dashboard Packaging",
            "Export latest analysis results for the React dashboard",
        )

    try:
        from src.reporting.dashboard_data_builder import DashboardDataBuilder
        import pandas as pd

        builder = DashboardDataBuilder(output_dir=Path(DATA_OUTPUTS_DIR))
        case_summary = (additional_reports or {}).get("case_street_summary") if additional_reports else None
        case_street_df = (additional_reports or {}).get("case_street_df") if additional_reports else None
        borough_breakdown = (additional_reports or {}).get("borough_breakdown") if additional_reports else None
        borough_priority_ranking = (additional_reports or {}).get("borough_priority_ranking") if additional_reports else None
        tenure_segmentation = (additional_reports or {}).get("tenure_segmentation") if additional_reports else None
        heat_network_thresholds = (additional_reports or {}).get("heat_network_thresholds") if additional_reports else None

        # Load additional data files if they exist
        load_profile_summary = None
        tipping_point_curve = None
        retrofit_packages_summary = None
        hn_vs_hp_comparison = None

        outputs_dir = Path(DATA_OUTPUTS_DIR)

        # Load load profiles summary (Section 9)
        load_profiles_file = outputs_dir / "pathway_load_profile_summary.csv"
        if load_profiles_file.exists():
            try:
                load_profile_summary = pd.read_csv(load_profiles_file)
                console.print(f"[green]✓[/green] Loaded load profile summary")
            except Exception as e:
                logger.debug(f"Could not load load profiles: {e}")

        # Load tipping point curve (Section 8)
        tipping_point_file = outputs_dir / "fabric_tipping_point_curve.csv"
        from config.config import get_scenario_policy
        if tipping_point_file.exists() and 'fabric_to_tipping_point' in get_scenario_policy()['publish']:
            try:
                tipping_point_curve = pd.read_csv(tipping_point_file)
                console.print(f"[green]✓[/green] Loaded fabric tipping point curve")
            except Exception as e:
                logger.debug(f"Could not load tipping point curve: {e}")

        # Load retrofit packages summary (Section 2, 3, 5)
        retrofit_packages_file = outputs_dir / "retrofit_packages_summary.csv"
        if retrofit_packages_file.exists():
            try:
                retrofit_packages_summary = pd.read_csv(retrofit_packages_file)
                console.print(f"[green]✓[/green] Loaded retrofit packages summary")
            except Exception as e:
                logger.debug(f"Could not load retrofit packages: {e}")

        comparison_file = outputs_dir / "comparisons" / "hn_vs_hp_comparison.csv"
        if comparison_file.exists():
            try:
                hn_vs_hp_comparison = pd.read_csv(comparison_file)
                console.print(f"[green]✓[/green] Loaded HP vs HN comparison")
            except Exception as e:
                logger.debug(f"Could not load HP vs HN comparison: {e}")

        threshold_file = outputs_dir / "heat_network_connection_thresholds.csv"
        if heat_network_thresholds is None and threshold_file.exists():
            try:
                heat_network_thresholds = pd.read_csv(threshold_file)
                console.print(f"[green]✓[/green] Loaded heat network connection thresholds")
            except Exception as e:
                logger.debug(f"Could not load heat network thresholds: {e}")

        dataset = builder.build_dataset(
            archetype_results,
            scenario_results,
            readiness_summary,
            pathway_summary,
            borough_breakdown,
            borough_priority_ranking,
            tenure_segmentation,
            case_summary,
            case_street_df,
            heat_network_thresholds,
            hn_vs_hp_comparison,
            subsidy_results,
            df_validated,
            load_profile_summary,
            tipping_point_curve,
            retrofit_packages_summary,
        )
        if _active_run_context is not None:
            dataset["runMetadata"] = _active_run_context.to_dict()

        dataset_path = builder.write_dataset(dataset)

        # Copy into dashboard public assets so the React app loads latest data
        # Promotion to public assets is performed only by the final publication
        # transaction after both integrity gates have passed.

        console.print(f"[green]✓[/green] Dashboard data saved to {dataset_path}")

        # Log summary of data arrays included
        data_arrays = [k for k in dataset.keys() if isinstance(dataset.get(k), list) and len(dataset.get(k, [])) > 0]
        console.print(f"[cyan]Data arrays included:[/cyan] {len(data_arrays)}")
        for arr in data_arrays:
            count = len(dataset[arr]) if isinstance(dataset[arr], list) else 1
            console.print(f"    • {arr}: {count} items")

        if analysis_logger:
            analysis_logger.add_output(
                str(dataset_path),
                "json",
                "Dashboard dataset for React UI",
            )
            analysis_logger.add_metric("dashboard_data_arrays", len(data_arrays), "Data arrays in dashboard JSON")
            analysis_logger.complete_phase(success=True, message="Dashboard data exported")
        _ui_metric(ui, "dashboard data arrays", len(data_arrays), group=PHASE_OUTPUTS)
        _ui_output(ui, "Dashboard data", dataset_path)
        _ui_phase_completed(ui, "Dashboard Packaging", "Dashboard data exported")
    except Exception as e:
        _ui_phase_failed(ui, "Dashboard Packaging", f"Dashboard packaging failed: {e}")
        console.print(f"[yellow]⚠ Could not package dashboard: {e}[/yellow]")
        logger.exception("Dashboard packaging error")
        if analysis_logger:
            analysis_logger.complete_phase(success=False, message=f"Error: {e}")
        return False

    return True


def _describe_existing_file(file_path: Path, title: str, include_records: bool = True):
    """Display a panel describing an existing data file."""
    if not file_path.exists():
        return

    try:
        file_size = os.path.getsize(file_path) / (1024 * 1024)  # MB
        mod_time = os.path.getmtime(file_path)
        from datetime import datetime
        mod_date = datetime.fromtimestamp(mod_time).strftime('%Y-%m-%d %H:%M')

        record_line = ""
        if include_records:
            try:
                if file_path.suffix.lower() == ".parquet":
                    record_count = parquet_row_count(file_path)
                else:
                    record_count = max(sum(1 for _ in open(file_path, encoding="utf-8")) - 1, 0)
                record_line = f"Records: ~{record_count:,}\n"
            except Exception as e:
                logger.debug(f"Could not count records in {file_path}: {e}")
        console.print()
        console.print(Panel(
            f"[bold cyan]{title}[/bold cyan]\n\n"
            f"File: {file_path.name}\n"
            f"Size: {file_size:.1f} MB\n"
            f"{record_line}"
            f"Last modified: {mod_date}",
            border_style="green"
        ))
        console.print()
    except Exception as e:
        logger.debug(f"Could not describe file {file_path}: {e}")


def prompt_use_existing_dataframe(
    phase_name: str,
    description: str,
    file_path: Path,
    analysis_logger: AnalysisLogger = None,
    include_records: bool = True,
    sample_start_date: date_cls = None,
    sample_end_date: date_cls = None,
    ui=None,
):
    """
    Ask the user whether to reuse an existing processed dataset.

    Returns a DataFrame if loaded, otherwise None.
    """
    candidate_paths = []
    for candidate in (file_path, file_path.with_suffix(".parquet")):
        if candidate not in candidate_paths and candidate.exists():
            candidate_paths.append(candidate)

    if not candidate_paths:
        return None

    selected_path = candidate_paths[0]
    if sample_start_date and sample_end_date:
        selected_path = None
        for candidate in candidate_paths:
            if sample_window_matches(candidate, sample_start_date, sample_end_date):
                selected_path = candidate
                break
        if selected_path is None:
            checked = ", ".join(path.name for path in candidate_paths)
            console.print(
                f"[yellow]⚠ Existing {description} does not match requested sample window "
                f"{sample_start_date.isoformat()} to {sample_end_date.isoformat()} "
                f"- regenerating (checked: {checked})[/yellow]"
            )
            return None

    if sample_start_date and sample_end_date and not sample_window_matches(selected_path, sample_start_date, sample_end_date):
        console.print(
            f"[yellow]⚠ Existing {description} does not match requested sample window "
            f"{sample_start_date.isoformat()} to {sample_end_date.isoformat()} - regenerating[/yellow]"
        )
        return None

    _describe_existing_file(selected_path, f"Existing {description}", include_records)

    use_existing = True  # Automatically use existing processed datasets

    if not use_existing:
        return None

    if analysis_logger:
        analysis_logger.start_phase(
            phase_name,
            f"Load existing {description} from disk"
        )
    _ui_phase_started(ui, phase_name, f"Loading existing {description}")

    try:
        import pandas as pd

        if selected_path.suffix.lower() == ".parquet":
            df_existing = pd.read_parquet(selected_path)
            output_type = "parquet"
        else:
            df_existing = pd.read_csv(selected_path)
            output_type = "csv"
        console.print(
            f"[green]✓[/green] Loaded existing {description} "
            f"({len(df_existing):,} records) from {selected_path.name}"
        )

        if analysis_logger:
            analysis_logger.add_metric("records_loaded", len(df_existing), f"{description} records loaded from disk")
            add_analysis_output_if_exists(analysis_logger, selected_path, output_type, f"Existing {description}")
            analysis_logger.complete_phase(success=True, message=f"Loaded existing {description}")

        _ui_metric(ui, "records loaded", len(df_existing), group=PHASE_ACQUISITION)
        _ui_output(ui, f"Existing {description}", selected_path)
        _ui_phase_completed(ui, phase_name, f"Loaded existing {description}")
        return df_existing
    except Exception as e:
        console.print(f"[yellow]⚠ Could not load existing {description}: {e}[/yellow]")
        _ui_phase_failed(ui, phase_name, f"Failed to load existing {description}: {e}")
        logger.exception(f"Failed to load existing {description}")
        if analysis_logger and analysis_logger.current_phase:
            analysis_logger.complete_phase(success=False, message=f"Failed to load existing {description}: {e}")
        return None


def load_json_if_exists(file_path: Path):
    """Load a JSON file if it exists, otherwise return None."""
    if not file_path.exists():
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.debug(f"Could not load JSON from {file_path}: {e}")
        return None


def check_existing_data(sample_start_date: date_cls = None, sample_end_date: date_cls = None):
    """Check if previously downloaded data exists."""
    raw_csv = DATA_RAW_DIR / "epc_london_raw.csv"
    filtered_csv = DATA_RAW_DIR / "epc_london_filtered.csv"

    def _matches(file_path: Path) -> bool:
        if sample_start_date and sample_end_date:
            return sample_window_matches(file_path, sample_start_date, sample_end_date)
        return True

    if raw_csv.exists() or filtered_csv.exists():
        # Get file info
        if filtered_csv.exists() and _matches(filtered_csv):
            import os
            file_size = os.path.getsize(filtered_csv) / (1024 * 1024)  # MB
            mod_time = os.path.getmtime(filtered_csv)
            from datetime import datetime
            mod_date = datetime.fromtimestamp(mod_time).strftime('%Y-%m-%d %H:%M')

            # Quick count of records
            import pandas as pd
            try:
                header_df = pd.read_csv(filtered_csv, nrows=0)
                missing_columns = EPCAPIDownloader.get_missing_stock_definition_columns(header_df)
                if missing_columns:
                    missing = ", ".join(missing_columns)
                    console.print()
                    console.print(Panel(
                        f"[bold yellow]Existing Filtered Data Ignored[/bold yellow]\n\n"
                        f"File: epc_london_filtered.csv\n"
                        f"Reason: missing stock-definition columns ({missing})\n"
                        f"A fresh full-load download is required to rebuild the London pre-1930 terraced house subset.",
                        border_style="yellow"
                    ))
                    console.print()
                    return False, None, 0
                line_count = sum(1 for _ in open(filtered_csv)) - 1  # Subtract header

                console.print()
                console.print(Panel(
                    f"[bold cyan]Existing Data Found[/bold cyan]\n\n"
                    f"File: epc_london_filtered.csv\n"
                    f"Size: {file_size:.1f} MB\n"
                    f"Records: ~{line_count:,} London pre-1930 terraced house records\n"
                    f"Last modified: {mod_date}",
                    border_style="green"
                ))
                console.print()

                return True, filtered_csv, line_count
            except Exception as e:
                logger.debug(f"Could not read existing data: {e}")
                return False, None, 0

        elif raw_csv.exists() and _matches(raw_csv):
            import os
            file_size = os.path.getsize(raw_csv) / (1024 * 1024)
            mod_time = os.path.getmtime(raw_csv)
            from datetime import datetime
            mod_date = datetime.fromtimestamp(mod_time).strftime('%Y-%m-%d %H:%M')

            console.print()
            console.print(Panel(
                f"[bold cyan]Existing Data Found[/bold cyan]\n\n"
                f"File: epc_london_raw.csv\n"
                f"Size: {file_size:.1f} MB\n"
                f"Dataset: London house records before pre-1930 terraced filtering\n"
                f"Last modified: {mod_date}",
                border_style="green"
            ))
            console.print()

            return True, raw_csv, 0

        elif filtered_csv.exists() or raw_csv.exists():
            console.print()
            console.print(Panel(
                f"[bold yellow]Existing Data Ignored[/bold yellow]\n\n"
                f"Stored data does not match the requested sample window:\n"
                f"{sample_start_date.isoformat()} to {sample_end_date.isoformat()}",
                border_style="yellow"
            ))
            console.print()

    return False, None, 0


def resolve_sample_window_from_args(args: argparse.Namespace, ui=None) -> Tuple[date_cls, date_cls]:
    """Resolve CLI sample dates or fall back to the interactive prompt."""
    if args.sample_start or args.sample_end:
        sample_end_date = args.sample_end or (date_cls.today() - timedelta(days=1))
        sample_start_date = args.sample_start or compute_sample_start_date(sample_end_date)
        if sample_start_date > sample_end_date:
            raise ValueError(
                f"Sample start date {sample_start_date.isoformat()} cannot be after "
                f"sample end date {sample_end_date.isoformat()}"
            )
        _ui_metric(ui, "sample start date", sample_start_date.isoformat(), group=PHASE_ACQUISITION)
        _ui_metric(ui, "sample end date", sample_end_date.isoformat(), group=PHASE_ACQUISITION)
        return sample_start_date, sample_end_date
    return _call_with_optional_ui(prompt_sample_window, ui=ui)


def resolve_one_stop_only(config: Optional[Dict[str, Any]], args: argparse.Namespace) -> bool:
    """Apply report-mode CLI overrides without editing config files."""
    if args.one_stop_only:
        return True
    if args.full_reports:
        return False
    return is_one_stop_only(config)


def open_results_folder() -> None:
    """Open the outputs folder with the platform file manager."""
    if platform.system() == 'Windows':
        subprocess.run(['explorer', 'data\\outputs'], check=False)
    elif platform.system() == 'Darwin':
        subprocess.run(['open', 'data/outputs'], check=False)
    else:
        subprocess.run(['xdg-open', 'data/outputs'], check=False)


def load_existing_data(file_path, analysis_logger: AnalysisLogger = None, ui=None):
    """Load previously downloaded data from file."""
    console.print()
    console.print(Panel("[bold]Phase 1: Loading Existing Data[/bold]", border_style="blue"))
    console.print()
    _ui_phase_started(ui, "Loading Existing Data", "Loading previously downloaded EPC data")

    if analysis_logger:
        analysis_logger.start_phase(
            "Loading Existing Data",
            "Load previously downloaded EPC data from file"
        )

    dataset_label = (
        "London pre-1930 terraced house data"
        if file_path.name == "epc_london_filtered.csv"
        else "London house data"
    )
    console.print(f"[cyan]Loading {dataset_label} from {file_path.name}...[/cyan]")

    import pandas as pd
    df = pd.read_csv(file_path)

    console.print(f"[green]✓[/green] Loaded {len(df):,} records")

    if analysis_logger:
        analysis_logger.add_metric("records_loaded", len(df), "Records loaded from existing file")
        analysis_logger.add_output(str(file_path), "csv", "Existing EPC data loaded")
        analysis_logger.complete_phase(success=True, message=f"Loaded {len(df):,} existing records")

    _ui_metric(ui, "records loaded", len(df), group=PHASE_ACQUISITION)
    _ui_output(ui, "Existing EPC data", file_path)
    _ui_phase_completed(ui, "Loading Existing Data", f"Loaded {len(df):,} existing records")
    return df


def main(argv=None):
    """Main execution function."""
    # Staged-safe mainline checks live in _main_impl:
    # dataset_is_empty(df), ensure_dataframe(df_adjusted)
    args = parse_args([] if argv is None else argv)
    ui = create_dashboard(args, console=console, env=os.environ)

    # Textual mode: run the Textual app in the main thread, pipeline in bg
    try:
        from src.ui.textual_app import TextualUIAdapter, run_with_textual, _TEXTUAL_AVAILABLE
        if isinstance(ui, TextualUIAdapter) and _TEXTUAL_AVAILABLE:
            return _run_with_textual_main(args, ui)
    except ImportError:
        pass

    # Non-Textual mode: run pipeline in main thread as before
    ui.start()
    analysis_logger = AnalysisLogger()
    start_time = time.time()
    try:
        with _configure_tui_logging(ui), _route_console_output_for_tui(ui):
            _ui_call(ui, "run_started", "HeatStreet analysis started")
            print_header()
            exit_code = _main_impl(args, ui, analysis_logger, start_time)
            if exit_code == EXIT_ANALYSIS_FAILED:
                _mark_active_run_failed()
                if hasattr(analysis_logger, "record_failure"):
                    analysis_logger.record_failure(
                        RuntimeError("Analysis terminated before required phases completed")
                    )
            return exit_code
    except Exception as exc:
        _mark_active_run_failed()
        if hasattr(analysis_logger, "record_failure"):
            analysis_logger.record_failure(exc)
        _ui_call(ui, "run_failed", str(exc))
        return EXIT_ANALYSIS_FAILED
    finally:
        _ui_call(ui, "stop")
        _restore_run_directories()


def _run_with_textual_main(args: argparse.Namespace, ui) -> int:
    """Run the pipeline in a background thread while Textual app is in main."""
    import threading
    from src.ui.textual_app import HeatStreetStudioApp

    result: Dict[str, Any] = {"exit_code": EXIT_SUCCESS}

    def _pipeline_thread_fn() -> None:
        analysis_logger = AnalysisLogger()
        start_time = time.time()
        try:
            with _configure_tui_logging(ui), _route_console_output_for_tui(ui):
                _ui_call(ui, "run_started", "HeatStreet analysis started")
                print_header()
                code = _main_impl(args, ui, analysis_logger, start_time)
                result["exit_code"] = code or EXIT_SUCCESS
                if code == EXIT_ANALYSIS_FAILED:
                    _mark_active_run_failed()
                    if hasattr(analysis_logger, "record_failure"):
                        analysis_logger.record_failure(
                            RuntimeError("Analysis terminated before required phases completed")
                        )
        except SystemExit as e:
            result["exit_code"] = e.code or EXIT_SUCCESS
        except KeyboardInterrupt:
            result["exit_code"] = EXIT_CANCELLED
        except Exception as exc:
            _mark_active_run_failed()
            if hasattr(analysis_logger, "record_failure"):
                analysis_logger.record_failure(exc)
            _ui_call(ui, "run_failed", str(exc))
            result["exit_code"] = EXIT_ANALYSIS_FAILED
        finally:
            _ui_call(ui, "stop")
            _restore_run_directories()

    pipeline_thread = threading.Thread(
        target=_pipeline_thread_fn, daemon=True, name="hs-pipeline"
    )
    pipeline_thread.start()

    app = HeatStreetStudioApp(
        state=ui.state,
        event_queue=ui._event_queue,
        cancel_event=ui._cancel_event,
        prompt_request_queue=ui._prompt_request_queue,
        prompt_response_queue=ui._prompt_response_queue,
    )
    ui._app = app
    try:
        app.run()
    except Exception:
        pass
    finally:
        ui._cancel_event.set()
        ui._prompt_response_queue.put_nowait(None)

    pipeline_thread.join(timeout=60)
    return result.get("exit_code", EXIT_SUCCESS)


def _main_impl(args: argparse.Namespace, ui, analysis_logger: AnalysisLogger, start_time: float):
    """Run the pipeline after argparse/UI setup."""
    global _active_run_context, _active_authoritative_cohort_size, _hp_hn_comparison_outputs_cache

    _active_run_context = None
    _active_authoritative_cohort_size = None
    _hp_hn_comparison_outputs_cache = None
    config_path = REPO_ROOT / "config" / "config.yaml"
    config_sha256 = hashlib.sha256(config_path.read_bytes()).hexdigest()
    git_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    ).stdout.strip() or None
    pending_run_context = RunContext.create(
        mode="production" if args.production else "development",
        git_commit=git_commit,
        configuration_sha256=config_sha256,
        source_identifier=args.source_run_id if args.development_fixture else None,
        source_fingerprint=args.source_fixture_sha256 if args.development_fixture else None,
    )
    run_root = Path(DATA_OUTPUTS_DIR).parent / "runs" / pending_run_context.run_id
    pending_run_context = pending_run_context.with_run_root(run_root)
    analysis_logger.set_metadata("run_id", pending_run_context.run_id)
    analysis_logger.set_metadata("git_commit", pending_run_context.git_commit)
    analysis_logger.set_metadata("configuration_sha256", pending_run_context.configuration_sha256)
    analysis_logger.set_metadata("source_identifier", pending_run_context.source_identifier)
    analysis_logger.set_metadata("source_fingerprint", pending_run_context.source_fingerprint)
    _configure_run_directories(
        pending_run_context,
        analysis_logger,
        isolate_processed=True,
    )
    _checkpoint(analysis_logger, status="running")

    runtime_identity, preflight = emit_startup_diagnostics(analysis_logger)
    if not preflight.get("ok"):
        analysis_logger.set_metadata(
            "startup_failure",
            "Startup preflight failed before prompts or Phase 1.",
        )
        log_path = save_startup_failure_log(analysis_logger)
        if log_path:
            console.print(f"[yellow]Startup diagnostics log saved to:[/yellow] {log_path}")
            console.print()
        _ui_call(ui, "run_failed", "Startup preflight failed")
        return EXIT_ANALYSIS_FAILED
    _ui_info(ui, "Preflight passed")

    # Check credentials
    if not args.development_fixture and not _call_with_optional_ui(check_credentials, ui=ui):
        console.print("[red]Cannot proceed without API credentials[/red]")
        _ui_call(ui, "run_failed", "API credentials missing")
        return EXIT_ANALYSIS_FAILED

    console.print("[green]✓[/green] API credentials configured")
    console.print()

    # Ensure directories exist
    ensure_directories()

    config = load_config()
    one_stop_only = resolve_one_stop_only(config, args)

    console.print("[green]✓[/green] Analysis logger initialized")
    console.print()

    # Ask about heat network data downloads
    # HNPD first (recommended, 2024 data)
    if not args.development_fixture:
        _call_with_optional_ui(ask_hnpd_download, ui=ui)

    try:
        sample_start_date, sample_end_date = resolve_sample_window_from_args(args, ui=ui)
    except KeyboardInterrupt:
        console.print("[yellow]Analysis cancelled by user[/yellow]")
        _ui_call(ui, "run_failed", "Analysis cancelled by user")
        return EXIT_CANCELLED
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        _ui_call(ui, "run_failed", str(e))
        return EXIT_ANALYSIS_FAILED

    analysis_logger.set_metadata("sample_start_date", sample_start_date.isoformat())
    analysis_logger.set_metadata("sample_end_date", sample_end_date.isoformat())
    pending_run_context = replace(
        pending_run_context,
        sample_start_date=sample_start_date.isoformat(),
        sample_end_date=sample_end_date.isoformat(),
    )

    fixture_mode = args.development_fixture is not None
    fixture_validation_report = None
    fixture_frame = None
    if fixture_mode:
        import pandas as pd

        fixture_path = Path(args.development_fixture)
        if not fixture_path.is_file():
            raise FileNotFoundError(f"Development fixture not found: {fixture_path}")
        actual_sha = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
        if actual_sha.casefold() != args.source_fixture_sha256.casefold():
            raise RuntimeError(
                f"Development fixture SHA-256 mismatch: {actual_sha}, expected {args.source_fixture_sha256}"
            )
        fixture_frame = pd.read_parquet(fixture_path)
        if len(fixture_frame) != 168_051:
            raise RuntimeError(f"Development fixture row-count mismatch: {len(fixture_frame):,}, expected 168,051")
        validator = EPCDataValidator(strict_schema_conflicts=False)
        canonical_fixture_columns = {"CURRENT_ENERGY_RATING", "TOTAL_FLOOR_AREA"}
        if not canonical_fixture_columns.issubset(fixture_frame.columns):
            fixture_frame = validator._standardize_column_names(fixture_frame)
            fixture_frame = validator.standardize_fields(fixture_frame)
        validated_fixture_path = Path(DATA_PROCESSED_DIR) / "epc_london_validated.parquet"
        fixture_frame.to_parquet(validated_fixture_path, index=False)
        fixture_geocoding_cache = fixture_path.parent / "geocoding_cache.csv"
        if fixture_geocoding_cache.is_file():
            cache_frame = pd.read_csv(fixture_geocoding_cache)
            required_cache_columns = {"postcode", "latitude", "longitude"}
            if required_cache_columns.issubset(cache_frame.columns) and not cache_frame.empty:
                run_cache_path = Path(DATA_PROCESSED_DIR) / "geocoding_cache.csv"
                shutil.copy2(fixture_geocoding_cache, run_cache_path)
                analysis_logger.set_metadata(
                    "fixture_geocoding_cache_sha256",
                    hashlib.sha256(fixture_geocoding_cache.read_bytes()).hexdigest(),
                )
                analysis_logger.set_metadata("fixture_geocoding_cache_rows", len(cache_frame))
        fixture_validation_report = {
            "total_records": 183_376,
            "stock_filtered_records": 183_376,
            "records_passed": 168_051,
            "duplicates_removed": 14_432,
            "invalid_records": 893,
            "staged_london_house_records": 732_887,
            "heating_controls_schema": validator.validation_report.get("heating_controls_schema", {}),
            "fixture_source_run_id": args.source_run_id,
            "fixture_sha256": actual_sha,
        }
        write_json_report(Path(DATA_PROCESSED_DIR) / "validation_report.json", fixture_validation_report)
        console.print(f"[green]OK[/green] Verified development fixture: {len(fixture_frame):,} rows")

    # Check for existing data
    if fixture_mode:
        has_existing, existing_file, record_count = False, None, len(fixture_frame)
    else:
        has_existing, existing_file, record_count = check_existing_data(
            sample_start_date=sample_start_date,
            sample_end_date=sample_end_date,
        )

    df = fixture_frame
    fresh_data_downloaded = fixture_mode  # Track if we just downloaded new data

    if args.use_existing and not has_existing:
        console.print("[red]No matching existing data found for --use-existing[/red]")
        _ui_call(ui, "run_failed", "No matching existing data found for --use-existing")
        return EXIT_ANALYSIS_FAILED

    if has_existing:
        if args.fresh:
            use_existing = False
        elif args.use_existing:
            use_existing = True
        else:
            # Ask user whether to use existing data or download new
            tui_choice = _tui_prompt(
                ui, "select",
                title="Existing data found",
                message="Existing data found. What would you like to do?",
                choices=[True, False],
                labels=["Use existing data", "Download new data (will overwrite existing)"],
            )
            if tui_choice is not None:
                use_existing = tui_choice
            else:
                with _ui_suspend(ui, "Waiting for existing-data decision"):
                    use_existing = questionary.select(
                        "Existing data found. What would you like to do?",
                        choices=[
                            questionary.Choice("Use existing data", value=True),
                            questionary.Choice("Download new data (will overwrite existing)", value=False),
                        ],
                    ).ask()

        if use_existing is None:
            console.print("[yellow]Analysis cancelled by user[/yellow]")
            _ui_call(ui, "run_failed", "Analysis cancelled by user")
            return EXIT_CANCELLED

        if use_existing:
            df = _call_with_optional_ui(load_existing_data, existing_file, analysis_logger, ui=ui)
        else:
            console.print()
            console.print("[yellow]Downloading new data (existing data will be overwritten)...[/yellow]")
            console.print()
            fresh_data_downloaded = True  # Flag that we're downloading fresh data

    # If not using existing data, download new
    if df is None or dataset_is_empty(df):
        fresh_data_downloaded = True  # Flag that we're downloading fresh data

        # Show summary
        console.print()
        console.print(Panel(
            f"[bold]Analysis Configuration[/bold]\n\n"
            f"Mode: full\n"
            f"Sample start date: {sample_start_date.isoformat()}\n"
            f"Sample end date: {sample_end_date.isoformat()}",
            border_style="cyan"
        ))
        console.print()

        proceed = True  # Automatically proceed with download

        if not proceed:
            console.print("[yellow]Analysis cancelled[/yellow]")
            return EXIT_CANCELLED

        # Run pipeline
        start_time = time.time()

        # Phase 1: Download
        try:
            df = _call_with_optional_ui(
                download_data,
                analysis_logger,
                sample_start_date=sample_start_date,
                sample_end_date=sample_end_date,
                download_scope=args.download_scope,
                borough=args.borough,
                ui=ui,
            )
        except AnalysisCancelled as e:
            _ui_call(ui, "run_failed", str(e))
            console.print(f"[yellow]{e}[/yellow]")
            return EXIT_CANCELLED
        if df is None or dataset_is_empty(df):
            _ui_call(ui, "run_failed", "Analysis stopped - no data available")
            console.print("[red]✗ Analysis stopped - no data available[/red]")
            return EXIT_ANALYSIS_FAILED
        gc.collect()  # Cleanup API response objects
    else:
        start_time = time.time()
        console.print()
        console.print("[cyan]Proceeding with existing data...[/cyan]")
        console.print()

    df_raw = df if is_dataset_reference(df) else df.copy()

    # Phase 2: Check for existing validated data before running validation
    # If we just downloaded fresh data, force re-validation instead of using old validated data
    validated_path = DATA_PROCESSED_DIR / "epc_london_validated.csv"
    df_validated = fixture_frame if fixture_mode else None
    if not fresh_data_downloaded:
        df_validated = _call_with_optional_ui(
            prompt_use_existing_dataframe,
            "Data Validation",
            "validated EPC dataset",
            validated_path,
            analysis_logger,
            sample_start_date=sample_start_date,
            sample_end_date=sample_end_date,
            ui=ui,
        )
    validation_report = fixture_validation_report

    if df_validated is not None:
        validation_report = load_json_if_exists(DATA_PROCESSED_DIR / "validation_report.json")
        if validation_report:
            console.print("[cyan]Loaded validation report from previous run[/cyan]")
        else:
            console.print("[yellow]⚠ Validation report JSON not found; generating from validated data...[/yellow]")
            validation_report = normalize_validation_report(
                {
                    "duplicates_removed": 0,  # Unknown from pre-validated data
                    "negative_energy_values": 0,  # Unknown
                    "negative_co2_values": 0,  # Unknown
                    "note": "Generated retroactively from validated dataset",
                },
                input_dataset=df,
                validated_dataset=df_validated,
            )
            # Save it for future use
            try:
                validation_report_path = DATA_PROCESSED_DIR / "validation_report.json"
                write_json_report(validation_report_path, validation_report)
                console.print(
                    f"[green]✓ Created validation_report.json with "
                    f"{validation_report['records_passed']:,} valid records[/green]"
                )
            except Exception as e:
                logger.warning(f"Could not save validation report: {e}")
    else:
        # Phase 2: Validate
        df_validated, validation_report = _call_with_optional_ui(
            validate_data,
            df,
            analysis_logger,
            sample_start_date=sample_start_date,
            sample_end_date=sample_end_date,
            strict_schema_conflicts=args.production,
            ui=ui,
        )
        # Cleanup raw dataframe since we now use df_validated
        if not is_dataset_reference(df):
            del df
        gc.collect()

    # Set metadata
    analysis_logger.set_metadata("total_properties", dataset_record_count(df_validated))

    if dataset_is_empty(df_validated):
        _ui_call(ui, "run_failed", "Analysis stopped - no valid data")
        console.print("[red]✗ Analysis stopped - no valid data[/red]")
        return EXIT_ANALYSIS_FAILED

    # Phase 2.5: Methodological Adjustments (check for existing adjusted data)
    # If we just downloaded fresh data, force re-adjustment instead of using old adjusted data
    adjusted_path = DATA_PROCESSED_DIR / "epc_london_adjusted.csv"
    df_adjusted = None
    if not fresh_data_downloaded:
        df_adjusted = _call_with_optional_ui(
            prompt_use_existing_dataframe,
            "Methodological Adjustments",
            "methodologically adjusted dataset",
            adjusted_path,
            analysis_logger,
            sample_start_date=sample_start_date,
            sample_end_date=sample_end_date,
            ui=ui,
        )
    adjustment_summary = None
    if df_adjusted is not None:
        adjustment_summary = load_json_if_exists(DATA_PROCESSED_DIR / "methodological_adjustments_summary.json")
        if adjustment_summary:
            console.print("[cyan]Loaded methodological adjustment summary from previous run[/cyan]")
        else:
            console.print("[yellow]⚠ Adjustment summary JSON not found; proceeding without it[/yellow]")
    else:
        df_adjusted, adjustment_summary = _call_with_optional_ui(
            apply_methodological_adjustments,
            df_validated,
            analysis_logger,
            sample_start_date=sample_start_date,
            sample_end_date=sample_end_date,
            ui=ui,
        )
        # Cleanup pre-adjustment dataframe since we now use df_adjusted
        if 'df_validated' in locals() and df_validated is not df_adjusted:
            del df_validated
        gc.collect()

    try:
        df_adjusted_frame = ensure_dataframe(df_adjusted, stage_name="adjusted EPC dataset", ui=ui)
    except RuntimeError as e:
        _ui_call(ui, "run_failed", str(e))
        console.print(f"[red]x[/red] {e}")
        return EXIT_ANALYSIS_FAILED

    authoritative_adjusted_path = Path(DATA_PROCESSED_DIR) / "epc_london_adjusted.parquet"
    if not authoritative_adjusted_path.is_file():
        authoritative_adjusted_path.parent.mkdir(parents=True, exist_ok=True)
        df_adjusted_frame.to_parquet(authoritative_adjusted_path, index=False)

    dataset_fingerprint = fingerprint_dataset(df_adjusted_frame)
    if not pending_run_context.source_fingerprint:
        pending_run_context = replace(
            pending_run_context,
            source_identifier=(
                str(df_raw.parquet_path) if isinstance(df_raw, DatasetReference) else "epc_acquisition_dataframe"
            ),
            source_fingerprint=fingerprint_dataset(df_raw),
        )
    current_run_context = pending_run_context.with_dataset_fingerprint(dataset_fingerprint).with_cohort(len(df_adjusted_frame))
    analysis_logger.set_metadata("dataset_fingerprint", dataset_fingerprint)
    analysis_logger.set_metadata("authoritative_cohort_size", len(df_adjusted_frame))
    _active_run_context = current_run_context
    _active_authoritative_cohort_size = len(df_adjusted_frame)
    _write_current_run_metadata(
        analysis_logger,
        _active_run_context,
        _active_authoritative_cohort_size,
    )

    # Phase 3: Analyze (use adjusted data)
    archetype_results = _call_with_optional_ui(analyze_archetype, df_adjusted_frame, analysis_logger, ui=ui)
    gc.collect()  # Cleanup analysis intermediate results

    # Build the diagnostic model family before the much larger stock-scenario
    # property table is retained in memory.
    diagnostic_outputs = _call_with_optional_ui(
        ensure_hp_hn_comparison_outputs,
        df_adjusted_frame,
        analysis_logger,
        ui=ui,
    )
    if diagnostic_outputs is None:
        raise RuntimeError("Diagnostic pathway phase failed to produce its required comparison artifacts")
    gc.collect()

    # Each memory-intensive phase starts from the authoritative persisted boundary.
    scenario_frame = _load_adjusted_phase_frame("Scenario Modeling")
    scenario_results, subsidy_results = _call_with_optional_ui(
        model_scenarios, scenario_frame, analysis_logger, ui=ui
    )
    del scenario_frame
    _register_required_artifacts(
        _active_run_context,
        phase="scenario_modeling",
        artifacts=[
            ("internal_scenarios", Path(DATA_OUTPUTS_DIR) / "internal_scenario_results.csv", "internal"),
            ("client_scenarios", Path(DATA_OUTPUTS_DIR) / "scenario_results_summary.csv", "client"),
        ],
    )
    from config.config import get_scenario_policy
    published_scenarios = set(get_scenario_policy()["publish"])
    client_scenario_results = {
        scenario_id: result
        for scenario_id, result in (scenario_results or {}).items()
        if scenario_id in published_scenarios
    }
    gc.collect()  # Major cleanup after expensive modeling phase

    # Phase 4.3: Retrofit Readiness
    readiness_frame = _load_adjusted_phase_frame("Retrofit Readiness Analysis")
    df_readiness, readiness_summary = _call_with_optional_ui(
        analyze_retrofit_readiness,
        readiness_frame,
        analysis_logger,
        one_stop_only=one_stop_only,
        ui=ui,
    )
    del readiness_frame
    if df_readiness is None or readiness_summary is None:
        raise RuntimeError("Retrofit readiness did not produce its required artifacts")
    _require_contract(ArtifactManifest.load(_active_run_context), ["readiness", "readiness_summary"])
    gc.collect()  # Cleanup readiness calculation intermediates

    # Phase 4.5: Required spatial classification (maps remain optional).
    spatial_frame = _load_adjusted_phase_frame("Spatial Analysis")
    properties_with_tiers, pathway_summary = _call_with_optional_ui(
        run_spatial_analysis,
        spatial_frame,
        analysis_logger,
        one_stop_only=one_stop_only,
        ui=ui,
    )
    del spatial_frame
    if properties_with_tiers is None or pathway_summary is None:
        raise RuntimeError("Spatial analysis did not produce its required classification artifact")
    spatial_path = Path(DATA_OUTPUTS_DIR) / "pathway_suitability_by_tier.csv"
    spatial_manifest = _register_required_artifacts(
        _active_run_context,
        phase="spatial_analysis",
        artifacts=[("spatial_suitability", spatial_path, "client")],
    )
    gc.collect()  # Cleanup GIS objects and geocoding cache

    # Phase 5.5: Additional reports and supporting tables
    try:
        df_raw_for_reports = ensure_dataframe(df_raw, stage_name="raw EPC dataset for reporting", ui=ui)
    except RuntimeError as e:
        console.print(f"[yellow]âš  Could not materialize raw dataset for additional reports: {e}[/yellow]")
        df_raw_for_reports = df_adjusted_frame

    spatial_reporting_frame = df_adjusted_frame.copy(deep=False)
    if (
        hasattr(properties_with_tiers, "columns")
        and "heat_network_tier" in properties_with_tiers.columns
        and len(properties_with_tiers) == len(df_adjusted_frame)
    ):
        # Carry only the spatial classification into the canonical analytical
        # frame; GeoDataFrame conversion can alter categorical report columns.
        spatial_reporting_frame = spatial_reporting_frame.assign(
            heat_network_tier=properties_with_tiers["heat_network_tier"].to_numpy()
        )
    additional_outputs = _call_with_optional_ui(
        generate_additional_reports,
        df_raw_for_reports,
        spatial_reporting_frame,
        validation_report,
        archetype_results,
        client_scenario_results,
        analysis_logger,
        ui=ui,
    )

    # Freeze the reporting provenance before any client artifact is built.
    _active_run_context = _active_run_context.with_timing(
        runtime_seconds=time.time() - start_time,
    )
    analysis_logger.set_metadata("analysis_end", _active_run_context.analysis_end)
    analysis_logger.set_metadata("total_duration_seconds", _active_run_context.runtime_seconds)
    analysis_logger.set_metadata("source_identifier", _active_run_context.source_identifier)
    analysis_logger.set_metadata("source_fingerprint", _active_run_context.source_fingerprint)
    _write_current_run_metadata(
        analysis_logger,
        _active_run_context,
        int(_active_authoritative_cohort_size),
    )

    # Phase 5: Report
    if one_stop_only:
        _call_with_optional_ui(generate_one_stop_report, df_adjusted_frame, analysis_logger, ui=ui)
        gc.collect()  # Cleanup report generation objects
    else:
        _call_with_optional_ui(
            generate_reports,
            archetype_results,
            client_scenario_results,
            subsidy_results,
            df_adjusted_frame,
            pathway_summary,
            analysis_logger,
            ui=ui,
            one_stop_only=one_stop_only,
        )
        gc.collect()  # Cleanup matplotlib figures and Excel writer objects
        _call_with_optional_ui(generate_one_stop_report, df_adjusted_frame, analysis_logger, ui=ui)

    # Phase 6: Package dashboard
    _call_with_optional_ui(
        package_dashboard_assets,
        archetype_results,
        client_scenario_results,
        readiness_summary,
        pathway_summary,
        additional_outputs,
        subsidy_results,
        df_adjusted_frame,
        analysis_logger,
        ui=ui,
    )
    gc.collect()  # Final cleanup after dashboard packaging

    # Complete
    elapsed = time.time() - start_time

    # Save analysis log
    console.print()
    console.print("[cyan]Saving analysis log...[/cyan]")
    log_path = analysis_logger.save_log()
    if _active_run_context is not None:
        _write_current_run_metadata(
            analysis_logger,
            _active_run_context,
            int(_active_authoritative_cohort_size),
        )
        stamp_artifact_tree([Path(DATA_OUTPUTS_DIR)], _active_run_context)

    # Generated reports are authoritative. The repair utility is intentionally
    # excluded from normal execution and remains available only as an explicit tool.

    # Generate a lightweight, self-contained HTML dashboard from the one-stop JSON output.
    try:
        from src.reporting.one_stop_html_dashboard import build_one_stop_html_dashboard

        dashboard_path = build_one_stop_html_dashboard(Path(DATA_OUTPUTS_DIR))
        if dashboard_path:
            console.print(f"[green]✓[/green] One-stop HTML dashboard generated: {dashboard_path}")
            if analysis_logger:
                analysis_logger.add_output(
                    "data/outputs/one_stop_dashboard.html",
                    "html",
                    "One-stop HTML dashboard (self-contained)",
                )
    except Exception as e:
        logger.warning(f"Could not generate one-stop HTML dashboard: {e}")

    if _active_run_context is not None:
        stamp_artifact_tree(
            [Path(DATA_OUTPUTS_DIR), Path(DATA_PROCESSED_DIR)],
            _active_run_context,
        )
        final_manifest = _register_current_artifacts(_active_run_context)
        _require_contract(
            final_manifest,
            [
                "published_validation_report", "one_stop_json", "dashboard_data",
                "dashboard_html", "analysis_compendium",
            ],
        )
        _active_run_context = _active_run_context.finalize(
            analysis_end=_active_run_context.analysis_end,
            runtime_seconds=float(_active_run_context.runtime_seconds),
        )
        _active_run_context.validate_production_report()
        _write_current_run_metadata(
            analysis_logger,
            _active_run_context,
            int(_active_authoritative_cohort_size),
        )
        stamp_artifact_tree(
            [Path(DATA_OUTPUTS_DIR), Path(DATA_PROCESSED_DIR)],
            _active_run_context,
        )
        _register_current_artifacts(_active_run_context)

    if _active_run_context is not None and args.production and not args.no_publish:
        stamp_artifact_tree([Path(DATA_OUTPUTS_DIR)], _active_run_context)
        publish_run_outputs(
            Path(DATA_OUTPUTS_DIR),
            Path(_public_outputs_dir),
            _active_run_context.run_id,
        )
        dashboard_candidate = Path(DATA_OUTPUTS_DIR) / "dashboard" / "dashboard-data.json"
        dashboard_public = REPO_ROOT / "dashboard" / "public" / "dashboard-data.json"
        dashboard_temp = dashboard_public.with_suffix(".json.publish-tmp")
        dashboard_temp.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dashboard_candidate, dashboard_temp)
        os.replace(dashboard_temp, dashboard_public)
        console.print(f"[green]OK[/green] Published validated run to: {_public_outputs_dir}")
    elif _active_run_context is not None:
        console.print(f"[cyan]Run retained without publication: {_active_run_context.run_root}[/cyan]")
    _checkpoint(analysis_logger, status="complete")
    console.print(f"[green]✓[/green] Analysis log saved to: {log_path}")
    combined_workbook = analysis_logger.metadata.get('combined_workbook')
    if combined_workbook:
        console.print(f"[green]✓[/green] Combined outputs workbook saved to: {combined_workbook}")

    # Show summary statistics
    summary_stats = analysis_logger.get_summary_stats()
    console.print()
    console.print(f"[cyan]Analysis Summary:[/cyan]")
    console.print(f"  • Total phases: {summary_stats['total_phases']}")
    console.print(f"  • Successful: {summary_stats['successful_phases']}")
    console.print(f"  • Failed: {summary_stats['failed_phases']}")
    console.print(f"  • Skipped: {summary_stats['skipped_phases']}")

    console.print()
    outputs_label = "one_stop_output.json (one-stop report)" if one_stop_only else "reports and charts"

    console.print(Panel.fit(
        f"[bold green]✓ Analysis Complete![/bold green]\n\n"
        f"Time elapsed: {elapsed/60:.1f} minutes\n"
        f"Properties analyzed: {len(df_adjusted_frame):,}\n\n"
        f"[cyan]Results saved to:[/cyan]\n"
        f"  • data/processed/ (validated data)\n"
        f"  • data/outputs/ ({outputs_label})\n"
        f"  • data/outputs/analysis_log.txt (analysis log)\n"
        f"  • data/outputs/analysis_outputs_compendium.xlsx (combined workbook)",
        border_style="green"
    ))
    console.print()

    _ui_call(
        ui,
        "run_completed",
        elapsed=elapsed,
        properties=len(df_adjusted_frame),
        one_stop_json=DATA_OUTPUTS_DIR / "one_stop_output.json",
        html_dashboard=DATA_OUTPUTS_DIR / "one_stop_dashboard.html",
        workbook=combined_workbook or DATA_OUTPUTS_DIR / "analysis_outputs_compendium.xlsx",
        audit_log=log_path,
        figures=DATA_OUTPUTS_DIR / "figures",
        maps=DATA_OUTPUTS_DIR / "maps",
        dashboard_data=DATA_OUTPUTS_DIR / "dashboard" / "dashboard-data.json",
    )

    if args.open_results:
        open_results_folder()

    return EXIT_SUCCESS


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        console.print("\n[yellow]Analysis interrupted by user[/yellow]")
        sys.exit(EXIT_CANCELLED)
    except SystemExit:
        raise
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        logger.exception("Unexpected error in main pipeline")
        sys.exit(EXIT_ANALYSIS_FAILED)
