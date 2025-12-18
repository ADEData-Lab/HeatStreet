"""
EPC Data Cleaning and Validation Module

Implements quality assurance checks based on Hardy and Glew's findings
that 36-62% of EPCs contain errors.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from loguru import logger
from datetime import datetime

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import (
    load_config,
    get_data_quality_thresholds,
    DATA_RAW_DIR,
    DATA_PROCESSED_DIR
)


class EPCDataValidator:
    """
    Validates and cleans EPC data according to quality assurance protocols.
    """

    def __init__(self):
        """Initialize the validator with configuration settings."""
        self.config = load_config()
        self.quality_thresholds = get_data_quality_thresholds()
        self.validation_report = {
            'total_records': 0,
            'duplicates_removed': 0,
            'implausible_floor_areas': 0,
            'inconsistent_built_form': 0,
            'missing_critical_fields': 0,
            'construction_date_mismatches': 0,
            'illogical_insulation': 0,
            'negative_energy_values': 0,
            'negative_co2_values': 0,
            'records_passed': 0
        }

        logger.info("Initialized EPC Data Validator")

    def validate_dataset(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict]:
        """
        Run complete validation pipeline on EPC dataset.

        Args:
            df: Raw EPC DataFrame

        Returns:
            Tuple of (validated DataFrame, validation report)
        """
        self.validation_report['total_records'] = len(df)
        logger.info(f"Starting validation of {len(df):,} records...")

        # Standardize column names first (EPC API uses hyphens, we need underscores)
        df = self._standardize_column_names(df)

        # Run validation checks in sequence
        df = self.remove_duplicates(df)
        df = self.validate_floor_areas(df)
        df = self.validate_energy_and_emissions(df)
        df = self.validate_built_form(df)
        df = self.validate_critical_fields(df)
        df = self.validate_construction_dates(df)
        df = self.validate_insulation_logic(df)
        df = self.standardize_fields(df)

        self.validation_report['records_passed'] = len(df)
        self.log_validation_summary()

        return df, self.validation_report

    def _standardize_column_names(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardize column names from EPC API format (hyphenated) to expected format (uppercase with underscores).

        Args:
            df: DataFrame with EPC API column names

        Returns:
            DataFrame with standardized column names
        """
        logger.info("Standardizing column names from EPC API format...")

        # Convert hyphenated lowercase to uppercase with underscores
        # e.g., 'current-energy-rating' -> 'CURRENT_ENERGY_RATING'
        df.columns = df.columns.str.replace('-', '_').str.upper()

        logger.info(f"Standardized {len(df.columns)} column names")

        return df

    def validate_energy_and_emissions(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Remove or clamp negative energy consumption and CO₂ emission values.

        Args:
            df: EPC DataFrame

        Returns:
            DataFrame with negative energy/CO₂ values removed
        """
        logger.info("Validating energy and CO₂ metrics for negative values...")

        energy_negatives = 0
        co2_negatives = 0

        if 'ENERGY_CONSUMPTION_CURRENT' in df.columns:
            energy_series = pd.to_numeric(df['ENERGY_CONSUMPTION_CURRENT'], errors='coerce')
            energy_negatives = (energy_series < 0).sum()

        if 'CO2_EMISSIONS_CURRENT' in df.columns:
            co2_series = pd.to_numeric(df['CO2_EMISSIONS_CURRENT'], errors='coerce')
            co2_negatives = (co2_series < 0).sum()

        removal_mask = pd.Series(False, index=df.index)

        if energy_negatives > 0:
            logger.warning(f"Found {energy_negatives:,} records with negative ENERGY_CONSUMPTION_CURRENT")
            removal_mask |= pd.to_numeric(df['ENERGY_CONSUMPTION_CURRENT'], errors='coerce') < 0

        if co2_negatives > 0:
            logger.warning(f"Found {co2_negatives:,} records with negative CO2_EMISSIONS_CURRENT")
            removal_mask |= pd.to_numeric(df['CO2_EMISSIONS_CURRENT'], errors='coerce') < 0

        removed_count = removal_mask.sum()
        if removed_count > 0:
            df = df[~removal_mask].copy()
            logger.info(f"Removed {removed_count:,} records with negative energy or CO₂ metrics")

        self.validation_report['negative_energy_values'] = int(energy_negatives)
        self.validation_report['negative_co2_values'] = int(co2_negatives)

        return df

    def remove_duplicates(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Remove duplicate certificates for the same property, retaining most recent.

        Args:
            df: EPC DataFrame

        Returns:
            DataFrame with duplicates removed
        """
        logger.info("Checking for duplicate certificates...")
        initial_count = len(df)

        # Identify duplicates by UPRN or address
        if 'UPRN' in df.columns:
            # Sort by lodgement date (most recent first)
            df = df.sort_values('LODGEMENT_DATE', ascending=False)
            # Keep first (most recent) for each UPRN
            df = df.drop_duplicates(subset='UPRN', keep='first')
            duplicates_removed = initial_count - len(df)
            logger.info(f"Removed {duplicates_removed:,} duplicate UPRNs")
        elif 'ADDRESS' in df.columns or 'ADDRESS1' in df.columns:
            # Fallback to address-based deduplication
            address_col = 'ADDRESS' if 'ADDRESS' in df.columns else 'ADDRESS1'
            df = df.sort_values('LODGEMENT_DATE', ascending=False)
            df = df.drop_duplicates(subset=address_col, keep='first')
            duplicates_removed = initial_count - len(df)
            logger.info(f"Removed {duplicates_removed:,} duplicate addresses")
        else:
            duplicates_removed = 0
            logger.warning("No UPRN or address column found for deduplication")

        self.validation_report['duplicates_removed'] = duplicates_removed

        # Flag historical certificates for trend analysis
        df['is_most_recent'] = True

        return df

    def validate_floor_areas(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Validate floor area values are within plausible ranges.

        Args:
            df: EPC DataFrame

        Returns:
            DataFrame with implausible floor areas removed
        """
        logger.info("Validating floor areas...")
        initial_count = len(df)

        min_area = self.quality_thresholds['min_floor_area']
        max_area = self.quality_thresholds['max_floor_area']

        if 'TOTAL_FLOOR_AREA' in df.columns:
            # Flag implausible values
            df['floor_area_valid'] = (
                (df['TOTAL_FLOOR_AREA'] >= min_area) &
                (df['TOTAL_FLOOR_AREA'] <= max_area)
            )

            invalid_count = (~df['floor_area_valid']).sum()
            logger.info(
                f"Found {invalid_count:,} records with implausible floor areas "
                f"(outside {min_area}-{max_area} m²)"
            )

            # Remove or flag for investigation
            df = df[df['floor_area_valid']].copy()
            self.validation_report['implausible_floor_areas'] = invalid_count
        else:
            logger.warning("TOTAL_FLOOR_AREA column not found")

        return df

    def validate_built_form(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Validate built form consistency with property type.

        Args:
            df: EPC DataFrame

        Returns:
            DataFrame with inconsistent built forms flagged/removed
        """
        logger.info("Validating built form consistency...")
        initial_count = len(df)

        if 'BUILT_FORM' in df.columns and 'PROPERTY_TYPE' in df.columns:
            # Check for logical inconsistencies
            # E.g., detached property flagged as terrace
            inconsistent_mask = (
                (df['PROPERTY_TYPE'].str.contains('Terrace', case=False, na=False)) &
                (df['BUILT_FORM'].str.contains('Detached', case=False, na=False))
            )

            inconsistent_count = inconsistent_mask.sum()
            logger.info(f"Found {inconsistent_count:,} records with inconsistent built form")

            # Flag for potential exclusion
            df['built_form_consistent'] = ~inconsistent_mask
            df = df[df['built_form_consistent']].copy()

            self.validation_report['inconsistent_built_form'] = inconsistent_count
        else:
            logger.warning("BUILT_FORM or PROPERTY_TYPE column not found")

        return df

    def validate_critical_fields(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Ensure all critical fields are present and non-null.

        Args:
            df: EPC DataFrame

        Returns:
            DataFrame with records having complete critical fields
        """
        logger.info("Validating critical fields...")
        initial_count = len(df)

        required_fields = self.quality_thresholds.get('required_fields', [])

        # Map config field names to actual column names (case-insensitive)
        field_mapping = {
            'address': ['ADDRESS', 'ADDRESS1'],
            'postcode': ['POSTCODE'],
            'property_type': ['PROPERTY_TYPE'],
            'built_form': ['BUILT_FORM'],
            'construction_age_band': ['CONSTRUCTION_AGE_BAND'],
            'current_energy_rating': ['CURRENT_ENERGY_RATING'],
            'walls_description': ['WALLS_DESCRIPTION', 'WALL_DESCRIPTION'],
            'heating_system': ['MAINHEAT_DESCRIPTION', 'HEATING_SYSTEM']
        }

        missing_counts = {}
        for field in required_fields:
            if field in field_mapping:
                possible_columns = field_mapping[field]
                found_column = None

                for col in possible_columns:
                    if col in df.columns:
                        found_column = col
                        break

                if found_column:
                    missing_count = df[found_column].isna().sum()
                    missing_counts[found_column] = missing_count

                    if missing_count > 0:
                        logger.info(f"  {found_column}: {missing_count:,} missing values")
                        df = df[df[found_column].notna()].copy()
                else:
                    logger.warning(f"  Required field '{field}' not found in dataset")

        total_removed = initial_count - len(df)
        self.validation_report['missing_critical_fields'] = total_removed
        logger.info(f"Removed {total_removed:,} records due to missing critical fields")

        return df

    def validate_construction_dates(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Validate construction dates match age band criteria.

        Args:
            df: EPC DataFrame

        Returns:
            DataFrame with validated construction dates
        """
        logger.info("Validating construction dates...")
        initial_count = len(df)

        if 'CONSTRUCTION_AGE_BAND' in df.columns:
            # Flag properties with age bands suggesting post-1930 construction
            post_1930_bands = [
                '1930-1949',
                '1950-1966',
                '1967-1975',
                '1976-1982',
                '1983-1990',
                '1991-1995',
                '1996-2002',
                '2003-2006',
                '2007-2011',
                '2012 onwards'
            ]

            post_1930_mask = df['CONSTRUCTION_AGE_BAND'].isin(post_1930_bands)
            mismatch_count = post_1930_mask.sum()

            if mismatch_count > 0:
                logger.info(f"Found {mismatch_count:,} records with post-1930 age bands")
                df = df[~post_1930_mask].copy()

            self.validation_report['construction_date_mismatches'] = mismatch_count
        else:
            logger.warning("CONSTRUCTION_AGE_BAND column not found")

        return df

    def validate_insulation_logic(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Check for illogical insulation combinations.

        Args:
            df: EPC DataFrame

        Returns:
            DataFrame with flagged illogical insulation
        """
        logger.info("Validating insulation logic...")

        # Example: cavity wall insulation in solid-wall properties
        illogical_count = 0

        if 'WALLS_DESCRIPTION' in df.columns:
            # Check for cavity insulation claimed in solid wall properties
            solid_wall_mask = df['WALLS_DESCRIPTION'].str.contains(
                'solid', case=False, na=False
            )
            cavity_insulation_mask = df['WALLS_DESCRIPTION'].str.contains(
                'cavity.*filled|filled.*cavity', case=False, na=False
            )

            illogical_mask = solid_wall_mask & cavity_insulation_mask
            illogical_count = illogical_mask.sum()

            if illogical_count > 0:
                logger.warning(f"Found {illogical_count:,} records with illogical insulation")
                df['insulation_logic_flag'] = illogical_mask
                # Don't remove, but flag for manual review

        self.validation_report['illogical_insulation'] = illogical_count

        return df

    def standardize_fields(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardize and normalize fields for analysis.

        Args:
            df: EPC DataFrame

        Returns:
            DataFrame with standardized fields
        """
        logger.info("Standardizing fields...")

        # Standardize heating system categories
        df = self._standardize_heating_systems(df)

        # Standardize wall construction types (detailed)
        df = self._standardize_wall_types_detailed(df)

        # Standardize roof/loft insulation
        df = self._standardize_roof_insulation(df)

        # Standardize floor insulation
        df = self._standardize_floor_insulation(df)

        # Standardize window glazing
        df = self._standardize_glazing(df)

        # Standardize ventilation
        df = self._standardize_ventilation(df)

        # Standardize tenure
        df = self._standardize_tenure(df)

        # Normalize energy consumption to kWh/m²/year
        df = self._normalize_energy_metrics(df)

        return df

    def _standardize_heating_systems(self, df: pd.DataFrame) -> pd.DataFrame:
        """Standardize heating system descriptions."""
        if 'MAINHEAT_DESCRIPTION' in df.columns:
            df['heating_system_type'] = 'Other'

            # Categorize heating systems
            boiler_mask = df['MAINHEAT_DESCRIPTION'].str.contains(
                'boiler', case=False, na=False
            )
            electric_mask = df['MAINHEAT_DESCRIPTION'].str.contains(
                'electric', case=False, na=False
            )
            heat_pump_mask = df['MAINHEAT_DESCRIPTION'].str.contains(
                'heat pump', case=False, na=False
            )

            df.loc[boiler_mask, 'heating_system_type'] = 'Gas Boiler'
            df.loc[electric_mask, 'heating_system_type'] = 'Electric'
            df.loc[heat_pump_mask, 'heating_system_type'] = 'Heat Pump'

            logger.info("Heating systems standardized")

        return df

    def _standardize_wall_types(self, df: pd.DataFrame) -> pd.DataFrame:
        """Standardize wall construction types (basic)."""
        if 'WALLS_DESCRIPTION' in df.columns:
            df['wall_type'] = 'Other'
            df['wall_insulated'] = False

            # Categorize wall types
            solid_mask = df['WALLS_DESCRIPTION'].str.contains(
                'solid', case=False, na=False
            )
            cavity_mask = df['WALLS_DESCRIPTION'].str.contains(
                'cavity', case=False, na=False
            )
            insulated_mask = df['WALLS_DESCRIPTION'].str.contains(
                'insulated|filled', case=False, na=False
            )

            df.loc[solid_mask, 'wall_type'] = 'Solid'
            df.loc[cavity_mask, 'wall_type'] = 'Cavity'
            df.loc[insulated_mask, 'wall_insulated'] = True

            logger.info("Wall types standardized")

        return df

    def _standardize_wall_types_detailed(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardize wall construction types with detailed insulation status.

        Creates:
        - wall_type: solid_brick, cavity, stone, timber_frame, system_built, other
        - wall_insulation_status: none, internal, external, cavity_filled, partial, unknown
        """
        if 'WALLS_DESCRIPTION' not in df.columns:
            df['wall_type'] = 'unknown'
            df['wall_insulation_status'] = 'unknown'
            df['wall_insulated'] = False
            return df

        walls_desc = df['WALLS_DESCRIPTION'].fillna('').str.lower()

        # Initialize columns
        df['wall_type'] = 'other'
        df['wall_insulation_status'] = 'unknown'
        df['wall_insulated'] = False

        # Wall type classification
        # Solid brick (most common for Edwardian)
        solid_brick = walls_desc.str.contains(r'solid.*brick|brick.*solid', na=False)
        df.loc[solid_brick, 'wall_type'] = 'solid_brick'

        # Generic solid walls
        solid_general = walls_desc.str.contains('solid', na=False) & ~solid_brick
        df.loc[solid_general, 'wall_type'] = 'solid_brick'  # Default solid to brick for Edwardian

        # Cavity walls
        cavity = walls_desc.str.contains('cavity', na=False)
        df.loc[cavity, 'wall_type'] = 'cavity'

        # Stone walls
        stone = walls_desc.str.contains('stone', na=False)
        df.loc[stone, 'wall_type'] = 'stone'

        # Timber frame
        timber = walls_desc.str.contains('timber.*frame|wood.*frame', na=False)
        df.loc[timber, 'wall_type'] = 'timber_frame'

        # System built (non-traditional)
        system_built = walls_desc.str.contains('system.*built|non.*traditional|prefab', na=False)
        df.loc[system_built, 'wall_type'] = 'system_built'

        # Insulation status classification
        # No insulation
        no_insulation = (
            walls_desc.str.contains('no insulation|uninsulated|as built', na=False) |
            (walls_desc.str.contains('solid', na=False) &
             ~walls_desc.str.contains('insul', na=False))
        )
        df.loc[no_insulation, 'wall_insulation_status'] = 'none'
        df.loc[no_insulation, 'wall_insulated'] = False

        # External wall insulation (EWI)
        ewi = walls_desc.str.contains('external.*insul|ewi|outside.*insul', na=False)
        df.loc[ewi, 'wall_insulation_status'] = 'external'
        df.loc[ewi, 'wall_insulated'] = True

        # Internal wall insulation (IWI)
        iwi = walls_desc.str.contains('internal.*insul|iwi|inside.*insul|dry.*lin', na=False)
        df.loc[iwi, 'wall_insulation_status'] = 'internal'
        df.loc[iwi, 'wall_insulated'] = True

        # Cavity filled
        cavity_filled = walls_desc.str.contains(
            'cavity.*fill|fill.*cavity|insulated.*cavity|cavity.*insul', na=False
        )
        df.loc[cavity_filled, 'wall_insulation_status'] = 'cavity_filled'
        df.loc[cavity_filled, 'wall_insulated'] = True

        # Partial insulation (only some walls done)
        partial = walls_desc.str.contains('partial|some.*insul', na=False)
        df.loc[partial, 'wall_insulation_status'] = 'partial'
        df.loc[partial, 'wall_insulated'] = True  # Counted as insulated but flagged

        # Log summary
        wall_type_counts = df['wall_type'].value_counts()
        insulation_counts = df['wall_insulation_status'].value_counts()
        logger.info(f"Wall types: {wall_type_counts.to_dict()}")
        logger.info(f"Wall insulation status: {insulation_counts.to_dict()}")

        return df

    def _standardize_roof_insulation(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardize roof/loft insulation data.

        Creates:
        - roof_insulation_thickness_mm: numeric thickness (NaN if unknown)
        - roof_insulation_category: none, minimal (<100mm), partial (100-200mm),
                                     good (200-270mm), excellent (>270mm), unknown
        """
        import re

        # Initialize columns
        df['roof_insulation_thickness_mm'] = np.nan
        df['roof_insulation_category'] = 'unknown'

        # Try to extract thickness from ROOF_DESCRIPTION
        if 'ROOF_DESCRIPTION' in df.columns:
            roof_desc = df['ROOF_DESCRIPTION'].fillna('')

            def extract_thickness(desc):
                """Extract numeric thickness from description string."""
                desc = str(desc).lower()

                # Look for explicit mm values
                match = re.search(r'(\d+)\s*mm', desc)
                if match:
                    return int(match.group(1))

                # No insulation patterns
                if any(p in desc for p in ['no insulation', 'uninsulated', '0 mm', '0mm']):
                    return 0

                return None

            df['roof_insulation_thickness_mm'] = roof_desc.apply(extract_thickness)

            # Also check for qualitative descriptions
            no_insulation = roof_desc.str.lower().str.contains(
                'no insulation|uninsulated', na=False
            )
            df.loc[no_insulation & df['roof_insulation_thickness_mm'].isna(),
                   'roof_insulation_thickness_mm'] = 0

        # Use ROOF_ENERGY_EFF as fallback for categorization
        if 'ROOF_ENERGY_EFF' in df.columns:
            roof_eff = df['ROOF_ENERGY_EFF'].fillna('').str.lower()

            # Map efficiency ratings to approximate thickness categories
            very_poor = roof_eff.isin(['very poor'])
            poor = roof_eff.isin(['poor'])
            average = roof_eff.isin(['average'])
            good = roof_eff.isin(['good'])
            very_good = roof_eff.isin(['very good'])

            # Set thickness estimates where not already known
            unknown_mask = df['roof_insulation_thickness_mm'].isna()
            df.loc[unknown_mask & very_poor, 'roof_insulation_thickness_mm'] = 25
            df.loc[unknown_mask & poor, 'roof_insulation_thickness_mm'] = 75
            df.loc[unknown_mask & average, 'roof_insulation_thickness_mm'] = 150
            df.loc[unknown_mask & good, 'roof_insulation_thickness_mm'] = 250
            df.loc[unknown_mask & very_good, 'roof_insulation_thickness_mm'] = 300

        # Categorize based on thickness
        thickness = df['roof_insulation_thickness_mm']
        df.loc[thickness == 0, 'roof_insulation_category'] = 'none'
        df.loc[(thickness > 0) & (thickness < 100), 'roof_insulation_category'] = 'minimal'
        df.loc[(thickness >= 100) & (thickness < 200), 'roof_insulation_category'] = 'partial'
        df.loc[(thickness >= 200) & (thickness < 270), 'roof_insulation_category'] = 'good'
        df.loc[thickness >= 270, 'roof_insulation_category'] = 'excellent'

        # Log summary
        cat_counts = df['roof_insulation_category'].value_counts()
        logger.info(f"Roof insulation categories: {cat_counts.to_dict()}")

        median_thickness = df['roof_insulation_thickness_mm'].median()
        if not pd.isna(median_thickness):
            logger.info(f"Median roof insulation thickness: {median_thickness:.0f}mm")

        return df

    def _standardize_floor_insulation(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardize floor insulation data.

        Creates:
        - floor_insulation: none, some, full, unknown
        - floor_insulation_present: boolean
        """
        df['floor_insulation'] = 'unknown'
        df['floor_insulation_present'] = False

        # Check FLOOR_DESCRIPTION
        if 'FLOOR_DESCRIPTION' in df.columns:
            floor_desc = df['FLOOR_DESCRIPTION'].fillna('').str.lower()

            # No insulation
            no_insulation = floor_desc.str.contains(
                'no insulation|uninsulated|suspended.*no|solid.*no', na=False
            )
            df.loc[no_insulation, 'floor_insulation'] = 'none'

            # Has insulation
            has_insulation = floor_desc.str.contains(
                'insulated|insulation', na=False
            ) & ~no_insulation
            df.loc[has_insulation, 'floor_insulation'] = 'full'
            df.loc[has_insulation, 'floor_insulation_present'] = True

            # Limited/partial insulation
            partial = floor_desc.str.contains('limited|partial|some', na=False)
            df.loc[partial, 'floor_insulation'] = 'some'
            df.loc[partial, 'floor_insulation_present'] = True

        # Use FLOOR_ENERGY_EFF as fallback
        if 'FLOOR_ENERGY_EFF' in df.columns:
            floor_eff = df['FLOOR_ENERGY_EFF'].fillna('').str.lower()
            unknown_mask = df['floor_insulation'] == 'unknown'

            very_poor = floor_eff.isin(['very poor'])
            poor = floor_eff.isin(['poor'])
            average_or_better = floor_eff.isin(['average', 'good', 'very good'])

            df.loc[unknown_mask & (very_poor | poor), 'floor_insulation'] = 'none'
            df.loc[unknown_mask & average_or_better, 'floor_insulation'] = 'some'
            df.loc[unknown_mask & average_or_better, 'floor_insulation_present'] = True

        # Log summary
        floor_counts = df['floor_insulation'].value_counts()
        logger.info(f"Floor insulation: {floor_counts.to_dict()}")

        return df

    def _standardize_glazing(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardize window glazing type.

        Creates:
        - glazing_type: single, double, triple, mixed, unknown
        """
        df['glazing_type'] = 'unknown'

        # Check multiple possible column names
        glazing_cols = ['WINDOWS_DESCRIPTION', 'GLAZED_TYPE', 'MULTI_GLAZE_PROPORTION']

        for col in glazing_cols:
            if col in df.columns:
                desc = df[col].fillna('').astype(str).str.lower()

                # Triple glazing
                triple = desc.str.contains('triple', na=False)
                df.loc[triple, 'glazing_type'] = 'triple'

                # Double glazing
                double = desc.str.contains('double', na=False) & ~triple
                df.loc[double, 'glazing_type'] = 'double'

                # Single glazing
                single = desc.str.contains('single', na=False)
                df.loc[single, 'glazing_type'] = 'single'

                # Mixed (some single, some double)
                mixed = desc.str.contains('mix|partial|some', na=False)
                df.loc[mixed, 'glazing_type'] = 'mixed'

        # Use WINDOWS_ENERGY_EFF as fallback
        if 'WINDOWS_ENERGY_EFF' in df.columns:
            window_eff = df['WINDOWS_ENERGY_EFF'].fillna('').str.lower()
            unknown_mask = df['glazing_type'] == 'unknown'

            very_poor = window_eff.isin(['very poor'])
            poor = window_eff.isin(['poor'])
            average_or_better = window_eff.isin(['average', 'good', 'very good'])

            # Assume very poor/poor = single, average+ = double
            df.loc[unknown_mask & (very_poor | poor), 'glazing_type'] = 'single'
            df.loc[unknown_mask & average_or_better, 'glazing_type'] = 'double'

        # Log summary
        glazing_counts = df['glazing_type'].value_counts()
        logger.info(f"Glazing types: {glazing_counts.to_dict()}")

        return df

    def _standardize_ventilation(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardize ventilation type.

        Creates:
        - ventilation_type: natural, extract_fans, mev, mvhr, other, unknown
        """
        df['ventilation_type'] = 'unknown'

        # Check VENTILATION_TYPE or similar columns
        vent_cols = ['VENTILATION_TYPE', 'MECHANICAL_VENTILATION']

        for col in vent_cols:
            if col in df.columns:
                desc = df[col].fillna('').astype(str).str.lower()

                # MVHR (mechanical ventilation with heat recovery)
                mvhr = desc.str.contains('mvhr|heat.*recovery|hrv', na=False)
                df.loc[mvhr, 'ventilation_type'] = 'mvhr'

                # MEV (mechanical extract ventilation)
                mev = desc.str.contains('mev|mechanical.*extract|centralised.*extract', na=False)
                df.loc[mev, 'ventilation_type'] = 'mev'

                # Extract fans only
                extract = desc.str.contains('extract.*fan|fan.*extract', na=False) & ~mev & ~mvhr
                df.loc[extract, 'ventilation_type'] = 'extract_fans'

                # Natural ventilation
                natural = desc.str.contains('natural|none|no mechanical', na=False)
                df.loc[natural, 'ventilation_type'] = 'natural'

        # If no ventilation data found, assume natural for pre-1930 properties
        if (df['ventilation_type'] == 'unknown').all():
            df['ventilation_type'] = 'natural'
            logger.info("No ventilation data found, assuming natural ventilation for all properties")
        else:
            vent_counts = df['ventilation_type'].value_counts()
            logger.info(f"Ventilation types: {vent_counts.to_dict()}")

        return df

    def _standardize_tenure(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardize tenure field.

        Creates:
        - tenure: owner_occupied, private_rented, social, unknown
        """
        df['tenure'] = 'unknown'

        # Check TENURE column (EPC API field)
        if 'TENURE' in df.columns:
            tenure_raw = df['TENURE'].fillna('').astype(str).str.lower()

            # Owner-occupied
            owner = tenure_raw.str.contains('owner|owned|freeholder', na=False)
            df.loc[owner, 'tenure'] = 'owner_occupied'

            # Private rented
            private_rent = tenure_raw.str.contains('private.*rent|rental.*private|rented.*private', na=False)
            df.loc[private_rent, 'tenure'] = 'private_rented'

            # Social housing
            social = tenure_raw.str.contains('social|council|housing.*assoc|ha|local.*authority', na=False)
            df.loc[social, 'tenure'] = 'social'

            # Generic rental (classify as private if not social)
            generic_rental = tenure_raw.str.contains('rent', na=False) & (df['tenure'] == 'unknown')
            df.loc[generic_rental, 'tenure'] = 'private_rented'

        # Log summary
        tenure_counts = df['tenure'].value_counts()
        logger.info(f"Tenure breakdown: {tenure_counts.to_dict()}")

        return df

    def _normalize_energy_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Normalize energy consumption and CO2 emissions metrics.

        EPC API fields (after column standardization):
        - ENERGY_CONSUMPTION_CURRENT: Primary energy consumption in kWh/m²/year
        - CO2_EMISSIONS_CURRENT: Total annual CO2 emissions in tonnes/year

        Note: We apply validation checks to catch unit errors early.
        Expected ranges for Edwardian terraced houses:
        - Energy: 100-400 kWh/m²/year (mean typically 150-250)
        - CO2: 20-100 kgCO₂/m²/year (mean typically 40-60)
        """
        # Handle energy consumption
        if 'ENERGY_CONSUMPTION_CURRENT' in df.columns and 'TOTAL_FLOOR_AREA' in df.columns:
            # Check if ENERGY_CONSUMPTION_CURRENT appears to be absolute (kWh/year)
            # or already normalized (kWh/m²/year)
            raw_mean = df['ENERGY_CONSUMPTION_CURRENT'].mean()
            floor_area_mean = df['TOTAL_FLOOR_AREA'].mean()

            # If mean is very high (>1000), it's likely absolute kWh/year
            # If mean is in range 50-500, it's likely already kWh/m²/year
            if raw_mean > 1000:
                # Absolute value - divide by floor area
                df['energy_kwh_per_m2_year'] = (
                    df['ENERGY_CONSUMPTION_CURRENT'] / df['TOTAL_FLOOR_AREA']
                )
                logger.info(f"Energy consumption appears to be absolute ({raw_mean:.0f} kWh/year mean)")
                logger.info("Normalized by dividing by floor area")
            else:
                # Already normalized - use directly
                df['energy_kwh_per_m2_year'] = df['ENERGY_CONSUMPTION_CURRENT'].copy()
                logger.info(f"Energy consumption appears already normalized ({raw_mean:.1f} kWh/m²/year mean)")

            # Validate the result
            result_mean = df['energy_kwh_per_m2_year'].mean()
            if result_mean < 50 or result_mean > 500:
                logger.warning(
                    f"Energy consumption mean ({result_mean:.1f} kWh/m²/year) outside expected range (50-500). "
                    f"Check raw data units. Raw mean: {raw_mean:.1f}, Floor area mean: {floor_area_mean:.1f} m²"
                )
                # Attempt correction if severely off
                if result_mean < 10:
                    # Likely divided twice or wrong unit - try multiplying by floor area
                    df['energy_kwh_per_m2_year'] = df['ENERGY_CONSUMPTION_CURRENT'] * df['TOTAL_FLOOR_AREA'] / df['TOTAL_FLOOR_AREA']
                    corrected_mean = df['energy_kwh_per_m2_year'].mean()
                    logger.warning(f"Attempted correction, new mean: {corrected_mean:.1f}")
            else:
                logger.info(f"✓ Energy consumption validated: mean = {result_mean:.1f} kWh/m²/year")

            negative_energy_norm = (df['energy_kwh_per_m2_year'] < 0).sum()
            if negative_energy_norm > 0:
                logger.warning(f"Clamping {negative_energy_norm:,} negative normalized energy values to zero")
                df['energy_kwh_per_m2_year'] = df['energy_kwh_per_m2_year'].clip(lower=0)
        elif 'ENERGY_CONSUMPTION_CURRENT' in df.columns:
            # No floor area available - copy as-is with warning
            df['energy_kwh_per_m2_year'] = df['ENERGY_CONSUMPTION_CURRENT'].copy()
            logger.warning("TOTAL_FLOOR_AREA not available for energy normalization check")

        # Handle CO2 emissions
        # CO2_EMISSIONS_CURRENT is in tonnes/year (absolute)
        # Convert to kg/m²/year: tonnes * 1000 / floor_area
        if 'CO2_EMISSIONS_CURRENT' in df.columns and 'TOTAL_FLOOR_AREA' in df.columns:
            df['co2_kg_per_m2_year'] = (
                df['CO2_EMISSIONS_CURRENT'] * 1000 / df['TOTAL_FLOOR_AREA']
            )

            # Validate the result
            co2_mean = df['co2_kg_per_m2_year'].mean()
            if co2_mean < 10 or co2_mean > 150:
                logger.warning(
                    f"CO₂ emissions mean ({co2_mean:.1f} kgCO₂/m²/year) outside expected range (10-150). "
                    f"Raw CO₂ mean: {df['CO2_EMISSIONS_CURRENT'].mean():.2f} tonnes/year"
                )
            else:
                logger.info(f"✓ CO₂ emissions validated: mean = {co2_mean:.1f} kgCO₂/m²/year")

            negative_co2_norm = (df['co2_kg_per_m2_year'] < 0).sum()
            if negative_co2_norm > 0:
                logger.warning(f"Clamping {negative_co2_norm:,} negative normalized CO₂ values to zero")
                df['co2_kg_per_m2_year'] = df['co2_kg_per_m2_year'].clip(lower=0)

            logger.info("CO2 metrics normalized to kg/m²/year (converted from tonnes/year)")

        # Also create absolute energy consumption for cost calculations
        if 'energy_kwh_per_m2_year' in df.columns and 'TOTAL_FLOOR_AREA' in df.columns:
            df['energy_kwh_per_year_absolute'] = (
                df['energy_kwh_per_m2_year'] * df['TOTAL_FLOOR_AREA']
            )
            logger.info("Created absolute energy consumption column (kWh/year)")

        return df

    def log_validation_summary(self):
        """Log summary of validation process."""
        logger.info("\n" + "="*60)
        logger.info("VALIDATION SUMMARY")
        logger.info("="*60)
        logger.info(f"Total records processed:        {self.validation_report['total_records']:,}")
        logger.info(f"Duplicates removed:             {self.validation_report['duplicates_removed']:,}")
        logger.info(f"Implausible floor areas:        {self.validation_report['implausible_floor_areas']:,}")
        logger.info(f"Inconsistent built form:        {self.validation_report['inconsistent_built_form']:,}")
        logger.info(f"Missing critical fields:        {self.validation_report['missing_critical_fields']:,}")
        logger.info(f"Construction date mismatches:   {self.validation_report['construction_date_mismatches']:,}")
        logger.info(f"Illogical insulation (flagged): {self.validation_report['illogical_insulation']:,}")
        logger.info(f"Negative energy values:         {self.validation_report['negative_energy_values']:,}")
        logger.info(f"Negative CO₂ values:            {self.validation_report['negative_co2_values']:,}")
        logger.info(f"\nRecords passed validation:      {self.validation_report['records_passed']:,}")

        pass_rate = (self.validation_report['records_passed'] /
                     self.validation_report['total_records'] * 100)
        logger.info(f"Pass rate:                      {pass_rate:.1f}%")
        logger.info("="*60 + "\n")

    def save_validation_report(self, output_path: Optional[Path] = None):
        """
        Save validation report to file.

        Args:
            output_path: Path to save report
        """
        if output_path is None:
            output_path = DATA_PROCESSED_DIR / "validation_report.txt"

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("EPC DATA VALIDATION REPORT\n")
            f.write("="*60 + "\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            for key, value in self.validation_report.items():
                f.write(f"{key.replace('_', ' ').title()}: {value:,}\n")

        logger.info(f"Validation report saved to: {output_path}")


def filter_properties(
    df: pd.DataFrame,
    tenure: Optional[str] = None,
    epc_band_range: Optional[Tuple[str, str]] = None,
    year_built_range: Optional[Tuple[int, int]] = None,
    property_type: Optional[str] = None,
    wall_type: Optional[str] = None,
    has_wall_insulation: Optional[bool] = None
) -> pd.DataFrame:
    """
    Filter properties DataFrame based on various criteria.

    Args:
        df: Properties DataFrame with standardized fields
        tenure: Filter by tenure type ('owner_occupied', 'private_rented', 'social', None for all)
        epc_band_range: Tuple of (min_band, max_band) e.g. ('D', 'G') for D-G inclusive
        year_built_range: Tuple of (start_year, end_year) e.g. (1900, 1930)
        property_type: Filter by property type (e.g., 'Terraced', 'Mid-terrace')
        wall_type: Filter by wall type ('solid_brick', 'cavity', etc.)
        has_wall_insulation: Filter by wall insulation status (True/False/None)

    Returns:
        Filtered DataFrame

    Example:
        # Get owner-occupied properties with EPC bands D-G
        df_filtered = filter_properties(df, tenure='owner_occupied', epc_band_range=('D', 'G'))

        # Get uninsulated solid wall properties
        df_filtered = filter_properties(df, wall_type='solid_brick', has_wall_insulation=False)
    """
    df_filtered = df.copy()
    initial_count = len(df_filtered)

    # Filter by tenure
    if tenure is not None:
        if 'tenure' in df_filtered.columns:
            df_filtered = df_filtered[df_filtered['tenure'] == tenure]
            logger.info(f"Filtered by tenure={tenure}: {len(df_filtered):,} properties")
        else:
            logger.warning("tenure column not found, skipping tenure filter")

    # Filter by EPC band range
    if epc_band_range is not None:
        if 'CURRENT_ENERGY_RATING' in df_filtered.columns:
            band_order = {'A': 1, 'B': 2, 'C': 3, 'D': 4, 'E': 5, 'F': 6, 'G': 7}
            min_band, max_band = epc_band_range
            min_val = band_order.get(min_band, 1)
            max_val = band_order.get(max_band, 7)

            df_filtered['_band_numeric'] = df_filtered['CURRENT_ENERGY_RATING'].map(band_order)
            df_filtered = df_filtered[
                (df_filtered['_band_numeric'] >= min_val) &
                (df_filtered['_band_numeric'] <= max_val)
            ]
            df_filtered = df_filtered.drop(columns=['_band_numeric'])
            logger.info(f"Filtered by EPC bands {min_band}-{max_band}: {len(df_filtered):,} properties")

    # Filter by construction year
    if year_built_range is not None:
        if 'CONSTRUCTION_AGE_BAND' in df_filtered.columns:
            start_year, end_year = year_built_range
            # This is a simplified filter - would need more sophisticated parsing
            # of CONSTRUCTION_AGE_BAND for precise filtering
            age_band = df_filtered['CONSTRUCTION_AGE_BAND'].fillna('')

            # Filter for bands that overlap with the range
            def band_in_range(band):
                band = str(band).lower()
                if 'before 1900' in band:
                    return start_year <= 1900
                if 'pre-1919' in band or 'pre 1919' in band:
                    return start_year < 1919
                if '1900-1929' in band:
                    return not (end_year < 1900 or start_year > 1929)
                if '1919-1929' in band:
                    return not (end_year < 1919 or start_year > 1929)
                if '1900-1918' in band:
                    return not (end_year < 1900 or start_year > 1918)
                # Default: include if we can't parse
                return True

            df_filtered = df_filtered[age_band.apply(band_in_range)]
            logger.info(f"Filtered by year range {start_year}-{end_year}: {len(df_filtered):,} properties")

    # Filter by property type
    if property_type is not None:
        if 'PROPERTY_TYPE' in df_filtered.columns:
            df_filtered = df_filtered[
                df_filtered['PROPERTY_TYPE'].str.contains(property_type, case=False, na=False)
            ]
            logger.info(f"Filtered by property_type={property_type}: {len(df_filtered):,} properties")

    # Filter by wall type
    if wall_type is not None:
        if 'wall_type' in df_filtered.columns:
            df_filtered = df_filtered[df_filtered['wall_type'] == wall_type]
            logger.info(f"Filtered by wall_type={wall_type}: {len(df_filtered):,} properties")

    # Filter by wall insulation status
    if has_wall_insulation is not None:
        if 'wall_insulated' in df_filtered.columns:
            df_filtered = df_filtered[df_filtered['wall_insulated'] == has_wall_insulation]
            logger.info(f"Filtered by has_wall_insulation={has_wall_insulation}: {len(df_filtered):,} properties")

    # Log summary
    final_count = len(df_filtered)
    reduction_pct = (1 - final_count / initial_count) * 100 if initial_count > 0 else 0
    logger.info(f"Filter complete: {initial_count:,} -> {final_count:,} properties ({reduction_pct:.1f}% removed)")

    return df_filtered


def flag_epc_anomalies(
    df: pd.DataFrame,
    roof_threshold_mm: int = 100,
    suspicious_bands: List[str] = None
) -> pd.DataFrame:
    """
    Flag properties with suspicious EPC ratings (e.g., uninsulated but still Band C/D).

    This identifies potential data quality issues or unusual properties that may require
    manual review or different treatment in analysis.

    Args:
        df: Properties DataFrame with standardized fabric fields
        roof_threshold_mm: Roof insulation threshold below which is considered poorly insulated
        suspicious_bands: EPC bands that are suspicious for poorly insulated properties

    Returns:
        DataFrame with anomaly flags added:
        - is_epc_fabric_anomaly: boolean flag
        - anomaly_reason: text description of why flagged

    Anomaly rules:
        1. Wall insulation = none/unknown AND roof < threshold AND EPC band in C/D
        2. Single glazing AND good EPC band (C or better)
        3. No fabric insulation at all but EPC band C or better
    """
    if suspicious_bands is None:
        suspicious_bands = ['C', 'D']

    df_flagged = df.copy()
    df_flagged['is_epc_fabric_anomaly'] = False
    df_flagged['anomaly_reason'] = ''

    # Rule 1: Uninsulated walls + poor roof + suspiciously good EPC
    rule1_mask = pd.Series(False, index=df.index)
    reason1_parts = []

    # Check wall insulation
    if 'wall_insulation_status' in df.columns:
        uninsulated_walls = df['wall_insulation_status'].isin(['none', 'unknown'])
        rule1_mask = rule1_mask | uninsulated_walls
        reason1_parts.append('uninsulated_walls')
    elif 'wall_insulated' in df.columns:
        uninsulated_walls = ~df['wall_insulated']
        rule1_mask = rule1_mask | uninsulated_walls
        reason1_parts.append('uninsulated_walls')

    # Check roof insulation
    if 'roof_insulation_thickness_mm' in df.columns:
        poor_roof = df['roof_insulation_thickness_mm'] < roof_threshold_mm
        rule1_mask = rule1_mask & poor_roof
        reason1_parts.append(f'roof<{roof_threshold_mm}mm')

    # Check if suspiciously good EPC band
    if 'CURRENT_ENERGY_RATING' in df.columns:
        suspicious_band = df['CURRENT_ENERGY_RATING'].isin(suspicious_bands)
        rule1_mask = rule1_mask & suspicious_band

    df_flagged.loc[rule1_mask, 'is_epc_fabric_anomaly'] = True
    df_flagged.loc[rule1_mask, 'anomaly_reason'] = 'uninsulated_but_good_epc'

    # Rule 2: Single glazing but EPC C or better
    if 'glazing_type' in df.columns and 'CURRENT_ENERGY_RATING' in df.columns:
        single_glazed = df['glazing_type'] == 'single'
        good_epc = df['CURRENT_ENERGY_RATING'].isin(['A', 'B', 'C'])
        rule2_mask = single_glazed & good_epc

        df_flagged.loc[rule2_mask, 'is_epc_fabric_anomaly'] = True
        df_flagged.loc[rule2_mask & (df_flagged['anomaly_reason'] == ''), 'anomaly_reason'] = 'single_glazed_good_epc'
        df_flagged.loc[rule2_mask & (df_flagged['anomaly_reason'] != '') & (df_flagged['anomaly_reason'] != 'single_glazed_good_epc'),
                       'anomaly_reason'] += ';single_glazed_good_epc'

    # Rule 3: No fabric insulation at all but EPC C or better
    if all(col in df.columns for col in ['wall_insulated', 'floor_insulation_present']):
        no_wall_insulation = ~df['wall_insulated']
        no_floor_insulation = ~df['floor_insulation_present']
        poor_roof = df.get('roof_insulation_thickness_mm', pd.Series(0, index=df.index)) < 100
        good_epc = df['CURRENT_ENERGY_RATING'].isin(['A', 'B', 'C']) if 'CURRENT_ENERGY_RATING' in df.columns else False

        rule3_mask = no_wall_insulation & no_floor_insulation & poor_roof & good_epc

        df_flagged.loc[rule3_mask, 'is_epc_fabric_anomaly'] = True
        df_flagged.loc[rule3_mask & (df_flagged['anomaly_reason'] == ''), 'anomaly_reason'] = 'no_fabric_insulation_good_epc'

    # Log summary
    n_anomalies = df_flagged['is_epc_fabric_anomaly'].sum()
    pct_anomalies = (n_anomalies / len(df_flagged) * 100) if len(df_flagged) > 0 else 0
    logger.info(f"EPC anomalies flagged: {n_anomalies:,} properties ({pct_anomalies:.1f}%)")

    # Log breakdown by reason
    if n_anomalies > 0:
        reason_counts = df_flagged[df_flagged['is_epc_fabric_anomaly']]['anomaly_reason'].value_counts()
        for reason, count in reason_counts.items():
            logger.info(f"  {reason}: {count:,}")

    return df_flagged


def main():
    """Main execution function for data validation."""
    logger.info("Starting EPC data validation...")

    # Load raw data
    input_file = DATA_RAW_DIR / "epc_london_filtered.csv"

    if not input_file.exists():
        logger.error(f"Input file not found: {input_file}")
        logger.info("Please run data acquisition first")
        return

    logger.info(f"Loading data from: {input_file}")
    df = pd.read_csv(input_file, low_memory=False)

    # Validate data
    validator = EPCDataValidator()
    df_validated, report = validator.validate_dataset(df)

    # Flag anomalies
    df_validated = flag_epc_anomalies(df_validated)

    # Save validated data
    output_file = DATA_PROCESSED_DIR / "epc_london_validated.csv"
    df_validated.to_csv(output_file, index=False)
    logger.info(f"Validated data saved to: {output_file}")

    # Save as parquet for faster loading
    parquet_file = output_file.with_suffix('.parquet')
    df_validated.to_parquet(parquet_file, index=False)
    logger.info(f"Also saved as parquet: {parquet_file}")

    # Save validation report
    validator.save_validation_report()

    logger.info("Data validation complete!")


if __name__ == "__main__":
    main()
