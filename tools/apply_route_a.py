#!/usr/bin/env python3
"""Apply the Route A implementation-pathway migration to HeatStreet.

This codemod is tailored to ADEData-Lab/HeatStreet as inspected at commit
`a65612488cb966cab3987e7f1b7fa17b0c8f6aec`.

The script is deliberately conservative. It preserves the existing stress-test
scenarios, adds separate implementation scenarios, writes a property-level
planner, integrates it with the scenario model, adds fatal semantic QA checks,
and adds focused tests.

Run from the repository root:

    python tools/apply_route_a.py --dry-run
    python tools/apply_route_a.py

The script creates timestamped backups under `.route_a_backups/`. It does not
commit or push changes.
"""

from __future__ import annotations

import argparse
import copy
import difflib
import json
import py_compile
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


ROOT_MARKERS = ("config/config.yaml", "src/modeling/scenario_model.py")
BACKUP_DIR = ".route_a_backups"


class MigrationError(RuntimeError):
    pass


def repo_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if all((candidate / marker).exists() for marker in ROOT_MARKERS):
            return candidate
    raise MigrationError("Run this script from inside the HeatStreet repository")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str, *, dry_run: bool, changes: list[str]) -> None:
    old = read(path) if path.exists() else ""
    if old == text:
        return
    changes.append(str(path))
    if dry_run:
        diff = difflib.unified_diff(
            old.splitlines(), text.splitlines(),
            fromfile=str(path), tofile=str(path), lineterm="",
        )
        print("\n".join(list(diff)[:160]))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise MigrationError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def insert_before(text: str, marker: str, insertion: str, *, label: str) -> str:
    if insertion.strip() in text:
        return text
    if marker not in text:
        raise MigrationError(f"{label}: marker not found")
    return text.replace(marker, insertion.rstrip() + "\n\n" + marker, 1)


def backup(root: Path, paths: list[Path], *, dry_run: bool) -> Path | None:
    if dry_run:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = root / BACKUP_DIR / stamp
    for path in paths:
        if path.exists():
            target = dest / path.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    return dest


def migrate_config(path: Path, *, dry_run: bool, changes: list[str]) -> None:
    config = yaml.safe_load(read(path))
    scenarios = config.setdefault("scenarios", {})

    definitions = scenarios.get("definitions")
    if definitions is None:
        definitions = {
            key: value for key, value in scenarios.items()
            if key not in {"calculate", "publish", "implementation_policy"}
        }
        scenarios.clear()
        scenarios["calculate"] = []
        scenarios["publish"] = []
        scenarios["definitions"] = definitions

    stress_ids = [
        "baseline", "fabric_only", "fabric_to_tipping_point",
        "minimum_fabric_hp_ready", "heat_pump", "heat_network", "hybrid",
    ]
    calculate = [item for item in scenarios.get("calculate", stress_ids) if item in definitions]

    for scenario_id in ("minimum_fabric_hp_ready", "heat_pump", "heat_network", "hybrid"):
        if scenario_id in definitions:
            definitions[scenario_id]["scenario_family"] = "stress_test"
            definitions[scenario_id]["headline_reporting_eligible"] = False

    definitions["ashp_implementation"] = {
        "name": "Modelled ASHP implementation pathway",
        "description": (
            "Property-specific enabling measures are selected and performance is "
            "recalculated before installation. An ASHP is installed only where the "
            "post-measure implementation contract passes; unresolved homes are deferred."
        ),
        "scenario_family": "implementation",
        "headline_reporting_eligible": True,
        "implementation_mode": "ashp",
        "requires_all_ashp_properties_ready": True,
        "unresolved_property_action": "defer",
        "measures": ["property_specific_enabling_package"],
    }
    definitions["spatial_implementation"] = {
        "name": "Modelled spatial implementation pathway",
        "description": (
            "Properties connect to a heat network only where existing or committed "
            "network availability is evidenced. Other properties enter the ASHP "
            "planner and are installed only after the readiness contract passes."
        ),
        "scenario_family": "implementation",
        "headline_reporting_eligible": True,
        "implementation_mode": "spatial",
        "requires_all_ashp_properties_ready": True,
        "requires_confirmed_network_availability": True,
        "unresolved_property_action": "defer",
        "measures": ["property_specific_pathway"],
    }

    for item in ("ashp_implementation", "spatial_implementation"):
        if item not in calculate:
            calculate.append(item)

    scenarios["calculate"] = calculate
    scenarios["publish"] = ["fabric_only", "ashp_implementation", "spatial_implementation"]
    scenarios["implementation_policy"] = {
        "confirmed_network_tiers": [1, 2],
        "strategic_network_candidate_tiers": [3],
        "candidate_measure_order": [
            "loft_insulation_topup", "draught_proofing", "floor_insulation",
            "wall_insulation", "double_glazing", "emitter_upgrades",
        ],
        "maximum_post_fabric_heat_demand_kwh_m2": 100,
        "maximum_operating_flow_temperature_c": 45,
        "require_positive_modelled_heat_demand": True,
        "defer_on_missing_required_inputs": True,
    }

    output = yaml.safe_dump(config, sort_keys=False, allow_unicode=True, width=100)
    write(path, output, dry_run=dry_run, changes=changes)


