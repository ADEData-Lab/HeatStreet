from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent))

from src.analysis.fabric_tipping_point import FabricTippingPointAnalyzer


def test_fabric_measure_sequence_excludes_duplicate_glazing(tmp_path):
    analyzer = FabricTippingPointAnalyzer(output_dir=tmp_path)

    sequence = analyzer.generate_fabric_measure_sequence(15000)

    assert "double_glazing_upgrade" in sequence
    assert "triple_glazing_upgrade" not in sequence


def test_fabric_measure_sequence_has_unique_exclusive_groups(tmp_path):
    analyzer = FabricTippingPointAnalyzer(output_dir=tmp_path)

    sequence = analyzer.generate_fabric_measure_sequence(15000)
    groups = [
        analyzer.catalogue[measure_id].mutually_exclusive_group
        for measure_id in sequence
        if analyzer.catalogue[measure_id].mutually_exclusive_group
    ]

    assert len(groups) == len(set(groups))


def test_tipping_point_curve_cumulative_capex_matches_measure_rows(tmp_path):
    analyzer = FabricTippingPointAnalyzer(output_dir=tmp_path)

    curve_df = analyzer.calculate_tipping_point_curve(15000)
    measure_rows = curve_df[curve_df["measure_id"] != "baseline"]

    assert curve_df.iloc[-1]["cumulative_capex"] == measure_rows["measure_capex"].sum()


def test_default_tipping_point_curve_selects_double_glazing_only(tmp_path):
    analyzer = FabricTippingPointAnalyzer(output_dir=tmp_path)

    curve_df = analyzer.calculate_tipping_point_curve(15000)
    glazing_rows = curve_df[
        curve_df["measure_id"].isin(
            ["double_glazing_upgrade", "triple_glazing_upgrade"]
        )
    ]

    assert glazing_rows["measure_id"].tolist() == ["double_glazing_upgrade"]
