"""Atomic Route A implementation phase for the main Heat Street pipeline."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from loguru import logger

from src.modeling.implementation_pathways import ImplementationPathwayModeler
from src.modeling.implementation_summary import (
    build_implementation_qa,
    enrich_implementation_summary,
)
from src.utils.run_integrity import ArtifactManifest, RunContext, stamp_artifact


MANIFEST_NAMES = {
    "properties": "implementation_properties",
    "summary": "implementation_summary",
    "qa": "implementation_qa",
}


def output_paths(root: Path) -> dict[str, Path]:
    root = Path(root)
    return {
        "properties": root / "implementation_results_by_property.parquet",
        "summary": root / "implementation_results_summary.csv",
        "qa": root / "implementation_qa.json",
    }


def _cleanup_candidate(candidate: Path) -> None:
    shutil.rmtree(candidate, ignore_errors=True)


def _promote(paths: dict[str, Path], outputs_dir: Path) -> dict[str, Path]:
    outputs_dir = Path(outputs_dir)
    outputs_dir.mkdir(parents=True, exist_ok=True)
    promoted: dict[str, Path] = {}
    backups: list[tuple[Path, Path]] = []
    completed: list[Path] = []
    backup_dir = outputs_dir / ".implementation-promotion-backup"
    _cleanup_candidate(backup_dir)
    try:
        for key, source in paths.items():
            destination = outputs_dir / source.name
            if destination.exists():
                backup = backup_dir / source.name
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(destination, backup)
                backups.append((backup, destination))
            os.replace(source, destination)
            completed.append(destination)
            promoted[key] = destination
    except Exception:
        for destination in reversed(completed):
            destination.unlink(missing_ok=True)
        for backup, destination in reversed(backups):
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(backup, destination)
        raise
    finally:
        _cleanup_candidate(backup_dir)
    return promoted


def validate_outputs(
    properties: pd.DataFrame,
    summary: pd.DataFrame,
    qa: dict[str, Any],
    *,
    cohort_size: int,
) -> None:
    expected_scenarios = {"ashp_implementation", "spatial_implementation"}
    if len(properties) != cohort_size * len(expected_scenarios):
        raise RuntimeError(
            f"Route A property rows={len(properties)}, expected={cohort_size * len(expected_scenarios)}"
        )
    scenario_counts = properties.groupby("scenario").size().to_dict()
    if set(scenario_counts) != expected_scenarios:
        raise RuntimeError(f"Route A scenarios are incomplete: {sorted(scenario_counts)}")
    for scenario, count in scenario_counts.items():
        if int(count) != int(cohort_size):
            raise RuntimeError(
                f"Route A scenario {scenario} rows={count}, expected={cohort_size}"
            )

    required_summary_columns = {
        "scenario_id",
        "total_properties",
        "properties_deployed",
        "properties_deferred",
        "ashp_installed_properties",
        "heat_network_connected_properties",
        "capital_cost_total",
        "capital_cost_deployed_total",
        "capital_cost_deferred_fabric_total",
        "deferred_reason_combination_counts",
    }
    missing = required_summary_columns.difference(summary.columns)
    if missing:
        raise RuntimeError(f"Route A summary fields are missing: {sorted(missing)}")
    if set(summary["scenario_id"].astype(str)) != expected_scenarios:
        raise RuntimeError("Route A summary does not contain both implementation scenarios")

    if qa.get("status") != "pass":
        raise RuntimeError(f"Route A QA status is not pass: {qa.get('status')!r}")
    contracts = qa.get("contracts") or {}
    failed = [name for name, passed in contracts.items() if passed is not True]
    if failed:
        raise RuntimeError(f"Route A QA contracts failed: {sorted(failed)}")


def run_implementation_phase(
    df: pd.DataFrame,
    *,
    context: Optional[RunContext],
    outputs_dir: Path,
    config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Run Route A, validate all contracts, promote outputs and register artifacts."""
    cohort_size = (
        int(context.authoritative_cohort)
        if context is not None and context.authoritative_cohort is not None
        else int(len(df))
    )
    if len(df) != cohort_size:
        raise RuntimeError(
            f"Route A source cohort rows={len(df)}, expected={cohort_size}"
        )

    outputs_dir = Path(outputs_dir)
    candidate = outputs_dir / ".implementation-candidate"
    _cleanup_candidate(candidate)
    candidate.mkdir(parents=True, exist_ok=True)

    try:
        logger.info("Running Route A implementation pathways for {:,} properties", cohort_size)
        modeler = ImplementationPathwayModeler(config=config, output_dir=candidate)
        properties, raw_summary = modeler.run(df)
        summary = enrich_implementation_summary(properties, raw_summary)
        summary.to_csv(output_paths(candidate)["summary"], index=False)
        qa = build_implementation_qa(
            properties,
            summary,
            cohort_size,
            policy=modeler.settings,
        )
        output_paths(candidate)["qa"].write_text(
            json.dumps(qa, indent=2, default=str),
            encoding="utf-8",
        )
        validate_outputs(properties, summary, qa, cohort_size=cohort_size)

        promoted = _promote(output_paths(candidate), outputs_dir)
        _cleanup_candidate(candidate)

        if context is not None:
            manifest = ArtifactManifest.load(context)
            for key, path in promoted.items():
                record_count = len(properties) if key == "properties" else len(summary)
                stamp_artifact(path, context, record_count=record_count)
                manifest.register(
                    MANIFEST_NAMES[key],
                    path,
                    phase="implementation_pathways",
                    required=True,
                    publication_scope="client" if key == "summary" else "internal",
                    cohort=cohort_size,
                    validation_status="valid",
                )

        logger.info(
            "Route A implementation phase complete: {}",
            {
                row["scenario_id"]: {
                    "deployed": int(row["properties_deployed"]),
                    "deferred": int(row["properties_deferred"]),
                }
                for row in summary.to_dict("records")
            },
        )
        return {
            **promoted,
            "properties_frame": properties,
            "summary_frame": summary,
            "qa_payload": qa,
        }
    except Exception:
        _cleanup_candidate(candidate)
        raise
