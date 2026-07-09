"""Throttled terminal dashboards for the HeatStreet analysis runner."""

from __future__ import annotations

import contextlib
import os
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Iterable, Iterator, Mapping, Optional

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from .compat import resolve_refresh_rate, should_enable_live
from .events import UIEvent
from .formatters import (
    format_count,
    format_duration,
    format_path,
    format_percent,
    phase_label,
    safe_text,
    status_label,
)
from .state import (
    AcquisitionCounters,
    ValidationFunnel as _ValidationFunnel,
    ArchetypeState,
    ScenarioState,
    RetrofitTierState,
    SpatialState,
    OutputEntry,
)


METRIC_GROUPS = ("Acquisition", "Validation", "Modelling", "Outputs")

DEFAULT_PHASES = (
    "Preflight",
    "Data Download",
    "Loading Existing Data",
    "Data Validation",
    "Methodological Adjustments",
    "Archetype Analysis",
    "Scenario Modeling",
    "Retrofit Readiness Analysis",
    "Spatial Analysis",
    "Additional Reports",
    "Report Generation",
    "One-Stop Report",
    "Dashboard Packaging",
)

HEADLINE_METRICS = {
    "Acquisition": (
        "Download scope",
        "sample start date",
        "sample end date",
        "rows read",
        "rows retained",
        "raw London records",
        "filtered stock records",
        "malformed rows skipped",
    ),
    "Validation": (
        "input records",
        "passed records",
        "duplicates removed",
        "invalid records",
        "validation rate",
        "adjustments applied",
        "records adjusted",
    ),
    "Modelling": (
        "properties",
        "scenarios modeled",
        "properties analysed",
        "solid wall barrier count",
        "mean fabric cost",
        "total retrofit investment",
        "properties geocoded",
    ),
    "Outputs": (
        "reports generated",
        "additional reports",
        "dashboard data arrays",
        "Elapsed",
    ),
}

PHASE_TO_GROUP = {
    "Data Download": "Acquisition",
    "Loading Existing Data": "Acquisition",
    "Data Validation": "Validation",
    "Methodological Adjustments": "Validation",
    "Archetype Analysis": "Modelling",
    "Scenario Modeling": "Modelling",
    "Retrofit Readiness Analysis": "Modelling",
    "Spatial Analysis": "Modelling",
    "Additional Reports": "Outputs",
    "Report Generation": "Outputs",
    "One-Stop Report": "Outputs",
    "Dashboard Packaging": "Outputs",
}

COMPLETION_LABELS = {
    "one_stop_json": "One-stop JSON",
    "html_dashboard": "HTML dashboard",
    "workbook": "Workbook",
    "audit_log": "Analysis log",
    "figures": "Figures directory",
    "maps": "Maps directory",
    "dashboard_data": "Dashboard data",
}


def _metric_map() -> Dict[str, "OrderedDict[str, str]"]:
    return {group: OrderedDict() for group in METRIC_GROUPS}


@dataclass
class DashboardState:
    """Mutable state observed by all HeatStreet Studio dashboard renderers."""

    start_time: Optional[float] = None
    completed_at: Optional[float] = None
    phases: "OrderedDict[str, str]" = field(default_factory=OrderedDict)
    phase_started_at: Dict[str, float] = field(default_factory=dict)
    current_phase: Optional[str] = None
    current_action: str = "Starting"
    sample_start: Optional[str] = None
    sample_end: Optional[str] = None
    progress_current: Optional[float] = None
    progress_total: Optional[float] = None
    progress_label: str = ""
    metrics: Dict[str, "OrderedDict[str, str]"] = field(default_factory=_metric_map)
    scenario_rows: "OrderedDict[str, OrderedDict[str, str]]" = field(default_factory=OrderedDict)
    events: Deque[str] = field(default_factory=lambda: deque(maxlen=6))
    warnings: Deque[str] = field(default_factory=lambda: deque(maxlen=10))
    outputs: "OrderedDict[str, str]" = field(default_factory=OrderedDict)
    completion_paths: "OrderedDict[str, str]" = field(default_factory=OrderedDict)
    last_render_at: float = 0.0
    properties_analysed: Optional[int] = None

    # Phase-specific rich state (used by Textual widgets)
    acquisition: AcquisitionCounters = field(default_factory=AcquisitionCounters)
    validation: "_ValidationFunnel" = field(default_factory=_ValidationFunnel)
    archetype: ArchetypeState = field(default_factory=ArchetypeState)
    scenario_states: "OrderedDict[str, ScenarioState]" = field(default_factory=OrderedDict)
    retrofit: RetrofitTierState = field(default_factory=RetrofitTierState)
    spatial: SpatialState = field(default_factory=SpatialState)
    svg_assets: Dict[str, str] = field(default_factory=dict)

    def elapsed(self, now: float) -> float:
        if self.start_time is None:
            return 0.0
        return max(0.0, (self.completed_at or now) - self.start_time)

    def phase_count_done(self) -> int:
        return sum(1 for s in self.phases.values() if s == "completed")

    def phase_count_total(self) -> int:
        return len(self.phases)

    def phase_count_failed(self) -> int:
        return sum(1 for s in self.phases.values() if s == "failed")

    def phase_count_skipped(self) -> int:
        return sum(1 for s in self.phases.values() if s == "skipped")


