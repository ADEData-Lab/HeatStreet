"""Tests for comparison reporting outputs."""

from pathlib import Path

import pandas as pd

from src.reporting.comparisons import ComparisonReporter


def _fake_results(pathways):
    records = []
    for pathway in pathways:
        for i in range(5):
            baseline_bill = 1200 + i * 10
            annual_bill = 800 + i * 5
            baseline_co2 = 3.0 + 0.1 * i
            annual_co2 = 1.5 + 0.05 * i
            capex = 10000 + 100 * i
            records.append(
                {
                    'pathway_id': pathway,
                    'total_capex': capex,
                    'annual_bill': annual_bill,
                    'baseline_bill': baseline_bill,
                    'annual_bill_saving': baseline_bill - annual_bill,
                    'annual_co2_tonnes': annual_co2,
                    'baseline_co2_tonnes': baseline_co2,
                    'co2_saving_tonnes': baseline_co2 - annual_co2,
                    'simple_payback_years': capex / (baseline_bill - annual_bill),
                }
            )
    return pd.DataFrame(records)


def test_comparison_outputs_created(tmp_path):
    reporter = ComparisonReporter(outputs_dir=tmp_path)
    df = _fake_results(
        ['fabric_plus_hp_only', 'fabric_plus_hn_only', 'fabric_plus_hp_plus_hn']
    )

    comparison_df = reporter.generate_comparisons(df=df)

    csv_path = tmp_path / 'comparisons' / 'hn_vs_hp_comparison.csv'
    snippet_path = tmp_path / 'comparisons' / 'hn_vs_hp_report_snippet.md'

    assert csv_path.exists(), "Comparison CSV should be written"
    assert snippet_path.exists(), "Markdown snippet should be written"
    assert not comparison_df.empty, "Comparison dataframe should not be empty"

    csv = pd.read_csv(csv_path)
    required_columns = {
        'pathway_id',
        'pathway_name',
        'n_homes',
        'capex_mean',
        'capex_median',
        'capex_p10',
        'capex_p90',
        'capex_min',
        'capex_max',
        'bill_saving_mean',
        'bill_change_mean',
        'co2_saving_mean',
        'co2_change_mean',
        'payback_mean',
        'payback_p10',
        'payback_p90',
        'payback_min',
        'payback_max',
    }

    assert required_columns.issubset(set(csv.columns)), "Missing required comparison columns"


def test_markdown_written_utf8_on_windows_1252(tmp_path, monkeypatch):
    reporter = ComparisonReporter(outputs_dir=tmp_path)
    df = _fake_results(
        ['fabric_plus_hp_only', 'fabric_plus_hn_only', 'fabric_plus_hp_plus_hn']
    )

    original_write_text = Path.write_text
    encodings_used = []

    def fake_write_text(self, text, *args, **kwargs):
        encoding = kwargs.get('encoding')
        encodings_used.append(encoding)
        if encoding is None:
            # Simulate a Windows-1252 default encoding that cannot handle CO₂
            text.encode('cp1252')
        return original_write_text(self, text, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fake_write_text)

    reporter.generate_comparisons(df=df)

    snippet_path = tmp_path / 'comparisons' / 'hn_vs_hp_report_snippet.md'
    assert snippet_path.exists(), "Markdown snippet should be written"
    assert any(enc == 'utf-8' for enc in encodings_used), "Markdown should be written with UTF-8 encoding"
