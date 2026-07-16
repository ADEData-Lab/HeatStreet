import json

from src.utils.analysis_logger import AnalysisLogger
from src.utils.run_integrity import ArtifactManifest, RunContext


def test_phase_completion_writes_running_checkpoint_without_workbook(tmp_path, monkeypatch):
    analysis_logger = AnalysisLogger(tmp_path)
    monkeypatch.setattr(
        analysis_logger,
        "build_combined_workbook",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("workbook must not run")),
    )
    analysis_logger.start_phase("Required phase")
    analysis_logger.complete_phase()

    payload = json.loads((tmp_path / "analysis_checkpoint.json").read_text(encoding="utf-8"))
    assert payload["run_status"] == "running"
    assert payload["phases"][-1]["phase_name"] == "Required phase"


def test_failure_checkpoint_preserves_exception_and_manifest_is_not_complete(tmp_path):
    context = RunContext(
        "failed-run", "fingerprint", run_root=tmp_path / "run", authoritative_cohort=1
    ).with_timing(runtime_seconds=1.0)
    context.output_dir.mkdir(parents=True)
    manifest = ArtifactManifest.load(context)
    manifest.save()
    analysis_logger = AnalysisLogger(context.output_dir)
    analysis_logger.start_phase("Retrofit Readiness Analysis")

    try:
        raise IndexError("buffer corruption")
    except IndexError as exc:
        failed = context.fail()
        ArtifactManifest.load(failed).save()
        analysis_logger.record_failure(exc)

    checkpoint = json.loads(
        (context.output_dir / "analysis_checkpoint.json").read_text(encoding="utf-8")
    )
    manifest_payload = json.loads(context.manifest_path.read_text(encoding="utf-8"))
    assert checkpoint["run_status"] == "failed"
    assert checkpoint["failed_phase"] == "Retrofit Readiness Analysis"
    assert checkpoint["exception_type"] == "IndexError"
    assert "buffer corruption" in checkpoint["traceback"]
    assert manifest_payload["run_status"] == "failed"
    assert not failed.finalized
