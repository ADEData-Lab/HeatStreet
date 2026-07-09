"""Simple line-oriented fallback dashboard for conservative terminals.

Prints one clean line per phase transition and a final summary table.
Stable in Anaconda Prompt, Windows cmd and other limited terminals.
"""

from __future__ import annotations

import contextlib
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Iterator, Optional

from rich.console import Console
from rich.panel import Panel
from rich import box

from .formatters import (
    format_count,
    format_duration,
    format_path,
    phase_label,
    safe_text,
    status_label,
)


@dataclass
class _SimpleState:
    """Minimal state for the simple fallback dashboard."""

    start_time: Optional[float] = None
    completed_at: Optional[float] = None
    phases: "OrderedDict[str, str]" = field(default_factory=OrderedDict)
    phase_started_at: Dict[str, float] = field(default_factory=dict)
    current_phase: Optional[str] = None
    current_action: str = "Starting"
    metrics: Dict[str, "OrderedDict[str, str]"] = field(
        default_factory=lambda: {g: OrderedDict() for g in ("Acquisition", "Validation", "Modelling", "Outputs")}
    )
    events: Deque[str] = field(default_factory=lambda: deque(maxlen=6))
    warnings: Deque[str] = field(default_factory=lambda: deque(maxlen=10))
    outputs: "OrderedDict[str, str]" = field(default_factory=OrderedDict)
    completion_paths: "OrderedDict[str, str]" = field(default_factory=OrderedDict)
    properties_analysed: Optional[int] = None
    sample_start: Optional[str] = None
    sample_end: Optional[str] = None

    def elapsed(self, now: float) -> float:
        if self.start_time is None:
            return 0.0
        return max(0.0, (self.completed_at or now) - self.start_time)


