"""HeatStreet Studio - Textual full-screen TUI application.

Runs the Textual app in the main thread.
The analysis pipeline runs in a background thread.
Events flow from pipeline -> queue.Queue -> app._poll_events -> widget updates.
"""

from __future__ import annotations

import contextlib
import queue
import threading
import time
from typing import Any, Callable, Dict, Iterator, List, Optional

from .live_dashboard import DashboardState, COMPLETION_LABELS
from .formatters import (
    format_count,
    format_duration,
    format_path,
    phase_label,
    safe_text,
    truncate_text,
    format_currency,
    format_carbon,
)
from .icons import get_icons, IconSet, phase_icon
from src.modeling.contracts import TIER_READINESS_LABELS

try:
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
    from textual.reactive import reactive
    from textual.screen import ModalScreen
    from textual.widgets import (
        Button,
        DataTable,
        Footer,
        Header,
        Input,
        Label,
        ListItem,
        ListView,
        Log,
        ProgressBar,
        RichLog,
        Static,
        TabbedContent,
        TabPane,
    )
    _TEXTUAL_AVAILABLE = True
except ImportError:
    _TEXTUAL_AVAILABLE = False


# ------------------------------------------------------------------
# CSS theme
# ------------------------------------------------------------------

MODAL_CSS = """
TextInputModal {
    align: center middle;
}
TextInputModal > #dialog {
    padding: 1 2;
    width: 64;
    height: 13;
    border: solid #58a6ff;
    background: #161b22;
}
TextInputModal #input-label {
    padding: 0 0 1 0;
    color: #c9d1d9;
}
TextInputModal Input {
    background: #21262d;
    border: solid #30363d;
    color: #c9d1d9;
    width: 100%;
}
TextInputModal #validation-msg {
    color: #f85149;
    height: 1;
}
TextInputModal #btn-row {
    align: right middle;
    padding: 1 0 0 0;
    height: 3;
}

SelectModal {
    align: center middle;
}
SelectModal > #dialog {
    padding: 1 2;
    width: 64;
    border: solid #58a6ff;
    background: #161b22;
}
SelectModal #select-label {
    padding: 0 0 1 0;
    color: #c9d1d9;
}
SelectModal ListView {
    background: #0d1117;
    border: solid #30363d;
    height: auto;
    max-height: 14;
}
SelectModal ListItem {
    padding: 0 1;
}
SelectModal ListItem:hover {
    background: #21262d;
}
SelectModal ListItem.--highlight {
    background: #1c2940;
    color: #58a6ff;
}
SelectModal #btn-row {
    align: right middle;
    padding: 1 0 0 0;
    height: 3;
}
"""

APP_CSS = """
Screen {
    background: #0d1117;
    color: #c9d1d9;
}

Header {
    background: #161b22;
    color: #58a6ff;
    height: 1;
}

Footer {
    background: #161b22;
    color: #8b949e;
    height: 1;
}

.panel-title {
    background: #21262d;
    color: #58a6ff;
    padding: 0 1;
}

.phase-rail {
    width: 28;
    background: #161b22;
    border-right: solid #30363d;
}

.phase-running {
    color: #58a6ff;
    text-style: bold;
}

.phase-completed {
    color: #3fb950;
}

.phase-failed {
    color: #f85149;
    text-style: bold;
}

.phase-skipped {
    color: #8b949e;
}

.phase-waiting {
    color: #d29922;
}

.phase-pending {
    color: #6e7681;
}

.current-phase-card {
    background: #161b22;
    border: solid #30363d;
    padding: 0 1;
    margin: 0 1;
}

.metrics-card {
    background: #161b22;
    border: solid #21262d;
    padding: 0 1;
    margin: 0;
}

.scenario-running {
    background: #1c2940;
    color: #58a6ff;
}

.tier-1 { color: #3fb950; }
.tier-2 { color: #7ee787; }
.tier-3 { color: #d29922; }
.tier-4 { color: #f0883e; }
.tier-5 { color: #f85149; }

.warning-item {
    color: #d29922;
    padding: 0 1;
}

.output-recommended {
    color: #3fb950;
    text-style: bold;
}

.tab-content {
    padding: 1;
}

TabbedContent ContentTab {
    background: #0d1117;
}

Button {
    background: #21262d;
    border: solid #30363d;
    color: #c9d1d9;
    margin: 0 1;
}

Button.-primary {
    background: #1f6feb;
    color: white;
}

Button:hover {
    background: #30363d;
}

ProgressBar > .bar--bar {
    color: #58a6ff;
}

ProgressBar > .bar--complete {
    color: #3fb950;
}

DataTable {
    background: #0d1117;
}

DataTable > .datatable--header {
    background: #161b22;
    color: #58a6ff;
}

DataTable > .datatable--cursor {
    background: #1c2940;
}

RichLog {
    background: #0d1117;
}
"""


# ------------------------------------------------------------------
# Confirmation modal
# ------------------------------------------------------------------

