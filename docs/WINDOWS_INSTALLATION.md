# Windows Installation Guide

## Quick Setup (No Spatial Features)

Most users don't need the spatial analysis features. Here's the quick setup:

```powershell
# 1. Create virtual environment
python -m venv venv

# 2. Activate it
.\venv\Scripts\Activate.ps1

# 3. Install core dependencies (this will work!)
pip install -r requirements.txt

# 4. Verify
python -c "from config.config import load_config; print('Setup complete!')"
```

✅ **You're done!** You can now run:
- Data acquisition
- Data cleaning and validation
- Archetype characterization
- Scenario modeling
- Reporting and visualization

## What About Spatial Analysis?

The spatial analysis module (heat network tier mapping) requires GDAL, which is difficult to install on Windows.

### Option 1: Skip It (Recommended)

Most of the analysis works fine without spatial features. The spatial module only adds:
- Heat network tier classification (you can do this manually in Excel)
- Interactive HTML maps

Everything else works perfectly!

### Option 2: Install with Conda (Advanced)

If you really need spatial analysis:

1. **Install Miniconda** from https://docs.conda.io/en/latest/miniconda.html

2. **Create conda environment**:
```powershell
conda create -n heatstreet python=3.11
conda activate heatstreet
```

3. **Install GDAL via conda**:
```powershell
conda install -c conda-forge geopandas
```

4. **Install other dependencies**:
```powershell
pip install -r requirements.txt
```

### Option 3: Pre-built Wheels (Advanced)

Use pre-compiled GDAL wheels:

1. Download GDAL wheel from: https://www.lfd.uci.edu/~gohlke/pythonlibs/#gdal
2. Choose the right version for your Python (e.g., GDAL-3.4.3-cp311-cp311-win_amd64.whl for Python 3.11)
3. Install:
```powershell
pip install path\to\GDAL-3.4.3-cp311-cp311-win_amd64.whl
pip install -r requirements-spatial.txt
```

## Common Issues

### "GDAL API version must be specified"

This means GDAL isn't installed. Either:
- Skip spatial analysis (use base requirements.txt only)
- Install via conda (Option 2 above)

### "Cannot find vcvarsall.bat"

This means you're missing C++ build tools. Either:
- Skip spatial analysis
- Install Visual Studio Build Tools from: https://visualstudio.microsoft.com/downloads/

### Jupyter notebook kernel issues

```powershell
python -m ipykernel install --user --name=heatstreet
```

## What Works Without Spatial Analysis?

✅ **Everything except**:
- Heat network tier classification (Tier 1-5 assignment)
- Interactive HTML maps

You can still:
- ✅ Download and process EPC data
- ✅ Validate and clean data
- ✅ Analyze property characteristics
- ✅ Model all decarbonization scenarios
- ✅ Calculate costs, savings, payback periods
- ✅ Subsidy sensitivity analysis
- ✅ Generate charts and reports
- ✅ Export results to CSV/Excel

## Recommended Workflow for Windows

1. **Start with core features** (no spatial)
2. **Do your analysis** with the main modules
3. **Export property data** with coordinates to CSV
4. **Use QGIS** (free GIS software) for spatial analysis if needed
   - Download QGIS: https://qgis.org/
   - Import your CSV with coordinates
   - Do spatial overlays with heat network data

This gives you the best of both worlds without the installation headaches!

## Summary

| Feature | Base Install | With Spatial |
|---------|--------------|--------------|
| EPC data processing | ✅ | ✅ |
| Data validation | ✅ | ✅ |
| Archetype analysis | ✅ | ✅ |
| Scenario modeling | ✅ | ✅ |
| Cost-benefit analysis | ✅ | ✅ |
| Charts & reports | ✅ | ✅ |
| Heat network tiers | ❌ | ✅ |
| Interactive maps | ❌ | ✅ |
| **Installation difficulty** | **Easy** | **Hard** |

**Recommendation**: Start with base install, add spatial later if really needed!
