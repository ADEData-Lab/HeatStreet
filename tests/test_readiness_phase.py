import json
from pathlib import Path

import pandas as pd
import pytest

from src.utils.readiness_phase import (
    RetrofitReadinessPhaseError,
    output_paths,
    run_readiness_phase,
    validate_artifacts,
)
from src.utils.run_integrity import ArtifactManifest, RunContext, provenance_path, stamp_artifact_tree


def _context(tmp_path: Path, cohort: int = 2) -> RunContext:
    context = RunContext(
        run_id="readiness-test",
        dataset_fingerprint="dataset-fingerprint",
        authoritative_cohort=cohort,
        run_root=tmp_path / "run",
    )
    context.output_dir.mkdir(parents=True)
    context.processed_dir.mkdir(parents=True)
    context.log_dir.mkdir(parents=True)
    return context


class FakeAnalyzer:
    calls = 0

    def assess_heat_pump_readiness(self, frame):
        type(self).calls += 1
        if "corrupt" in frame.columns:
            raise IndexError("Out of bounds on buffer access (axis 0)")
        result = frame.copy()
        result["hp_readiness_tier"] = [1, 5][: len(result)]
        result["hp_readiness_label"] = "label"
        result["fabric_prerequisite_cost"] = 1.0
        result["system_cost_full_ashp"] = 2.0
        result["total_cost_full_ashp"] = 3.0
        result["system_cost_hybrid_ashp_sensitivity"] = 1.5
        result["total_cost_hybrid_ashp_sensitivity"] = 2.5
        return result

    def generate_readiness_summary(self, frame):
        tiers = frame["hp_readiness_tier"]
        return {
            "total_properties": len(frame),
            "tier_distribution": tiers.value_counts().to_dict(),
            "tier_percentages": (tiers.value_counts(normalize=True) * 100).to_dict(),
        }

    def save_readiness_results(self, frame, summary, output_path=None, summary_path=None):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(output_path, index=False)
        Path(summary_path).parent.mkdir(parents=True, exist_ok=True)
        Path(summary_path).write_text(
            f"Total Properties Analyzed: {len(frame):,}\n", encoding="utf-8"
        )


def test_copy_corruption_reloads_parquet_retries_and_registers(tmp_path):
    FakeAnalyzer.calls = 0
    context = _context(tmp_path)
    clean = pd.DataFrame({"property": [1, 2]})
    clean.to_parquet(context.processed_dir / "epc_london_adjusted_spatial.parquet", index=False)

    result = run_readiness_phase(
        pd.DataFrame({"property": [1, 2], "corrupt": [True, True]}),
        context=context,
        outputs_dir=context.output_dir,
        processed_dir=context.processed_dir,
        analyzer_class=FakeAnalyzer,
    )

    assert result["attempt"] == 2
    assert FakeAnalyzer.calls == 2
    manifest = ArtifactManifest.load(context)
    manifest.require(["readiness", "readiness_summary"])
    assert not list(context.output_dir.glob(".readiness-candidate-*"))
    failure = json.loads(
        (context.log_dir / "retrofit_readiness_attempt_1_failure.json").read_text(encoding="utf-8")
    )
    assert "IndexError" in failure["traceback"]


def test_two_failures_keep_both_tracebacks_and_remove_candidates(tmp_path):
    context = _context(tmp_path)
    broken = pd.DataFrame({"property": [1, 2], "corrupt": [True, True]})
    broken.to_parquet(context.processed_dir / "epc_london_adjusted_spatial.parquet", index=False)

    with pytest.raises(RetrofitReadinessPhaseError) as caught:
        run_readiness_phase(
            broken,
            context=context,
            outputs_dir=context.output_dir,
            processed_dir=context.processed_dir,
            analyzer_class=FakeAnalyzer,
        )

    assert len(caught.value.failures) == 2
    assert all(item["traceback"] for item in caught.value.failures)
    assert not list(context.output_dir.glob(".readiness-candidate-*"))


@pytest.mark.parametrize("mutation, match", [
    ("missing", "missing"),
    ("cohort", "cohort mismatch"),
    ("columns", "columns are missing"),
    ("tiers", "invalid tiers"),
    ("hash", "hash mismatch"),
    ("run", "provenance mismatch"),
    ("fingerprint", "provenance mismatch"),
])
def test_readiness_validation_rejects_contract_failures(tmp_path, mutation, match):
    context = _context(tmp_path)
    paths = output_paths(context.output_dir)
    analyzer = FakeAnalyzer()
    frame = analyzer.assess_heat_pump_readiness(pd.DataFrame({"property": [1, 2]}))
    analyzer.save_readiness_results(
        frame, analyzer.generate_readiness_summary(frame),
        output_path=paths["readiness"], summary_path=paths["summary"],
    )
    stamp_artifact_tree([context.output_dir], context)

    if mutation == "missing":
        paths["summary"].unlink()
    elif mutation == "cohort":
        pd.concat([frame, frame.iloc[:1]]).to_csv(paths["readiness"], index=False)
        stamp_artifact_tree([context.output_dir], context)
    elif mutation == "columns":
        frame.drop(columns=["total_cost_full_ashp"]).to_csv(paths["readiness"], index=False)
        stamp_artifact_tree([context.output_dir], context)
    elif mutation == "tiers":
        frame.assign(hp_readiness_tier=9).to_csv(paths["readiness"], index=False)
        stamp_artifact_tree([context.output_dir], context)
    elif mutation == "hash":
        paths["readiness"].write_text(paths["readiness"].read_text() + "\n", encoding="utf-8")
    else:
        sidecar = provenance_path(paths["readiness"])
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        payload["run_id" if mutation == "run" else "dataset_fingerprint"] = "wrong"
        sidecar.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match=match):
        validate_artifacts(paths, cohort_size=2, context=context)
