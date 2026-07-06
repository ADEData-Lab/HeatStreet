from pathlib import Path
import sys

import pandas as pd

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

    analyzer = RetrofitReadinessAnalyzer()
    readiness = analyzer.assess_heat_pump_readiness(df)
    summary = analyzer.generate_readiness_summary(readiness)

    pd.testing.assert_series_equal(
        readiness["fabric_prerequisite_cost"] + readiness["system_cost"],
        readiness["total_cost"],
        check_names=False,
    )
    pd.testing.assert_series_equal(
        readiness["total_retrofit_cost"],
        readiness["total_cost"],
        check_names=False,
    )

    tier_technology = dict(
        zip(readiness["hp_readiness_tier"], readiness["system_technology"])
    )
    assert tier_technology[4] == "hybrid_ashp"
    assert all(
        technology == "ashp"
        for tier, technology in tier_technology.items()
        if tier != 4
    )

    full_ashp_by_tier = summary["total_cost_full_ashp_by_tier"]
    ordered = [full_ashp_by_tier[tier] for tier in sorted(full_ashp_by_tier)]
    assert ordered == sorted(ordered)
