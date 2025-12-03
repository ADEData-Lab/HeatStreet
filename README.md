# Heat Street EPC Analysis

Large-scale Energy Performance Certificate (EPC) analysis for London's Edwardian terraced housing stock, with a focus on decarbonization pathways and heat network zone planning.

## Project Overview

This project analyzes approximately 500,000 EPC certificates for Edwardian and late Victorian terraced houses across London's 33 boroughs to:

- **Characterize** the current state of the housing stock (insulation, heating systems, energy efficiency)
- **Model** different decarbonization pathways (fabric improvements, heat pumps, district heating)
- **Analyze** heat network zone suitability and optimal technology deployment strategies
- **Evaluate** policy interventions and subsidy mechanisms

## Key Features

✅ **Comprehensive Data Pipeline**: Automated EPC data acquisition, cleaning, and validation
✅ **Quality Assurance**: Implements Hardy & Glew validation protocols (addresses 36-62% error rate in EPCs)
✅ **Archetype Analysis**: Detailed characterization of building fabric, heating systems, and energy performance
✅ **Scenario Modeling**: Cost-benefit analysis for multiple decarbonization pathways
✅ **Spatial Analysis**: GIS-based heat network zone overlay and property classification
✅ **Policy Analysis**: Subsidy sensitivity modeling and carbon abatement cost calculations
✅ **Visualization**: Charts, maps, and executive summary reports

## Project Structure

```
HeatStreetEPC/
├── config/
│   ├── config.yaml           # Main configuration file
│   └── config.py             # Configuration loader
├── data/
│   ├── raw/                  # Raw EPC data files
│   ├── processed/            # Cleaned and validated data
│   ├── supplementary/        # Heat map and boundary files
│   └── outputs/              # Analysis outputs, figures, reports
├── src/
│   ├── acquisition/          # EPC data download modules
│   ├── cleaning/             # Data validation and cleaning
│   ├── analysis/             # Archetype characterization
│   ├── modeling/             # Scenario modeling
│   ├── spatial/              # Heat network zone analysis
│   ├── reporting/            # Visualization and reporting
│   └── utils/                # Utility functions
├── tests/                    # Unit tests
├── docs/                     # Additional documentation
├── notebooks/                # Jupyter notebooks for exploration
├── main.py                   # Main pipeline orchestrator
└── requirements.txt          # Python dependencies
```

## Installation

### Prerequisites

- Python 3.9 or higher
- pip package manager
- (Optional) PostgreSQL for large datasets

### Setup

1. **Clone the repository**:
```bash
git clone https://github.com/pipnic1234/HeatStreetEPC.git
cd HeatStreetEPC
```

2. **Create a virtual environment**:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**:
```bash
pip install -r requirements.txt
```

4. **Verify installation**:
```bash
python -c "from config.config import load_config; print('✓ Installation successful!')"
```

## Data Acquisition

### EPC Register Data

EPC data must be obtained from the UK Government's EPC Register:

