"""Integrated Heat Street pipeline bootstrap.

The implementation remains in run_analysis_core.py. This bootstrap installs the
Route A phase before exposing the legacy module object, preserving existing imports,
monkeypatching behaviour and command-line usage.
"""

from __future__ import annotations

import sys

import run_analysis_core as _core
from src.integration.route_a_pipeline import install_run_analysis_hooks

install_run_analysis_hooks(_core)

# Preserve `import run_analysis` compatibility by returning the core module object
# after the integration hook has been installed.
sys.modules[__name__] = _core

if __name__ == "__main__":
    raise SystemExit(_core.main())
