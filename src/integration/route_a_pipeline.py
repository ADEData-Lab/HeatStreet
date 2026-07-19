"""Route A integration hooks for the main Heat Street pipeline.

This module keeps the legacy pipeline implementation intact while making Route A a
required run-scoped phase immediately before the one-stop report is generated.
The one-stop report wrapper then promotes the validated implementation pathways to
the headline scenario section while retaining the stock-wide scenarios as stress
tests.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from src.modeling.implementation_summary import (
    REQUIRED_IMPLEMENTATION_CONTRACTS,
    REQUIRED_IMPLEMENTATION_SCENARIOS,
)
from src.utils.implementation_phase import run_implementation_phase
from src.utils.run_integrity import ArtifactManifest, require_current_artifact, stamp_artifact


_REQUIRED_ROUTE_A_ARTIFACTS = [
    "implementation_properties",
    "implementation_summary",
    "implementation_qa",
]


def _parse_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return {}
    text = str(value).strip()
    if not text:
        return {}
    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(text)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {"unparsed": text}


def validate_report_inputs(
    summary: pd.DataFrame,
    qa: dict[str, Any],
    *,
    authoritative_cohort: Optional[int],
) -> None:
    """Reject incomplete, failed or cohort-mismatched Route A report inputs."""
    if summary is None or summary.empty:
        raise RuntimeError("Route A implementation summary is missing or empty")
    required_columns = {
        "scenario_id",
        "total_properties",
        "properties_deployed",
        "properties_deferred",
        "deployment_rate_pct",
        "ashp_installed_properties",
        "heat_network_connected_properties",
        "strategic_network_candidate_properties",
        "capital_cost_total",
        "capital_cost_deployed_total",
        "capital_cost_deferred_fabric_total",
        "mean_capital_cost_per_deployed_property",
        "mean_fabric_cost_per_deferred_property",
        "annual_energy_reduction_kwh",
        "annual_co2_reduction_kg",
        "annual_bill_savings",
        "deferred_reason_combination_counts",
    }
    missing = required_columns.difference(summary.columns)
    if missing:
        raise RuntimeError(f"Route A report fields are missing: {sorted(missing)}")

    scenarios = set(summary["scenario_id"].astype(str))
    if scenarios != REQUIRED_IMPLEMENTATION_SCENARIOS:
        raise RuntimeError(
            f"Route A report scenarios are {sorted(scenarios)}, "
            f"expected {sorted(REQUIRED_IMPLEMENTATION_SCENARIOS)}"
        )
    if qa.get("status") != "pass":
        raise RuntimeError(f"Route A QA status is not pass: {qa.get('status')!r}")
    contracts = qa.get("contracts") or {}
    failed = [name for name in REQUIRED_IMPLEMENTATION_CONTRACTS if contracts.get(name) is not True]
    if failed:
        raise RuntimeError(f"Route A QA contracts failed: {sorted(failed)}")

    cohort = int(authoritative_cohort) if authoritative_cohort is not None else None
    for row in summary.to_dict("records"):
        scenario = str(row["scenario_id"])
        total = int(row["total_properties"])
        deployed = int(row["properties_deployed"])
        deferred = int(row["properties_deferred"])
        if cohort is not None and total != cohort:
            raise RuntimeError(f"{scenario} total_properties={total}, expected {cohort}")
        if deployed + deferred != total:
            raise RuntimeError(f"{scenario} deployed and deferred counts do not reconcile")
        combinations = _parse_mapping(row["deferred_reason_combination_counts"])
        if sum(int(value) for value in combinations.values() if str(value).isdigit()) != deferred:
            raise RuntimeError(f"{scenario} deferred reason combinations do not reconcile")


def run_route_a_before_report(core_module, df, analysis_logger=None, ui=None):
    """Run Route A in the active run and then delegate to the normal report phase."""
    if df is None:
        raise RuntimeError("Route A requires the authoritative spatially enriched dataframe")

    core_module.console.print()
    core_module.console.print(
        core_module.Panel("[bold]Phase 4.8: Route A Implementation Pathways[/bold]", border_style="blue")
    )
    core_module.console.print()
    core_module._ui_phase_started(
        ui,
        "Route A Implementation Pathways",
        "Modeling deployable ASHP and spatial implementation pathways",
    )
    if analysis_logger:
        analysis_logger.start_phase(
            "Route A Implementation Pathways",
            "Model deployable pathways and enforce property-level deployment contracts",
        )

    result = run_implementation_phase(
        df,
        context=core_module._active_run_context,
        outputs_dir=Path(core_module.DATA_OUTPUTS_DIR),
        config=core_module.load_config(),
    )

    summary = result["summary_frame"]
    for row in summary.to_dict("records"):
        scenario = str(row["scenario_id"])
        core_module._ui_metric(
            ui,
            f"{scenario} deployed",
            int(row["properties_deployed"]),
            group=core_module.PHASE_MODELLING,
        )
        core_module._ui_metric(
            ui,
            f"{scenario} deferred",
            int(row["properties_deferred"]),
            group=core_module.PHASE_MODELLING,
        )

    if core_module._active_run_context is not None:
        manifest = ArtifactManifest.load(core_module._active_run_context)
        core_module._require_contract(manifest, _REQUIRED_ROUTE_A_ARTIFACTS)

    if analysis_logger:
        analysis_logger.add_output(
            str(result["summary"]),
            "csv",
            "Route A implementation pathway summary",
        )
        analysis_logger.add_output(
            str(result["properties"]),
            "parquet",
            "Route A property-level implementation results",
        )
        analysis_logger.add_output(
            str(result["qa"]),
            "json",
            "Route A implementation QA contracts",
        )
        analysis_logger.complete_phase(
            success=True,
            message="Route A implementation pathways completed and passed all contracts",
        )

    core_module._ui_output(ui, "Route A summary", result["summary"])
    core_module._ui_output(ui, "Route A QA", result["qa"])
    core_module._ui_phase_completed(
        ui,
        "Route A Implementation Pathways",
        "Implementation pathways passed all contracts",
    )
    return result


def install_run_analysis_hooks(core_module) -> None:
    """Install the Route A phase once on the legacy pipeline module."""
    if getattr(core_module, "_route_a_integration_installed", False):
        return
    original = core_module.generate_one_stop_report

    def integrated_generate_one_stop_report(df=None, analysis_logger=None, ui=None):
        run_route_a_before_report(core_module, df, analysis_logger=analysis_logger, ui=ui)
        return original(df, analysis_logger=analysis_logger, ui=ui)

    integrated_generate_one_stop_report.__name__ = "generate_one_stop_report"
    integrated_generate_one_stop_report.__doc__ = (
        "Run Route A and generate the integrated one-stop JSON report."
    )
    core_module.generate_one_stop_report = integrated_generate_one_stop_report
    core_module._route_a_integration_installed = True


class RouteAOneStopMixin:
    """Post-build integration of validated Route A results into Section 6."""

    def _load_route_a_inputs(self) -> tuple[pd.DataFrame, dict[str, Any]]:
        summary_path = self.output_dir / "implementation_results_summary.csv"
        qa_path = self.output_dir / "implementation_qa.json"
        if self.run_context:
            require_current_artifact(summary_path, self.run_context)
            require_current_artifact(qa_path, self.run_context)
        if not summary_path.is_file() or not qa_path.is_file():
            raise RuntimeError("Route A outputs are required before one-stop report generation")
        summary = pd.read_csv(summary_path)
        qa = json.loads(qa_path.read_text(encoding="utf-8"))
        validate_report_inputs(
            summary,
            qa,
            authoritative_cohort=self.authoritative_cohort_size,
        )
        return summary, qa

    @staticmethod
    def _route_a_datapoints(summary: pd.DataFrame, annotated_datapoint_class) -> list[dict[str, Any]]:
        datapoints: list[dict[str, Any]] = []
        metric_definitions = {
            "properties_deployed": ("Properties deployed", "Properties receiving a heating technology after passing the Route A deployment contract.", "All properties in implementation scenario"),
            "properties_deferred": ("Properties deferred", "Properties not assigned a heating technology because the deployment contract or confirmed-network rule was not met.", "All properties in implementation scenario"),
            "deployment_rate_pct": ("Deployment rate", "Share of the authoritative cohort receiving a modelled heating technology.", "All properties in implementation scenario"),
            "ashp_installed_properties": ("ASHP installations", "Properties receiving an ASHP only after the final readiness contract passes.", "All properties in implementation scenario"),
            "heat_network_connected_properties": ("Heat-network connections", "Properties connected only where network availability is confirmed or committed.", "All properties in implementation scenario"),
            "strategic_network_candidate_properties": ("Strategic network candidates", "Properties in density-led opportunity areas without confirmed or committed network availability.", "All properties in implementation scenario"),
            "capital_cost_total": ("Total implementation capital cost", "Property-side capital cost including deployed pathways and retained fabric expenditure on deferred properties.", "All properties in implementation scenario"),
            "capital_cost_deployed_total": ("Capital cost on deployed properties", "Total property-side capital expenditure for properties receiving a heating technology.", "Deployed properties"),
            "capital_cost_deferred_fabric_total": ("Fabric cost on deferred properties", "Fabric expenditure retained for properties whose heating technology deployment is deferred.", "Deferred properties"),
            "mean_capital_cost_per_deployed_property": ("Mean capital cost per deployed property", "Mean property-side capital expenditure among deployed properties.", "Deployed properties"),
            "mean_fabric_cost_per_deferred_property": ("Mean fabric cost per deferred property", "Mean retained fabric expenditure among deferred properties.", "Deferred properties"),
            "annual_energy_reduction_kwh": ("Annual energy reduction", "Modelled annual delivered-energy reduction for the implementation pathway.", "All properties in implementation scenario"),
            "annual_co2_reduction_kg": ("Annual CO2 reduction", "Modelled annual operational CO2 reduction for the implementation pathway.", "All properties in implementation scenario"),
            "annual_bill_savings": ("Annual bill savings", "Modelled aggregate annual bill savings for the implementation pathway.", "All properties in implementation scenario"),
        }
        for row in summary.to_dict("records"):
            scenario_id = str(row["scenario_id"])
            scenario_label = str(row.get("scenario") or scenario_id.replace("_", " ").title())
            for field, (label, definition, denominator) in metric_definitions.items():
                datapoints.append(
                    annotated_datapoint_class(
                        name=f"{label} ({scenario_label})",
                        key=f"{field}_{scenario_id}",
                        value=row.get(field),
                        definition=definition,
                        denominator=denominator,
                        source=f"data/outputs/implementation_results_summary.csv -> {field} for {scenario_id}",
                        usage="Route A implementation pathway headline reporting",
                    ).to_dict()
                )
            for field, label in (
                ("deferred_reason_combination_counts", "Mutually exclusive deferred-reason combinations"),
                ("deferred_reason_incidence_counts", "Deferred-reason incidence"),
                ("deployment_contract_failure_incidence_counts", "Deployment-contract failure incidence"),
            ):
                datapoints.append(
                    annotated_datapoint_class(
                        name=f"{label} ({scenario_label})",
                        key=f"{field}_{scenario_id}",
                        value=_parse_mapping(row.get(field)),
                        definition=(
                            "Count mapping. Combination counts are mutually exclusive; incidence counts may overlap because one property can fail more than one check."
                        ),
                        denominator="Deferred properties",
                        source=f"data/outputs/implementation_results_summary.csv -> {field} for {scenario_id}",
                        usage="Route A deferral interpretation",
                    ).to_dict()
                )
        return datapoints

    def generate(self):
        summary, qa = self._load_route_a_inputs()
        output_path = super().generate()
        payload = json.loads(Path(output_path).read_text(encoding="utf-8"))
        section = payload["sections"]["section_6"]
        section["title"] = "Section 6: Implementation Pathways and Scenario Stress Tests"
        section["datapoints"] = self._route_a_datapoints(
            summary,
            self._annotated_datapoint_class,
        ) + list(section.get("datapoints", []))

        route_a_table = {
            "caption": "Route A Implementation Pathways",
            "columns": list(summary.columns),
            "data": [
                {
                    key: _parse_mapping(value)
                    if key.endswith("_counts")
                    else (None if pd.isna(value) else value)
                    for key, value in row.items()
                }
                for row in summary.to_dict("records")
            ],
        }
        legacy_tables = list(section.get("tables", []))
        for table in legacy_tables:
            if table.get("caption") == "Complete Scenario Results Summary":
                table["caption"] = "Stock-wide Scenario Stress Tests"
        section["tables"] = [route_a_table, *legacy_tables]
        section["implementation_qa"] = qa
        section["reporting_contract"] = {
            "headline_pathways": sorted(REQUIRED_IMPLEMENTATION_SCENARIOS),
            "stress_tests_retained": True,
            "route_a_required": True,
        }
        payload["metadata"]["version"] = "2.1"
        payload["metadata"]["implementation_pathway_contract"] = "Route A"
        Path(output_path).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        if self.run_context:
            stamp_artifact(
                Path(output_path),
                self.run_context,
                record_count=self.authoritative_cohort_size,
            )
        return output_path
