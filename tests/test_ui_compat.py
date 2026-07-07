from src.ui.compat import (
    is_conservative_terminal,
    live_rendering_allowed,
    resolve_refresh_rate,
)


class DummyConsole:
    def __init__(self, is_terminal):
        self.is_terminal = is_terminal


def test_term_dumb_disables_full_tui():
    assert live_rendering_allowed(
        console=DummyConsole(True),
        env={"TERM": "dumb", "HEATSTREET_TUI": "1"},
    ) is False


def test_non_tty_disables_full_tui():
    assert live_rendering_allowed(
        console=DummyConsole(False),
        env={"TERM": "xterm", "HEATSTREET_TUI": "1"},
    ) is False


def test_windows_cmd_and_anaconda_select_conservative_mode():
    cmd_env = {"ComSpec": r"C:\Windows\System32\cmd.exe", "PROMPT": "$P$G"}
    conda_env = {"CONDA_PREFIX": r"C:\Users\me\anaconda3\envs\heatstreet"}

    assert is_conservative_terminal(cmd_env, os_name="nt") is True
    assert is_conservative_terminal(conda_env, os_name="nt") is True
    assert resolve_refresh_rate(None, env=cmd_env, os_name="nt") == 2
    assert resolve_refresh_rate(1, env=cmd_env, os_name="nt") == 2
    assert resolve_refresh_rate(10, env=cmd_env, os_name="nt") == 4
