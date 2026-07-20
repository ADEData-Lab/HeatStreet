"""Re-run semantic QA for an existing completed HeatStreet run.

This utility reuses the analytical artifacts already stored under ``data/runs``.
It does not rerun acquisition, cleaning, spatial analysis, modelling, or reporting.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from src.utils.run_integrity import ArtifactManifest, RunContext, stamp_artifact
from src.utils.semantic_qa import require_passing_qa, run_semantic_qa


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = REPO_ROOT / "data" / "runs"


def _latest_run() -> Path:
    runs = [path for path in RUNS_DIR.iterdir() if path.is_dir()]
    if not runs:
        raise FileNotFoundError(f"No run directories found under {RUNS_DIR}")
    return max(runs, key=lambda path: path.stat().st_mtime)


def _load_context(run_root: Path) -> RunContext:
    manifest_path = run_root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Run manifest not found: {manifest_path}")

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    context_payload = dict(payload.get("context") or {})
    context_payload["run_root"] = run_root
    context_payload["run_status"] = "complete"
    return RunContext(**context_payload)


def rerun(run_root: Path) -> Path:
    run_root = run_root.resolve()
    context = _load_context(run_root)
    manifest = ArtifactManifest.load(context)
    manifest.context = context

    qa_path = run_root / "outputs" / "qa_checks.json"
    result = run_semantic_qa(context, manifest, qa_path)
    stamp_artifact(qa_path, context)
    manifest.register(
        "qa_checks",
        qa_path,
        phase="semantic_qa",
        required=True,
        publication_scope="internal",
        validation_status="valid" if result["status"] == "pass" else "invalid",
    )

    require_passing_qa(
        qa_path,
        run_id=context.run_id,
        dataset_fingerprint=context.dataset_fingerprint,
    )

    manifest.context = replace(context, run_status="complete")
    manifest.save()
    return qa_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-run semantic QA against an existing HeatStreet run."
    )
    parser.add_argument(
        "run_root",
        nargs="?",
        type=Path,
        help="Run directory. Defaults to the most recently modified directory in data/runs.",
    )
    args = parser.parse_args()

    run_root = args.run_root or _latest_run()
    qa_path = rerun(run_root)
    print(f"Semantic QA passed: {qa_path}")
    print(f"Run marked complete: {run_root / 'manifest.json'}")


if __name__ == "__main__":
    main()
