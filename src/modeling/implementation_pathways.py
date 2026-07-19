"""Route A implementation pathways for Heat Street.

The existing stock scenarios remain stress tests. This module adds implementation
pathways that enforce deployment contracts at property level:

* an ASHP is installed only after the selected enabling package meets the configured
  post-measure heat-demand and flow-temperature thresholds;
* a heat-network connection is made only for properties in confirmed or committed
  network tiers, configured here as tiers 1 and 2;
* all other properties receive an explicit deferred status and reason.

The module reuses the existing property calculation function so costs, energy, bills,
carbon and COP assumptions remain consistent with the rest of the repository.
"""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from loguru import logger

from config.config import load_config
from src.modeling.scenario_model import (
    ScenarioModeler,
    _calculate_property_upgrade_core,
)
from src.modeling.contracts import PROPERTY_ID_COLUMN, require_property_identifier
from src.utils.profiling import get_chunk_size, get_worker_count


ASHP_IMPLEMENTATION = "ashp_implementation"
SPATIAL_IMPLEMENTATION = "spatial_implementation"
IMPLEMENTATION_SCENARIOS = (ASHP_IMPLEMENTATION, SPATIAL_IMPLEMENTATION)

FINAL_PATHWAYS = {
    "ashp_installed",
    "heat_network_connected",
    "fabric_only",
    "deferred_requires_deeper_retrofit",
    "deferred_requires_survey",
    "deferred_no_network_available",
    "deferred_strategic_network_candidate",
}

DEFAULT_CANDIDATE_MEASURES = (
    "loft_insulation_topup",
    "draught_proofing",
    "floor_insulation",
    "wall_insulation",
    "double_glazing",
    "emitter_upgrades",
)


