import json
from pathlib import Path

import pandas as pd

from src.utils.analysis_logger import AnalysisLogger


def test_load_tabular_preview_handles_mismatched_dashboard_json(tmp_path):
    dashboard_payload = {
        "labels": ["A", "B", "C"],
        "values": [10, 20],
        "percentages": [0.1, 0.2, 0.3, 0.4],
    }

    json_path = Path(tmp_path) / "dashboard-data.json"
    json_path.write_text(json.dumps(dashboard_payload))

    logger = AnalysisLogger(output_dir=tmp_path)

    df = logger._load_tabular_preview(json_path, max_rows=10)

    assert df is not None
    assert isinstance(df, pd.DataFrame)
    # Should normalize to the longest list length with None padding
    assert len(df) == 4
    assert list(df.columns) == ["labels", "values", "percentages"]
    assert pd.isna(df.loc[2, "values"])


