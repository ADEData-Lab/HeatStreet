"""Resume validated client packaging for a failed development run.

This utility never publishes and never edits analytical values. It invokes the
same report generators and manifest gates as the main pipeline.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from config.config import get_scenario_policy
from src.analysis.additional_reports import AdditionalReports
from src.analysis.retrofit_readiness import RetrofitReadinessAnalyzer
from src.utils.analysis_logger import AnalysisLogger
from src.utils.run_integrity import RunContext, stamp_artifact, stamp_artifact_tree


def _context_from_metadata(run_root: Path) -> RunContext:
    payload = json.loads((run_root / "outputs" / "run_metadata.json").read_text(encoding="utf-8"))
    manifest_path = run_root / "manifest.json"
    if manifest_path.is_file():
        manifest_context = json.loads(manifest_path.read_text(encoding="utf-8")).get("context", {})
        for key, value in manifest_context.items():
            if payload.get(key) is None:
                payload[key] = value
    fields = RunContext.__dataclass_fields__
    values = {key: value for key, value in payload.items() if key in fields}
    values["run_root"] = run_root.resolve()
    context = RunContext(**values)
    if context.mode == "production":
        raise RuntimeError("Development resume utility cannot operate on production runs")
    if not context.finalized:
        raise RuntimeError("Cannot resume an unfinalized run")
    return context


def resume_development_outputs(run_root: Path) -> Path:
    run_root = Path(run_root).resolve()
    context = _context_from_metadata(run_root)
    outputs = context.output_dir
    processed = context.processed_dir
    adjusted = pd.read_parquet(processed / "epc_london_adjusted.parquet")

    # Importing here avoids initializing the interactive pipeline for library use.
    import run_analysis as pipeline

    pipeline.DATA_OUTPUTS_DIR = outputs
    pipeline.DATA_PROCESSED_DIR = processed
    pipeline._active_run_context = context
    pipeline._active_authoritative_cohort_size = int(context.authoritative_cohort)
    pipeline._hp_hn_comparison_outputs_cache = None

    logger = AnalysisLogger(output_dir=outputs)
    for key, value in context.to_dict().items():
        logger.set_metadata(key, value)
    logger.set_metadata("authoritative_cohort_size", context.authoritative_cohort)
    logger.start_phase("Validated Development Resume", "Regenerate client packaging through active manifest gates")

    comparison = pipeline.ensure_hp_hn_comparison_outputs(adjusted, logger, ui=None)
    if comparison is None:
        raise RuntimeError("Diagnostic pathway outputs could not be regenerated")

    reporter = AdditionalReports()
    tenure_path = outputs / "reports" / "tenure_segmentation.csv"
    tenure_summary_path = outputs / "reports" / "tenure_segmentation.txt"
    tenure = reporter.generate_tenure_segmentation(
        adjusted,
        output_path=tenure_path,
        summary_path=tenure_summary_path,
        source_label=str(processed / "epc_london_adjusted.parquet"),
    )
    stamp_artifact(tenure_path, context, record_count=len(adjusted))
    stamp_artifact(tenure_summary_path, context)

    pipeline.generate_one_stop_report(adjusted, logger, ui=None)

    archetype = json.loads((outputs / "archetype_analysis_results.json").read_text(encoding="utf-8"))
    internal_rows = pd.read_csv(outputs / "internal_scenario_results.csv").to_dict("records")
    publish = set(get_scenario_policy()["publish"])
    scenarios = {
        str(row["scenario_id"]): row for row in internal_rows
        if str(row.get("scenario_id")) in publish
    }
    readiness_frame = pd.read_csv(outputs / "retrofit_readiness_analysis.csv")
    readiness = RetrofitReadinessAnalyzer().generate_readiness_summary(readiness_frame)
    pathway = pd.read_csv(outputs / "pathway_suitability_by_tier.csv")
    additional = {
        "borough_breakdown": pd.read_csv(outputs / "borough_breakdown.csv"),
        "borough_priority_ranking": pd.read_csv(outputs / "reports" / "borough_priority_ranking.csv"),
        "tenure_segmentation": tenure,
        "heat_network_thresholds": pd.read_csv(outputs / "heat_network_connection_thresholds.csv"),
    }
    pipeline.package_dashboard_assets(
        archetype,
        scenarios,
        readiness,
        pathway_summary=pathway,
        additional_reports=additional,
        subsidy_results={},
        df_validated=adjusted,
        analysis_logger=logger,
        ui=None,
    )

    logger.add_output(str(outputs / "one_stop_output.json"), "json", "One-stop report")
    logger.add_output(str(outputs / "dashboard" / "dashboard-data.json"), "json", "Dashboard data")
    logger.complete_phase(success=True, message="Development client packaging regenerated")
    logger.save_log()

    from src.reporting.one_stop_html_dashboard import build_one_stop_html_dashboard
    build_one_stop_html_dashboard(outputs)
    stamp_artifact_tree([outputs, processed], context)
    manifest = pipeline._register_current_artifacts(context)
    pipeline._require_contract(
        manifest,
        [
            "published_validation_report", "one_stop_json", "dashboard_data",
            "dashboard_html", "analysis_compendium",
        ],
    )
    return context.manifest_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_root", type=Path)
    args = parser.parse_args()
    print(resume_development_outputs(args.run_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