PLANNER_MODULE = r'''"""Property-level implementation pathway planning.

This module separates deployable implementation pathways from stock-wide stress
tests. It deliberately returns an explicit final state and deferral reason for
every property.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import math


@dataclass(frozen=True)
class ImplementationPlan:
    candidate_pathway: str
    final_pathway: str
    implementation_status: str
    deployment_contract_passed: bool
    measures_applied: list[str] = field(default_factory=list)
    measures_considered: list[str] = field(default_factory=list)
    failed_checks: list[str] = field(default_factory=list)
    deferred_reason: str = ""
    post_measure_heat_demand_kwh_m2: float | None = None
    post_measure_flow_temperature_c: float | None = None
    heat_network_confirmed_available: bool = False
    strategic_network_candidate: bool = False


class ImplementationPathwayPlanner:
    """Select measures, recalculate screening metrics, then route technology."""

    def __init__(self, config: Mapping[str, Any]):
        self.config = config
        policy = config.get("scenarios", {}).get("implementation_policy", {})
        eligibility = config.get("eligibility", {}).get("ashp", {})
        self.max_heat_demand = float(policy.get(
            "maximum_post_fabric_heat_demand_kwh_m2",
            eligibility.get("max_heat_demand_kwh_per_m2", 100),
        ))
        self.max_flow_temp = float(policy.get(
            "maximum_operating_flow_temperature_c",
            eligibility.get("target_flow_temperature_c", 45),
        ))
        self.measure_order = list(policy.get("candidate_measure_order", []))
        self.confirmed_network_tiers = set(policy.get("confirmed_network_tiers", [1, 2]))
        self.strategic_network_tiers = set(policy.get("strategic_network_candidate_tiers", [3]))
        self.measure_savings = config.get("measure_savings", {})

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    def _baseline_intensity(self, prop: Mapping[str, Any]) -> float | None:
        for key in (
            "energy_consumption_adjusted",
            "energy_consumption_adjusted_central",
            "ENERGY_CONSUMPTION_CURRENT",
            "heat_demand_kwh_m2",
        ):
            value = self._number(prop.get(key))
            if value is not None and value >= 0:
                return value
        return None

    def _baseline_flow_temp(self, prop: Mapping[str, Any]) -> float | None:
        for key in ("estimated_flow_temp", "estimated_flow_temp_c", "operating_flow_temp_c"):
            value = self._number(prop.get(key))
            if value is not None:
                return value
        return None

    def _measure_needed(self, measure: str, prop: Mapping[str, Any]) -> bool:
        explicit = {
            "loft_insulation_topup": "needs_loft_topup",
            "wall_insulation": "needs_wall_insulation",
            "double_glazing": "needs_glazing_upgrade",
            "emitter_upgrades": "needs_radiator_upsizing",
            "floor_insulation": "needs_floor_insulation",
        }
        flag = explicit.get(measure)
        if flag in prop and prop.get(flag) is not None:
            return bool(prop.get(flag))
        if measure == "double_glazing":
            return str(prop.get("glazing_type", prop.get("glazing", ""))).lower() == "single"
        return True

    def _saving_fraction(self, measure: str, prop: Mapping[str, Any]) -> float:
        cfg = self.measure_savings.get(measure, {})
        if measure == "wall_insulation":
            wall = str(prop.get("wall_type", "Solid")).lower()
            key = "cavity_kwh_saving_pct" if "cavity" in wall else "solid_kwh_saving_pct"
            return float(cfg.get(key, 0.0) or 0.0)
        return float(cfg.get("kwh_saving_pct", 0.0) or 0.0)

    def _flow_reduction(self, measure: str) -> float:
        key = "radiator_upsizing" if measure == "emitter_upgrades" else measure
        return float(self.measure_savings.get(key, {}).get("flow_temp_reduction_k", 0.0) or 0.0)

    def _ashp_plan(self, prop: Mapping[str, Any]) -> ImplementationPlan:
        intensity = self._baseline_intensity(prop)
        flow_temp = self._baseline_flow_temp(prop)
        considered: list[str] = []
        applied: list[str] = []

        if intensity is None:
            return ImplementationPlan(
                candidate_pathway="ashp", final_pathway="deferred_requires_survey",
                implementation_status="deferred", deployment_contract_passed=False,
                failed_checks=["missing_heat_demand"], deferred_reason="missing_heat_demand",
            )
        if intensity <= 0:
            return ImplementationPlan(
                candidate_pathway="ashp", final_pathway="deferred_requires_survey",
                implementation_status="deferred", deployment_contract_passed=False,
                failed_checks=["non_positive_heat_demand"], deferred_reason="non_positive_heat_demand",
                post_measure_heat_demand_kwh_m2=intensity,
            )

        current_intensity = intensity
        current_flow = flow_temp
        for measure in self.measure_order:
            if current_intensity <= self.max_heat_demand and (
                current_flow is None or current_flow <= self.max_flow_temp
            ):
                break
            considered.append(measure)
            if not self._measure_needed(measure, prop):
                continue
            applied.append(measure)
            saving = min(max(self._saving_fraction(measure, prop), 0.0), 0.95)
            current_intensity *= 1.0 - saving
            if current_flow is not None:
                current_flow -= self._flow_reduction(measure)

        failed: list[str] = []
        if current_intensity > self.max_heat_demand:
            failed.append("heat_demand_above_threshold")
        if current_flow is None:
            failed.append("flow_temperature_requires_survey")
        elif current_flow > self.max_flow_temp:
            failed.append("flow_temperature_above_threshold")

        passes = not failed
        if passes:
            applied.extend(["ashp_installation"])
            if "emitter_upgrades" not in applied and bool(prop.get("needs_radiator_upsizing", False)):
                applied.insert(-1, "emitter_upgrades")
            return ImplementationPlan(
                candidate_pathway="ashp", final_pathway="ashp_installed",
                implementation_status="deployed", deployment_contract_passed=True,
                measures_applied=applied, measures_considered=considered,
                post_measure_heat_demand_kwh_m2=current_intensity,
                post_measure_flow_temperature_c=current_flow,
            )

        reason = "requires_property_survey" if "flow_temperature_requires_survey" in failed else "requires_deeper_retrofit"
        return ImplementationPlan(
            candidate_pathway="ashp", final_pathway=f"deferred_{reason}",
            implementation_status="deferred", deployment_contract_passed=False,
            measures_applied=applied, measures_considered=considered,
            failed_checks=failed, deferred_reason=reason,
            post_measure_heat_demand_kwh_m2=current_intensity,
            post_measure_flow_temperature_c=current_flow,
        )

    def plan(self, prop: Mapping[str, Any], mode: str) -> ImplementationPlan:
        tier = self._number(prop.get("tier_number"))
        tier_int = int(tier) if tier is not None else None
        confirmed = tier_int in self.confirmed_network_tiers
        strategic = tier_int in self.strategic_network_tiers

        if mode == "spatial" and confirmed:
            return ImplementationPlan(
                candidate_pathway="heat_network", final_pathway="heat_network_connected",
                implementation_status="deployed", deployment_contract_passed=True,
                measures_applied=["district_heating_connection"],
                heat_network_confirmed_available=True,
                strategic_network_candidate=strategic,
            )

        result = self._ashp_plan(prop)
        if mode == "spatial" and not result.deployment_contract_passed and strategic:
            return ImplementationPlan(
                candidate_pathway="strategic_network_candidate",
                final_pathway="deferred_strategic_network_candidate",
                implementation_status="deferred", deployment_contract_passed=False,
                measures_applied=result.measures_applied,
                measures_considered=result.measures_considered,
                failed_checks=result.failed_checks,
                deferred_reason="strategic_network_candidate_without_committed_infrastructure",
                post_measure_heat_demand_kwh_m2=result.post_measure_heat_demand_kwh_m2,
                post_measure_flow_temperature_c=result.post_measure_flow_temperature_c,
                heat_network_confirmed_available=False,
                strategic_network_candidate=True,
            )
        return result
'''


