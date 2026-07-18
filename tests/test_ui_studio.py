"""Tests for HeatStreet Studio UI modules.

No real terminal required. No Textual rendering snapshots.
"""

from __future__ import annotations

import math
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest
from rich.console import Console

import run_analysis
from src.ui import create_dashboard, NullDashboard, SimpleDashboard, LiveDashboard
from src.ui.formatters import (
    format_carbon,
    format_currency,
    format_duration,
    format_count,
    terminal_width_safe,
    truncate_text,
)
from src.ui.icons import ASCII_ICONS, UNICODE_ICONS, get_icons, IconSet, phase_icon
from src.ui.null_ui import NullUI
from src.ui.simple_fallback import SimpleFallback
from src.ui.state import (
    AcquisitionCounters,
    ArchetypeState,
    PhaseState,
    RetrofitTierState,
    ScenarioState,
    SpatialState,
    ValidationFunnel,
    StudioSessionState,
)


def test_studio_session_lifecycle_keeps_process_ready_for_another_run():
    session = StudioSessionState()
    assert session.status == "setup"
    session.begin("january_client_report_provisional")
    assert session.status == "running"
    session.complete({"run_id": "run-one", "qa_status": "pass"})
    assert session.status == "completed"
    session.reset()
    assert session.status == "setup"
    assert session.run_id is None
    assert session.completion == {}
    session.begin("january_client_report_provisional")
    session.fail("cancelled", cancelled=True)
    assert session.status == "cancelled"


def test_textual_adapter_reset_discards_run_state_without_duplicating_queues():
    from src.ui.textual_app import TextualUIAdapter

    adapter = TextualUIAdapter()
    event_queue = adapter._event_queue
    prompt_queue = adapter._prompt_request_queue
    adapter.run_started("first")
    adapter.output("old", "old.txt")
    new_state = adapter.reset_session()
    assert adapter._event_queue is event_queue
    assert adapter._prompt_request_queue is prompt_queue
    assert not new_state.outputs
    assert new_state.start_time is None
    assert adapter._event_queue.empty()


def test_pipeline_stop_keeps_studio_open_until_deliberate_exit():
    from src.ui.textual_app import TextualUIAdapter

    adapter = TextualUIAdapter()
    adapter._app = MagicMock()
    adapter.stop()
    adapter._app.exit.assert_not_called()


def test_second_session_gets_new_context_and_preserves_previous_artifacts(tmp_path):
    from src.utils.run_integrity import RunContext

    first = RunContext.create()
    first_dir = tmp_path / first.run_id
    first_dir.mkdir()
    artifact = first_dir / "one_stop_output.json"
    artifact.write_text("{}", encoding="utf-8")
    session = StudioSessionState()
    session.begin("january_client_report_provisional")
    session.complete({"run_id": first.run_id})
    session.reset()
    second = RunContext.create()
    assert second.run_id != first.run_id
    assert artifact.is_file()

from src.ui.terminal import TerminalInfo, detect_terminal, recommended_tui_mode


# ------------------------------------------------------------------
# Formatter tests
# ------------------------------------------------------------------

class TestFormatCurrency:
    def test_gbp_thousands(self):
        assert "1,234" in format_currency(1234)

    def test_gbp_millions(self):
        result = format_currency(1_500_000)
        assert "1.5M" in result

    def test_gbp_small(self):
        result = format_currency(99.5)
        assert "99.50" in result

    def test_none(self):
        assert format_currency(None) == "-"

    def test_nan(self):
        assert format_currency(float("nan")) == "-"


class TestFormatCarbon:
    def test_tonnes(self):
        result = format_carbon(12.3)
        assert "12.3" in result
        assert "tCO2" in result.lower() or "tco2" in result.lower()

    def test_kilo_tonnes(self):
        result = format_carbon(5000)
        assert "5.0" in result
        assert "k" in result.lower()

    def test_none(self):
        assert format_carbon(None) == "-"


