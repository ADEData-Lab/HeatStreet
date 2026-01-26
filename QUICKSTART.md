# Heat Street EPC - Quick Start Guide

## 🎯 Choose Your Method

### Method 1: Conda (Recommended for Windows + Full Features)

**✅ Best for**: Windows users who want heat network tier analysis

**What you get**: Complete analysis including spatial features (heat density, tier classification, interactive maps)

**Prerequisites**: None! Script handles everything

#### Steps:

1. **Install Miniconda** (5 minutes, one-time only)
   - Download: https://docs.conda.io/en/latest/miniconda.html
   - Run installer, use default settings
   - Restart terminal

2. **Clone repository**
   ```bash
   git clone https://github.com/ADEData-Lab/HeatStreet.git
   cd HeatStreet
   ```

3. **Run Conda launcher**
   ```bash
   # Windows Command Prompt
   run-conda.bat

   # OR Windows PowerShell
   .\run-conda.ps1
   ```

4. **Done!** First run takes 10-15 minutes (downloads ~500MB dependencies). Subsequent runs are instant.

---

### Method 2: Python (Core Features)

**✅ Best for**: Quick testing and core analysis without spatial features

**What you get**: EPC analysis, scenarios, charts, Excel reports (most features)

**Prerequisites**: Python 3.11+

#### Steps:

1. **Clone repository**
   ```bash
   git clone https://github.com/ADEData-Lab/HeatStreet.git
   cd HeatStreet
   ```

2. **Create environment + install dependencies**
   ```bash
   python -m venv venv
   # Activate venv (platform-specific)
   # Windows PowerShell: .\venv\Scripts\Activate.ps1
   # Windows Cmd:       venv\Scripts\activate.bat
   # Linux/Mac:         source venv/bin/activate

   pip install -r requirements.txt
   ```

3. **Run**
   ```bash
   python run_analysis.py
   ```

For spatial analysis on Windows, use Method 1 (Conda) or see `docs/SPATIAL_SETUP.md`.

---

## 📊 What Gets Analyzed?

The interactive CLI guides you through:

### Phase 1: Data Download
- Select London borough(s)
- Auto-downloads from EPC Register API
- Example: "Islington" → downloads ~4,200 properties

### Phase 2: Archetype Analysis
**Analyzes**:
- EPC band distribution (A-G ratings)
- Wall types (solid/cavity) and insulation status
- Loft insulation thickness
- Heating systems (boiler types, fuel)
- Energy consumption (kWh/year)
- CO₂ emissions (kg/year)

**Outputs**:
- Console summary with statistics
- `archetype_analysis_results.txt`

### Phase 3: Scenario Modeling
**Models 5 pathways**:
1. **Baseline** (do nothing)
2. **Fabric improvements** (insulation only)
3. **Heat pump** (fabric + air-source heat pump)
4. **District heating** (modest fabric + network connection)
5. **Hybrid** (optimal mix based on location)

**For each scenario calculates**:
- Capital costs (per property and total stock)
- Annual energy savings (kWh)
- CO₂ reductions (kg)
- Bill savings (£/year)
- Payback period (years)
- New EPC bands

**Performs subsidy sensitivity (multi-pathway)**:
- Tests subsidy levels (default: 0%, 25%, 50%, 75%, 100%) for multiple pathways (e.g., `heat_pump`, `hybrid`, `heat_network`)
- Recalculates payback and maps payback to an illustrative uptake rate using a smooth logistic adoption curve (rather than step-change thresholds)
- Calculates upgraded properties, total public expenditure, and implied public cost per tonne CO2 abated (over the analysis horizon)

**Outputs**:
- Console comparison tables
- `scenario_comparison.png` (chart)
- `subsidy_sensitivity_analysis.csv` (table; may be archived to `data/outputs/bin/run_<timestamp>/` in one-stop-only mode)
- Section 9 in `one_stop_output.json` and the "Subsidy Sensitivity" tab in `one_stop_dashboard.html`
- `subsidy_sensitivity.png` (optional static chart)
- `scenario_modeling_results.txt`

### Phase 4: Spatial Analysis (Conda method only)
**Uses multiple evidence layers**:
- **DESNZ/BEIS Heat Network Planning Database (HNPD, Jan 2024)** for up-to-date heat network scheme locations (Tier 1 evidence; London fallback if unavailable)
- **London Heat Map GIS package (legacy)** for zone / “potential network” geometries used by the Tier 2 overlay (optional)
- **EPC-derived heat demand** to compute local heat density for Tier 3–5

**Classifies properties into tiers**:
- **Tier 1**: Within 250m of existing heat network
- **Tier 2**: Within designated Heat Network Zone
- **Tier 3**: High heat density (≥20 GWh/km²; configurable in `config/config.yaml`)
- **Tier 4**: Moderate density (5-20 GWh/km²)
- **Tier 5**: Low density (<5 GWh/km²)

