import inspect
import json
import sys
import types
from datetime import date as date_cls
import io
import urllib.error
import uuid
from pathlib import Path

import pandas as pd

import run_analysis
from src.acquisition.epc_api_downloader import EPCDownloadError, EPCRequestContext
from src.acquisition.london_gis_downloader import LondonGISDownloadError
from src.utils.staged_dataset import DatasetReference


class DummyPrompt:
    def __init__(self, value):
        self.value = value

    def ask(self):
        return self.value


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
        rendered = " ".join(rendered_parts)
        self.messages.append(rendered)


class FakeAnalysisLogger:
    def __init__(self):
        self.metadata = {}

    def set_metadata(self, key, value):
        self.metadata[key] = value


class RecordingAnalysisLogger(FakeAnalysisLogger):
    def __init__(self, output_dir: Path):
        super().__init__()
        self.output_dir = output_dir
        self.current_phase = None
        self.metrics = []
        self.outputs = []

    def start_phase(self, phase_name, description):
        self.current_phase = phase_name

    def add_metric(self, *args, **kwargs):
        self.metrics.append((args, kwargs))

    def add_output(self, *args, **kwargs):
        self.outputs.append((args, kwargs))

    def complete_phase(self, **kwargs):
        self.current_phase = None

    def save_log(self):
        log_path = self.output_dir / "analysis_log.json"
        log_path.write_text("{}", encoding="utf-8")
        return str(log_path)

    def get_summary_stats(self):
        return {
            "total_phases": 0,
            "successful_phases": 0,
            "failed_phases": 0,
            "skipped_phases": 0,
        }


def make_dataset_reference(base_dir: Path, name: str, df: pd.DataFrame, *, stage: str) -> DatasetReference:
    parquet_path = base_dir / f"{name}.parquet"
    csv_path = base_dir / f"{name}.csv"
    manifest_path = base_dir / f"{name}_manifest.json"
    df.to_parquet(parquet_path, index=False)
    df.to_csv(csv_path, index=False)
    return DatasetReference(
        name=name,
        parquet_path=parquet_path,
        csv_path=csv_path,
        manifest_path=manifest_path,
        stage=stage,
        row_count=len(df),
        sample_start_date="2024-01-01",
        sample_end_date="2024-12-31",
    )


def test_ask_gis_download_warns_optional_london_datastore_layer(monkeypatch):
    fake_console = FakeConsole()

    class FakeGISDownloader:
        def __init__(self):
            self.last_error = LondonGISDownloadError(
                "Failed to fetch London Datastore resource page https://data.london.gov.uk/dataset/london-heat-map: HTTP 404 Not Found",
                failure_kind="resource_page_fetch",
            )

        def get_data_summary(self):
            return {"available": False}

        def download_and_prepare(self):
            return False

    monkeypatch.setattr(run_analysis, "console", fake_console)
    monkeypatch.setattr(run_analysis, "LondonGISDownloader", FakeGISDownloader)

    result = run_analysis.ask_gis_download()

    assert result is False
    output = "\n".join(fake_console.messages)
    assert "Optional London Datastore GIS download failed" in output
    assert "this does not affect the EPC API download path" in output
    assert "Reason:" in output
    assert "resource page" in output


def test_download_data_surfaces_borough_scoped_api_error(monkeypatch):
    sample_start = date_cls(2024, 1, 1)
    sample_end = date_cls(2024, 12, 31)
    fake_console = FakeConsole()

    class FakeDownloader:
        LONDON_LA_CODES = {"Camden": "E09000007"}

        def __init__(self, *args, **kwargs):
            self.download_mode = kwargs.get("download_mode")

        def download_all_london_boroughs(self, **kwargs):
            context = EPCRequestContext(
                borough_name="Camden",
                property_type="house",
                sample_start_date=sample_start,
                sample_end_date=sample_end,
                request_mode="full_load",
            )
            raise EPCDownloadError.from_http_error(
                context,
                urllib.error.HTTPError(
                    url="https://example.test/api/files/domestic/csv",
                    code=400,
                    msg="Bad Request",
                    hdrs=None,
                    fp=io.BytesIO(b'{"message":"invalid request for borough"}'),
                ),
            )

    monkeypatch.setattr(run_analysis, "console", fake_console)
    monkeypatch.setattr(run_analysis, "EPCAPIDownloader", FakeDownloader)
    monkeypatch.setattr(
        run_analysis.questionary,
        "select",
        lambda *args, **kwargs: DummyPrompt("All London boroughs (full dataset)"),
    )

    result = run_analysis.download_data(
        sample_start_date=sample_start,
        sample_end_date=sample_end,
    )

    assert result is None
    output = "\n".join(fake_console.messages)
    assert "EPC download failed" in output
    assert "Camden" in output
    assert "HTTP 400" in output
    assert "request_mode='full_load'" in output