class SimpleFallback:
    """Line-oriented dashboard for terminals that dislike Rich Live rendering."""

    is_full_tui = False
    is_simple_tui = True
    suppress_external_progress = False
    route_console_output = False

    def __init__(
        self,
        *,
        enabled: bool = True,
        quiet: bool = False,
        verbose: bool = False,
        console: Optional[Console] = None,
        refresh_per_second: int = 2,
        time_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        self.enabled = bool(enabled and not quiet)
        self.quiet = bool(quiet)
        self.verbose = bool(verbose)
        self.console = console or Console()
        self.refresh_per_second = refresh_per_second
        self._time = time_fn or time.time
        self.state = _SimpleState()
        self.allow_console_output = True

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

    def __enter__(self) -> "SimpleFallback":
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
        self._ensure_phase("Preflight")
        if self.enabled:
            self.console.print("[cyan]HeatStreet Studio[/cyan]  (simple mode)")

    def stop(self) -> None:
        return None

    def emit(self, event) -> None:
        self._guard(self._handle_event, event)

    def _handle_event(self, event) -> None:
        t = event.event_type
        if t == "run_started":
            self.run_started(event.message)
        elif t == "run_completed":
            self.run_completed(**event.payload)
        elif t == "run_failed":
            self.run_failed(event.message)
        elif t == "phase_started":
            self.phase_started(event.phase or event.message, event.message)
        elif t == "phase_progress":
            self.phase_progress(event.phase, event.message)
        elif t == "phase_completed":
            self.phase_completed(event.phase or event.message, event.message)
        elif t == "phase_failed":
            self.phase_failed(event.phase or event.message, event.message)
        elif t == "phase_skipped":
            self.phase_skipped(event.phase or event.message, event.message)
        elif t == "metric_updated":
            self.metric(event.metric or event.message, event.value, group=event.group)
        elif t == "output_registered":
            self.output(event.message, event.value)
        elif t == "warning":
            self.warning(event.message)
        elif t == "info":
            self.info(event.message)
        elif t == "prompt_pending":
            self.prompt_pending(event.message)
        elif t == "prompt_completed":
            self.prompt_completed(event.message)

    def run_started(self, message: str = "") -> None:
        self.state.start_time = self.state.start_time or self._time()
        self._ensure_phase("Preflight")

    def run_completed(self, *, elapsed=None, properties=None, **paths) -> None:
        self.state.completed_at = self._time()
        self._complete_running_phases()
        if properties is not None:
            self.state.properties_analysed = int(properties)
        _LABELS = {
            "one_stop_json": "One-stop JSON",
            "html_dashboard": "HTML dashboard",
            "workbook": "Workbook",
            "audit_log": "Analysis log",
            "figures": "Figures directory",
            "maps": "Maps directory",
            "dashboard_data": "Dashboard data",
        }
        for key, path in paths.items():
            if path:
                label = _LABELS.get(key, key.replace("_", " ").title())
                self.state.completion_paths[label] = format_path(path, max_length=96)
        self._after_completion()

    def run_failed(self, message: str = "") -> None:
        self.state.completed_at = self._time()
        if self.state.current_phase:
            self.state.phases[self.state.current_phase] = "failed"
        if message:
            self.warning(message)
        self._on_phase_line("Run", "FAIL", message or "Run failed")

    def phase_started(self, name: str, message: str = "") -> None:
        name = phase_label(name)
        if not name:
            return
        self._ensure_phase(name)
        self.state.phases[name] = "running"
        self.state.phase_started_at[name] = self._time()
        self.state.current_phase = name
        self.state.current_action = safe_text(message or name, max_length=90)
        self._on_phase_line(name, "RUN", self.state.current_action)

    def phase_progress(self, name=None, message: str = "") -> None:
        if name:
            name = phase_label(name)
            self._ensure_phase(name)
            self.state.current_phase = name
        if message:
            self.state.current_action = safe_text(message, max_length=90)

    def phase_completed(self, name: str, message: str = "") -> None:
        name = phase_label(name)
        if not name:
            return
        self._ensure_phase(name)
        self.state.phases[name] = "completed"
        self.state.current_phase = None
        msg = safe_text(message or f"{name} complete", max_length=90)
        self._on_phase_line(name, "DONE", msg)

    def phase_failed(self, name: str, message: str = "") -> None:
        name = phase_label(name)
        if not name:
            return
        self._ensure_phase(name)
        self.state.phases[name] = "failed"
        msg = safe_text(message or f"{name} failed", max_length=90)
        self.warning(msg)
        self._on_phase_line(name, "FAIL", msg)

    def phase_skipped(self, name: str, message: str = "") -> None:
        name = phase_label(name)
        if not name:
            return
        self._ensure_phase(name)
        self.state.phases[name] = "skipped"
        self.state.current_phase = None
        msg = safe_text(message or f"{name} skipped", max_length=90)
        self._on_phase_line(name, "SKIP", msg)

    def progress(self, current=None, total=None, *, label: str = "") -> None:
        pass

    def metric(self, key: str, value: Any, *, group: Optional[str] = None) -> None:
        safe_key = safe_text(key, max_length=44)
        if not safe_key:
            return
        group_name = group if group in self.state.metrics else "Outputs"
        formatted = self._format_value(value, key=safe_key)
        self.state.metrics[group_name][safe_key] = formatted
        lowered = safe_key.lower()
        if "sample start" in lowered:
            self.state.sample_start = formatted
        elif "sample end" in lowered:
            self.state.sample_end = formatted

    @staticmethod
    def _format_value(value: Any, *, key: str = "") -> str:
        import math
        from pathlib import Path
        if isinstance(value, str):
            return safe_text(value, max_length=40)
        if isinstance(value, Path):
            return format_path(value, max_length=48)
        if isinstance(value, float):
            if math.isnan(value):
                return "-"
            if "rate" in key.lower() or "percent" in key.lower():
                from .formatters import format_percent
                return format_percent(value)
            return f"{value:,.2f}" if abs(value) < 1000 else f"{value:,.0f}"
        if isinstance(value, int):
            return format_count(value)
        return safe_text(value, max_length=40)

    def output(self, label: str, path: Any = None) -> None:
        safe_label = safe_text(label, max_length=38) or "Output"
        formatted_path = format_path(path if path is not None else label, max_length=96)
        self.state.outputs[safe_label] = formatted_path

    def warning(self, message: str) -> None:
        text = safe_text(message, max_length=120)
        if text:
            self.state.warnings.append(text)
            if self.enabled:
                self.console.print(f"[yellow]WARN[/yellow] {text}")

    def info(self, message: str) -> None:
        text = safe_text(message, max_length=120)
        if text:
            self.state.events.append(text)

    def prompt_pending(self, message: str) -> None:
        self.state.current_action = safe_text(message or "Waiting for input", max_length=90)

    def prompt_completed(self, message: str = "") -> None:
        if message:
            self.state.events.append(safe_text(message, max_length=120))

    def set_current_action(self, text: str) -> None:
        self.state.current_action = safe_text(text, max_length=90)

    def counter(self, key: str, value: Any, *, group: Optional[str] = None, label: Optional[str] = None) -> None:
        self.metric(key, value, group=group)

    def scenario_started(self, name: str) -> None:
        pass

    def scenario_progress(self, name: str, **kwargs) -> None:
        pass

    def scenario_completed(self, name: str, **kwargs) -> None:
        pass

    def visualization(self, path: Any, kind: str, description: str = "") -> None:
        if path:
            self.output(f"SVG: {kind}", path)

    def register_metrics(self, metrics: Dict[str, Any], *, group=None) -> None:
        for key, value in metrics.items():
            self.metric(key, value, group=group)

    def register_outputs(self, outputs) -> None:
        for label, path in outputs:
            self.output(label, path)

    @contextlib.contextmanager
    def suspend_for_prompt(self, message: str = "") -> Iterator[None]:
        self.prompt_pending(message)
        previous = self.allow_console_output
        self.allow_console_output = True
        try:
            yield
        finally:
            self.allow_console_output = previous
            self.prompt_completed()

    def _on_phase_line(self, name: str, status: str, message: str) -> None:
        if not self.enabled or self.quiet:
            return
        elapsed = ""
        started = self.state.phase_started_at.get(name)
        if started:
            elapsed = f" [{format_duration(self._time() - started)}]"
        self.console.print(
            f"{safe_text(status, max_length=4):<4}  "
            f"{phase_label(name):<32}  "
            f"{safe_text(message, max_length=60)}{elapsed}"
        )

    def _after_completion(self) -> None:
        if not self.enabled or self.quiet:
            return
        now = self._time()
        paths = self.state.completion_paths
        counts = {
            "done": sum(1 for s in self.state.phases.values() if s == "completed"),
            "failed": sum(1 for s in self.state.phases.values() if s == "failed"),
            "skipped": sum(1 for s in self.state.phases.values() if s == "skipped"),
        }
        open_first = (
            paths.get("HTML dashboard")
            or paths.get("One-stop JSON")
            or paths.get("Workbook")
            or next(iter(paths.values()), "data/outputs")
        )
        lines = [
            "[bold green]Run complete[/bold green]",
            f"Elapsed: {format_duration(self.state.elapsed(now))}",
            (
                f"Phases: {counts['done']} done, "
                f"{counts['failed']} failed, {counts['skipped']} skipped"
            ),
            f"Properties analysed: {format_count(self.state.properties_analysed)}",
            f"Warnings: {len(self.state.warnings)}",
            "",
            f"Open first: {format_path(open_first, max_length=86)}",
        ]
        for label, path in paths.items():
            lines.append(f"  {safe_text(label, max_length=22)}: {format_path(path, max_length=60)}")
        self.console.print(
            Panel("\n".join(lines), title="HeatStreet Studio", border_style="green", box=box.ASCII)
        )

    def _ensure_phase(self, name: str) -> None:
        name = phase_label(name)
        if name and name not in self.state.phases:
            self.state.phases[name] = "pending"

    def _complete_running_phases(self) -> None:
        for phase, status in list(self.state.phases.items()):
            if status in {"running", "waiting", "pending"}:
                self.state.phases[phase] = "completed"
