"""
Archetype Characterization Module

Produces summary statistics and distributions for Edwardian terraced housing stock.
Implements Section 3.1 of the project specification.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional
import matplotlib.pyplot as plt
import seaborn as sns
from loguru import logger
from concurrent.futures import ThreadPoolExecutor, as_completed

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import (
    load_config,
    DATA_PROCESSED_DIR,
    DATA_OUTPUTS_DIR
)


class ArchetypeAnalyzer:
    """
    Analyzes EPC data to characterize the Edwardian terraced housing archetype.
    """

    def __init__(self):
        """Initialize the archetype analyzer."""
        self.config = load_config()
        self.results = {}

        # Set visualization style
        sns.set_style("whitegrid")
        plt.rcParams['figure.figsize'] = (12, 8)

        logger.info("Initialized Archetype Analyzer")

    def analyze_archetype(self, df: pd.DataFrame, use_parallel: bool = True) -> Dict:
        """
        Run complete archetype characterization analysis with parallel processing.

        Args:
            df: Validated EPC DataFrame
            use_parallel: Use parallel processing for independent analyses (default: True)

        Returns:
            Dictionary containing all analysis results
        """
        logger.info(f"Analyzing archetype for {len(df):,} properties...")

        if use_parallel:
            logger.info("Running analyses in parallel...")

            # Define all analysis functions with their keys
            analysis_tasks = [
                ('epc_bands', self.analyze_epc_bands),
                ('sap_scores', self.analyze_sap_scores),
                ('wall_construction', self.analyze_wall_construction),
                ('loft_insulation', self.analyze_loft_insulation),
                ('floor_insulation', self.analyze_floor_insulation),
                ('glazing', self.analyze_glazing),
                ('heating_systems', self.analyze_heating_systems),
                ('heating_controls', self.analyze_heating_controls),
                ('hot_water', self.analyze_hot_water),
                ('energy_consumption', self.analyze_energy_consumption),
                ('co2_emissions', self.analyze_co2_emissions)
            ]

            # Execute analyses in parallel using ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=8) as executor:
                # Submit all analysis tasks
                futures = {
                    executor.submit(func, df): key
                    for key, func in analysis_tasks
                }

                # Collect results as they complete
                for future in as_completed(futures):
                    key = futures[future]
                    try:
                        self.results[key] = future.result()
                    except Exception as e:
                        logger.error(f"Error in {key} analysis: {e}")
                        self.results[key] = {}

        else:
            # Sequential execution (fallback)
            self.results['epc_bands'] = self.analyze_epc_bands(df)
            self.results['sap_scores'] = self.analyze_sap_scores(df)
            self.results['wall_construction'] = self.analyze_wall_construction(df)
            self.results['loft_insulation'] = self.analyze_loft_insulation(df)
            self.results['floor_insulation'] = self.analyze_floor_insulation(df)
            self.results['glazing'] = self.analyze_glazing(df)
            self.results['heating_systems'] = self.analyze_heating_systems(df)
            self.results['heating_controls'] = self.analyze_heating_controls(df)
            self.results['hot_water'] = self.analyze_hot_water(df)
            self.results['energy_consumption'] = self.analyze_energy_consumption(df)
            self.results['co2_emissions'] = self.analyze_co2_emissions(df)

        logger.info("Archetype characterization complete!")
        return self.results

    def analyze_epc_bands(self, df: pd.DataFrame) -> Dict:
        """Analyze current EPC band distribution."""
        logger.info("Analyzing EPC band distribution...")

        if 'CURRENT_ENERGY_RATING' not in df.columns:
            logger.warning("CURRENT_ENERGY_RATING column not found")
            return {}

        # Frequency table
        freq_table = df['CURRENT_ENERGY_RATING'].value_counts().sort_index()
        freq_pct = df['CURRENT_ENERGY_RATING'].value_counts(normalize=True).sort_index() * 100

        results = {
            'frequency': freq_table.to_dict(),
            'percentage': freq_pct.to_dict(),
            'total': len(df)
        }

        logger.info(f"EPC Band Distribution:")
        for band in ['A', 'B', 'C', 'D', 'E', 'F', 'G']:
            if band in results['frequency']:
                logger.info(f"  Band {band}: {results['frequency'][band]:,} ({results['percentage'][band]:.1f}%)")

        return results

    def analyze_sap_scores(self, df: pd.DataFrame) -> Dict:
        """Analyze SAP score distribution."""
        logger.info("Analyzing SAP scores...")

        sap_columns = ['CURRENT_ENERGY_EFFICIENCY', 'ENERGY_RATING']
        sap_col = None

        for col in sap_columns:
            if col in df.columns:
                sap_col = col
                break

        if sap_col is None:
            logger.warning("No SAP score column found")
            return {}

        results = {
            'mean': float(df[sap_col].mean()),
            'median': float(df[sap_col].median()),
            'std': float(df[sap_col].std()),
            'min': float(df[sap_col].min()),
            'max': float(df[sap_col].max()),
            'percentiles': {
                '25th': float(df[sap_col].quantile(0.25)),
                '50th': float(df[sap_col].quantile(0.50)),
                '75th': float(df[sap_col].quantile(0.75)),
                '90th': float(df[sap_col].quantile(0.90))
            }
        }

        logger.info(f"SAP Score Statistics:")
        logger.info(f"  Mean: {results['mean']:.1f}")
        logger.info(f"  Median: {results['median']:.1f}")
        logger.info(f"  Std Dev: {results['std']:.1f}")

        return results

    def analyze_wall_construction(self, df: pd.DataFrame) -> Dict:
        """Analyze wall construction types and insulation status."""
        logger.info("Analyzing wall construction...")

        if 'wall_type' not in df.columns or 'wall_insulated' not in df.columns:
            logger.warning("Standardized wall columns not found")
            return {}

        # Wall type distribution
        wall_types = df['wall_type'].value_counts().to_dict()

        # Insulation status
        insulated_count = df['wall_insulated'].sum()
        total = len(df)
        insulation_rate = (insulated_count / total * 100) if total > 0 else 0

        # Cross-tabulation
        wall_insulation_crosstab = pd.crosstab(
            df['wall_type'],
            df['wall_insulated'],
            normalize='index'
        ) * 100

        results = {
            'wall_types': wall_types,
            'insulation_rate': float(insulation_rate),
            'insulated_count': int(insulated_count),
            'uninsulated_count': int(total - insulated_count),
            'crosstab': wall_insulation_crosstab.to_dict()
        }

        logger.info(f"Wall Construction:")
        for wall_type, count in wall_types.items():
            logger.info(f"  {wall_type}: {count:,}")
        logger.info(f"  Insulation rate: {insulation_rate:.1f}%")

        return results

    def analyze_loft_insulation(self, df: pd.DataFrame) -> Dict:
        """
        Analyze loft insulation status and thickness.

        Implements tiered confidence approach:
        - High confidence: Explicit thickness mentioned or 'no insulation'
        - Medium confidence: Efficiency rating available (Good/Poor etc)
        - Low confidence: Unknown - requires survey
        """
        logger.info("Analyzing loft insulation...")

        loft_col = None
        for col in ['ROOF_DESCRIPTION', 'LOFT_INSULATION']:
            if col in df.columns:
                loft_col = col
                break

        # Also check for efficiency column
        eff_col = None
        for col in ['ROOF_ENERGY_EFF', 'ROOF_EFFICIENCY']:
            if col in df.columns:
                eff_col = col
                break

        if loft_col is None and eff_col is None:
            logger.warning("No loft insulation or roof efficiency column found")
            return {}

        # Initialize columns
        df['loft_category'] = 'Unknown'
        df['loft_confidence'] = 'low'
        df['loft_needs_work'] = 'unknown'
        df['loft_recommendation'] = 'Survey required'

        # Extract thickness from description
        import re
        if loft_col and loft_col in df.columns:
            loft_desc = df[loft_col].fillna('')

            # Extract thickness if present
            def extract_thickness(desc):
                match = re.search(r'(\d+)\s*mm', str(desc).lower())
                if match:
                    return int(match.group(1))
                return None

            df['loft_thickness_mm'] = loft_desc.apply(extract_thickness)

            # Categorize based on thickness
            # No insulation
            none_mask = loft_desc.str.contains('no insulation|0 mm|0mm|uninsulated', case=False, na=False)
            df.loc[none_mask, 'loft_category'] = 'None'
            df.loc[none_mask, 'loft_confidence'] = 'high'
            df.loc[none_mask, 'loft_needs_work'] = 'yes'
            df.loc[none_mask, 'loft_recommendation'] = 'Full loft insulation (270mm)'

            # Low thickness (<100mm)
            low_mask = (df['loft_thickness_mm'].notna()) & (df['loft_thickness_mm'] < 100)
            df.loc[low_mask, 'loft_category'] = 'Low (<100mm)'
            df.loc[low_mask, 'loft_confidence'] = 'high'
            df.loc[low_mask, 'loft_needs_work'] = 'yes'
            df.loc[low_mask, 'loft_recommendation'] = df.loc[low_mask, 'loft_thickness_mm'].apply(
                lambda x: f'Top-up from {int(x)}mm to 270mm' if pd.notna(x) else 'Top-up to 270mm'
            )

            # Partial (100-200mm)
            partial_mask = (df['loft_thickness_mm'].notna()) & (df['loft_thickness_mm'] >= 100) & (df['loft_thickness_mm'] < 200)
            df.loc[partial_mask, 'loft_category'] = 'Partial (100-200mm)'
            df.loc[partial_mask, 'loft_confidence'] = 'high'
            df.loc[partial_mask, 'loft_needs_work'] = 'yes'
            df.loc[partial_mask, 'loft_recommendation'] = df.loc[partial_mask, 'loft_thickness_mm'].apply(
                lambda x: f'Top-up from {int(x)}mm to 270mm' if pd.notna(x) else 'Top-up to 270mm'
            )

            # Good (200-270mm)
            good_mask = (df['loft_thickness_mm'].notna()) & (df['loft_thickness_mm'] >= 200) & (df['loft_thickness_mm'] < 270)
            df.loc[good_mask, 'loft_category'] = 'Good (200-269mm)'
            df.loc[good_mask, 'loft_confidence'] = 'high'
            df.loc[good_mask, 'loft_needs_work'] = 'optional'
            df.loc[good_mask, 'loft_recommendation'] = 'Minor top-up optional'

            # Full (270mm+)
            full_mask = (df['loft_thickness_mm'].notna()) & (df['loft_thickness_mm'] >= 270)
            df.loc[full_mask, 'loft_category'] = 'Full (≥270mm)'
            df.loc[full_mask, 'loft_confidence'] = 'high'
            df.loc[full_mask, 'loft_needs_work'] = 'no'
            df.loc[full_mask, 'loft_recommendation'] = 'Adequate'

        # Use efficiency column for remaining unknowns
        if eff_col and eff_col in df.columns:
            unknown_mask = df['loft_category'] == 'Unknown'

            very_poor_eff = unknown_mask & df[eff_col].isin(['Very Poor', 'very poor'])
            df.loc[very_poor_eff, 'loft_category'] = 'Very Poor (efficiency rating)'
            df.loc[very_poor_eff, 'loft_confidence'] = 'medium'
            df.loc[very_poor_eff, 'loft_needs_work'] = 'yes'
            df.loc[very_poor_eff, 'loft_recommendation'] = 'Likely needs insulation or top-up'

            poor_eff = unknown_mask & df[eff_col].isin(['Poor', 'poor'])
            df.loc[poor_eff, 'loft_category'] = 'Poor (efficiency rating)'
            df.loc[poor_eff, 'loft_confidence'] = 'medium'
            df.loc[poor_eff, 'loft_needs_work'] = 'likely'
            df.loc[poor_eff, 'loft_recommendation'] = 'Likely needs insulation or top-up'

            average_eff = unknown_mask & df[eff_col].isin(['Average', 'average'])
            df.loc[average_eff, 'loft_category'] = 'Average (efficiency rating)'
            df.loc[average_eff, 'loft_confidence'] = 'medium'
            df.loc[average_eff, 'loft_needs_work'] = 'possible'
            df.loc[average_eff, 'loft_recommendation'] = 'May need top-up'

            good_eff = unknown_mask & df[eff_col].isin(['Good', 'good', 'Very Good', 'very good'])
            df.loc[good_eff, 'loft_category'] = 'Good/Very Good (efficiency rating)'
            df.loc[good_eff, 'loft_confidence'] = 'medium'
            df.loc[good_eff, 'loft_needs_work'] = 'no'
            df.loc[good_eff, 'loft_recommendation'] = 'Likely adequate'

        # Remaining unknowns - conservative assumption but with low confidence
        still_unknown = df['loft_category'] == 'Unknown'
        df.loc[still_unknown, 'loft_needs_work'] = 'likely'  # Conservative
        df.loc[still_unknown, 'loft_recommendation'] = 'Unknown - assume top-up needed (conservative)'

        # Compile results
        loft_categories = df['loft_category'].value_counts().to_dict()
        loft_pct = df['loft_category'].value_counts(normalize=True).to_dict()
        confidence_dist = df['loft_confidence'].value_counts(normalize=True).to_dict()
        needs_work_dist = df['loft_needs_work'].value_counts().to_dict()

        results = {
            'categories': loft_categories,
            'percentages': {k: float(v*100) for k, v in loft_pct.items()},
            'confidence_distribution': {k: float(v*100) for k, v in confidence_dist.items()},
            'needs_work_distribution': needs_work_dist,
            'pct_definitely_need_work': float((df['loft_needs_work'] == 'yes').mean() * 100),
            'pct_likely_need_work': float((df['loft_needs_work'].isin(['yes', 'likely'])).mean() * 100),
            'pct_unknown': float((df['loft_category'] == 'Unknown').mean() * 100),
        }

        logger.info(f"Loft Insulation:")
        for category, count in loft_categories.items():
            pct = loft_pct.get(category, 0) * 100
            logger.info(f"  {category}: {count:,} ({pct:.1f}%)")
        logger.info(f"Confidence levels:")
        for level, pct in confidence_dist.items():
            logger.info(f"  {level}: {pct*100:.1f}%")
        logger.info(f"Need loft insulation (definitely + likely): {results['pct_likely_need_work']:.1f}%")

        return results

    def analyze_floor_insulation(self, df: pd.DataFrame) -> Dict:
        """Analyze floor insulation presence/absence."""
        logger.info("Analyzing floor insulation...")

        floor_col = None
        for col in ['FLOOR_DESCRIPTION', 'FLOOR_INSULATION']:
            if col in df.columns:
                floor_col = col
                break

        if floor_col is None:
            logger.warning("No floor insulation column found")
            return {}

        # Check for insulation presence
        insulated_mask = df[floor_col].str.contains(
            'insulated|insulation', case=False, na=False
        )

        insulated_count = insulated_mask.sum()
        total = len(df)
        insulation_rate = (insulated_count / total * 100) if total > 0 else 0

        results = {
            'insulated': int(insulated_count),
            'uninsulated': int(total - insulated_count),
            'insulation_rate': float(insulation_rate)
        }

        logger.info(f"Floor Insulation:")
        logger.info(f"  Insulated: {insulated_count:,} ({insulation_rate:.1f}%)")
        logger.info(f"  Uninsulated: {total - insulated_count:,} ({100-insulation_rate:.1f}%)")

        return results

    def analyze_glazing(self, df: pd.DataFrame) -> Dict:
        """Analyze window glazing types."""
        logger.info("Analyzing window glazing...")

        glazing_col = None
        for col in ['WINDOWS_DESCRIPTION', 'GLAZING_TYPE']:
            if col in df.columns:
                glazing_col = col
                break

        if glazing_col is None:
            logger.warning("No glazing column found")
            return {}

        # Categorize glazing types
        df['glazing_type'] = 'Unknown'

        single_mask = df[glazing_col].str.contains('single', case=False, na=False)
        double_mask = df[glazing_col].str.contains('double', case=False, na=False)
        triple_mask = df[glazing_col].str.contains('triple', case=False, na=False)

        df.loc[single_mask, 'glazing_type'] = 'Single'
        df.loc[double_mask, 'glazing_type'] = 'Double'
        df.loc[triple_mask, 'glazing_type'] = 'Triple'

        glazing_types = df['glazing_type'].value_counts().to_dict()
        glazing_pct = df['glazing_type'].value_counts(normalize=True).to_dict()

        results = {
            'types': glazing_types,
            'percentages': {k: float(v*100) for k, v in glazing_pct.items()}
        }

        logger.info(f"Window Glazing:")
        for glaze_type, count in glazing_types.items():
            pct = glazing_pct.get(glaze_type, 0) * 100
            logger.info(f"  {glaze_type}: {count:,} ({pct:.1f}%)")

        return results

    def analyze_heating_systems(self, df: pd.DataFrame) -> Dict:
        """Analyze primary heating systems and fuel types."""
        logger.info("Analyzing heating systems...")

        if 'heating_system_type' not in df.columns:
            logger.warning("Standardized heating system column not found")
            return {}

        heating_types = df['heating_system_type'].value_counts().to_dict()
        heating_pct = df['heating_system_type'].value_counts(normalize=True).to_dict()

        results = {
            'types': heating_types,
            'percentages': {k: float(v*100) for k, v in heating_pct.items()}
        }

        logger.info(f"Heating Systems:")
        for heat_type, count in heating_types.items():
            pct = heating_pct.get(heat_type, 0) * 100
            logger.info(f"  {heat_type}: {count:,} ({pct:.1f}%)")

        return results

    def analyze_heating_controls(self, df: pd.DataFrame) -> Dict:
        """
        Analyze heating control systems.

        EPC API field is 'mainheat-cont-description' which becomes
        'MAINHEAT_CONT_DESCRIPTION' after column standardization.
        """
        logger.info("Analyzing heating controls...")

        results = {}

        # Find heating controls column
        # EPC API uses 'mainheat-cont-description' -> 'MAINHEAT_CONT_DESCRIPTION'
        # Try multiple possible column names to handle variations
        control_col = None
        possible_cols = [
            'MAINHEAT_CONT_DESCRIPTION',  # Correct standardized name
            'MAINHEATCONT_DESCRIPTION',    # Alternative
            'MAIN_HEAT_CONT_DESCRIPTION',  # Another variation
            'HEATING_CONTROLS_DESCRIPTION',
            'MAIN_HEATING_CONTROLS',
        ]

        # Log available columns for debugging
        heating_related_cols = [col for col in df.columns if any(
            x in col.upper() for x in ['HEAT', 'CONT', 'CONTROL', 'TRV', 'THERM']
        )]
        if heating_related_cols:
            logger.debug(f"Heating-related columns found: {heating_related_cols}")

        for col in possible_cols:
            if col in df.columns:
                control_col = col
                logger.info(f"Using heating controls column: {control_col}")
                break

        if control_col:
            # Get non-null value count
            non_null_count = df[control_col].notna().sum()
            results['data_completeness'] = float(non_null_count / len(df) * 100)
            logger.info(f"  Data completeness: {results['data_completeness']:.1f}%")

            # TRV presence
            trv_mask = df[control_col].str.contains(
                'TRV|thermostatic radiator', case=False, na=False
            )
            results['trv_present'] = int(trv_mask.sum())
            results['trv_rate'] = float(trv_mask.sum() / len(df) * 100)

            # Programmer/timer presence
            programmer_mask = df[control_col].str.contains(
                'programmer|timer|time control', case=False, na=False
            )
            results['programmer_present'] = int(programmer_mask.sum())
            results['programmer_rate'] = float(programmer_mask.sum() / len(df) * 100)

            # Room thermostat
            thermostat_mask = df[control_col].str.contains(
                'room thermostat|roomstat', case=False, na=False
            )
            results['room_thermostat_present'] = int(thermostat_mask.sum())
            results['room_thermostat_rate'] = float(thermostat_mask.sum() / len(df) * 100)

            # Smart controls
            smart_mask = df[control_col].str.contains(
                'smart|learning|app|wireless', case=False, na=False
            )
            results['smart_controls_present'] = int(smart_mask.sum())
            results['smart_controls_rate'] = float(smart_mask.sum() / len(df) * 100)

            # Log sample values for debugging
            sample_values = df[control_col].dropna().head(5).tolist()
            if sample_values:
                logger.debug(f"Sample heating control values: {sample_values}")
        else:
            logger.warning("No heating controls column found. Available columns may not match expected names.")
            logger.warning(f"Available heating-related columns: {heating_related_cols}")
            results['error'] = 'No heating controls column found'

        logger.info(f"Heating Controls:")
        if 'trv_rate' in results:
            logger.info(f"  TRV present: {results.get('trv_present', 0):,} ({results.get('trv_rate', 0):.1f}%)")
        if 'programmer_rate' in results:
            logger.info(f"  Programmer/timer: {results.get('programmer_present', 0):,} ({results.get('programmer_rate', 0):.1f}%)")
        if 'room_thermostat_rate' in results:
            logger.info(f"  Room thermostat: {results.get('room_thermostat_present', 0):,} ({results.get('room_thermostat_rate', 0):.1f}%)")
        if 'smart_controls_rate' in results:
            logger.info(f"  Smart controls: {results.get('smart_controls_present', 0):,} ({results.get('smart_controls_rate', 0):.1f}%)")

        return results

    def analyze_hot_water(self, df: pd.DataFrame) -> Dict:
        """Analyze hot water systems."""
        logger.info("Analyzing hot water systems...")

        hotwater_col = None
        for col in ['HOTWATER_DESCRIPTION', 'HOT_WATER_SYSTEM']:
            if col in df.columns:
                hotwater_col = col
                break

        if hotwater_col is None:
            logger.warning("No hot water system column found")
            return {}

        # Categorize hot water systems
        df['hotwater_type'] = 'Other'

        immersion_mask = df[hotwater_col].str.contains('immersion', case=False, na=False)
        combi_mask = df[hotwater_col].str.contains('combi', case=False, na=False)
        system_mask = df[hotwater_col].str.contains('system', case=False, na=False)

        df.loc[immersion_mask, 'hotwater_type'] = 'Immersion'
        df.loc[combi_mask, 'hotwater_type'] = 'Combi'
        df.loc[system_mask, 'hotwater_type'] = 'System Boiler'

        hotwater_types = df['hotwater_type'].value_counts().to_dict()
        hotwater_pct = df['hotwater_type'].value_counts(normalize=True).to_dict()

        results = {
            'types': hotwater_types,
            'percentages': {k: float(v*100) for k, v in hotwater_pct.items()}
        }

        logger.info(f"Hot Water Systems:")
        for hw_type, count in hotwater_types.items():
            pct = hotwater_pct.get(hw_type, 0) * 100
            logger.info(f"  {hw_type}: {count:,} ({pct:.1f}%)")

        return results

    def analyze_energy_consumption(self, df: pd.DataFrame) -> Dict:
        """Analyze current energy consumption estimates."""
        logger.info("Analyzing energy consumption...")

        if 'energy_kwh_per_m2_year' not in df.columns:
            logger.warning("Normalized energy consumption column not found")
            return {}

        results = {
            'mean': float(df['energy_kwh_per_m2_year'].mean()),
            'median': float(df['energy_kwh_per_m2_year'].median()),
            'std': float(df['energy_kwh_per_m2_year'].std()),
            'min': float(df['energy_kwh_per_m2_year'].min()),
            'max': float(df['energy_kwh_per_m2_year'].max()),
            'percentiles': {
                '25th': float(df['energy_kwh_per_m2_year'].quantile(0.25)),
                '50th': float(df['energy_kwh_per_m2_year'].quantile(0.50)),
                '75th': float(df['energy_kwh_per_m2_year'].quantile(0.75)),
                '90th': float(df['energy_kwh_per_m2_year'].quantile(0.90))
            }
        }

        logger.info(f"Energy Consumption (kWh/m²/year):")
        logger.info(f"  Mean: {results['mean']:.1f}")
        logger.info(f"  Median: {results['median']:.1f}")

        return results

    def analyze_co2_emissions(self, df: pd.DataFrame) -> Dict:
        """Analyze current CO2 emissions estimates."""
        logger.info("Analyzing CO2 emissions...")

        if 'co2_kg_per_m2_year' not in df.columns:
            logger.warning("Normalized CO2 emissions column not found")
            return {}

        results = {
            'mean': float(df['co2_kg_per_m2_year'].mean()),
            'median': float(df['co2_kg_per_m2_year'].median()),
            'std': float(df['co2_kg_per_m2_year'].std()),
            'min': float(df['co2_kg_per_m2_year'].min()),
            'max': float(df['co2_kg_per_m2_year'].max()),
            'percentiles': {
                '25th': float(df['co2_kg_per_m2_year'].quantile(0.25)),
                '50th': float(df['co2_kg_per_m2_year'].quantile(0.50)),
                '75th': float(df['co2_kg_per_m2_year'].quantile(0.75)),
                '90th': float(df['co2_kg_per_m2_year'].quantile(0.90))
            }
        }

        logger.info(f"CO2 Emissions (kg/m²/year):")
        logger.info(f"  Mean: {results['mean']:.1f}")
        logger.info(f"  Median: {results['median']:.1f}")

        return results

    def save_results(self, output_path: Optional[Path] = None):
        """
        Save analysis results to file.

        Args:
            output_path: Path to save results
        """
        if output_path is None:
            output_path = DATA_OUTPUTS_DIR / "archetype_analysis_results.txt"

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("ARCHETYPE CHARACTERIZATION RESULTS\n")
            f.write("="*70 + "\n\n")

            for section, data in self.results.items():
                f.write(f"\n{section.replace('_', ' ').upper()}\n")
                f.write("-"*70 + "\n")
                f.write(str(data) + "\n")

        logger.info(f"Results saved to: {output_path}")


def main():
    """Main execution function for archetype analysis."""
    logger.info("Starting archetype characterization...")

    # Load validated data
    input_file = DATA_PROCESSED_DIR / "epc_validated.csv"

    if not input_file.exists():
        logger.error(f"Input file not found: {input_file}")
        logger.info("Please run data validation first")
        return

    logger.info(f"Loading data from: {input_file}")
    df = pd.read_csv(input_file, low_memory=False)

    # Perform analysis
    analyzer = ArchetypeAnalyzer()
    results = analyzer.analyze_archetype(df)

    # Save results
    analyzer.save_results()

    logger.info("Archetype characterization complete!")


if __name__ == "__main__":
    main()
