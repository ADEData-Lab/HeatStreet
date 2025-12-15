"""
Test Module for Heat Street Analysis

Contains lightweight tests and assertions to verify:
1. Hybrid cost bug fix - hybrid pathway costs more than fabric-only
2. EPC anomaly flagging - correctly identifies suspicious properties
3. Package/pathway ID resolution - all IDs resolve to known definitions
"""

import copy
import pandas as pd
import numpy as np
from pathlib import Path
import sys
import pytest

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from loguru import logger


def test_hybrid_cost_bug_fix():
    """
    Verify that the hybrid cost bug is fixed.

    The bug was that hybrid pathway showed same cost as fabric-only.
    After fix, hybrid should have higher costs (fabric + heat tech).

    """
    logger.info("=" * 60)
    logger.info("TEST: Hybrid Cost Bug Fix")
    logger.info("=" * 60)

    from src.modeling.pathway_model import PathwayModeler, PATHWAYS

    # Create test property
    test_property = pd.Series({
        'LMK_KEY': 'TEST_HYBRID_001',
        'TOTAL_FLOOR_AREA': 100,
        'ENERGY_CONSUMPTION_CURRENT': 200,  # kWh/m²/year
        'wall_type': 'solid_brick',
        'wall_insulated': False,
        'roof_insulation_thickness_mm': 50,
        'floor_insulation_present': False,
        'glazing_type': 'single',
    })

    modeler = PathwayModeler()

    # Calculate costs for each pathway
    fabric_only = modeler.calculate_property_pathway(
        test_property,
        PATHWAYS['fabric_only'],
        has_hn_access=False
    )

    hybrid_no_hn = modeler.calculate_property_pathway(
        test_property,
        PATHWAYS['fabric_plus_hp_plus_hn'],
        has_hn_access=False
    )

    hybrid_with_hn = modeler.calculate_property_pathway(
        test_property,
        PATHWAYS['fabric_plus_hp_plus_hn'],
        has_hn_access=True
    )

    hp_only = modeler.calculate_property_pathway(
        test_property,
        PATHWAYS['fabric_plus_hp_only'],
        has_hn_access=False
    )

    hn_only = modeler.calculate_property_pathway(
        test_property,
        PATHWAYS['fabric_plus_hn_only'],
        has_hn_access=True
    )

    # Log results
    logger.info(f"Fabric-only capex: £{fabric_only['total_capex']:,.0f}")
    logger.info(f"HP-only capex: £{hp_only['total_capex']:,.0f}")
    logger.info(f"HN-only capex: £{hn_only['total_capex']:,.0f}")
    logger.info(f"Hybrid (no HN) capex: £{hybrid_no_hn['total_capex']:,.0f}")
    logger.info(f"Hybrid (with HN) capex: £{hybrid_with_hn['total_capex']:,.0f}")

    # Assertions
    errors = []

    # 1. Fabric-only should have non-zero capex
    if fabric_only['total_capex'] <= 0:
        errors.append("Fabric-only should have non-zero capex")

    # 2. All heat tech pathways should cost more than fabric-only
    if hp_only['total_capex'] <= fabric_only['total_capex']:
        errors.append(
            f"HP-only (£{hp_only['total_capex']:,.0f}) should cost more than "
            f"fabric-only (£{fabric_only['total_capex']:,.0f})"
        )

    if hn_only['total_capex'] <= fabric_only['total_capex']:
        errors.append(
            f"HN-only (£{hn_only['total_capex']:,.0f}) should cost more than "
            f"fabric-only (£{fabric_only['total_capex']:,.0f})"
        )

    # 3. KEY TEST: Hybrid should cost more than fabric-only
    if hybrid_no_hn['total_capex'] <= fabric_only['total_capex']:
        errors.append(
            f"HYBRID COST BUG: Hybrid (no HN) (£{hybrid_no_hn['total_capex']:,.0f}) "
            f"should cost more than fabric-only (£{fabric_only['total_capex']:,.0f})"
        )

    if hybrid_with_hn['total_capex'] <= fabric_only['total_capex']:
        errors.append(
            f"HYBRID COST BUG: Hybrid (with HN) (£{hybrid_with_hn['total_capex']:,.0f}) "
            f"should cost more than fabric-only (£{fabric_only['total_capex']:,.0f})"
        )

    # 4. Hybrid without HN should equal HP-only cost
    if abs(hybrid_no_hn['total_capex'] - hp_only['total_capex']) > 1:
        errors.append(
            f"Hybrid (no HN) should equal HP-only cost: "
            f"£{hybrid_no_hn['total_capex']:,.0f} vs £{hp_only['total_capex']:,.0f}"
        )

    # 5. Hybrid with HN should equal HN-only cost
    if abs(hybrid_with_hn['total_capex'] - hn_only['total_capex']) > 1:
        errors.append(
            f"Hybrid (with HN) should equal HN-only cost: "
            f"£{hybrid_with_hn['total_capex']:,.0f} vs £{hn_only['total_capex']:,.0f}"
        )

    if errors:
        for error in errors:
            logger.error(f"FAIL: {error}")
        assert False, "\n".join(errors)

    logger.info("PASS: All hybrid cost bug tests passed!")


