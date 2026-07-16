import json
from pathlib import Path

import pandas as pd
import pytest

from src.utils.diagnostic_phase import (
    COMPARISON_IDS,
    PATHWAY_IDS,
    DiagnosticPathwayPhaseError,
    output_paths,
    run_diagnostic_phase,
    validate_artifacts,
)
from src.utils.run_integrity import ArtifactManifest, RunContext, provenance_path


def _context(tmp_path: Path, cohort: int = 2) -> RunContext:
    return RunContext(
        run_id="diagnostic-test-run",
        dataset_fingerprint="dataset-fingerprint",
        run_root=tmp_path,
        authoritative_cohort=cohort,
    )


def _properties(cohort: int) -> pd.DataFrame:
    return pd.DataFrame(
        [{"pathway_id": pathway_id, "property": index} for pathway_id in PATHWAY_IDS for index in range(cohort)]
    )


def _summary(cohort: int) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "pathway_id": pathway_id,
                "model_family": "full_fabric_pathway",
                "intended_reporting_use": "diagnostic_distributional_only",
                "headline_reporting_eligible": False,
                "n_properties": cohort,
            }
            for pathway_id in PATHWAY_IDS
        ]
    )


class ValidReporter:
    def __init__(self, outputs_dir):
        self.outputs_dir = Path(outputs_dir)

    def generate_comparisons(self, results_path):
        cohort = len(pd.read_parquet(results_path)) // len(PATHWAY_IDS)
        frame = pd.DataFrame(
            [{"pathway_id": pathway_id, "n_homes": cohort} for pathway_id in COMPARISON_IDS]
        )
        directory = self.outputs_dir / "comparisons"
        directory.mkdir(parents=True, exist_ok=True)
        frame.to_csv(directory / "hn_vs_hp_comparison.csv", index=False)
        (directory / "hn_vs_hp_report_snippet.md").write_text("validated", encoding="utf-8")
        return frame


def _modeler_class(*, fail_attempts=0, calls=None):
    calls = calls if calls is not None else []

    class Modeler:
        def __init__(self, output_dir):
            self.output_dir = Path(output_dir)

        # Deliberately accepts no progress_callback: no-TUI execution must omit it.
        def model_all_pathways(self, df):
            calls.append(len(df))
            if len(calls) <= fail_attempts:
                raise RuntimeError(f"model failure {len(calls)}")
            return _properties(len(df))

        def generate_pathway_summary(self, results):
            return _summary(len(results) // len(PATHWAY_IDS))

        def export_results(self, results, summary):
            self.output_dir.mkdir(parents=True, exist_ok=True)
            property_path = self.output_dir / "pathway_results_by_property.parquet"
            summary_path = self.output_dir / "pathway_results_summary.csv"
            results.to_parquet(property_path, index=False)
            summary.to_csv(summary_path, index=False)
            return property_path, summary_path

    return Modeler


def _run(tmp_path, modeler_class, *, context=None):
    context = context or _context(tmp_path)
    context.output_dir.mkdir(parents=True, exist_ok=True)
    context.processed_dir.mkdir(parents=True, exist_ok=True)
    source = pd.DataFrame({"source": [1, 2]})
    source.to_parquet(context.processed_dir / "epc_london_adjusted.parquet", index=False)
    return run_diagnostic_phase(
        source,
        context=context,
        outputs_dir=context.output_dir,
        processed_dir=context.processed_dir,
        pathway_modeler_class=modeler_class,
        comparison_reporter_class=ValidReporter,
        progress_callback=None,
    )


def test_first_failure_reloads_adjusted_parquet_then_succeeds_and_registers(tmp_path):
    calls = []
    context = _context(tmp_path)
    result = _run(tmp_path, _modeler_class(fail_attempts=1, calls=calls), context=context)

    assert result["attempt"] == 2
    assert calls == [2, 2]
    manifest = ArtifactManifest.load(context)
    manifest.require(
        ["diagnostic_pathway_properties", "diagnostic_pathways", "diagnostic_hp_hn_comparison"]
    )
    failure = json.loads((context.log_dir / "diagnostic_pathway_attempt_1_failure.json").read_text())
    assert failure["exception_type"] == "RuntimeError"
    assert failure["attempt"] == 1
    assert "model failure 1" in failure["traceback"]
    assert not list(context.output_dir.glob(".diagnostic-candidate-*"))


def test_two_failures_preserve_both_causes_and_remove_candidates(tmp_path):
    context = _context(tmp_path)
    with pytest.raises(DiagnosticPathwayPhaseError) as caught:
        _run(tmp_path, _modeler_class(fail_attempts=2), context=context)

    assert [item["message"] for item in caught.value.failures] == ["model failure 1", "model failure 2"]
    assert (context.log_dir / "diagnostic_pathway_attempt_1_failure.json").is_file()
    assert (context.log_dir / "diagnostic_pathway_attempt_2_failure.json").is_file()
    assert not list(context.output_dir.glob(".diagnostic-candidate-*"))
    assert not context.manifest_path.exists()


@pytest.mark.parametrize(
    ("column", "bad_value", "message"),
    [
        ("model_family", "stock_scenario", "model_family"),
        ("headline_reporting_eligible", True, "headline-eligible"),
        ("n_properties", 999, "active cohort"),
    ],
)
def test_summary_validation_rejects_wrong_family_headline_or_cohort(
    tmp_path, column, bad_value, message
):
    paths = output_paths(tmp_path)
    paths["comparison_csv"].parent.mkdir(parents=True)
    _properties(2).to_parquet(paths["property_results"], index=False)
    summary = _summary(2)
    summary.loc[0, column] = bad_value
    summary.to_csv(paths["summary"], index=False)
    pd.DataFrame(
        [{"pathway_id": pathway_id, "n_homes": 2} for pathway_id in COMPARISON_IDS]
    ).to_csv(paths["comparison_csv"], index=False)

    with pytest.raises(RuntimeError, match=message):
        validate_artifacts(paths, cohort_size=2, context=None)


def test_corrupt_hash_or_wrong_run_provenance_is_regenerated(tmp_path):
    context = _context(tmp_path)
    _run(tmp_path, _modeler_class(), context=context)
    paths = output_paths(context.output_dir)
    paths["summary"].write_text("corrupt", encoding="utf-8")
    sidecar = provenance_path(paths["comparison_csv"])
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    payload["run_id"] = "wrong-run"
    sidecar.write_text(json.dumps(payload), encoding="utf-8")

    calls = []
    result = _run(tmp_path, _modeler_class(calls=calls), context=context)

    assert result["rebuilt"] is True
    assert calls == [2]
    validate_artifacts(output_paths(context.output_dir), cohort_size=2, context=context)
