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

**Core Requirements**:
- Python 3.11 or higher
- pip package manager

**For Spatial Analysis (Heat Network Tiers)**:
- **Option A (Recommended)**: Miniconda/Anaconda - handles GDAL automatically
- **Option B**: Manual GDAL installation (complex on Windows)
- **Option C**: Skip spatial analysis - 85% of functionality still works!

### 🚀 Quick Start (Recommended Methods)

#### Method 1: Conda Launcher (Best for Windows + Spatial Analysis)

**Recommended if you want heat network tier analysis on Windows!**

This method automatically installs GDAL/geopandas via Conda, avoiding Windows installation issues.

**Step 1**: Install Miniconda (if not already installed)
- Download: https://docs.conda.io/en/latest/miniconda.html
- Run installer with default settings
- Restart your terminal

**Step 2**: Clone and run
```bash
git clone https://github.com/pipnic1234/HeatStreetEPC.git
cd HeatStreetEPC

# Windows Command Prompt
run-conda.bat

# OR Windows PowerShell
.\run-conda.ps1
```

This single command:
- Creates conda environment with Python 3.11
- Installs geopandas + GDAL automatically
- Installs all other dependencies
- Runs the interactive analysis
- **Everything works, including spatial analysis!**

#### Method 2: Standard Launcher (Core Analysis Only)

**Use this if you don't need spatial analysis or have GDAL issues.**

Works perfectly for EPC analysis, scenarios, charts, and reports (85% of functionality).

```bash
git clone https://github.com/pipnic1234/HeatStreetEPC.git
cd HeatStreetEPC

# Windows Command Prompt
run.bat

# OR Windows PowerShell
.\run.ps1

# OR Linux/Mac
./run.sh
```

This automatically:
- Creates virtual environment
- Installs all core dependencies
- Optionally attempts spatial dependencies (may fail on Windows)
- Runs the interactive analysis

**The analysis works even if spatial dependencies fail!**

#### Method 3: Manual Setup (Advanced Users)

See [Manual Setup](#manual-setup-all-platforms) section below.

### Manual Setup (All Platforms)

<details>
<summary>Click to expand manual setup instructions</summary>

#### Step 1: Clone the repository

**Windows (PowerShell)**:
```powershell
git clone https://github.com/pipnic1234/HeatStreetEPC.git
cd HeatStreetEPC
```

**Linux/Mac**:
```bash
git clone https://github.com/pipnic1234/HeatStreetEPC.git
cd HeatStreetEPC
```

#### Step 2: Create virtual environment

**All platforms**:
```bash
python -m venv venv
```

#### Step 3: Activate virtual environment

**Windows PowerShell**:
```powershell
.\venv\Scripts\Activate.ps1
```

**Windows Command Prompt**:
```cmd
venv\Scripts\activate.bat
```

**Linux/Mac**:
```bash
source venv/bin/activate
```

#### Step 4: Install dependencies

**All platforms**:
```bash
pip install -r requirements.txt
```

#### Step 5: Verify installation

**All platforms**:
```bash
python -c "from config.config import load_config; print('✓ Installation successful!')"
```

</details>

### Troubleshooting

#### Common Issues

**Windows: "cannot be loaded because running scripts is disabled"**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**Any platform: "python is not recognized"**
- Ensure Python is in your PATH
- Try using `python3` instead of `python`
- Reinstall Python and check "Add to PATH" during installation

**Conda: "conda is not recognized"**
- Install Miniconda: https://docs.conda.io/en/latest/miniconda.html
- Restart your terminal after installation
- Use `run-conda.bat` or `run-conda.ps1` (not `run.bat`)

**GDAL/Geopandas installation fails with run.bat**
- This is normal on Windows!
- The core analysis still works (85% of functionality)
- For spatial analysis, use `run-conda.bat` instead
- See [docs/SPATIAL_SETUP.md](docs/SPATIAL_SETUP.md) for detailed guide

**"No module named 'osgeo'" during spatial analysis**
- GDAL not installed
- Use `run-conda.bat` for automatic installation
- Or skip spatial analysis (analysis works without it)

#### Which Run Script Should I Use?

| Script | Best For | Spatial Analysis? |
|--------|----------|-------------------|
| `run-conda.bat/ps1` | **Windows users wanting heat network tiers** | ✅ Yes (auto-installs GDAL) |
| `run.bat/ps1` | Quick start, core analysis only | ⚠️ Attempts install (may fail) |
| `setup.bat/ps1` | First-time setup only | ❌ No (run separately) |

**Recommendation**: Use `run-conda.bat` if you want the complete analysis with spatial features on Windows!

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

### 🎯 Interactive Analysis (Recommended)

The easiest way to run the complete analysis is using the interactive CLI:

```bash
# If using Conda method
run-conda.bat   # or run-conda.ps1 for PowerShell

# If using standard method
run.bat         # or run.ps1 for PowerShell
```

The interactive CLI will guide you through:

1. **EPC Data Download**
   - Choose borough(s) to analyze
   - Automatically downloads from EPC API
   - Validates and cleans data

2. **Archetype Characterization**
   - Analyzes building fabric (walls, loft, floors, windows)
   - Summarizes heating systems and fuel types
   - Reports EPC band distribution
   - Calculates energy consumption and CO₂ emissions

3. **Scenario Modeling**
   - Models 5 decarbonization pathways
   - Calculates costs, savings, payback periods
   - Estimates EPC band improvements
   - Performs subsidy sensitivity analysis

4. **Spatial Analysis** (if GDAL available)
   - Auto-downloads London GIS data
   - Classifies properties into heat network tiers
   - Calculates heat density (GWh/km²)
   - Generates interactive HTML maps
   - Exports GeoJSON with tier classifications

5. **Visualization & Reports**
   - Creates charts (EPC bands, scenarios, subsidies)
   - Generates formatted Excel workbook
   - Produces executive summary report
   - Saves all outputs to `data/outputs/`

### 📊 Output Locations

After running the analysis, find your results in:

```
data/outputs/
├── figures/
│   ├── epc_band_distribution.png
│   ├── scenario_comparison.png
│   ├── subsidy_sensitivity.png
│   └── heat_network_tiers.png
├── reports/
│   └── executive_summary.txt
├── maps/
│   └── heat_network_tiers.html  (interactive map)
├── analysis_results.xlsx         (comprehensive workbook)
└── properties_with_tiers.geojson (spatial data)
```

### 🔧 Advanced: Command-Line Interface

For automated workflows or specific phases:

```bash
# Activate environment first
conda activate heatstreet  # if using Conda
# OR
.\venv\Scripts\activate    # if using venv

# Run specific phases
python run_analysis.py
```

### 🛠️ Advanced: Running Individual Modules

Each module can be run independently for testing:

```bash
# Data acquisition
python src/acquisition/epc_downloader.py

# Data validation
python src/cleaning/data_validator.py

# Archetype analysis
python src/analysis/archetype_analysis.py

# Scenario modeling
python src/modeling/scenario_model.py

# Spatial analysis (requires GDAL)
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