if _TEXTUAL_AVAILABLE:
    class ConfirmModal(ModalScreen):
        """Simple yes/no confirmation modal."""

        CSS = """
        ConfirmModal {
            align: center middle;
        }
        #dialog {
            grid-size: 2;
            grid-gutter: 1 2;
            grid-rows: 1fr 3;
            padding: 1 2;
            width: 50;
            height: 11;
            border: solid #58a6ff;
            background: #161b22;
        }
        #question {
            column-span: 2;
            height: 1fr;
            width: 1fr;
            content-align: center middle;
        }
        Button { width: 100%; }
        """

        def __init__(self, question: str, **kwargs) -> None:
            super().__init__(**kwargs)
            self._question = question

        def compose(self) -> ComposeResult:
            yield Container(
                Label(self._question, id="question"),
                Button("Yes", variant="error", id="yes"),
                Button("No", variant="primary", id="no"),
                id="dialog",
            )

        def on_button_pressed(self, event: Button.Pressed) -> None:
            self.dismiss(event.button.id == "yes")

    class TextInputModal(ModalScreen):
        """Modal for a single-line text entry (e.g. date input)."""

        CSS = MODAL_CSS

        def __init__(
            self,
            title: str,
            message: str,
            default: str = "",
            validate_fn=None,
            **kwargs,
        ) -> None:
            super().__init__(**kwargs)
            self._title = title
            self._message = message
            self._default = default
            self._validate_fn = validate_fn

        def compose(self) -> ComposeResult:
            with Container(id="dialog"):
                yield Label(f"[bold cyan]{self._title}[/bold cyan]", id="input-label")
                yield Label(self._message)
                yield Input(value=self._default, id="text-input")
                yield Label("", id="validation-msg")
                with Horizontal(id="btn-row"):
                    yield Button("Cancel", variant="default", id="cancel")
                    yield Button("OK", variant="primary", id="ok")

        def on_mount(self) -> None:
            self.query_one("#text-input", Input).focus()

        def on_input_submitted(self, event: Input.Submitted) -> None:
            self._submit(event.value)

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "cancel":
                self.dismiss(None)
            else:
                value = self.query_one("#text-input", Input).value
                self._submit(value)

        def _submit(self, value: str) -> None:
            if self._validate_fn is not None:
                result = self._validate_fn(value)
                if result is not True:
                    msg = result if isinstance(result, str) else "Invalid input"
                    self.query_one("#validation-msg", Label).update(f"[red]{msg}[/red]")
                    return
            self.dismiss(value)

    class SelectModal(ModalScreen):
        """Modal for selecting one item from a list."""

        CSS = MODAL_CSS

        def __init__(
            self,
            title: str,
            message: str,
            choices: List[Any],
            choice_labels: Optional[List[str]] = None,
            **kwargs,
        ) -> None:
            super().__init__(**kwargs)
            self._title = title
            self._message = message
            self._choices = choices
            self._labels = choice_labels or [str(c) for c in choices]

        def compose(self) -> ComposeResult:
            with Container(id="dialog"):
                yield Label(f"[bold cyan]{self._title}[/bold cyan]", id="select-label")
                yield Label(self._message)
                yield ListView(
                    *[ListItem(Label(lbl)) for lbl in self._labels],
                    id="choice-list",
                )
                with Horizontal(id="btn-row"):
                    yield Button("Cancel", variant="default", id="cancel")
                    yield Button("Select", variant="primary", id="ok")

        def on_mount(self) -> None:
            self.query_one("#choice-list", ListView).focus()

        def on_list_view_selected(self, event: ListView.Selected) -> None:
            idx = event.list_view.index
            if idx is not None and 0 <= idx < len(self._choices):
                self.dismiss(self._choices[idx])

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "cancel":
                self.dismiss(None)
            else:
                lv = self.query_one("#choice-list", ListView)
                idx = lv.index
                if idx is not None and 0 <= idx < len(self._choices):
                    self.dismiss(self._choices[idx])
                else:
                    self.dismiss(None)


# ------------------------------------------------------------------
# Main application
# ------------------------------------------------------------------