def test_carbon_factor_fallback_matches_authoritative(monkeypatch):
    """Ensure hardcoded electricity carbon fallback matches the authoritative config value."""

    from config.config import load_config
    from src.modeling import pathway_model
    from src.modeling.pathway_model import PathwayModeler

    base_config = load_config()
    expected_electricity_factor = base_config['carbon_factors']['current']['electricity']

    def fake_load_config():
        config_copy = copy.deepcopy(base_config)
        config_copy['carbon_factors']['current'].pop('electricity', None)
        return config_copy

    monkeypatch.setattr(pathway_model, 'load_config', fake_load_config)

    modeler = PathwayModeler()

    assert modeler.elec_carbon == expected_electricity_factor, (
        "Fallback electricity carbon factor should align with authoritative config"
    )


def test_epc_anomaly_flagging():
    """
    Verify that EPC anomaly flagging works correctly.

    Test cases:
    1. Uninsulated solid wall + poor roof + EPC band D -> should flag
    2. Single glazed + EPC band C -> should flag
    3. Well-insulated + EPC band C -> should NOT flag

    """
    logger.info("=" * 60)
    logger.info("TEST: EPC Anomaly Flagging")
    logger.info("=" * 60)

    from src.cleaning.data_validator import flag_epc_anomalies

    # Create test dataset
    test_data = pd.DataFrame([
        # Case 1: Should be flagged - uninsulated + poor roof + EPC D
        {
            'LMK_KEY': 'ANOMALY_001',
            'wall_insulation_status': 'none',
            'roof_insulation_thickness_mm': 50,
            'CURRENT_ENERGY_RATING': 'D',
            'glazing_type': 'double',
            'wall_insulated': False,
            'floor_insulation_present': False,
        },
        # Case 2: Should be flagged - single glazed + EPC C
        {
            'LMK_KEY': 'ANOMALY_002',
            'wall_insulation_status': 'internal',
            'roof_insulation_thickness_mm': 200,
            'CURRENT_ENERGY_RATING': 'C',
            'glazing_type': 'single',
            'wall_insulated': True,
            'floor_insulation_present': True,
        },
        # Case 3: Should NOT be flagged - well insulated + EPC C
        {
            'LMK_KEY': 'NORMAL_001',
            'wall_insulation_status': 'external',
            'roof_insulation_thickness_mm': 300,
            'CURRENT_ENERGY_RATING': 'C',
            'glazing_type': 'double',
            'wall_insulated': True,
            'floor_insulation_present': True,
        },
        # Case 4: Should NOT be flagged - uninsulated but EPC F (consistent)
        {
            'LMK_KEY': 'NORMAL_002',
            'wall_insulation_status': 'none',
            'roof_insulation_thickness_mm': 25,
            'CURRENT_ENERGY_RATING': 'F',
            'glazing_type': 'single',
            'wall_insulated': False,
            'floor_insulation_present': False,
        },
    ])

    # Flag anomalies
    df_flagged = flag_epc_anomalies(test_data)

    # Check results
    errors = []

    # Case 1: Should be flagged
    case1 = df_flagged[df_flagged['LMK_KEY'] == 'ANOMALY_001']
    if len(case1) > 0 and not case1['is_epc_fabric_anomaly'].values[0]:
        errors.append("Case 1 (uninsulated + EPC D) should be flagged as anomaly")

    # Case 2: Should be flagged
    case2 = df_flagged[df_flagged['LMK_KEY'] == 'ANOMALY_002']
    if len(case2) > 0 and not case2['is_epc_fabric_anomaly'].values[0]:
        errors.append("Case 2 (single glazed + EPC C) should be flagged as anomaly")

    # Case 3: Should NOT be flagged
    case3 = df_flagged[df_flagged['LMK_KEY'] == 'NORMAL_001']
    if len(case3) > 0 and case3['is_epc_fabric_anomaly'].values[0]:
        errors.append("Case 3 (well insulated + EPC C) should NOT be flagged")

    # Case 4: Should NOT be flagged (consistent poor insulation + poor EPC)
    case4 = df_flagged[df_flagged['LMK_KEY'] == 'NORMAL_002']
    if len(case4) > 0 and case4['is_epc_fabric_anomaly'].values[0]:
        errors.append("Case 4 (uninsulated + EPC F) should NOT be flagged (consistent)")

    # Log results
    logger.info(f"Flagged properties: {df_flagged['is_epc_fabric_anomaly'].sum()}/{len(df_flagged)}")
    for _, row in df_flagged.iterrows():
        status = "FLAGGED" if row['is_epc_fabric_anomaly'] else "normal"
        logger.info(f"  {row['LMK_KEY']}: {status} ({row.get('anomaly_reason', '')})")

    if errors:
        for error in errors:
            logger.error(f"FAIL: {error}")
        assert False, "\n".join(errors)

    logger.info("PASS: All anomaly flagging tests passed!")


