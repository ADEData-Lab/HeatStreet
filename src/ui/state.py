"""Shared mutable state for all HeatStreet Studio UI renderers."""

from __future__ import annotations

import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional


# ------------------------------------------------------------------
# Phase state
# ------------------------------------------------------------------

@dataclass
class PhaseState:
    """Per-phase progress tracking, independent of rendering."""

    name: str
    status: str = "pending"  # pending | running | completed | failed | skipped | waiting
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    progress_current: Optional[float] = None
    progress_total: Optional[float] = None
    current_action: str = ""

    def elapsed(self, now: Optional[float] = None) -> float:
        if self.started_at is None:
            return 0.0
        end = self.completed_at or (now or time.time())
        return max(0.0, end - self.started_at)

    def progress_fraction(self) -> Optional[float]:
        if self.progress_current is None or not self.progress_total:
            return None
        return max(0.0, min(1.0, float(self.progress_current) / float(self.progress_total)))


# ------------------------------------------------------------------
# Specialised sub-state containers
# ------------------------------------------------------------------

@dataclass
class AcquisitionCounters:
    zip_bytes_downloaded: Optional[int] = None
    zip_bytes_total: Optional[int] = None
    members_selected: int = 0
    members_ignored: int = 0
    members_processed: int = 0
    rows_read: int = 0
    rows_retained: int = 0
    rows_malformed: int = 0
    parquet_parts: int = 0
    london_records: int = 0
    stock_records: int = 0
    rows_per_second: Optional[float] = None
    mb_per_second: Optional[float] = None
    zip_status: str = "pending"  # pending | downloading | done | failed


@dataclass
class ValidationFunnel:
    input_records: Optional[int] = None
    schema_passed: Optional[int] = None
    after_dedup: Optional[int] = None
    plausibility_passed: Optional[int] = None
    output_records: Optional[int] = None
    duplicates_removed: Optional[int] = None
    invalid_records: Optional[int] = None
    validation_rate: Optional[float] = None
    warnings: int = 0
    output_path: Optional[str] = None


@dataclass
class ArchetypeState:
    total_properties: Optional[int] = None
    pre_1930_terraced: Optional[int] = None
    dominant_epc_band: Optional[str] = None
    most_common_wall_type: Optional[str] = None
    most_common_heating: Optional[str] = None
    epc_distribution: Dict[str, int] = field(default_factory=dict)


@dataclass
class ScenarioState:
    name: str
    status: str = "pending"
    progress_current: Optional[float] = None
    progress_total: Optional[float] = None
    properties_processed: Optional[int] = None
    mean_capex: Optional[float] = None
    total_capex: Optional[float] = None
    carbon_impact: Optional[float] = None
    bill_impact: Optional[float] = None
    output_status: str = "pending"


@dataclass
class RetrofitTierState:
    tier_1_count: Optional[int] = None
    tier_2_count: Optional[int] = None
    tier_3_count: Optional[int] = None
    tier_4_count: Optional[int] = None
    tier_5_count: Optional[int] = None
    mean_fabric_cost: Optional[float] = None
    total_investment: Optional[float] = None
    solid_wall_barrier: Optional[int] = None
    glazing_barrier: Optional[int] = None
    heating_barrier: Optional[int] = None

    def counts(self) -> List[Optional[int]]:
        return [
            self.tier_1_count, self.tier_2_count, self.tier_3_count,
            self.tier_4_count, self.tier_5_count,
        ]

    def total(self) -> int:
        return sum(c for c in self.counts() if c is not None)


@dataclass
class SpatialState:
    geopandas_ok: Optional[bool] = None
    shapely_ok: Optional[bool] = None
    pyproj_ok: Optional[bool] = None
    pyogrio_ok: Optional[bool] = None
    fiona_ok: Optional[bool] = None
    gdal_ok: Optional[bool] = None
    conda_ok: Optional[bool] = None
    current_step: Optional[str] = None
    steps_done: List[str] = field(default_factory=list)
    borough_progress: Dict[str, str] = field(default_factory=dict)
    tier_counts: Dict[str, int] = field(default_factory=dict)
    gis_output_status: str = "pending"


@dataclass
class OutputEntry:
    label: str
    path: str
    output_type: str = "file"  # file | report | figure | map | log | dashboard
    description: str = ""
    recommended: bool = False
    size_bytes: Optional[int] = None
    modified_time: Optional[float] = None


# ------------------------------------------------------------------
# Top-level dashboard state
# ------------------------------------------------------------------

_METRIC_GROUPS = ("Acquisition", "Validation", "Modelling", "Outputs")


def _metric_map() -> Dict[str, "OrderedDict[str, str]"]:
    return {group: OrderedDict() for group in _METRIC_GROUPS}