def test_download_data_uses_full_load_and_reports_separate_counts(monkeypatch):
    sample_start = date_cls(2024, 1, 1)
    sample_end = date_cls(2024, 12, 31)
    fake_console = FakeConsole()

    class FakeDownloader:
        LONDON_LA_CODES = {"Camden": "E09000007"}
        init_modes = []
        saved = []

        def __init__(self, *args, **kwargs):
            self.download_mode = kwargs.get("download_mode")
            self.__class__.init_modes.append(self.download_mode)

        def download_all_london_boroughs(self, **kwargs):
            return pd.DataFrame(
                [
                    {
                        "UPRN": "1",
                        "COUNCIL": "Camden",
                        "PROPERTY_TYPE": "House",
                        "BUILT_FORM": "Mid-Terrace",
                        "CONSTRUCTION_AGE_BAND": "England and Wales: 1900-1929",
                    },
                    {
                        "UPRN": "2",
                        "COUNCIL": "Camden",
                        "PROPERTY_TYPE": "House",
                        "BUILT_FORM": "Detached",
                        "CONSTRUCTION_AGE_BAND": "England and Wales: before 1900",
                    },
                    {
                        "UPRN": "3",
                        "COUNCIL": "Westminster",
                        "PROPERTY_TYPE": "House",
                        "BUILT_FORM": "End-Terrace",
                        "CONSTRUCTION_AGE_BAND": "1930-1949",
                    },
                ]
            )

        def download_borough_data(self, *args, **kwargs):
            raise AssertionError("Full-London runs should not call borough search mode")

        def apply_edwardian_filters(self, df):
            return df.iloc[[0]].copy()

        def save_data(self, df, filename, raw_df=None):
            self.__class__.saved.append(
                (filename, len(df), None if raw_df is None else len(raw_df))
            )

    monkeypatch.setattr(run_analysis, "console", fake_console)
    monkeypatch.setattr(run_analysis, "EPCAPIDownloader", FakeDownloader)
    monkeypatch.setattr(run_analysis, "write_sample_window_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        run_analysis.questionary,
        "select",
        lambda *args, **kwargs: DummyPrompt("All London boroughs (full dataset)"),
    )

    result = run_analysis.download_data(
        sample_start_date=sample_start,
        sample_end_date=sample_end,
    )

    assert len(result) == 1
    assert FakeDownloader.init_modes == ["full_load"]
    assert ("epc_london_raw.csv", 3, None) in FakeDownloader.saved
    assert ("epc_london_filtered.csv", 1, 3) in FakeDownloader.saved

    output = "\n".join(fake_console.messages)
    assert "Using EPC full-load CSV extract for London stock definition" in output
    assert "Raw London house records: 3" in output
    assert "Filtered London pre-1930 terraced house records: 1" in output


