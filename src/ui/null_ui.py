"""No-op UI adapter for --no-tui and CI execution.

Never prints anything. All methods silently return None.
"""

from __future__ import annotations

import contextlib
from collections import OrderedDict, deque
from typing import Iterator


class NullUI:
    """No-op dashboard used when terminal UI output is disabled."""

    enabled = False
    quiet = True
    verbose = False
    is_full_tui = False
    is_simple_tui = False
    is_live_active = False
    suppress_external_progress = False
    route_console_output = False
    allow_console_output = True

    def __enter__(self) -> "NullUI":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def __getattr__(self, name: str):
        if name == "metrics":
            return OrderedDict()
        if name in {"outputs"}:
            return OrderedDict()
        if name in {"warnings", "events"}:
            return deque()

        def noop(*args, **kwargs):
            return None

        return noop

    @contextlib.contextmanager
    def suspend_for_prompt(self, message: str = "") -> Iterator[None]:
        yield
