# Heat Street Quick Start

## Choose Your Path

### Windows + Spatial Analysis

This is the supported path if you want heat-network tiering, GIS outputs, and maps on Windows.

```bash
git clone https://github.com/ADEData-Lab/HeatStreet.git
cd HeatStreet
conda env create -f environment.yml
conda activate heatstreet

# Command Prompt
run-conda.bat

# PowerShell
.\run-conda.ps1
```

What this does:

- Uses the repo's canonical Conda environment in `environment.yml`
- Installs `geopandas`, `fiona`, `gdal`, `pyproj`, `shapely`, `rtree`, `pyogrio`, and `folium` from `conda-forge`
- Installs the remaining pure-Python app dependencies from `requirements.txt`
- Validates that `python`, `pip`, and the active Conda env are aligned before any install step
- Keeps `run-conda.ps1` / `run-conda.bat` as the canonical Windows launch path for Phase 1 runtime validation

Supported Windows Python versions for the spatial stack: 3.11 and 3.12. `environment.yml` defaults to Python 3.11. Python 3.13 and 3.14 are not the supported default here yet.

### Core Analysis Only

If you do not need GIS features, a normal virtual environment is enough:

```bash
git clone https://github.com/ADEData-Lab/HeatStreet.git
cd HeatStreet
python -m venv venv

# Activate venv
# Windows PowerShell: .\venv\Scripts\Activate.ps1
# Windows Cmd:       venv\Scripts\activate.bat
# Linux/Mac:         source venv/bin/activate

pip install -r requirements.txt
python run_analysis.py
```

Windows users should still prefer `run-conda.ps1` / `run-conda.bat` unless they have already verified that `python`, `pip`, and the active Conda prefix all resolve to the same environment.

### Linux / macOS Spatial Fallback

`requirements-spatial.txt` remains available for non-Windows setups that already have working GDAL tooling:

```bash
pip install -r requirements.txt
pip install -r requirements-spatial.txt
python run_analysis.py
```

## Windows Troubleshooting

### `conda info` shows one Python but `python --version` shows another

That shell is mixed. Recreate or refresh the Conda env, reactivate it, and rerun the launcher:

```bash
conda env update -n heatstreet -f environment.yml --prune
conda activate heatstreet
.\run-conda.ps1
```

Diagnosis commands:

```powershell
where python
where pip
conda info
conda list | findstr /i "python geopandas fiona gdal shapely"
```

The new startup diagnostics in `run_analysis.py` also print `sys.executable`, the working directory, the live `run_analysis.py` path, and the resolved source lines for the staged Phase 1 functions so checkout/interpreter mismatches are obvious immediately.

### `pip` resolves into `AppData\Roaming\Python\...`

Your user-site scripts are ahead of the Conda env on PATH. The hardened launcher will stop instead of letting pip install into the wrong interpreter. Reactivate the env or open a fresh Conda-enabled shell.

### `fiona` asks for `GDAL_VERSION` or `gdal-config`

That means pip is trying to build the geospatial stack from source. On Windows, do not continue with pip. Use:

```bash
conda env create -f environment.yml
conda activate heatstreet
.\run-conda.ps1
```

### PowerShell script execution is disabled

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

## What Runs

`run_analysis.py` drives the interactive pipeline:

1. EPC data download or reuse of local source files
2. Validation and cleaning
3. Archetype analysis
4. Scenario modeling
5. Optional spatial analysis if GIS libraries are installed
6. Reports, charts, and exports under `data/outputs/`

Key spatial outputs:

- `data/processed/epc_with_heat_network_tiers.geojson`
- `data/outputs/pathway_suitability_by_tier.csv`
- `data/outputs/maps/heat_network_tiers.html`

## Environment Refresh

If the repo dependencies change, refresh the Windows Conda env with:

```bash
conda env update -n heatstreet -f environment.yml --prune
conda activate heatstreet
```

Then rerun `run-conda.bat` or `.\run-conda.ps1`.
