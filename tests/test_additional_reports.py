from pathlib import Path

import pandas as pd

from src.analysis.additional_reports import AdditionalReports


def test_generate_borough_priority_ranking_creates_ranked_output(tmp_path):
    reporter = AdditionalReports()
    df = pd.DataFrame(
        [
            {
                "LMK_KEY": "A1",
                "BOROUGH": "Alpha",
                "CURRENT_ENERGY_EFFICIENCY": 55,
                "energy_kwh_per_m2_year": 260,
            },
            {
                "LMK_KEY": "A2",
                "BOROUGH": "Alpha",
                "CURRENT_ENERGY_EFFICIENCY": 57,
                "energy_kwh_per_m2_year": 250,
            },
            {
                "LMK_KEY": "B1",
                "BOROUGH": "Beta",
                "CURRENT_ENERGY_EFFICIENCY": 70,
                "energy_kwh_per_m2_year": 180,
            },
            {
                "LMK_KEY": "C1",
                "BOROUGH": "Gamma",
                "CURRENT_ENERGY_EFFICIENCY": 60,
                "energy_kwh_per_m2_year": 220,
            },
        ]
    )

    output_path = tmp_path / "borough_priority_ranking.csv"
    summary_path = tmp_path / "borough_priority_ranking.txt"
    ranking = reporter.generate_borough_priority_ranking(
        df,
        output_path=output_path,
        summary_path=summary_path,
        source_label="test dataset",
    )

    assert output_path.exists()
    assert summary_path.exists()
    assert list(ranking.columns) == [
        "borough",
        "property_count",
        "mean_epc_score",
        "mean_energy_intensity_kwh_m2_year",
        "composite_priority_score",
        "rank",
    ]
    assert len(ranking) == 3
    assert ranking.iloc[0]["borough"] == "Alpha"
    assert ranking["rank"].tolist() == [1, 2, 3]
    assert "TOP 10 BOROUGHS" in summary_path.read_text(encoding="utf-8")


def test_generate_tenure_segmentation_maps_groups_and_percentages(tmp_path):
    reporter = AdditionalReports()
    df = pd.DataFrame(
        [
            {
                "tenure": "owner_occupied",
                "CURRENT_ENERGY_EFFICIENCY": 60,
                "energy_kwh_per_m2_year": 210,
                "wall_insulated": True,
                "heating_system_type": "Gas Boiler",
            },
            {
                "tenure": "rental (private)",
                "CURRENT_ENERGY_EFFICIENCY": 55,
                "energy_kwh_per_m2_year": 240,
                "wall_insulated": False,
                "heating_system_type": "Heat Pump",
            },
            {
                "tenure": "private_rented",
                "CURRENT_ENERGY_EFFICIENCY": 58,
                "energy_kwh_per_m2_year": 230,
                "wall_insulated": False,
                "heating_system_type": "Gas Boiler",
            },
            {
                "tenure": "social",
                "CURRENT_ENERGY_EFFICIENCY": 62,
                "energy_kwh_per_m2_year": 205,
                "wall_insulated": True,
                "heating_system_type": "District/Communal/Heat Network",
            },
            {
                "tenure": None,
                "CURRENT_ENERGY_EFFICIENCY": 59,
                "energy_kwh_per_m2_year": 215,
                "wall_insulated": False,
                "heating_system_type": "Other",
            },
        ]
    )

    output_path = tmp_path / "tenure_segmentation.csv"
    summary_path = tmp_path / "tenure_segmentation.txt"
    segmentation = reporter.generate_tenure_segmentation(
        df,
        output_path=output_path,
        summary_path=summary_path,
        source_label="test dataset",
    )

    assert output_path.exists()
    assert summary_path.exists()
    assert segmentation["property_count"].sum() == len(df)
    assert round(segmentation["share_pct"].sum(), 2) == 100.00

    private_row = segmentation.loc[
        segmentation["tenure_group"] == "private_rented_sector"
    ].iloc[0]
    assert private_row["property_count"] == 2
    assert private_row["pct_heat_pump"] == 50.0
    assert private_row["pct_gas_boiler"] == 50.0

    social_row = segmentation.loc[
        segmentation["tenure_group"] == "social_affordable"
    ].iloc[0]
    assert social_row["pct_district"] == 100.0
    assert "KEY FINDINGS" in summary_path.read_text(encoding="utf-8")
def test_tenure_mapper_recognises_raw_epc_labels():
    reporter = AdditionalReports()

    assert (
        reporter._map_tenure_group('Owner-occupied')
        == 'owner_occupied'
    )
    assert (
        reporter._map_tenure_group('Rented (private)')
        == 'private_rented_sector'
    )
    assert (
        reporter._map_tenure_group('Rented (social)')
        == 'social_affordable'
    )
    assert reporter._map_tenure_group(None) == 'unknown'


def test_tenure_report_uses_raw_tenure_when_canonical_is_damaged(
    tmp_path,
):
    reporter = AdditionalReports()

    df = pd.DataFrame(
        [
            {
                'TENURE': 'Owner-occupied',
                'tenure': 'owner_occupied',
                'CURRENT_ENERGY_EFFICIENCY': 60,
                'energy_kwh_per_m2_year': 200,
                'wall_insulated': True,
                'heating_system_type': 'Gas Boiler',
            },
            {
                'TENURE': 'Rented (private)',
                'tenure': 'unknown',
                'CURRENT_ENERGY_EFFICIENCY': 55,
                'energy_kwh_per_m2_year': 240,
                'wall_insulated': False,
                'heating_system_type': 'Gas Boiler',
            },
            {
                'TENURE': 'Rented (social)',
                'tenure': 'unknown',
                'CURRENT_ENERGY_EFFICIENCY': 58,
                'energy_kwh_per_m2_year': 220,
                'wall_insulated': False,
                'heating_system_type': 'Gas Boiler',
            },
        ]
    )

    result = reporter.generate_tenure_segmentation(
        df,
        output_path=tmp_path / 'tenure.csv',
    )

    counts = (
        result.set_index('tenure_group')['property_count']
        .astype(int)
        .to_dict()
    )

    assert counts['owner_occupied'] == 1
    assert counts['private_rented_sector'] == 1
    assert counts['social_affordable'] == 1