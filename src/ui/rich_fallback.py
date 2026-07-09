"""Improved Rich Live dashboard - the --tui rich fallback.

Fixed-height panels, throttled rendering, compact layout.
Subclasses DashboardBase for all state management.
"""

from __future__ import annotations

import contextlib
import time
from collections import OrderedDict
from typing import Any, Callable, Iterator, Optional

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from .live_dashboard import DashboardBase, DashboardState, PHASE_TO_GROUP, HEADLINE_METRICS, COMPLETION_LABELS
from .formatters import (
    format_count,
    format_duration,
    format_path,
    phase_label,
    safe_text,
    status_label,
    truncate_text,
)
from .icons import get_icons, IconSet


_STATUS_COLOURS = {
    "DONE": "green",
    "RUN": "cyan",
    "WAIT": "white",
    "SKIP": "bright_black",
    "WARN": "yellow",
    "FAIL": "red bold",
}


class RichFallback(DashboardBase):
    """Compact, low-flicker Rich Live dashboard for --tui rich mode."""

    is_full_tui = True
    is_simple_tui = False
    suppress_external_progress = True
    route_console_output = True

    def __init__(
        self,
        *,
        enabled: bool = True,
        quiet: bool = False,
        verbose: bool = False,
        console: Optional[Console] = None,
        refresh_per_second: int = 2,
        state: Optional[DashboardState] = None,
        time_fn: Optional[Callable[[], float]] = None,
        live_factory: Callable[..., Live] = Live,
        unicode_icons: bool = True,
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
        self._icons: IconSet = get_icons(unicode_ok=unicode_icons)

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

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

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
        if final and self.state.current_action == "Run complete":
            title = "HeatStreet Studio - Run complete"
        elif final and self.state.current_action == "Run failed":
            title = "HeatStreet Studio - Run failed"
        else:
            title = "HeatStreet Studio"
        body = (
            f"Elapsed: {format_duration(self.state.elapsed(now))} | "
            f"Phase {phase_number}/{phase_total}: {phase_label(phase_name)} | "
            f"{safe_text(self.state.current_action, max_length=64)}"
            f"{safe_text(sample, max_length=52)}"
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
                idx = next((i for i, r in enumerate(rows) if r[0] == current), len(rows) - 1)
                start = max(0, min(idx - 5, len(rows) - 12))
                rows = rows[start: start + 12]
            else:
                rows = rows[-12:]

        all_names = list(self.state.phases.keys())
        table = Table(box=None, expand=True, padding=(0, 0))
        table.add_column("I", width=4, no_wrap=True)
        table.add_column("#", justify="right", width=2, no_wrap=True)
        table.add_column("Phase", no_wrap=True)

        for phase, status in rows:
            number = str(all_names.index(phase) + 1) if phase in all_names else ""
            lbl = status_label(status)
            style = _STATUS_COLOURS.get(lbl, "white")
            icon = self._icons.for_status(status)
            table.add_row(icon, number, phase_label(phase), style=style)

        return Panel(table, title="Phases", border_style="blue", box=box.ASCII)

    def _main_panel(self) -> Panel:
        now = self._time()
        phase = self.state.current_phase or "No active phase"
        started = self.state.phase_started_at.get(phase)
        phase_elapsed = format_duration(now - started) if started else "-"
        lines = [
            f"Phase:   {phase_label(phase)}",
            f"Action:  {safe_text(self.state.current_action, max_length=62)}",
            f"Elapsed: {phase_elapsed}",
            self._progress_line(now),
            self._throughput_line(now),
        ]
        return Panel("\n".join(lines), title="Current Work", border_style="cyan", box=box.ASCII)

    def _progress_line(self, now: float) -> str:
        current = self.state.progress_current
        total = self.state.progress_total
        if current is None or not total:
            label = safe_text(self.state.progress_label, max_length=26)
            return f"Progress: working {label}".rstrip()
        pct = max(0.0, min(1.0, float(current) / float(total)))
        width = 22
        filled = int(round(pct * width))
        bar = self._icons.progress_fill * filled + self._icons.progress_empty * (width - filled)
        return f"[{bar}] {pct * 100:5.1f}% ({format_count(current)}/{format_count(total)})"

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
        return f"ETA: {format_duration(eta)} | {rate:,.0f}/s"

    def _headline_panel(self) -> Panel:
        group = PHASE_TO_GROUP.get(self.state.current_phase or "", "Outputs")
        group_metrics = self.state.metrics.get(group, OrderedDict())
        preferred = HEADLINE_METRICS.get(group, ())
        lines = []
        for key in preferred:
            if key in group_metrics:
                lines.append(f"{safe_text(key, max_length=26)}: {safe_text(group_metrics[key], max_length=18)}")
        if not lines:
            for key, value in list(group_metrics.items())[-7:]:
                lines.append(f"{safe_text(key, max_length=26)}: {safe_text(value, max_length=18)}")
        if not lines:
            lines.append("Waiting for counters")
        return Panel("\n".join(lines[:8]), title=f"{group} Counters", border_style="magenta", box=box.ASCII)

    def _scenario_panel(self) -> Panel:
        table = Table(box=None, expand=True, padding=(0, 1))
        table.add_column("Scenario", no_wrap=True)
        table.add_column("Status", no_wrap=True)
        table.add_column("Cost/home", justify="right", no_wrap=True)

        if self.state.scenario_rows:
            for scenario, values in list(self.state.scenario_rows.items())[:6]:
                table.add_row(
                    safe_text(scenario, max_length=24),
                    safe_text(values.get("Status", "pending"), max_length=12),
                    safe_text(values.get("Cost/property", "-"), max_length=14),
                )
        else:
            table.add_row("Waiting for scenario data", "-", "-")

        return Panel(table, title="Scenario Board", border_style="green", box=box.ASCII)

    def _bottom_panel(self) -> Panel:
        lines = []
        if self.state.events:
            lines.append("Recent events")
            for msg in list(self.state.events)[-4:]:
                lines.append(f"  {self._icons.bullet} {safe_text(msg, max_length=94)}")
        if self.state.warnings:
            if lines:
                lines.append("")
            lines.append(f"Warnings ({len(self.state.warnings)})")
            for msg in list(self.state.warnings)[-3:]:
                lines.append(f"  {self._icons.warning} {safe_text(msg, max_length=94)}")
        if self.state.outputs:
            if lines:
                lines.append("")
            lines.append("Recent outputs")
            for label, path in list(self.state.outputs.items())[-2:]:
                lines.append(f"  {safe_text(label, max_length=22)}: {truncate_text(path, 68)}")
        if not lines:
            lines.append("Starting up...")
        return Panel("\n".join(lines), title="Activity", border_style="blue", box=box.ASCII)

    def _completion_panel(self) -> Panel:
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
            f"Elapsed:    {format_duration(self.state.elapsed(now))}",
            f"Phases:     {counts['done']} done, {counts['failed']} failed, {counts['skipped']} skipped",
            f"Properties: {format_count(self.state.properties_analysed)}",
            f"Warnings:   {len(self.state.warnings)}",
            "",
            f"Open first: {truncate_text(open_first, 80)}",
        ]
        for label, path in paths.items():
            lines.append(f"  {safe_text(label, max_length=22)}: {truncate_text(path, 66)}")
        return Panel(
            "\n".join(lines),
            title="HeatStreet Studio - Complete",
            border_style="green",
            box=box.ASCII,
        )

    def _phase_position(self):
        total = max(len(self.state.phases), 1)
        if self.state.current_phase and self.state.current_phase in self.state.phases:
            return list(self.state.phases.keys()).index(self.state.current_phase) + 1, total
        return total, total