**Recommends pathways by tier**:
- Tiers 1-3 → District heating preferred
- Tiers 4-5 → Heat pumps recommended

**Auto-downloads London GIS data**:
- Heat loads (33 boroughs)
- Existing district heating networks
- Planned Heat Network Zones
- Heat supply infrastructure

**Outputs**:
- `properties_with_tiers.geojson` (spatial data)
- `pathway_suitability_by_tier.csv` (recommendations)
- `heat_network_tiers.html` (interactive map)
- `heat_density_distribution.png` (chart)

### Phase 5: Visualization & Reporting
**Creates**:
- EPC band distribution charts
- Scenario comparison charts
- Subsidy sensitivity analysis
- Heat network tier maps (if spatial ran)
- Executive summary report
- Comprehensive Excel workbook with:
  - Executive Summary sheet
  - EPC Bands breakdown
  - Scenario Comparison table
  - Subsidy Sensitivity matrix
  - Property Sample (first 1,000 properties)

**All outputs saved to**: `data/outputs/`

---

## 🔍 Example Session

```
========================================
Heat Street EPC Analysis (Conda)
========================================

[OK] Conda found!
[OK] Environment 'heatstreet' already exists
[OK] Activating conda environment...
[OK] Geopandas already installed
[OK] Installing/updating core dependencies...
[OK] All dependencies ready!
[OK] GDAL version: 3.6.2
[OK] Geopandas version: 0.13.2

========================================
Starting Interactive Analysis
========================================

Phase 1: Data Acquisition
--------------------------
Enter borough name (or 'all' for all London): Islington
Downloading EPC data for Islington...
✓ Downloaded 4,234 properties
✓ Validated and cleaned
✓ Saved to data/processed/epc_islington_validated.csv

Phase 2: Archetype Analysis
----------------------------
Analyzing 4,234 properties...

EPC Band Distribution:
  Band C: 1,609 (38%)
  Band D: 2,117 (50%)
  Band E: 480 (11%)
  Band F: 28 (1%)

Wall Construction:
  Solid walls: 2,710 (64%)
  Wall insulation: 1,017 (24%)

Heating Systems:
  Gas boiler: 4,022 (95%)
  Electric heating: 212 (5%)

✓ Results saved to data/outputs/archetype_analysis_results.txt

Phase 3: Scenario Modeling
---------------------------
Modeling 5 decarbonization pathways...

Scenario Comparison (4,234 properties):
                      Capital Cost    Annual Savings    Payback    CO₂ Reduction
Fabric Only           £42.1M         £2.8M/year        15 years   35%
Heat Pump             £105.3M        £5.1M/year        21 years   72%
District Heating      £31.8M         £4.2M/year        8 years    68%
Hybrid (Optimal)      £67.2M         £4.8M/year        14 years   70%

✓ Charts saved to data/outputs/figures/
✓ Results saved to data/outputs/scenario_modeling_results.txt

Phase 4: Spatial Analysis
--------------------------
Checking for London GIS data...
✓ GIS data found: data/supplementary/GIS_All_Data/
✓ Loading heat loads for Islington...
✓ Loading existing heat networks...

Geocoding properties...
✓ 4,108/4,234 properties geocoded (97%)

Calculating heat density...
✓ Using 250m buffers for spatial aggregation
✓ Heat density range: 2.3 - 47.8 GWh/km²

Classifying heat network tiers...
  Tier 1 (Existing network): 328 properties (8%)
  Tier 2 (Planned HN zone): 892 properties (22%)
  Tier 3 (High density): 1,456 properties (36%)
  Tier 4 (Medium density): 1,189 properties (29%)
  Tier 5 (Low density): 243 properties (6%)

Pathway Recommendations:
  District Heating suitable: 2,676 properties (65%)
  Heat Pump recommended: 1,432 properties (35%)

✓ GeoJSON saved to data/outputs/properties_with_tiers.geojson
✓ CSV saved to data/outputs/pathway_suitability_by_tier.csv
✓ Interactive map saved to data/outputs/maps/heat_network_tiers.html

Phase 5: Visualization & Reporting
-----------------------------------
Generating visualizations...
✓ EPC band distribution chart
✓ Scenario comparison chart
✓ Subsidy sensitivity chart
✓ Heat network tier distribution chart

Exporting to Excel...
✓ Excel workbook saved to data/outputs/analysis_results.xlsx

Creating executive summary...
✓ Report saved to data/outputs/reports/executive_summary.txt

========================================
[OK] Analysis complete!

Check data\outputs\ for results:
  - Figures: data\outputs\figures\
  - Reports: data\outputs\reports\
  - Excel: data\outputs\analysis_results.xlsx
  - Maps: data\outputs\maps\heat_network_tiers.html
  - GeoJSON: data\outputs\properties_with_tiers.geojson
========================================
```

