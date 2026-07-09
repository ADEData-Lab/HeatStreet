"""Icon sets for HeatStreet Studio. Two modes: unicode and ascii.

No emoji used by default. No em dashes or en dashes anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class IconSet:
    """A complete set of status and phase icons."""

    # App identity
    app: str

    # Status icons
    done: str
    running: str
    waiting: str
    warning: str
    failed: str
    skipped: str

    # Phase icons
    acquisition: str
    validation: str
    archetypes: str
    scenarios: str
    retrofit: str
    spatial: str
    outputs: str
    logs: str

    # Misc
    arrow_right: str
    bullet: str
    progress_fill: str
    progress_empty: str

    def for_status(self, status: str) -> str:
        """Return the appropriate icon for a phase status string."""
        mapping = {
            "completed": self.done,
            "complete": self.done,
            "success": self.done,
            "running": self.running,
            "in_progress": self.running,
            "waiting": self.waiting,
            "pending": self.waiting,
            "queued": self.waiting,
            "warning": self.warning,
            "warn": self.warning,
            "failed": self.failed,
            "error": self.failed,
            "skipped": self.skipped,
            "skip": self.skipped,
        }
        return mapping.get(str(status).lower(), self.waiting)


UNICODE_ICONS = IconSet(
    app="[HS]",
    done="[+]",
    running="[>]",
    waiting="[ ]",
    warning="[!]",
    failed="[x]",
    skipped="[-]",
    acquisition="[D]",
    validation="[V]",
    archetypes="[A]",
    scenarios="[S]",
    retrofit="[R]",
    spatial="[M]",
    outputs="[O]",
    logs="[L]",
    arrow_right="->",
    bullet="-",
    progress_fill="#",
    progress_empty=".",
)

ASCII_ICONS = IconSet(
    app="[HS]",
    done="OK  ",
    running="RUN ",
    waiting="WAIT",
    warning="WARN",
    failed="FAIL",
    skipped="SKIP",
    acquisition="DATA",
    validation="QA  ",
    archetypes="TYPE",
    scenarios="PATH",
    retrofit="FIX ",
    spatial="MAP ",
    outputs="OUT ",
    logs="LOG ",
    arrow_right="->",
    bullet="-",
    progress_fill="#",
    progress_empty=".",
)


def get_icons(*, unicode_ok: bool = True) -> IconSet:
    """Return the appropriate icon set for the current terminal."""
    return UNICODE_ICONS if unicode_ok else ASCII_ICONS


def phase_icon(phase_name: str, icons: Optional[IconSet] = None) -> str:
    """Return the icon for a named pipeline phase."""
    if icons is None:
        icons = UNICODE_ICONS
    name = phase_name.lower()
    if "download" in name or "acqui" in name or "load" in name:
        return icons.acquisition
    if "valid" in name or "clean" in name:
        return icons.validation
    if "archetype" in name:
        return icons.archetypes
    if "scenario" in name or "model" in name or "pathway" in name:
        return icons.scenarios
    if "retrofit" in name:
        return icons.retrofit
    if "spatial" in name or "gis" in name or "geo" in name:
        return icons.spatial
    if "report" in name or "dashboard" in name or "output" in name:
        return icons.outputs
    if "log" in name:
        return icons.logs
    return icons.bullet
