"""Terminal compatibility checks for Rich Live rendering."""

from __future__ import annotations

import os
from typing import Any, Mapping, Optional

from rich.console import Console


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _falsey(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"0", "false", "no", "off"}


def _is_truthy_tui(value: Optional[str]) -> Optional[bool]:
    if _truthy(value):
        return True
    if _falsey(value):
        return False
    return None


def is_conservative_terminal(
    env: Optional[Mapping[str, str]] = None,
    *,
    os_name: Optional[str] = None,
) -> bool:
    """Return True for Windows cmd/Anaconda-style terminals that need 2 FPS."""
    env = os.environ if env is None else env
    os_name = os_name if os_name is not None else os.name
    if os_name != "nt":
        return False

    if env.get("WT_SESSION") or str(env.get("TERM_PROGRAM", "")).lower() in {"vscode", "windows_terminal"}:
        return False

    terminal = " ".join(
        str(env.get(key, ""))
        for key in (
            "TERM",
            "TERM_PROGRAM",
            "PROMPT",
            "ComSpec",
            "COMSPEC",
            "CONDA_PREFIX",
            "CONDA_DEFAULT_ENV",
            "ANACONDA_PROMPT_MODIFIER",
        )
    ).lower()

    if "anaconda" in terminal or "conda" in terminal:
        return True
    if "cmd.exe" in terminal:
        return True
    return False


def resolve_refresh_rate(
    requested: Optional[Any] = None,
    *,
    env: Optional[Mapping[str, str]] = None,
    enabled: bool = True,
    os_name: Optional[str] = None,
) -> int:
    """Resolve and clamp the dashboard refresh rate to the supported 2-4 FPS range."""
    env = os.environ if env is None else env
    if not enabled:
        return 0

    value = requested if requested is not None else env.get("HEATSTREET_TUI_REFRESH_RATE")
    if value is None:
        return 2 if is_conservative_terminal(env, os_name=os_name) else 4

    try:
        fps = int(value)
    except (TypeError, ValueError):
        fps = 2 if is_conservative_terminal(env, os_name=os_name) else 4
    return max(2, min(4, fps))


def live_rendering_allowed(console: Optional[Console] = None, env: Optional[Mapping[str, str]] = None) -> bool:
    """Return True when the current process is a sensible target for Rich Live."""
    env = os.environ if env is None else env
    console = console or Console()

    tui_env = _is_truthy_tui(env.get("HEATSTREET_TUI"))
    if tui_env is False:
        return False
    if _truthy(env.get("CI")):
        return False
    if str(env.get("TERM", "")).lower() == "dumb":
        return False
    if not bool(getattr(console, "is_terminal", False)):
        return False
    if tui_env is True:
        return True
    return True


def should_enable_live(
    *,
    requested: Optional[bool],
    quiet: bool = False,
    console: Optional[Console] = None,
    env: Optional[Mapping[str, str]] = None,
) -> bool:
    """Resolve argparse/env/default state into a Live on/off decision."""
    if quiet:
        return False
    if requested is False:
        return False
    allowed = live_rendering_allowed(console=console, env=env)
    if requested is True:
        return allowed
    return allowed
