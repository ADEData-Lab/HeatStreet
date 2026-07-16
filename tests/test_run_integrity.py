import json
from pathlib import Path

import pandas as pd
import pytest

from src.reporting.one_stop_report import OneStopReportGenerator
from src.reporting.patch_one_stop_output import patch_one_stop_output
from src.utils.run_integrity import RunContext, stamp_artifact


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_current_run_fixture(root: Path, context: RunContext, cohort: int = 3) -> tuple[Path, Path]:
    outputs = root / "outputs"
    processed = root / "processed"
    (outputs / "reports").mkdir(parents=True)
    processed.mkdir(parents=True)

    _write_json(outputs / "run_metadata.json", {**context.to_dict(), "authoritative_cohort_size": cohort})
    _write_json(
        processed / "validation_report.json",
        {"total_records": cohort + 2, "records_passed": cohort, "duplicates_removed": 1, "invalid_records": 1},
    )
    _write_json(processed / "methodological_adjustments_summary.json", {})
    _write_json(
        outputs / "archetype_analysis_results.json",
        {
            "epc_bands": {"frequency": {"C": 1, "D": cohort - 1}},
            "heating_systems": {"types": {"Gas boiler": cohort}},
        },
    )
    pd.DataFrame({"hp_readiness_tier": [1, 2, 3][:cohort]}).to_csv(
        outputs / "retrofit_readiness_analysis.csv", index=False
    )
    pd.DataFrame(
        [
            {
                "scenario_id": "baseline", "scenario": "Baseline", "total_properties": cohort,
                "model_family": "stock_scenario", "headline_reporting_eligible": True,
            },
            {
                "scenario_id": "hybrid",
                "scenario": "Hybrid",
                "total_properties": cohort,
                "hn_assigned_properties": 1,
                "ashp_assigned_properties": cohort - 1,
                "model_family": "stock_scenario",
                "headline_reporting_eligible": True,
            },
        ]
    ).to_csv(outputs / "scenario_results_summary.csv", index=False)
    pd.DataFrame(
        {"Tier": ["Tier 1", "Tier 2"], "Property Count": [1, cohort - 1], "Percentage": [33.3, 66.7]}
    ).to_csv(outputs / "pathway_suitability_by_tier.csv", index=False)
    pd.DataFrame({"borough": ["A", "B"], "property_count": [1, cohort - 1]}).to_csv(
        outputs / "borough_breakdown.csv", index=False
    )
    pd.DataFrame({"tenure_group": ["owner", "rented"], "property_count": [2, cohort - 2]}).to_csv(
        outputs / "reports" / "tenure_segmentation.csv", index=False
    )

    for root_dir in (outputs, processed):
        for artifact in root_dir.rglob("*"):
            if artifact.is_file() and not artifact.name.endswith(".provenance.json"):
                stamp_artifact(artifact, context)
    return outputs, processed


def _strict_generator(outputs: Path, processed: Path, context: RunContext, cohort: int = 3):
    return OneStopReportGenerator(
        output_dir=outputs,
        processed_dir=processed,
        run_id=context.run_id,
        dataset_fingerprint=context.dataset_fingerprint,
        authoritative_cohort_size=cohort,
    )


def test_current_run_cohorts_generate_provenance_stamped_output(tmp_path):
    context = RunContext("run-current", "fingerprint-current")
    outputs, processed = _write_current_run_fixture(tmp_path, context)

    report_path = _strict_generator(outputs, processed, context).generate()

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["metadata"]["run_id"] == context.run_id
    assert payload["metadata"]["dataset_fingerprint"] == context.dataset_fingerprint
    sidecar = json.loads(
        report_path.with_name(report_path.name + ".provenance.json").read_text(encoding="utf-8")
    )
    assert sidecar["record_count"] == 3


def test_stale_artifact_provenance_fails_without_one_stop_output(tmp_path):
    current = RunContext("run-current", "fingerprint-current")
    outputs, processed = _write_current_run_fixture(tmp_path, current)
    stale = RunContext("run-stale", "fingerprint-stale")
    stamp_artifact(outputs / "scenario_results_summary.csv", stale)

    with pytest.raises(RuntimeError, match="provenance mismatch"):
        _strict_generator(outputs, processed, current).generate()

    assert not (outputs / "one_stop_output.json").exists()


def test_mismatched_cohort_fails_without_one_stop_output(tmp_path):
    context = RunContext("run-current", "fingerprint-current")
    outputs, processed = _write_current_run_fixture(tmp_path, context)
    borough = pd.DataFrame({"borough": ["A"], "property_count": [2]})
    borough.to_csv(outputs / "borough_breakdown.csv", index=False)
    stamp_artifact(outputs / "borough_breakdown.csv", context)

    with pytest.raises(RuntimeError, match="borough totals=2"):
        _strict_generator(outputs, processed, context).generate()

    assert not (outputs / "one_stop_output.json").exists()


def test_validation_arithmetic_mismatch_fails_before_write(tmp_path):
    context = RunContext("run-current", "fingerprint-current")
    outputs, processed = _write_current_run_fixture(tmp_path, context)
    report_path = processed / "validation_report.json"
    _write_json(
        report_path,
        {"total_records": 6, "records_passed": 3, "duplicates_removed": 1, "invalid_records": 1},
    )
    stamp_artifact(report_path, context)

    with pytest.raises(RuntimeError, match="Validation arithmetic mismatch"):
        _strict_generator(outputs, processed, context).generate()

    assert not (outputs / "one_stop_output.json").exists()


def test_patcher_does_not_default_missing_metric_to_zero(tmp_path):
    context = RunContext("run-current", "fingerprint-current")
    one_stop_path = tmp_path / "one_stop_output.json"
    log_path = tmp_path / "analysis_log.json"
    _write_json(
        one_stop_path,
        {
            "metadata": context.to_dict(),
            "sections": {
                "section_1": {"datapoints": [{"key": "analysis_start_time", "value": None}]},
                "section_2": {"datapoints": [{"key": "duplicates_removed", "value": 7}]},
            }
        },
    )
    _write_json(
        log_path,
        {
            "metadata": {**context.to_dict(), "analysis_start": "2026-01-01T00:00:00"},
            "phases": [{"phase_name": "Data Validation", "metrics": {}}],
        },
    )
    stamp_artifact(one_stop_path, context)
    stamp_artifact(log_path, context)

    result = patch_one_stop_output(
        tmp_path,
        create_backup=False,
        run_id=context.run_id,
        dataset_fingerprint=context.dataset_fingerprint,
    )

    assert result == one_stop_path
    payload = json.loads(one_stop_path.read_text(encoding="utf-8"))
    duplicates = payload["sections"]["section_2"]["datapoints"][0]["value"]
    assert duplicates == 7


def test_patcher_rejects_stale_analysis_log_without_modifying_report(tmp_path):
    current = RunContext("run-current", "fingerprint-current")
    stale = RunContext("run-stale", "fingerprint-stale")
    one_stop_path = tmp_path / "one_stop_output.json"
    log_path = tmp_path / "analysis_log.json"
    _write_json(one_stop_path, {"metadata": current.to_dict(), "sections": {}})
    _write_json(log_path, {"metadata": stale.to_dict(), "phases": []})
    stamp_artifact(one_stop_path, current)
    stamp_artifact(log_path, stale)
    original = one_stop_path.read_bytes()

    with pytest.raises(RuntimeError, match="provenance mismatch"):
        patch_one_stop_output(
            tmp_path,
            create_backup=False,
            run_id=current.run_id,
            dataset_fingerprint=current.dataset_fingerprint,
        )

    assert one_stop_path.read_bytes() == original