TEST_MODULE = r'''from src.modeling.implementation_pathway import ImplementationPathwayPlanner


def config():
    return {
        "eligibility": {"ashp": {"max_heat_demand_kwh_per_m2": 100, "target_flow_temperature_c": 45}},
        "scenarios": {"implementation_policy": {
            "confirmed_network_tiers": [1, 2],
            "strategic_network_candidate_tiers": [3],
            "candidate_measure_order": ["loft_insulation_topup", "wall_insulation", "emitter_upgrades"],
        }},
        "measure_savings": {
            "loft_insulation_topup": {"kwh_saving_pct": 0.20, "flow_temp_reduction_k": 3},
            "wall_insulation": {"solid_kwh_saving_pct": 0.30, "cavity_kwh_saving_pct": 0.20, "flow_temp_reduction_k": 5},
            "radiator_upsizing": {"flow_temp_reduction_k": 10},
        },
    }


def test_ready_property_gets_ashp():
    plan = ImplementationPathwayPlanner(config()).plan({
        "energy_consumption_adjusted": 90, "estimated_flow_temp": 44, "tier_number": 4,
    }, "ashp")
    assert plan.final_pathway == "ashp_installed"
    assert plan.deployment_contract_passed
    assert "ashp_installation" in plan.measures_applied


def test_unready_property_is_deferred():
    plan = ImplementationPathwayPlanner(config()).plan({
        "energy_consumption_adjusted": 300, "estimated_flow_temp": 70,
        "needs_loft_topup": True, "needs_wall_insulation": True,
        "needs_radiator_upsizing": True, "tier_number": 4,
    }, "ashp")
    assert plan.implementation_status == "deferred"
    assert "ashp_installation" not in plan.measures_applied


def test_high_density_without_network_is_not_connected():
    plan = ImplementationPathwayPlanner(config()).plan({
        "energy_consumption_adjusted": 300, "estimated_flow_temp": 70,
        "needs_loft_topup": True, "needs_wall_insulation": True,
        "needs_radiator_upsizing": True, "tier_number": 3,
    }, "spatial")
    assert plan.final_pathway == "deferred_strategic_network_candidate"
    assert "district_heating_connection" not in plan.measures_applied


def test_confirmed_network_connects():
    plan = ImplementationPathwayPlanner(config()).plan({
        "energy_consumption_adjusted": 300, "estimated_flow_temp": 70, "tier_number": 1,
    }, "spatial")
    assert plan.final_pathway == "heat_network_connected"
    assert plan.heat_network_confirmed_available
'''