if _TEXTUAL_AVAILABLE:
    class HeatStreetStudioApp(App):
        """Full-screen HeatStreet Studio TUI."""

        TITLE = "HeatStreet Studio"
        BINDINGS = [
            Binding("q", "request_quit", "Quit", priority=True),
            Binding("1", "switch_tab('overview')", "Overview", show=False),
            Binding("2", "switch_tab('acquisition')", "Acquisition", show=False),
            Binding("3", "switch_tab('validation')", "Validation", show=False),
            Binding("4", "switch_tab('archetypes')", "Archetypes", show=False),
            Binding("5", "switch_tab('scenarios')", "Scenarios", show=False),
            Binding("6", "switch_tab('retrofit')", "Retrofit", show=False),
            Binding("7", "switch_tab('spatial')", "Spatial", show=False),
            Binding("o", "switch_tab('outputs')", "Outputs"),
            Binding("l", "switch_tab('logs')", "Logs"),
            Binding("w", "toggle_warnings", "Warnings"),
            Binding("s", "switch_tab('scenarios')", "Scenarios", show=False),
            Binding("a", "switch_tab('acquisition')", "Acquisition", show=False),
            Binding("v", "switch_tab('validation')", "Validation", show=False),
            Binding("p", "pause_updates", "Pause", show=False),
            Binding("r", "resume_updates", "Resume", show=False),
            Binding("f", "toggle_log", "Full log", show=False),
        ]
        CSS = APP_CSS

        def __init__(
            self,
            state: DashboardState,
            event_queue: "queue.Queue",
            cancel_event: threading.Event,
            prompt_request_queue: Optional["queue.Queue"] = None,
            prompt_response_queue: Optional["queue.Queue"] = None,
            **kwargs,
        ) -> None:
            super().__init__(**kwargs)
            self._state = state
            self._event_queue = event_queue
            self._cancel_event = cancel_event
            self._prompt_request_queue = prompt_request_queue or queue.Queue()
            self._prompt_response_queue = prompt_response_queue or queue.Queue()
            self._icons = get_icons(unicode_ok=True)
            self._paused = False
            self._log_entries: List[str] = []
            self._warnings: List[Dict[str, str]] = []
            self._outputs: List[Dict[str, Any]] = []
            self._run_done = False
            self._prompt_active = False

        def compose(self) -> ComposeResult:
            yield Header()
            with TabbedContent(initial="overview", id="tabs"):
                with TabPane("Overview", id="overview"):
                    yield from self._compose_overview()
                with TabPane("Acquisition", id="acquisition"):
                    yield from self._compose_acquisition()
                with TabPane("Validation", id="validation"):
                    yield from self._compose_validation()
                with TabPane("Archetypes", id="archetypes"):
                    yield from self._compose_archetypes()
                with TabPane("Scenarios", id="scenarios"):
                    yield from self._compose_scenarios()
                with TabPane("Retrofit", id="retrofit"):
                    yield from self._compose_retrofit()
                with TabPane("Spatial", id="spatial"):
                    yield from self._compose_spatial()
                with TabPane("Outputs", id="outputs"):
                    yield from self._compose_outputs()
                with TabPane("Logs", id="logs"):
                    yield from self._compose_logs()
            yield Footer()

        # --- Tab composition ---

        def _compose_overview(self) -> ComposeResult:
            with Horizontal():
                yield Static("", id="phase-rail", classes="phase-rail")
                with Vertical():
                    yield Static("", id="current-phase-card", classes="current-phase-card")
                    yield Static("", id="global-progress", classes="metrics-card")
                    yield Static("", id="overview-metrics", classes="metrics-card")

        def _compose_acquisition(self) -> ComposeResult:
            yield Static("", id="acq-flow", classes="current-phase-card")
            yield Static("", id="acq-counters", classes="metrics-card")

        def _compose_validation(self) -> ComposeResult:
            yield Static("", id="val-funnel", classes="current-phase-card")
            yield Static("", id="val-quality", classes="metrics-card")

        def _compose_archetypes(self) -> ComposeResult:
            yield Static("", id="arch-cards", classes="current-phase-card")
            yield Static("", id="arch-epc-dist", classes="metrics-card")

        def _compose_scenarios(self) -> ComposeResult:
            yield Static("", id="scenario-board-header", classes="panel-title")
            yield DataTable(id="scenario-table")
            yield Static("", id="scenario-comparison", classes="metrics-card")

        def _compose_retrofit(self) -> ComposeResult:
            yield Static("", id="retrofit-grid", classes="current-phase-card")
            yield Static("", id="retrofit-investment", classes="metrics-card")

        def _compose_spatial(self) -> ComposeResult:
            yield Static("", id="spatial-deps", classes="current-phase-card")
            yield Static("", id="spatial-steps", classes="metrics-card")

        def _compose_outputs(self) -> ComposeResult:
            with ScrollableContainer():
                yield Static("", id="output-launcher", classes="tab-content")

        def _compose_logs(self) -> ComposeResult:
            yield RichLog(id="log-panel", highlight=True, markup=True)

        # --- Lifecycle ---

        def on_mount(self) -> None:
            self._setup_scenario_table()
            self.set_interval(0.25, self._poll_events)

        def _setup_scenario_table(self) -> None:
            table = self.query_one("#scenario-table", DataTable)
            table.add_columns("Scenario", "Status", "Properties", "Mean Capex", "Carbon", "Output")
            table.cursor_type = "row"

        # --- Event polling (runs on Textual timer, UI thread safe) ---

        def _poll_events(self) -> None:
            # Service prompt requests (highest priority - pipeline is blocked)
            if not self._prompt_active:
                try:
                    request = self._prompt_request_queue.get_nowait()
                    self._handle_prompt_request(request)
                except queue.Empty:
                    pass

            if self._paused:
                return
            processed = 0
            while processed < 50:
                try:
                    event = self._event_queue.get_nowait()
                except queue.Empty:
                    break
                self._apply_event(event)
                processed += 1
            if processed > 0:
                self._refresh_all_widgets()

        def _handle_prompt_request(self, request: Dict) -> None:
            """Show the appropriate modal for a prompt request from the pipeline thread."""
            self._prompt_active = True
            prompt_type = request.get("type", "text")

            def _send_response(value) -> None:
                self._prompt_active = False
                self._prompt_response_queue.put(value)

            if prompt_type == "confirm":
                question = request.get("message", "Continue?")
                self.push_screen(ConfirmModal(question), _send_response)

            elif prompt_type == "select":
                title = request.get("title", "Select")
                message = request.get("message", "Choose an option:")
                choices = request.get("choices", [])
                labels = request.get("labels", None)
                self.push_screen(
                    SelectModal(title, message, choices, labels),
                    _send_response,
                )

            else:  # "text" or "date"
                title = request.get("title", "Input required")
                message = request.get("message", "Enter value:")
                default = request.get("default", "")
                validate_fn = request.get("validate_fn", None)
                self.push_screen(
                    TextInputModal(title, message, default, validate_fn),
                    _send_response,
                )

        def _apply_event(self, event) -> None:
            t = event.event_type
            state = self._state

            if t == "run_started":
                self._log(f"[cyan]Run started[/cyan]: {safe_text(event.message, max_length=80)}")

            elif t in ("phase_started", "phase_progress"):
                phase = phase_label(event.phase or event.message)
                msg = safe_text(event.message, max_length=80)
                self._log(f"[cyan]{phase}[/cyan]: {msg}")

            elif t == "phase_completed":
                phase = phase_label(event.phase or event.message)
                self._log(f"[green][+] {phase} complete[/green]")

            elif t in ("phase_failed",):
                phase = phase_label(event.phase or event.message)
                self._log(f"[red][x] {phase} FAILED: {safe_text(event.message, max_length=80)}[/red]")

            elif t == "phase_skipped":
                phase = phase_label(event.phase or event.message)
                self._log(f"[bright_black][-] {phase} skipped[/bright_black]")

            elif t == "warning":
                msg = safe_text(event.message, max_length=120)
                self._log(f"[yellow][!] Warning: {msg}[/yellow]")
                self._warnings.append({"message": msg, "phase": event.phase or "", "severity": "warning"})

            elif t == "info":
                msg = safe_text(event.message, max_length=120)
                self._log(f"[dim]{msg}[/dim]")

            elif t == "output_registered":
                label = safe_text(event.message, max_length=38)
                path = safe_text(event.value, max_length=120)
                self._outputs.append({"label": label, "path": path, "type": "file"})
                self._log(f"[green]Output:[/green] {label}")

            elif t == "run_completed":
                self._run_done = True
                self._log("[bold green]Run complete[/bold green]")
                self.action_switch_tab("outputs")

            elif t == "run_failed":
                self._run_done = True
                self._log(f"[bold red]Run failed:[/bold red] {safe_text(event.message, max_length=80)}")

            elif t == "scenario_started":
                name = safe_text(event.message or (event.phase or ""), max_length=30)
                self._update_scenario_table(name, "running", {})

            elif t == "scenario_completed":
                name = safe_text(event.message or (event.phase or ""), max_length=30)
                metrics = event.payload or {}
                self._update_scenario_table(name, "completed", metrics)

            elif t == "prompt_pending":
                msg = safe_text(event.message, max_length=80)
                self._log(f"[yellow]Waiting: {msg}[/yellow]")

        def _update_scenario_table(self, name: str, status: str, metrics: Dict) -> None:
            table = self.query_one("#scenario-table", DataTable)
            props = format_count(metrics.get("properties_processed"))
            capex = format_currency(metrics.get("mean_capex")) if metrics.get("mean_capex") else "-"
            carbon = format_carbon(metrics.get("carbon_impact")) if metrics.get("carbon_impact") else "-"
            out_status = safe_text(metrics.get("output_status", "-"), max_length=12)
            status_str = "[green]done[/green]" if status == "completed" else f"[cyan]{status}[/cyan]"
            try:
                key = name
                row_exists = any(
                    table.get_row(r)[0] == name
                    for r in table.rows
                )
                if row_exists:
                    table.update_cell(key, "Status", status_str)
                else:
                    table.add_row(name, status_str, props, capex, carbon, out_status, key=key)
            except Exception:
                try:
                    table.add_row(name, status_str, props, capex, carbon, out_status)
                except Exception:
                    pass

        def _log(self, message: str) -> None:
            self._log_entries.append(message)
            try:
                log_panel = self.query_one("#log-panel", RichLog)
                log_panel.write(message)
            except Exception:
                pass

        # --- Widget refresh ---

        def _refresh_all_widgets(self) -> None:
            state = self._state
            self._refresh_phase_rail(state)
            self._refresh_current_phase_card(state)
            self._refresh_global_progress(state)
            self._refresh_acquisition(state)
            self._refresh_validation(state)
            self._refresh_archetypes(state)
            self._refresh_scenario_comparison(state)
            self._refresh_retrofit(state)
            self._refresh_spatial(state)
            self._refresh_output_launcher(state)

        def _refresh_phase_rail(self, state: DashboardState) -> None:
            lines = []
            all_phases = list(state.phases.keys())
            for i, (name, status) in enumerate(state.phases.items()):
                icon = self._icons.for_status(status)
                num = str(i + 1).rjust(2)
                truncated = safe_text(name, max_length=18)
                is_current = name == state.current_phase
                prefix = "> " if is_current else "  "
                cls = {
                    "completed": "phase-completed",
                    "running": "phase-running",
                    "failed": "phase-failed",
                    "skipped": "phase-skipped",
                    "waiting": "phase-waiting",
                }.get(status, "phase-pending")
                lines.append(f"{prefix}{icon} {num} {truncated}")
            content = "\n".join(lines) or "Waiting..."
            try:
                self.query_one("#phase-rail", Static).update(content)
            except Exception:
                pass

        def _refresh_current_phase_card(self, state: DashboardState) -> None:
            now = time.time()
            phase = state.current_phase or "No active phase"
            started = state.phase_started_at.get(phase)
            elapsed_str = format_duration(now - started) if started else "-"
            current = state.progress_current
            total = state.progress_total
            bar_str = ""
            if current is not None and total:
                pct = max(0.0, min(1.0, float(current) / float(total)))
                filled = int(round(pct * 24))
                bar_str = f"\n[{'#' * filled}{'.' * (24 - filled)}] {pct * 100:.1f}% ({format_count(current)}/{format_count(total)})"
            content = (
                f"[bold cyan]{phase_label(phase)}[/bold cyan]\n"
                f"{safe_text(state.current_action, max_length=72)}\n"
                f"Elapsed: {elapsed_str}{bar_str}"
            )
            try:
                self.query_one("#current-phase-card", Static).update(content)
            except Exception:
                pass

        def _refresh_global_progress(self, state: DashboardState) -> None:
            done = state.phase_count_done()
            total = state.phase_count_total()
            now = time.time()
            elapsed = format_duration(state.elapsed(now))
            pct = (done / total * 100) if total else 0
            filled = int(round(pct / 100 * 40))
            bar = f"[{'#' * filled}{'.' * (40 - filled)}]"
            content = f"Global: {bar} {done}/{total} phases  Elapsed: {elapsed}"
            try:
                self.query_one("#global-progress", Static).update(content)
            except Exception:
                pass

        def _refresh_acquisition(self, state: DashboardState) -> None:
            acq = state.acquisition
            flow_line = (
                f"API {self._icons.arrow_right} ZIP "
                f"[{'done' if acq.zip_status == 'done' else 'working...'}] "
                f"{self._icons.arrow_right} Parquet "
                f"({format_count(acq.parquet_parts)} parts) "
                f"{self._icons.arrow_right} London "
                f"({format_count(acq.london_records)}) "
                f"{self._icons.arrow_right} Stock "
                f"({format_count(acq.stock_records)})"
            )
            counters = (
                f"Rows read: {format_count(acq.rows_read)}  "
                f"Retained: {format_count(acq.rows_retained)}  "
                f"Malformed: {format_count(acq.rows_malformed)}  "
                f"Members: {format_count(acq.members_processed)}"
            )
            throughput = ""
            if acq.rows_per_second:
                throughput = f"  {acq.rows_per_second:,.0f} rows/s"
            content = f"[bold]Acquisition Flow[/bold]\n{flow_line}\n{counters}{throughput}"
            try:
                self.query_one("#acq-flow", Static).update(content)
            except Exception:
                pass

        def _refresh_validation(self, state: DashboardState) -> None:
            v = state.validation
            lines = ["[bold]Validation Funnel[/bold]"]
            steps = [
                ("Input records", v.input_records),
                ("Schema passed", v.schema_passed),
                ("After dedup", v.after_dedup),
                ("Plausibility passed", v.plausibility_passed),
                ("Output records", v.output_records),
            ]
            max_val = max((s[1] for s in steps if s[1] is not None), default=1) or 1
            for label, val in steps:
                if val is not None:
                    width = int(round(val / max_val * 30))
                    bar = "#" * width + "." * (30 - width)
                    pct = val / max_val * 100
                    lines.append(f"  {label:<26} [{bar}] {format_count(val)} ({pct:.1f}%)")
            if v.validation_rate is not None:
                lines.append(f"\n  Validation rate: {v.validation_rate:.1f}%")
            if v.warnings:
                lines.append(f"  Warnings: {v.warnings}")
            try:
                self.query_one("#val-funnel", Static).update("\n".join(lines))
            except Exception:
                pass

        def _refresh_archetypes(self, state: DashboardState) -> None:
            arch = state.archetype
            lines = [
                "[bold]Archetype Analysis[/bold]",
                f"Total properties:    {format_count(arch.total_properties)}",
                f"Pre-1930 terraced:   {format_count(arch.pre_1930_terraced)}",
                f"Dominant EPC band:   {safe_text(arch.dominant_epc_band or '-', max_length=10)}",
                f"Most common wall:    {safe_text(arch.most_common_wall_type or '-', max_length=30)}",
                f"Most common heating: {safe_text(arch.most_common_heating or '-', max_length=30)}",
            ]
            if arch.epc_distribution:
                lines.append("\nEPC Distribution:")
                max_count = max(arch.epc_distribution.values(), default=1) or 1
                for band, count in sorted(arch.epc_distribution.items()):
                    width = int(round(count / max_count * 20))
                    bar = "#" * width + "." * (20 - width)
                    lines.append(f"  {band}: [{bar}] {format_count(count)}")
            try:
                self.query_one("#arch-cards", Static).update("\n".join(lines))
            except Exception:
                pass

        def _refresh_scenario_comparison(self, state: DashboardState) -> None:
            rows = state.scenario_rows
            if not rows:
                content = "Waiting for scenario results..."
            else:
                lines = ["[bold]Scenario Comparison[/bold]"]
                for name, values in list(rows.items())[:8]:
                    cost = safe_text(values.get("Cost/property", "-"), max_length=14)
                    status = safe_text(values.get("Status", "-"), max_length=12)
                    lines.append(f"  {safe_text(name, max_length=22):<24} {status:<14} {cost}")
                content = "\n".join(lines)
            try:
                self.query_one("#scenario-comparison", Static).update(content)
            except Exception:
                pass

        def _refresh_retrofit(self, state: DashboardState) -> None:
            r = state.retrofit
            TIER_LABELS = [TIER_READINESS_LABELS[tier] for tier in range(1, 6)]
            TIER_COLOURS = ["green", "bright_green", "yellow", "orange3", "red"]
            counts = r.counts()
            total = r.total() or 1
            lines = ["[bold]Retrofit Readiness[/bold]"]
            for i, (label, count) in enumerate(zip(TIER_LABELS, counts)):
                if count is None:
                    continue
                pct = count / total * 100
                width = int(round(pct / 100 * 24))
                bar = "#" * width + "." * (24 - width)
                colour = TIER_COLOURS[i]
                lines.append(
                    f"  [{colour}]{label:<22}[/{colour}] [{bar}] "
                    f"{format_count(count)} ({pct:.1f}%)"
                )
            if r.total_investment is not None:
                lines.append(f"\nTotal investment: {format_currency(r.total_investment)}")
            if r.mean_fabric_cost is not None:
                lines.append(f"Mean fabric cost: {format_currency(r.mean_fabric_cost)}")
            try:
                self.query_one("#retrofit-grid", Static).update("\n".join(lines))
            except Exception:
                pass

        def _refresh_spatial(self, state: DashboardState) -> None:
            sp = state.spatial
            lines = ["[bold]Spatial Analysis[/bold]", "", "Dependencies:"]
            deps = [
                ("geopandas", sp.geopandas_ok),
                ("shapely", sp.shapely_ok),
                ("pyproj", sp.pyproj_ok),
                ("pyogrio/fiona", sp.pyogrio_ok if sp.pyogrio_ok is not None else sp.fiona_ok),
                ("GDAL", sp.gdal_ok),
            ]
            for dep, ok in deps:
                if ok is None:
                    icon = "[ ]"
                    colour = "white"
                elif ok:
                    icon = "[+]"
                    colour = "green"
                else:
                    icon = "[x]"
                    colour = "red"
                lines.append(f"  [{colour}]{icon}[/{colour}] {dep}")
            if sp.current_step:
                lines.append(f"\nStep: {sp.current_step}")
            if sp.steps_done:
                lines.append(f"Done: {', '.join(sp.steps_done[-3:])}")
            if sp.tier_counts:
                lines.append("\nHeat network tier counts:")
                for tier, count in sp.tier_counts.items():
                    lines.append(f"  {safe_text(tier, max_length=20)}: {format_count(count)}")
            try:
                self.query_one("#spatial-deps", Static).update("\n".join(lines))
            except Exception:
                pass

        def _refresh_output_launcher(self, state: DashboardState) -> None:
            paths = state.completion_paths
            all_outputs = dict(state.outputs)
            all_outputs.update(paths)
            if not all_outputs and not self._outputs:
                content = "No outputs registered yet. Outputs will appear here as the run progresses."
            else:
                lines = ["[bold]Output Launcher[/bold]", ""]
                groups: Dict[str, list] = {
                    "Open First": [],
                    "Reports": [],
                    "Data files": [],
                    "Figures": [],
                    "Maps": [],
                    "Logs": [],
                    "Other": [],
                }
                for label, path in all_outputs.items():
                    lbl = label.lower()
                    if "dashboard" in lbl or "html" in lbl or "json" in lbl:
                        groups["Open First"].append((label, path))
                    elif "report" in lbl or "workbook" in lbl or "xlsx" in lbl:
                        groups["Reports"].append((label, path))
                    elif "figure" in lbl or "chart" in lbl or "plot" in lbl:
                        groups["Figures"].append((label, path))
                    elif "map" in lbl or "geo" in lbl:
                        groups["Maps"].append((label, path))
                    elif "log" in lbl:
                        groups["Logs"].append((label, path))
                    else:
                        groups["Data files"].append((label, path))
                for entry in self._outputs:
                    groups["Other"].append((entry["label"], entry["path"]))
                for group_name, items in groups.items():
                    if not items:
                        continue
                    lines.append(f"[bold cyan]{group_name}[/bold cyan]")
                    for label, path in items:
                        lines.append(
                            f"  [green]{safe_text(label, max_length=28)}[/green]  "
                            f"{truncate_text(path, 60)}"
                        )
                    lines.append("")
                content = "\n".join(lines)
            try:
                self.query_one("#output-launcher", Static).update(content)
            except Exception:
                pass

        # --- Actions ---

        def action_switch_tab(self, tab_id: str) -> None:
            try:
                self.query_one(TabbedContent).active = tab_id
            except Exception:
                pass

        def action_request_quit(self) -> None:
            def _check_result(confirmed: bool) -> None:
                if confirmed:
                    self._cancel_event.set()
                    self.exit()

            self.push_screen(ConfirmModal("Request cancellation and exit?"), _check_result)

        def action_pause_updates(self) -> None:
            self._paused = True

        def action_resume_updates(self) -> None:
            self._paused = False

        def action_toggle_warnings(self) -> None:
            self.action_switch_tab("logs")

        def action_toggle_log(self) -> None:
            self.action_switch_tab("logs")


