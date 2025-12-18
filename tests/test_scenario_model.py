"""Unit tests for scenario modeling edge cases and hybrid routing."""

from pathlib import Path
import pandas as pd
import pytest
import sys
import types

# Lightweight stubs so scenario_model import does not require heavyweight spatial deps
sys.modules.setdefault(
    'geopandas',
    types.SimpleNamespace(GeoDataFrame=object, read_file=lambda *_, **__: None)
)
sys.modules.setdefault('shapely', types.SimpleNamespace())
sys.modules.setdefault('shapely.geometry', types.SimpleNamespace(Point=object))

sys.path.append(str(Path(__file__).parent.parent))

from src.modeling import scenario_model


class DummyFabricTippingPointAnalyzer:
    """Lightweight stub to avoid heavy fabric analysis in tests."""

    def __init__(self, output_dir=None):
        self.output_dir = output_dir

    def run_analysis(self):
        return pd.DataFrame(), {}

    def derive_fabric_bundles(self, curve_df, typical_annual_heat_demand_kwh=15000):
        return {
            'fabric_full_to_tipping': ['loft_insulation', 'double_glazing_upgrade'],
            'fabric_minimum_to_ashp': ['loft_insulation']
        }


class DummyHeatNetworkAnalyzer:
    def __init__(self, ready_postcodes=None):
        self.ready_postcodes = set(ready_postcodes or [])

    def annotate_heat_network_readiness(self, df: pd.DataFrame) -> pd.DataFrame:
        annotated = df.copy()
        postcodes = annotated.get('POSTCODE', pd.Series('', index=annotated.index))
        annotated['hn_ready'] = postcodes.isin(self.ready_postcodes)
        annotated['tier_number'] = annotated.get('tier_number', 1)
        annotated['distance_to_network_m'] = annotated.get('distance_to_network_m', 50)
        annotated['in_heat_zone'] = annotated['hn_ready']
        return annotated


@pytest.fixture
def scenario_modeler_factory(monkeypatch):
    """Provide a ScenarioModeler with lightweight spatial and fabric dependencies."""

    def factory(ready_postcodes=None):
        monkeypatch.setattr(
            scenario_model, 'FabricTippingPointAnalyzer', DummyFabricTippingPointAnalyzer
        )
        monkeypatch.setattr(
            scenario_model, 'HeatNetworkAnalyzer', lambda: DummyHeatNetworkAnalyzer(ready_postcodes)
        )
        return scenario_model.ScenarioModeler()

    return factory


def test_hybrid_routing_and_costs(monkeypatch, scenario_modeler_factory):
    modeler = scenario_modeler_factory(ready_postcodes={'HN1'})

    base_measures = ['modest_fabric_improvements', 'heat_network_where_available', 'ashp_elsewhere']
    ready_property = {
        'LMK_KEY': 'HN_READY',
        'POSTCODE': 'HN1',
        'TOTAL_FLOOR_AREA': 80,
        'ENERGY_CONSUMPTION_CURRENT': 150,
        'wall_type': 'Solid',
        'ashp_ready': True,
        'ashp_projected_ready': True,
        'hn_ready': True
    }
    not_ready_property = {
        'LMK_KEY': 'NO_HN',
        'POSTCODE': 'ZZZ',
        'TOTAL_FLOOR_AREA': 80,
        'ENERGY_CONSUMPTION_CURRENT': 150,
        'wall_type': 'Cavity',
        'ashp_ready': True,
        'ashp_projected_ready': True,
        'hn_ready': False
    }

    ready_plan, _, _, ready_pathway, _ = modeler._build_property_measures(base_measures, ready_property)
    not_ready_plan, _, _, not_ready_pathway, _ = modeler._build_property_measures(base_measures, not_ready_property)

    assert 'district_heating_connection' in ready_plan
    assert 'ashp_installation' not in ready_plan
    assert ready_pathway == 'heat_network'

    assert 'ashp_installation' in not_ready_plan
    assert 'emitter_upgrades' in not_ready_plan
    assert not_ready_pathway == 'ashp'

    fabric_only_plan = modeler._resolve_scenario_measures(['fabric_improvements'])

    hybrid_upgrades = [
        modeler._calculate_property_upgrade(pd.Series(prop), 'hybrid', plan)
        for prop, plan in (
            (ready_property, ready_plan),
            (not_ready_property, not_ready_plan),
        )
    ]

    fabric_upgrades = [
        modeler._calculate_property_upgrade(pd.Series(prop), 'fabric', fabric_only_plan)
        for prop in (ready_property, not_ready_property)
    ]

    hybrid_avg = sum(u.capital_cost for u in hybrid_upgrades) / len(hybrid_upgrades)
    fabric_avg = sum(u.capital_cost for u in fabric_upgrades) / len(fabric_upgrades)

    assert hybrid_avg > fabric_avg


def test_unrecognised_measure_raises(monkeypatch):
    monkeypatch.setattr(
        scenario_model, 'FabricTippingPointAnalyzer', DummyFabricTippingPointAnalyzer
    )
    monkeypatch.setattr(
        scenario_model, 'HeatNetworkAnalyzer', lambda: DummyHeatNetworkAnalyzer()
    )
    monkeypatch.setattr(
        scenario_model,
        'get_scenario_definitions',
        lambda: {'invalid_scenario': {'measures': ['not_a_real_measure']}}
    )

    with pytest.raises(ValueError):
        scenario_model.ScenarioModeler()


def test_hn_ready_generation_drives_pathway(monkeypatch, scenario_modeler_factory):
    modeler = scenario_modeler_factory(ready_postcodes={'AB1'})

    df = pd.DataFrame([
        {'LMK_KEY': 'AB_PROP', 'POSTCODE': 'AB1', 'TOTAL_FLOOR_AREA': 70, 'ENERGY_CONSUMPTION_CURRENT': 140},
    ])

    processed = modeler._preprocess_ashp_readiness(df)

    assert 'hn_ready' in processed.columns
    assert bool(processed.loc[0, 'hn_ready']) is True

    measures = ['fabric_improvements', 'heat_network_where_available', 'ashp_elsewhere']
    plan, _, _, pathway, _ = modeler._build_property_measures(
        measures,
        processed.iloc[0].to_dict()
    )

    assert pathway == 'heat_network'
    assert 'district_heating_connection' in plan
    assert 'ashp_installation' not in plan


def test_negative_energy_intensity_rejected(scenario_modeler_factory):
    modeler = scenario_modeler_factory()

    df = pd.DataFrame([
        {
            'LMK_KEY': 'NEG_EN',
            'TOTAL_FLOOR_AREA': 75,
            'ENERGY_CONSUMPTION_CURRENT': -15,
            'CURRENT_ENERGY_RATING': 'D',
        }
    ])

    with pytest.raises(ValueError):
        modeler.model_all_scenarios(df)
