"""Shared costing utilities to keep scenario, pathway, and readiness modules aligned."""

from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Tuple

from loguru import logger


MeasureCost = Tuple[float, Dict[str, Any]]


class CostCalculator:
    """Encapsulates retrofit costing rules and helpers.

    The calculator consumes the raw ``costs`` block (legacy flat numbers) and the
    new ``cost_rules`` structure from ``config/config.yaml``. When a rule is not
    supplied, it falls back to the legacy cost while recording that fallback so
    downstream reporting can surface any remaining differences.

    AUDIT FIX: Added size_adjustment_factor to scale costs for properties that
    deviate significantly from the median floor area (~110 m² for terraced houses).
    This addresses the audit finding that uniform costs introduce errors for
    outlier properties (small cottages or large houses).

    Size-based adjustment uses quartile-based scaling:
    - Smallest quartile (<80 m²): 0.7x cost factor
    - Below median (80-110 m²): 0.85x cost factor
    - Median range (110-140 m²): 1.0x cost factor (baseline)
    - Above median (140-180 m²): 1.25x cost factor
    - Largest quartile (>180 m²): 1.5x cost factor
    """

    ALIAS_MAP = {
        'rad_upsizing': 'radiator_upsizing',
        'emitter_upgrades': 'radiator_upsizing',
        'double_glazing_upgrade': 'double_glazing',
        'triple_glazing_upgrade': 'triple_glazing',
        'heat_pump_installation': 'ashp_installation',
    }

    # Size adjustment thresholds based on typical terraced house floor areas
    # Reference: ~110 m² median for Edwardian terraces
    SIZE_ADJUSTMENT_THRESHOLDS = [
        (80, 0.70),    # <80 m² (small): 30% cost reduction
        (110, 0.85),   # 80-110 m² (below median): 15% cost reduction
        (140, 1.00),   # 110-140 m² (median): baseline costs
        (180, 1.25),   # 140-180 m² (above median): 25% cost increase
        (float('inf'), 1.50),  # >180 m² (large): 50% cost increase
    ]

    def __init__(self, costs: Mapping[str, Any], cost_rules: Mapping[str, Any]):
        self.costs = dict(costs or {})
        self.rules = dict(cost_rules or {})
        self.stats = {
            'caps_applied': {},
            'fallback_measures': set(),
            'size_adjustments_applied': 0,
        }

    def measure_cost(self, measure: str, property_like: Mapping[str, Any]) -> MeasureCost:
        """Return the cost for a measure and metadata describing the rule.

        AUDIT FIX: Now applies size-based adjustment to fixed costs to account
        for property size variations. Per-m2 and per-unit costs already scale
        naturally. Fixed costs are adjusted by a factor (0.7-1.5) based on the
        property's floor area relative to the median (~110 m²).

        Args:
            measure: Canonical measure name or alias
            property_like: Dict/Series with property attributes

        Returns:
            (cost, metadata) where metadata captures basis, cap usage, and source
        """

        normalized = self.ALIAS_MAP.get(measure, measure)
        rule = self.rules.get(normalized, {}) or {}

        detail: Dict[str, Any] = {
            'measure': normalized,
            'basis': rule.get('basis', 'legacy_fixed'),
            'source': 'cost_rules' if rule else 'legacy_costs',
            'cap_applied': False,
            'size_adjusted': False,
            'size_adjustment_factor': 1.0,
            'rationale': rule.get('rationale'),
        }

        # Legacy fallback - apply size adjustment
        if not rule:
            base_cost = float(self.costs.get(normalized, 0))
            self.stats['fallback_measures'].add(normalized)

            # Apply size adjustment for fixed/legacy costs
            cost, size_factor = self.apply_size_adjustment(base_cost, property_like)
            detail['raw_cost'] = base_cost
            detail['final_cost'] = cost
            detail['size_adjusted'] = (size_factor != 1.0)
            detail['size_adjustment_factor'] = size_factor
            return cost, detail

        basis = rule.get('basis')

        if basis == 'per_m2':
            # Per-m2 costs already scale with property size
            cost = self._cost_per_m2(rule, property_like)
        elif basis == 'per_unit':
            # Per-unit costs already scale with property size
            cost = self._cost_per_unit(rule, property_like)
        else:
            # Fixed costs - apply size adjustment
            base_cost = float(rule.get('fixed_cost', self.costs.get(normalized, 0)))

            # Check if size adjustment should be applied (can be disabled per-measure)
            apply_size_adj = rule.get('apply_size_adjustment', True)
            cost, size_factor = self.apply_size_adjustment(base_cost, property_like, apply_size_adj)
            detail['size_adjusted'] = (size_factor != 1.0)
            detail['size_adjustment_factor'] = size_factor

        capped_cost, cap_applied = self._apply_caps(cost, rule)

        detail['raw_cost'] = cost
        detail['final_cost'] = capped_cost
        detail['cap_applied'] = cap_applied

        if cap_applied:
            self.stats['caps_applied'][normalized] = self.stats['caps_applied'].get(normalized, 0) + 1

        return capped_cost, detail

    def _apply_caps(self, cost: float, rule: Mapping[str, Any]) -> Tuple[float, bool]:
        cap_applied = False
        min_total = rule.get('min_total')
        if min_total is not None:
            cost = max(float(min_total), float(cost))

        cap = rule.get('cap_per_home')
        if cap is not None:
            capped = min(float(cap), float(cost))
            cap_applied = capped < cost
            cost = capped

        return cost, cap_applied

    def _cost_per_m2(self, rule: Mapping[str, Any], property_like: Mapping[str, Any]) -> float:
        floor_area = property_like.get('TOTAL_FLOOR_AREA', rule.get('floor_area_fallback_m2', 100))
        try:
            area_val = float(floor_area)
        except (TypeError, ValueError):
            area_val = float(rule.get('floor_area_fallback_m2', 100))

        area_share = float(rule.get('area_share_of_floor', 1.0))
        area_multiplier = float(rule.get('area_multiplier', 1.0))
        rate = float(rule.get('rate', 0))

        effective_area = area_val * area_share * area_multiplier
        return effective_area * rate

    def _cost_per_unit(self, rule: Mapping[str, Any], property_like: Mapping[str, Any]) -> float:
        floor_area = property_like.get('TOTAL_FLOOR_AREA', rule.get('floor_area_fallback_m2', 100))
        try:
            area_val = float(floor_area)
        except (TypeError, ValueError):
            area_val = float(rule.get('floor_area_fallback_m2', 100))

        unit_size = float(rule.get('unit_size_m2', 1))
        unit_rate = float(rule.get('unit_rate', 0))
        min_units = int(rule.get('min_units', 0))

        units = max(min_units, int(math.ceil(area_val / unit_size))) if unit_size > 0 else min_units
        return units * unit_rate

    def get_size_adjustment_factor(self, property_like: Mapping[str, Any]) -> float:
        """
        Calculate size adjustment factor based on property floor area.

        AUDIT FIX: Implements cost scaling by dwelling size to address the
        audit finding that uniform costs introduce errors for outlier properties.

        Small properties will have reduced costs (less material, faster install).
        Large properties will have increased costs (more material, longer install).

        Args:
            property_like: Dict/Series with property attributes including TOTAL_FLOOR_AREA

        Returns:
            Adjustment factor (0.7 to 1.5)
        """
        floor_area = property_like.get('TOTAL_FLOOR_AREA', 110)
        try:
            area_val = float(floor_area)
        except (TypeError, ValueError):
            area_val = 110.0  # Default to median

        # Find appropriate adjustment factor
        for threshold, factor in self.SIZE_ADJUSTMENT_THRESHOLDS:
            if area_val <= threshold:
                return factor

        return 1.0  # Fallback

    def apply_size_adjustment(
        self,
        base_cost: float,
        property_like: Mapping[str, Any],
        apply_adjustment: bool = True
    ) -> Tuple[float, float]:
        """
        Apply size-based cost adjustment for legacy fixed costs.

        For measures that use per_m2 or per_unit basis, scaling is already
        built in. This method is for fixed-cost measures where we want to
        add approximate size scaling.

        Args:
            base_cost: Base cost before adjustment
            property_like: Property attributes
            apply_adjustment: Whether to apply (can be disabled via config)

        Returns:
            (adjusted_cost, adjustment_factor)
        """
        if not apply_adjustment:
            return base_cost, 1.0

        factor = self.get_size_adjustment_factor(property_like)
        adjusted = base_cost * factor

        if factor != 1.0:
            self.stats['size_adjustments_applied'] += 1

        return adjusted, factor

    def summary_notes(self) -> str:
        """Human-readable summary of applied bases and fallbacks for logging/reporting."""

        pieces = []

        if self.rules:
            pieces.append("Rule-based costing active for key measures (per-m² vs fixed with caps).")

        if self.stats['caps_applied']:
            measures = ", ".join(f"{m}:{c}" for m, c in sorted(self.stats['caps_applied'].items()))
            pieces.append(f"Caps applied on {measures} properties.")

        if self.stats['fallback_measures']:
            fallbacks = ", ".join(sorted(self.stats['fallback_measures']))
            pieces.append(f"Legacy defaults used for: {fallbacks}.")

        if self.stats['size_adjustments_applied'] > 0:
            pieces.append(
                f"Size-based cost adjustments applied to {self.stats['size_adjustments_applied']:,} "
                f"property-measure combinations (accounts for varying floor areas)."
            )

        return " ".join(pieces)
