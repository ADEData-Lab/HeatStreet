"""Terminal UI package for HeatStreet Studio."""

from .compat import (
    is_conservative_terminal,
    live_rendering_allowed,
    resolve_refresh_rate,
    should_enable_live,
)
from .events import UIEvent, UI_EVENT_TYPES
from .formatters import (
    format_bytes,
    format_carbon,
    format_count,
    format_currency,
    format_duration,
    format_path,
    format_percent,
    phase_label,
    safe_text,
    status_label,
    terminal_width_safe,
    truncate_text,
)
from .icons import IconSet, ASCII_ICONS, UNICODE_ICONS, get_icons, phase_icon
from .live_dashboard import (
    DashboardBase,
    DashboardState,
    LiveDashboard,
    NullDashboard,
    SimpleDashboard,
    create_dashboard,
    METRIC_GROUPS,
    DEFAULT_PHASES,
    PHASE_TO_GROUP,
    HEADLINE_METRICS,
    COMPLETION_LABELS,
)
from .null_ui import NullUI
from .rich_fallback import RichFallback
from .simple_fallback import SimpleFallback
from .state import (
    PhaseState,
    AcquisitionCounters,
    ValidationFunnel,
    ArchetypeState,
    ScenarioState,
    RetrofitTierState,
    SpatialState,
    OutputEntry,
    StudioSessionState,
)
from .terminal import (
    TerminalInfo,
    detect_terminal,
    recommended_tui_mode,
)

__all__ = [
    # Factory
    "create_dashboard",

    # State
    "DashboardState",
    "DashboardBase",
    "PhaseState",
    "AcquisitionCounters",
    "ValidationFunnel",
    "ArchetypeState",
    "ScenarioState",
    "RetrofitTierState",
    "SpatialState",
    "OutputEntry",
    "StudioSessionState",

    # UI implementations
    "LiveDashboard",
    "RichFallback",
    "SimpleDashboard",
    "SimpleFallback",
    "NullDashboard",
    "NullUI",

    # Events
    "UIEvent",
    "UI_EVENT_TYPES",

    # Formatters
    "safe_text",
    "format_count",
    "format_percent",
    "format_duration",
    "format_bytes",
    "format_path",
    "format_currency",
    "format_carbon",
    "truncate_text",
    "terminal_width_safe",
    "phase_label",
    "status_label",

    # Icons
    "IconSet",
    "ASCII_ICONS",
    "UNICODE_ICONS",
    "get_icons",
    "phase_icon",

    # Terminal detection
    "TerminalInfo",
    "detect_terminal",
    "recommended_tui_mode",
    "is_conservative_terminal",
    "live_rendering_allowed",
    "resolve_refresh_rate",
    "should_enable_live",

    # Constants
    "METRIC_GROUPS",
    "DEFAULT_PHASES",
    "PHASE_TO_GROUP",
    "HEADLINE_METRICS",
    "COMPLETION_LABELS",
]
