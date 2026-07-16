from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

import run_analysis
from src.utils.staged_dataset import (
    DatasetReference,
    iter_parquet_batches,
    parquet_columns,
    parquet_row_count,
)
from src.utils.staged_processing import (
    apply_adjustments_staged_dataset,
    validate_staged_dataset,
)


def _write_parquet_dataset_dir(dataset_dir: Path, df: pd.DataFrame) -> Path:
    dataset_dir.mkdir(parents=True, exist_ok=True)
    split_point = max(1, len(df) // 2)
    frames = [df.iloc[:split_point].copy(), df.iloc[split_point:].copy()]
    for index, frame in enumerate(frames):
        if frame.empty:
            continue
        frame.to_parquet(dataset_dir / f"part-{index:05d}.parquet", index=False)
    (dataset_dir / "calculation_notes.md").write_text("# Calculation notes\n", encoding="utf-8")
    return dataset_dir


def test_dataset_reference_load_dataframe_ignores_non_parquet_sidecars(tmp_path):
    dataset_df = pd.DataFrame(
        [
            {"UPRN": "1", "COUNCIL": "Camden", "PROPERTY_TYPE": "House"},
            {"UPRN": "2", "COUNCIL": "Westminster", "PROPERTY_TYPE": "Flat"},
        ]
    )
    dataset_dir = _write_parquet_dataset_dir(tmp_path / "raw_certificates_dataset", dataset_df)
    dataset_ref = DatasetReference(
        name="sidecar_dataset",
        parquet_path=dataset_dir,
        stage="raw",
        row_count=len(dataset_df),
    )

    loaded = dataset_ref.load_dataframe(columns=["UPRN", "COUNCIL"])

    assert list(loaded.columns) == ["UPRN", "COUNCIL"]
    assert sorted(loaded["UPRN"].tolist()) == ["1", "2"]
    assert sorted(loaded["COUNCIL"].tolist()) == ["Camden", "Westminster"]


def test_parquet_dataset_helpers_ignore_non_parquet_sidecars(tmp_path):
    dataset_df = pd.DataFrame(
        [
            {"UPRN": "1", "COUNCIL": "Camden", "PROPERTY_TYPE": "House"},
            {"UPRN": "2", "COUNCIL": "Westminster", "PROPERTY_TYPE": "Flat"},
            {"UPRN": "3", "COUNCIL": "Camden", "PROPERTY_TYPE": "House"},
        ]
    )
    dataset_dir = _write_parquet_dataset_dir(tmp_path / "validated_dataset", dataset_df)

    batches = list(iter_parquet_batches(dataset_dir, batch_size=1, columns=["UPRN", "COUNCIL"]))
    batch_df = pd.concat(batches, ignore_index=True)

    assert parquet_row_count(dataset_dir) == len(dataset_df)
    assert parquet_columns(dataset_dir) == list(dataset_df.columns)
    assert len(batch_df) == len(dataset_df)
    assert list(batch_df.columns) == ["UPRN", "COUNCIL"]
    assert sorted(batch_df["UPRN"].tolist()) == ["1", "2", "3"]


def test_staged_validation_and_adjustment_create_parquet_outputs(tmp_path):
    raw_parquet = tmp_path / "raw_input.parquet"
    raw_df = pd.DataFrame(
        [
            {
                "UPRN": "1",
                "LODGEMENT_DATE": "2024-01-01",
                "POSTCODE": "SW1A 1AA",
                "PROPERTY_TYPE": "House",
                "BUILT_FORM": "Mid-Terrace",
                "CONSTRUCTION_AGE_BAND": "England and Wales: 1900-1929",
                "CURRENT_ENERGY_RATING": "D",
                "CURRENT_ENERGY_EFFICIENCY": 60,
                "TOTAL_FLOOR_AREA": 100,
                "ENERGY_CONSUMPTION_CURRENT": 200,
                "CO2_EMISSIONS_CURRENT": 4.5,
                "WALLS_DESCRIPTION": "Solid brick, as built, no insulation",
                "FLOOR_DESCRIPTION": "Suspended timber, insulated",
                "MAINHEAT_DESCRIPTION": "Boiler and radiators, mains gas",
            },
            {
                "UPRN": "1",
                "LODGEMENT_DATE": "2023-01-01",
                "POSTCODE": "SW1A 1AA",
                "PROPERTY_TYPE": "House",
                "BUILT_FORM": "Mid-Terrace",
                "CONSTRUCTION_AGE_BAND": "England and Wales: 1900-1929",
                "CURRENT_ENERGY_RATING": "E",
                "CURRENT_ENERGY_EFFICIENCY": 55,
                "TOTAL_FLOOR_AREA": 100,
                "ENERGY_CONSUMPTION_CURRENT": 220,
                "CO2_EMISSIONS_CURRENT": 5.0,
                "WALLS_DESCRIPTION": "Solid brick, as built, no insulation",
                "FLOOR_DESCRIPTION": "Suspended timber, insulated",
                "MAINHEAT_DESCRIPTION": "Boiler and radiators, mains gas",
            },
            {
                "UPRN": "2",
                "LODGEMENT_DATE": "2024-01-01",
                "POSTCODE": "SW1A 1AA",
                "PROPERTY_TYPE": "House",
                "BUILT_FORM": "Mid-Terrace",
                "CONSTRUCTION_AGE_BAND": "England and Wales: 1900-1929",
                "CURRENT_ENERGY_RATING": "D",
                "CURRENT_ENERGY_EFFICIENCY": 60,
                "TOTAL_FLOOR_AREA": 100,
                "ENERGY_CONSUMPTION_CURRENT": 200,
                "CO2_EMISSIONS_CURRENT": 4.5,
                "WALLS_DESCRIPTION": "Solid brick, as built, no insulation",
                "FLOOR_DESCRIPTION": "Solid floor, no insulation",
                "MAINHEAT_DESCRIPTION": "Boiler and radiators, mains gas",
            },
            {
                "UPRN": "3",
                "LODGEMENT_DATE": "2024-01-01",
                "POSTCODE": "SW1A 1AA",
                "PROPERTY_TYPE": "House",
                "BUILT_FORM": "Mid-Terrace",
                "CONSTRUCTION_AGE_BAND": "England and Wales: 1900-1929",
                "CURRENT_ENERGY_RATING": "D",
                "CURRENT_ENERGY_EFFICIENCY": 60,
                "TOTAL_FLOOR_AREA": 100,
                "ENERGY_CONSUMPTION_CURRENT": 200,
                "CO2_EMISSIONS_CURRENT": 4.5,
                "WALLS_DESCRIPTION": "Solid brick, as built, no insulation",
                "FLOOR_DESCRIPTION": None,
                "MAINHEAT_DESCRIPTION": "Boiler and radiators, mains gas",
            },
        ]
    )
    raw_df.to_parquet(raw_parquet, index=False)

    raw_dataset = DatasetReference(
        name="raw_input",
        parquet_path=raw_parquet,
        stage="raw",
        row_count=len(raw_df),
        sample_start_date="2024-01-01",
        sample_end_date="2024-12-31",
    )

    validated_dataset, report = validate_staged_dataset(
        raw_dataset,
        tmp_path / "validated.csv",
        chunk_size=10,
    )

    assert validated_dataset.parquet_path.exists()
    assert validated_dataset.csv_path.exists()
    assert validated_dataset.row_count == 3
    assert report["duplicates_removed"] == 1
    validated_floor = pd.read_parquet(validated_dataset.parquet_path)["floor_insulation_present"]
    assert ds.dataset(validated_dataset.parquet_path).schema.field(
        "floor_insulation_present"
    ).type == pa.bool_()
    assert int((validated_floor == True).sum()) == 1  # noqa: E712
    assert int((validated_floor == False).sum()) == 1  # noqa: E712
    assert int(validated_floor.isna().sum()) == 1

    adjusted_dataset, summary = apply_adjustments_staged_dataset(
        validated_dataset,
        tmp_path / "adjusted.csv",
        chunk_size=10,
    )

    assert adjusted_dataset.parquet_path.exists()
    assert adjusted_dataset.csv_path.exists()
    assert adjusted_dataset.row_count == 3
    assert summary["prebound_adjustment"]["applied"] is True
    assert summary["flow_temperature"]["applied"] is True
    adjusted_floor = pd.read_parquet(adjusted_dataset.parquet_path)["floor_insulation_present"]
    assert ds.dataset(adjusted_dataset.parquet_path).schema.field(
        "floor_insulation_present"
    ).type == pa.bool_()
    pd.testing.assert_series_equal(
        adjusted_floor.reset_index(drop=True),
        validated_floor.reset_index(drop=True),
        check_names=False,
    )


def test_noninteractive_staged_download_validate_adjust_smoke(monkeypatch, tmp_path):
    class DummyPrompt:
        def __init__(self, value):
            self.value = value

        def ask(self):
            return self.value

    class FakeConsole:
        def clear(self):
            return None

        def print(self, *args, **kwargs):
            return None

    raw_df = pd.DataFrame(
        [
            {
                "UPRN": "1",
                "LODGEMENT_DATE": "2024-01-01",
                "POSTCODE": "SW1A 1AA",
                "PROPERTY_TYPE": "House",
                "BUILT_FORM": "Mid-Terrace",
                "CONSTRUCTION_AGE_BAND": "England and Wales: 1900-1929",
                "CURRENT_ENERGY_RATING": "D",
                "CURRENT_ENERGY_EFFICIENCY": 60,
                "TOTAL_FLOOR_AREA": 100,
                "ENERGY_CONSUMPTION_CURRENT": 200,
                "CO2_EMISSIONS_CURRENT": 4.5,
                "WALLS_DESCRIPTION": "Solid brick, as built, no insulation",
                "MAINHEAT_DESCRIPTION": "Boiler and radiators, mains gas",
            },
            {
                "UPRN": "1",
                "LODGEMENT_DATE": "2023-01-01",
                "POSTCODE": "SW1A 1AA",
                "PROPERTY_TYPE": "House",
                "BUILT_FORM": "Mid-Terrace",
                "CONSTRUCTION_AGE_BAND": "England and Wales: 1900-1929",
                "CURRENT_ENERGY_RATING": "E",
                "CURRENT_ENERGY_EFFICIENCY": 55,
                "TOTAL_FLOOR_AREA": 100,
                "ENERGY_CONSUMPTION_CURRENT": 220,
                "CO2_EMISSIONS_CURRENT": 5.0,
                "WALLS_DESCRIPTION": "Solid brick, as built, no insulation",
                "MAINHEAT_DESCRIPTION": "Boiler and radiators, mains gas",
            },
        ]
    )

    national_parquet = tmp_path / "national_input.parquet"
    raw_df.to_parquet(national_parquet, index=False)

    raw_dataset_dir = _write_parquet_dataset_dir(tmp_path / "epc_london_raw_dataset", raw_df)
    filtered_dataset_dir = _write_parquet_dataset_dir(tmp_path / "epc_london_filtered_dataset", raw_df)

    national_ref = DatasetReference(
        name="national_input",
        parquet_path=national_parquet,
        stage="national_raw",
        row_count=len(raw_df),
        metadata={
            "selected_certificate_members": ["domestic.csv"],
            "ignored_recommendation_members": ["recommendations.csv"],
            "malformed_rows_skipped": 0,
        },
    )
    raw_ref = DatasetReference(
        name="raw_london_house_dataset",
        parquet_path=raw_dataset_dir,
        csv_path=tmp_path / "epc_london_raw.csv",
        stage="raw",
        row_count=len(raw_df),
        sample_start_date="2024-01-01",
        sample_end_date="2024-12-31",
        storage_kind="parquet_dataset",
    )
    filtered_ref = DatasetReference(
        name="filtered_london_pre_1930_terraced_dataset",
        parquet_path=filtered_dataset_dir,
        csv_path=tmp_path / "epc_london_filtered.csv",
        stage="raw_filtered",
        row_count=len(raw_df),
        sample_start_date="2024-01-01",
        sample_end_date="2024-12-31",
        storage_kind="parquet_dataset",
    )

    class FakeDownloader:
        LONDON_LA_CODES = {"Camden": "E09000007"}

        def __init__(self, *args, **kwargs):
            return None

        def download_national_domestic_dataset(self, **kwargs):
            return national_ref

        def materialize_full_load_subset(self, input_dataset, output_path, dataset_name, **kwargs):
            if dataset_name == "raw_london_house_dataset":
                return raw_ref
            assert dataset_name == "filtered_london_pre_1930_terraced_dataset"
            return filtered_ref

    monkeypatch.setattr(run_analysis, "console", FakeConsole())
    monkeypatch.setattr(run_analysis, "DATA_RAW_DIR", tmp_path)
    monkeypatch.setattr(run_analysis, "DATA_PROCESSED_DIR", tmp_path)
    monkeypatch.setattr(run_analysis, "EPCAPIDownloader", FakeDownloader)
    monkeypatch.setattr(run_analysis, "write_sample_window_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        run_analysis.questionary,
        "select",
        lambda *args, **kwargs: DummyPrompt("All London boroughs (full dataset)"),
    )

    downloaded_dataset = run_analysis.download_data()
    validated_dataset, report = run_analysis.validate_data(downloaded_dataset)
    adjusted_dataset, summary = run_analysis.apply_methodological_adjustments(validated_dataset)

    assert isinstance(downloaded_dataset, DatasetReference)
    assert isinstance(validated_dataset, DatasetReference)
    assert isinstance(adjusted_dataset, DatasetReference)
    assert report["records_passed"] == 1
    assert adjusted_dataset.csv_path.exists()
    assert adjusted_dataset.parquet_path.exists()
    assert summary["prebound_adjustment"]["applied"] is True
