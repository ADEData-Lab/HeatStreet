from datetime import date as date_cls

import pytest
from rich.console import Console

import run_analysis
from src.ui import LiveDashboard, NullDashboard, SimpleDashboard, create_dashboard


def test_parse_args_defaults():
    args = run_analysis.parse_args([])
    assert args.tui is None
    assert args.simple_tui is False
    assert args.tui_refresh_rate is None
    assert args.quiet is False
    assert args.verbose is False
    assert args.open_results is False
    assert args.sample_start is None
    assert args.sample_end is None


def test_parse_args_no_tui_and_dates():
    args = run_analysis.parse_args([
        "--no-tui",
        "--sample-start",
        "2016-01-01",
        "--sample-end",
        "2025-12-31",
    ])
    assert args.tui is False
    assert args.sample_start == date_cls(2016, 1, 1)
    assert args.sample_end == date_cls(2025, 12, 31)


def test_parse_args_use_existing_fresh_conflict():
    with pytest.raises(SystemExit):
        run_analysis.parse_args(["--use-existing", "--fresh"])


def test_parse_args_rejects_inverted_dates():
    with pytest.raises(SystemExit):
        run_analysis.parse_args([
            "--sample-start",
            "2025-12-31",
            "--sample-end",
            "2016-01-01",
        ])


def test_parse_args_download_scope_and_borough():
    args = run_analysis.parse_args([
        "--download-scope",
        "single-borough",
        "--borough",
        "Camden",
    ])
    assert args.download_scope == "single-borough"
    assert args.borough == "Camden"

    args = run_analysis.parse_args(["--borough", "Camden"])
    assert args.download_scope == "single-borough"


def test_parse_args_simple_tui_refresh_quiet_verbose():
    args = run_analysis.parse_args(["--simple-tui", "--tui-refresh-rate", "2", "--quiet", "--verbose"])
    assert args.simple_tui is True
    assert args.tui_refresh_rate == 2
    assert args.quiet is True
    assert args.verbose is True


def test_dashboard_factory_honors_tui_env_overrides():
    console = Console(force_terminal=True)

    args = run_analysis.parse_args([])
    ui = create_dashboard(args, console=console, env={"HEATSTREET_TUI": "0", "TERM": "xterm"})
    assert isinstance(ui, NullDashboard)

    ui = create_dashboard(
        args,
        console=console,
        env={"HEATSTREET_TUI": "1", "HEATSTREET_TUI_REFRESH_RATE": "2", "TERM": "xterm"},
    )
    assert isinstance(ui, LiveDashboard)
    assert ui.refresh_per_second == 2

    args = run_analysis.parse_args(["--simple-tui"])
    ui = create_dashboard(args, console=console, env={"TERM": "dumb"})
    assert isinstance(ui, SimpleDashboard)
