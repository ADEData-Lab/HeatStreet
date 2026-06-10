import importlib
from pathlib import Path

import pytest

import run_analysis
from src.utils.analysis_logger import AnalysisLogger


class FakeConsole:
    def __init__(self):
        self.messages = []

    def clear(self):
        return None

    def print(self, *args, **kwargs):
        rendered_parts = []
        for arg in args:
            if hasattr(arg, "renderable"):
                rendered_parts.append(str(arg.renderable))
            else:
                rendered_parts.append(str(arg))
        self.messages.append(" ".join(rendered_parts))


def test_emit_startup_diagnostics_records_runtime_metadata(monkeypatch, tmp_path):
    fake_console = FakeConsole()
    monkeypatch.setattr(run_analysis, "console", fake_console)

    analysis_logger = AnalysisLogger(output_dir=tmp_path)
    runtime_identity = run_analysis.collect_runtime_identity()
    preflight = {
        "status": "passed",
        "ok": True,
        "checks": [
            {
                "name": "download_data() staged implementation",
                "ok": True,
                "detail": "resolved to staged implementation",
            }
        ],
        "issues": [],
        "likely_causes": [],
    }

    run_analysis.emit_startup_diagnostics(analysis_logger, runtime_identity, preflight)

    assert analysis_logger.metadata["runtime_identity"] == runtime_identity
    assert analysis_logger.metadata["startup_preflight"] == preflight
    assert analysis_logger.metadata["runtime_python_executable"] == runtime_identity["python_executable"]
    assert analysis_logger.metadata["startup_preflight_status"] == "passed"

    output = "\n".join(fake_console.messages)
    assert "Runtime Identity" in output
    assert "Startup Preflight: PASSED" in output
    assert runtime_identity["python_executable"] in output
    assert runtime_identity["run_analysis_file"] in output
    assert "download_data()" in output


def test_run_startup_preflight_confirms_staged_runtime_path():
    runtime_identity = run_analysis.collect_runtime_identity()

    preflight = run_analysis.run_startup_preflight(runtime_identity)

    assert preflight["ok"] is True
    checks = {check["name"]: check for check in preflight["checks"]}
    assert checks["download_data() staged implementation"]["ok"] is True
    assert checks["download_national_domestic_dataset() staged implementation"]["ok"] is True
    assert checks["import src.utils.staged_dataset"]["ok"] is True
    assert checks["import src.utils.staged_processing"]["ok"] is True
    assert checks["import duckdb"]["ok"] is True


def test_run_startup_preflight_reports_missing_staged_helper(monkeypatch):
    runtime_identity = run_analysis.collect_runtime_identity()
    original_import_module = importlib.import_module

    def fake_import_module(name, package=None):
        if name == "src.utils.staged_processing":
            raise ImportError("simulated staged helper import failure")
        return original_import_module(name, package)

    monkeypatch.setattr(run_analysis.importlib, "import_module", fake_import_module)

    preflight = run_analysis.run_startup_preflight(runtime_identity)

    assert preflight["ok"] is False
    assert any("src.utils.staged_processing" in issue for issue in preflight["issues"])


def test_main_stops_before_prompts_when_duckdb_missing(monkeypatch, tmp_path):
    fake_console = FakeConsole()

    class FakeAnalysisLogger:
        def __init__(self):
            self.metadata = {}

        def set_metadata(self, key, value):
            self.metadata[key] = value

        def save_log(self):
            log_path = Path(tmp_path) / "analysis_log.txt"
            log_path.write_text("startup failure", encoding="utf-8")
            return str(log_path)

    original_import_module = importlib.import_module

    def fake_import_module(name, package=None):
        if name == "duckdb":
            raise ImportError("No module named 'duckdb'")
        return original_import_module(name, package)

    monkeypatch.setattr(run_analysis, "console", fake_console)
    monkeypatch.setattr(run_analysis, "AnalysisLogger", FakeAnalysisLogger)
    monkeypatch.setattr(run_analysis, "print_header", lambda: None)
    monkeypatch.setattr(run_analysis.importlib, "import_module", fake_import_module)
    monkeypatch.setattr(
        run_analysis,
        "check_credentials",
        lambda: pytest.fail("startup preflight should fail before credential prompts"),
    )

    exit_code = run_analysis.main()

    assert exit_code == run_analysis.EXIT_ANALYSIS_FAILED
    output = "\n".join(fake_console.messages)
    assert "Python executable:" in output
    assert "duckdb is not importable" in output
    assert "Startup diagnostics log saved to:" in output
    assert (Path(tmp_path) / "analysis_log.txt").exists()