def patch_contracts(path: Path, *, dry_run: bool, changes: list[str]) -> None:
    text = read(path)
    text = replace_once(
        text,
        "HN_READY_TIERS = frozenset({1, 2, 3})",
        "# Only existing or committed network evidence counts as implementation-ready.\nHN_READY_TIERS = frozenset({1, 2})\nSTRATEGIC_HN_CANDIDATE_TIERS = frozenset({3})",
        label="confirmed network tiers",
    )
    write(path, text, dry_run=dry_run, changes=changes)


def patch_scenario_model(path: Path, *, dry_run: bool, changes: list[str]) -> None:
    text = read(path)
    import_marker = "from src.modeling.costing import CostCalculator\n"
    import_line = "from src.modeling.implementation_pathway import ImplementationPathwayPlanner\n"
    if import_line not in text:
        text = replace_once(text, import_marker, import_marker + import_line, label="planner import")

    init_marker = "        self.adjuster = MethodologicalAdjustments()\n"
    init_line = "        self.implementation_planner = ImplementationPathwayPlanner(self.config)\n"
    if init_line not in text:
        text = replace_once(text, init_marker, init_marker + init_line, label="planner init")

    dispatch_old = """        df_ready = self._ensure_adjusted_baseline(df)\n\n        if not measures:\n            # Baseline scenario - no interventions\n            return self._model_baseline(df_ready)\n"""
    dispatch_new = """        df_ready = self._ensure_adjusted_baseline(df)\n\n        if scenario_config.get('scenario_family') == 'implementation':\n            return self._model_implementation_scenario(\n                df_ready, scenario_name, scenario_config, progress_callback=progress_callback\n            )\n\n        if not measures:\n            # Baseline scenario - no interventions\n            return self._model_baseline(df_ready)\n"""
    if dispatch_new not in text:
        text = replace_once(text, dispatch_old, dispatch_new, label="implementation dispatch")

    method = r'''    def _model_implementation_scenario(
        self,
        df: pd.DataFrame,
        scenario_name: str,
        scenario_config: Dict[str, Any],
        progress_callback: Optional[Callable[[Dict], None]] = None,
    ) -> Dict[str, Any]:
        """Model one implementation pathway with explicit deployed or deferred states."""
        df_ready = self._preprocess_ashp_readiness(self._ensure_adjusted_baseline(df))
        mode = str(scenario_config.get("implementation_mode", "ashp"))
        rows: List[Dict[str, Any]] = []

        for index, prop in enumerate(df_ready.to_dict("records"), start=1):
            plan = self.implementation_planner.plan(prop, mode)
            upgrade = _calculate_property_upgrade_core(
                prop,
                scenario_name,
                plan.measures_applied,
                self.costs,
                self.cost_rules,
                self.config,
                bool(plan.measures_applied),
                False,
                None,
                [],
            )
            row = asdict(upgrade)
            row.update({
                "scenario_family": "implementation",
                "candidate_pathway": plan.candidate_pathway,
                "final_pathway": plan.final_pathway,
                "implementation_status": plan.implementation_status,
                "deployment_contract_passed": plan.deployment_contract_passed,
                "deployment_contract_failures": plan.failed_checks,
                "measures_considered": plan.measures_considered,
                "deferred_reason": plan.deferred_reason,
                "heat_network_confirmed_available": plan.heat_network_confirmed_available,
                "strategic_network_candidate": plan.strategic_network_candidate,
            })
            rows.append(row)
            if progress_callback and index % 10000 == 0:
                progress_callback({
                    "event": "scenario_chunk_progress",
                    "scenario_name": scenario_name,
                    "properties_done": index,
                    "total_properties": len(df_ready),
                })

        property_df = pd.DataFrame(rows)
        self.property_results[scenario_name] = property_df
        results = self._aggregate_scenario_results(property_df, df_ready)
        deployed = property_df["implementation_status"].eq("deployed")
        results.update({
            "scenario_name": scenario_name,
            "scenario_label": self._get_scenario_label(scenario_name),
            "scenario_family": "implementation",
            "headline_reporting_eligible": bool(scenario_config.get("headline_reporting_eligible", True)),
            "properties_assessed": int(len(property_df)),
            "properties_deployed": int(deployed.sum()),
            "properties_deferred": int((~deployed).sum()),
            "deployment_rate_pct": float(deployed.mean() * 100) if len(property_df) else 0.0,
            "ashp_installed_properties": int(property_df["final_pathway"].eq("ashp_installed").sum()),
            "hn_assigned_properties": int(property_df["final_pathway"].eq("heat_network_connected").sum()),
            "ashp_assigned_properties": int(property_df["final_pathway"].eq("ashp_installed").sum()),
            "deferred_reason_counts": property_df.loc[~deployed, "deferred_reason"].value_counts().to_dict(),
            "measures": ["property_specific_pathway"],
        })
        return results
'''
    text = insert_before(text, "    def _model_baseline(self, df: pd.DataFrame) -> Dict:\n", method, label="implementation method")
    write(path, text, dry_run=dry_run, changes=changes)


