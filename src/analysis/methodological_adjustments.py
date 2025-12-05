"""
Methodological Adjustments Module

Implements evidence-based adjustments to improve analysis accuracy:
- Prebound effect adjustment (Few et al., 2023)
- Heat pump flow temperature modeling
- Measurement error and confidence intervals (Crawley et al., 2019)
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple
from loguru import logger


class MethodologicalAdjustments:
    """Apply evidence-based methodological adjustments to EPC analysis."""

    # Prebound effect factors from Few et al. (2023)
    # EPCs systematically overpredict energy consumption, especially for lower-rated homes
    PREBOUND_FACTORS = {
        'A': 1.00,  # No adjustment needed
        'B': 1.00,  # No adjustment needed
        'C': 0.92,  # 8% overprediction
        'D': 0.82,  # 18% overprediction
        'E': 0.72,  # 28% overprediction
        'F': 0.55,  # 45% overprediction
        'G': 0.52,  # 48% overprediction
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
        logger.info("Initialized Methodological Adjustments")

    def apply_prebound_adjustment(self, df: pd.DataFrame) -> pd.DataFrame:
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

        Returns:
            DataFrame with adjusted energy consumption columns
        """
        logger.info("Applying prebound effect adjustment...")

        df_adj = df.copy()

        # Get EPC band
        if 'CURRENT_ENERGY_RATING' not in df.columns:
            logger.warning("CURRENT_ENERGY_RATING column not found, skipping prebound adjustment")
            return df

        # Map band to factor
        df_adj['prebound_factor'] = df_adj['CURRENT_ENERGY_RATING'].map(self.PREBOUND_FACTORS)

        # Default to D band factor (0.82) for missing values
        df_adj['prebound_factor'] = df_adj['prebound_factor'].fillna(0.82)

        # Apply adjustment to energy consumption (which is already in kWh/m²/year)
        if 'ENERGY_CONSUMPTION_CURRENT' in df.columns:
            df_adj['energy_consumption_adjusted'] = (
                df_adj['ENERGY_CONSUMPTION_CURRENT'] * df_adj['prebound_factor']
            )

            # Calculate absolute consumption for cost calculations
            if 'TOTAL_FLOOR_AREA' in df.columns:
                df_adj['baseline_consumption_kwh_year'] = (
                    df_adj['energy_consumption_adjusted'] * df_adj['TOTAL_FLOOR_AREA']
                )

        logger.info(f"✓ Prebound adjustment applied")

        # Log impact
        if 'ENERGY_CONSUMPTION_CURRENT' in df.columns and 'energy_consumption_adjusted' in df_adj.columns:
            original_mean = df['ENERGY_CONSUMPTION_CURRENT'].mean()
            adjusted_mean = df_adj['energy_consumption_adjusted'].mean()
            reduction_pct = (1 - adjusted_mean / original_mean) * 100
            logger.info(f"  Original mean: {original_mean:.1f} kWh/m²/year")
            logger.info(f"  Adjusted mean: {adjusted_mean:.1f} kWh/m²/year")
            logger.info(f"  Reduction: {reduction_pct:.1f}% (more realistic baseline)")

        return df_adj

    def estimate_flow_temperature(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Estimate required flow temperature for heat pumps based on fabric performance.

        Heat pumps operate efficiently at 35-55°C. Older radiators sized for
        70-80°C gas boilers may need upsizing (typically 2-2.5× larger surface area).

        Args:
            df: DataFrame with EPC fields

        Returns:
            DataFrame with flow temperature estimates and emitter upgrade needs
        """
        logger.info("Estimating heat pump flow temperature requirements...")

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

        Args:
            df: Raw validated DataFrame

        Returns:
            DataFrame with all adjustments applied
        """
        logger.info("Applying all methodological adjustments...")

        df_adjusted = df.copy()

        # 1. Prebound effect (must be first - affects baseline)
        df_adjusted = self.apply_prebound_adjustment(df_adjusted)

        # 2. Flow temperature model (for heat pump costing)
        df_adjusted = self.estimate_flow_temperature(df_adjusted)

        # 3. Measurement uncertainty (for reporting)
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
            'flow_temperature': {},
            'uncertainty': {}
        }

        # Prebound summary
        if 'prebound_factor' in df.columns:
            summary['prebound_adjustment'] = {
                'applied': True,
                'mean_factor': df['prebound_factor'].mean(),
                'description': 'Adjusts EPC-modeled consumption to realistic baseline (Few et al., 2023)'
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