---

## 📁 Output Files

After analysis completes, find your results:

```
data/outputs/
│
├── figures/
│   ├── epc_band_distribution.png          # Current EPC ratings
│   ├── sap_score_distribution.png         # SAP score histogram
│   ├── scenario_comparison.png            # Cost vs savings by scenario
│   ├── subsidy_sensitivity.png            # Impact of subsidy levels
│   └── heat_network_tiers.png             # Tier distribution (spatial)
│
├── reports/
│   ├── archetype_analysis_results.txt     # Detailed property statistics
│   ├── scenario_modeling_results.txt      # Scenario cost-benefit analysis
│   └── executive_summary.txt              # High-level summary
│
├── maps/
│   └── heat_network_tiers.html            # Interactive Folium map
│
├── analysis_results.xlsx                  # Comprehensive Excel workbook
├── properties_with_tiers.geojson          # Spatial data with tier classification
└── pathway_suitability_by_tier.csv        # Recommendations by tier
```

---

## ⚙️ Configuration

### Customize Analysis

Edit `config/config.yaml` before running:

```yaml
# Which boroughs to analyze
geographic_scope:
  boroughs:
    - "Islington"
    - "Camden"
    - "Hackney"

# Property filtering
property_filters:
  construction_period:
    start_year: 1890
    end_year: 1930
  property_types:
    - "Mid-terrace"
    - "End-terrace"

# Scenario costs (£)
costs:
  loft_insulation_topup: 1200
  cavity_wall_insulation: 3500
  solid_wall_insulation: 8000
  ashp_installation: 12000
  heat_network_connection: 5000

# Energy prices (£/kWh)
energy_prices:
  electricity: 0.34
  gas: 0.10
  district_heat: 0.08
```

---

## 🔧 Troubleshooting

### "Conda is not recognized"
→ Install Miniconda: https://docs.conda.io/en/latest/miniconda.html
→ Restart terminal
→ Use `run-conda.bat` or `.\run-conda.ps1`

### "No module named 'osgeo'" or GDAL errors
→ Conda auto-installs GDAL correctly
→ Use `run-conda.bat` / `.\run-conda.ps1`
→ Or run without spatial analysis (the pipeline will skip spatial steps if GIS libs are missing)

### "Cannot be loaded because running scripts is disabled"
→ PowerShell security policy issue
→ Run: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`

### No properties downloaded
→ Check borough spelling (case-sensitive)
→ Try "all" to download all London boroughs
→ Check internet connection

### Analysis works but no spatial outputs
→ Spatial analysis requires GDAL
→ Use `run-conda.bat` for automatic installation
→ Or see [docs/SPATIAL_SETUP.md](docs/SPATIAL_SETUP.md)

---

## 📚 Additional Documentation

- **[README.md](README.md)** - Full project documentation
- **[docs/SPATIAL_SETUP.md](docs/SPATIAL_SETUP.md)** - Detailed GDAL installation guide
- **[docs/GIS_DATA.md](docs/GIS_DATA.md)** - London GIS data documentation
- **[docs/INTERACTIVE_MODE.md](docs/INTERACTIVE_MODE.md)** - Interactive CLI guide

---

## 🎓 Learn More

### Heat Network Tiers Explained

| Tier | Heat Density | Distance to Network | Recommendation |
|------|-------------|---------------------|----------------|
| 1 | Any | Within 250m | **Connect now** - lowest cost |
| 2 | Any | Planned-network indicator (zone polygon or HNPD buffer proxy) | **Connect planned** - wait for rollout |
| 3 | ≥20 GWh/km² | Outside zone | **DH viable** - extension worth considering |
| 4 | 5-20 GWh/km² | Outside zone | **Marginal** - consider heat pumps |
| 5 | <5 GWh/km² | Outside zone | **HP recommended** - DH not economical |

Tier 1 evidence is sourced from HNPD (2024) where available. Tier 2 is treated as a **planned network indicator**: if a polygon zone layer is available it is used directly; otherwise the pipeline uses a configurable proximity buffer around HNPD planned scheme points as a proxy.

### Decarbonization Pathways

1. **Fabric First**: Insulate before changing heating system
2. **Heat Pumps**: Best for low-density areas (Tiers 4-5)
3. **District Heating**: Best for high-density areas (Tiers 1-3)
4. **Hybrid**: Optimal mix based on local conditions
5. **Do Nothing**: Baseline for comparison

### Key Metrics

- **SAP Score**: Standard Assessment Procedure (1-100, higher = better)
- **EPC Band**: Energy rating (A=best, G=worst)
- **Heat Density**: GWh/km² - determines DH viability
- **Payback Period**: Years to recover capital investment
- **Carbon Abatement Cost**: £/tCO₂ saved

---

**Need Help?**
Open an issue on GitHub or see full documentation in [README.md](README.md)
