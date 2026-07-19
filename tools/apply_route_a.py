#!/usr/bin/env python3
"""Apply the Route A implementation-pathway migration to HeatStreet.

This codemod is tailored to ADEData-Lab/HeatStreet main as inspected at
commit a65612488cb966cab3987e7f1b7fa17b0c8f6aec.

It does not commit changes. It:

1. Preserves the legacy stress-test scenarios.
2. Adds ASHP and spatial implementation scenarios.
3. Adds a property-level implementation pathway planner.
4. Enforces readiness before ASHP installation.