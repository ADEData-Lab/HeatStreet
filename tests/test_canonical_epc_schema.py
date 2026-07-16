import pandas as pd
import pytest

from src.analysis.archetype_analysis import ArchetypeAnalyzer
from src.cleaning.data_validator import EPCDataValidator


@pytest.mark.parametrize(
    ("description", "expected_category", "expected_present"),
    [
        ("Suspended timber, no insulation", "none", False),
        ("Solid floor, uninsulated", "none", False),
        ("Suspended timber, insulated", "full", True),
        ("Some limited floor insulation", "some", True),
        ("Floor U-value 0.72 W/m2K", "unknown", pd.NA),
    ],
)
def test_floor_standardisation_is_explicit_and_nullable(
    description, expected_category, expected_present
):
    frame = pd.DataFrame({"FLOOR_DESCRIPTION": [description]})

    result = EPCDataValidator()._standardize_floor_insulation(frame)

    assert result.loc[0, "floor_insulation"] == expected_category
    if expected_present is pd.NA:
        assert pd.isna(result.loc[0, "floor_insulation_present"])
    else:
        assert bool(result.loc[0, "floor_insulation_present"]) is expected_present


def test_blank_and_efficiency_only_floor_data_remain_unknown():
    frame = pd.DataFrame(
        {
            "FLOOR_DESCRIPTION": ["", None],
            "FLOOR_ENERGY_EFF": ["Very Poor", "Very Good"],
        }
    )

    result = EPCDataValidator()._standardize_floor_insulation(frame)

    assert result["floor_insulation"].tolist() == ["unknown", "unknown"]
    assert result["floor_insulation_present"].isna().all()


def test_archetype_floor_totals_keep_unknown_separate():
    frame = pd.DataFrame(
        {
            "floor_insulation": ["none", "none", "some", "full", "unknown"],
            "floor_insulation_present": pd.Series(
                [False, False, True, True, pd.NA], dtype="boolean"
            ),
        }
    )

    result = ArchetypeAnalyzer().analyze_floor_insulation(frame)

    assert result["insulated"] == 2
    assert result["uninsulated"] == 2
    assert result["unknown"] == 1
    assert result["insulated_pct"] == 40.0
    assert result["uninsulated_pct"] == 40.0
    assert result["unknown_pct"] == 20.0


@pytest.mark.parametrize("alias", EPCDataValidator.HEATING_CONTROL_ALIASES)
def test_heating_control_aliases_produce_identical_canonical_analysis(alias):
    values = [
        " Programmer, room thermostat and TRVs ",
        "Smart wireless controls",
        "   ",
    ]
    validator = EPCDataValidator()
    frame = validator._resolve_heating_controls_description(pd.DataFrame({alias: values}))

    result = ArchetypeAnalyzer().analyze_heating_controls(frame)

    assert result["data_completeness"] == pytest.approx(200 / 3)
    assert result["trv_present"] == 1
    assert result["programmer_present"] == 1
    assert result["room_thermostat_present"] == 1
    assert result["smart_controls_present"] == 1
    schema = validator.validation_report["heating_controls_schema"]
    assert schema["selected_source_counts"][alias] == 2
    assert schema["conflict_count"] == 0


def test_heating_control_conflicts_fail_in_strict_mode():
    frame = pd.DataFrame(
        {
            "MAINHEAT_CONT_DESCRIPTION": ["Programmer"],
            "MAINHEATCONT_DESCRIPTION": ["Room thermostat"],
        }
    )

    with pytest.raises(ValueError, match="Conflicting heating-control aliases"):
        EPCDataValidator(strict_schema_conflicts=True)._resolve_heating_controls_description(frame)


@pytest.mark.parametrize(
    ("method", "frame", "message"),
    [
        ("analyze_floor_insulation", pd.DataFrame({"FLOOR_DESCRIPTION": ["insulated"]}), "canonical floor"),
        ("analyze_glazing", pd.DataFrame({"WINDOWS_DESCRIPTION": ["double"]}), "canonical glazing"),
        ("analyze_heating_controls", pd.DataFrame({"MAINHEAT_CONT_DESCRIPTION": ["TRV"]}), "canonical heating"),
    ],
)
def test_archetype_rejects_raw_field_fallbacks(method, frame, message):
    with pytest.raises(ValueError, match=message):
        getattr(ArchetypeAnalyzer(), method)(frame)