class TestTruncateText:
    def test_short_no_change(self):
        assert truncate_text("hello", 10) == "hello"

    def test_middle_truncation(self):
        long = "A" * 40 + "B" * 40
        result = truncate_text(long, 20, middle=True)
        assert len(result) <= 20
        assert "..." in result

    def test_end_truncation(self):
        long = "X" * 30
        result = truncate_text(long, 10, middle=False)
        assert len(result) == 10
        assert result.endswith("...")

    def test_exactly_max(self):
        s = "A" * 10
        assert truncate_text(s, 10) == s


class TestTerminalWidthSafe:
    def test_normal(self):
        assert terminal_width_safe(120) == 120

    def test_too_small(self):
        assert terminal_width_safe(5) == 80

    def test_too_large(self):
        assert terminal_width_safe(5000) == 300

    def test_invalid(self):
        assert terminal_width_safe("bad") == 80


# ------------------------------------------------------------------
# Icon tests
# ------------------------------------------------------------------

class TestIcons:
    def test_unicode_icons_are_iconset(self):
        assert isinstance(UNICODE_ICONS, IconSet)

    def test_ascii_icons_are_iconset(self):
        assert isinstance(ASCII_ICONS, IconSet)

    def test_get_icons_unicode(self):
        icons = get_icons(unicode_ok=True)
        assert icons is UNICODE_ICONS

    def test_get_icons_ascii(self):
        icons = get_icons(unicode_ok=False)
        assert icons is ASCII_ICONS

    def test_for_status_completed(self):
        icon = UNICODE_ICONS.for_status("completed")
        assert icon == UNICODE_ICONS.done

    def test_for_status_running(self):
        icon = UNICODE_ICONS.for_status("running")
        assert icon == UNICODE_ICONS.running

    def test_for_status_failed(self):
        icon = UNICODE_ICONS.for_status("failed")
        assert icon == UNICODE_ICONS.failed

    def test_for_status_unknown(self):
        icon = UNICODE_ICONS.for_status("unknown_status")
        assert icon == UNICODE_ICONS.waiting

    def test_phase_icon_acquisition(self):
        icon = phase_icon("Data Download")
        assert icon == UNICODE_ICONS.acquisition

    def test_phase_icon_validation(self):
        icon = phase_icon("Data Validation")
        assert icon == UNICODE_ICONS.validation

    def test_phase_icon_scenarios(self):
        icon = phase_icon("Scenario Modeling")
        assert icon == UNICODE_ICONS.scenarios


# ------------------------------------------------------------------
# Terminal detection tests
# ------------------------------------------------------------------

class TestDetectTerminal:
    def _env(self, **kwargs):
        base = {"TERM": "xterm-256color"}
        base.update(kwargs)
        return base

    def test_ci_detected(self):
        info = detect_terminal(env=self._env(CI="true"), os_name="posix")
        assert info.kind == "ci"
        assert not info.supports_textual
        assert info.recommended_tui_mode == "none"

    def test_dumb_terminal(self):
        info = detect_terminal(env=self._env(TERM="dumb"), os_name="posix")
        assert info.kind == "dumb"
        assert info.recommended_tui_mode == "none"

    def test_windows_terminal(self):
        info = detect_terminal(
            env=self._env(WT_SESSION="abc123", CONDA_PREFIX="c:\\conda"),
            os_name="nt",
        )
        assert info.kind == "windows_terminal"
        assert info.supports_unicode

    def test_anaconda_prompt(self):
        info = detect_terminal(
            env={"CONDA_PREFIX": r"C:\conda", "CONDA_DEFAULT_ENV": "heatstreet"},
            os_name="nt",
        )
        assert info.kind == "anaconda"

    def test_posix_mode(self):
        info = detect_terminal(env={"TERM": "xterm"}, os_name="posix")
        assert info.kind in ("posix", "unknown")

    def test_returns_terminal_info(self):
        info = detect_terminal(env={}, os_name="posix")
        assert isinstance(info, TerminalInfo)
        assert isinstance(info.width, int)


