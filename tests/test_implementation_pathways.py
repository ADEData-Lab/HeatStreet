from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from config.config import load_config
from src.modeling.implementation_pathways import (
    ASHP_IMPLEMENTATION,
    SPATIAL_IMPLEMENTATION,
    ImplementationPathwayModeler,
)


def _property(**overrides):
    base = {
        "CERTIFICATE_NUMBER": "test-1",
        "UPRN": "1",
        "POSTCODE": "SW1A 1AA",
        "TOTAL_FLOOR_AREA": 100.0,
        "CURRENT_ENERGY_EFFICIENCY": 55,
        "CURRENT_ENERGY_RATING": "D",
        "ENERGY_CONSUMPTION_CURRENT": 90.0,
        "energy_consumption_adjusted": 90.0,
        "estimated_flow_temp": 40.0,
        "wall_type": "Solid",
        "rebound_factor": 1.0,
        "tier_number": 5,
        "hn_ready": False,
        "in_heat_zone": False,
        "distance_to_network_m": None,
    }
    base.update(overrides)
    return base


@pytest.fixture()
def modeler(tmp_path: Path) -> ImplementationPathwayModeler:
    config = load_config()
    config["implementation_pathways"] = {
        "candidate_measures": [
            "loft_insulation_topup",
            "emitter_upgrades",
            "wall_insulation",
        ],
        "maximum_heat_demand_kwh_m2": 100,
        "maximum_flow_temperature_c": 45,
        "confirmed_network_tiers": [1, 2],
        "strategic_network_tiers": [3],
        "require_positive_heat_demand": True,
    }
    return ImplementationPathwayModeler(config=config, output_dir=tmp_path)


def test_ready_property_receives_ashp(modeler: ImplementationPathwayModeler):
    frame = pd.DataFrame([_property()])
    result = modeler.model_scenario(frame, ASHP_IMPLEMENTATION).iloc[0]
    assert result["implementation_status"] == "deployed"
    assert result["final_pathway"] == "ashp_installed"
    assert bool(result["ashp_installed"])
    assert bool(result["deployment_contract_passed"])


def test_unready_property_is_deferred_without_ashp(modeler: ImplementationPathwayModeler):
    frame = pd.DataFrame(
        [
            _property(
                ENERGY_CONSUMPTION_CURRENT=500.0,
                energy_consumption_adjusted=500.0,
                estimated_flow_temp=70.0,
            )
        ]
    )
    result = modeler.model_scenario(frame, ASHP_IMPLEMENTATION).iloc[0]
    assert result["implementation_status"] == "deferred"
    assert not bool(result["ashp_installed"])
    assert not bool(result["deployment_contract_passed"])
    assert result["deferred_reason"]
    assert "ashp_installation" not in result["measures_applied"]


def test_confirmed_network_tier_connects(modeler: ImplementationPathwayModeler):
    frame = pd.DataFrame([_property(tier_number=1, hn_ready=True)])
    result = modeler.model_scenario(frame, SPATIAL_IMPLEMENTATION).iloc[0]
    assert result["final_pathway"] == "heat_network_connected"
    assert bool(result["heat_network_connected"])
    assert bool(result["heat_network_confirmed_available"])
    assert not bool(result["ashp_installed"])


def test_high_density_tier_is_not_treated_as_available_network(
    modeler: ImplementationPathwayModeler,
):
    frame = pd.DataFrame(
        [
            _property(
                tier_number=3,
                hn_ready=True,
                ENERGY_CONSUMPTION_CURRENT=500.0,
                energy_consumption_adjusted=500.0,
                estimated_flow_temp=70.0,
            )
        ]
    )
    result = modeler.model_scenario(frame, SPATIAL_IMPLEMENTATION).iloc[0]
    assert not bool(result["heat_network_connected"])
    assert not bool(result["heat_network_confirmed_available"])
    assert bool(result["strategic_network_candidate"])
    assert result["final_pathway"] == "deferred_strategic_network_candidate"


def test_each_property_has_one_final_state(modeler: ImplementationPathwayModeler):
    frame = pd.DataFrame(
        [
            _property(CERTIFICATE_NUMBER="a", tier_number=1, hn_ready=True),
            _property(CERTIFICATE_NUMBER="b", tier_number=5, hn_ready=False),
        ]
    )
    result = modeler.model_scenario(frame, SPATIAL_IMPLEMENTATION)
    assert len(result) == 2
    assert result["property_id"].is_unique
    assert result["implementation_status"].isin({"deployed", "deferred"}).all()