def test_download_data_single_borough_uses_full_load_stock_source(monkeypatch):
    sample_start = date_cls(2024, 1, 1)
    sample_end = date_cls(2024, 12, 31)
    fake_console = FakeConsole()

    class FakeDownloader:
        LONDON_LA_CODES = {"Camden": "E09000007"}
        init_modes = []
        saved = []

        def __init__(self, *args, **kwargs):
            self.download_mode = kwargs.get("download_mode")
            self.__class__.init_modes.append(self.download_mode)

        def download_borough_data(self, borough_name, **kwargs):
            assert self.download_mode == "full_load"
            assert borough_name == "Camden"
            return pd.DataFrame(
                [
                    {
                        "UPRN": "1",
                        "COUNCIL": "Camden",
                        "PROPERTY_TYPE": "House",
                        "BUILT_FORM": "Mid-Terrace",
                        "CONSTRUCTION_AGE_BAND": "England and Wales: 1900-1929",
                    },
                    {
                        "UPRN": "2",
                        "COUNCIL": "Camden",
                        "PROPERTY_TYPE": "House",
                        "BUILT_FORM": "Detached",
                        "CONSTRUCTION_AGE_BAND": "England and Wales: before 1900",
                    },
                ]
            )

        def apply_edwardian_filters(self, df):
            return df.iloc[[0]].copy()

        def save_data(self, df, filename, raw_df=None):
            self.__class__.saved.append(
                (filename, len(df), None if raw_df is None else len(raw_df))
            )

    monkeypatch.setattr(run_analysis, "console", fake_console)
    monkeypatch.setattr(run_analysis, "EPCAPIDownloader", FakeDownloader)
    monkeypatch.setattr(run_analysis, "write_sample_window_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        run_analysis.questionary,
        "select",
        lambda *args, **kwargs: DummyPrompt("Single borough (testing)"),
    )
    monkeypatch.setattr(
        run_analysis.questionary,
        "autocomplete",
        lambda *args, **kwargs: DummyPrompt("Camden"),
    )

    result = run_analysis.download_data(
        sample_start_date=sample_start,
        sample_end_date=sample_end,
    )

    assert len(result) == 1
    assert FakeDownloader.init_modes == ["full_load"]
    assert ("epc_camden_raw.csv", 2, None) in FakeDownloader.saved
    assert ("epc_camden_filtered.csv", 1, 2) in FakeDownloader.saved

    output = "\n".join(fake_console.messages)
    assert "Using EPC full-load CSV extract as the stock-definition source for Camden" in output
    assert "Raw Camden house records: 2" in output
    assert "Filtered Camden pre-1930 terraced house records: 1" in output


def test_check_existing_data_ignores_filtered_file_missing_stock_columns(monkeypatch):
    fake_console = FakeConsole()
    data_dir = Path(".tmp_existing_stock_check")
    data_dir.mkdir(exist_ok=True)
    filtered_path = data_dir / "epc_london_filtered.csv"
    filtered_path.write_text("COUNCIL\nCamden\n", encoding="utf-8")
    (data_dir / "epc_london_raw.csv").unlink(missing_ok=True)

    monkeypatch.setattr(run_analysis, "console", fake_console)
    monkeypatch.setattr(run_analysis, "DATA_RAW_DIR", data_dir)

    has_existing, existing_file, record_count = run_analysis.check_existing_data()

    assert (has_existing, existing_file, record_count) == (False, None, 0)
    assert "Existing Filtered Data Ignored" in "\n".join(fake_console.messages)


def test_main_returns_non_zero_when_phase_one_has_no_data(monkeypatch):
    fake_console = FakeConsole()

    monkeypatch.setattr(run_analysis, "console", fake_console)
    monkeypatch.setattr(run_analysis, "print_header", lambda: None)
    monkeypatch.setattr(run_analysis, "check_credentials", lambda: True)
    monkeypatch.setattr(run_analysis, "ensure_directories", lambda: None)
    monkeypatch.setattr(
        run_analysis,
        "emit_startup_diagnostics",
        lambda analysis_logger=None: ({}, {"ok": True}),
    )
    monkeypatch.setattr(run_analysis, "load_config", lambda: {})
    monkeypatch.setattr(run_analysis, "is_one_stop_only", lambda config=None: False)
    monkeypatch.setattr(run_analysis, "AnalysisLogger", FakeAnalysisLogger)
    monkeypatch.setattr(run_analysis, "ask_hnpd_download", lambda: False)
    monkeypatch.setattr(run_analysis, "ask_gis_download", lambda: False)
    monkeypatch.setattr(
        run_analysis,
        "prompt_sample_window",
        lambda: (date_cls(2024, 1, 1), date_cls(2024, 12, 31)),
    )
    monkeypatch.setattr(
        run_analysis,
        "check_existing_data",
        lambda **kwargs: (False, None, 0),
    )
    monkeypatch.setattr(run_analysis, "download_data", lambda *args, **kwargs: None)

    exit_code = run_analysis.main()

    assert exit_code == run_analysis.EXIT_ANALYSIS_FAILED
    assert any("no data available" in message.lower() for message in fake_console.messages)