class TestRecommendedTuiMode:
    def test_env_override_none(self):
        mode = recommended_tui_mode(env={"HEATSTREET_TUI": "0"})
        assert mode == "none"

    def test_env_mode_simple(self):
        mode = recommended_tui_mode(env={"HEATSTREET_TUI_MODE": "simple"})
        assert mode == "simple"

    def test_env_mode_rich(self):
        mode = recommended_tui_mode(env={"HEATSTREET_TUI_MODE": "rich"})
        assert mode == "rich"


# ------------------------------------------------------------------
# CLI arg tests
# ------------------------------------------------------------------

class TestParseArgsTUI:
    def test_default_tui_none(self):
        args = run_analysis.parse_args([])
        assert args.tui is None
        assert args.tui_mode is None
        assert not args.no_tui

    def test_tui_textual(self):
        args = run_analysis.parse_args(["--tui", "textual"])
        assert args.tui_mode == "textual"
        assert args.tui is True

    def test_tui_rich(self):
        args = run_analysis.parse_args(["--tui", "rich"])
        assert args.tui_mode == "rich"
        assert args.tui is True

    def test_tui_alone_defaults_textual(self):
        args = run_analysis.parse_args(["--tui"])
        assert args.tui_mode == "textual"
        assert args.tui is True

    def test_no_tui(self):
        args = run_analysis.parse_args(["--no-tui"])
        assert args.no_tui is True
        assert args.tui is False

    def test_no_tui_conflicts_with_tui(self):
        with pytest.raises(SystemExit):
            run_analysis.parse_args(["--no-tui", "--tui"])


# ------------------------------------------------------------------
# NullUI tests
# ------------------------------------------------------------------

class TestNullUI:
    def _make(self):
        return NullUI()

    def test_enter_exit(self):
        ui = self._make()
        with ui:
            pass  # must not raise

    def test_all_methods_noop(self):
        ui = self._make()
        ui.start()
        ui.stop()
        ui.run_started("hello")
        ui.run_completed()
        ui.run_failed("oops")
        ui.phase_started("Phase A")
        ui.phase_progress("Phase A", "working")
        ui.phase_completed("Phase A")
        ui.phase_failed("Phase A")
        ui.metric("rows", 1000)
        ui.output("result", "/some/path")
        ui.warning("something wrong")
        ui.info("informational")

    def test_suppress_progress_false(self):
        ui = self._make()
        assert not ui.suppress_external_progress

    def test_context_manager_with_exception(self):
        ui = self._make()
        try:
            with ui:
                raise ValueError("test error")
        except ValueError:
            pass  # exception propagates; dashboard does not crash


# ------------------------------------------------------------------
# SimpleFallback tests
# ------------------------------------------------------------------

class TestSimpleFallback:
    def _make(self):
        console = Console(record=True, force_terminal=False, color_system=None, width=120)
        return SimpleFallback(enabled=True, quiet=False, console=console)

    def test_start_prints_header(self):
        ui = self._make()
        ui.start()
        output = ui.console.export_text()
        assert "HeatStreet" in output

    def test_phase_started_prints_line(self):
        ui = self._make()
        ui.start()
        ui.phase_started("Data Download", "Fetching EPC data")
        output = ui.console.export_text()
        assert "Data Download" in output or "RUN" in output

    def test_phase_completed_prints_done(self):
        ui = self._make()
        ui.start()
        ui.phase_started("Validation", "running")
        ui.phase_completed("Validation", "All done")
        output = ui.console.export_text()
        assert "DONE" in output or "Validation" in output

    def test_warning_prints(self):
        ui = self._make()
        ui.start()
        ui.warning("test warning message")
        output = ui.console.export_text()
        assert "warning message" in output.lower() or "WARN" in output

    def test_metric_stored(self):
        ui = self._make()
        ui.metric("rows read", 1234, group="Acquisition")
        assert "rows read" in ui.state.metrics["Acquisition"]

    def test_does_not_crash_on_exceptions(self):
        ui = self._make()
        # Should not raise even with bad inputs
        ui.metric(None, None)
        ui.phase_started("")
        ui.warning("")

    def test_run_completed_calls_after_completion(self):
        ui = self._make()
        ui.start()
        ui.phase_started("Phase A")
        ui.run_completed(elapsed=10.0, properties=500)
        output = ui.console.export_text()
        assert "complete" in output.lower() or "Complete" in output