# ------------------------------------------------------------------
# TextualUIAdapter - implements DashboardBase interface over the app
# ------------------------------------------------------------------

class TextualUIAdapter:
    """Bridges DashboardBase API calls to HeatStreetStudioApp via a queue.

    This adapter runs in the pipeline thread and is the single consumer
    of the DashboardBase interface.  The Textual app polls the queue.
    """

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
        state: Optional[DashboardState] = None,
        time_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        from .live_dashboard import DashboardState as _DS, DashboardBase as _DB
        self.enabled = bool(enabled and not quiet)
        self.quiet = bool(quiet)
        self.verbose = bool(verbose)
        self._state = state or _DS()
        self._time = time_fn or time.time
        self._event_queue: queue.Queue = queue.Queue()
        self._cancel_event = threading.Event()
        self._prompt_request_queue: queue.Queue = queue.Queue()
        self._prompt_response_queue: queue.Queue = queue.Queue()
        self._app: Optional["HeatStreetStudioApp"] = None
        self._thread: Optional[threading.Thread] = None
        # Delegate state management to DashboardBase methods
        self._base = _DB(state=self._state, time_fn=self._time)
        self.allow_console_output = False

    @property
    def state(self) -> DashboardState:
        return self._state

    @property
    def metrics(self):
        return self._state.metrics

    @property
    def outputs(self):
        return self._state.outputs

    @property
    def warnings(self):
        return self._state.warnings

    @property
    def events(self):
        return self._state.events

    @property
    def is_live_active(self) -> bool:
        return self._app is not None

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def __enter__(self) -> "TextualUIAdapter":
        self._start_app()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is not None:
            self._guard(self.run_failed, str(exc))
        self._stop_app()
        return False

    def _start_app(self) -> None:
        if not _TEXTUAL_AVAILABLE or not self.enabled:
            return
        self._app = HeatStreetStudioApp(
            state=self._state,
            event_queue=self._event_queue,
            cancel_event=self._cancel_event,
            prompt_request_queue=self._prompt_request_queue,
            prompt_response_queue=self._prompt_response_queue,
        )
        self._state.start_time = self._state.start_time or self._time()
        # The Textual app runs in the main thread; pipeline runs in a bg thread

    def _stop_app(self) -> None:
        if self._app is not None:
            try:
                self._app.exit()
            except Exception:
                pass

    def _guard(self, func, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            return None

    def _enqueue(self, event_type: str, **kwargs) -> None:
        from .events import UIEvent
        try:
            event = UIEvent(event_type=event_type, **kwargs)
            self._event_queue.put_nowait(event)
        except Exception:
            pass

    def _update_state(self, method_name: str, *args, **kwargs) -> None:
        try:
            method = getattr(self._base, method_name, None)
            if method:
                method(*args, **kwargs)
        except Exception:
            pass

    # --- DashboardBase interface ---

    def emit(self, event) -> None:
        self._guard(self._base.emit, event)
        try:
            self._event_queue.put_nowait(event)
        except Exception:
            pass

    def start(self) -> None:
        self._state.start_time = self._state.start_time or self._time()

    def stop(self) -> None:
        self._stop_app()

    def run_started(self, message: str = "") -> None:
        self._update_state("run_started", message)
        self._enqueue("run_started", message=message)

    def run_completed(self, **kwargs) -> None:
        self._update_state("run_completed", **kwargs)
        self._enqueue("run_completed", payload=kwargs)

    def run_failed(self, message: str = "") -> None:
        self._update_state("run_failed", message)
        self._enqueue("run_failed", message=message)

    def phase_started(self, name: str, message: str = "") -> None:
        self._update_state("phase_started", name, message)
        self._enqueue("phase_started", phase=name, message=message)

    def phase_progress(self, name=None, message: str = "") -> None:
        self._update_state("phase_progress", name, message)
        self._enqueue("phase_progress", phase=name or "", message=message)

    def phase_completed(self, name: str, message: str = "") -> None:
        self._update_state("phase_completed", name, message)
        self._enqueue("phase_completed", phase=name, message=message)

    def phase_failed(self, name: str, message: str = "") -> None:
        self._update_state("phase_failed", name, message)
        self._enqueue("phase_failed", phase=name, message=message)

    def phase_skipped(self, name: str, reason: str = "") -> None:
        self._update_state("phase_skipped", name, reason)
        self._enqueue("phase_skipped", phase=name, message=reason)

    def progress(self, current=None, total=None, *, label: str = "") -> None:
        self._update_state("progress", current, total, label=label)

    def set_current_action(self, text: str) -> None:
        self._update_state("phase_progress", None, text)

    def metric(self, key: str, value, *, group=None, label=None, unit=None) -> None:
        self._update_state("metric", key, value, group=group)
        self._enqueue("metric_updated", metric=key, value=value, group=group)

    def counter(self, key: str, value, *, group=None, label=None) -> None:
        self.metric(key, value, group=group)
        self._enqueue("counter_updated", counter_key=key, counter_value=value, group=group)

    def output(self, path, output_type=None, description=None, recommended=False) -> None:
        label = safe_text(str(path), max_length=38)
        formatted = format_path(path, max_length=96)
        self._state.outputs[label] = formatted
        self._enqueue("output_registered", message=label, value=formatted)

    def warning(self, message: str, phase=None, blocking: bool = False) -> None:
        self._update_state("warning", message)
        self._enqueue("warning", message=message, phase=phase or "")

    def info(self, message: str) -> None:
        self._update_state("info", message)
        self._enqueue("info", message=message)

    def visualization(self, path, kind: str, description: str = "") -> None:
        if path:
            self._state.svg_assets[kind] = str(path)
            self.output(path, output_type="figure", description=description)

    def scenario_started(self, name: str) -> None:
        self._enqueue("scenario_started", message=name)

    def scenario_progress(self, name: str, completed=None, total=None, metrics=None) -> None:
        self._enqueue("scenario_progress", phase=name, payload={"completed": completed, "total": total, "metrics": metrics or {}})

    def scenario_completed(self, name: str, metrics=None, outputs=None) -> None:
        self._update_state("_update_scenario_row", f"{name} status", "complete")
        self._enqueue("scenario_completed", message=name, payload=metrics or {})

    def prompt_pending(self, message: str) -> None:
        self._update_state("prompt_pending", message)
        self._enqueue("prompt_pending", message=message)

    def prompt_completed(self, message: str = "") -> None:
        self._update_state("prompt_completed", message)
        self._enqueue("prompt_completed", message=message)

    def register_metrics(self, metrics, *, group=None) -> None:
        for key, value in metrics.items():
            self.metric(key, value, group=group)

    def register_outputs(self, outputs) -> None:
        for label, path in outputs:
            self.output(path)

    def prompt_request(
        self,
        prompt_type: str,
        *,
        title: str = "Input required",
        message: str = "",
        default: str = "",
        choices: Optional[List] = None,
        labels: Optional[List[str]] = None,
        validate_fn=None,
        timeout: float = 600.0,
    ) -> Optional[Any]:
        """Send a prompt request to the Textual UI and block until answered.

        Returns the user's response, or None if cancelled/timed out.
        This is called from the pipeline background thread.
        """
        if self._app is None:
            return None
        request = {
            "type": prompt_type,
            "title": title,
            "message": message,
            "default": default,
            "choices": choices or [],
            "labels": labels,
            "validate_fn": validate_fn,
        }
        self.prompt_pending(message or title)
        self._prompt_request_queue.put(request)
        try:
            response = self._prompt_response_queue.get(timeout=timeout)
            self.prompt_completed(str(response) if response is not None else "cancelled")
            return response
        except queue.Empty:
            self.prompt_completed("timed out")
            return None

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


# ------------------------------------------------------------------
# Entry point for running with Textual
# ------------------------------------------------------------------

def run_with_textual(
    pipeline_fn: Callable,
    *,
    state: Optional[DashboardState] = None,
    enabled: bool = True,
    quiet: bool = False,
    verbose: bool = False,
) -> int:
    """Run pipeline_fn in a background thread while HeatStreetStudioApp runs in main.

    Returns the pipeline exit code (0 = success, non-zero = failure).
    """
    if not _TEXTUAL_AVAILABLE:
        raise RuntimeError("textual is not installed. Install with: pip install textual>=0.47.0")

    from .live_dashboard import DashboardState as _DS
    state = state or _DS()
    cancel_event = threading.Event()
    event_queue: queue.Queue = queue.Queue()
    result_holder: Dict[str, Any] = {"exit_code": 0, "error": None}

    adapter = TextualUIAdapter(enabled=enabled, quiet=quiet, verbose=verbose, state=state)
    adapter._cancel_event = cancel_event
    adapter._event_queue = event_queue

    def _run_pipeline() -> None:
        try:
            pipeline_fn(adapter)
        except KeyboardInterrupt:
            result_holder["exit_code"] = 130
        except SystemExit as e:
            result_holder["exit_code"] = e.code or 0
        except Exception as exc:
            result_holder["exit_code"] = 1
            result_holder["error"] = str(exc)
            try:
                adapter.run_failed(str(exc))
            except Exception:
                pass

    pipeline_thread = threading.Thread(target=_run_pipeline, daemon=True, name="hs-pipeline")

    app = HeatStreetStudioApp(
        state=state,
        event_queue=event_queue,
        cancel_event=cancel_event,
    )
    adapter._app = app

    pipeline_thread.start()
    app.run()
    cancel_event.set()
    pipeline_thread.join(timeout=30)

    return result_holder["exit_code"]