def test_ensure_hp_hn_comparison_outputs_caches_failed_rebuild(monkeypatch):
    fake_console = FakeConsole()
    temp_root = Path("temp_verify_dir")
    temp_root.mkdir(exist_ok=True)
    test_root = temp_root / f"ensure_hp_hn_{uuid.uuid4().hex}"
    test_root.mkdir(parents=True, exist_ok=True)
    outputs_dir = test_root / "data" / "outputs"
    call_counts = {
        "pathway_modeler_inits": 0,
        "model_all_pathways": 0,
    }

    class FakeLogger:
        def __init__(self):
            self.exception_calls = 0

        def exception(self, message):
            self.exception_calls += 1

    fake_logger = FakeLogger()

    class FakePathwayModeler:
        def __init__(self, output_dir=None):
            call_counts["pathway_modeler_inits"] += 1
            self.output_dir = output_dir or outputs_dir
            self.output_dir.mkdir(parents=True, exist_ok=True)

        def model_all_pathways(self, df):
            call_counts["model_all_pathways"] += 1
            raise RuntimeError("baseline pathway rebuild failed")

        def generate_pathway_summary(self, pathway_results):
            raise AssertionError("generate_pathway_summary should not be called after a rebuild failure")

        def export_results(self, pathway_results, pathway_summary):
            raise AssertionError("export_results should not be called after a rebuild failure")

    monkeypatch.setattr(run_analysis, "console", fake_console)
    monkeypatch.setattr(run_analysis, "logger", fake_logger)
    monkeypatch.setattr(run_analysis, "DATA_OUTPUTS_DIR", outputs_dir)
    monkeypatch.setattr(run_analysis, "PathwayModeler", FakePathwayModeler)
    monkeypatch.setattr(run_analysis, "_hp_hn_comparison_outputs_cache", None)

    df = pd.DataFrame({"value": [1]})

    first = run_analysis.ensure_hp_hn_comparison_outputs(df=df)
    second = run_analysis.ensure_hp_hn_comparison_outputs(df=df)
    third = run_analysis.ensure_hp_hn_comparison_outputs(df=df)

    assert first is None
    assert second is None
    assert third is None
    assert call_counts["pathway_modeler_inits"] == 1
    assert call_counts["model_all_pathways"] == 1
    assert fake_logger.exception_calls == 1

    output = "\n".join(fake_console.messages).lower()
    assert output.count("attempting to rebuild hp vs hn comparison outputs") == 1
    assert output.count("could not be regenerated from pathway modeling") == 1


def test_validate_data_writes_normalized_report_for_dataset_reference(monkeypatch, tmp_path):
    fake_console = FakeConsole()
    raw_ref = make_dataset_reference(
        tmp_path,
        "raw_input",
        pd.DataFrame({"value": [1, 2, 3, 4, 5]}),
        stage="raw",
    )
    validated_df = pd.DataFrame({"value": [1, 2, 3]})
    validated_ref = make_dataset_reference(
        tmp_path,
        "validated_output",
        validated_df,
        stage="validated",
    )

    class FakeValidator:
        def __init__(self):
            self.validation_report = {}

        def save_validation_report(self):
            return None

    def fake_validate_staged_dataset(input_dataset, output_file):
        assert input_dataset is raw_ref
        validated_df.to_csv(output_file, index=False)
        validated_df.to_parquet(output_file.with_suffix(".parquet"), index=False)
        return validated_ref, {"total_records": 5, "duplicates_removed": 1}

    monkeypatch.setattr(run_analysis, "console", fake_console)
    monkeypatch.setattr(run_analysis, "DATA_PROCESSED_DIR", tmp_path)
    monkeypatch.setattr(run_analysis, "EPCDataValidator", FakeValidator)
    monkeypatch.setattr(run_analysis, "validate_staged_dataset", fake_validate_staged_dataset)

    validated_dataset, report = run_analysis.validate_data(raw_ref)

    assert validated_dataset is validated_ref
    assert report["records_passed"] == 3
    assert report["valid_records"] == 3
    assert report["invalid_records"] == 1

    payload = json.loads((tmp_path / "validation_report.json").read_text(encoding="utf-8"))
    assert payload["total_records"] == 5
    assert payload["records_passed"] == 3
    assert payload["invalid_records"] == 1


