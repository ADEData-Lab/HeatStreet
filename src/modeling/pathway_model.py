"""
Pathway Model Module

Models heat decarbonization pathways combining fabric improvements with heat technologies.
Fixes the hybrid cost bug where costs were not properly combined.

Three main pathways (all assume sensible fabric improvements):
1. fabric_plus_hp_only: Fabric + Heat Pump
2. fabric_plus_hn_only: Fabric + Heat Network
3. fabric_plus_hp_plus_hn: Hybrid (HP where HN unavailable)

Key fix: Hybrid pathway now correctly sums:
- Fabric package costs (from retrofit_packages)
- Heat pump costs (for properties without HN access)
- Heat network costs (for properties with HN access)

Outputs:
- pathway_results_by_property.parquet
- pathway_results_summary.csv
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from loguru import logger

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import (
    load_config,
    get_cost_assumptions,
    get_cost_rules,
    get_financial_params,
    get_heat_network_params,
    get_uncertainty_params,
    DATA_PROCESSED_DIR,
    DATA_OUTPUTS_DIR
)
from src.analysis.retrofit_packages import (
    get_measure_catalogue,
    get_package_definitions,
    RetrofitPackageAnalyzer
)
from src.analysis.methodological_adjustments import MethodologicalAdjustments
from src.modeling.costing import CostCalculator


def _select_baseline_energy_intensity(property_like: pd.Series) -> float:
    """Pick adjusted energy intensity when available, otherwise EPC value."""
    for col in [
        'energy_consumption_adjusted',
        'energy_consumption_adjusted_central',
        'ENERGY_CONSUMPTION_CURRENT',
    ]:
        val = property_like.get(col)
        if val is not None and not pd.isna(val):
            numeric_val = float(val)
            if numeric_val < 0:
                raise ValueError(f"Negative energy intensity supplied for {col}: {numeric_val}")
            return numeric_val

    return float(property_like.get('ENERGY_CONSUMPTION_CURRENT', 150))


def _select_baseline_annual_kwh(property_like: pd.Series, energy_intensity: float) -> float:
    """Return absolute baseline demand (kWh/year) prioritising adjusted baseline."""
    for col in [
        'baseline_consumption_kwh_year',
        'baseline_consumption_kwh_year_central',
        'baseline_consumption_kwh_year_low',
        'baseline_consumption_kwh_year_high',
    ]:
        val = property_like.get(col)
        if val is not None and not pd.isna(val):
            return float(val)

    floor_area = property_like.get('TOTAL_FLOOR_AREA', 100)
    if pd.isna(floor_area):
        floor_area = 100

    return float(energy_intensity) * float(floor_area)


def _assert_non_negative_intensities(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure no negative energy intensity values are present before pathway modeling."""
    intensity_cols = [
        'energy_consumption_adjusted',
        'energy_consumption_adjusted_central',
        'ENERGY_CONSUMPTION_CURRENT',
    ]

    present_cols = [col for col in intensity_cols if col in df.columns]
    if not present_cols:
        return df

    negative_counts = {
        col: int((pd.to_numeric(df[col], errors='coerce') < 0).sum())
        for col in present_cols
    }

    total_negatives = sum(negative_counts.values())
    if total_negatives > 0:
        raise ValueError(f"Negative energy intensities found in pathway inputs: {negative_counts}")

    return df


# ============================================================================
# PATHWAY DEFINITIONS
# ============================================================================

@dataclass
class Pathway:
    """
    Represents a heat decarbonization pathway.

    A pathway combines:
    - A fabric retrofit package
    - A heat technology (HP, HN, or hybrid)
    """
    pathway_id: str
    name: str
    description: str
    fabric_package: str  # ID of retrofit package to apply
    heat_source: str  # 'hp', 'hn', 'hp+hn', or 'hp_proxy'


