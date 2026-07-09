"""ASCII-safe formatting helpers for HeatStreet terminal output."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Optional


_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_STATUS_LABELS = {
    "pending": "WAIT",
    "waiting": "WAIT",
    "queued": "WAIT",
    "running": "RUN",
    "in_progress": "RUN",
    "complete": "DONE",
    "completed": "DONE",
    "success": "DONE",
    "failed": "FAIL",
    "error": "FAIL",
    "skipped": "SKIP",
    "skip": "SKIP",
    "warning": "WARN",
    "warn": "WARN",
}


def safe_text(value: Any, *, max_length: Optional[int] = None) -> str:
    """Return printable ASCII text with control characters stripped."""
    if value is None:
        text = ""
    else:
        text = str(value)
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = _CONTROL_CHARS.sub("", text)
    text = text.encode("ascii", errors="replace").decode("ascii")
    text = " ".join(text.split())
    if max_length is not None and max_length >= 1 and len(text) > max_length:
        if max_length <= 3:
            return text[:max_length]
        return f"{text[: max_length - 3]}..."
    return text


def format_count(value: Any) -> str:
    """Format an integer count with thousands separators."""
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return "-"
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return safe_text(value)


def format_percent(value: Any, *, decimals: int = 1) -> str:
    """Format a numeric percentage value."""
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return "-"
        return f"{float(value):.{decimals}f}%"
    except (TypeError, ValueError):
        return safe_text(value)


def format_duration(seconds: Any) -> str:
    """Format elapsed seconds as compact ASCII duration text."""
    try:
        total = max(0.0, float(seconds))
    except (TypeError, ValueError):
        return "-"
    if total < 60:
        return f"{total:.1f}s"
    minutes, secs = divmod(int(round(total)), 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def format_bytes(value: Any) -> str:
    """Format bytes using binary units."""
    try:
        size = float(value)
    except (TypeError, ValueError):
        return "-"
    if size < 0:
        size = 0
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{int(size)} B"
    return f"{size:.1f} {units[unit_index]}"


def format_path(value: Any, *, max_length: int = 72) -> str:
    """Format a path, truncating from the left when needed."""
    if value is None:
        return ""
    text = safe_text(Path(value) if not isinstance(value, Path) else value)
    if len(text) <= max_length:
        return text
    if max_length <= 4:
        return text[-max_length:]
    return f"...{text[-(max_length - 3):]}"


def status_label(status: Any) -> str:
    """Return a stable uppercase label for a status value."""
    key = safe_text(status).lower().replace("-", "_")
    return _STATUS_LABELS.get(key, safe_text(status).upper() or "UNKNOWN")


def phase_label(name: Any) -> str:
    """Normalize a phase name for compact dashboard display."""
    return safe_text(name, max_length=42)


def format_currency(value: Any, *, symbol: str = "GBP") -> str:
    """Format a monetary value with currency symbol."""
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return "-"
        amount = float(value)
        prefix = "GBP " if symbol == "GBP" else f"{symbol} "
        if abs(amount) >= 1_000_000:
            return f"{prefix}{amount / 1_000_000:.1f}M"
        if abs(amount) >= 1_000:
            return f"{prefix}{amount:,.0f}"
        return f"{prefix}{amount:.2f}"
    except (TypeError, ValueError):
        return safe_text(value)


def format_carbon(value: Any) -> str:
    """Format a carbon value in tonnes CO2."""
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return "-"
        amount = float(value)
        if abs(amount) >= 1_000:
            return f"{amount / 1_000:.1f}ktCO2"
        return f"{amount:.1f}tCO2"
    except (TypeError, ValueError):
        return safe_text(value)


def truncate_text(text: Any, max_len: int, *, middle: bool = True) -> str:
    """Truncate text, optionally from the middle (useful for paths)."""
    s = safe_text(text)
    if len(s) <= max_len or max_len < 5:
        return s[:max_len] if max_len >= 0 else s
    if middle:
        half = (max_len - 3) // 2
        return f"{s[:half]}...{s[-(max_len - 3 - half):]}"
    return f"{s[: max_len - 3]}..."


def terminal_width_safe(width: int, *, fallback: int = 80) -> int:
    """Clamp a terminal width to a safe printable range."""
    try:
        w = int(width)
        if w < 20:
            return fallback
        return min(w, 300)
    except (TypeError, ValueError):
        return fallback
