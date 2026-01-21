"""
Methodological Adjustments Module

Implements evidence-based adjustments to improve analysis accuracy:
- Prebound effect adjustment (Few et al., 2023)
- Heat pump flow temperature modeling
- Measurement error and confidence intervals (Crawley et al., 2019)
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, Union
from loguru import logger
from config.config import (
    get_default_performance_gap_variant,
    get_performance_gap_factors,
    get_heat_pump_cop_curve,
)


class MethodologicalAdjustments:
    """Apply evidence-based methodological adjustments to EPC analysis."""

    # Prebound effect factors from Few et al. (2023) used as fallback
    # EPCs systematically overpredict energy consumption, especially for lower-rated homes
    DEFAULT_PREBOUND_FACTORS = {
        'A': 1.00,  # No adjustment needed
        'B': 1.00,  # No adjustment needed
        'C': 0.92,  # 8% overprediction
        'D': 0.82,  # 18% overprediction
        'E': 0.72,  # 28% overprediction
        'F': 0.55,  # 45% overprediction
        'G': 0.52,  # 48% overprediction
    }

    # AUDIT FIX: Rebound effect factors by EPC band
    # Homes that were under-heated before retrofit may "take back" some savings
    # as improved comfort (the "rebound effect" or "comfort taking").
    # Research suggests 10-40% of theoretical savings may be taken as comfort.
    # Factors represent fraction of modeled savings that will be realized as
    # actual energy reduction (remainder taken as improved comfort).
    #
    # Evidence base:
    # - Sorrell et al. (2009): Direct rebound effects typically 10-30%
    # - Milne & Boardman (2000): Comfort taking in fuel-poor homes ~30%
    # - Hong et al. (2006): Rebound 15-20% in average homes, higher in under-heated
    # - Chitnis et al. (2013): UK rebound effect estimates 5-15%
    #
    # Homes with lower EPC ratings (who likely under-heated) have higher rebound.
    REBOUND_FACTORS = {
        'A': 1.00,  # Well-heated home, minimal rebound
        'B': 0.95,  # 5% taken as comfort
        'C': 0.90,  # 10% taken as comfort
        'D': 0.85,  # 15% taken as comfort
        'E': 0.75,  # 25% taken as comfort (moderate under-heating)
        'F': 0.65,  # 35% taken as comfort (significant under-heating)
        'G': 0.55,  # 45% taken as comfort (severe under-heating)
    }

    # Emitter upgrade costs for heat pump compatibility
    EMITTER_UPGRADE_COSTS = {
        'none': 0,        # Existing radiators adequate
        'possible': 1500,  # Minor upsizing
        'likely': 3500,    # Significant upsizing
        'definite': 6000,  # Major replacement
    }

    def __init__(self):
        """Initialize methodological adjustments."""
        self.performance_gap_variants = self._load_performance_gap_variants()
        self.base_gap_variant = self._resolve_base_variant()
        self.hp_cop_curve = get_heat_pump_cop_curve()
        self.min_flow_temp = float(min(self.hp_cop_curve.get('temperatures_c', [45])))
        logger.info(
            "Initialized Methodological Adjustments (base performance gap variant: {})",
            self.base_gap_variant,
        )

    def _load_performance_gap_variants(self) -> Dict[str, Dict[str, float]]:
        """Load performance gap factors from config with sensible fallback."""
        try:
            factors = get_performance_gap_factors("all")
            if not isinstance(factors, dict) or not factors:
                raise ValueError("Performance gap factors missing or malformed")
            return factors
        except Exception as exc:
            logger.warning(
                "Falling back to default prebound factors due to config issue: {}", exc
            )
            return {'central': self.DEFAULT_PREBOUND_FACTORS}

    def _resolve_base_variant(self) -> str:
        """Pick the base (canonical) variant used for main baseline columns."""
        configured = get_default_performance_gap_variant()
        if configured in self.performance_gap_variants:
            return configured
        if 'central' in self.performance_gap_variants:
            return 'central'
        return next(iter(self.performance_gap_variants.keys()))

    def apply_prebound_adjustment(self, df: pd.DataFrame, variant: str = None, inplace: bool = False) -> pd.DataFrame:
        """
        Apply prebound effect adjustment to energy consumption.

        Research shows EPCs systematically overpredict consumption, especially
        for lower-rated homes due to:
        - Lower internal temperatures (heating underconsumption)
        - Behavioral factors
        - Modeling assumptions

        Based on Few et al. (2023) findings on performance gap.

        Args:
            df: DataFrame with CURRENT_ENERGY_RATING and ENERGY_CONSUMPTION_CURRENT
            variant: Performance gap variant to use
            inplace: If True, modify df directly (saves memory)

        Returns:
            DataFrame with adjusted energy consumption columns
        """
        logger.info("Applying prebound effect adjustment...")

        if inplace:
            df_adj = df
        else:
            df_adj = df.copy()

        # Get EPC band
        if 'CURRENT_ENERGY_RATING' not in df.columns:
            logger.warning("CURRENT_ENERGY_RATING column not found, skipping prebound adjustment")
            return df

        available_variants = ['central', 'low', 'high']
        available_variants = [v for v in available_variants if v in self.performance_gap_variants]
        if not available_variants:
            available_variants = list(self.performance_gap_variants.keys())

        base_variant = variant or self.base_gap_variant
        if base_variant not in available_variants:
            logger.warning(
                "Requested base variant '{}' not found; defaulting to '{}'",
                base_variant,
                available_variants[0],
            )
            base_variant = available_variants[0]

        central_factors = self.performance_gap_variants.get(
            'central', self.DEFAULT_PREBOUND_FACTORS
        )
        default_fill = central_factors.get('D', 0.82)

        # Map band to factor for each variant and compute adjusted intensities
        for variant_name in available_variants:
            factor_map = self.performance_gap_variants.get(variant_name, central_factors)
            factor_col = f'prebound_factor_{variant_name}'
            df_adj[factor_col] = df_adj['CURRENT_ENERGY_RATING'].map(factor_map)
            df_adj[factor_col] = df_adj[factor_col].fillna(default_fill)
            # Ensure numeric dtype (categorical EPC_RATING can produce categorical factor)
            df_adj[factor_col] = df_adj[factor_col].astype(float)

            if 'ENERGY_CONSUMPTION_CURRENT' in df.columns:
                adjusted_col = f'energy_consumption_adjusted_{variant_name}'
                df_adj[adjusted_col] = (
                    df_adj['ENERGY_CONSUMPTION_CURRENT'] * df_adj[factor_col]
                )

                if 'TOTAL_FLOOR_AREA' in df.columns:
                    df_adj[f'baseline_consumption_kwh_year_{variant_name}'] = (
                        df_adj[adjusted_col] * df_adj['TOTAL_FLOOR_AREA']
                    )

        # Canonical columns use the base variant
        base_factor_col = f'prebound_factor_{base_variant}'
        if base_factor_col in df_adj.columns:
            df_adj['prebound_factor'] = df_adj[base_factor_col]
        else:
            df_adj['prebound_factor'] = df_adj['CURRENT_ENERGY_RATING'].map(central_factors).fillna(default_fill)
            # Ensure numeric dtype
            df_adj['prebound_factor'] = df_adj['prebound_factor'].astype(float)

        if 'ENERGY_CONSUMPTION_CURRENT' in df.columns:
            base_adjusted_col = f'energy_consumption_adjusted_{base_variant}'
            if base_adjusted_col in df_adj.columns:
                df_adj['energy_consumption_adjusted'] = df_adj[base_adjusted_col]
            else:
                df_adj['energy_consumption_adjusted'] = (
                    df_adj['ENERGY_CONSUMPTION_CURRENT'] * df_adj['prebound_factor']
                )

            if 'TOTAL_FLOOR_AREA' in df.columns:
                base_baseline_col = f'baseline_consumption_kwh_year_{base_variant}'
                if base_baseline_col in df_adj.columns:
                    df_adj['baseline_consumption_kwh_year'] = df_adj[base_baseline_col]
                else:
                    df_adj['baseline_consumption_kwh_year'] = (
                        df_adj['energy_consumption_adjusted'] * df_adj['TOTAL_FLOOR_AREA']
                    )

        logger.info(f"✓ Prebound adjustment applied using '{base_variant}' variant")

        # Log impact (overall and band-wise)
        if 'ENERGY_CONSUMPTION_CURRENT' in df.columns:
            original_mean = df['ENERGY_CONSUMPTION_CURRENT'].mean()
            logger.info(f"  Original mean: {original_mean:.1f} kWh/m²/year")

            for variant_name in available_variants:
                adjusted_col = f'energy_consumption_adjusted_{variant_name}'
                if adjusted_col not in df_adj.columns:
                    continue

                adjusted_mean = df_adj[adjusted_col].mean()
                reduction_pct = (
                    (1 - adjusted_mean / original_mean) * 100
                    if original_mean > 0 else np.nan
                )
                logger.info(
                    "  Variant '{variant}': adjusted mean {mean:.1f} kWh/m²/year ({reduction:.1f}% reduction)",
                    variant=variant_name,
                    mean=adjusted_mean,
                    reduction=reduction_pct,
                )

                band_summary = (
                    df_adj[['CURRENT_ENERGY_RATING', 'ENERGY_CONSUMPTION_CURRENT', adjusted_col]]
                    .dropna(subset=['CURRENT_ENERGY_RATING'])
                    .groupby('CURRENT_ENERGY_RATING')
                    .mean()
                )
                for band, row in band_summary.sort_index().iterrows():
                    original_band = row.get('ENERGY_CONSUMPTION_CURRENT')
                    adjusted_band = row.get(adjusted_col)
                    reduction_band_pct = (
                        (1 - adjusted_band / original_band) * 100
                        if pd.notna(original_band) and original_band != 0 else np.nan
                    )
                    logger.info(
                        "    Band {band}: {orig:.1f} → {adjusted:.1f} kWh/m² ({gap:.1f}% gap) [{variant}]",
                        band=band,
                        orig=original_band,
                        adjusted=adjusted_band,
                        gap=reduction_band_pct,
                        variant=variant_name,
                    )

        return df_adj

    def derive_heat_pump_cop(
        self,
        flow_temp: Union[pd.Series, float, int],
        include_bounds: bool = True,
    ) -> Dict[str, Union[pd.Series, float]]:
        """Map flow temperature to COP/SPF using configured curves.

        Args:
            flow_temp: Target flow temperature(s) in °C.
            include_bounds: Whether to return low/high sensitivity bounds.

        Returns:
            Dictionary with central (and optional low/high) COP values.
        """
        temps = np.array(self.hp_cop_curve.get('temperatures_c', []), dtype=float)
        if temps.size == 0:
            raise ValueError("Heat pump COP curve temperatures are not configured.")

        def _interp(values: Optional[list]) -> Union[pd.Series, float]:
            curve = np.array(values if values is not None else self.hp_cop_curve['central'], dtype=float)
            if isinstance(flow_temp, pd.Series):
                return pd.Series(
                    np.interp(flow_temp.astype(float), temps, curve),
                    index=flow_temp.index,
                )
            return float(np.interp(float(flow_temp), temps, curve))

        central = _interp(self.hp_cop_curve.get('central'))
        results: Dict[str, Union[pd.Series, float]] = {'central': central}

        if include_bounds:
            results['low'] = _interp(self.hp_cop_curve.get('low'))
            results['high'] = _interp(self.hp_cop_curve.get('high'))

        return results

    def estimate_flow_temperature(self, df: pd.DataFrame, inplace: bool = False) -> pd.DataFrame:
        """
        Estimate required flow temperature for heat pumps based on fabric performance.

        Args:
            df: DataFrame with fabric and heating data
            inplace: If True, modify df directly (saves memory)

        Returns:
            DataFrame with flow temperature estimates

        Heat pumps operate efficiently at 35-55°C. Older radiators sized for
        70-80°C gas boilers may need upsizing (typically 2-2.5× larger surface area).

        Args:
            df: DataFrame with EPC fields

        Returns:
            DataFrame with flow temperature estimates and emitter upgrade needs
        """
        logger.info("Estimating heat pump flow temperature requirements...")

        if inplace:
            df_temp = df
        else:
            df_temp = df.copy()

        # Base flow temp from SAP score (proxy for fabric quality)
        # SAP 80+ = 45°C (good fabric), SAP 40 = 70°C (poor fabric)
        if 'CURRENT_ENERGY_EFFICIENCY' in df.columns:
            sap = df_temp['CURRENT_ENERGY_EFFICIENCY'].fillna(50)

            # Linear interpolation: 70°C at SAP 40, 45°C at SAP 80
            df_temp['base_flow_temp'] = 70 - (sap - 40) * (25 / 40)
            df_temp['base_flow_temp'] = df_temp['base_flow_temp'].clip(45, 75)
        else:
            df_temp['base_flow_temp'] = 60  # Default

        # Adjust for specific fabric deficiencies
        flow_temp_adjustment = 0

        # Wall insulation
        if 'wall_insulated' in df.columns:
            flow_temp_adjustment += (~df_temp['wall_insulated']).astype(int) * 5

        # Glazing type
        if 'WINDOWS_DESCRIPTION' in df.columns:
            single_glazed = df_temp['WINDOWS_DESCRIPTION'].str.contains(
                'single', case=False, na=False
            )
            flow_temp_adjustment += single_glazed.astype(int) * 3

        # Final flow temperature estimate
        df_temp['estimated_flow_temp'] = (
            df_temp['base_flow_temp'] + flow_temp_adjustment
        ).clip(45, 80)

        # Assess emitter upgrade need
        df_temp['emitter_upgrade_need'] = pd.cut(
            df_temp['estimated_flow_temp'],
            bins=[0, 45, 55, 65, 100],
            labels=['none', 'possible', 'likely', 'definite']
        )

        # Add emitter upgrade costs
        df_temp['emitter_upgrade_cost'] = df_temp['emitter_upgrade_need'].map(
            self.EMITTER_UPGRADE_COSTS
        ).fillna(0)

        logger.info(f"✓ Flow temperature estimates complete")

        # Log distribution
        if 'emitter_upgrade_need' in df_temp.columns:
            upgrade_dist = df_temp['emitter_upgrade_need'].value_counts(normalize=True) * 100
            logger.info(f"  Emitter upgrade needs:")
            for need, pct in upgrade_dist.items():
                logger.info(f"    {need}: {pct:.1f}%")

        return df_temp

    def attach_cop_estimates(
        self,
        df: pd.DataFrame,
        flow_temp_col: str = 'estimated_flow_temp',
        inplace: bool = False
    ) -> pd.DataFrame:
        """Add COP estimates to dataframe based on flow temperatures.

        Args:
            df: DataFrame with flow temperature data
            flow_temp_col: Column name containing flow temperatures
            inplace: If True, modify df directly (saves memory)

        Returns:
            DataFrame with COP estimates attached
        """
        if flow_temp_col not in df.columns:
            logger.warning("Flow temperature column '%s' missing; skipping COP attachment", flow_temp_col)
            return df

        if inplace:
            df_cop = df
        else:
            df_cop = df.copy()
        cop = self.derive_heat_pump_cop(df_cop[flow_temp_col], include_bounds=True)
        df_cop['hp_cop_central'] = cop['central']
        df_cop['hp_cop_low'] = cop.get('low', cop['central'])
        df_cop['hp_cop_high'] = cop.get('high', cop['central'])

        return df_cop

    def get_rebound_factor(self, epc_band: str) -> float:
        """
        Get the rebound effect factor for a given EPC band.

        The rebound effect represents the fraction of modeled energy savings
        that will actually be realized. The remainder is "taken back" as
        improved thermal comfort (warmer home temperatures).

        Args:
            epc_band: EPC rating (A-G)

        Returns:
            Factor between 0 and 1 representing realized savings fraction
        """
        return self.REBOUND_FACTORS.get(str(epc_band).upper(), 0.85)

    def apply_rebound_adjustment(
        self,
        df: pd.DataFrame,
        savings_col: str = 'modeled_savings_kwh'
    ) -> pd.DataFrame:
        """
        Apply rebound effect adjustment to modeled energy savings.

        AUDIT FIX: Addresses audit finding that the model applies prebound
        calibration to baseline but then uses full SAP-derived savings,
        which may overestimate actual energy reductions. In reality,
        homes that were under-heated before retrofit may "take back"
        some savings as improved comfort.

        This adjustment:
        1. Maps each property's EPC band to a rebound factor
        2. Reduces modeled savings by the rebound factor
        3. Provides both unadjusted and adjusted savings columns

        Evidence base:
        - Few et al. (2023): Performance gap analysis
        - Sorrell et al. (2009): Direct rebound effects 10-30%
        - Milne & Boardman (2000): Comfort taking ~30% in fuel-poor homes

        Args:
            df: DataFrame with CURRENT_ENERGY_RATING and savings columns

        Returns:
            DataFrame with rebound-adjusted savings columns
        """
        logger.info("Applying rebound effect adjustment to savings estimates...")

        df_adj = df.copy()

        if 'CURRENT_ENERGY_RATING' not in df.columns:
            logger.warning("CURRENT_ENERGY_RATING column not found, skipping rebound adjustment")
            return df

        # Map EPC band to rebound factor
        df_adj['rebound_factor'] = df_adj['CURRENT_ENERGY_RATING'].map(self.REBOUND_FACTORS)
        df_adj['rebound_factor'] = df_adj['rebound_factor'].fillna(0.85)  # Default for unknown bands
        # Ensure numeric dtype (categorical EPC_RATING can produce categorical rebound_factor)
        df_adj['rebound_factor'] = df_adj['rebound_factor'].astype(float)

        # Apply to any savings columns that exist
        savings_columns = [
            'modeled_savings_kwh',
            'annual_kwh_saving',
            'fabric_savings_kwh',
            'heat_pump_savings_kwh',
        ]

        adjusted_cols = 0
        for col in savings_columns:
            if col in df_adj.columns:
                # Keep original as _unadjusted
                df_adj[f'{col}_unadjusted'] = df_adj[col]
                # Apply rebound factor
                df_adj[col] = df_adj[col] * df_adj['rebound_factor']
                adjusted_cols += 1
                logger.info(f"  Applied rebound adjustment to {col}")

        # Also apply to percentage savings if present
        pct_cols = ['kwh_saving_pct', 'energy_reduction_pct']
        for col in pct_cols:
            if col in df_adj.columns:
                df_adj[f'{col}_unadjusted'] = df_adj[col]
                df_adj[col] = df_adj[col] * df_adj['rebound_factor']
                adjusted_cols += 1

        # Log impact
        if adjusted_cols > 0:
            mean_rebound = df_adj['rebound_factor'].mean()
            reduction_pct = (1 - mean_rebound) * 100
            logger.info(f"✓ Rebound effect adjustment applied")
            logger.info(f"  Mean rebound factor: {mean_rebound:.2f}")
            logger.info(f"  Average savings reduction due to comfort-taking: {reduction_pct:.1f}%")

            # Band-wise breakdown
            band_summary = df_adj.groupby('CURRENT_ENERGY_RATING')['rebound_factor'].mean()
            for band in ['A', 'B', 'C', 'D', 'E', 'F', 'G']:
                if band in band_summary.index:
                    factor = band_summary[band]
                    taken = (1 - factor) * 100
                    logger.info(f"    Band {band}: {taken:.0f}% of savings taken as comfort")
        else:
            logger.info("  No applicable savings columns found; rebound factor added for downstream use")

        return df_adj

    def add_measurement_uncertainty(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add measurement error and confidence intervals based on Crawley et al. (2019).

        EPC measurement error is:
        - ±2.4 SAP points at high ratings (85+)
        - ±4.0 SAP points at good ratings (70-84)
        - ±6.0 SAP points at average ratings (55-69)
        - ±8.0 SAP points at low ratings (<55)

        Args:
            df: DataFrame with CURRENT_ENERGY_EFFICIENCY

        Returns:
            DataFrame with uncertainty estimates
        """
        logger.info("Adding measurement uncertainty estimates...")

        df_unc = df.copy()

        if 'CURRENT_ENERGY_EFFICIENCY' not in df.columns:
            logger.warning("CURRENT_ENERGY_EFFICIENCY not found, skipping uncertainty")
            return df

        # Assign uncertainty based on SAP score
        sap = df_unc['CURRENT_ENERGY_EFFICIENCY'].fillna(50)

        conditions = [
            (sap >= 85),
            (sap >= 70) & (sap < 85),
            (sap >= 55) & (sap < 70),
            (sap < 55)
        ]

        uncertainties = [2.4, 4.0, 6.0, 8.0]

        df_unc['sap_uncertainty'] = np.select(conditions, uncertainties, default=6.0)

        # Calculate 95% confidence intervals for mean (for aggregate reporting)
        mean_sap = df_unc['CURRENT_ENERGY_EFFICIENCY'].mean()
        mean_uncertainty = df_unc['sap_uncertainty'].mean()
        n = len(df_unc)
        ci_95 = 1.96 * mean_uncertainty / np.sqrt(n)

        df_unc['mean_sap_ci_lower'] = mean_sap - ci_95
        df_unc['mean_sap_ci_upper'] = mean_sap + ci_95

        logger.info(f"✓ Uncertainty estimates added")
        logger.info(f"  Mean SAP: {mean_sap:.1f} ± {ci_95:.2f} (95% CI)")

        return df_unc

    def apply_all_adjustments(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply all methodological adjustments in correct sequence.

        AUDIT FIX: Now includes rebound effect factor for downstream savings
        calculations. The sequence is:

        1. Prebound effect (calibrate baseline to realistic consumption)
        2. Rebound factor (prepare for downstream savings adjustment)
        3. Flow temperature model (for heat pump costing)
        4. Measurement uncertainty (for reporting)

        Note: The rebound factor is attached to each property for use by
        the scenario model when calculating actual energy savings. This
        ensures that homes with high prebound (under-heating) will have
        their modeled savings reduced to account for comfort-taking.

        Args:
            df: Raw validated DataFrame

        Returns:
            DataFrame with all adjustments applied
        """
        logger.info("Applying all methodological adjustments...")

        df_adjusted = df.copy()

        # 1. Prebound effect (must be first - affects baseline)
        df_adjusted = self.apply_prebound_adjustment(df_adjusted)

        # 2. Attach rebound factors for downstream savings calculations
        # This doesn't modify savings yet (scenario model does that) but
        # provides the factors for each property based on their EPC band
        df_adjusted = self.apply_rebound_adjustment(df_adjusted)

        # 3. Flow temperature model (for heat pump costing)
        df_adjusted = self.estimate_flow_temperature(df_adjusted)

        # 4. Measurement uncertainty (for reporting)
        df_adjusted = self.add_measurement_uncertainty(df_adjusted)

        logger.info(f"✓ All methodological adjustments complete")

        return df_adjusted

    def generate_adjustment_summary(self, df: pd.DataFrame) -> Dict:
        """
        Generate summary of methodological adjustments applied.

        Args:
            df: Adjusted DataFrame

        Returns:
            Dictionary with adjustment statistics
        """
        summary = {
            'prebound_adjustment': {},
            'rebound_adjustment': {},
            'flow_temperature': {},
            'uncertainty': {}
        }

        # Prebound summary
        if 'prebound_factor' in df.columns:
            # BUG FIX: Count properties that were adjusted (prebound_factor != 1.0)
            properties_adjusted = int((df['prebound_factor'] != 1.0).sum())
            summary['prebound_adjustment'] = {
                'applied': True,
                'properties_adjusted': properties_adjusted,
                'mean_factor': df['prebound_factor'].mean(),
                'description': 'Adjusts EPC-modeled consumption to realistic baseline (Few et al., 2023)'
            }

        # Rebound effect summary
        if 'rebound_factor' in df.columns:
            mean_rebound = df['rebound_factor'].mean()
            comfort_taking_pct = (1 - mean_rebound) * 100
            summary['rebound_adjustment'] = {
                'applied': True,
                'mean_factor': mean_rebound,
                'comfort_taking_pct': comfort_taking_pct,
                'description': (
                    'Adjusts modeled savings for comfort-taking (rebound effect). '
                    'Under-heated homes take some savings as improved thermal comfort '
                    'rather than reduced fuel consumption. '
                    '(Sorrell et al., 2009; Milne & Boardman, 2000)'
                ),
                'methodology_note': (
                    f'Average {comfort_taking_pct:.1f}% of theoretical savings '
                    f'expected to be taken as comfort improvement rather than energy reduction'
                )
            }

        # Flow temperature summary
        if 'estimated_flow_temp' in df.columns:
            summary['flow_temperature'] = {
                'applied': True,
                'mean_flow_temp': df['estimated_flow_temp'].mean(),
                'pct_need_emitter_upgrade': (
                    (df['emitter_upgrade_need'] != 'none').mean() * 100
                ),
                'description': 'Estimates required flow temperature for heat pump efficiency'
            }

        # Uncertainty summary
        if 'sap_uncertainty' in df.columns:
            summary['uncertainty'] = {
                'applied': True,
                'mean_uncertainty': df['sap_uncertainty'].mean(),
                'description': 'EPC measurement error (Crawley et al., 2019)'
            }

        return summary


def apply_demand_uncertainty(
    df: pd.DataFrame,
    demand_col: str = 'annual_kwh_saving',
    bill_col: str = 'annual_bill_saving',
    co2_col: str = 'co2_saving_tonnes',
    low: float = -0.20,
    high: float = 0.20,
    anomaly_low: float = -0.30,
    anomaly_high: float = 0.30
) -> pd.DataFrame:
    """
    Apply demand uncertainty ranges to analysis results.

    Creates low/high variants of demand, bills, and CO2 based on EPC measurement
    error and prebound effect uncertainties.

    Args:
        df: DataFrame with analysis results (must have demand/bill/CO2 columns)
        demand_col: Column name for demand/savings to apply uncertainty to
        bill_col: Column name for bill savings (derived from demand)
        co2_col: Column name for CO2 savings (derived from demand)
        low: Low uncertainty bound (e.g., -0.20 for -20%)
        high: High uncertainty bound (e.g., 0.20 for +20%)
        anomaly_low: Low bound for flagged anomalies (e.g., -0.30 for -30%)
        anomaly_high: High bound for flagged anomalies

    Returns:
        DataFrame with additional columns:
        - {col}_low: Lower bound estimate
        - {col}_high: Upper bound estimate
        - simple_payback_years_low/high (if capex column exists)

    Example:
        df_with_uncertainty = apply_demand_uncertainty(
            df,
            demand_col='annual_kwh_saving',
            low=-0.20,
            high=0.20
        )
    """
    logger.info("Applying demand uncertainty ranges...")

    df_uncertain = df.copy()

    # Determine if property is an anomaly
    if 'is_epc_fabric_anomaly' in df.columns:
        is_anomaly = df['is_epc_fabric_anomaly']
    else:
        is_anomaly = pd.Series(False, index=df.index)

    # Calculate uncertainty bounds (anomalies get wider range)
    low_factor = np.where(is_anomaly, 1 + anomaly_low, 1 + low)
    high_factor = np.where(is_anomaly, 1 + anomaly_high, 1 + high)

    # Apply to demand/savings
    if demand_col in df.columns:
        df_uncertain[f'{demand_col}_baseline'] = df[demand_col]
        df_uncertain[f'{demand_col}_low'] = df[demand_col] * low_factor
        df_uncertain[f'{demand_col}_high'] = df[demand_col] * high_factor

        logger.info(f"  Applied uncertainty to {demand_col}: [{low*100:.0f}%, +{high*100:.0f}%]")

    # Apply to bills (proportional to demand)
    if bill_col in df.columns:
        df_uncertain[f'{bill_col}_baseline'] = df[bill_col]
        df_uncertain[f'{bill_col}_low'] = df[bill_col] * low_factor
        df_uncertain[f'{bill_col}_high'] = df[bill_col] * high_factor

        logger.info(f"  Applied uncertainty to {bill_col}")

    # Apply to CO2 (proportional to demand)
    if co2_col in df.columns:
        df_uncertain[f'{co2_col}_baseline'] = df[co2_col]
        df_uncertain[f'{co2_col}_low'] = df[co2_col] * low_factor
        df_uncertain[f'{co2_col}_high'] = df[co2_col] * high_factor

        logger.info(f"  Applied uncertainty to {co2_col}")

    # Calculate payback uncertainty (if capex exists)
    if 'capex_per_home' in df.columns and f'{bill_col}_low' in df_uncertain.columns:
        capex = df['capex_per_home']

        # Low bill savings = longer payback (pessimistic)
        bill_low = df_uncertain[f'{bill_col}_low']
        df_uncertain['simple_payback_years_high'] = np.where(
            bill_low > 0, capex / bill_low, np.inf
        )

        # High bill savings = shorter payback (optimistic)
        bill_high = df_uncertain[f'{bill_col}_high']
        df_uncertain['simple_payback_years_low'] = np.where(
            bill_high > 0, capex / bill_high, np.inf
        )

        logger.info("  Calculated payback uncertainty ranges")

    # Alternative: if 'total_capex' column exists
    elif 'total_capex' in df.columns and f'{bill_col}_low' in df_uncertain.columns:
        capex = df['total_capex']

        bill_low = df_uncertain[f'{bill_col}_low']
        df_uncertain['simple_payback_years_high'] = np.where(
            bill_low > 0, capex / bill_low, np.inf
        )

        bill_high = df_uncertain[f'{bill_col}_high']
        df_uncertain['simple_payback_years_low'] = np.where(
            bill_high > 0, capex / bill_high, np.inf
        )

        logger.info("  Calculated payback uncertainty ranges")

    # Log summary
    n_anomalies = is_anomaly.sum()
    if n_anomalies > 0:
        logger.info(f"  {n_anomalies:,} properties with anomaly flag get wider uncertainty ({anomaly_low*100:.0f}% to +{anomaly_high*100:.0f}%)")

    return df_uncertain


def generate_uncertainty_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Generate summary statistics showing uncertainty ranges.

    Args:
        df: DataFrame with uncertainty columns applied

    Returns:
        Summary DataFrame showing baseline, low, and high estimates
    """
    summary_rows = []

    # Find columns with _baseline suffix
    baseline_cols = [c for c in df.columns if c.endswith('_baseline')]

    for base_col in baseline_cols:
        metric_name = base_col.replace('_baseline', '')
        low_col = f'{metric_name}_low'
        high_col = f'{metric_name}_high'

        if low_col in df.columns and high_col in df.columns:
            summary_rows.append({
                'metric': metric_name,
                'baseline_mean': df[base_col].mean(),
                'low_mean': df[low_col].mean(),
                'high_mean': df[high_col].mean(),
                'baseline_total': df[base_col].sum(),
                'low_total': df[low_col].sum(),
                'high_total': df[high_col].sum(),
            })

    # Add payback if available
    if 'simple_payback_years_low' in df.columns:
        finite_baseline = df[np.isfinite(df['simple_payback_years'])] if 'simple_payback_years' in df.columns else df
        finite_low = df[np.isfinite(df['simple_payback_years_low'])]
        finite_high = df[np.isfinite(df['simple_payback_years_high'])]

        summary_rows.append({
            'metric': 'simple_payback_years',
            'baseline_mean': finite_baseline['simple_payback_years'].mean() if 'simple_payback_years' in finite_baseline.columns else np.nan,
            'low_mean': finite_high['simple_payback_years_low'].mean() if len(finite_high) > 0 else np.nan,  # Note: low payback from high savings
            'high_mean': finite_low['simple_payback_years_high'].mean() if len(finite_low) > 0 else np.nan,
            'baseline_total': np.nan,
            'low_total': np.nan,
            'high_total': np.nan,
        })

    return pd.DataFrame(summary_rows)
