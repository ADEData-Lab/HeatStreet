import json
from pathlib import Path

import pytest

from src.utils.resume_run_outputs import _context_from_metadata


def _write_metadata(run_root: Path, payload: dict) -> None:
    outputs = run_root / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "run_metadata.json").write_text(json.dumps(payload), encoding="utf-8")


def test_context_accepts_completed_timing_without_serialized_run_status(tmp_path):
    _write_metadata(
        tmp_path,
        {
            "run_id": "run-resume",
            "dataset_fingerprint": "fingerprint",
            "mode": "development",
            "analysis_start": "2026-07-20T08:59:53+00:00",
            "analysis_end": "2026-07-20T09:07:53+00:00",
            "runtime_seconds": 480.0,
            "authoritative_cohort": 168032,
        },
    )

    context = _context_from_metadata(tmp_path)

    assert context.run_id == "run-resume"
    assert context.analysis_end == "2026-07-20T09:07:53+00:00"
    assert context.runtime_seconds == 480.0
    assert context.run_root == tmp_path.resolve()


def test_context_rejects_run_without_completed_timing(tmp_path):
    _write_metadata(
        tmp_path,
        {
            "run_id": "run-incomplete",
            "dataset_fingerprint": "fingerprint",
            "mode": "development",
            "analysis_start": "2026-07-20T08:59:53+00:00",
        },
    )

    with pytest.raises(RuntimeError, match="completed analysis timing metadata"):
        _context_from_metadata(tmp_path)


def test_context_rejects_production_run(tmp_path):
    _write_metadata(
        tmp_path,
        {
            "run_id": "run-production",
            "dataset_fingerprint": "fingerprint",
            "mode": "production",
            "analysis_start": "2026-07-20T08:59:53+00:00",
            "analysis_end": "2026-07-20T09:07:53+00:00",
            "runtime_seconds": 480.0,
        },
    )

    with pytest.raises(RuntimeError, match="cannot operate on production runs"):
        _context_from_metadata(tmp_path)
