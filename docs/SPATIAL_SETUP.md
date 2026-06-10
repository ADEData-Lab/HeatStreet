# Spatial Setup

## Windows: Supported Workflow

The supported Windows path for spatial analysis is a fresh Conda environment built from the repo's root `environment.yml`. Do not use `pip install -r requirements-spatial.txt` as the default Windows setup path.

```bash
git clone https://github.com/ADEData-Lab/HeatStreet.git
cd HeatStreet
conda env create -f environment.yml
conda activate heatstreet
.\run-conda.ps1
```

If the environment already exists:

```bash
conda env update -n heatstreet -f environment.yml --prune
conda activate heatstreet
.\run-conda.ps1
```

`environment.yml` installs the GDAL-backed stack from `conda-forge`:

- `geopandas`
- `fiona`
- `gdal`
- `pyproj`
- `shapely`
- `rtree`
- `pyogrio`
- `folium`

The launcher then installs `requirements.txt` without asking pip to build Fiona/GDAL from source.
It is also the canonical Windows path for verifying that `python`, `pip`, and `CONDA_PREFIX` match before the interactive pipeline reaches Phase 1.

## Supported Python Versions

- Windows spatial default: Python 3.11 from `environment.yml`
- Also supported if you intentionally create the env that way: Python 3.12
- Not the supported default in this repo yet: Python 3.13 and 3.14

## Why Windows Pip Fails

The common failure mode is a mixed shell:

- `conda info` reports one interpreter
- `python --version` resolves to another
- `pip` points into `AppData\Roaming\Python\...`
- `fiona` falls back to a source build and asks for `GDAL_VERSION` or `gdal-config`

The fix is not to debug the pip build. The fix is to use the Conda environment from `environment.yml`.

## Diagnosis Commands

Run these in the shell you plan to use:

```powershell
where python
where pip
conda info
conda list | findstr /i "python geopandas fiona gdal shapely"
```

What you want to see:

- `python` and `pip` resolve inside the active Conda env
- `conda info` shows the same active env you just activated
- `conda list` shows the geospatial packages inside that env

## What `run-conda` Validates

The hardened launchers now fail fast when:

- no dedicated Conda env is active
- `python` is not coming from the active env
- `pip` is not coming from the active env
- the active Windows interpreter is not Python 3.11 or 3.12

They also warn when user-site Python executables are visible on PATH, because that is a common precursor to mixed installs.

## Linux / macOS Fallback

If you already manage system GDAL tooling on Linux or macOS, you can still use:

```bash
pip install -r requirements.txt
pip install -r requirements-spatial.txt
python run_analysis.py
```

That file remains a fallback for non-Windows or advanced environments. It is not the primary Windows path.

## Verification

Once the Conda env is active, these imports should succeed:

```bash
python -c "import geopandas, fiona, pyogrio, pyproj, shapely, folium; from osgeo import gdal; print(geopandas.__version__)"
```

Then start the pipeline:

```bash
python run_analysis.py
```

Or, on Windows, use the canonical launcher again:

```bash
.\run-conda.ps1
```

## If You Do Not Need Spatial Analysis

The rest of the project still works without GIS dependencies:

- EPC download and validation
- archetype analysis
- scenario modeling
- charts, workbooks, and reports

Spatial setup is only required for heat-network tier classification and map outputs.