def test_package_and_pathway_ids():
    """
    Verify that all package and pathway IDs resolve to known definitions.

    """
    logger.info("=" * 60)
    logger.info("TEST: Package and Pathway ID Resolution")
    logger.info("=" * 60)

    from src.analysis.retrofit_packages import get_package_definitions, get_measure_catalogue
    from src.modeling.pathway_model import PATHWAYS

    errors = []

    # Check package definitions
    packages = get_package_definitions()
    catalogue = get_measure_catalogue()

    logger.info(f"Packages defined: {len(packages)}")
    for pkg_id, package in packages.items():
        logger.info(f"  {pkg_id}: {package.name}")

        # Check all measures in package exist in catalogue
        for measure_id in package.measures:
            if measure_id not in catalogue:
                errors.append(f"Package '{pkg_id}' references unknown measure '{measure_id}'")
            else:
                logger.info(f"    - {measure_id}: OK")

    # Check pathway definitions
    logger.info(f"\nPathways defined: {len(PATHWAYS)}")
    for pathway_id, pathway in PATHWAYS.items():
        logger.info(f"  {pathway_id}: {pathway.name}")

        # Check fabric_package reference
        if pathway.fabric_package != 'none' and pathway.fabric_package not in packages:
            errors.append(
                f"Pathway '{pathway_id}' references unknown package '{pathway.fabric_package}'"
            )

        # Check heat_source is valid
        valid_heat_sources = ['gas', 'hp', 'hn', 'hp+hn']
        if pathway.heat_source not in valid_heat_sources:
            errors.append(
                f"Pathway '{pathway_id}' has invalid heat_source '{pathway.heat_source}'"
            )

    # Expected IDs that should exist
    expected_packages = ['max_retrofit', 'loft_plus_rad', 'walls_plus_rad', 'value_package']
    expected_pathways = ['fabric_plus_hp_only', 'fabric_plus_hn_only', 'fabric_plus_hp_plus_hn']

    for pkg_id in expected_packages:
        if pkg_id not in packages:
            errors.append(f"Expected package '{pkg_id}' not found")

    for pathway_id in expected_pathways:
        if pathway_id not in PATHWAYS:
            errors.append(f"Expected pathway '{pathway_id}' not found")

    if errors:
        for error in errors:
            logger.error(f"FAIL: {error}")
        assert False, "\n".join(errors)

    logger.info("\nPASS: All package and pathway ID tests passed!")