def _dedupe(items: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _implementation_config(config: Dict[str, Any]) -> Dict[str, Any]:
    section = config.get("implementation_pathways", {})
    eligibility = config.get("eligibility", {}).get("ashp", {})
    return {
        "candidate_measures": tuple(
            section.get("candidate_measures", DEFAULT_CANDIDATE_MEASURES)
        ),
        "maximum_heat_demand_kwh_m2": float(
            section.get(
                "maximum_heat_demand_kwh_m2",
                eligibility.get("max_heat_demand_kwh_per_m2", 100),
            )
        ),
        "maximum_flow_temperature_c": float(
            section.get(
                "maximum_flow_temperature_c",
                eligibility.get("target_flow_temperature_c", 45),
            )
        ),
        "confirmed_network_tiers": frozenset(
            int(value) for value in section.get("confirmed_network_tiers", [1, 2])
        ),
        "strategic_network_tiers": frozenset(
            int(value) for value in section.get("strategic_network_tiers", [3])
        ),
        "require_positive_heat_demand": bool(
            section.get("require_positive_heat_demand", True)
        ),
    }


def _candidate_measure_is_applicable(property_dict: Dict[str, Any], measure: str) -> bool:
    """Avoid clearly redundant measures where EPC-derived flags are available."""
    if measure == "loft_insulation_topup":
        for key in ("needs_loft_insulation", "loft_insulation_needed"):
            if key in property_dict and property_dict[key] is not None:
                return bool(property_dict[key])
    if measure == "wall_insulation":
        for key in ("needs_wall_insulation", "wall_insulation_needed"):
            if key in property_dict and property_dict[key] is not None:
                return bool(property_dict[key])
    if measure == "double_glazing":
        for key in ("needs_double_glazing", "glazing_upgrade_needed"):
            if key in property_dict and property_dict[key] is not None:
                return bool(property_dict[key])
    if measure == "emitter_upgrades":
        for key in ("radiator_upsizing_needed", "needs_radiator_upgrade"):
            if key in property_dict and property_dict[key] is not None:
                return bool(property_dict[key])
    return True


def _calculate(
    property_dict: Dict[str, Any],
    scenario: str,
    measures: Sequence[str],
    modeler: ScenarioModeler,
    *,
    hybrid_pathway: Optional[str] = None,
) -> Dict[str, Any]:
    result = _calculate_property_upgrade_core(
        property_dict,
        scenario,
        list(measures),
        modeler.costs,
        modeler.cost_rules,
        modeler.config,
        any(
            measure
            in {
                "loft_insulation_topup",
                "wall_insulation",
                "double_glazing",
                "triple_glazing",
                "floor_insulation",
                "draught_proofing",
            }
            for measure in measures
        ),
        False,
        hybrid_pathway,
        [],
    )
    return asdict(result)


def _passes_ashp_contract(
    result: Dict[str, Any],
    settings: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    failures: List[str] = []
    demand = pd.to_numeric(
        pd.Series([result.get("post_fabric_heat_demand_kwh_m2")]), errors="coerce"
    ).iloc[0]
    flow = pd.to_numeric(
        pd.Series([result.get("operating_flow_temp_c")]), errors="coerce"
    ).iloc[0]
    baseline = pd.to_numeric(
        pd.Series([result.get("baseline_energy_kwh")]), errors="coerce"
    ).iloc[0]

    if pd.isna(demand):
        failures.append("missing_post_measure_heat_demand")
    elif float(demand) > settings["maximum_heat_demand_kwh_m2"]:
        failures.append("heat_demand_above_threshold")

    if pd.isna(flow):
        failures.append("missing_operating_flow_temperature")
    elif float(flow) > settings["maximum_flow_temperature_c"]:
        failures.append("flow_temperature_above_threshold")

    if settings["require_positive_heat_demand"]:
        if pd.isna(baseline) or float(baseline) <= 0:
            failures.append("non_positive_or_missing_baseline_heat_demand")

    return not failures, failures


def _blank_technology_outputs(result: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure deferred rows cannot be mistaken for completed technology installs."""
    result["heat_pump_electricity_kwh"] = 0.0
    result["heat_pump_electricity_kwh_low"] = 0.0
    result["heat_pump_electricity_kwh_high"] = 0.0
    result["heat_pump_cop_central"] = np.nan
    result["heat_pump_cop_low"] = np.nan
    result["heat_pump_cop_high"] = np.nan
    result["ashp_ready_after_applied_measures"] = False
    return result


def _plan_ashp(
    property_dict: Dict[str, Any],
    scenario: str,
    modeler: ScenarioModeler,
    settings: Dict[str, Any],
) -> Dict[str, Any]:
    candidate_measures = [
        measure
        for measure in settings["candidate_measures"]
        if _candidate_measure_is_applicable(property_dict, measure)
    ]
    selected: List[str] = []
    attempts: List[Dict[str, Any]] = []

    terminal_measures = ["ashp_installation"]
    if "emitter_upgrades" not in candidate_measures:
        terminal_measures.append("emitter_upgrades")

    initial = _calculate(
        property_dict,
        scenario,
        _dedupe([*selected, *terminal_measures]),
        modeler,
        hybrid_pathway="ashp" if scenario == SPATIAL_IMPLEMENTATION else None,
    )
    passed, failures = _passes_ashp_contract(initial, settings)
    attempts.append({"measures": list(selected), "failures": list(failures)})
    if passed:
        final = initial
    else:
        final = initial
        for measure in candidate_measures:
            if measure == "emitter_upgrades" and measure in terminal_measures:
                continue
            selected.append(measure)
            trial_measures = _dedupe([*selected, *terminal_measures])
            trial = _calculate(
                property_dict,
                scenario,
                trial_measures,
                modeler,
                hybrid_pathway="ashp" if scenario == SPATIAL_IMPLEMENTATION else None,
            )
            passed, failures = _passes_ashp_contract(trial, settings)
            attempts.append({"measures": list(selected), "failures": list(failures)})
            final = trial
            if passed:
                break

    final["scenario_family"] = "implementation"
    final["candidate_pathway"] = "ashp"
    final["measures_considered"] = list(candidate_measures)
    final["measure_attempt_count"] = len(attempts)
    final["deployment_contract_failures"] = list(failures)
    final["deployment_contract_passed"] = bool(passed)
    final["ashp_installed"] = bool(passed)
    final["heat_network_connected"] = False
    final["heat_network_confirmed_available"] = False
    final["strategic_network_candidate"] = False
    final["cost_boundary"] = "property_side_only"
    final["shared_system_cost_complete"] = False

    if passed:
        final["final_pathway"] = "ashp_installed"
        final["implementation_status"] = "deployed"
        final["deferred_reason"] = ""
        final["hybrid_pathway"] = (
            "ashp" if scenario == SPATIAL_IMPLEMENTATION else None
        )
    else:
        fabric_only = [
            measure
            for measure in selected
            if measure not in {"ashp_installation", "emitter_upgrades"}
        ]
        if fabric_only:
            final = _calculate(
                property_dict,
                scenario,
                fabric_only,
                modeler,
                hybrid_pathway=None,
            )
        else:
            final = _calculate(property_dict, scenario, [], modeler, hybrid_pathway=None)
        final = _blank_technology_outputs(final)
        final.update(
            {
                "scenario_family": "implementation",
                "candidate_pathway": "ashp",
                "measures_considered": list(candidate_measures),
                "measure_attempt_count": len(attempts),
                "deployment_contract_failures": list(failures),
                "deployment_contract_passed": False,
                "ashp_installed": False,
                "heat_network_connected": False,
                "heat_network_confirmed_available": False,
                "strategic_network_candidate": False,
                "final_pathway": "deferred_requires_deeper_retrofit",
                "implementation_status": "deferred",
                "deferred_reason": ";".join(failures)
                or "readiness_contract_not_met",
                "hybrid_pathway": None,
                "cost_boundary": "property_side_only",
                "shared_system_cost_complete": False,
            }
        )
    return final


def _tier_number(property_dict: Dict[str, Any]) -> Optional[int]:
    value = property_dict.get("tier_number")
    try:
        if value is None or pd.isna(value):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _plan_property(
    property_dict: Dict[str, Any],
    scenario: str,
    modeler: ScenarioModeler,
    settings: Dict[str, Any],
) -> Dict[str, Any]:
    if scenario == ASHP_IMPLEMENTATION:
        return _plan_ashp(property_dict, scenario, modeler, settings)

    if scenario != SPATIAL_IMPLEMENTATION:
        raise ValueError(f"Unknown implementation scenario: {scenario}")

    tier = _tier_number(property_dict)
    confirmed = tier in settings["confirmed_network_tiers"]
    strategic = tier in settings["strategic_network_tiers"]

    if confirmed:
        result = _calculate(
            property_dict,
            scenario,
            ["district_heating_connection"],
            modeler,
            hybrid_pathway="heat_network",
        )
        result.update(
            {
                "scenario_family": "implementation",
                "candidate_pathway": "heat_network",
                "final_pathway": "heat_network_connected",
                "implementation_status": "deployed",
                "deployment_contract_passed": True,
                "deployment_contract_failures": [],
                "ashp_installed": False,
                "heat_network_connected": True,
                "heat_network_confirmed_available": True,
                "strategic_network_candidate": strategic,
                "deferred_reason": "",
                "measures_considered": ["district_heating_connection"],
                "measure_attempt_count": 1,
                "cost_boundary": "property_side_only",
                "shared_system_cost_complete": False,
            }
        )
        return result

    result = _plan_ashp(property_dict, scenario, modeler, settings)
    result["heat_network_confirmed_available"] = False
    result["strategic_network_candidate"] = strategic
    if result["deployment_contract_passed"]:
        return result

    if strategic:
        result["final_pathway"] = "deferred_strategic_network_candidate"
        result["deferred_reason"] = (
            "strategic_network_candidate_without_committed_infrastructure;"
            + str(result.get("deferred_reason", ""))
        ).rstrip(";")
    elif tier is None:
        result["final_pathway"] = "deferred_requires_survey"
        result["deferred_reason"] = (
            "missing_spatial_classification;" + str(result.get("deferred_reason", ""))
        ).rstrip(";")
    else:
        result["final_pathway"] = "deferred_no_network_available"
        result["deferred_reason"] = (
            "no_confirmed_network_and_ashp_contract_failed;"
            + str(result.get("deferred_reason", ""))
        ).rstrip(";")
    return result


def _worker(args: Tuple[Dict[str, Any], str, Dict[str, Any], Dict[str, Any]]) -> Dict[str, Any]:
    property_dict, scenario, config, settings = args
    modeler = ScenarioModeler(config=config)
    return _plan_property(property_dict, scenario, modeler, settings)


class ImplementationPathwayModeler:
    """Model deployable Route A pathways on the authoritative enriched cohort."""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        output_dir: Optional[Path] = None,
    ) -> None:
        self.config = config or load_config()
        self.settings = _implementation_config(self.config)
        self.output_dir = Path(output_dir or Path("data") / "outputs")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.modeler = ScenarioModeler(config=self.config, output_dir=self.output_dir)

    def model_scenario(self, frame: pd.DataFrame, scenario: str) -> pd.DataFrame:
        if scenario not in IMPLEMENTATION_SCENARIOS:
            raise ValueError(f"Unsupported implementation scenario: {scenario}")
        require_property_identifier(frame)
        records = frame.to_dict("records")
        workers = get_worker_count(default=1)
        chunk_size = get_chunk_size(default=5000)
        logger.info(
            "Modeling Route A scenario {} for {:,} properties with {} worker(s)",
            scenario,
            len(records),
            workers,
        )

        if workers <= 1:
            rows = [
                _plan_property(record, scenario, self.modeler, self.settings)
                for record in records
            ]
        else:
            rows: List[Dict[str, Any]] = []
            with ProcessPoolExecutor(max_workers=workers) as executor:
                for start in range(0, len(records), chunk_size):
                    chunk = records[start : start + chunk_size]
                    args = [
                        (record, scenario, self.config, self.settings)
                        for record in chunk
                    ]
                    rows.extend(executor.map(_worker, args, chunksize=50))
        result = pd.DataFrame(rows)
        self._validate_property_results(result, len(frame), scenario)
        return result

    @staticmethod
    def _validate_property_results(
        frame: pd.DataFrame,
        cohort: int,
        scenario: str,
    ) -> None:
        if len(frame) != cohort:
            raise ValueError(
                f"{scenario} produced {len(frame)} rows, expected {cohort}"
            )
        if frame["property_id"].isna().any() or frame["property_id"].duplicated().any():
            raise ValueError(f"{scenario} property identifiers are missing or duplicated")
        invalid = set(frame["final_pathway"].dropna()).difference(FINAL_PATHWAYS)
        if invalid:
            raise ValueError(f"{scenario} contains invalid final pathways: {sorted(invalid)}")
        installed_unready = frame["ashp_installed"].astype(bool) & ~frame[
            "deployment_contract_passed"
        ].astype(bool)
        if installed_unready.any():
            raise ValueError(
                f"{scenario} installs ASHPs at {int(installed_unready.sum())} properties "
                "that fail the deployment contract"
            )
        network_without_availability = frame["heat_network_connected"].astype(bool) & ~frame[
            "heat_network_confirmed_available"
        ].astype(bool)
        if network_without_availability.any():
            raise ValueError(
                f"{scenario} connects {int(network_without_availability.sum())} properties "
                "without confirmed network availability"
            )
        deployed = frame["implementation_status"].eq("deployed")
        deferred = frame["implementation_status"].eq("deferred")
        if not (deployed ^ deferred).all():
            raise ValueError(f"{scenario} has properties without one exclusive final state")
        if frame.loc[deferred, "deferred_reason"].fillna("").str.strip().eq("").any():
            raise ValueError(f"{scenario} contains deferred properties without reasons")

    @staticmethod
    def summarize(frame: pd.DataFrame, scenario: str) -> Dict[str, Any]:
        deployed = frame["implementation_status"].eq("deployed")
        deferred = frame["implementation_status"].eq("deferred")
        total = len(frame)
        costs = pd.to_numeric(frame["capital_cost"], errors="coerce").fillna(0)
        deferred_reasons = Counter(
            reason
            for value in frame.loc[deferred, "deferred_reason"].fillna("")
            for reason in str(value).split(";")
            if reason
        )
        return {
            "scenario_id": scenario,
            "scenario": scenario.replace("_", " ").title(),
            "scenario_family": "implementation",
            "model_purpose": "property-level deployable pathway assessment",
            "headline_reporting_eligible": True,
            "total_properties": total,
            "properties_deployed": int(deployed.sum()),
            "properties_deferred": int(deferred.sum()),
            "deployment_rate_pct": float(deployed.mean() * 100 if total else 0),
            "ashp_installed_properties": int(frame["ashp_installed"].astype(bool).sum()),
            "heat_network_connected_properties": int(
                frame["heat_network_connected"].astype(bool).sum()
            ),
            "strategic_network_candidate_properties": int(
                frame["strategic_network_candidate"].astype(bool).sum()
            ),
            "capital_cost_total": float(costs.sum()),
            "capital_cost_per_total_stock_property": float(costs.mean() if total else 0),
            "capital_cost_per_deployed_property": float(
                costs.loc[deployed].mean() if deployed.any() else 0
            ),
            "annual_energy_reduction_kwh": float(
                pd.to_numeric(
                    frame["annual_energy_reduction_kwh"], errors="coerce"
                ).fillna(0).sum()
            ),
            "annual_co2_reduction_kg": float(
                pd.to_numeric(
                    frame["annual_co2_reduction_kg"], errors="coerce"
                ).fillna(0).sum()
            ),
            "annual_bill_savings": float(
                pd.to_numeric(frame["annual_bill_savings"], errors="coerce")
                .fillna(0)
                .sum()
            ),
            "cost_boundary": "property_side_only",
            "network_backbone_included": False,
            "grid_reinforcement_included": False,
            "deferred_reason_counts": dict(sorted(deferred_reasons.items())),
        }

    def run(self, frame: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
        property_frames: List[pd.DataFrame] = []
        summaries: List[Dict[str, Any]] = []
        for scenario in IMPLEMENTATION_SCENARIOS:
            result = self.model_scenario(frame, scenario)
            property_frames.append(result)
            summaries.append(self.summarize(result, scenario))
        properties = pd.concat(property_frames, ignore_index=True)
        summary = pd.DataFrame(summaries)
        self.save(properties, summary)
        return properties, summary

    def save(self, properties: pd.DataFrame, summary: pd.DataFrame) -> Dict[str, Path]:
        property_path = self.output_dir / "implementation_results_by_property.parquet"
        summary_path = self.output_dir / "implementation_results_summary.csv"
        properties.to_parquet(property_path, index=False)
        summary.to_csv(summary_path, index=False)
        return {"property_path": property_path, "summary_path": summary_path}
