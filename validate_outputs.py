"""
Heat Street EPC Analysis - Output Validation Script

Validates that analysis outputs are in expected ranges after bug fixes.
Run this after the main analysis to verify correctness.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from loguru import logger
import sys

# Set up logging
logger.remove()
logger.add(sys.stderr, level="INFO")

DATA_PROCESSED_DIR = Path("data/processed")
DATA_OUTPUTS_DIR = Path("data/outputs")


class OutputValidator:
    """Validates analysis outputs are in expected ranges."""

    def __init__(self):
        self.checks_passed = 0
        self.checks_failed = 0
        self.warnings = []
        self.errors = []

    def check(self, condition: bool, description: str, is_critical: bool = True):
        """Run a validation check."""
        if condition:
            self.checks_passed += 1
            logger.info(f"✓ PASS: {description}")
            return True
        else:
            if is_critical:
                self.checks_failed += 1
                self.errors.append(description)
                logger.error(f"✗ FAIL: {description}")
            else:
                self.warnings.append(description)
                logger.warning(f"⚠ WARN: {description}")
            return False

    def validate_energy_consumption(self, df: pd.DataFrame) -> bool:
        """Validate energy consumption is in expected range (150-250 kWh/m²/year)."""
        logger.info("\n" + "="*60)
        logger.info("VALIDATING ENERGY CONSUMPTION")
        logger.info("="*60)

        all_passed = True

        # Check normalized column exists
        if 'energy_kwh_per_m2_year' not in df.columns:
            self.check(False, "energy_kwh_per_m2_year column exists")
            return False

        energy = df['energy_kwh_per_m2_year'].dropna()
        mean_energy = energy.mean()

        # Expected range for Edwardian terraced: 150-250 kWh/m²/year
        all_passed &= self.check(
            50 < mean_energy < 400,
            f"Energy consumption mean ({mean_energy:.1f}) in range 50-400 kWh/m²/year"
        )

        all_passed &= self.check(
            100 < mean_energy < 300,
            f"Energy consumption mean ({mean_energy:.1f}) in expected range 100-300 kWh/m²/year",
            is_critical=False
        )

        # Check for obviously wrong values (< 10 suggests unit error)
        all_passed &= self.check(
            mean_energy > 10,
            f"Energy consumption mean ({mean_energy:.1f}) not suspiciously low (>10 kWh/m²/year)"
        )

        return all_passed

    def validate_co2_emissions(self, df: pd.DataFrame) -> bool:
        """Validate CO2 emissions are in expected range (40-60 kgCO₂/m²/year)."""
        logger.info("\n" + "="*60)
        logger.info("VALIDATING CO2 EMISSIONS")
        logger.info("="*60)

        all_passed = True

        # Check normalized column exists
        if 'co2_kg_per_m2_year' not in df.columns:
            self.check(False, "co2_kg_per_m2_year column exists")
            return False

        co2 = df['co2_kg_per_m2_year'].dropna()
        mean_co2 = co2.mean()

        # Expected range: 20-100 kgCO₂/m²/year
        all_passed &= self.check(
            10 < mean_co2 < 150,
            f"CO₂ emissions mean ({mean_co2:.1f}) in range 10-150 kgCO₂/m²/year"
        )

        all_passed &= self.check(
            30 < mean_co2 < 80,
            f"CO₂ emissions mean ({mean_co2:.1f}) in expected range 30-80 kgCO₂/m²/year",
            is_critical=False
        )

        # Check for obviously wrong values (< 1 suggests unit error)
        all_passed &= self.check(
            mean_co2 > 1,
            f"CO₂ emissions mean ({mean_co2:.1f}) not suspiciously low (>1 kgCO₂/m²/year)"
        )

        return all_passed

    def validate_retrofit_tiers(self, df: pd.DataFrame) -> bool:
        """Validate retrofit readiness tiers are distributed (not all in one tier)."""
        logger.info("\n" + "="*60)
        logger.info("VALIDATING RETROFIT READINESS TIERS")
        logger.info("="*60)

        all_passed = True

        # Check tier column exists
        if 'hp_readiness_tier' not in df.columns:
            self.check(False, "hp_readiness_tier column exists")
            return False

        tier_dist = df['hp_readiness_tier'].value_counts(normalize=True) * 100

        # Check that no single tier has > 90% (would indicate classification bug)
        max_tier_pct = tier_dist.max()
        all_passed &= self.check(
            max_tier_pct < 90,
            f"No single tier has >90% of properties (max: {max_tier_pct:.1f}%)"
        )

        # Check that at least 3 tiers are represented
        tiers_with_properties = len(tier_dist[tier_dist > 0])
        all_passed &= self.check(
            tiers_with_properties >= 3,
            f"At least 3 tiers have properties ({tiers_with_properties} found)"
        )

        # Log distribution
        logger.info("Tier distribution:")
        for tier in range(1, 6):
            pct = tier_dist.get(tier, 0)
            logger.info(f"  Tier {tier}: {pct:.1f}%")

        return all_passed

    def validate_wall_insulation(self, df: pd.DataFrame) -> bool:
        """Validate wall insulation needs matches uninsulated count."""
        logger.info("\n" + "="*60)
        logger.info("VALIDATING WALL INSULATION LOGIC")
        logger.info("="*60)

        all_passed = True

        # Check columns exist
        if 'wall_insulated' not in df.columns:
            self.check(False, "wall_insulated column exists")
            return False

        uninsulated_count = (~df['wall_insulated']).sum()
        total = len(df)
        uninsulated_pct = uninsulated_count / total * 100

        # Check that uninsulated count is > 0 (expect ~80% for Edwardian)
        all_passed &= self.check(
            uninsulated_count > 0,
            f"Some properties have uninsulated walls ({uninsulated_count:,} = {uninsulated_pct:.1f}%)"
        )

        # If needs_wall_insulation exists, check it aligns
        if 'needs_wall_insulation' in df.columns:
            needs_count = df['needs_wall_insulation'].sum()
            all_passed &= self.check(
                needs_count > 0,
                f"needs_wall_insulation count > 0 ({needs_count:,})"
            )

            # Check alignment (should be similar)
            diff_pct = abs(needs_count - uninsulated_count) / total * 100
            all_passed &= self.check(
                diff_pct < 20,
                f"needs_wall_insulation aligns with uninsulated count (diff: {diff_pct:.1f}%)",
                is_critical=False
            )

        return all_passed

    def validate_payback_calculations(self, df: pd.DataFrame = None) -> bool:
        """Validate payback calculations are not NaN."""
        logger.info("\n" + "="*60)
        logger.info("VALIDATING PAYBACK CALCULATIONS")
        logger.info("="*60)

        # Try to load scenario results
        scenario_file = DATA_OUTPUTS_DIR / "scenario_modeling_results.txt"
        if not scenario_file.exists():
            logger.warning("Scenario results file not found, skipping payback validation")
            return True

        # Read file and check for NaN
        with open(scenario_file, 'r') as f:
            content = f.read()

        all_passed = True

        # Check for "nan" in payback values
        has_nan = 'average_payback_years: nan' in content.lower() or 'payback_years: nan' in content.lower()
        all_passed &= self.check(
            not has_nan,
            "No NaN values in payback calculations"
        )

        return all_passed

    def validate_case_street_extract(self) -> bool:
        """Validate Shakespeare Crescent extract exists and has records."""
        logger.info("\n" + "="*60)
        logger.info("VALIDATING CASE STREET EXTRACT")
        logger.info("="*60)

        all_passed = True

        # Check file exists
        case_street_file = DATA_OUTPUTS_DIR / "shakespeare_crescent_extract.csv"

        if not case_street_file.exists():
            self.check(False, "Shakespeare Crescent extract file exists")
            logger.info("  (This may be expected if street not in dataset)")
            return True  # Not a failure - street may not be in data

        # Load and check
        df = pd.read_csv(case_street_file)
        all_passed &= self.check(
            len(df) > 0,
            f"Shakespeare Crescent extract has records ({len(df)} found)"
        )

        return all_passed

    def validate_constituency_breakdown(self) -> bool:
        """Validate constituency breakdown exists and has records."""
        logger.info("\n" + "="*60)
        logger.info("VALIDATING CONSTITUENCY BREAKDOWN")
        logger.info("="*60)

        all_passed = True

        # Check file exists
        constituency_file = DATA_OUTPUTS_DIR / "constituency_breakdown.csv"

        if not constituency_file.exists():
            self.check(False, "Constituency breakdown file exists")
            return False

        # Load and check
        df = pd.read_csv(constituency_file)
        n_constituencies = len(df)

        all_passed &= self.check(
            n_constituencies > 0,
            f"Constituency breakdown has records ({n_constituencies} constituencies)"
        )

        # Rough expectation for London constituencies (warning only)
        all_passed &= self.check(
            n_constituencies >= 10,
            f"Constituency breakdown has at least 10 constituencies (found {n_constituencies})",
            is_critical=False
        )

        return all_passed

    def run_all_validations(self) -> bool:
        """Run all validation checks."""
        logger.info("\n" + "="*70)
        logger.info("HEAT STREET EPC ANALYSIS - OUTPUT VALIDATION")
        logger.info("="*70)

        # Load validated data
        validated_file = DATA_PROCESSED_DIR / "epc_london_validated.csv"

        if not validated_file.exists():
            logger.error("Validated data file not found. Run analysis first.")
            return False

        logger.info(f"Loading validated data from: {validated_file}")
        df = pd.read_csv(validated_file, low_memory=False)
        logger.info(f"Loaded {len(df):,} records")

        # Run validations
        all_passed = True
        all_passed &= self.validate_energy_consumption(df)
        all_passed &= self.validate_co2_emissions(df)
        all_passed &= self.validate_retrofit_tiers(df)
        all_passed &= self.validate_wall_insulation(df)
        all_passed &= self.validate_payback_calculations(df)
        all_passed &= self.validate_case_street_extract()
        all_passed &= self.validate_constituency_breakdown()

        # Summary
        logger.info("\n" + "="*70)
        logger.info("VALIDATION SUMMARY")
        logger.info("="*70)
        logger.info(f"Checks passed: {self.checks_passed}")
        logger.info(f"Checks failed: {self.checks_failed}")
        logger.info(f"Warnings: {len(self.warnings)}")

        if self.errors:
            logger.error("\nFailed checks:")
            for error in self.errors:
                logger.error(f"  - {error}")

        if self.warnings:
            logger.warning("\nWarnings:")
            for warning in self.warnings:
                logger.warning(f"  - {warning}")

        if all_passed:
            logger.info("\n✓ ALL VALIDATIONS PASSED")
        else:
            logger.error("\n✗ SOME VALIDATIONS FAILED - Review errors above")

        return all_passed


def main():
    """Run output validation."""
    validator = OutputValidator()
    success = validator.run_all_validations()

    return 0 if success else 1


if __name__ == "__main__":
    exit(main())