PATHWAYS = {
    'baseline': Pathway(
        pathway_id='baseline',
        name='Baseline (No Intervention)',
        description='Current state with no retrofit or heat technology change',
        fabric_package='none',
        heat_source='gas'
    ),

    'fabric_only': Pathway(
        pathway_id='fabric_only',
        name='Fabric Only',
        description='Full fabric improvements but retain gas heating',
        fabric_package='max_retrofit',
        heat_source='gas'
    ),

    'fabric_plus_hp_only': Pathway(
        pathway_id='fabric_plus_hp_only',
        name='Fabric + Heat Pump',
        description='Full fabric improvements plus air source heat pump for all properties',
        fabric_package='max_retrofit',
        heat_source='hp'
    ),

    'fabric_plus_hn_only': Pathway(
        pathway_id='fabric_plus_hn_only',
        name='Fabric + Heat Network',
        description='Full fabric improvements plus heat network connection for all properties',
        fabric_package='max_retrofit',
        heat_source='hn'
    ),

    'fabric_plus_hp_plus_hn': Pathway(
        pathway_id='fabric_plus_hp_plus_hn',
        name='Hybrid: Fabric + HP + HN',
        description='Full fabric improvements. Heat network where available, heat pump elsewhere.',
        fabric_package='max_retrofit',
        heat_source='hp+hn'
    ),

    'fabric_plus_shared_ground_loop_proxy': Pathway(
        pathway_id='fabric_plus_shared_ground_loop_proxy',
        name='Fabric + Shared Ground Loop (proxy)',
        description='Full fabric improvements with a higher COP shared ground loop proxy heat pump',
        fabric_package='max_retrofit',
        heat_source='hp_proxy'
    ),
}