def patch_semantic_qa(path: Path, *, dry_run: bool, changes: list[str]) -> None:
    text = read(path)
    call_marker = "    _check(checks, \"scenario_readiness_reconciliation\", lambda: _validate_scenario_readiness_reconciliation(\n"
    insertion = "    _check(checks, \"implementation_pathway_contract\", lambda: _validate_implementation_pathways(scenario_properties, scenarios))\n"
    if insertion not in text:
        if call_marker not in text:
            raise MigrationError("semantic QA insertion marker not found")
        text = text.replace(call_marker, insertion + call_marker, 1)

    fn = r'''def _validate_implementation_pathways(
    properties: pd.DataFrame,
    scenarios: pd.DataFrame,
) -> dict[str, dict[str, int]]:
    """Fail publication if implementation routes breach technology contracts."""
    required = {
        "scenario", "scenario_family", "final_pathway", "implementation_status",
        "deployment_contract_passed", "measures_applied",
        "heat_network_confirmed_available", "deferred_reason",
    }
    missing = required.difference(properties.columns)
    if missing:
        raise ValueError(f"implementation pathway fields missing: {sorted(missing)}")

    implementation = properties[properties["scenario_family"].eq("implementation")].copy()
    if implementation.empty:
        raise ValueError("no implementation scenario property results found")

    result: dict[str, dict[str, int]] = {}
    for scenario_id, subset in implementation.groupby("scenario"):
        installed_ashp = subset["final_pathway"].eq("ashp_installed")
        connected_hn = subset["final_pathway"].eq("heat_network_connected")
        deferred = subset["implementation_status"].eq("deferred")
        passed = subset["deployment_contract_passed"].fillna(False).astype(bool)

        if (installed_ashp & ~passed).any():
            raise ValueError(f"{scenario_id} installs ASHPs without a passing contract")
        if (connected_hn & ~subset["heat_network_confirmed_available"].fillna(False).astype(bool)).any():
            raise ValueError(f"{scenario_id} connects properties without confirmed network availability")
        if (deferred & subset["deferred_reason"].fillna("").eq("")).any():
            raise ValueError(f"{scenario_id} contains deferred properties without reasons")
        if not subset["implementation_status"].isin(["deployed", "deferred"]).all():
            raise ValueError(f"{scenario_id} contains invalid implementation states")
        if int((installed_ashp | connected_hn | deferred).sum()) != len(subset):
            raise ValueError(f"{scenario_id} does not assign exactly one final state per property")

        result[str(scenario_id)] = {
            "properties": int(len(subset)),
            "ashp_installed": int(installed_ashp.sum()),
            "heat_network_connected": int(connected_hn.sum()),
            "deferred": int(deferred.sum()),
        }
    return result
'''
    text = insert_before(text, "def _validate_scenario_readiness_reconciliation(\n", fn, label="implementation QA function")
    write(path, text, dry_run=dry_run, changes=changes)