# ------------------------------------------------------------------
# RichFallback throttling tests
# ------------------------------------------------------------------

class FakeLive:
    instances = []

    def __init__(self, renderable, **kwargs):
        self.renderable = renderable
        self.started = False
        self.stopped = False
        self.updates = []
        FakeLive.instances.append(self)

    def start(self, refresh=False):
        self.started = True

    def stop(self):
        self.stopped = True

    def update(self, renderable, refresh=False):
        self.updates.append(renderable)


class FakeClock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class TestRichFallbackThrottling:
    def _make(self):
        FakeLive.instances = []
        clock = FakeClock()
        console = Console(record=True, force_terminal=True, color_system=None, width=120)
        from src.ui.rich_fallback import RichFallback
        ui = RichFallback(
            console=console,
            time_fn=clock,
            live_factory=FakeLive,
            refresh_per_second=4,
        )
        return ui, clock

    def test_below_interval_no_refresh(self):
        ui, clock = self._make()
        ui.start()
        live = FakeLive.instances[-1]
        n_before = len(live.updates)
        # metric update below 250ms interval should not trigger render
        ui.metric("rows read", 10, group="Acquisition")
        assert len(live.updates) == n_before

    def test_above_interval_triggers_refresh(self):
        ui, clock = self._make()
        ui.start()
        live = FakeLive.instances[-1]
        clock.advance(0.3)  # > 250ms
        ui.metric("rows read", 20, group="Acquisition")
        assert len(live.updates) == 1

    def test_force_refresh_on_phase_change(self):
        ui, clock = self._make()
        ui.start()
        live = FakeLive.instances[-1]
        n_before = len(live.updates)
        ui.phase_started("Data Download", "starting")
        assert len(live.updates) > n_before


# ------------------------------------------------------------------
# DashboardState tests
# ------------------------------------------------------------------

class TestDashboardState:
    def _make(self):
        from src.ui.live_dashboard import DashboardState
        return DashboardState()

    def test_phase_count_done(self):
        state = self._make()
        state.phases["A"] = "completed"
        state.phases["B"] = "running"
        state.phases["C"] = "completed"
        assert state.phase_count_done() == 2

    def test_phase_count_failed(self):
        state = self._make()
        state.phases["A"] = "failed"
        state.phases["B"] = "completed"
        assert state.phase_count_failed() == 1

    def test_elapsed_zero_before_start(self):
        state = self._make()
        assert state.elapsed(100.0) == 0.0

    def test_elapsed_with_start(self):
        state = self._make()
        state.start_time = 100.0
        assert abs(state.elapsed(110.0) - 10.0) < 0.001


class TestPhaseState:
    def test_elapsed(self):
        ps = PhaseState(name="Test", started_at=100.0)
        assert abs(ps.elapsed(110.0) - 10.0) < 0.001

    def test_progress_fraction_none(self):
        ps = PhaseState(name="Test")
        assert ps.progress_fraction() is None

    def test_progress_fraction(self):
        ps = PhaseState(name="Test", progress_current=50.0, progress_total=100.0)
        assert abs(ps.progress_fraction() - 0.5) < 0.001


