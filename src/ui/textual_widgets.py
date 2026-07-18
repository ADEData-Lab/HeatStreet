"""Custom Textual widgets for HeatStreet Studio.

Each widget is a self-contained Static or compound widget that
accepts state updates via its update_* methods.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .formatters import (
    format_count,
    format_currency,
    format_carbon,
    format_duration,
    format_path,
    phase_label,
    safe_text,
    truncate_text,
)
from .icons import get_icons, IconSet
from src.modeling.contracts import TIER_READINESS_LABELS

try:
    from textual.widgets import Static, DataTable, RichLog, ListView, ListItem, Label
    from textual.containers import Horizontal, Vertical, ScrollableContainer
    _TEXTUAL_AVAILABLE = True
except ImportError:
    _TEXTUAL_AVAILABLE = False


_STATUS_MARKUP = {
    "completed": "green",
    "running": "cyan",
    "waiting": "yellow",
    "failed": "red",
    "skipped": "bright_black",
    "pending": "white dim",
}


def _status_markup(status: str, text: str) -> str:
    colour = _STATUS_MARKUP.get(status, "white")
    return f"[{colour}]{text}[/{colour}]"


if _TEXTUAL_AVAILABLE:

    class HeaderBar(Static):
        """Top header showing run title, elapsed time and phase progress."""

        def update_state(self, state) -> None:
            import time
            now = time.time()
            elapsed = format_duration(state.elapsed(now))
            done = state.phase_count_done()
            total = state.phase_count_total()
            phase = phase_label(state.current_phase or "Idle")
            sample = ""
            if state.sample_start or state.sample_end:
                sample = f"  |  Sample: {state.sample_start or '?'} to {state.sample_end or '?'}"
            content = (
                f"[bold cyan]HeatStreet Studio[/bold cyan]  |  "
                f"Elapsed: {elapsed}  |  "
                f"Phases: {done}/{total}  |  "
                f"[cyan]{phase}[/cyan]"
                f"{sample}"
            )
            self.update(content)

    class PhaseRail(Static):
        """Vertical phase list showing status icons, numbers and names."""

        def __init__(self, *args, icons: Optional[IconSet] = None, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._icons = icons or get_icons(unicode_ok=True)

        def update_state(self, state) -> None:
            lines = []
            for i, (name, status) in enumerate(state.phases.items()):
                icon = self._icons.for_status(status)
                num = str(i + 1).rjust(2)
                truncated = safe_text(name, max_length=18)
                is_current = name == state.current_phase
                prefix = "> " if is_current else "  "
                colour = _STATUS_MARKUP.get(status, "white dim")
                lines.append(f"{prefix}[{colour}]{icon} {num} {truncated}[/{colour}]")
            self.update("\n".join(lines) or "Starting...")

    class CurrentPhasePanel(Static):
        """Large card showing current phase, action, elapsed time and progress."""

        def update_state(self, state) -> None:
            import time
            now = time.time()
            phase = state.current_phase or "No active phase"
            started = state.phase_started_at.get(phase)
            elapsed = format_duration(now - started) if started else "-"
            action = safe_text(state.current_action, max_length=70)
            current = state.progress_current
            total = state.progress_total
            bar_str = ""
            if current is not None and total:
                pct = max(0.0, min(1.0, float(current) / float(total)))
                filled = int(round(pct * 30))
                bar_str = f"\n[{'#' * filled}{'.' * (30 - filled)}] {pct * 100:.1f}% ({format_count(current)}/{format_count(total)})"
            content = (
                f"[bold cyan]{phase_label(phase)}[/bold cyan]\n"
                f"{action}\n"
                f"Phase elapsed: {elapsed}"
                f"{bar_str}"
            )
            self.update(content)

    class AcquisitionFlow(Static):
        """Left-to-right acquisition pipeline flow with counters."""

        def __init__(self, *args, icons: Optional[IconSet] = None, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._icons = icons or get_icons(unicode_ok=True)

        def update_state(self, state) -> None:
            acq = state.acquisition
            arrow = self._icons.arrow_right

            def _node(label: str, count: Optional[int], status: str = "pending") -> str:
                icon = self._icons.for_status(status)
                cnt = format_count(count) if count is not None else "..."
                return f"{icon} {label}\n   ({cnt})"

            nodes = [
                _node("API token", None, "completed" if acq.zip_status != "pending" else "pending"),
                _node("EPC ZIP", acq.zip_bytes_total, acq.zip_status),
                _node("Members", acq.members_processed),
                _node("Parquet", acq.parquet_parts),
                _node("London", acq.london_records),
                _node("Stock", acq.stock_records),
            ]
            flow = f"  {arrow}  ".join(nodes[:3]) + f"\n  {arrow}  " + f"  {arrow}  ".join(nodes[3:])
            counters = (
                f"\nRows read: {format_count(acq.rows_read)}  "
                f"Retained: {format_count(acq.rows_retained)}  "
                f"Malformed: {format_count(acq.rows_malformed)}"
            )
            throughput = ""
            if acq.rows_per_second:
                throughput = f"  |  {acq.rows_per_second:,.0f} rows/s"
            self.update(f"[bold]Acquisition Flow[/bold]\n\n{flow}{counters}{throughput}")

    class ValidationFunnel(Static):
        """Stepped funnel bar chart for validation pipeline."""

        def update_state(self, state) -> None:
            v = state.validation
            steps = [
                ("Input records", v.input_records),
                ("Schema passed", v.schema_passed),
                ("After dedup", v.after_dedup),
                ("Plausibility", v.plausibility_passed),
                ("Output records", v.output_records),
            ]
            lines = ["[bold]Validation Funnel[/bold]", ""]
            max_val = max((s[1] for s in steps if s[1] is not None), default=1) or 1
            for label, val in steps:
                if val is None:
                    continue
                width = int(round(val / max_val * 32))
                bar = "[cyan]" + "#" * width + "[/cyan]" + "." * (32 - width)
                pct = val / max_val * 100
                lines.append(f"  {label:<26} [{bar}] {format_count(val)} ({pct:.0f}%)")
            if v.duplicates_removed is not None:
                lines.append(f"\n  Duplicates removed: {format_count(v.duplicates_removed)}")
            if v.invalid_records is not None:
                lines.append(f"  Invalid records:    {format_count(v.invalid_records)}")
            if v.validation_rate is not None:
                lines.append(f"  Validation rate:    {v.validation_rate:.1f}%")
            if v.warnings:
                lines.append(f"  [yellow]Warnings:           {v.warnings}[/yellow]")
            self.update("\n".join(lines))

    class ArchetypeCards(Static):
        """Compact archetype summary with EPC distribution bars."""

        def update_state(self, state) -> None:
            arch = state.archetype
            lines = [
                "[bold]Archetype Analysis[/bold]", "",
                f"Total properties:    [cyan]{format_count(arch.total_properties)}[/cyan]",
                f"Pre-1930 terraced:   [cyan]{format_count(arch.pre_1930_terraced)}[/cyan]",
                f"Dominant EPC band:   [yellow]{safe_text(arch.dominant_epc_band or '-', max_length=10)}[/yellow]",
                f"Most common wall:    {safe_text(arch.most_common_wall_type or '-', max_length=30)}",
                f"Most common heating: {safe_text(arch.most_common_heating or '-', max_length=30)}",
            ]
            if arch.epc_distribution:
                lines.extend(["", "[bold]EPC Distribution[/bold]"])
                max_count = max(arch.epc_distribution.values(), default=1) or 1
                epc_colours = {"A": "green", "B": "bright_green", "C": "cyan",
                               "D": "yellow", "E": "orange3", "F": "red", "G": "red bold"}
                for band, count in sorted(arch.epc_distribution.items()):
                    width = int(round(count / max_count * 20))
                    colour = epc_colours.get(band, "white")
                    bar = f"[{colour}]{'#' * width}[/{colour}]{'.' * (20 - width)}"
                    lines.append(f"  {band}: [{bar}] {format_count(count)}")
            self.update("\n".join(lines))

    class ScenarioBoard(Static):
        """Scenario progress board - status, progress bars and key metrics."""

        def update_state(self, state) -> None:
            rows = state.scenario_rows
            if not rows:
                self.update("Waiting for scenario data...")
                return
            lines = ["[bold]Scenario Board[/bold]", ""]
            header = f"{'Scenario':<24} {'Status':<14} {'Cost/home':>12}"
            lines.append(f"[dim]{header}[/dim]")
            lines.append("[dim]" + "-" * 52 + "[/dim]")
            for name, values in list(rows.items())[:8]:
                status = safe_text(values.get("Status", "pending"), max_length=12)
                cost = safe_text(values.get("Cost/property", "-"), max_length=12)
                colour = "green" if "complet" in status.lower() else "cyan" if "run" in status.lower() else "white dim"
                lines.append(
                    f"[{colour}]{safe_text(name, max_length=24):<24}[/{colour}] "
                    f"{status:<14} {cost:>12}"
                )
            self.update("\n".join(lines))

    class RetrofitReadinessGrid(Static):
        """Tier distribution grid with counts, percentages and investment."""

        _TIER_LABELS = [TIER_READINESS_LABELS[tier] for tier in range(1, 6)]
        _TIER_COLOURS = ["green", "bright_green", "yellow", "orange3", "red"]

        def update_state(self, state) -> None:
            r = state.retrofit
            counts = r.counts()
            total = r.total() or 1
            lines = ["[bold]Retrofit Readiness Grid[/bold]", ""]
            for i, (label, count) in enumerate(zip(self._TIER_LABELS, counts)):
                if count is None:
                    continue
                pct = count / total * 100
                width = int(round(pct / 100 * 28))
                colour = self._TIER_COLOURS[i]
                bar = f"[{colour}]{'#' * width}[/{colour}]{'.' * (28 - width)}"
                lines.append(
                    f"  [{colour}]{label:<22}[/{colour}] [{bar}] "
                    f"{format_count(count)} ({pct:.1f}%)"
                )
            if r.total_investment is not None:
                lines.extend(["", f"Total investment:  [cyan]{format_currency(r.total_investment)}[/cyan]"])
            if r.mean_fabric_cost is not None:
                lines.append(f"Mean fabric cost:  [cyan]{format_currency(r.mean_fabric_cost)}[/cyan]")
            if r.solid_wall_barrier is not None:
                lines.append(f"Solid wall barrier: {format_count(r.solid_wall_barrier)}")
            self.update("\n".join(lines))

    class SpatialReadinessPanel(Static):
        """Dependency checklist and spatial processing step progress."""

        _DEP_LABELS = [
            ("geopandas", "geopandas_ok"),
            ("shapely", "shapely_ok"),
            ("pyproj", "pyproj_ok"),
            ("pyogrio/fiona", "pyogrio_ok"),
            ("GDAL", "gdal_ok"),
            ("conda env", "conda_ok"),
        ]

        def update_state(self, state) -> None:
            sp = state.spatial
            lines = ["[bold]Spatial Analysis[/bold]", "", "Dependency status:"]
            for label, attr in self._DEP_LABELS:
                ok = getattr(sp, attr, None)
                if ok is None:
                    icon, colour = "[ ]", "white"
                elif ok:
                    icon, colour = "[+]", "green"
                else:
                    icon, colour = "[x]", "red"
                lines.append(f"  [{colour}]{icon}[/{colour}] {label}")
            if sp.current_step:
                lines.extend(["", f"[cyan]Current step:[/cyan] {sp.current_step}"])
            if sp.steps_done:
                lines.append(f"Completed:    {', '.join(sp.steps_done[-4:])}")
            if sp.tier_counts:
                lines.extend(["", "[bold]Heat network tier counts:[/bold]"])
                for tier, count in sp.tier_counts.items():
                    lines.append(f"  {safe_text(tier, max_length=20)}: {format_count(count)}")
            if sp.borough_progress:
                lines.extend(["", "Borough progress:"])
                for borough, status in list(sp.borough_progress.items())[:10]:
                    colour = "green" if status == "done" else "cyan"
                    lines.append(f"  [{colour}]{safe_text(borough, max_length=24)}[/{colour}]: {status}")
            self.update("\n".join(lines))

    class OutputLauncher(Static):
        """Grouped output file launcher."""

        _GROUPS = [
            ("Open First", ["dashboard", "html", "json"]),
            ("Reports", ["report", "workbook", "xlsx", "pdf"]),
            ("Data files", ["parquet", "csv", "data"]),
            ("Figures", ["figure", "chart", "plot", "svg", "png"]),
            ("Maps", ["map", "geo", "geojson"]),
            ("Logs", ["log", "audit"]),
        ]

        def update_state(self, state) -> None:
            all_outputs = dict(state.outputs)
            all_outputs.update(state.completion_paths)
            if not all_outputs:
                self.update("No outputs registered yet.")
                return
            buckets: Dict[str, list] = {g[0]: [] for g in self._GROUPS}
            buckets["Other"] = []
            for label, path in all_outputs.items():
                lbl = label.lower()
                placed = False
                for group_name, keywords in self._GROUPS:
                    if any(kw in lbl for kw in keywords):
                        buckets[group_name].append((label, path))
                        placed = True
                        break
                if not placed:
                    buckets["Other"].append((label, path))
            lines = ["[bold]Output Launcher[/bold]", ""]
            for group_name in list(buckets.keys()):
                items = buckets[group_name]
                if not items:
                    continue
                colour = "green" if group_name == "Open First" else "cyan"
                lines.append(f"[bold {colour}]{group_name}[/bold {colour}]")
                for label, path in items:
                    icon = "[green][+][/green]" if group_name == "Open First" else "[dim][-][/dim]"
                    lines.append(
                        f"  {icon} [bold]{safe_text(label, max_length=28)}[/bold]"
                        f"  {truncate_text(path, 60)}"
                    )
                lines.append("")
            self.update("\n".join(lines))

    class WarningDrawer(Static):
        """Collapsible warning panel."""

        def update_state(self, state) -> None:
            warnings = list(state.warnings)
            if not warnings:
                self.update("[dim]No warnings.[/dim]")
                return
            lines = [f"[bold yellow]Warnings ({len(warnings)})[/bold yellow]", ""]
            for msg in warnings[-10:]:
                lines.append(f"  [yellow][!][/yellow] {safe_text(msg, max_length=100)}")
            self.update("\n".join(lines))

    class EventLogPanel(RichLog):
        """Scrollable event log with markup support."""

        def add_event(self, message: str) -> None:
            self.write(message)

    class MetricsCards(Static):
        """Compact key-value metrics display."""

        def update_state(self, state, group: str = "Acquisition") -> None:
            group_data = state.metrics.get(group, {})
            if not group_data:
                self.update(f"[dim]No {group} metrics yet.[/dim]")
                return
            lines = [f"[bold]{group} Metrics[/bold]", ""]
            for key, value in list(group_data.items())[:12]:
                lines.append(f"  {safe_text(key, max_length=28):<30} {safe_text(value, max_length=18)}")
            self.update("\n".join(lines))

    class MiniSparklinePanel(Static):
        """ASCII mini bar chart for a list of (label, value) pairs."""

        def update_values(self, title: str, values: List[tuple]) -> None:
            if not values:
                self.update(f"[dim]{title}: no data[/dim]")
                return
            lines = [f"[bold]{title}[/bold]", ""]
            max_val = max((v for _, v in values if v is not None), default=1) or 1
            for label, val in values:
                if val is None:
                    continue
                width = int(round(val / max_val * 20))
                bar = "#" * width + "." * (20 - width)
                lines.append(f"  {safe_text(label, max_length=20):<22} [{bar}] {val:,.1f}")
            self.update("\n".join(lines))

    class VectorPreviewPanel(Static):
        """Shows paths to generated SVG assets with launch hints."""

        def update_state(self, state) -> None:
            assets = state.svg_assets
            if not assets:
                self.update("[dim]SVG assets will appear here when generated.[/dim]")
                return
            lines = ["[bold]Vector Assets (SVG)[/bold]", ""]
            for kind, path in assets.items():
                lines.append(
                    f"  [green]{safe_text(kind, max_length=30)}[/green]  "
                    f"{truncate_text(path, 60)}"
                )
            self.update("\n".join(lines))

else:
    # Stub classes when Textual is not available
    class _StubWidget:
        def __init__(self, *args, **kwargs):
            pass

        def update_state(self, state, **kwargs) -> None:
            pass

        def update_values(self, title: str, values: list) -> None:
            pass

        def add_event(self, message: str) -> None:
            pass

    HeaderBar = _StubWidget
    PhaseRail = _StubWidget
    CurrentPhasePanel = _StubWidget
    AcquisitionFlow = _StubWidget
    ValidationFunnel = _StubWidget
    ArchetypeCards = _StubWidget
    ScenarioBoard = _StubWidget
    RetrofitReadinessGrid = _StubWidget
    SpatialReadinessPanel = _StubWidget
    OutputLauncher = _StubWidget
    WarningDrawer = _StubWidget
    EventLogPanel = _StubWidget
    MetricsCards = _StubWidget
    MiniSparklinePanel = _StubWidget
    VectorPreviewPanel = _StubWidget
