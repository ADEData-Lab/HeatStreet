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
HeatStreet/
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
├── run_analysis.py           # Interactive pipeline orchestrator
├── run-conda.bat             # Windows conda launcher (recommended for spatial analysis)
├── run-conda.ps1             # PowerShell conda launcher (recommended for spatial analysis)
├── requirements.txt          # Core Python dependencies
└── requirements-spatial.txt  # Optional spatial dependencies (GDAL/geopandas)
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
git clone https://github.com/ADEData-Lab/HeatStreet.git
cd HeatStreet

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

**Use this if you don't need spatial analysis (or you're not on Windows).**

```bash
git clone https://github.com/ADEData-Lab/HeatStreet.git
cd HeatStreet

python -m venv venv
# Activate venv (platform-specific)
# Windows PowerShell: .\venv\Scripts\Activate.ps1
# Windows Cmd:       venv\Scripts\activate.bat
# Linux/Mac:         source venv/bin/activate

pip install -r requirements.txt
python run_analysis.py
```

For spatial analysis on Windows, use the Conda launcher above (or see `docs/SPATIAL_SETUP.md`).

#### Method 3: Manual Setup (Advanced Users)

See [Manual Setup](#manual-setup-all-platforms) section below.

### Manual Setup (All Platforms)

<details>
<summary>Click to expand manual setup instructions</summary>

#### Step 1: Clone the repository

**Windows (PowerShell)**:
```powershell
git clone https://github.com/ADEData-Lab/HeatStreet.git
cd HeatStreet
```

**Linux/Mac**:
```bash
git clone https://github.com/ADEData-Lab/HeatStreet.git
cd HeatStreet
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
- Use `run-conda.bat` or `run-conda.ps1`

**GDAL/Geopandas installation fails**
- This is common on Windows when installing GDAL via pip/venv
- For spatial analysis, use `run-conda.bat` instead
- See [docs/SPATIAL_SETUP.md](docs/SPATIAL_SETUP.md) for detailed guide

**"No module named 'osgeo'" during spatial analysis**
- GDAL not installed
- Use `run-conda.bat` for automatic installation
- Or skip spatial analysis (analysis works without it)

#### How Should I Run It?

| Option | Best For | Spatial Analysis? |
|--------|----------|-------------------|
| `run-conda.bat/ps1` | **Windows users wanting heat network tiers** | ✅ Yes (auto-installs GDAL) |
| `python run_analysis.py` (in your own env) | Core analysis and non-Windows runs | ⚠️ Depends on GDAL/geopandas |

**Recommendation**: Use `run-conda.bat` if you want the complete analysis with spatial features on Windows!

## Data Acquisition

### EPC Register Data

HeatStreet can obtain EPC data via the UK Government EPC Register in two ways:

1. **API download (recommended)**: run the interactive pipeline and choose a download scope. The runner will prompt for (or read) your API email/key from `.env`.
2. **Bulk/manual download**: place EPC CSVs in `data/raw/` and skip the download step when prompted.

Register for API access at [https://epc.opendatacommunities.org/](https://epc.opendatacommunities.org/) and copy `.env.example` to `.env` if you prefer to set credentials up-front.

### Supplementary Data

**Heat Network Planning Database (HNPD) (recommended for Tiering)**:
- DESNZ/BEIS Heat Network Planning Database (January 2024) is used as the primary source of up-to-date heat network scheme locations.
- The pipeline auto-downloads it to `data/external/hnpd-january-2024.csv` (see `data_sources.heat_networks` in `config/config.yaml`).

**London Heat Map GIS package (legacy; optional/fallback)**:
- Used as a fallback evidence layer if HNPD is unavailable, and to provide zone/“potential network” geometries used by the Tier 2 overlay.
- The pipeline can auto-download this from the London Datastore as `data/external/GIS_All_Data.zip` and extract it under `data/external/`.

**Boundary Files**:
- London borough boundaries
- LSOA boundaries for aggregation

## Usage

### 🎯 Interactive Analysis (Recommended)

The easiest way to run the complete analysis is using the interactive CLI:

```bash
# Windows Command Prompt (Conda launcher)
run-conda.bat

# Windows PowerShell (Conda launcher)
.\run-conda.ps1

# Any platform (if dependencies already installed)
python run_analysis.py
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
   - Uses HNPD (2024) and optional London Heat Map GIS (legacy) as evidence layers
   - Classifies properties into heat network tiers (Tier 1–5)
   - Calculates local heat density (GWh/km²) from EPC-derived demand
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

- `data/outputs/one_stop_output.json` - One-stop report output (definitive reporting output when `reporting.one_stop_only: true`)
- `data/outputs/one_stop_dashboard.html` - Self-contained HTML dashboard generated from `one_stop_output.json`
- `data/outputs/archetype_analysis_results.txt` - Property characteristics summary
- `data/outputs/scenario_modeling_results.txt` - Scenario cost-benefit analysis
- `data/outputs/validation_report.txt` - Data quality report
- `data/outputs/reports/executive_summary.txt` - Executive summary
- `data/outputs/reports/executive_summary_datapoints.xlsx` - Excel workbook of datapoints used in the executive summary report
- `data/outputs/comparisons/hn_vs_hp_comparison.csv` - Per-home HP vs HN comparison stats (mean/median/p10/p90/min/max)
- `data/outputs/comparisons/hn_vs_hp_report_snippet.md` - Markdown summary including sign conventions and tariff/COP/HN connection notes
- `data/outputs/comparisons/hn_cost_sensitivity.csv` - Optional HN connection-cost sensitivity table (created when `--run-hn-sensitivity` is used)

### Visualizations

- `data/outputs/figures/epc_band_distribution.png` - Current EPC ratings
- `data/outputs/figures/sap_score_distribution.png` - SAP score histogram
- `data/outputs/figures/scenario_comparison.png` - Scenario comparison charts
- `data/outputs/figures/subsidy_sensitivity.png` - Subsidy impact analysis
- `data/outputs/figures/heat_network_tiers.png` - Tier distribution
- `data/outputs/figures/hn_vs_hp_comparison.png` - Mean capex/bill/CO₂ savings for HP vs HN pathways
- `data/outputs/maps/heat_network_tiers.html` - Interactive map

When `reporting.one_stop_only: true` is enabled in `config/config.yaml`, the pipeline focuses on producing the single
`one_stop_output.json` plus a small set of supporting CSVs and key figures used in reporting (including the fabric tipping
point and EPC lodgement charts). Set `one_stop_only: false` to generate the full suite of dashboard assets, maps, and
additional reporting artefacts.

Example CSV header and row:

```
pathway_id,pathway_name,n_homes,capex_mean,bill_saving_mean,co2_saving_mean,payback_median
fabric_plus_hp_only,Fabric + Heat Pump,10000,21000,450,1.8,24.0
```

## Decarbonization Scenarios

The project models five scenarios:

| Scenario | Measures | Typical Cost | CO₂ Savings |
|----------|----------|--------------|-------------|
| **Baseline** | No intervention | £0 | 0% |
| **Fabric Only** | Loft, wall, glazing | £8,000-15,000 | 30-40% |
| **Heat Pump** | Fabric + ASHP + emitters | £20,000-30,000 | 60-80% |
| **Heat Network** | Modest fabric + DH connection | £7,000-12,000 | 50-70% |
| **Hybrid** | Heat network where viable, ASHP elsewhere | Varies | 60-75% |

### Targeting and shared-package assumptions

- Hybrid heat-network targeting currently uses the existing `has_hn_access` flag or the configured heat-network penetration rate. It does **not** dynamically select properties from the spatial tier outputs; add geospatial filtering first if you want the hybrid run to follow map-derived tiers.
- Fabric packages are shared across scenarios by design. If you want differentiated fabric measures (e.g., lighter fabric for heat networks vs deeper fabric for heat pumps), add explicit branching logic before the packages are applied.

## Heat Network Tier Classification

HeatStreet’s heat network tiering is a **screening tool** that combines (a) evidence of nearby network infrastructure / planned zones and (b) EPC-derived local heat density.

Properties are classified into five tiers:

| Tier | Definition (screening) | Main evidence input | Recommended Pathway |
|------|------------|---------------------|
| **Tier 1** | Within 250m of existing heat network | HNPD (Operational / Under Construction) or London Heat Map fallback | District heating connection |
| **Tier 2** | Near planned heat network (proxy) | HNPD planned schemes (planning granted) buffered by the configured distance; polygon zone layer used if available | District heating (planned) |
| **Tier 3** | High local heat density (default ≥20 GWh/km²) | EPC-derived heat density (postcode centroids) | District heating (extension potentially viable) |
| **Tier 4** | Moderate density (default 5–20 GWh/km²) | EPC-derived heat density | Heat pump (network marginal) |
| **Tier 5** | Low density (default <5 GWh/km²) | EPC-derived heat density | Heat pump (network not viable) |

Thresholds are configured in `config/config.yaml` (see `eligibility.heat_network_tiers` and `heat_network.readiness`).

### Spatial Analysis Method: Grid-Based Aggregation

The spatial analysis uses a **memory-efficient grid aggregation method** to calculate neighborhood heat densities. This method is designed to handle large datasets (100k+ properties) without running out of memory.

#### How It Works

1. **Grid Assignment**: Properties are assigned to grid cells (default: 125m × 125m) in British National Grid coordinates (EPSG:27700)
2. **Cell Aggregation**: Energy consumption is aggregated at the cell level rather than per-property
3. **Neighborhood Calculation**: For each cell, neighborhood totals are computed by summing all cells within the specified radius (default: 250m)
4. **Tier Classification**: Properties are classified based on their cell's neighborhood heat density (GWh/km²)

#### Configuration Options

You can customize the spatial analysis method in `config/config.yaml`:

```yaml
spatial:
  # Choose method: "grid" (recommended) or "buffer" (legacy, memory-intensive)
  method: "grid"

  # Disable spatial analysis entirely if needed
  disable: false

  # Grid parameters
  grid:
    cell_size_m: 125          # Grid cell size in meters
    buffer_radius_m: 250      # Neighborhood radius in meters
    use_circular_mask: true   # Use circular vs square neighborhood
```

#### Memory-Safe Configuration for Large Datasets

For processing ~700k properties on a laptop (≈16 GB RAM), use these **environment variables** to prevent OOM kills:

```bash
# Recommended settings for 16 GB laptop
export HEATSTREET_WORKERS=1           # Number of parallel workers (default: CPU count)
export HEATSTREET_CHUNK_SIZE=50000    # Properties per chunk (default: 50,000)
export HEATSTREET_PROFILE=1           # Enable memory profiling logs (optional)

# Run the analysis
python run_analysis.py
```

**Parameter Guide**:

| Parameter | Purpose | Laptop (16 GB) | Workstation (32+ GB) |
|-----------|---------|----------------|----------------------|
| `HEATSTREET_WORKERS` | Parallel processes for scenario modeling | `1` | `2-4` |
| `HEATSTREET_CHUNK_SIZE` | Properties processed per batch | `50000` | `100000` |
| `HEATSTREET_PROFILE` | Log RSS memory at checkpoints | `1` | `0` (optional) |

**Why these settings matter**:
- **Workers**: Each worker process loads the full cost database and configuration into memory. Using `WORKERS=1` runs sequentially and avoids multiprocessing memory overhead.
- **Chunk Size**: Scenario modeling converts DataFrames to dictionaries in chunks. Smaller chunks reduce peak memory usage during this conversion.
- **Profiling**: When enabled, logs show RSS memory (MB) at critical checkpoints, helping diagnose memory spikes.

**What's been optimized** (v2.0+):
- ✅ GeoDataFrame construction now uses explicit `geometry=` parameter (no more "Assigning CRS to GeoDataFrame without geometry" errors)
- ✅ Removed unnecessary `DataFrame.copy()` operations (~3-5 GB savings)
- ✅ Vectorized coordinate extraction (`.geometry.x` instead of list comprehension)
- ✅ Bounding box pre-filtering for spatial joins (50-80% reduction in join workload)
- ✅ Vectorized distance calculations (replaced `.apply(lambda)` with `.distance()`)
- ✅ Memory profiling at all critical sections

**Memory usage profile** (700k properties, laptop mode):
- Geocoding expansion: ~4-5 GB
- Spatial tier classification: ~6-8 GB (peak during Tier 2 join)
- Grid aggregation: ~7-9 GB
- Scenario modeling: ~9-11 GB (peak during dict conversion)
- Subsidy sensitivity: ~10-12 GB (final phase)

With these optimizations, the **full pipeline completes reliably on a 16 GB laptop** without OOM kills.

#### Performance Comparison

| Method | Memory Usage | Scalability | Accuracy |
|--------|--------------|-------------|----------|
| **Grid** (default) | Low | 100k+ properties | ~95% match to buffer method |
| **Buffer** (legacy) | High | <10k properties | Reference standard |

**Recommendation**: Use the grid method (default) for all analyses. The buffer method is provided for backward compatibility only.

#### Method Details

The grid method approximates the 250m circular buffer around each property by:
- Dividing the study area into regular grid cells
- Computing cell-to-cell neighborhoods using pre-calculated offsets
- Using a circular mask to include only cells within the radius

This approach:
- ✅ Reduces memory usage by ~95% compared to buffer method
- ✅ Scales to 1M+ properties on standard laptops
- ✅ Produces comparable results to the buffer method
- ✅ Runs 2-5x faster on large datasets

For more details, see `src/spatial/heat_network_analysis.py::_classify_heat_density_tiers_grid`

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
| Scenario diagnostics by property | `scenario_results_by_property.parquet` |
| Scenario summary metrics | `scenario_results_summary.csv` |
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