class TestRetrofitTierState:
    def test_total(self):
        r = RetrofitTierState(tier_1_count=100, tier_2_count=200, tier_3_count=150)
        assert r.total() == 450

    def test_counts_list(self):
        r = RetrofitTierState(tier_1_count=10, tier_2_count=20)
        counts = r.counts()
        assert counts[0] == 10
        assert counts[1] == 20
        assert counts[2] is None


# ------------------------------------------------------------------
# Vector asset generation tests
# ------------------------------------------------------------------

class TestVectorAssets:
    def _minimal_state(self):
        from src.ui.live_dashboard import DashboardState
        state = DashboardState()
        state.phases["Data Download"] = "completed"
        state.phases["Validation"] = "completed"
        state.phases["Scenarios"] = "running"
        state.start_time = 0.0
        return state

    def test_generate_all_does_not_raise(self):
        from src.ui.vector_assets import generate_all
        state = self._minimal_state()
        with tempfile.TemporaryDirectory() as tmpdir:
            results = generate_all(state, Path(tmpdir))
            assert isinstance(results, dict)

    def test_pipeline_flow_svg_created(self):
        from src.ui.vector_assets import generate_pipeline_flow_svg
        state = self._minimal_state()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = generate_pipeline_flow_svg(state, Path(tmpdir))
            assert out is not None
            assert out.exists()
            content = out.read_text()
            assert "<svg" in content

    def test_run_summary_svg_created(self):
        from src.ui.vector_assets import generate_run_summary_svg
        state = self._minimal_state()
        state.properties_analysed = 5000
        with tempfile.TemporaryDirectory() as tmpdir:
            out = generate_run_summary_svg(state, Path(tmpdir))
            assert out is not None
            assert out.exists()

    def test_epc_distribution_returns_none_when_empty(self):
        from src.ui.vector_assets import generate_epc_distribution_svg
        from src.ui.live_dashboard import DashboardState
        state = DashboardState()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = generate_epc_distribution_svg(state, Path(tmpdir))
        assert out is None  # no data - OK to check after context

    def test_epc_distribution_creates_svg_with_data(self):
        from src.ui.vector_assets import generate_epc_distribution_svg
        from src.ui.live_dashboard import DashboardState
        from src.ui.state import ArchetypeState
        state = DashboardState()
        state.archetype = ArchetypeState(epc_distribution={"D": 1000, "E": 2000, "F": 500})
        with tempfile.TemporaryDirectory() as tmpdir:
            out = generate_epc_distribution_svg(state, Path(tmpdir))
            assert out is not None
            assert "<rect" in out.read_text()

    def test_scenario_swimlanes_returns_none_when_empty(self):
        from src.ui.vector_assets import generate_scenario_swimlanes_svg
        from src.ui.live_dashboard import DashboardState
        state = DashboardState()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = generate_scenario_swimlanes_svg(state, Path(tmpdir))
        assert out is None  # no data - OK to check after context

    def test_generate_all_survives_corrupt_state(self):
        from src.ui.vector_assets import generate_all
        # Pass None as state - must not raise, result must be a dict
        with tempfile.TemporaryDirectory() as tmpdir:
            results = generate_all(None, Path(tmpdir))
        assert isinstance(results, dict)
        # All values are either None (failed gracefully) or Path objects
        for v in results.values():
            assert v is None or isinstance(v, Path)


# ------------------------------------------------------------------
# Output path registration tests
# ------------------------------------------------------------------

class TestOutputRegistration:
    def _make_simple(self):
        console = Console(record=True, force_terminal=False, color_system=None)
        return SimpleFallback(enabled=False, quiet=True, console=console)

    def test_output_stored_in_state(self):
        ui = self._make_simple()
        ui.output("My Report", "/data/outputs/report.xlsx")
        assert any("report.xlsx" in v for v in ui.state.outputs.values())

    def test_multiple_outputs(self):
        ui = self._make_simple()
        ui.output("JSON", "/a.json")
        ui.output("XLSX", "/b.xlsx")
        assert len(ui.state.outputs) == 2


