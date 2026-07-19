"""Unambiguous summary reporting for Route A implementation pathways.

The property-level model can attach more than one reason to a deferred property.
This module therefore reports both mutually exclusive reason combinations and
non-exclusive reason incidence. It also separates expenditure on deployed
properties from fabric expenditure retained for properties whose heating
technology deployment is deferred.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, Mapping, Optional

import numpy as np
import pandas as pd


COST_RECONCILIATION_ABS_TOLERANCE_GBP = 1.0
COST_RECONCILIATION_REL_TOLERANCE = 1e-9
REQUIRED_IMPLEMENTATION_SCENARIOS = {
    "ashp_implementation",
    "spatial_implementation",
}
REQUIRED_IMPLEMENTATION_CONTRACTS = {
    "no_unready_ashp_installations",
    "no_unavailable_heat_network_connections",
    "exclusive_final_state",
    "deferred_reason_complete",
    "deferred_reason_combinations_reconcile",
    "capital_cost_components_reconcile",
}


def _reason_tokens(values: Iterable[Any]) -> Counter[str]:
    """Count individual semicolon-delimited reasons, allowing overlap."""
    return Counter(
        token.strip()
        for value in values
        for token in str(value or "").split(";")
        if token.strip()
    )


def _reason_combinations(values: Iterable[Any]) -> Counter[str]:
    """Count exact deferred-reason combinations, one combination per property."""
    return Counter(
        str(value).strip()
        for value in values
        if str(value or "").strip()
    )


def _contract_failure_tokens(values: Iterable[Any]) -> Counter[str]:
    """Count technical deployment-contract failures independently of route reasons."""
    counts: Counter[str] = Counter()
    for value in values:
        if isinstance(value, (list, tuple, set, np.ndarray)):
            tokens = value
        elif value is None or (isinstance(value, float) and np.isnan(value)):
            tokens = []
        else:
            text = str(value).strip()
            if not text:
                tokens = []
            elif text.startswith("[") and text.endswith("]"):
                tokens = [
                    item.strip().strip("'\"")
                    for item in text[1:-1].split(",")
                    if item.strip().strip("'\"")
                ]
            else:
                tokens = text.split(";")
        counts.update(str(token).strip() for token in tokens if str(token).strip())
    return counts


def enrich_implementation_summary(
    properties: pd.DataFrame,
    summary: pd.DataFrame,
) -> pd.DataFrame:
    """Return a validated summary with explicit reason and cost boundaries.

    The function removes the two ambiguous legacy fields:

    * ``deferred_reason_counts`` mixed overlapping reason incidences with an
      apparently reconcilable distribution;
    * ``capital_cost_per_deployed_property`` did not state that it was a mean
      over deployed rows and excluded fabric expenditure on deferred rows.
    """
    required_property_columns = {
        "scenario",
        "implementation_status",
        "capital_cost",
        "deferred_reason",
        "deployment_contract_failures",
    }
    missing = required_property_columns.difference(properties.columns)
    if missing:
        raise ValueError(
            f"Implementation property results are missing summary fields: {sorted(missing)}"
        )

    scenario_key = "scenario_id" if "scenario_id" in summary.columns else "scenario"
    if scenario_key not in summary.columns:
        raise ValueError("Implementation summary lacks a scenario identifier")
    if summary[scenario_key].duplicated().any():
        duplicates = summary.loc[summary[scenario_key].duplicated(), scenario_key].tolist()
        raise ValueError(f"Implementation summary contains duplicate scenarios: {duplicates}")

    enriched_rows: list[Dict[str, Any]] = []
    for row in summary.to_dict("records"):
        scenario = str(row[scenario_key])
        subset = properties.loc[properties["scenario"].eq(scenario)].copy()
        if subset.empty:
            raise ValueError(f"No property results found for implementation scenario {scenario}")

        deployed = subset["implementation_status"].eq("deployed")
        deferred = subset["implementation_status"].eq("deferred")
        if not (deployed ^ deferred).all():
            raise ValueError(f"{scenario} properties do not have exclusive deployed/deferred states")

        total = int(len(subset))
        reported_total = int(row.get("total_properties", total))
        if reported_total != total:
            raise ValueError(
                f"{scenario} summary reports {reported_total} properties, property results contain {total}"
            )

        costs = pd.to_numeric(subset["capital_cost"], errors="coerce")
        if costs.isna().any() or (~np.isfinite(costs)).any() or costs.lt(0).any():
            raise ValueError(f"{scenario} contains missing, non-finite or negative capital costs")

        deployed_total = float(costs.loc[deployed].sum())
        deferred_fabric_total = float(costs.loc[deferred].sum())
        capital_cost_total = float(costs.sum())
        if not np.isclose(
            deployed_total + deferred_fabric_total,
            capital_cost_total,
            rtol=COST_RECONCILIATION_REL_TOLERANCE,
            atol=COST_RECONCILIATION_ABS_TOLERANCE_GBP,
        ):
            raise ValueError(f"{scenario} deployed and deferred costs do not reconcile")

        combination_counts = _reason_combinations(
            subset.loc[deferred, "deferred_reason"].fillna("")
        )
        if sum(combination_counts.values()) != int(deferred.sum()):
            raise ValueError(
                f"{scenario} deferred reason combinations total "
                f"{sum(combination_counts.values())}, expected {int(deferred.sum())}"
            )

        incidence_counts = _reason_tokens(
            subset.loc[deferred, "deferred_reason"].fillna("")
        )
        failure_counts = _contract_failure_tokens(
            subset.loc[deferred, "deployment_contract_failures"]
        )

        clean_row = dict(row)
        clean_row.pop("deferred_reason_counts", None)
        clean_row.pop("capital_cost_per_deployed_property", None)
        clean_row.update(
            {
                "capital_cost_total": capital_cost_total,
                "capital_cost_deployed_total": deployed_total,
                "capital_cost_deferred_fabric_total": deferred_fabric_total,
                "capital_cost_per_total_stock_property": (
                    capital_cost_total / total if total else 0.0
                ),
                "mean_capital_cost_per_deployed_property": (
                    deployed_total / int(deployed.sum()) if deployed.any() else 0.0
                ),
                "mean_fabric_cost_per_deferred_property": (
                    deferred_fabric_total / int(deferred.sum()) if deferred.any() else 0.0
                ),
                "deferred_cost_scope": (
                    "fabric measures retained after technology deployment is deferred; "
                    "ASHP, emitter and heat-network technology costs excluded"
                ),
                "deferred_reason_combination_counts": dict(
                    sorted(combination_counts.items())
                ),
                "deferred_reason_incidence_counts": dict(
                    sorted(incidence_counts.items())
                ),
                "deployment_contract_failure_incidence_counts": dict(
                    sorted(failure_counts.items())
                ),
            }
        )
        enriched_rows.append(clean_row)

    return pd.DataFrame(enriched_rows)


def build_implementation_qa(
    properties: pd.DataFrame,
    summary: pd.DataFrame,
    authoritative_cohort: int,
    *,
    policy: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build and validate the Route A QA payload used by every execution path."""
    cohort = int(authoritative_cohort)
    expected_rows = cohort * len(REQUIRED_IMPLEMENTATION_SCENARIOS)
    if len(properties) != expected_rows:
        raise ValueError(
            f"Implementation property rows total {len(properties)}, expected {expected_rows}"
        )

    required_property_columns = {
        "scenario",
        "implementation_status",
        "ashp_installed",
        "heat_network_connected",
        "heat_network_confirmed_available",
        "deployment_contract_passed",
        "deferred_reason",
        "capital_cost",
    }
    missing = required_property_columns.difference(properties.columns)
    if missing:
        raise ValueError(f"Implementation QA fields are missing: {sorted(missing)}")

    scenarios = set(properties["scenario"].astype(str).unique())
    if scenarios != REQUIRED_IMPLEMENTATION_SCENARIOS:
        raise ValueError(
            f"Implementation property scenarios are {sorted(scenarios)}, "
            f"expected {sorted(REQUIRED_IMPLEMENTATION_SCENARIOS)}"
        )

    installed_unready = properties["ashp_installed"].astype(bool) & ~properties[
        "deployment_contract_passed"
    ].astype(bool)
    unavailable_network = properties["heat_network_connected"].astype(bool) & ~properties[
        "heat_network_confirmed_available"
    ].astype(bool)
    deployed = properties["implementation_status"].eq("deployed")
    deferred = properties["implementation_status"].eq("deferred")
    missing_deferred_reason = deferred & properties["deferred_reason"].fillna("").str.strip().eq("")

    contracts = {
        "no_unready_ashp_installations": not bool(installed_unready.any()),
        "no_unavailable_heat_network_connections": not bool(unavailable_network.any()),
        "exclusive_final_state": bool((deployed ^ deferred).all()),
        "deferred_reason_complete": not bool(missing_deferred_reason.any()),
        "deferred_reason_combinations_reconcile": True,
        "capital_cost_components_reconcile": True,
    }

    scenario_key = "scenario_id" if "scenario_id" in summary.columns else "scenario"
    if scenario_key not in summary.columns:
        raise ValueError("Implementation summary lacks a scenario identifier")
    summary_scenarios = set(summary[scenario_key].astype(str))
    if summary_scenarios != REQUIRED_IMPLEMENTATION_SCENARIOS:
        raise ValueError(
            f"Implementation summary scenarios are {sorted(summary_scenarios)}, "
            f"expected {sorted(REQUIRED_IMPLEMENTATION_SCENARIOS)}"
        )

    for row in summary.to_dict("records"):
        scenario = str(row[scenario_key])
        total = int(row["total_properties"])
        deployed_count = int(row["properties_deployed"])
        deferred_count = int(row["properties_deferred"])
        technology_count = int(row["ashp_installed_properties"]) + int(
            row["heat_network_connected_properties"]
        )
        if total != cohort:
            raise ValueError(f"{scenario} total_properties={total}, expected {cohort}")
        if deployed_count + deferred_count != cohort:
            raise ValueError(f"{scenario} deployed and deferred counts do not reconcile")
        if technology_count != deployed_count:
            raise ValueError(f"{scenario} technology deployments do not reconcile")
        combinations = row.get("deferred_reason_combination_counts", {})
        if not isinstance(combinations, dict) or sum(int(v) for v in combinations.values()) != deferred_count:
            contracts["deferred_reason_combinations_reconcile"] = False
        total_cost = float(row["capital_cost_total"])
        components = float(row["capital_cost_deployed_total"]) + float(
            row["capital_cost_deferred_fabric_total"]
        )
        if not np.isclose(
            total_cost,
            components,
            rtol=COST_RECONCILIATION_REL_TOLERANCE,
            atol=COST_RECONCILIATION_ABS_TOLERANCE_GBP,
        ):
            contracts["capital_cost_components_reconcile"] = False

    failed = [name for name in REQUIRED_IMPLEMENTATION_CONTRACTS if not contracts.get(name)]
    if failed:
        raise ValueError(f"Route A implementation contracts failed: {sorted(failed)}")

    payload: Dict[str, Any] = {
        "status": "pass",
        "authoritative_cohort": cohort,
        "property_rows": int(len(properties)),
        "scenarios": summary.to_dict("records"),
        "contracts": contracts,
    }
    if policy is not None:
        payload["implementation_policy"] = {
            key: sorted(value) if isinstance(value, (set, frozenset)) else value
            for key, value in dict(policy).items()
        }
    return payload
