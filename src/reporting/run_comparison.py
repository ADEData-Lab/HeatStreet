"""Create a reproducible reference-output versus run-manifest comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.utils.run_integrity import ArtifactManifest, RunContext, stamp_artifact


def _context(run_root: Path) -> RunContext:
    payload = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))["context"]
    payload["run_root"] = run_root.resolve()
    fields = RunContext.__dataclass_fields__
    return RunContext(**{key: value for key, value in payload.items() if key in fields})


def _add(rows, domain, item, metric, old, new):
    old_value = float(old) if pd.notna(old) else None
    new_value = float(new) if pd.notna(new) else None
    rows.append(
        {
            "domain": domain,
            "item": str(item),
            "metric": metric,
            "reference_value": old_value,
            "corrected_value": new_value,
            "absolute_change": None if old_value is None or new_value is None else new_value - old_value,
        }
    )


def generate_comparison(reference_outputs: Path, run_root: Path) -> Path:
    reference_outputs = reference_outputs.resolve()
    run_root = run_root.resolve()
    context = _context(run_root)
    outputs = context.output_dir
    rows: list[dict] = []

    old_archetype = json.loads((reference_outputs / "archetype_analysis_results.json").read_text(encoding="utf-8"))
    new_archetype = json.loads((outputs / "archetype_analysis_results.json").read_text(encoding="utf-8"))
    old_floor = old_archetype["floor_insulation"]
    new_floor = new_archetype["floor_insulation"]
    old_total = int(old_floor.get("insulated", 0)) + int(old_floor.get("uninsulated", 0)) + int(old_floor.get("unknown", 0))
    _add(rows, "cohort", "authoritative", "properties", old_total, context.authoritative_cohort)
    for metric in ("insulated", "uninsulated", "unknown"):
        _add(rows, "floor_insulation", metric, "properties", old_floor.get(metric, 0), new_floor.get(metric, 0))
    _add(rows, "floor_insulation", "insulated", "percent", old_floor.get("insulation_rate"), new_floor.get("insulated_pct"))

    old_scenarios = pd.read_csv(reference_outputs / "scenario_results_summary.csv").set_index("scenario_id")
    new_scenarios = pd.read_csv(outputs / "scenario_results_summary.csv").set_index("scenario_id")
    for scenario_id in new_scenarios.index:
        if scenario_id not in old_scenarios.index:
            continue
        for metric in ("total_properties", "capital_cost_total", "annual_bill_savings", "annual_co2_reduction_kg"):
            _add(rows, "published_scenario", scenario_id, metric, old_scenarios.at[scenario_id, metric], new_scenarios.at[scenario_id, metric])

    old_readiness = pd.read_csv(reference_outputs / "retrofit_readiness_analysis.csv", usecols=["hp_readiness_tier"])
    new_readiness = pd.read_csv(outputs / "retrofit_readiness_analysis.csv", usecols=["hp_readiness_tier"])
    old_tiers = old_readiness["hp_readiness_tier"].value_counts()
    new_tiers = new_readiness["hp_readiness_tier"].value_counts()
    for tier in sorted(set(old_tiers.index) | set(new_tiers.index)):
        _add(rows, "readiness", tier, "properties", old_tiers.get(tier, 0), new_tiers.get(tier, 0))

    old_spatial = pd.read_csv(reference_outputs / "pathway_suitability_by_tier.csv").set_index("Tier")
    new_spatial = pd.read_csv(outputs / "pathway_suitability_by_tier.csv").set_index("Tier")
    for tier in new_spatial.index:
        _add(rows, "spatial", tier, "properties", old_spatial["Property Count"].get(tier, 0), new_spatial.at[tier, "Property Count"])

    result = pd.DataFrame(rows)
    result.insert(0, "corrected_run_id", context.run_id)
    result.insert(1, "dataset_fingerprint", context.dataset_fingerprint)
    result.insert(2, "reference_outputs", str(reference_outputs))
    output_path = outputs / "old_vs_corrected_comparison.csv"
    result.to_csv(output_path, index=False)
    stamp_artifact(output_path, context, record_count=len(result))
    manifest = ArtifactManifest.load(context)
    manifest.register(
        "run_comparison",
        output_path,
        phase="verification",
        required=False,
        publication_scope="internal",
        cohort=context.authoritative_cohort,
    )
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reference_outputs", type=Path)
    parser.add_argument("run_root", type=Path)
    args = parser.parse_args()
    print(generate_comparison(args.reference_outputs, args.run_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
