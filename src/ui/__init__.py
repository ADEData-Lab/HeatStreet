"""Terminal UI helpers for the HeatStreet runner."""

from .compat import (
    is_conservative_terminal,
    live_rendering_allowed,
    resolve_refresh_rate,
    should_enable_live,
)
from .events import UIEvent, UI_EVENT_TYPES
from .live_dashboard import DashboardState, LiveDashboard, NullDashboard, SimpleDashboard, create_dashboard

__all__ = [
    "DashboardState",
    "LiveDashboard",
    "NullDashboard",
    "SimpleDashboard",
    "UIEvent",
    "UI_EVENT_TYPES",
    "create_dashboard",
    "is_conservative_terminal",
    "live_rendering_allowed",
    "resolve_refresh_rate",
    "should_enable_live",
]
