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

        # Standardize wall construction types
        df = self._standardize_wall_types(df)

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
        """Standardize wall construction types."""
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

    def _normalize_energy_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize energy consumption metrics."""
        if 'ENERGY_CONSUMPTION_CURRENT' in df.columns and 'TOTAL_FLOOR_AREA' in df.columns:
            df['energy_kwh_per_m2_year'] = (
                df['ENERGY_CONSUMPTION_CURRENT'] / df['TOTAL_FLOOR_AREA']
            )
            logger.info("Energy metrics normalized to kWh/m²/year")

        if 'CO2_EMISSIONS_CURRENT' in df.columns and 'TOTAL_FLOOR_AREA' in df.columns:
            df['co2_kg_per_m2_year'] = (
                df['CO2_EMISSIONS_CURRENT'] / df['TOTAL_FLOOR_AREA']
            )
            logger.info("CO2 metrics normalized to kg/m²/year")

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

        with open(output_path, 'w') as f:
            f.write("EPC DATA VALIDATION REPORT\n")
            f.write("="*60 + "\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            for key, value in self.validation_report.items():
                f.write(f"{key.replace('_', ' ').title()}: {value:,}\n")

        logger.info(f"Validation report saved to: {output_path}")


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