def test_apply_methodological_adjustments_uses_staged_helper_for_dataset_reference(monkeypatch, tmp_path):
    fake_console = FakeConsole()
    validated_ref = make_dataset_reference(
        tmp_path,
        "validated_input",
        pd.DataFrame({"value": [10, 20]}),
        stage="validated",
    )
    summary = {
        "prebound_adjustment": {"applied": True},
        "flow_temperature": {"applied": True},
        "uncertainty": {"applied": True},
    }

    def fake_apply_adjustments(input_dataset, output_file):
        assert input_dataset is validated_ref
        adjusted_df = pd.DataFrame({"value": [11, 21]})
        adjusted_df.to_csv(output_file, index=False)
        adjusted_df.to_parquet(output_file.with_suffix(".parquet"), index=False)
        adjusted_ref = DatasetReference(
            name="adjusted_epc_dataset",
            parquet_path=output_file.with_suffix(".parquet"),
            csv_path=output_file,
            manifest_path=output_file.with_name("epc_london_adjusted_manifest.json"),
            stage="adjusted",
            row_count=len(adjusted_df),
            sample_start_date="2024-01-01",
            sample_end_date="2024-12-31",
        )
        return adjusted_ref, summary

    monkeypatch.setattr(run_analysis, "console", fake_console)
    monkeypatch.setattr(run_analysis, "DATA_PROCESSED_DIR", tmp_path)
    monkeypatch.setattr(run_analysis, "apply_adjustments_staged_dataset", fake_apply_adjustments)

    adjusted_dataset, returned_summary = run_analysis.apply_methodological_adjustments(validated_ref)

    assert isinstance(adjusted_dataset, DatasetReference)
    assert adjusted_dataset.csv_path.exists()
    assert adjusted_dataset.parquet_path.exists()
    assert returned_summary == summary
    assert json.loads((tmp_path / "methodological_adjustments_summary.json").read_text(encoding="utf-8")) == summary