def test_demand_uncertainty():
    """
    Verify that demand uncertainty calculations work correctly.

    """
    logger.info("=" * 60)
    logger.info("TEST: Demand Uncertainty Calculations")
    logger.info("=" * 60)

    from src.analysis.methodological_adjustments import apply_demand_uncertainty

    # Create test data
    test_data = pd.DataFrame([
        {
            'property_id': 'TEST_001',
            'annual_kwh_saving': 5000,
            'annual_bill_saving': 300,
            'co2_saving_tonnes': 1.0,
            'capex_per_home': 10000,
            'is_epc_fabric_anomaly': False,
        },
        {
            'property_id': 'TEST_002_ANOMALY',
            'annual_kwh_saving': 5000,
            'annual_bill_saving': 300,
            'co2_saving_tonnes': 1.0,
            'capex_per_home': 10000,
            'is_epc_fabric_anomaly': True,  # Should get wider uncertainty
        },
    ])

    # Apply uncertainty
    df_uncertain = apply_demand_uncertainty(
        test_data,
        demand_col='annual_kwh_saving',
        bill_col='annual_bill_saving',
        co2_col='co2_saving_tonnes',
        low=-0.20,
        high=0.20,
        anomaly_low=-0.30,
        anomaly_high=0.30
    )

    errors = []

    # Check normal property has ±20% range
    normal = df_uncertain[df_uncertain['property_id'] == 'TEST_001']
    if len(normal) > 0:
        baseline = normal['annual_kwh_saving_baseline'].values[0]
        low = normal['annual_kwh_saving_low'].values[0]
        high = normal['annual_kwh_saving_high'].values[0]

        expected_low = baseline * 0.80  # -20%
        expected_high = baseline * 1.20  # +20%

        if abs(low - expected_low) > 1:
            errors.append(f"Normal property low should be {expected_low}, got {low}")
        if abs(high - expected_high) > 1:
            errors.append(f"Normal property high should be {expected_high}, got {high}")

        logger.info(f"Normal property: {low:.0f} - {baseline:.0f} - {high:.0f} kWh")

    # Check anomaly property has ±30% range
    anomaly = df_uncertain[df_uncertain['property_id'] == 'TEST_002_ANOMALY']
    if len(anomaly) > 0:
        baseline = anomaly['annual_kwh_saving_baseline'].values[0]
        low = anomaly['annual_kwh_saving_low'].values[0]
        high = anomaly['annual_kwh_saving_high'].values[0]

        expected_low = baseline * 0.70  # -30%
        expected_high = baseline * 1.30  # +30%

        if abs(low - expected_low) > 1:
            errors.append(f"Anomaly property low should be {expected_low}, got {low}")
        if abs(high - expected_high) > 1:
            errors.append(f"Anomaly property high should be {expected_high}, got {high}")

        logger.info(f"Anomaly property: {low:.0f} - {baseline:.0f} - {high:.0f} kWh")

    # Check payback ranges exist
    if 'simple_payback_years_low' not in df_uncertain.columns:
        errors.append("Payback low column not created")
    if 'simple_payback_years_high' not in df_uncertain.columns:
        errors.append("Payback high column not created")

    if errors:
        for error in errors:
            logger.error(f"FAIL: {error}")
        assert False, "\n".join(errors)

    logger.info("PASS: All demand uncertainty tests passed!")


def run_all_tests():
    """Run all tests and report results."""
    logger.info("\n" + "=" * 70)
    logger.info("RUNNING ALL TESTS")
    logger.info("=" * 70 + "\n")

    tests = {
        'hybrid_cost_bug': test_hybrid_cost_bug_fix,
        'epc_anomaly_flagging': test_epc_anomaly_flagging,
        'package_pathway_ids': test_package_and_pathway_ids,
        'demand_uncertainty': test_demand_uncertainty,
    }

    results = {}
    for test_name, test_func in tests.items():
        try:
            test_func()
            results[test_name] = True
        except AssertionError as err:
            logger.error(f"FAIL: {test_name} -> {err}")
            results[test_name] = False

    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("TEST SUMMARY")
    logger.info("=" * 70)

    passed = sum(results.values())
    total = len(results)

    for test_name, passed_flag in results.items():
        status = "PASS" if passed_flag else "FAIL"
        logger.info(f"  {test_name}: {status}")

    logger.info(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        logger.info("\nALL TESTS PASSED!")
        return True
    else:
        logger.error(f"\n{total - passed} TEST(S) FAILED!")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
