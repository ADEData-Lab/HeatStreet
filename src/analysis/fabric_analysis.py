"""
Fabric Analysis Module

Generates detailed fabric breakdown summaries and outputs for Edwardian terraces.
Produces CSV and parquet outputs for downstream analysis and visualization.

Outputs:
- epc_fabric_breakdown_summary.csv: Aggregated fabric statistics
- epc_clean_properties.parquet: Property-level cleaned data
- epc_fabric_breakdown_by_tenure.csv: Tenure-segmented summary
- epc_anomalies_summary.csv: EPC anomaly breakdown
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Optional, List
from loguru import logger

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import (
    load_config,
    DATA_PROCESSED_DIR,
    DATA_OUTPUTS_DIR
)
from src.cleaning.data_validator import filter_properties, flag_epc_anomalies


class FabricAnalyzer:
    """
    Analyzes building fabric characteristics from EPC data.

    Generates summary tables and property-level outputs for fabric breakdown.
    """

    def __init__(self, output_dir: Optional[Path] = None):
        """
        Initialize the fabric analyzer.

        Args:
            output_dir: Directory for outputs. Defaults to DATA_OUTPUTS_DIR.
        """
        self.config = load_config()
        self.output_dir = output_dir or DATA_OUTPUTS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Initialized Fabric Analyzer")

    def generate_fabric_breakdown_summary(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate aggregated fabric breakdown summary.

        Args:
            df: DataFrame with standardized fabric fields

        Returns:
            Summary DataFrame with fabric statistics

        Output file: epc_fabric_breakdown_summary.csv
        """
        logger.info("Generating fabric breakdown summary...")

        n_properties = len(df)
        summary_rows = []

        # ---- Wall type breakdown ----
        if 'wall_type' in df.columns:
            wall_type_counts = df['wall_type'].value_counts()
            for wall_type, count in wall_type_counts.items():
                summary_rows.append({
                    'category': 'wall_type',
                    'subcategory': wall_type,
                    'count': count,
                    'share_pct': count / n_properties * 100
                })

        # ---- Wall insulation status breakdown ----
        if 'wall_insulation_status' in df.columns:
            wall_insul_counts = df['wall_insulation_status'].value_counts()
            for status, count in wall_insul_counts.items():
                summary_rows.append({
                    'category': 'wall_insulation_status',
                    'subcategory': status,
                    'count': count,
                    'share_pct': count / n_properties * 100
                })

        # ---- Wall type × insulation status cross-tabulation ----
        if 'wall_type' in df.columns and 'wall_insulation_status' in df.columns:
            cross_tab = pd.crosstab(df['wall_type'], df['wall_insulation_status'])
            for wall_type in cross_tab.index:
                for insul_status in cross_tab.columns:
                    count = cross_tab.loc[wall_type, insul_status]
                    if count > 0:
                        summary_rows.append({
                            'category': 'wall_type_x_insulation',
                            'subcategory': f'{wall_type}|{insul_status}',
                            'count': count,
                            'share_pct': count / n_properties * 100
                        })

        # ---- Roof insulation distribution ----
        if 'roof_insulation_thickness_mm' in df.columns:
            roof_thickness = df['roof_insulation_thickness_mm'].dropna()
            if len(roof_thickness) > 0:
                summary_rows.extend([
                    {'category': 'roof_insulation_thickness_mm', 'subcategory': 'median',
                     'count': roof_thickness.median(), 'share_pct': np.nan},
                    {'category': 'roof_insulation_thickness_mm', 'subcategory': 'q25',
                     'count': roof_thickness.quantile(0.25), 'share_pct': np.nan},
                    {'category': 'roof_insulation_thickness_mm', 'subcategory': 'q75',
                     'count': roof_thickness.quantile(0.75), 'share_pct': np.nan},
                    {'category': 'roof_insulation_thickness_mm', 'subcategory': 'below_100mm',
                     'count': (roof_thickness < 100).sum(),
                     'share_pct': (roof_thickness < 100).sum() / len(roof_thickness) * 100},
                    {'category': 'roof_insulation_thickness_mm', 'subcategory': 'below_200mm',
                     'count': (roof_thickness < 200).sum(),
                     'share_pct': (roof_thickness < 200).sum() / len(roof_thickness) * 100},
                    {'category': 'roof_insulation_thickness_mm', 'subcategory': 'above_270mm',
                     'count': (roof_thickness >= 270).sum(),
                     'share_pct': (roof_thickness >= 270).sum() / len(roof_thickness) * 100},
                ])

        # ---- Roof insulation category breakdown ----
        if 'roof_insulation_category' in df.columns:
            roof_cat_counts = df['roof_insulation_category'].value_counts()
            for cat, count in roof_cat_counts.items():
                summary_rows.append({
                    'category': 'roof_insulation_category',
                    'subcategory': cat,
                    'count': count,
                    'share_pct': count / n_properties * 100
                })

        # ---- Floor insulation breakdown ----
        if 'floor_insulation' in df.columns:
            floor_counts = df['floor_insulation'].value_counts()
            for floor_status, count in floor_counts.items():
                summary_rows.append({
                    'category': 'floor_insulation',
                    'subcategory': floor_status,
                    'count': count,
                    'share_pct': count / n_properties * 100
                })

        # ---- Glazing type breakdown ----
        if 'glazing_type' in df.columns:
            glazing_counts = df['glazing_type'].value_counts()
            for glazing, count in glazing_counts.items():
                summary_rows.append({
                    'category': 'glazing_type',
                    'subcategory': glazing,
                    'count': count,
                    'share_pct': count / n_properties * 100
                })

        # ---- Ventilation type breakdown ----
        if 'ventilation_type' in df.columns:
            vent_counts = df['ventilation_type'].value_counts()
            for vent, count in vent_counts.items():
                summary_rows.append({
                    'category': 'ventilation_type',
                    'subcategory': vent,
                    'count': count,
                    'share_pct': count / n_properties * 100
                })

        # ---- Total properties ----
        summary_rows.append({
            'category': 'total',
            'subcategory': 'n_properties',
            'count': n_properties,
            'share_pct': 100.0
        })

        summary_df = pd.DataFrame(summary_rows)

        # Save to CSV
        output_path = self.output_dir / "epc_fabric_breakdown_summary.csv"
        summary_df.to_csv(output_path, index=False)
        logger.info(f"Saved fabric breakdown summary to {output_path}")

        return summary_df

    def generate_tenure_segmented_summary(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate fabric breakdown segmented by tenure type.

        Args:
            df: DataFrame with standardized fabric and tenure fields

        Returns:
            Summary DataFrame grouped by tenure

        Output file: epc_fabric_breakdown_by_tenure.csv
        """
        logger.info("Generating tenure-segmented fabric breakdown...")

        if 'tenure' not in df.columns:
            logger.warning("tenure column not found, skipping tenure segmentation")
            return pd.DataFrame()

        summary_rows = []

        for tenure in df['tenure'].unique():
            df_tenure = df[df['tenure'] == tenure]
            n_tenure = len(df_tenure)

            if n_tenure == 0:
                continue

            row = {
                'tenure': tenure,
                'n_properties': n_tenure,
                'share_of_total_pct': n_tenure / len(df) * 100
            }

            # Wall type distribution
            if 'wall_type' in df.columns:
                wall_counts = df_tenure['wall_type'].value_counts(normalize=True) * 100
                for wt in ['solid_brick', 'cavity', 'stone', 'other']:
                    row[f'wall_type_{wt}_pct'] = wall_counts.get(wt, 0)

            # Wall insulation
            if 'wall_insulated' in df.columns:
                row['wall_insulated_pct'] = df_tenure['wall_insulated'].mean() * 100

            # Roof insulation
            if 'roof_insulation_thickness_mm' in df.columns:
                thickness = df_tenure['roof_insulation_thickness_mm'].dropna()
                row['roof_insulation_median_mm'] = thickness.median() if len(thickness) > 0 else np.nan
                row['roof_below_100mm_pct'] = ((thickness < 100).sum() / len(thickness) * 100) if len(thickness) > 0 else np.nan

            # Floor insulation
            if 'floor_insulation_present' in df.columns:
                row['floor_insulation_pct'] = df_tenure['floor_insulation_present'].mean() * 100

            # Glazing
            if 'glazing_type' in df.columns:
                glazing_counts = df_tenure['glazing_type'].value_counts(normalize=True) * 100
                row['single_glazed_pct'] = glazing_counts.get('single', 0)
                row['double_glazed_pct'] = glazing_counts.get('double', 0)
                row['triple_glazed_pct'] = glazing_counts.get('triple', 0)

            # EPC band distribution
            if 'CURRENT_ENERGY_RATING' in df.columns:
                band_counts = df_tenure['CURRENT_ENERGY_RATING'].value_counts(normalize=True) * 100
                for band in ['A', 'B', 'C', 'D', 'E', 'F', 'G']:
                    row[f'epc_band_{band}_pct'] = band_counts.get(band, 0)

            summary_rows.append(row)

        summary_df = pd.DataFrame(summary_rows)

        # Save to CSV
        output_path = self.output_dir / "epc_fabric_breakdown_by_tenure.csv"
        summary_df.to_csv(output_path, index=False)
        logger.info(f"Saved tenure-segmented breakdown to {output_path}")

        return summary_df

    def generate_anomalies_summary(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate summary of EPC anomalies by band and anomaly type.

        Args:
            df: DataFrame with anomaly flags (from flag_epc_anomalies)

        Returns:
            Summary DataFrame with anomaly counts and shares

        Output file: epc_anomalies_summary.csv
        """
        logger.info("Generating EPC anomalies summary...")

        # Ensure anomaly flags exist
        if 'is_epc_fabric_anomaly' not in df.columns:
            df = flag_epc_anomalies(df)

        summary_rows = []
        n_total = len(df)
        n_anomalies = df['is_epc_fabric_anomaly'].sum()

        # Overall summary
        summary_rows.append({
            'group_by': 'total',
            'group_value': 'all_properties',
            'n_properties': n_total,
            'n_anomalies': n_anomalies,
            'anomaly_rate_pct': n_anomalies / n_total * 100 if n_total > 0 else 0
        })

        # By EPC band
        if 'CURRENT_ENERGY_RATING' in df.columns:
            for band in ['A', 'B', 'C', 'D', 'E', 'F', 'G']:
                df_band = df[df['CURRENT_ENERGY_RATING'] == band]
                n_band = len(df_band)
                n_band_anomalies = df_band['is_epc_fabric_anomaly'].sum() if n_band > 0 else 0

                summary_rows.append({
                    'group_by': 'epc_band',
                    'group_value': band,
                    'n_properties': n_band,
                    'n_anomalies': n_band_anomalies,
                    'anomaly_rate_pct': n_band_anomalies / n_band * 100 if n_band > 0 else 0
                })

        # By anomaly reason
        if 'anomaly_reason' in df.columns:
            df_anomalies = df[df['is_epc_fabric_anomaly']]
            if len(df_anomalies) > 0:
                # Handle multiple reasons separated by semicolons
                reason_counts = {}
                for reasons in df_anomalies['anomaly_reason']:
                    for reason in str(reasons).split(';'):
                        reason = reason.strip()
                        if reason:
                            reason_counts[reason] = reason_counts.get(reason, 0) + 1

                for reason, count in reason_counts.items():
                    summary_rows.append({
                        'group_by': 'anomaly_reason',
                        'group_value': reason,
                        'n_properties': np.nan,
                        'n_anomalies': count,
                        'anomaly_rate_pct': count / n_anomalies * 100 if n_anomalies > 0 else 0
                    })

        # By wall insulation status (among anomalies)
        if 'wall_insulation_status' in df.columns:
            for status in df['wall_insulation_status'].unique():
                df_status = df[df['wall_insulation_status'] == status]
                n_status = len(df_status)
                n_status_anomalies = df_status['is_epc_fabric_anomaly'].sum() if n_status > 0 else 0

                summary_rows.append({
                    'group_by': 'wall_insulation_status',
                    'group_value': status,
                    'n_properties': n_status,
                    'n_anomalies': n_status_anomalies,
                    'anomaly_rate_pct': n_status_anomalies / n_status * 100 if n_status > 0 else 0
                })

        summary_df = pd.DataFrame(summary_rows)

        # Save to CSV
        output_path = self.output_dir / "epc_anomalies_summary.csv"
        summary_df.to_csv(output_path, index=False)
        logger.info(f"Saved anomalies summary to {output_path}")

        return summary_df

    def export_clean_properties(self, df: pd.DataFrame) -> Path:
        """
        Export cleaned property-level dataset with fabric variables.

        Args:
            df: DataFrame with standardized fabric fields

        Returns:
            Path to output parquet file

        Output file: epc_clean_properties.parquet
        """
        logger.info("Exporting clean properties dataset...")

        # Select columns to include
        fabric_columns = [
            'wall_type', 'wall_insulation_status', 'wall_insulated',
            'roof_insulation_thickness_mm', 'roof_insulation_category',
            'floor_insulation', 'floor_insulation_present',
            'glazing_type', 'ventilation_type', 'tenure',
            'is_epc_fabric_anomaly', 'anomaly_reason'
        ]

        # Core EPC columns to retain
        core_columns = [
            'LMK_KEY', 'ADDRESS', 'ADDRESS1', 'ADDRESS2', 'POSTCODE',
            'UPRN', 'LOCAL_AUTHORITY',
            'PROPERTY_TYPE', 'BUILT_FORM', 'CONSTRUCTION_AGE_BAND',
            'TOTAL_FLOOR_AREA',
            'CURRENT_ENERGY_RATING', 'CURRENT_ENERGY_EFFICIENCY',
            'POTENTIAL_ENERGY_RATING', 'POTENTIAL_ENERGY_EFFICIENCY',
            'ENERGY_CONSUMPTION_CURRENT', 'CO2_EMISSIONS_CURRENT',
            'MAINHEAT_DESCRIPTION', 'heating_system_type',
            'WALLS_DESCRIPTION', 'ROOF_DESCRIPTION', 'FLOOR_DESCRIPTION',
            'WINDOWS_DESCRIPTION',
            'LODGEMENT_DATE'
        ]

        # Build column list (only include columns that exist)
        all_columns = []
        for col in core_columns + fabric_columns:
            if col in df.columns:
                all_columns.append(col)

        # Remove duplicates while preserving order
        all_columns = list(dict.fromkeys(all_columns))

        df_export = df[all_columns].copy()

        # Save to parquet
        output_path = self.output_dir / "epc_clean_properties.parquet"
        df_export.to_parquet(output_path, index=False)
        logger.info(f"Saved {len(df_export):,} clean properties to {output_path}")

        # Also save a CSV version for easier inspection
        csv_path = self.output_dir / "epc_clean_properties.csv"
        df_export.to_csv(csv_path, index=False)
        logger.info(f"Also saved CSV version to {csv_path}")

        return output_path

    def run_full_analysis(self, df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
        """
        Run complete fabric analysis and generate all outputs.

        Args:
            df: Validated EPC DataFrame

        Returns:
            Dictionary with all generated DataFrames
        """
        logger.info("Running full fabric analysis...")

        # Ensure anomaly flags exist
        if 'is_epc_fabric_anomaly' not in df.columns:
            df = flag_epc_anomalies(df)

        results = {}

        # Generate all summaries
        results['fabric_summary'] = self.generate_fabric_breakdown_summary(df)
        results['tenure_summary'] = self.generate_tenure_segmented_summary(df)
        results['anomalies_summary'] = self.generate_anomalies_summary(df)

        # Export clean properties
        self.export_clean_properties(df)

        logger.info("Full fabric analysis complete!")

        return results


def main():
    """Main execution function for fabric analysis."""
    logger.info("Starting fabric analysis...")

    # Load validated data
    input_file = DATA_PROCESSED_DIR / "epc_london_validated.parquet"

    if not input_file.exists():
        # Try CSV fallback
        input_file = DATA_PROCESSED_DIR / "epc_london_validated.csv"
        if not input_file.exists():
            logger.error(f"Input file not found: {input_file}")
            logger.info("Please run data validation first")
            return

    logger.info(f"Loading data from: {input_file}")
    if input_file.suffix == '.parquet':
        df = pd.read_parquet(input_file)
    else:
        df = pd.read_csv(input_file)

    # Run analysis
    analyzer = FabricAnalyzer()
    results = analyzer.run_full_analysis(df)

    # Log summary
    logger.info("\nFabric Analysis Summary:")
    logger.info(f"  Total properties analyzed: {len(df):,}")

    if 'fabric_summary' in results:
        logger.info(f"  Fabric summary rows: {len(results['fabric_summary'])}")

    if 'anomalies_summary' in results:
        total_row = results['anomalies_summary'][
            results['anomalies_summary']['group_value'] == 'all_properties'
        ]
        if len(total_row) > 0:
            n_anomalies = total_row['n_anomalies'].values[0]
            anomaly_rate = total_row['anomaly_rate_pct'].values[0]
            logger.info(f"  EPC anomalies: {n_anomalies:,} ({anomaly_rate:.1f}%)")

    logger.info("Fabric analysis complete!")


if __name__ == "__main__":
    main()
