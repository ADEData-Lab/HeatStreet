"""
Retrofit Packages Module

Defines individual retrofit measures and packages for heat decarbonization analysis.
Implements a measure catalogue, package definitions, and cost/savings calculations.

Key concepts:
- Measure: Individual intervention (e.g., loft insulation, radiator upsizing)
- Package: Combination of measures applied together
- Pathway: Package + heat technology (HP, HN, or both)

Outputs:
- retrofit_packages_by_property.parquet: Property-level package results
- retrofit_packages_summary.csv: Aggregated package statistics
- window_upgrade_comparison.csv: Double vs triple glazing comparison
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from loguru import logger

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import (
    load_config,
    get_cost_assumptions,
    get_measure_savings,
    get_financial_params,
    get_analysis_horizon_years,
    get_uncertainty_params,
    DATA_PROCESSED_DIR,
    DATA_OUTPUTS_DIR
)
from src.modeling.costing import CostCalculator


@dataclass
class Measure:
    """
    Represents a single retrofit measure.

    Attributes:
        measure_id: Unique identifier (e.g., 'loft_insulation')
        name: Human-readable name
        capex_per_home: Capital cost in GBP (can be fixed or calculated)
        annual_kwh_saving_pct: Percentage reduction in heating demand
        annual_kwh_saving_fixed: Fixed kWh saving (if not percentage-based)
        flow_temp_reduction_k: Reduction in required flow temperature (K)
        co2_saving_factor: Additional CO2 factor beyond energy savings
        applicability_check: Function to check if measure applies to property
    """
    measure_id: str
    name: str
    capex_per_home: float = 0.0
    annual_kwh_saving_pct: float = 0.0
    annual_kwh_saving_fixed: float = 0.0
    flow_temp_reduction_k: float = 0.0
    co2_saving_factor: float = 1.0  # Multiplier for CO2 savings
    requires_check: bool = False  # If True, applicability depends on property


# ============================================================================
# MEASURE CATALOGUE
# ============================================================================
# Central catalogue of all available retrofit measures with costs and savings

def get_measure_catalogue() -> Dict[str, Measure]:
    """
    Return the complete measure catalogue with costs and savings.

    Costs are from config.yaml and literature sources.
    Savings are percentage reductions in heating demand.

    Returns:
        Dictionary mapping measure_id to Measure objects
    """
    costs = get_cost_assumptions()
    savings = get_measure_savings()

    catalogue = {
        # ---- Loft/Roof Measures ----
        'loft_insulation': Measure(
            measure_id='loft_insulation',
            name='Loft Insulation Top-up (to 270mm)',
            capex_per_home=costs.get('loft_insulation_topup', 1200),
            annual_kwh_saving_pct=savings.get('loft_insulation_topup', {}).get('kwh_saving_pct', 0.15),
            flow_temp_reduction_k=savings.get('loft_insulation_topup', {}).get('flow_temp_reduction_k', 2),
            requires_check=True  # Only if roof insulation < 270mm
        ),

        # ---- Wall Measures ----
        'cavity_wall_insulation': Measure(
            measure_id='cavity_wall_insulation',
            name='Cavity Wall Insulation',
            capex_per_home=costs.get('cavity_wall_insulation', 2500),
            annual_kwh_saving_pct=savings.get('wall_insulation', {}).get('cavity_kwh_saving_pct', 0.20),
            flow_temp_reduction_k=savings.get('wall_insulation', {}).get('flow_temp_reduction_k', 5),
            requires_check=True  # Only if cavity walls and uninsulated
        ),

        'solid_wall_insulation_ewi': Measure(
            measure_id='solid_wall_insulation_ewi',
            name='External Wall Insulation (EWI)',
            capex_per_home=costs.get('solid_wall_insulation_ewi', 10000),
            annual_kwh_saving_pct=savings.get('wall_insulation', {}).get('solid_kwh_saving_pct', 0.30),
            flow_temp_reduction_k=savings.get('wall_insulation', {}).get('flow_temp_reduction_k', 5),
            requires_check=True  # Only if solid walls and uninsulated
        ),

        'solid_wall_insulation_iwi': Measure(
            measure_id='solid_wall_insulation_iwi',
            name='Internal Wall Insulation (IWI)',
            capex_per_home=costs.get('solid_wall_insulation_iwi', 14000),
            annual_kwh_saving_pct=savings.get('wall_insulation', {}).get('solid_kwh_saving_pct', 0.30),
            flow_temp_reduction_k=savings.get('wall_insulation', {}).get('flow_temp_reduction_k', 5),
            requires_check=True  # Only if solid walls and uninsulated
        ),

        # ---- Floor Measures ----
        'floor_insulation': Measure(
            measure_id='floor_insulation',
            name='Floor Insulation (Suspended Timber)',
            capex_per_home=costs.get('floor_insulation', 1500),
            annual_kwh_saving_pct=savings.get('floor_insulation', {}).get('kwh_saving_pct', 0.05),
            flow_temp_reduction_k=savings.get('floor_insulation', {}).get('flow_temp_reduction_k', 1),
            requires_check=True  # Only if no floor insulation
        ),

        # ---- Glazing Measures ----
        'double_glazing_upgrade': Measure(
            measure_id='double_glazing_upgrade',
            name='Double Glazing Upgrade (from single)',
            capex_per_home=costs.get('double_glazing_upgrade', 6000),
            annual_kwh_saving_pct=savings.get('double_glazing', {}).get('kwh_saving_pct', 0.10),
            flow_temp_reduction_k=savings.get('double_glazing', {}).get('flow_temp_reduction_k', 2),
            requires_check=True  # Only if single glazed
        ),

        'triple_glazing_upgrade': Measure(
            measure_id='triple_glazing_upgrade',
            name='Triple Glazing Upgrade (Danish standard)',
            capex_per_home=costs.get('triple_glazing_upgrade', 9000),
            annual_kwh_saving_pct=savings.get('triple_glazing', {}).get('kwh_saving_pct', 0.15),
            flow_temp_reduction_k=savings.get('triple_glazing', {}).get('flow_temp_reduction_k', 3),
            requires_check=True  # Applies to single or double glazed
        ),

        # ---- Airtightness ----
        'draught_proofing': Measure(
            measure_id='draught_proofing',
            name='Draught Proofing',
            capex_per_home=costs.get('draught_proofing', 500),
            annual_kwh_saving_pct=savings.get('draught_proofing', {}).get('kwh_saving_pct', 0.05),
            flow_temp_reduction_k=savings.get('draught_proofing', {}).get('flow_temp_reduction_k', 1),
            requires_check=False  # Assume all properties can benefit
        ),

        # ---- Emitter/Distribution ----
        'rad_upsizing': Measure(
            measure_id='rad_upsizing',
            name='Radiator Upsizing (for low-temp HP)',
            capex_per_home=costs.get('radiator_upsizing', 2500),
            annual_kwh_saving_pct=savings.get('radiator_upsizing', {}).get('kwh_saving_pct', 0.0),
            flow_temp_reduction_k=savings.get('radiator_upsizing', {}).get('flow_temp_reduction_k', 10),
            requires_check=False  # Part of HP readiness
        ),

        'hot_water_cylinder': Measure(
            measure_id='hot_water_cylinder',
            name='Hot Water Cylinder Installation',
            capex_per_home=costs.get('hot_water_cylinder', 1200),
            annual_kwh_saving_pct=0.0,  # Enables HP, not direct savings
            flow_temp_reduction_k=0,
            requires_check=False
        ),

        # ---- Electrical ----
        'electrical_upgrade': Measure(
            measure_id='electrical_upgrade',
            name='Electrical Supply Upgrade (60A to 100A)',
            capex_per_home=costs.get('electrical_upgrade', 1500),
            annual_kwh_saving_pct=0.0,  # Enables HP, not direct savings
            flow_temp_reduction_k=0,
            requires_check=False
        ),
    }

    return catalogue


@dataclass
class RetrofitPackage:
    """
    Represents a combination of retrofit measures.

    Attributes:
        package_id: Unique identifier
        name: Human-readable name
        description: What this package achieves
        measures: List of measure_ids included
    """
    package_id: str
    name: str
    description: str
    measures: List[str]

    def get_total_capex(self, measure_catalogue: Dict[str, Measure]) -> float:
        """Calculate total capital cost for the package."""
        total = 0.0
        for measure_id in self.measures:
            if measure_id in measure_catalogue:
                total += measure_catalogue[measure_id].capex_per_home
        return total

    def get_total_kwh_saving_pct(self, measure_catalogue: Dict[str, Measure]) -> float:
        """
        Calculate total kWh savings percentage.

        Note: Uses diminishing returns model - not simply additive.
        """
        remaining_demand = 1.0
        for measure_id in self.measures:
            if measure_id in measure_catalogue:
                saving_pct = measure_catalogue[measure_id].annual_kwh_saving_pct
                remaining_demand *= (1 - saving_pct)
        return 1 - remaining_demand

    def get_total_flow_temp_reduction(self, measure_catalogue: Dict[str, Measure]) -> float:
        """Calculate total flow temperature reduction from fabric measures."""
        total = 0.0
        for measure_id in self.measures:
            if measure_id in measure_catalogue:
                total += measure_catalogue[measure_id].flow_temp_reduction_k
        return total


# ============================================================================
# PACKAGE DEFINITIONS
# ============================================================================

def get_package_definitions() -> Dict[str, RetrofitPackage]:
    """
    Return all defined retrofit packages.

    Packages:
    - Single measures (individual options)
    - max_retrofit: "Rolls Royce" package with all reasonable measures
    - loft_plus_rad: Simple two-measure package
    - walls_plus_rad: Wall focus two-measure package
    - value_package: Best value for money (high savings per £)

    Returns:
        Dictionary mapping package_id to RetrofitPackage objects
    """
    packages = {
        # ---- Single Measure Packages ----
        'loft_only': RetrofitPackage(
            package_id='loft_only',
            name='Loft Insulation Only',
            description='Top-up loft insulation to 270mm',
            measures=['loft_insulation']
        ),

        'wall_only': RetrofitPackage(
            package_id='wall_only',
            name='Wall Insulation Only',
            description='Wall insulation (cavity fill or EWI for solid)',
            measures=['solid_wall_insulation_ewi']  # Default to solid for Edwardian
        ),

        'glazing_only': RetrofitPackage(
            package_id='glazing_only',
            name='Glazing Upgrade Only',
            description='Upgrade to triple glazing',
            measures=['triple_glazing_upgrade']
        ),

        'rad_upsizing_only': RetrofitPackage(
            package_id='rad_upsizing_only',
            name='Radiator Upsizing Only',
            description='Upsize radiators for low-temperature heat pump',
            measures=['rad_upsizing']
        ),

        # ---- Two-Measure Packages ----
        'loft_plus_rad': RetrofitPackage(
            package_id='loft_plus_rad',
            name='Loft + Radiators',
            description='Loft insulation top-up plus radiator upsizing',
            measures=['loft_insulation', 'rad_upsizing']
        ),

        'walls_plus_rad': RetrofitPackage(
            package_id='walls_plus_rad',
            name='Walls + Radiators',
            description='Wall insulation plus radiator upsizing for HP compatibility',
            measures=['solid_wall_insulation_ewi', 'rad_upsizing']
        ),

        'loft_plus_draught': RetrofitPackage(
            package_id='loft_plus_draught',
            name='Loft + Draught Proofing',
            description='Low-cost fabric improvements',
            measures=['loft_insulation', 'draught_proofing']
        ),

        # ---- Value Package (High savings per £) ----
        'value_package': RetrofitPackage(
            package_id='value_package',
            name='Value Sweet Spot',
            description='High savings per £ without full Rolls Royce investment. '
                        'Loft, draught proofing, and radiator upsizing.',
            measures=['loft_insulation', 'draught_proofing', 'rad_upsizing']
        ),

        # ---- Full Fabric Package ----
        'fabric_full': RetrofitPackage(
            package_id='fabric_full',
            name='Full Fabric Upgrade',
            description='Complete fabric improvements without heat technology',
            measures=[
                'loft_insulation',
                'solid_wall_insulation_ewi',
                'floor_insulation',
                'triple_glazing_upgrade',
                'draught_proofing'
            ]
        ),

        # ---- Max Retrofit / Rolls Royce Package ----
        'max_retrofit': RetrofitPackage(
            package_id='max_retrofit',
            name='Maximum Retrofit (Rolls Royce)',
            description='All reasonable fabric and emitter measures. '
                        'Loft, walls (EWI), floor, triple glazing, draught proofing, '
                        'radiator upsizing, hot water cylinder, electrical upgrade.',
            measures=[
                'loft_insulation',
                'solid_wall_insulation_ewi',
                'floor_insulation',
                'triple_glazing_upgrade',
                'draught_proofing',
                'rad_upsizing',
                'hot_water_cylinder',
                'electrical_upgrade'
            ]
        ),
    }

    return packages


class RetrofitPackageAnalyzer:
    """
    Analyzes retrofit packages for properties.

    Calculates costs, savings, and payback periods for each package
    at property level and aggregated.
    """

    def __init__(self, output_dir: Optional[Path] = None, cost_calculator: Optional[CostCalculator] = None):
        """Initialize the analyzer with measure catalogue and packages."""
        self.config = load_config()
        self.catalogue = get_measure_catalogue()
        self.packages = get_package_definitions()
        self.output_dir = output_dir or DATA_OUTPUTS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Load financial parameters
        self.financial = get_financial_params()
        self.discount_rate = self.financial.get('discount_rate', 0.035)
        self.analysis_horizon_years = get_analysis_horizon_years()

        # Load energy prices
        self.energy_prices = self.config.get('energy_prices', {}).get('current', {})
        self.gas_price = self.energy_prices.get('gas', 0.0624)
        self.elec_price = self.energy_prices.get('electricity', 0.245)

        # Load carbon factors
        self.carbon_factors = self.config.get('carbon_factors', {}).get('current', {})
        self.gas_carbon = self.carbon_factors.get('gas', 0.183)
        self.cost_calculator = cost_calculator

        logger.info(f"Initialized RetrofitPackageAnalyzer with {len(self.packages)} packages")

    def calculate_property_package_results(
        self,
        property_data: pd.Series,
        package: RetrofitPackage
    ) -> Dict:
        """
        Calculate package results for a single property.

        Args:
            property_data: Row from properties DataFrame
            package: RetrofitPackage to evaluate

        Returns:
            Dictionary with metrics for this property and package
        """
        # Get property characteristics
        floor_area = property_data.get('TOTAL_FLOOR_AREA', 100)
        energy_intensity = property_data.get('ENERGY_CONSUMPTION_CURRENT', 150)  # kWh/m²/year
        annual_energy = energy_intensity * floor_area  # kWh/year

        # Calculate package metrics
        total_capex = 0.0
        total_saving_pct = 0.0
        remaining_demand = 1.0
        total_flow_temp_reduction = 0.0

        applicable_measures = []

        for measure_id in package.measures:
            if measure_id not in self.catalogue:
                continue

            measure = self.catalogue[measure_id]

            # Check applicability based on property characteristics
            if self._is_measure_applicable(measure, property_data):
                applicable_measures.append(measure_id)
                total_capex += self._measure_cost(measure_id, property_data)
                remaining_demand *= (1 - measure.annual_kwh_saving_pct)
                total_flow_temp_reduction += measure.flow_temp_reduction_k

        total_saving_pct = 1 - remaining_demand
        annual_kwh_saving = annual_energy * total_saving_pct
        annual_bill_saving = annual_kwh_saving * self.gas_price
        co2_saving_tonnes = (annual_kwh_saving * self.gas_carbon) / 1000  # kg to tonnes

        # Calculate payback
        if annual_bill_saving > 0:
            simple_payback_years = total_capex / annual_bill_saving
        else:
            simple_payback_years = np.inf

        # Calculate discounted payback
        discounted_payback_years = self._calculate_discounted_payback(
            total_capex, annual_bill_saving
        )

        return {
            'property_id': property_data.get('LMK_KEY', 'unknown'),
            'package_id': package.package_id,
            'applicable_measures': ','.join(applicable_measures),
            'n_measures_applied': len(applicable_measures),
            'capex_per_home': total_capex,
            'annual_kwh_saving': annual_kwh_saving,
            'annual_kwh_saving_pct': total_saving_pct * 100,
            'annual_bill_saving': annual_bill_saving,
            'co2_saving_tonnes': co2_saving_tonnes,
            'flow_temp_reduction_k': total_flow_temp_reduction,
            'simple_payback_years': simple_payback_years,
            'discounted_payback_years': discounted_payback_years
        }

    def _measure_cost(self, measure_id: str, property_data: pd.Series) -> float:
        """Return measure cost using shared costing rules when available."""

        if not self.cost_calculator:
            return self.catalogue[measure_id].capex_per_home

        alias_map = {
            'rad_upsizing': 'radiator_upsizing',
            'double_glazing_upgrade': 'double_glazing',
            'triple_glazing_upgrade': 'triple_glazing',
        }

        measure_name = alias_map.get(measure_id, measure_id)
        cost, _ = self.cost_calculator.measure_cost(measure_name, property_data)
        return cost

    def _is_measure_applicable(self, measure: Measure, property_data: pd.Series) -> bool:
        """
        Check if a measure is applicable to a property.

        Args:
            measure: Measure to check
            property_data: Property characteristics

        Returns:
            True if measure should be applied
        """
        if not measure.requires_check:
            return True

        measure_id = measure.measure_id

        # Loft insulation - check if roof insulation is below threshold
        if measure_id == 'loft_insulation':
            roof_thickness = property_data.get('roof_insulation_thickness_mm', np.nan)
            if pd.notna(roof_thickness) and roof_thickness >= 270:
                return False
            return True

        # Cavity wall insulation - check wall type and insulation status
        if measure_id == 'cavity_wall_insulation':
            wall_type = property_data.get('wall_type', '')
            wall_insulated = property_data.get('wall_insulated', False)
            return 'cavity' in str(wall_type).lower() and not wall_insulated

        # Solid wall insulation - check wall type and insulation status
        if measure_id in ['solid_wall_insulation_ewi', 'solid_wall_insulation_iwi']:
            wall_type = property_data.get('wall_type', '')
            wall_insulated = property_data.get('wall_insulated', False)
            is_solid = any(t in str(wall_type).lower() for t in ['solid', 'brick', 'stone'])
            return is_solid and not wall_insulated

        # Floor insulation - check if no floor insulation
        if measure_id == 'floor_insulation':
            floor_insulation = property_data.get('floor_insulation_present', False)
            return not floor_insulation

        # Glazing upgrades - check glazing type
        if measure_id == 'double_glazing_upgrade':
            glazing = property_data.get('glazing_type', '')
            return 'single' in str(glazing).lower()

        if measure_id == 'triple_glazing_upgrade':
            glazing = property_data.get('glazing_type', '')
            return glazing in ['single', 'double', 'mixed']

        return True

    def _calculate_discounted_payback(
        self,
        capex: float,
        annual_saving: float,
        max_years: int = 50
    ) -> float:
        """
        Calculate discounted payback period.

        Args:
            capex: Upfront capital cost
            annual_saving: Annual bill savings
            max_years: Maximum years to calculate

        Returns:
            Discounted payback in years (inf if not achieved)
        """
        if annual_saving <= 0 or capex <= 0:
            return np.inf

        cumulative_savings = 0.0
        for year in range(1, max_years + 1):
            discounted_saving = annual_saving / ((1 + self.discount_rate) ** year)
            cumulative_savings += discounted_saving
            if cumulative_savings >= capex:
                return year

        return np.inf

    def analyze_all_packages(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Analyze all packages for all properties.

        Args:
            df: Properties DataFrame

        Returns:
            DataFrame with results for each property × package combination
        """
        logger.info(f"Analyzing {len(self.packages)} packages for {len(df):,} properties...")

        results = []

        for idx, (_, property_data) in enumerate(df.iterrows()):
            if idx % 1000 == 0:
                logger.info(f"  Processing property {idx + 1:,}/{len(df):,}...")

            for package_id, package in self.packages.items():
                result = self.calculate_property_package_results(property_data, package)
                results.append(result)

        results_df = pd.DataFrame(results)
        logger.info(f"Generated {len(results_df):,} property-package results")

        return results_df

    def generate_package_summary(self, results_df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate summary statistics for each package.

        Args:
            results_df: Property-level results from analyze_all_packages

        Returns:
            Summary DataFrame with one row per package
        """
        logger.info("Generating package summary...")

        summary_rows = []

        for package_id in results_df['package_id'].unique():
            pkg_results = results_df[results_df['package_id'] == package_id]

            # Filter out infinite paybacks for mean calculations
            finite_paybacks = pkg_results[np.isfinite(pkg_results['simple_payback_years'])]

            summary = {
                'package_id': package_id,
                'package_name': self.packages[package_id].name if package_id in self.packages else '',
                'n_properties': len(pkg_results),

                # Costs
                'capex_per_home_mean': pkg_results['capex_per_home'].mean(),
                'capex_per_home_median': pkg_results['capex_per_home'].median(),
                'capex_per_home_std': pkg_results['capex_per_home'].std(),

                # Energy savings
                'annual_kwh_saving_mean': pkg_results['annual_kwh_saving'].mean(),
                'annual_kwh_saving_pct_mean': pkg_results['annual_kwh_saving_pct'].mean(),

                # Bill savings
                'annual_bill_saving_mean': pkg_results['annual_bill_saving'].mean(),
                'annual_bill_saving_median': pkg_results['annual_bill_saving'].median(),

                # CO2
                'co2_saving_tonnes_mean': pkg_results['co2_saving_tonnes'].mean(),
                'co2_saving_tonnes_total': pkg_results['co2_saving_tonnes'].sum(),

                # Payback
                'simple_payback_median': finite_paybacks['simple_payback_years'].median()
                    if len(finite_paybacks) > 0 else np.nan,
                'simple_payback_mean': finite_paybacks['simple_payback_years'].mean()
                    if len(finite_paybacks) > 0 else np.nan,
                'discounted_payback_median': finite_paybacks[
                    np.isfinite(finite_paybacks['discounted_payback_years'])
                ]['discounted_payback_years'].median()
                    if len(finite_paybacks) > 0 else np.nan,

                # Measures
                'avg_measures_applied': pkg_results['n_measures_applied'].mean(),
                'flow_temp_reduction_mean': pkg_results['flow_temp_reduction_k'].mean(),

                # Cost effectiveness
                'gbp_per_tonne_co2': (
                    pkg_results['capex_per_home'].sum() /
                    (pkg_results['co2_saving_tonnes'].sum() * self.analysis_horizon_years)
                ) if pkg_results['co2_saving_tonnes'].sum() > 0 else np.nan,
            }

            summary_rows.append(summary)

        summary_df = pd.DataFrame(summary_rows)
        summary_df = summary_df.sort_values('simple_payback_median')

        return summary_df

    def generate_window_comparison(self) -> pd.DataFrame:
        """
        Generate comparison table for double vs triple glazing.

        Returns:
            DataFrame comparing glazing options
        """
        logger.info("Generating window upgrade comparison...")

        double = self.catalogue.get('double_glazing_upgrade')
        triple = self.catalogue.get('triple_glazing_upgrade')

        if not double or not triple:
            logger.warning("Glazing measures not found in catalogue")
            return pd.DataFrame()

        # Calculate for typical property (100m², 15000 kWh/year heating)
        typical_heating_kwh = 15000

        comparison = pd.DataFrame([
            {
                'measure_id': 'double_glazing_upgrade',
                'name': double.name,
                'capex_per_home': double.capex_per_home,
                'annual_kwh_saving': typical_heating_kwh * double.annual_kwh_saving_pct,
                'annual_kwh_saving_pct': double.annual_kwh_saving_pct * 100,
                'annual_bill_saving': typical_heating_kwh * double.annual_kwh_saving_pct * self.gas_price,
                'flow_temp_reduction_k': double.flow_temp_reduction_k,
                'simple_payback_years': double.capex_per_home / (
                    typical_heating_kwh * double.annual_kwh_saving_pct * self.gas_price
                ) if double.annual_kwh_saving_pct > 0 else np.inf
            },
            {
                'measure_id': 'triple_glazing_upgrade',
                'name': triple.name,
                'capex_per_home': triple.capex_per_home,
                'annual_kwh_saving': typical_heating_kwh * triple.annual_kwh_saving_pct,
                'annual_kwh_saving_pct': triple.annual_kwh_saving_pct * 100,
                'annual_bill_saving': typical_heating_kwh * triple.annual_kwh_saving_pct * self.gas_price,
                'flow_temp_reduction_k': triple.flow_temp_reduction_k,
                'simple_payback_years': triple.capex_per_home / (
                    typical_heating_kwh * triple.annual_kwh_saving_pct * self.gas_price
                ) if triple.annual_kwh_saving_pct > 0 else np.inf
            }
        ])

        # Add marginal benefit of triple over double
        comparison.loc[2] = {
            'measure_id': 'triple_vs_double_marginal',
            'name': 'Marginal benefit: Triple over Double',
            'capex_per_home': triple.capex_per_home - double.capex_per_home,
            'annual_kwh_saving': (triple.annual_kwh_saving_pct - double.annual_kwh_saving_pct) * typical_heating_kwh,
            'annual_kwh_saving_pct': (triple.annual_kwh_saving_pct - double.annual_kwh_saving_pct) * 100,
            'annual_bill_saving': (triple.annual_kwh_saving_pct - double.annual_kwh_saving_pct) * typical_heating_kwh * self.gas_price,
            'flow_temp_reduction_k': triple.flow_temp_reduction_k - double.flow_temp_reduction_k,
            'simple_payback_years': (triple.capex_per_home - double.capex_per_home) / (
                (triple.annual_kwh_saving_pct - double.annual_kwh_saving_pct) * typical_heating_kwh * self.gas_price
            ) if (triple.annual_kwh_saving_pct - double.annual_kwh_saving_pct) > 0 else np.inf
        }

        return comparison

    def export_results(
        self,
        results_df: pd.DataFrame,
        summary_df: pd.DataFrame
    ) -> Tuple[Path, Path]:
        """
        Export analysis results to files.

        Args:
            results_df: Property-level results
            summary_df: Package summary

        Returns:
            Tuple of (property_results_path, summary_path)
        """
        # Export property-level results
        property_path = self.output_dir / "retrofit_packages_by_property.parquet"
        results_df.to_parquet(property_path, index=False)
        logger.info(f"Saved property-level results to {property_path}")

        # Also save CSV for easier inspection
        csv_path = self.output_dir / "retrofit_packages_by_property.csv"
        # Sample for CSV to keep file size manageable
        if len(results_df) > 50000:
            results_df.sample(50000).to_csv(csv_path, index=False)
            logger.info(f"Saved sampled CSV (50k rows) to {csv_path}")
        else:
            results_df.to_csv(csv_path, index=False)

        # Export summary
        summary_path = self.output_dir / "retrofit_packages_summary.csv"
        summary_df.to_csv(summary_path, index=False)
        logger.info(f"Saved package summary to {summary_path}")

        # Export window comparison
        window_comparison = self.generate_window_comparison()
        window_path = self.output_dir / "window_upgrade_comparison.csv"
        window_comparison.to_csv(window_path, index=False)
        logger.info(f"Saved window comparison to {window_path}")

        return property_path, summary_path

    def run_full_analysis(self, df: pd.DataFrame) -> Dict:
        """
        Run complete retrofit package analysis.

        Args:
            df: Properties DataFrame

        Returns:
            Dictionary with all results
        """
        logger.info("Running full retrofit package analysis...")

        # Analyze all packages
        results_df = self.analyze_all_packages(df)

        # Generate summary
        summary_df = self.generate_package_summary(results_df)

        # Export results
        self.export_results(results_df, summary_df)

        return {
            'results': results_df,
            'summary': summary_df
        }


def main():
    """Main execution function."""
    logger.info("Starting retrofit package analysis...")

    # Load validated data
    input_file = DATA_PROCESSED_DIR / "epc_validated.parquet"

    if not input_file.exists():
        input_file = DATA_PROCESSED_DIR / "epc_validated.csv"
        if not input_file.exists():
            logger.error(f"Input file not found")
            return

    logger.info(f"Loading data from: {input_file}")
    if input_file.suffix == '.parquet':
        df = pd.read_parquet(input_file)
    else:
        df = pd.read_csv(input_file, low_memory=False)

    # Run analysis
    analyzer = RetrofitPackageAnalyzer()
    results = analyzer.run_full_analysis(df)

    # Log summary
    logger.info("\nRetrofit Package Analysis Summary:")
    logger.info(f"Properties analyzed: {len(df):,}")
    logger.info(f"Packages analyzed: {len(analyzer.packages)}")

    if 'summary' in results:
        logger.info("\nTop packages by payback:")
        top_packages = results['summary'].head(5)
        for _, row in top_packages.iterrows():
            logger.info(
                f"  {row['package_id']}: "
                f"£{row['capex_per_home_mean']:,.0f} capex, "
                f"£{row['annual_bill_saving_mean']:,.0f}/yr savings, "
                f"{row['simple_payback_median']:.1f}yr payback"
            )

    logger.info("Retrofit package analysis complete!")


if __name__ == "__main__":
    main()