def test_main_completes_staged_pipeline_without_dataframe_assumptions(monkeypatch, tmp_path):
    fake_console = FakeConsole()
    raw_ref = make_dataset_reference(
        tmp_path,
        "raw_stage",
        pd.DataFrame({"value": [1, 2]}),
        stage="raw",
    )
    validated_ref = make_dataset_reference(
        tmp_path,
        "validated_stage",
        pd.DataFrame({"value": [1]}),
        stage="validated",
    )
    adjusted_ref = make_dataset_reference(
        tmp_path,
        "adjusted_stage",
        pd.DataFrame({"value": [1]}),
        stage="adjusted",
    )

    validate_calls = []
    adjustment_calls = []

    monkeypatch.setattr(run_analysis, "console", fake_console)
    monkeypatch.setattr(run_analysis, "print_header", lambda: None)
    monkeypatch.setattr(run_analysis, "check_credentials", lambda: True)
    monkeypatch.setattr(run_analysis, "ensure_directories", lambda: None)
    monkeypatch.setattr(
        run_analysis,
        "emit_startup_diagnostics",
        lambda analysis_logger=None: ({}, {"ok": True}),
    )
    monkeypatch.setattr(run_analysis, "load_config", lambda: {})
    monkeypatch.setattr(run_analysis, "is_one_stop_only", lambda config=None: False)
    monkeypatch.setattr(run_analysis, "AnalysisLogger", lambda: RecordingAnalysisLogger(tmp_path))
    monkeypatch.setattr(run_analysis, "ask_hnpd_download", lambda: False)
    monkeypatch.setattr(run_analysis, "ask_gis_download", lambda: False)
    monkeypatch.setattr(
        run_analysis,
        "prompt_sample_window",
        lambda: (date_cls(2024, 1, 1), date_cls(2024, 12, 31)),
    )
    monkeypatch.setattr(
        run_analysis,
        "check_existing_data",
        lambda **kwargs: (False, None, 0),
    )
    monkeypatch.setattr(run_analysis, "download_data", lambda *args, **kwargs: raw_ref)

    def fake_validate_data(dataset, *args, **kwargs):
        validate_calls.append(dataset)
        assert dataset is raw_ref
        return validated_ref, {"total_records": 2, "records_passed": 1, "invalid_records": 1}

    def fake_apply_methodological_adjustments(dataset, *args, **kwargs):
        adjustment_calls.append(dataset)
        assert dataset is validated_ref
        return adjusted_ref, {"prebound_adjustment": {"applied": True}}

    monkeypatch.setattr(run_analysis, "validate_data", fake_validate_data)
    monkeypatch.setattr(run_analysis, "apply_methodological_adjustments", fake_apply_methodological_adjustments)
    monkeypatch.setattr(run_analysis, "analyze_archetype", lambda df, analysis_logger=None: {"rows": len(df)})
    monkeypatch.setattr(run_analysis, "model_scenarios", lambda df, analysis_logger=None: ({"heat_pump": {}}, {}))
    monkeypatch.setattr(
        run_analysis,
        "analyze_retrofit_readiness",
        lambda df, analysis_logger=None, one_stop_only=False: (df.copy(), {"status": "ok"}),
    )
    monkeypatch.setattr(
        run_analysis,
        "run_spatial_analysis",
        lambda df, analysis_logger=None, one_stop_only=False: (df.copy(), {"status": "ok"}),
    )
    monkeypatch.setattr(run_analysis, "generate_additional_reports", lambda *args, **kwargs: {})
    monkeypatch.setattr(run_analysis, "generate_reports", lambda *args, **kwargs: None)
    monkeypatch.setattr(run_analysis, "generate_one_stop_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(run_analysis, "package_dashboard_assets", lambda *args, **kwargs: None)
    monkeypatch.setattr(run_analysis, "cleanup_reporting_outputs", lambda: None)
    monkeypatch.setitem(
        sys.modules,
        "src.reporting.patch_one_stop_output",
        types.SimpleNamespace(patch_one_stop_output=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.reporting.one_stop_html_dashboard",
        types.SimpleNamespace(build_one_stop_html_dashboard=lambda *_args, **_kwargs: None),
    )

    exit_code = run_analysis.main()

    assert exit_code == run_analysis.EXIT_SUCCESS
    assert validate_calls == [raw_ref]
    assert adjustment_calls == [validated_ref]


def test_main_returns_non_zero_when_staged_phase_one_dataset_is_empty(monkeypatch, tmp_path):
    fake_console = FakeConsole()
    empty_ref = make_dataset_reference(
        tmp_path,
        "empty_stage",
        pd.DataFrame({"value": []}),
        stage="raw",
    )

    monkeypatch.setattr(run_analysis, "console", fake_console)
    monkeypatch.setattr(run_analysis, "print_header", lambda: None)
    monkeypatch.setattr(run_analysis, "check_credentials", lambda: True)
    monkeypatch.setattr(run_analysis, "ensure_directories", lambda: None)
    monkeypatch.setattr(
        run_analysis,
        "emit_startup_diagnostics",
        lambda analysis_logger=None: ({}, {"ok": True}),
    )
    monkeypatch.setattr(run_analysis, "load_config", lambda: {})
    monkeypatch.setattr(run_analysis, "is_one_stop_only", lambda config=None: False)
    monkeypatch.setattr(run_analysis, "AnalysisLogger", lambda: RecordingAnalysisLogger(tmp_path))
    monkeypatch.setattr(run_analysis, "ask_hnpd_download", lambda: False)
    monkeypatch.setattr(run_analysis, "ask_gis_download", lambda: False)
    monkeypatch.setattr(
        run_analysis,
        "prompt_sample_window",
        lambda: (date_cls(2024, 1, 1), date_cls(2024, 12, 31)),
    )
    monkeypatch.setattr(
        run_analysis,
        "check_existing_data",
        lambda **kwargs: (False, None, 0),
    )
    monkeypatch.setattr(run_analysis, "download_data", lambda *args, **kwargs: empty_ref)
    monkeypatch.setattr(
        run_analysis,
        "validate_data",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("validate_data should not run for an empty staged dataset")),
    )

    exit_code = run_analysis.main()

    assert exit_code == run_analysis.EXIT_ANALYSIS_FAILED
    assert any("no data available" in message.lower() for message in fake_console.messages)


def test_run_analysis_has_single_staged_safe_mainline():
    assert not hasattr(run_analysis, "_legacy_main")

    main_source = inspect.getsource(run_analysis.main)

    assert "dataset_is_empty(df)" in main_source
    assert "ensure_dataframe(df_adjusted" in main_source