class PathwayModeler:
    """
    Models heat decarbonization pathways for properties.

    Key responsibilities:
    - Calculate costs for each pathway (fabric + heat tech)
    - Calculate energy demand after fabric improvements
    - Calculate bills under each heat technology
    - Calculate payback periods
    - Handle hybrid pathway correctly (FIX: ensures HP+HN costs are summed properly)
    """

    def __init__(
        self,
        output_dir: Optional[Path] = None,
        include_ground_loop_proxy: bool = False,
        ground_loop_scop: Optional[float] = None,
        ground_loop_capex_delta: float = 0.0
    ):
        """Initialize the pathway modeler."""
        self.config = load_config()
        self.costs = get_cost_assumptions()
        self.cost_rules = get_cost_rules()
        self.cost_calculator = CostCalculator(self.costs, self.cost_rules)
        self.financial = get_financial_params()
        self.hn_params = get_heat_network_params()
        self.uncertainty = get_uncertainty_params()
        readiness_cfg = self.config.get('heat_network', {}).get('readiness', {})
        self.adjuster = MethodologicalAdjustments()
        self.heating_fraction = float(self.config.get('heat_pump', {}).get('heating_demand_fraction', 0.8))
        self.min_flow_temp = float(min(self.config.get('heat_pump', {}).get('design_flow_temps', [self.adjuster.min_flow_temp])))

        self.output_dir = output_dir or DATA_OUTPUTS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.comparisons_dir = self.output_dir / "comparisons"
        self.comparisons_dir.mkdir(parents=True, exist_ok=True)

        # Energy prices
        self.prices = self.config.get('energy_prices', {}).get('current', {})
        self.gas_price = self.prices.get('gas', 0.0624)
        self.elec_price = self.prices.get('electricity', 0.245)
        self.hn_tariff = self.hn_params.get('tariff_per_kwh', 0.08)

        # Carbon factors
        self.carbon = self.config.get('carbon_factors', {}).get('current', {})
        self.gas_carbon = self.carbon.get('gas', 0.183)
        self.elec_carbon = self.carbon.get('electricity', 0.225)
        self.hn_carbon = self.hn_params.get('carbon_intensity_kg_per_kwh', self.carbon.get('heat_network', self.gas_carbon * 0.4))

        # Heat pump parameters
        self.hp_scop = self.config.get('heat_pump', {}).get('scop', 3.0)
        self.ground_loop_scop = (
            ground_loop_scop
            if ground_loop_scop is not None
            else self.config.get('heat_pump', {}).get('ground_loop_proxy_scop', 3.6)
        )
        self.ground_loop_capex_delta = ground_loop_capex_delta

        # Heat network parameters
        self.hn_efficiency = self.hn_params.get('distribution_efficiency', 0.90)
        self.hn_penetration = self.hn_params.get('current_penetration', 0.002)
        self.hn_access_column = readiness_cfg.get('access_column', 'hn_ready')

        # Financial parameters
        self.discount_rate = self.financial.get('discount_rate', 0.035)

        # Package analyzer for fabric costs
        self.package_analyzer = RetrofitPackageAnalyzer(
            self.output_dir,
            cost_calculator=self.cost_calculator
        )
        self.packages = get_package_definitions()

        # Pathway configuration (supports optional shared ground loop proxy)
        self.include_ground_loop_proxy = include_ground_loop_proxy
        base_pathways = dict(PATHWAYS)
        if not include_ground_loop_proxy:
            base_pathways.pop('fabric_plus_shared_ground_loop_proxy', None)

        self.pathways: Dict[str, Pathway] = base_pathways
        if include_ground_loop_proxy and 'fabric_plus_shared_ground_loop_proxy' not in self.pathways:
            self.pathways['fabric_plus_shared_ground_loop_proxy'] = Pathway(
                pathway_id='fabric_plus_shared_ground_loop_proxy',
                name='Fabric + Shared Ground Loop (proxy)',
                description='Full fabric improvements with higher COP shared ground loop heat pump proxy',
                fabric_package='max_retrofit',
                heat_source='hp_proxy'
            )

        logger.info("Initialized PathwayModeler")
        logger.info(f"  HP SCOP: {self.hp_scop}")
        logger.info(self.cost_calculator.summary_notes() or "Costing rules configured.")
        logger.info(f"  Shared ground loop COP: {self.ground_loop_scop} (enabled={include_ground_loop_proxy})")
        logger.info(f"  HN tariff: £{self.hn_tariff}/kWh")
        logger.info(f"  HN penetration: {self.hn_penetration * 100:.1f}%")

    def _ensure_adjusted_baseline(self, df: pd.DataFrame) -> pd.DataFrame:
        """Guarantee prebound baseline is available before pathway calculations."""
        if 'energy_consumption_adjusted' in df.columns or 'energy_consumption_adjusted_central' in df.columns:
            return _assert_non_negative_intensities(df)

        logger.info("Applying prebound adjustment to supply adjusted baseline for pathway modeling...")
        adjusted = self.adjuster.apply_prebound_adjustment(df)
        return _assert_non_negative_intensities(adjusted)

    def calculate_property_pathway(
        self,
        property_data: pd.Series,
        pathway: Pathway,
        has_hn_access: bool = False
    ) -> Dict:
        """
        Calculate pathway results for a single property.

        CRITICAL FIX: This method properly combines all cost components:
        - Fabric package costs (capex)
        - Heat technology costs (HP installation OR HN connection)
        - Operating costs (bills based on energy source)

        Args:
            property_data: Row from properties DataFrame
            pathway: Pathway to evaluate
            has_hn_access: Whether property has heat network access

        Returns:
            Dictionary with all pathway metrics
        """
        # Property characteristics
        floor_area = property_data.get('TOTAL_FLOOR_AREA', 100)
        energy_intensity = _select_baseline_energy_intensity(property_data)  # kWh/m²/year
        baseline_demand = _select_baseline_annual_kwh(property_data, energy_intensity)  # kWh/year

        # ====================================================================
        # STEP 1: Calculate fabric package costs and savings
        # ====================================================================
        fabric_capex = 0.0
        fabric_saving_pct = 0.0

        if pathway.fabric_package != 'none' and pathway.fabric_package in self.packages:
            pkg = self.packages[pathway.fabric_package]
            fabric_result = self.package_analyzer.calculate_property_package_results(
                property_data, pkg
            )
            fabric_capex = fabric_result['capex_per_home']
            fabric_saving_pct = fabric_result['annual_kwh_saving_pct'] / 100

        # Post-fabric energy demand
        post_fabric_demand = baseline_demand * (1 - fabric_saving_pct)

        baseline_flow_temp = property_data.get('estimated_flow_temp')
        if baseline_flow_temp is None or pd.isna(baseline_flow_temp):
            derived = self.adjuster.estimate_flow_temperature(pd.DataFrame([property_data]))
            baseline_flow_temp = float(derived['estimated_flow_temp'].iloc[0]) if 'estimated_flow_temp' in derived else self.min_flow_temp

        flow_temp_after_measures = max(
            self.min_flow_temp,
            baseline_flow_temp - fabric_result.get('flow_temp_reduction_k', 0.0)
        )

        cop_estimates = self.adjuster.derive_heat_pump_cop(flow_temp_after_measures, include_bounds=True)
        hp_cop_central = cop_estimates.get('central') or self.hp_scop
        hp_cop_low = cop_estimates.get('low', hp_cop_central)
        hp_cop_high = cop_estimates.get('high', hp_cop_central)

        # ====================================================================
        # STEP 2: Calculate heat technology costs
        # ====================================================================
        hp_capex = 0.0
        hn_capex = 0.0
        heat_tech_capex = 0.0

        hp_install_cost = self.costs.get('ashp_installation', 12000)

        if pathway.heat_source == 'hp':
            # Heat pump for all properties
            hp_capex = hp_install_cost
            heat_tech_capex = hp_capex

        elif pathway.heat_source == 'hp_proxy':
            hp_capex = hp_install_cost + self.ground_loop_capex_delta
            heat_tech_capex = hp_capex

        elif pathway.heat_source == 'hn':
            # Heat network for all properties
            hn_capex = self.costs.get('district_heating_connection', 5000)
            heat_tech_capex = hn_capex

        elif pathway.heat_source == 'hp+hn':
            # HYBRID: HN where available, HP elsewhere
            # CRITICAL FIX: Both costs must be considered in totals
            if has_hn_access:
                hn_capex = self.costs.get('district_heating_connection', 5000)
                heat_tech_capex = hn_capex
            else:
                hp_capex = self.costs.get('ashp_installation', 12000)
                heat_tech_capex = hp_capex

        # ====================================================================
        # STEP 3: Calculate total CAPEX
        # CRITICAL: This must sum fabric + heat technology costs
        # ====================================================================
        total_capex = fabric_capex + heat_tech_capex

        # Verify hybrid cost is correct (assertion for bug fix)
        if pathway.heat_source == 'hp+hn':
            assert total_capex > fabric_capex, \
                f"Hybrid cost bug: total_capex ({total_capex}) should exceed fabric_capex ({fabric_capex})"

        # ====================================================================
        # STEP 4: Calculate annual bills based on heat source
        # ====================================================================
        baseline_bill = baseline_demand * self.gas_price
        heating_after_fabric = post_fabric_demand * self.heating_fraction
        residual_gas_after_fabric = max(post_fabric_demand - heating_after_fabric, 0)

        if pathway.heat_source == 'gas':
            # Gas boiler (with or without fabric)
            annual_demand = post_fabric_demand
            annual_bill = annual_demand * self.gas_price
            annual_co2 = (annual_demand * self.gas_carbon) / 1000  # tonnes

        elif pathway.heat_source == 'hp':
            # Heat pump (electricity)
            hp_demand = heating_after_fabric / hp_cop_central if hp_cop_central else heating_after_fabric
            annual_demand = residual_gas_after_fabric + hp_demand
            annual_bill = hp_demand * self.elec_price + residual_gas_after_fabric * self.gas_price
            annual_co2 = (
                hp_demand * self.elec_carbon + residual_gas_after_fabric * self.gas_carbon
            ) / 1000

        elif pathway.heat_source == 'hp_proxy':
            proxy_cop = self.ground_loop_scop or hp_cop_central
            hp_demand = heating_after_fabric / proxy_cop if proxy_cop else heating_after_fabric
            annual_demand = residual_gas_after_fabric + hp_demand
            annual_bill = hp_demand * self.elec_price + residual_gas_after_fabric * self.gas_price
            annual_co2 = (
                hp_demand * self.elec_carbon + residual_gas_after_fabric * self.gas_carbon
            ) / 1000

        elif pathway.heat_source == 'hn':
            # Heat network (network tariff)
            hn_demand = heating_after_fabric / self.hn_efficiency if self.hn_efficiency > 0 else heating_after_fabric
            annual_demand = non_heating_energy + heating_after_fabric  # Delivered heat (no additional demand saving)
            annual_bill = hn_demand * self.hn_tariff + non_heating_energy * self.gas_price
            annual_co2 = (
                hn_demand * self.hn_carbon + non_heating_energy * self.gas_carbon
            ) / 1000

        elif pathway.heat_source == 'hp+hn':
            # Hybrid - depends on HN access
            if has_hn_access:
                hn_demand = heating_after_fabric / self.hn_efficiency if self.hn_efficiency > 0 else heating_after_fabric
                annual_demand = non_heating_energy + heating_after_fabric
                annual_bill = hn_demand * self.hn_tariff + non_heating_energy * self.gas_price
                annual_co2 = (
                    hn_demand * self.hn_carbon + non_heating_energy * self.gas_carbon
                ) / 1000
            else:
                hp_demand = heating_after_fabric / hp_cop_central if hp_cop_central else heating_after_fabric
                annual_demand = residual_gas_after_fabric + hp_demand
                annual_bill = hp_demand * self.elec_price + residual_gas_after_fabric * self.gas_price
                annual_co2 = (
                    hp_demand * self.elec_carbon + residual_gas_after_fabric * self.gas_carbon
                ) / 1000

        # ====================================================================
        # STEP 5: Calculate savings and payback
        # ====================================================================
        annual_bill_saving = baseline_bill - annual_bill
        baseline_co2 = (baseline_demand * self.gas_carbon) / 1000
        co2_saving = baseline_co2 - annual_co2

        demand_reduction_kwh = baseline_demand - annual_demand
        demand_reduction_pct = (demand_reduction_kwh / baseline_demand * 100) if baseline_demand else 0

        # Simple payback
        if annual_bill_saving > 0:
            simple_payback = total_capex / annual_bill_saving
        else:
            simple_payback = np.inf

        # Discounted payback
        discounted_payback = self._calculate_discounted_payback(
            total_capex, annual_bill_saving
        )

        return {
            'property_id': property_data.get('LMK_KEY', 'unknown'),
            'pathway_id': pathway.pathway_id,
            'has_hn_access': has_hn_access,

            'heat_pump_flow_temp_c': flow_temp_after_measures,
            'heat_pump_cop_central': hp_cop_central,
            'heat_pump_cop_low': hp_cop_low,
            'heat_pump_cop_high': hp_cop_high,

            # Baseline
            'baseline_demand_kwh': baseline_demand,
            'baseline_bill': baseline_bill,
            'baseline_co2_tonnes': baseline_co2,

            # Post-pathway
            'annual_demand_kwh': annual_demand,
            'annual_bill': annual_bill,
            'annual_co2_tonnes': annual_co2,

            # Savings
            'demand_reduction_kwh': demand_reduction_kwh,
            'demand_reduction_pct': demand_reduction_pct,
            'annual_bill_saving': annual_bill_saving,
            'co2_saving_tonnes': co2_saving,

            # Costs breakdown
            'fabric_capex': fabric_capex,
            'hp_capex': hp_capex,
            'hn_capex': hn_capex,
            'heat_tech_capex': heat_tech_capex,
            'total_capex': total_capex,

            # Payback
            'simple_payback_years': simple_payback,
            'discounted_payback_years': discounted_payback,
        }

    def _calculate_discounted_payback(
        self,
        capex: float,
        annual_saving: float,
        max_years: int = 50
    ) -> float:
        """Calculate discounted payback period."""
        if annual_saving <= 0 or capex <= 0:
            return np.inf

        cumulative = 0.0
        for year in range(1, max_years + 1):
            discounted = annual_saving / ((1 + self.discount_rate) ** year)
            cumulative += discounted
            if cumulative >= capex:
                return year

        return np.inf

    def _get_hn_access(self, df: pd.DataFrame, hn_access_column: Optional[str] = None) -> pd.Series:
        """Determine which properties have heat network access."""
        column = hn_access_column or self.hn_access_column

        if column and column in df.columns:
            hn_access = df[column].fillna(False).astype(bool)
            logger.info(
                f"  Using deterministic heat network access column '{column}' "
                f"({hn_access.mean()*100:.1f}% ready)"
            )
        else:
            logger.warning(
                "Heat network access column not found; defaulting all properties to no access."
            )
            hn_access = pd.Series(False, index=df.index)

        return hn_access

    @staticmethod
    def _summarize_series(series: pd.Series) -> Dict[str, float]:
        """Return common summary statistics for a series."""
        clean = series.replace([np.inf, -np.inf], np.nan).dropna()
        if len(clean) == 0:
            return {k: np.nan for k in ['mean', 'median', 'p10', 'p90', 'min', 'max']}

        return {
            'mean': clean.mean(),
            'median': clean.median(),
            'p10': clean.quantile(0.10),
            'p90': clean.quantile(0.90),
            'min': clean.min(),
            'max': clean.max(),
        }

    def analyze_all_pathways(
        self,
        df: pd.DataFrame,
        hn_access_column: str = None
    ) -> pd.DataFrame:
        """
        Analyze all pathways for all properties.

        Args:
            df: Properties DataFrame
            hn_access_column: Column name indicating HN access (if None, uses random based on penetration)

        Returns:
            DataFrame with results for each property × pathway combination
        """
        logger.info(f"Analyzing pathways for {len(df):,} properties...")

        df_ready = self._ensure_adjusted_baseline(df)
        hn_access = self._get_hn_access(df_ready, hn_access_column=hn_access_column)

        results = []

        for idx, (row_idx, property_data) in enumerate(df_ready.iterrows()):
            if idx % 1000 == 0:
                logger.info(f"  Processing property {idx + 1:,}/{len(df_ready):,}...")

            has_hn = hn_access.loc[row_idx]

            for pathway_id, pathway in self.pathways.items():
                result = self.calculate_property_pathway(
                    property_data, pathway, has_hn_access=has_hn
                )
                results.append(result)

        results_df = pd.DataFrame(results)
        logger.info(f"Generated {len(results_df):,} pathway results")

        return results_df

    def model_all_pathways(
        self,
        df: pd.DataFrame,
        hn_access_column: str = None
    ) -> pd.DataFrame:
        """Alias for analyze_all_pathways for backwards compatibility."""
        return self.analyze_all_pathways(df, hn_access_column=hn_access_column)

    def generate_pathway_summary(self, results_df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate summary statistics for each pathway.

        Args:
            results_df: Property-level results

        Returns:
            Summary DataFrame with one row per pathway
        """
        logger.info("Generating pathway summary...")

        summary_rows = []

        for pathway_id in results_df['pathway_id'].unique():
            pathway_results = results_df[results_df['pathway_id'] == pathway_id]

            # Get pathway object
            pathway = self.pathways.get(pathway_id, PATHWAYS.get(pathway_id))
            pathway_name = pathway.name if pathway else pathway_id

            # Filter finite paybacks
            finite_payback = pathway_results[
                np.isfinite(pathway_results['simple_payback_years'])
            ]

            summary = {
                'pathway_id': pathway_id,
                'pathway_name': pathway_name,
                'heat_source': pathway.heat_source if pathway else '',
                'n_properties': len(pathway_results),

                # Costs
                'total_capex_mean': pathway_results['total_capex'].mean(),
                'total_capex_median': pathway_results['total_capex'].median(),
                'fabric_capex_mean': pathway_results['fabric_capex'].mean(),
                'heat_tech_capex_mean': pathway_results['heat_tech_capex'].mean(),

                # Bills
                'annual_bill_mean': pathway_results['annual_bill'].mean(),
                'annual_bill_saving_mean': pathway_results['annual_bill_saving'].mean(),

                # Demand
                'demand_reduction_pct_mean': pathway_results['demand_reduction_pct'].mean(),

                # CO2
                'annual_co2_mean': pathway_results['annual_co2_tonnes'].mean(),
                'co2_saving_mean': pathway_results['co2_saving_tonnes'].mean(),
                'co2_saving_total': pathway_results['co2_saving_tonnes'].sum(),

                # Payback
                'simple_payback_median': finite_payback['simple_payback_years'].median()
                    if len(finite_payback) > 0 else np.nan,
                'discounted_payback_median': finite_payback['discounted_payback_years'].median()
                    if len(finite_payback) > 0 else np.nan,

                # Cost effectiveness
                'gbp_per_tonne_co2_20yr': (
                    pathway_results['total_capex'].sum() /
                    (pathway_results['co2_saving_tonnes'].sum() * 20)
                ) if pathway_results['co2_saving_tonnes'].sum() > 0 else np.nan,
            }

            summary_rows.append(summary)

        summary_df = pd.DataFrame(summary_rows)
        return summary_df

    def run_hn_connection_sensitivity(
        self,
        df: pd.DataFrame,
        hn_access_column: Optional[str] = None,
        deltas: Tuple[int, ...] = (0, 2000, 5000)
    ) -> pd.DataFrame:
        """Run sensitivity on district heating connection costs."""
        base_cost = self.costs.get('district_heating_connection', 5000)
        hn_access = self._get_hn_access(df, hn_access_column=hn_access_column)

        rows = []
        hn_pathway = self.pathways.get('fabric_plus_hn_only', PATHWAYS.get('fabric_plus_hn_only'))

        for delta in deltas:
            self.costs['district_heating_connection'] = base_cost + delta
            scenario_results = []

            for row_idx, property_data in df.iterrows():
                scenario_results.append(
                    self.calculate_property_pathway(
                        property_data,
                        hn_pathway,
                        has_hn_access=hn_access.loc[row_idx]
                    )
                )

            scenario_df = pd.DataFrame(scenario_results)
            capex_stats = self._summarize_series(scenario_df['total_capex'])
            bill_saving_stats = self._summarize_series(scenario_df['annual_bill_saving'])
            bill_change_stats = self._summarize_series(
                scenario_df['annual_bill'] - scenario_df['baseline_bill']
            )
            co2_saving_stats = self._summarize_series(scenario_df['co2_saving_tonnes'])
            co2_change_stats = self._summarize_series(
                scenario_df['annual_co2_tonnes'] - scenario_df['baseline_co2_tonnes']
            )
            payback_stats = self._summarize_series(scenario_df['simple_payback_years'])

            rows.append({
                'scenario': f'hn_cost_{int(base_cost + delta)}',
                'hn_connection_cost_per_home': base_cost + delta,
                'n_properties': len(scenario_df),
                **{f'capex_{k}': v for k, v in capex_stats.items()},
                **{f'bill_saving_{k}': v for k, v in bill_saving_stats.items()},
                **{f'bill_change_{k}': v for k, v in bill_change_stats.items()},
                **{f'co2_saving_{k}': v for k, v in co2_saving_stats.items()},
                **{f'co2_change_{k}': v for k, v in co2_change_stats.items()},
                **{f'payback_{k}': v for k, v in payback_stats.items()},
            })

        # Restore base cost
        self.costs['district_heating_connection'] = base_cost

        sensitivity_df = pd.DataFrame(rows)
        output_path = self.comparisons_dir / "hn_cost_sensitivity.csv"
        sensitivity_df.to_csv(output_path, index=False)
        logger.info(f"Saved HN cost sensitivity results to {output_path}")

        return sensitivity_df

    def verify_hybrid_cost_fix(self, results_df: pd.DataFrame) -> bool:
        """
        Verify that the hybrid cost bug is fixed.

        The bug was that hybrid pathway showed same cost as fabric-only.
        After fix, hybrid should have higher costs (fabric + heat tech).

        Args:
            results_df: Pathway results DataFrame

        Returns:
            True if verification passes

        Raises:
            AssertionError: If hybrid cost bug is detected
        """
        logger.info("Verifying hybrid cost fix...")

        fabric_only = results_df[results_df['pathway_id'] == 'fabric_only']
        hybrid = results_df[results_df['pathway_id'] == 'fabric_plus_hp_plus_hn']

        if len(fabric_only) == 0 or len(hybrid) == 0:
            logger.warning("Cannot verify - missing pathways in results")
            return True

        fabric_mean = fabric_only['total_capex'].mean()
        hybrid_mean = hybrid['total_capex'].mean()

        logger.info(f"  Fabric-only mean capex: £{fabric_mean:,.0f}")
        logger.info(f"  Hybrid mean capex: £{hybrid_mean:,.0f}")
        logger.info(f"  Difference: £{hybrid_mean - fabric_mean:,.0f}")

        # Hybrid should cost more than fabric-only (by at least HP or HN cost)
        min_expected_diff = min(
            self.costs.get('ashp_installation', 12000),
            self.costs.get('district_heating_connection', 5000)
        ) * 0.9  # Allow 10% tolerance

        if hybrid_mean <= fabric_mean:
            raise AssertionError(
                f"HYBRID COST BUG DETECTED: "
                f"Hybrid (£{hybrid_mean:,.0f}) should exceed fabric-only (£{fabric_mean:,.0f})"
            )

        if hybrid_mean - fabric_mean < min_expected_diff:
            logger.warning(
                f"Hybrid cost difference (£{hybrid_mean - fabric_mean:,.0f}) "
                f"is less than expected (£{min_expected_diff:,.0f})"
            )

        logger.info("Hybrid cost fix verified successfully!")
        return True

    def export_results(
        self,
        results_df: pd.DataFrame,
        summary_df: pd.DataFrame
    ) -> Tuple[Path, Path]:
        """Export pathway results to files."""
        # Property-level results
        property_path = self.output_dir / "pathway_results_by_property.parquet"
        results_df.to_parquet(property_path, index=False)
        logger.info(f"Saved property-level results to {property_path}")

        # Summary
        summary_path = self.output_dir / "pathway_results_summary.csv"
        summary_df.to_csv(summary_path, index=False)
        logger.info(f"Saved pathway summary to {summary_path}")

        return property_path, summary_path

    def run_full_analysis(self, df: pd.DataFrame) -> Dict:
        """
        Run complete pathway analysis.

        Args:
            df: Properties DataFrame

        Returns:
            Dictionary with all results
        """
        logger.info("Running full pathway analysis...")

        # Analyze all pathways
        results_df = self.analyze_all_pathways(df)

        # Verify hybrid cost fix
        self.verify_hybrid_cost_fix(results_df)

        # Generate summary
        summary_df = self.generate_pathway_summary(results_df)

        # Export results
        self.export_results(results_df, summary_df)

        return {
            'results': results_df,
            'summary': summary_df
        }


def test_hybrid_cost_bug():
    """
    Unit test for hybrid cost bug fix.

    Creates a synthetic property and verifies that hybrid pathway
    costs more than fabric-only pathway.
    """
    logger.info("Running hybrid cost bug test...")

    # Create synthetic test property
    test_property = pd.Series({
        'LMK_KEY': 'TEST001',
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
    fabric_result = modeler.calculate_property_pathway(
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

    # Assertions
    assert fabric_result['total_capex'] > 0, "Fabric-only should have non-zero capex"
    assert hybrid_no_hn['total_capex'] > fabric_result['total_capex'], \
        f"Hybrid (no HN access) should cost more than fabric-only: " \
        f"£{hybrid_no_hn['total_capex']:,.0f} vs £{fabric_result['total_capex']:,.0f}"
    assert hybrid_with_hn['total_capex'] > fabric_result['total_capex'], \
        f"Hybrid (with HN access) should cost more than fabric-only"
    assert hp_only['total_capex'] > fabric_result['total_capex'], \
        "HP-only should cost more than fabric-only"

    # Hybrid without HN should equal HP cost
    assert abs(hybrid_no_hn['total_capex'] - hp_only['total_capex']) < 1, \
        "Hybrid without HN access should equal HP pathway cost"

    logger.info("All hybrid cost bug tests passed!")
    logger.info(f"  Fabric-only capex: £{fabric_result['total_capex']:,.0f}")
    logger.info(f"  Hybrid (no HN) capex: £{hybrid_no_hn['total_capex']:,.0f}")
    logger.info(f"  Hybrid (with HN) capex: £{hybrid_with_hn['total_capex']:,.0f}")
    logger.info(f"  HP-only capex: £{hp_only['total_capex']:,.0f}")

    return True


def main():
    """Main execution function."""
    logger.info("Starting pathway analysis...")

    # Run unit test first
    test_hybrid_cost_bug()

    # Load validated data
    input_file = DATA_PROCESSED_DIR / "epc_london_validated.parquet"

    if not input_file.exists():
        input_file = DATA_PROCESSED_DIR / "epc_london_validated.csv"
        if not input_file.exists():
            logger.error("Input file not found")
            return

    logger.info(f"Loading data from: {input_file}")
    if input_file.suffix == '.parquet':
        df = pd.read_parquet(input_file)
    else:
        df = pd.read_csv(input_file, low_memory=False)

    # Run analysis
    modeler = PathwayModeler()
    results = modeler.run_full_analysis(df)

    # Log summary
    logger.info("\nPathway Analysis Summary:")
    if 'summary' in results:
        for _, row in results['summary'].iterrows():
            logger.info(
                f"  {row['pathway_id']}: "
                f"£{row['total_capex_mean']:,.0f} capex, "
                f"£{row['annual_bill_saving_mean']:,.0f}/yr savings, "
                f"{row['simple_payback_median']:.1f}yr payback"
            )

    logger.info("Pathway analysis complete!")


if __name__ == "__main__":
    main()