class DashboardBase:
    """Shared state/event handling for full and simple dashboards."""

    is_full_tui = False
    is_simple_tui = False
    suppress_external_progress = False
    route_console_output = False

    def __init__(
        self,
        *,
        enabled: bool = True,
        quiet: bool = False,
        verbose: bool = False,
        console: Optional[Console] = None,
        refresh_per_second: int = 4,
        state: Optional[DashboardState] = None,
        time_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        self.enabled = bool(enabled and not quiet)
        self.quiet = bool(quiet)
        self.verbose = bool(verbose)
        self.console = console or Console()
        self.refresh_per_second = max(2, min(4, int(refresh_per_second or 4)))
        self.state = state or DashboardState()
        self._time = time_fn or time.time
        self.allow_console_output = False

    @property
    def metrics(self) -> Dict[str, "OrderedDict[str, str]"]:
        return self.state.metrics

    @property
    def outputs(self) -> "OrderedDict[str, str]":
        return self.state.outputs

    @property
    def warnings(self) -> Deque[str]:
        return self.state.warnings

    @property
    def events(self) -> Deque[str]:
        return self.state.events

    @property
    def is_live_active(self) -> bool:
        return False

    def __enter__(self) -> "DashboardBase":
        self._guard(self.start)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is not None:
            self.run_failed(str(exc))
        self._guard(self.stop)
        return False

    def _guard(self, func, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            return None

    def start(self) -> None:
        now = self._time()
        if self.state.start_time is None:
            self.state.start_time = now
        self.state.current_action = "Preflight"
        self._ensure_phase("Preflight")
        self._refresh(force=True)

    def stop(self) -> None:
        return None

    def emit(self, event: UIEvent) -> None:
        self._guard(self._handle_event, event)

    def _handle_event(self, event: UIEvent) -> None:
        event_type = event.event_type
        if event.phase:
            self._ensure_phase(event.phase)

        if event_type == "run_started":
            self.run_started(event.message)
        elif event_type == "run_completed":
            self.run_completed(**event.payload)
        elif event_type == "run_failed":
            self.run_failed(event.message)
        elif event_type == "phase_started":
            self.phase_started(event.phase or event.message, event.message)
        elif event_type == "phase_progress":
            self.phase_progress(event.phase, event.message)
        elif event_type == "phase_completed":
            self.phase_completed(event.phase or event.message, event.message)
        elif event_type == "phase_failed":
            self.phase_failed(event.phase or event.message, event.message)
        elif event_type == "metric_updated":
            self.metric(event.metric or event.message, event.value, group=event.group)
        elif event_type == "output_registered":
            self.output(event.message, event.value)
        elif event_type == "warning":
            self.warning(event.message)
        elif event_type == "info":
            self.info(event.message)
        elif event_type == "prompt_pending":
            self.prompt_pending(event.message)
        elif event_type == "prompt_completed":
            self.prompt_completed(event.message)

    def run_started(self, message: str = "") -> None:
        self.state.start_time = self.state.start_time or self._time()
        self._ensure_phase("Preflight")
        self.state.phases["Preflight"] = "running"
        self.state.current_action = safe_text(message or "Run started", max_length=90)
        self._record("Run started")
        self._refresh(force=True)

    def run_completed(
        self,
        *,
        elapsed: Optional[float] = None,
        properties: Optional[int] = None,
        **paths,
    ) -> None:
        self.state.completed_at = self._time()
        self.state.current_phase = None
        self.state.current_action = "Run complete"
        self._complete_running_phases()
        if elapsed is not None:
            self._store_metric("Elapsed", format_duration(elapsed), group="Outputs")
        if properties is not None:
            self.state.properties_analysed = int(properties)
            self._store_metric("Properties analysed", format_count(properties), group="Modelling")
        for key, path in paths.items():
            if path:
                label = COMPLETION_LABELS.get(key, key.replace("_", " ").title())
                formatted = format_path(path, max_length=96)
                self.state.completion_paths[label] = formatted
                self.state.outputs[label] = formatted
        self._record("Run complete")
        self._refresh(force=True, final=True)
        self._after_completion()

    def run_failed(self, message: str = "") -> None:
        self.state.completed_at = self._time()
        self.state.current_action = "Run failed"
        if self.state.current_phase:
            self.state.phases[self.state.current_phase] = "failed"
        if message:
            self.warning(message)
        self._record("Run failed")
        self._refresh(force=True, final=True)
        self._after_failure()

    def phase_started(self, name: str, message: str = "") -> None:
        name = phase_label(name)
        if not name:
            return
        self._ensure_phase(name)
        self.state.phases[name] = "running"
        self.state.phase_started_at[name] = self._time()
        self.state.current_phase = name
        self.state.current_action = safe_text(message or name, max_length=90)
        self.state.progress_current = None
        self.state.progress_total = None
        self._record(f"Started {name}")
        self._on_phase_line(name, "RUN", self.state.current_action)
        self._refresh(force=True)

    def phase_progress(self, name: Optional[str], message: str = "") -> None:
        if name:
            safe_name = phase_label(name)
            self._ensure_phase(safe_name)
            self.state.current_phase = safe_name
            if self.state.phases.get(safe_name) == "pending":
                self.state.phases[safe_name] = "running"
        self.state.current_action = safe_text(message or self.state.current_action, max_length=90)
        self._record(self.state.current_action)
        self._refresh()

    def phase_completed(self, name: str, message: str = "") -> None:
        name = phase_label(name)
        if not name:
            return
        self._ensure_phase(name)
        self.state.phases[name] = "completed"
        self.state.current_phase = None
        self.state.current_action = safe_text(message or f"{name} complete", max_length=90)
        self._record(self.state.current_action)
        self._on_phase_line(name, "DONE", self.state.current_action)
        self._refresh(force=True)

    def phase_failed(self, name: str, message: str = "") -> None:
        name = phase_label(name)
        if not name:
            return
        self._ensure_phase(name)
        self.state.phases[name] = "failed"
        self.state.current_phase = name
        self.state.current_action = safe_text(message or f"{name} failed", max_length=90)
        self.warning(self.state.current_action)
        self._on_phase_line(name, "FAIL", self.state.current_action)
        self._refresh(force=True)

    def phase_skipped(self, name: str, message: str = "") -> None:
        name = phase_label(name)
        if not name:
            return
        self._ensure_phase(name)
        self.state.phases[name] = "skipped"
        self.state.current_phase = None
        self.state.current_action = safe_text(message or f"{name} skipped", max_length=90)
        self._record(self.state.current_action)
        self._on_phase_line(name, "SKIP", self.state.current_action)
        self._refresh(force=True)

    def progress(
        self,
        current: Optional[float] = None,
        total: Optional[float] = None,
        *,
        label: str = "",
    ) -> None:
        self.state.progress_current = current
        self.state.progress_total = total
        self.state.progress_label = safe_text(label, max_length=40)
        self._refresh()

    def metric(self, key: str, value: Any, *, group: Optional[str] = None) -> None:
        self._store_metric(key, value, group=group)
        self._refresh()

    def output(self, label: str, path: Any = None) -> None:
        safe_label = safe_text(label, max_length=38) or "Output"
        formatted_path = format_path(path if path is not None else label, max_length=96)
        self.state.outputs[safe_label] = formatted_path
        self._record(f"Output: {safe_label}")
        self._refresh()

    def warning(self, message: str) -> None:
        text = safe_text(message, max_length=120)
        if text:
            self.state.warnings.append(text)
            self._record(f"Warning: {text}")
            if not self.enabled and not self.quiet:
                self.console.print(f"[yellow]Warning:[/yellow] {text}")
        self._refresh(force=True)

    def info(self, message: str) -> None:
        text = safe_text(message, max_length=120)
        if text:
            self._record(text)
            if not self.enabled and self.verbose and not self.quiet:
                self.console.print(f"[cyan]{text}[/cyan]")
        self._refresh()

    def prompt_pending(self, message: str) -> None:
        self.state.current_action = safe_text(message or "Waiting for operator input", max_length=90)
        if self.state.current_phase:
            self.state.phases[self.state.current_phase] = "waiting"
        self._record(self.state.current_action)
        self._refresh(force=True)

    def prompt_completed(self, message: str = "") -> None:
        if self.state.current_phase and self.state.phases.get(self.state.current_phase) == "waiting":
            self.state.phases[self.state.current_phase] = "running"
        if message:
            self._record(safe_text(message, max_length=120))
        self._refresh(force=True)

    @contextlib.contextmanager
    def suspend_for_prompt(self, message: str = "") -> Iterator[None]:
        self._guard(self.prompt_pending, message)
        previous = self.allow_console_output
        self.allow_console_output = True
        try:
            yield
        finally:
            self.allow_console_output = previous
            self._guard(self.prompt_completed)

    def register_metrics(self, metrics: Dict[str, Any], *, group: Optional[str] = None) -> None:
        for key, value in metrics.items():
            self.metric(key, value, group=group)

    def register_outputs(self, outputs: Iterable[tuple[str, Any]]) -> None:
        for label, path in outputs:
            self.output(label, path)

    def _ensure_phase(self, name: str) -> None:
        name = phase_label(name)
        if name and name not in self.state.phases:
            self.state.phases[name] = "pending"

    def _complete_running_phases(self) -> None:
        for phase, status in list(self.state.phases.items()):
            if status in {"running", "waiting", "pending"}:
                self.state.phases[phase] = "completed"

    def _store_metric(self, key: str, value: Any, *, group: Optional[str] = None) -> None:
        safe_key = safe_text(key, max_length=44)
        if not safe_key:
            return
        group_name = group if group in METRIC_GROUPS else self._infer_group(safe_key)
        formatted = self._format_metric_value(value, key=safe_key)
        self.state.metrics[group_name][safe_key] = formatted
        self._update_sample_window(safe_key, formatted)
        self._update_scenario_row(safe_key, formatted)

    def _update_sample_window(self, key: str, value: str) -> None:
        lowered = key.lower()
        if "sample start" in lowered:
            self.state.sample_start = value
        elif "sample end" in lowered:
            self.state.sample_end = value

    def _update_scenario_row(self, key: str, value: str) -> None:
        lowered = key.lower()
        if "scenario" in lowered and "modeled" in lowered:
            return
        if " status" not in lowered and "cost/property" not in lowered:
            return
        scenario = key
        field = "Value"
        if lowered.endswith(" status"):
            scenario = key[: -len(" status")]
            field = "Status"
        elif "cost/property" in lowered:
            scenario = key.split("cost/property", 1)[0].strip()
            field = "Cost/property"
        scenario = safe_text(scenario.replace("_", " "), max_length=28)
        if not scenario:
            return
        if scenario not in self.state.scenario_rows:
            self.state.scenario_rows[scenario] = OrderedDict(
                (("Status", "pending"), ("Cost/property", "pending"))
            )
        self.state.scenario_rows[scenario][field] = value

    def _record(self, message: str) -> None:
        text = safe_text(message, max_length=118)
        if text:
            self.state.events.append(text)

    def _refresh(self, *, force: bool = False, final: bool = False) -> None:
        return None

    def _after_completion(self) -> None:
        return None

    def _after_failure(self) -> None:
        return None

    def _on_phase_line(self, name: str, status: str, message: str) -> None:
        return None

    def _infer_group(self, key: str) -> str:
        text = safe_text(key).lower()
        if any(token in text for token in ("download", "raw", "member", "row", "borough", "filtered", "malformed", "epc zip", "sample")):
            return "Acquisition"
        if any(token in text for token in ("valid", "duplicate", "negative", "adjust")):
            return "Validation"
        if any(token in text for token in ("scenario", "retrofit", "tier", "cost", "carbon", "property", "fabric")):
            return "Modelling"
        return "Outputs"

    def _format_metric_value(self, value: Any, *, key: str = "") -> str:
        if isinstance(value, str):
            return safe_text(value, max_length=40)
        if isinstance(value, Path):
            return format_path(value, max_length=48)
        if isinstance(value, float):
            if "rate" in key.lower() or "percent" in key.lower():
                return format_percent(value)
            return f"{value:,.2f}" if abs(value) < 1000 else f"{value:,.0f}"
        if isinstance(value, int):
            return format_count(value)
        return safe_text(value, max_length=40)


class LiveDashboard(DashboardBase):
    """Fixed-layout Rich Live dashboard used as an optional observer."""

    is_full_tui = True
    suppress_external_progress = True
    route_console_output = True

    def __init__(
        self,
        *,
        enabled: bool = True,
        quiet: bool = False,
        verbose: bool = False,
        console: Optional[Console] = None,
        refresh_per_second: int = 4,
        state: Optional[DashboardState] = None,
        time_fn: Optional[Callable[[], float]] = None,
        live_factory: Callable[..., Live] = Live,
    ) -> None:
        super().__init__(
            enabled=enabled,
            quiet=quiet,
            verbose=verbose,
            console=console,
            refresh_per_second=refresh_per_second,
            state=state,
            time_fn=time_fn,
        )
        self._live_factory = live_factory
        self._live: Optional[Live] = None

    @property
    def is_live_active(self) -> bool:
        return self._live is not None

    def start(self) -> None:
        super().start()
        if self.enabled and self._live is None:
            self._live = self._live_factory(
                self._render(),
                console=self.console,
                auto_refresh=False,
                transient=False,
            )
            self._live.start(refresh=True)
            self.state.last_render_at = self._time()

    def stop(self) -> None:
        if self._live is not None:
            live = self._live
            self._live = None
            live.stop()

    @contextlib.contextmanager
    def suspend_for_prompt(self, message: str = "") -> Iterator[None]:
        self._guard(self.prompt_pending, message)
        live = self._live
        if live is not None:
            self._live = None
            with contextlib.suppress(Exception):
                live.stop()
        previous = self.allow_console_output
        self.allow_console_output = True
        try:
            yield
        finally:
            self.allow_console_output = previous
            if self.enabled and live is not None:
                try:
                    live.start(refresh=True)
                    self._live = live
                    self.state.last_render_at = self._time()
                except Exception:
                    self._live = None
            self._guard(self.prompt_completed)

    def _refresh(self, *, force: bool = False, final: bool = False) -> None:
        if self._live is None:
            return
        now = self._time()
        interval = 1.0 / max(1, self.refresh_per_second)
        if not force and (now - self.state.last_render_at) < interval:
            return
        self._live.update(self._render(final=final), refresh=True)
        self.state.last_render_at = now

    def _after_completion(self) -> None:
        self.stop()
        if self.enabled and not self.quiet:
            self.console.print(self._completion_panel())

    def _after_failure(self) -> None:
        self.stop()

    def _render(self, *, final: bool = False):
        return Group(
            self._header(final=final),
            self._body_table(),
            self._scenario_panel(),
            self._bottom_panel(),
        )

    def _header(self, *, final: bool) -> Panel:
        now = self._time()
        phase_number, phase_total = self._phase_position()
        phase_name = self.state.current_phase or "Idle"
        sample = ""
        if self.state.sample_start or self.state.sample_end:
            sample = f" | Sample: {self.state.sample_start or '?'} to {self.state.sample_end or '?'}"
        title = "HeatStreet Mission Control"
        if final and self.state.current_action == "Run complete":
            title = "HeatStreet Mission Control - Run complete"
        elif final and self.state.current_action == "Run failed":
            title = "HeatStreet Mission Control - Run failed"
        body = (
            f"Elapsed: {format_duration(self.state.elapsed(now))} | "
            f"Phase {phase_number}/{phase_total}: {phase_label(phase_name)} | "
            f"Action: {safe_text(self.state.current_action, max_length=74)}"
            f"{safe_text(sample, max_length=56)}"
        )
        return Panel(body, title=title, border_style="cyan", box=box.ASCII)

    def _body_table(self) -> Table:
        table = Table.grid(expand=True)
        table.add_column(ratio=2)
        table.add_column(ratio=4)
        table.add_column(ratio=3)
        table.add_row(self._phase_panel(), self._main_panel(), self._headline_panel())
        return table

    def _phase_panel(self) -> Panel:
        rows = list(self.state.phases.items()) or [("Preflight", "running")]
        if len(rows) > 12:
            current = self.state.current_phase
            if current:
                current_index = next((idx for idx, row in enumerate(rows) if row[0] == current), len(rows) - 1)
                start = max(0, min(current_index - 6, len(rows) - 12))
                rows = rows[start : start + 12]
            else:
                rows = rows[-12:]

        table = Table(box=None, expand=True, padding=(0, 1))
        table.add_column("#", justify="right", width=2, no_wrap=True)
        table.add_column("State", width=5, no_wrap=True)
        table.add_column("Phase", no_wrap=True)
        all_names = list(self.state.phases.keys())
        for phase, status in rows:
            number = str(all_names.index(phase) + 1) if phase in all_names else ""
            label = status_label(status)
            style = {
                "DONE": "green",
                "RUN": "cyan",
                "WAIT": "yellow",
                "SKIP": "yellow",
                "WARN": "yellow",
                "FAIL": "red",
            }.get(label, "white")
            table.add_row(number, label, phase_label(phase), style=style)
        return Panel(table, title="Phases", border_style="blue", box=box.ASCII)

    def _main_panel(self) -> Panel:
        now = self._time()
        phase = self.state.current_phase or "No active phase"
        started = self.state.phase_started_at.get(phase)
        phase_elapsed = format_duration(now - started) if started else "-"
        lines = [
            f"Current phase: {phase_label(phase)}",
            f"Action: {safe_text(self.state.current_action, max_length=68)}",
            f"Phase elapsed: {phase_elapsed}",
            self._progress_line(now),
            self._throughput_line(now),
        ]
        return Panel("\n".join(lines), title="Current Work", border_style="cyan", box=box.ASCII)

    def _progress_line(self, now: float) -> str:
        current = self.state.progress_current
        total = self.state.progress_total
        if current is None or not total:
            return f"Progress: working {safe_text(self.state.progress_label, max_length=32)}".rstrip()
        pct = max(0.0, min(1.0, float(current) / float(total)))
        width = 24
        filled = int(round(pct * width))
        bar = "#" * filled + "." * (width - filled)
        return f"Progress: [{bar}] {pct * 100:5.1f}% ({format_count(current)}/{format_count(total)})"

    def _throughput_line(self, now: float) -> str:
        current = self.state.progress_current
        total = self.state.progress_total
        phase = self.state.current_phase
        started = self.state.phase_started_at.get(phase or "")
        if current is None or total in (None, 0) or not started:
            return "ETA: pending"
        elapsed = max(0.001, now - started)
        rate = float(current) / elapsed
        remaining = max(0.0, float(total) - float(current))
        eta = remaining / rate if rate > 0 else 0
        return f"ETA: {format_duration(eta)} | Throughput: {rate:,.0f}/s"

    def _headline_panel(self) -> Panel:
        group = PHASE_TO_GROUP.get(self.state.current_phase or "", "Outputs")
        group_metrics = self.state.metrics.get(group, OrderedDict())
        preferred = HEADLINE_METRICS.get(group, ())
        lines = []
        for key in preferred:
            if key in group_metrics:
                lines.append(f"{safe_text(key, max_length=28)}: {safe_text(group_metrics[key], max_length=18)}")
        if not lines:
            for key, value in list(group_metrics.items())[-7:]:
                lines.append(f"{safe_text(key, max_length=28)}: {safe_text(value, max_length=18)}")
        if not lines:
            lines.append("Waiting for counters")
        return Panel("\n".join(lines[:8]), title=f"{group} Counters", border_style="magenta", box=box.ASCII)

    def _scenario_panel(self) -> Panel:
        table = Table(box=None, expand=True, padding=(0, 1))
        table.add_column("Scenario", no_wrap=True)
        table.add_column("Status", no_wrap=True)
        table.add_column("Cost/property", justify="right", no_wrap=True)
        if self.state.scenario_rows:
            for scenario, values in list(self.state.scenario_rows.items())[:6]:
                table.add_row(
                    safe_text(scenario, max_length=28),
                    safe_text(values.get("Status", "pending"), max_length=14),
                    safe_text(values.get("Cost/property", "pending"), max_length=16),
                )
        else:
            table.add_row("pending", "pending", "pending")
        return Panel(table, title="Scenario Board", border_style="green", box=box.ASCII)

    def _bottom_panel(self) -> Panel:
        lines = []
        if self.state.events:
            lines.append("Recent events")
            lines.extend(f"- {safe_text(message, max_length=100)}" for message in list(self.state.events)[-6:])
        if self.state.warnings:
            if lines:
                lines.append("")
            lines.append("Warnings")
            lines.extend(f"- {safe_text(message, max_length=100)}" for message in list(self.state.warnings)[-3:])
        if self.state.outputs:
            if lines:
                lines.append("")
            lines.append("Outputs")
            for label, path in list(self.state.outputs.items())[-3:]:
                lines.append(f"- {safe_text(label, max_length=28)}: {format_path(path, max_length=72)}")
        if not lines:
            lines.append("Starting up")
        return Panel("\n".join(lines), title="Run Notes", border_style="blue", box=box.ASCII)

    def _completion_panel(self) -> Panel:
        counts = self._phase_counts()
        elapsed = self.state.elapsed(self._time())
        paths = self.state.completion_paths
        open_first = (
            paths.get("HTML dashboard")
            or paths.get("One-stop JSON")
            or paths.get("Workbook")
            or next(iter(paths.values()), "data/outputs")
        )
        lines = [
            "[bold green]Run complete[/bold green]",
            f"Elapsed time: {format_duration(elapsed)}",
            (
                "Phase counts: "
                f"{counts['done']} done, {counts['failed']} failed, "
                f"{counts['skipped']} skipped"
            ),
            f"Properties analysed: {format_count(self.state.properties_analysed)}",
            f"Warnings count: {len(self.state.warnings)}",
            "",
            f"Open first: {format_path(open_first, max_length=86)}",
            f"One-stop JSON: {paths.get('One-stop JSON', 'pending')}",
            f"Workbook: {paths.get('Workbook', 'pending')}",
            f"Dashboard data: {paths.get('Dashboard data', 'pending')}",
            f"Analysis log: {paths.get('Analysis log', 'pending')}",
            f"Figures directory: {paths.get('Figures directory', 'pending')}",
            f"Maps directory: {paths.get('Maps directory', 'pending')}",
        ]
        return Panel("\n".join(lines), title="HeatStreet Mission Control", border_style="green", box=box.ASCII)

    def _phase_position(self) -> tuple[int, int]:
        total = max(len(self.state.phases), 1)
        if self.state.current_phase and self.state.current_phase in self.state.phases:
            return list(self.state.phases.keys()).index(self.state.current_phase) + 1, total
        return total, total

    def _phase_counts(self) -> Dict[str, int]:
        statuses = list(self.state.phases.values())
        return {
            "done": sum(1 for status in statuses if status == "completed"),
            "failed": sum(1 for status in statuses if status == "failed"),
            "skipped": sum(1 for status in statuses if status == "skipped"),
        }


class SimpleDashboard(DashboardBase):
    """Line-oriented dashboard for terminals that dislike Rich Live."""

    is_simple_tui = True

    def start(self) -> None:
        super().start()
        if self.enabled and not self.quiet:
            self.console.print("[cyan]HeatStreet Mission Control[/cyan]")

    def _on_phase_line(self, name: str, status: str, message: str) -> None:
        if not self.enabled or self.quiet:
            return
        self.console.print(
            f"{safe_text(status, max_length=5):<5} {phase_label(name):<34} "
            f"{safe_text(message, max_length=72)}"
        )

    def _after_completion(self) -> None:
        if not self.enabled or self.quiet:
            return
        completion = LiveDashboard(
            enabled=False,
            quiet=True,
            console=self.console,
            state=self.state,
            time_fn=self._time,
        )
        self.console.print(completion._completion_panel())

    @contextlib.contextmanager
    def suspend_for_prompt(self, message: str = "") -> Iterator[None]:
        self._guard(self.prompt_pending, message)
        previous = self.allow_console_output
        self.allow_console_output = True
        try:
            yield
        finally:
            self.allow_console_output = previous
            self._guard(self.prompt_completed)


class NullDashboard:
    """No-op dashboard used when terminal UI output is disabled."""

    enabled = False
    quiet = True
    verbose = False
    is_full_tui = False
    is_simple_tui = False
    is_live_active = False
    suppress_external_progress = False
    route_console_output = False
    allow_console_output = True

    def __enter__(self) -> "NullDashboard":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def __getattr__(self, name: str):
        if name in {"metrics", "outputs", "warnings", "events"}:
            return OrderedDict() if name in {"metrics", "outputs"} else deque()

        def noop(*args, **kwargs):
            return None

        return noop

    @contextlib.contextmanager
    def suspend_for_prompt(self, message: str = "") -> Iterator[None]:
        yield


def create_dashboard(
    args: Any,
    *,
    console: Optional[Console] = None,
    env: Optional[Mapping[str, str]] = None,
) -> "DashboardBase | NullDashboard":
    """Create the dashboard selected by CLI arguments and terminal policy.

    Supports both legacy bool ``args.tui`` and new string ``args.tui_mode``.
    New modes: ``args.tui_mode in ("textual", "rich")`` or ``args.no_tui``.
    """
    env = os.environ if env is None else env
    console = console or Console()
    quiet = bool(getattr(args, "quiet", False))
    verbose = bool(getattr(args, "verbose", False))
    simple = bool(getattr(args, "simple_tui", False))
    no_tui = bool(getattr(args, "no_tui", False))

    # Resolve TUI mode from new (tui_mode string) or legacy (tui bool) arg
    tui_mode_arg = getattr(args, "tui_mode", None)  # "textual" | "rich" | None
    tui_legacy = getattr(args, "tui", None)          # True | False | None (legacy)

    # Hard disable conditions
    if quiet or no_tui or tui_legacy is False:
        return NullDashboard()

    refresh_rate = resolve_refresh_rate(
        getattr(args, "tui_refresh_rate", None),
        env=env,
        enabled=True,
    )

    if simple:
        return SimpleDashboard(
            enabled=True,
            quiet=quiet,
            verbose=verbose,
            console=console,
            refresh_per_second=refresh_rate,
        )

    # Explicit textual mode (only when --tui textual is set, NOT legacy bool tui=True)
    if tui_mode_arg == "textual":
        from .terminal import _textual_importable
        from .compat import live_rendering_allowed
        if _textual_importable() and live_rendering_allowed(console=console, env=env):
            from .textual_app import TextualUIAdapter
            return TextualUIAdapter(enabled=True, quiet=quiet, verbose=verbose)
        # Textual unavailable - fall through to Rich
        tui_mode_arg = "rich"

    # Legacy bool: HEATSTREET_TUI=1 or old --tui flag -> use Rich Live dashboard
    if tui_legacy is True:
        tui_mode_arg = "rich"

    # Explicit rich mode
    if tui_mode_arg == "rich":
        from .compat import live_rendering_allowed
        if live_rendering_allowed(console=console, env=env):
            from .rich_fallback import RichFallback
            return RichFallback(
                enabled=True,
                quiet=quiet,
                verbose=verbose,
                console=console,
                refresh_per_second=refresh_rate,
            )
        return NullDashboard()

    # Auto-detect mode
    if verbose:
        return NullDashboard()

    from .terminal import recommended_tui_mode, _textual_importable
    mode = recommended_tui_mode(env=env)

    if mode == "none":
        return NullDashboard()

    if mode == "simple":
        return SimpleDashboard(
            enabled=True, quiet=quiet, verbose=verbose,
            console=console, refresh_per_second=refresh_rate,
        )

    if mode == "textual" and _textual_importable():
        from .compat import live_rendering_allowed
        if live_rendering_allowed(console=console, env=env):
            from .textual_app import TextualUIAdapter
            return TextualUIAdapter(enabled=True, quiet=quiet, verbose=verbose)

    # Default: Rich live dashboard
    enabled = should_enable_live(
        requested=tui_legacy,
        quiet=quiet,
        console=console,
        env=env,
    )
    if not enabled:
        return NullDashboard()

    return LiveDashboard(
        enabled=True,
        quiet=quiet,
        verbose=verbose,
        console=console,
        refresh_per_second=refresh_rate,
    )