1. **Register** at [https://epc.opendatacommunities.org/](https://epc.opendatacommunities.org/)
2. **Download** bulk data for London boroughs (see `data/raw/DOWNLOAD_INSTRUCTIONS.txt`)
3. **Place** CSV files in `data/raw/` directory with naming pattern `epc_*.csv`

Alternatively, run:
```bash
python main.py --phase acquire --download
```
This creates detailed download instructions.

### Supplementary Data

**London Heat Map** (optional but recommended):
- Heat network locations: Download from [London Datastore](https://data.london.gov.uk/)
- Heat Network Zones: [GLA Heat Network Zones](https://www.london.gov.uk/programmes-strategies/environment-and-climate-change/energy/london-heat-map)
- Place GeoJSON/Shapefile in `data/supplementary/`

**Boundary Files**:
- London borough boundaries
- LSOA boundaries for aggregation

## Usage

### Running the Complete Pipeline

```bash
python main.py --phase all
```

This executes all phases:
1. Data acquisition
2. Data cleaning & validation
3. Archetype characterization
4. Scenario modeling
5. Spatial analysis
6. Report generation

### Running Individual Phases

**Data Cleaning Only**:
```bash
python main.py --phase clean
```

**Archetype Analysis Only**:
```bash
python main.py --phase analyze
```

**Scenario Modeling Only**:
```bash
python main.py --phase model
```

**Spatial Analysis Only**:
```bash
python main.py --phase spatial
```

**Report Generation Only**:
```bash
python main.py --phase report
```

### Running Individual Modules

Each module can also be run independently:

```bash
# Data acquisition
python src/acquisition/epc_downloader.py

# Data validation
python src/cleaning/data_validator.py

# Archetype analysis
python src/analysis/archetype_analysis.py

# Scenario modeling
python src/modeling/scenario_model.py

# Spatial analysis
python src/spatial/heat_network_analysis.py
```

## Configuration

Edit `config/config.yaml` to customize:

- **Geographic scope**: London boroughs to include
- **Property filters**: Construction period, property types
- **Quality thresholds**: Floor area ranges, required fields
- **Scenario definitions**: Measures for each pathway
- **Cost assumptions**: Installation costs, energy prices
- **Subsidy levels**: For sensitivity analysis

Example:
```yaml
property_filters:
  construction_period:
    end_year: 1930
  property_types:
    - "Mid-terrace"
    - "End-terrace"

scenarios:
  heat_pump:
    name: "Heat pump pathway"
    measures:
      - "loft_insulation_topup"
      - "wall_insulation"
      - "ashp_installation"
```

## Key Outputs

### Data Files

- `data/processed/epc_london_validated.csv` - Cleaned EPC dataset
- `data/processed/epc_london_with_tiers.geojson` - Properties with heat network tier classification
- `data/outputs/pathway_suitability_by_tier.csv` - Recommended pathways by tier

### Analysis Reports

- `data/outputs/archetype_analysis_results.txt` - Property characteristics summary
- `data/outputs/scenario_modeling_results.txt` - Scenario cost-benefit analysis
- `data/outputs/validation_report.txt` - Data quality report
- `data/outputs/reports/executive_summary.txt` - Executive summary

### Visualizations

- `data/outputs/figures/epc_band_distribution.png` - Current EPC ratings
- `data/outputs/figures/sap_score_distribution.png` - SAP score histogram
- `data/outputs/figures/scenario_comparison.png` - Scenario comparison charts
- `data/outputs/figures/subsidy_sensitivity.png` - Subsidy impact analysis
- `data/outputs/figures/heat_network_tiers.png` - Tier distribution
- `data/outputs/maps/heat_network_tiers.html` - Interactive map

## Decarbonization Scenarios

The project models five scenarios:

| Scenario | Measures | Typical Cost | CO₂ Savings |
|----------|----------|--------------|-------------|
| **Baseline** | No intervention | £0 | 0% |
| **Fabric Only** | Loft, wall, glazing | £8,000-15,000 | 30-40% |
| **Heat Pump** | Fabric + ASHP + emitters | £20,000-30,000 | 60-80% |
| **Heat Network** | Modest fabric + DH connection | £7,000-12,000 | 50-70% |
| **Hybrid** | Heat network where viable, ASHP elsewhere | Varies | 60-75% |

## Heat Network Tier Classification

Properties are classified into five tiers:

| Tier | Definition | Recommended Pathway |
|------|------------|---------------------|
| **Tier 1** | Within 250m of existing heat network | District heating connection |
| **Tier 2** | Within designated Heat Network Zone | District heating (planned) |
| **Tier 3** | High heat density (>3,000 kWh/m/year) | District heating (extension viable) |
| **Tier 4** | Moderate heat density (1,500-3,000) | Heat pump (network marginal) |
| **Tier 5** | Low heat density (<1,500) | Heat pump (network not viable) |

## Analysis Methodology

### Data Quality Validation

Based on Hardy & Glew (2019) findings:
- Duplicate removal (by UPRN/address, keep most recent)
- Floor area validation (25-400 m²)
- Built form consistency checks
- Construction date verification
- Insulation logic validation (e.g., no cavity fill in solid walls)

### Archetype Characterization

Summary statistics for:
- EPC band distribution
- SAP score (mean, median, percentiles)
- Wall construction and insulation status
- Loft insulation thickness categories
- Floor insulation presence
- Window glazing types
- Heating systems and fuel types
- Current energy consumption (kWh/m²/year)
- CO₂ emissions (kg/m²/year)

### Scenario Modeling

For each property:
1. Calculate intervention costs based on property characteristics
2. Estimate energy savings (using simplified RdSAP methodology)
3. Calculate CO₂ reductions
4. Compute bill savings (current and projected energy prices)
5. Determine payback period
6. Estimate new EPC band

Aggregate to stock level:
- Total capital costs
- Annual energy/CO₂ savings
- Payback distribution
- EPC band shift analysis

### Subsidy Sensitivity

Model subsidy levels: 0%, 25%, 50%, 75%, 100%

For each level:
- Adjusted payback period
- Estimated uptake rate (based on payback thresholds)
- Public expenditure required
- Carbon abatement cost (£/tCO₂)

## Deliverables Mapping

This project delivers all contract requirements:

| Contract Element | Output Location |
|------------------|-----------------|
| Insulation levels analysis | `archetype_analysis_results.txt` |
| Heating systems analysis | `archetype_analysis_results.txt` |
| Energy consumption estimates | `archetype_analysis_results.txt` |
| EPC ratings and scores | `archetype_analysis_results.txt` |
| Carbon impact | `archetype_analysis_results.txt` |
| Energy efficiency options | `scenario_modeling_results.txt` |
| Costed decarbonization pathways | `scenario_modeling_results.txt` |
| District heating analysis | `pathway_suitability_by_tier.csv` |
| Heat pump pathway analysis | `scenario_modeling_results.txt` |
| Subsidy impact analysis | `subsidy_sensitivity.png` |
| Policy implications | `executive_summary.txt` |

## Timeline & Milestones

- **Phase 1 (Data Acquisition)**: Complete by 3 Dec
- **Phase 2 (Data Cleaning)**: Complete by 5 Dec
- **Phase 3 (Archetype Analysis)**: Complete by 7 Dec
- **Phase 4 (Spatial Overlay)**: Complete by 8 Dec
- **Phase 5 (Scenario Modeling)**: Complete by 11 Dec
- **Phase 6 (Subsidy Analysis)**: Complete by 13 Dec
- **Phase 7 (Final Reporting)**: Complete by 15 Dec

## Testing

Run unit tests:
```bash
pytest tests/
```

Run with coverage:
```bash
pytest --cov=src tests/
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/new-analysis`)
3. Commit changes (`git commit -am 'Add new analysis module'`)
4. Push to branch (`git push origin feature/new-analysis`)
5. Create Pull Request

## References

- Hardy, A., & Glew, D. (2019). An analysis of errors in the Energy Performance certificate database. *Energy Policy*, 129, 1168-1178.
- UK EPC Register: https://epc.opendatacommunities.org/
- London Heat Map: https://www.london.gov.uk/programmes-strategies/environment-and-climate-change/energy/london-heat-map
- RdSAP Methodology: https://www.bre.co.uk/sap/

## License

This project is licensed under the MIT License - see LICENSE file for details.

## Contact

For questions or issues:
- Open an issue on GitHub
- Contact: [project lead email]

## Acknowledgments

- UK Government EPC Register for open data access
- Greater London Authority for London Heat Map data
- Hardy & Glew for EPC quality assurance methodology
- Case street residents (Shakespeare Crescent) for local calibration data

---

**Version**: 1.0.0
**Last Updated**: December 2025
**Status**: Active Development
