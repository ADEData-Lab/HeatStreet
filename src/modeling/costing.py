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
    """

    ALIAS_MAP = {
        'rad_upsizing': 'radiator_upsizing',
        'emitter_upgrades': 'radiator_upsizing',
        'double_glazing_upgrade': 'double_glazing',
        'triple_glazing_upgrade': 'triple_glazing',
        'heat_pump_installation': 'ashp_installation',
    }

    def __init__(self, costs: Mapping[str, Any], cost_rules: Mapping[str, Any]):
        self.costs = dict(costs or {})
        self.rules = dict(cost_rules or {})
        self.stats = {
            'caps_applied': {},
            'fallback_measures': set(),
        }

    def measure_cost(self, measure: str, property_like: Mapping[str, Any]) -> MeasureCost:
        """Return the cost for a measure and metadata describing the rule.

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
            'rationale': rule.get('rationale'),
        }

        # Legacy fallback
        if not rule:
            cost = float(self.costs.get(normalized, 0))
            self.stats['fallback_measures'].add(normalized)
            detail['raw_cost'] = cost
            detail['final_cost'] = cost
            return cost, detail

        basis = rule.get('basis')

        if basis == 'per_m2':
            cost = self._cost_per_m2(rule, property_like)
        elif basis == 'per_unit':
            cost = self._cost_per_unit(rule, property_like)
        else:
            cost = float(rule.get('fixed_cost', self.costs.get(normalized, 0)))

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

        return " ".join(pieces)
