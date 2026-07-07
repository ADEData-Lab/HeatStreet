"""Lightweight event model for the runner dashboard."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


UI_EVENT_TYPES = (
    "run_started",
    "run_completed",
    "run_failed",
    "phase_started",
    "phase_progress",
    "phase_completed",
    "phase_failed",
    "metric_updated",
    "output_registered",
    "warning",
    "info",
    "prompt_pending",
    "prompt_completed",
)


@dataclass(frozen=True)
class UIEvent:
    """Structured event consumed by LiveDashboard."""

    event_type: str
    message: str = ""
    phase: Optional[str] = None
    metric: Optional[str] = None
    value: Any = None
    group: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        if self.event_type not in UI_EVENT_TYPES:
            raise ValueError(f"Unsupported UI event type: {self.event_type}")
