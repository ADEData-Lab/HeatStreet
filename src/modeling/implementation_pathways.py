"""Route A implementation pathways for Heat Street.

This module is intentionally additive. It preserves the existing stock-wide stress
scenarios, while adding two publication-eligible implementation scenarios that only
install technologies where their deployment contracts pass.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd


ASH_PUMP_SCENARIO = "ashp_implementation"
SPATIAL_SCENARIO = "spatial_implementation"
