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
    if context.analysis_end is None or context.runtime_seconds is None:
        raise RuntimeError("Cannot resume a run without completed analysis timing metadata")
    return context


def _generate_additional_reports(
    reporter: AdditionalReports,
    report_df: pd.DataFrame,
    outputs: Path,
    processed: Path,
    context: RunContext,
) -> dict[str, pd.DataFrame]:
    reports_dir = outputs / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    tenure_path = reports_dir / "tenure_segmentation.csv"
    tenure_summary_path = reports_dir / "tenure_segmentation.txt"
    tenure = reporter.generate_tenure_segmentation(
        report_df,
        output_path=tenure_path,
        summary_path=tenure_summary_path,
        source_label=str(processed / "epc_london_adjusted_spatial.parquet"),
    )

    borough_path = outputs / "borough_breakdown.csv"
    borough = reporter.generate_borough_breakdown(report_df, output_path=borough_path)

    borough_priority_path = reports_dir / "borough_priority_ranking.csv"
    borough_priority_summary_path = reports_dir / "borough_priority_ranking.txt"
    borough_priority = reporter.generate_borough_priority_ranking(
        report_df,
        output_path=borough_priority_path,
        summary_path=borough_priority_summary_path,
        source_label=str(processed / "epc_london_adjusted_spatial.parquet"),
    )

    case_street_path = outputs / "shakespeare_crescent_extract.csv"
    case_street_summary_path = outputs / "shakespeare_crescent_summary.txt"
    reporter.extract_case_street(
        report_df,
        street_name="Shakespeare Crescent",
        output_path=case_street_path,
        summary_path=case_street_summary_path,
    )

    network_thresholds_path = outputs / "heat_network_connection_thresholds.csv"
    network_thresholds = reporter.analyze_heat_network_connection_thresholds(
        report_df,
        output_path=network_thresholds_path,
    )

    for path, record_count in (
        (tenure_path, len(tenure)),
        (tenure_summary_path, None),
        (borough_path, len(borough)),
        (borough_priority_path, len(borough_priority)),
        (borough_priority_summary_path, None),
        (case_street_path, None),
        (case_street_summary_path, None),
        (network_thresholds_path, len(network_thresholds)),
    ):
        stamp_artifact(path, context, record_count=record_count)

    return {
        "borough_breakdown": borough,
        "borough_priority_ranking": borough_priority,
        "tenure_segmentation": tenure,
        "heat_network_thresholds": network_thresholds,
    }


def resume_development_outputs(run_root: Path) -> Path:
    run_root = Path(run_root).resolve()
    context = _context_from_metadata(run_root)
    outputs = context.output_dir
    processed = context.processed_dir
    adjusted = pd.read_parquet(processed / "epc_london_adjusted.parquet")
    spatial_path = processed / "epc_london_adjusted_spatial.parquet"
    if not spatial_path.is_file():
        raise RuntimeError("Cannot resume client outputs without the spatially enriched dataset")
    report_df = pd.read_parquet(spatial_path)

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
    additional = _generate_additional_reports(
        reporter,
        report_df,
        outputs,
        processed,
        context,
    )

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
