"""Terminal capability detection for HeatStreet Studio.

Wraps and extends src/ui/compat.py with Textual-specific detection.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Mapping, Optional

from .compat import (
    is_conservative_terminal,
    live_rendering_allowed,
    resolve_refresh_rate,
    should_enable_live,
)


# ------------------------------------------------------------------
# Terminal kind enumeration (strings, not an Enum, for easy serialise)
# ------------------------------------------------------------------

KIND_WINDOWS_TERMINAL = "windows_terminal"
KIND_VSCODE = "vscode"
KIND_POWERSHELL = "powershell"
KIND_ANACONDA = "anaconda"
KIND_CMD = "cmd"
KIND_CI = "ci"
KIND_DUMB = "dumb"
KIND_POSIX = "posix"
KIND_UNKNOWN = "unknown"


@dataclass(frozen=True)
class TerminalInfo:
    """Detected terminal properties."""

    kind: str
    supports_unicode: bool
    supports_colour: bool
    supports_textual: bool
    is_interactive: bool
    recommended_tui_mode: str  # "textual" | "rich" | "simple" | "none"
    os_name: str
    width: int


def detect_terminal(
    env: Optional[Mapping[str, str]] = None,
    *,
    os_name: Optional[str] = None,
) -> TerminalInfo:
    """Detect current terminal capabilities and return a TerminalInfo."""
    env = os.environ if env is None else env
    os_name = os_name if os_name is not None else os.name

    # --- kind ---
    ci = _truthy(env.get("CI")) or _truthy(env.get("GITHUB_ACTIONS")) or _truthy(env.get("GITLAB_CI"))
    dumb = str(env.get("TERM", "")).lower() == "dumb"

    if ci:
        kind = KIND_CI
    elif dumb:
        kind = KIND_DUMB
    elif env.get("WT_SESSION"):
        kind = KIND_WINDOWS_TERMINAL
    elif str(env.get("TERM_PROGRAM", "")).lower() in {"vscode", "vscode-remote"}:
        kind = KIND_VSCODE
    elif os_name == "nt":
        conda = env.get("CONDA_PREFIX") or env.get("CONDA_DEFAULT_ENV") or env.get("ANACONDA_PROMPT_MODIFIER")
        comspec = str(env.get("ComSpec", "") or env.get("COMSPEC", "")).lower()
        psmod = env.get("PSModulePath")
        if conda:
            kind = KIND_ANACONDA
        elif "cmd.exe" in comspec:
            kind = KIND_CMD
        elif psmod:
            kind = KIND_POWERSHELL
        else:
            kind = KIND_UNKNOWN
    else:
        kind = KIND_POSIX

    # --- is_interactive ---
    is_interactive = bool(
        not ci
        and not dumb
        and sys.stdout.isatty()
    )

    # --- unicode support ---
    supports_unicode = _unicode_supported(kind, os_name, env)

    # --- colour support ---
    supports_colour = is_interactive and not dumb and not ci

    # --- textual support ---
    supports_textual = (
        is_interactive
        and not dumb
        and not ci
        and kind not in (KIND_CMD,)
        and _textual_importable()
    )

    # --- recommended mode ---
    mode = _recommend_mode(kind, is_interactive, supports_textual, env)

    # --- width ---
    try:
        import shutil
        width = shutil.get_terminal_size((80, 24)).columns
    except Exception:
        width = 80

    return TerminalInfo(
        kind=kind,
        supports_unicode=supports_unicode,
        supports_colour=supports_colour,
        supports_textual=supports_textual,
        is_interactive=is_interactive,
        recommended_tui_mode=mode,
        os_name=os_name,
        width=width,
    )


def recommended_tui_mode(env: Optional[Mapping[str, str]] = None) -> str:
    """Return the recommended TUI mode string for the current terminal."""
    env = os.environ if env is None else env

    # Honour explicit overrides first
    mode_env = env.get("HEATSTREET_TUI_MODE", "").lower().strip()
    if mode_env in ("textual", "rich", "simple", "none"):
        return mode_env

    tui_env = env.get("HEATSTREET_TUI", "").strip().lower()
    if tui_env in ("0", "false", "no", "off"):
        return "none"
    if tui_env in ("1", "true", "yes", "on"):
        # Legacy "enable live TUI" flag -> Rich dashboard (backwards compat).
        # Use HEATSTREET_TUI_MODE=textual to explicitly request Textual.
        return "rich"

    info = detect_terminal(env=env)
    return info.recommended_tui_mode


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _unicode_supported(kind: str, os_name: str, env: Mapping[str, str]) -> bool:
    if kind in (KIND_CI, KIND_DUMB):
        return False
    if kind == KIND_CMD:
        return False
    if kind in (KIND_WINDOWS_TERMINAL, KIND_VSCODE, KIND_POWERSHELL):
        return True
    if os_name != "nt":
        return True
    return kind == KIND_ANACONDA  # conda terminals often support some unicode


def _textual_importable() -> bool:
    try:
        import importlib
        spec = importlib.util.find_spec("textual")
        return spec is not None
    except Exception:
        return False


def _recommend_mode(
    kind: str,
    is_interactive: bool,
    supports_textual: bool,
    env: Mapping[str, str],
) -> str:
    if not is_interactive or kind in (KIND_CI, KIND_DUMB):
        return "none"
    if kind == KIND_CMD:
        return "simple"
    if kind == KIND_ANACONDA:
        # Anaconda is conservative; prefer simple unless Textual available
        return "textual" if supports_textual else "simple"
    if supports_textual:
        return "textual"
    return "rich"


# Re-export compat helpers so callers need only import from terminal
__all__ = [
    "TerminalInfo",
    "detect_terminal",
    "recommended_tui_mode",
    "is_conservative_terminal",
    "live_rendering_allowed",
    "resolve_refresh_rate",
    "should_enable_live",
    "KIND_WINDOWS_TERMINAL",
    "KIND_VSCODE",
    "KIND_POWERSHELL",
    "KIND_ANACONDA",
    "KIND_CMD",
    "KIND_CI",
    "KIND_DUMB",
    "KIND_POSIX",
    "KIND_UNKNOWN",
]
