import json
from pathlib import Path

from src.utils.analysis_logger import AnalysisLogger

import run_analysis


def test_package_dashboard_assets_still_exports_when_one_stop_only(monkeypatch, tmp_path):
    class FakeBuilder:
        def __init__(self, output_dir=None):
            self.output_dir = tmp_path / "data" / "outputs" / "dashboard"

        def build_dataset(self, *args, **kwargs):
            return {
                "epcBandData": [{"band": "A", "count": 1}],
                "summaryStats": {"totalProperties": 1},
            }

        def write_dataset(self, dataset):
            output_path = self.output_dir / "dashboard-data.json"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(dataset), encoding="utf-8")
            return output_path

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_analysis, "is_one_stop_only", lambda config=None: True)

    import src.reporting.dashboard_data_builder as dashboard_data_builder

    monkeypatch.setattr(dashboard_data_builder, "DashboardDataBuilder", FakeBuilder)

    logger = AnalysisLogger(output_dir=tmp_path / "logs")

    result = run_analysis.package_dashboard_assets(
        archetype_results={},
        scenario_results={},
        readiness_summary={},
        pathway_summary=None,
        additional_reports={},
        subsidy_results={},
        df_validated=None,
        analysis_logger=logger,
    )

    outputs_dataset = tmp_path / "data" / "outputs" / "dashboard" / "dashboard-data.json"
    public_dataset = tmp_path / "dashboard" / "public" / "dashboard-data.json"

    assert result is True
    assert outputs_dataset.exists()
    assert public_dataset.exists()
    assert json.loads(outputs_dataset.read_text(encoding="utf-8")) == json.loads(
        public_dataset.read_text(encoding="utf-8")
    )
