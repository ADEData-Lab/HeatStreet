from pathlib import Path
import sys

import pandas as pd
import pytest

sys.path.append(str(Path(__file__).parent.parent))

from src.analysis.retrofit_readiness import RetrofitReadinessAnalyzer


def test_readiness_cost_decomposition_and_tier_technology():
    df = pd.DataFrame(
        [
            {
                "LMK_KEY": "tier_1",
                "TOTAL_FLOOR_AREA": 100,
                "ENERGY_CONSUMPTION_CURRENT": 90,
                "CURRENT_ENERGY_EFFICIENCY": 70,
                "CURRENT_ENERGY_RATING": "C",
                "wall_insulated": True,
                "wall_type": "Cavity",
                "ROOF_ENERGY_EFF": "Good",
                "glazing_type": "double glazing",
                "FLOOR_ENERGY_EFF": "Good",
            },
            {
                "LMK_KEY": "tier_2",
                "TOTAL_FLOOR_AREA": 100,
                "ENERGY_CONSUMPTION_CURRENT": 90,
                "CURRENT_ENERGY_EFFICIENCY": 62,
                "CURRENT_ENERGY_RATING": "D",
                "wall_insulated": True,
                "wall_type": "Cavity",
                "ROOF_ENERGY_EFF": "Poor",
                "glazing_type": "double glazing",
                "FLOOR_ENERGY_EFF": "Good",
            },
            {
                "LMK_KEY": "tier_3",
                "TOTAL_FLOOR_AREA": 100,
                "ENERGY_CONSUMPTION_CURRENT": 90,
                "CURRENT_ENERGY_EFFICIENCY": 60,
                "CURRENT_ENERGY_RATING": "D",
                "wall_insulated": False,
                "wall_type": "Cavity",
                "ROOF_ENERGY_EFF": "Good",
                "glazing_type": "double glazing",
                "FLOOR_ENERGY_EFF": "Good",
            },
            {
                "LMK_KEY": "tier_4",
                "TOTAL_FLOOR_AREA": 100,
                "ENERGY_CONSUMPTION_CURRENT": 90,
                "CURRENT_ENERGY_EFFICIENCY": 60,
                "CURRENT_ENERGY_RATING": "D",
                "wall_insulated": False,
                "wall_type": "Cavity",
                "ROOF_ENERGY_EFF": "Poor",
                "glazing_type": "double glazing",
                "FLOOR_ENERGY_EFF": "Good",
            },
        ]
    )
    df["wall_insulation_status"] = df["wall_insulated"].map({True: "cavity_filled", False: "none"})
    df["floor_insulation"] = "full"
    df["floor_insulation_present"] = pd.Series([True] * len(df), dtype="boolean")

    analyzer = RetrofitReadinessAnalyzer()
    readiness = analyzer.assess_heat_pump_readiness(df)
    summary = analyzer.generate_readiness_summary(readiness)

    pd.testing.assert_series_equal(
        readiness["fabric_prerequisite_cost"] + readiness["system_cost_full_ashp"],
        readiness["total_cost_full_ashp"],
        check_names=False,
    )
    pd.testing.assert_series_equal(
        readiness["fabric_prerequisite_cost"] + readiness["system_cost_hybrid_ashp_sensitivity"],
        readiness["total_cost_hybrid_ashp_sensitivity"],
        check_names=False,
    )

    assert not {"system_cost", "total_cost", "total_retrofit_cost"}.intersection(readiness.columns)
    assert readiness["ashp_plus_boiler_sensitivity_label"].eq(
        "Tier 4 ASHP-plus-boiler capital-cost sensitivity"
    ).all()
    caveats = readiness["ashp_plus_boiler_sensitivity_qualifications"].iloc[0].casefold()
    assert "not the spatial heat-network/ashp hybrid scenario" in caveats
    assert "not a recommended pathway" in caveats
    assert "retains boiler backup" in caveats

    full_ashp_by_tier = summary["total_cost_full_ashp_by_tier"]
    ordered = [full_ashp_by_tier[tier] for tier in sorted(full_ashp_by_tier)]
    assert ordered == sorted(ordered)


def _readiness_boolean_fixture(floor_values):
    row = {
        "TOTAL_FLOOR_AREA": 100,
        "ENERGY_CONSUMPTION_CURRENT": 90,
        "CURRENT_ENERGY_EFFICIENCY": 70,
        "CURRENT_ENERGY_RATING": "C",
        "wall_insulated": True,
        "wall_type": "Cavity",
        "wall_insulation_status": "cavity_filled",
        "ROOF_ENERGY_EFF": "Good",
        "glazing_type": "double glazing",
        "floor_insulation": "unknown",
    }
    frame = pd.DataFrame([dict(row, LMK_KEY=str(index)) for index in range(len(floor_values))])
    frame["floor_insulation_present"] = floor_values
    return frame


def test_readiness_accepts_nullable_and_legacy_boolean_values_identically():
    nullable = _readiness_boolean_fixture(
        pd.Series([True, False, pd.NA], dtype="boolean")
    )
    legacy = _readiness_boolean_fixture(pd.Series(["True", "False", None], dtype="object"))

    analyzer = RetrofitReadinessAnalyzer()
    nullable_result = analyzer.assess_heat_pump_readiness(nullable)
    legacy_result = analyzer.assess_heat_pump_readiness(legacy)

    assert str(nullable_result["floor_insulation_present"].dtype) == "boolean"
    pd.testing.assert_frame_equal(nullable_result, legacy_result)
    assert nullable_result.loc[1, "deficiency_score"] == nullable_result.loc[2, "deficiency_score"]


def test_readiness_accepts_standard_serialized_null_tokens():
    frame = _readiness_boolean_fixture(
        pd.Series(["None", "null", "NaN", "<NA>", ""], dtype="object")
    )

    result = RetrofitReadinessAnalyzer().assess_heat_pump_readiness(frame)

    assert result["floor_insulation_present"].isna().all()


def test_readiness_rejects_invalid_canonical_boolean_token():
    frame = _readiness_boolean_fixture(pd.Series(["unknown-value"], dtype="object"))

    with pytest.raises(
        ValueError,
        match=r"schema contract violation for 'floor_insulation_present'.*unknown-value",
    ):
        RetrofitReadinessAnalyzer().assess_heat_pump_readiness(frame)
