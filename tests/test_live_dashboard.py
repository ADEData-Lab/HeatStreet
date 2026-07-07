from rich.console import Console

from src.ui.live_dashboard import LiveDashboard, NullDashboard, SimpleDashboard


class Clock:
    def __init__(self, value=0.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class FakeLive:
    instances = []

    def __init__(self, renderable, **kwargs):
        self.renderable = renderable
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        self.updates = []
        FakeLive.instances.append(self)

    def start(self, refresh=False):
        self.started = True

    def stop(self):
        self.stopped = True

    def update(self, renderable, refresh=False):
        self.renderable = renderable
        self.updates.append((renderable, refresh))


def make_console():
    return Console(record=True, force_terminal=True, color_system=None, width=120)


def test_state_updates_do_not_refresh_every_metric():
    FakeLive.instances = []
    clock = Clock()
    ui = LiveDashboard(console=make_console(), time_fn=clock, live_factory=FakeLive)
    ui.start()
    live = FakeLive.instances[-1]

    ui.metric("rows read", 10, group="Acquisition")
    assert live.updates == []

    clock.advance(0.26)
    ui.metric("rows read", 20, group="Acquisition")
    assert len(live.updates) == 1


def test_force_refresh_on_phase_changes_and_completion():
    FakeLive.instances = []
    clock = Clock()
    console = make_console()
    ui = LiveDashboard(console=console, time_fn=clock, live_factory=FakeLive)
    ui.start()
    live = FakeLive.instances[-1]

    ui.phase_started("Data Download", "Starting EPC download")
    ui.phase_completed("Data Download", "Download complete")
    ui.run_completed(
        elapsed=1.2,
        properties=3,
        one_stop_json="data/outputs/one_stop_output.json",
        workbook="data/outputs/analysis_outputs_compendium.xlsx",
        dashboard_data="data/outputs/dashboard-data.json",
        audit_log="data/outputs/analysis_log.txt",
        figures="data/outputs/figures",
        maps="data/outputs/maps",
    )

    assert len(live.updates) == 3
    assert live.stopped is True
    rendered = console.export_text()
    assert "Run complete" in rendered
    assert "Properties analysed: 3" in rendered
    assert "One-stop JSON:" in rendered
    assert "Workbook:" in rendered
    assert "Dashboard data:" in rendered
    assert "Analysis log:" in rendered
    assert "Figures directory:" in rendered
    assert "Maps directory:" in rendered


def test_long_paths_and_events_are_truncated():
    ui = LiveDashboard(enabled=False, quiet=True, console=make_console())
    long_path = "C:/" + "/".join(["verylongsegment"] * 12) + "/output.parquet"
    ui.output("Dataset", long_path)
    ui.info("x" * 200)

    assert ui.outputs["Dataset"].startswith("...")
    assert ui.outputs["Dataset"].endswith("output.parquet")
    assert len(ui.events[-1]) <= 118


def test_disabled_dashboard_public_methods_are_noop_safe():
    with LiveDashboard(enabled=False, quiet=True, verbose=True) as ui:
        ui.run_started("start")
        ui.phase_completed("Validation", "out of order completion")
        ui.phase_started("Download", "starting")
        ui.phase_progress("Download", "working")
        ui.metric("rows", 10, group="Acquisition")
        ui.output("Dataset", "data/raw/example.parquet")
        ui.warning("warning text")
        ui.info("info text")
        ui.phase_failed("Spatial", "missing deps")
        ui.phase_skipped("Reports", "not needed")
        with ui.suspend_for_prompt("prompt"):
            pass
        ui.run_completed(elapsed=1.2, properties=3, audit_log="analysis_log.txt")

    assert ui.metrics["Acquisition"]["rows"] == "10"
    assert "Dataset" in ui.outputs


def test_null_dashboard_public_methods_are_safe():
    ui = NullDashboard()
    ui.start()
    ui.run_started("start")
    ui.phase_started("Phase", "work")
    ui.metric("rows", 1)
    ui.output("Output", "path")
    ui.warning("warning")
    with ui.suspend_for_prompt("prompt"):
        pass
    ui.run_completed(elapsed=1, properties=1)
    ui.stop()


def test_suspend_for_prompt_active_disabled_and_simple_dashboards():
    FakeLive.instances = []
    clock = Clock()
    active = LiveDashboard(console=make_console(), time_fn=clock, live_factory=FakeLive)
    active.start()
    active_live = FakeLive.instances[-1]
    with active.suspend_for_prompt("prompt"):
        assert active.allow_console_output is True
        assert active.is_live_active is False
    assert active.is_live_active is True
    assert active_live.stopped is True
    active.stop()

    disabled = LiveDashboard(enabled=False, quiet=True, console=make_console())
    with disabled.suspend_for_prompt("prompt"):
        assert disabled.allow_console_output is True

    simple = SimpleDashboard(console=make_console())
    simple.start()
    with simple.suspend_for_prompt("prompt"):
        assert simple.allow_console_output is True