def validate(root: Path, *, run_tests: bool) -> None:
    targets = [
        root / "src/modeling/implementation_pathway.py",
        root / "src/modeling/scenario_model.py",
        root / "src/utils/semantic_qa.py",
        root / "tests/test_implementation_pathway.py",
    ]
    for target in targets:
        py_compile.compile(str(target), doraise=True)
    if run_tests:
        subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "tests/test_implementation_pathway.py"],
            cwd=root,
            check=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    parser.add_argument("--no-tests", action="store_true", help="Skip focused pytest validation")
    args = parser.parse_args()

    root = repo_root(Path.cwd())
    paths = [
        root / "config/config.yaml",
        root / "src/modeling/contracts.py",
        root / "src/modeling/scenario_model.py",
        root / "src/utils/semantic_qa.py",
        root / "src/modeling/implementation_pathway.py",
        root / "tests/test_implementation_pathway.py",
    ]
    backup_path = backup(root, paths, dry_run=args.dry_run)
    changes: list[str] = []

    migrate_config(paths[0], dry_run=args.dry_run, changes=changes)
    patch_contracts(paths[1], dry_run=args.dry_run, changes=changes)
    patch_scenario_model(paths[2], dry_run=args.dry_run, changes=changes)
    patch_semantic_qa(paths[3], dry_run=args.dry_run, changes=changes)
    write(paths[4], PLANNER_MODULE, dry_run=args.dry_run, changes=changes)
    write(paths[5], TEST_MODULE, dry_run=args.dry_run, changes=changes)

    if args.dry_run:
        print(json.dumps({"dry_run": True, "files_that_would_change": changes}, indent=2))
        return 0

    validate(root, run_tests=not args.no_tests)
    print(json.dumps({
        "status": "ok",
        "backup": str(backup_path) if backup_path else None,
        "changed_files": changes,
        "next_steps": [
            "Run the full test suite: python -m pytest -q",
            "Run a development analysis and inspect deployment and deferral counts",
            "Do not publish unless semantic QA passes with zero critical failures",
        ],
    }, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (MigrationError, subprocess.CalledProcessError) as exc:
        print(f"Route A migration failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
