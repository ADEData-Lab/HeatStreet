import pandas as pd
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from src.cleaning.data_validator import EPCDataValidator


def test_negative_energy_and_co2_rows_removed():
    df = pd.DataFrame([
        {
            'LMK_KEY': 'KEEP',
            'UPRN': '1',
            'ADDRESS': '1 Street',
            'POSTCODE': 'AB1 1AA',
            'PROPERTY_TYPE': 'Mid-Terrace',
            'BUILT_FORM': 'Mid-Terrace',
            'CONSTRUCTION_AGE_BAND': '1900-1929',
            'CURRENT_ENERGY_RATING': 'D',
            'WALLS_DESCRIPTION': 'Solid brick wall',
            'MAINHEAT_DESCRIPTION': 'Gas boiler',
            'TOTAL_FLOOR_AREA': 85,
            'ENERGY_CONSUMPTION_CURRENT': 150,
            'CO2_EMISSIONS_CURRENT': 2.5,
            'LODGEMENT_DATE': '2023-01-01',
        },
        {
            'LMK_KEY': 'NEG_ENERGY',
            'UPRN': '2',
            'ADDRESS': '2 Street',
            'POSTCODE': 'AB1 1AB',
            'PROPERTY_TYPE': 'Mid-Terrace',
            'BUILT_FORM': 'Mid-Terrace',
            'CONSTRUCTION_AGE_BAND': '1900-1929',
            'CURRENT_ENERGY_RATING': 'D',
            'WALLS_DESCRIPTION': 'Solid brick wall',
            'MAINHEAT_DESCRIPTION': 'Gas boiler',
            'TOTAL_FLOOR_AREA': 90,
            'ENERGY_CONSUMPTION_CURRENT': -20,
            'CO2_EMISSIONS_CURRENT': 2.0,
            'LODGEMENT_DATE': '2023-01-02',
        },
        {
            'LMK_KEY': 'NEG_CO2',
            'UPRN': '3',
            'ADDRESS': '3 Street',
            'POSTCODE': 'AB1 1AC',
            'PROPERTY_TYPE': 'Mid-Terrace',
            'BUILT_FORM': 'Mid-Terrace',
            'CONSTRUCTION_AGE_BAND': '1900-1929',
            'CURRENT_ENERGY_RATING': 'D',
            'WALLS_DESCRIPTION': 'Solid brick wall',
            'MAINHEAT_DESCRIPTION': 'Gas boiler',
            'TOTAL_FLOOR_AREA': 95,
            'ENERGY_CONSUMPTION_CURRENT': 180,
            'CO2_EMISSIONS_CURRENT': -0.5,
            'LODGEMENT_DATE': '2023-01-03',
        },
    ])

    validator = EPCDataValidator()
    df_validated, report = validator.validate_dataset(df)

    assert len(df_validated) == 1
    assert report['negative_energy_values'] == 1
    assert report['negative_co2_values'] == 1
    assert (df_validated['ENERGY_CONSUMPTION_CURRENT'] < 0).sum() == 0
    assert (df_validated['CO2_EMISSIONS_CURRENT'] < 0).sum() == 0

