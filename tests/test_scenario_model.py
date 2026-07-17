"""Unit tests for scenario modeling edge cases and hybrid routing."""

from pathlib import Path
import pandas as pd
import pytest
import sys

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
        'CERTIFICATE_NUMBER': 'HN_READY',
        'POSTCODE': 'HN1',
        'TOTAL_FLOOR_AREA': 80,
        'ENERGY_CONSUMPTION_CURRENT': 150,
        'wall_type': 'Solid',
        'glazing_type': 'unknown',
        'ashp_ready': True,
        'ashp_projected_ready': True,
        'hn_ready': True,
        'tier_number': 2,
    }
    not_ready_property = {
        'CERTIFICATE_NUMBER': 'NO_HN',
        'POSTCODE': 'ZZZ',
        'TOTAL_FLOOR_AREA': 80,
        'ENERGY_CONSUMPTION_CURRENT': 150,
        'wall_type': 'Cavity',
        'glazing_type': 'unknown',
        'ashp_ready': True,
        'ashp_projected_ready': True,
        'hn_ready': False,
        'tier_number': 5,
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


def test_spatially_enriched_hn_readiness_drives_pathway(monkeypatch, scenario_modeler_factory):
    modeler = scenario_modeler_factory(ready_postcodes={'AB1'})

    df = pd.DataFrame([
        {'CERTIFICATE_NUMBER': 'AB_PROP', 'POSTCODE': 'AB1', 'TOTAL_FLOOR_AREA': 70, 'ENERGY_CONSUMPTION_CURRENT': 140, 'glazing_type': 'unknown', 'tier_number': 2, 'hn_ready': True},
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


def test_conflicting_tier_and_hn_ready_is_rejected():
    from src.modeling.contracts import validate_hn_readiness
    frame = pd.DataFrame({"tier_number": [4, 3], "hn_ready": [True, False]})
    with pytest.raises(ValueError, match="conflicts with canonical tiers"):
        validate_hn_readiness(frame)


def test_negative_energy_intensity_rejected(scenario_modeler_factory):
    modeler = scenario_modeler_factory()

    df = pd.DataFrame([
        {
            'CERTIFICATE_NUMBER': 'NEG_EN',
            'TOTAL_FLOOR_AREA': 75,
            'ENERGY_CONSUMPTION_CURRENT': -15,
            'CURRENT_ENERGY_RATING': 'D',
        }
    ])

    with pytest.raises(ValueError):
        modeler.model_all_scenarios(df)


def test_aggregate_cost_per_tco2_and_diagnostic_abatement_aliases(scenario_modeler_factory):
    modeler = scenario_modeler_factory()
    property_df = pd.DataFrame(
        [
            {
                "capital_cost": 10000,
                "annual_energy_reduction_kwh": 1000,
                "annual_co2_reduction_kg": 500,
                "annual_bill_savings": 500,
                "baseline_bill": 1200,
                "post_measure_bill": 700,
                "baseline_co2_kg": 1000,
                "post_measure_co2_kg": 500,
                "payback_years": 20,
                "new_epc_band": "C",
                "carbon_abatement_cost": 1000,
                "upgrade_recommended": True,
            },
            {
                "capital_cost": 20000,
                "annual_energy_reduction_kwh": 1500,
                "annual_co2_reduction_kg": 1000,
                "annual_bill_savings": 1000,
                "baseline_bill": 1600,
                "post_measure_bill": 600,
                "baseline_co2_kg": 2000,
                "post_measure_co2_kg": 1000,
                "payback_years": 20,
                "new_epc_band": "B",
                "carbon_abatement_cost": 2000,
                "upgrade_recommended": True,
            },
        ]
    )
    source_df = pd.DataFrame({"CURRENT_ENERGY_RATING": ["D", "E"]})

    results = modeler._aggregate_scenario_results(property_df, source_df)

    assert results["cost_per_tco2_20yr_gbp"] == 1000
    assert "capital_cost_total / ((annual_co2_reduction_kg / 1000) * 20" in results[
        "cost_per_tco2_20yr_definition"
    ]
    assert results["carbon_abatement_cost_property_mean"] == 1500
    assert results["carbon_abatement_cost_property_median"] == 1500
    assert results["carbon_abatement_cost_property_p10"] == pytest.approx(1100)
    assert results["carbon_abatement_cost_property_p90"] == pytest.approx(1900)
    assert results["carbon_abatement_cost_mean"] == results["carbon_abatement_cost_property_mean"]
    assert results["carbon_abatement_cost_median"] == results["carbon_abatement_cost_property_median"]
    assert results["aggregate_simple_payback_years"] == 20
    assert results["property_simple_payback_mean_years"] == 20
    assert results["truncation_threshold_years"] is None
    assert results["excluded_by_truncation_count"] == 0


def test_subsidy_sensitivity_includes_configured_50_percent_narrative(scenario_modeler_factory):
    modeler = scenario_modeler_factory()
    modeler.results = {
        "heat_pump": {
            "capital_cost_total": 1_000_000,
            "capital_cost_per_property": 10_000,
            "annual_bill_savings": 100_000,
            "annual_co2_reduction_kg": 50_000,
            "total_properties": 100,
            "aggregate_simple_payback_years": 10,
        }
    }

    results = modeler.model_subsidy_sensitivity(pd.DataFrame({"value": [1]}), "heat_pump")

    assert "50%" in results
    line = results["50%"]["narrative_line"]
    assert "50% subsidy" in line
    assert "payback" in line
    assert "uptake" in line
    assert "public spend" in line
    assert "abatement cost" in line