# ------------------------------------------------------------------
# Warning handling tests
# ------------------------------------------------------------------

class TestWarningHandling:
    def _make(self):
        console = Console(record=True, force_terminal=False)
        return SimpleFallback(enabled=True, quiet=False, console=console)

    def test_warning_appended(self):
        ui = self._make()
        ui.warning("data quality issue")
        assert any("data quality" in w for w in ui.state.warnings)

    def test_empty_warning_ignored(self):
        ui = self._make()
        ui.warning("")
        assert len(ui.state.warnings) == 0

    def test_multiple_warnings(self):
        ui = self._make()
        for i in range(5):
            ui.warning(f"warning {i}")
        assert len(ui.state.warnings) == 5


# ------------------------------------------------------------------
# Acquisition callback conversion tests
# ------------------------------------------------------------------

class TestAcquisitionCallback:
    def _make_ui(self):
        console = Console(record=True, force_terminal=False)
        return SimpleFallback(enabled=False, quiet=True, console=console)

    def test_callback_chunk_parsed_updates_counters(self):
        ui = self._make_ui()
        cb = run_analysis._make_epc_progress_callback(ui)
        assert cb is not None
        cb({"event": "chunk_parsed", "rows_read": 1000, "rows_retained": 950})
        assert "rows read" in ui.state.metrics.get("Acquisition", {})
        assert "rows retained" in ui.state.metrics.get("Acquisition", {})

    def test_callback_member_complete_accumulates(self):
        ui = self._make_ui()
        cb = run_analysis._make_epc_progress_callback(ui)
        cb({"event": "member_complete", "malformed_rows_skipped": 5})
        cb({"event": "member_complete", "malformed_rows_skipped": 3})
        metrics = ui.state.metrics.get("Acquisition", {})
        assert "members processed" in metrics
        # Should be 2 after two member_complete events
        assert metrics["members processed"] == "2"

    def test_callback_none_for_null_ui(self):
        # NullUI has no suppress_external_progress but should still work
        cb = run_analysis._make_epc_progress_callback(None)
        assert cb is None

    def test_callback_does_not_raise_on_bad_event(self):
        ui = self._make_ui()
        cb = run_analysis._make_epc_progress_callback(ui)
        # Unknown event type - must not raise
        cb({"event": "unknown_event_xyz", "data": None})

    def test_callback_zip_download_started(self):
        ui = self._make_ui()
        cb = run_analysis._make_epc_progress_callback(ui)
        cb({"event": "zip_download_started"})  # must not raise


# ------------------------------------------------------------------
# Validation funnel state tests
# ------------------------------------------------------------------

class TestValidationFunnelState:
    def test_fields(self):
        v = ValidationFunnel(
            input_records=10000,
            schema_passed=9500,
            after_dedup=9200,
            output_records=9000,
            validation_rate=90.0,
        )
        assert v.input_records == 10000
        assert v.output_records == 9000
        assert v.validation_rate == 90.0


# ------------------------------------------------------------------
# Scenario board state tests
# ------------------------------------------------------------------

class TestScenarioBoardState:
    def test_scenario_state_fields(self):
        s = ScenarioState(
            name="Heat pump",
            status="running",
            mean_capex=12000.0,
            carbon_impact=-2.5,
        )
        assert s.name == "Heat pump"
        assert s.status == "running"
        assert s.mean_capex == 12000.0

    def test_dashboard_scenario_rows_update(self):
        from src.ui.live_dashboard import DashboardBase, DashboardState
        state = DashboardState()
        db = DashboardBase(state=state)
        db._update_scenario_row("Heat pump status", "complete")
        assert "Heat pump" in state.scenario_rows
        assert state.scenario_rows["Heat pump"]["Status"] == "complete"
