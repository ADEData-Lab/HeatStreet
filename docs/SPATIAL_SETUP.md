# Setting Up Spatial Analysis (GDAL/Geopandas) on Windows

The spatial analysis features require **GDAL** (Geospatial Data Abstraction Library) and **geopandas**, which can be challenging to install on Windows. This guide provides multiple methods from easiest to most comprehensive.

## ⚠️ Important Note

**The core analysis works perfectly WITHOUT spatial dependencies!**

If you run into issues, you can:
- Use the analysis for EPC data, scenarios, and reports (85% of functionality)
- Skip the heat network tier classification
- Come back to spatial analysis later

## 🎯 **Recommended: Conda Method** (Easiest, Most Reliable)

This is the **strongly recommended** approach for Windows users.

### Step 1: Install Miniconda (if you don't have it)

1. Download Miniconda for Windows:
   https://docs.conda.io/en/latest/miniconda.html

2. Install Miniconda (use default settings)

3. Open "Anaconda Prompt" from Start Menu

### Step 2: Create a Conda Environment

```bash
# Create new environment with Python 3.11
conda create -n heatstreet python=3.11 -y

# Activate the environment
conda activate heatstreet
```

### Step 3: Install Geopandas (includes GDAL)

```bash
# Install geopandas from conda-forge (this installs GDAL automatically)
conda install -c conda-forge geopandas -y
```

This single command installs:
- GDAL (with all dependencies)
- geopandas
- shapely
- fiona
- pyproj
- rtree

### Step 4: Install Other Project Dependencies

```bash
# Navigate to your project directory
cd "path\to\HeatStreet"

# Install core requirements
pip install -r requirements.txt

# Install remaining spatial dependencies
pip install folium>=0.14.0
```

### Step 5: Test Installation

```bash
python -c "import geopandas; print('✓ Geopandas installed successfully!')"
python -c "from osgeo import gdal; print('✓ GDAL installed successfully!')"
```

### Step 6: Run Analysis

```bash
# From the Anaconda Prompt (with heatstreet environment activated)
python run_analysis.py
```

## 🔧 **Alternative: Pre-built Wheels Method**

If you prefer to stick with standard Python (not Conda):

### Step 1: Install Pre-built Wheels

Visit: https://www.lfd.uci.edu/~gohlke/pythonlibs/

Download these files (match your Python version and architecture):
1. `GDAL‑3.4.3‑cp311‑cp311‑win_amd64.whl`
2. `Fiona‑1.9.2‑cp311‑cp311‑win_amd64.whl`
3. `Shapely‑2.0.1‑cp311‑cp311‑win_amd64.whl`

### Step 2: Install in Order

```powershell
# Install GDAL first
pip install "path\to\GDAL‑3.4.3‑cp311‑cp311‑win_amd64.whl"

# Then Fiona
pip install "path\to\Fiona‑1.9.2‑cp311‑cp311‑win_amd64.whl"

# Then Shapely
pip install "path\to\Shapely‑2.0.1‑cp311‑cp311‑win_amd64.whl"

# Finally geopandas
pip install geopandas
```

### Step 3: Install Remaining Dependencies

```powershell
pip install -r requirements-spatial.txt
```

## 🐧 **Linux Method** (Simple)

On Linux, spatial dependencies install easily:

```bash
# Ubuntu/Debian
sudo apt-get install gdal-bin libgdal-dev

# Install Python packages
pip install -r requirements-spatial.txt
```

## 🍎 **Mac Method**

```bash
# Install GDAL via Homebrew
brew install gdal

# Install Python packages
pip install -r requirements-spatial.txt
```

## ✅ **Verifying Your Installation**

Run this test script to check everything:

```python
python -c """
import sys

print('Testing spatial dependencies...')
print('-' * 60)

# Test GDAL
try:
    from osgeo import gdal
    print('✓ GDAL:', gdal.__version__)
except ImportError as e:
    print('✗ GDAL not installed')
    print('  Error:', e)
    sys.exit(1)

# Test geopandas
try:
    import geopandas as gpd
    print('✓ Geopandas:', gpd.__version__)
except ImportError:
    print('✗ Geopandas not installed')
    sys.exit(1)

# Test shapely
try:
    import shapely
    print('✓ Shapely:', shapely.__version__)
except ImportError:
    print('✗ Shapely not installed')
    sys.exit(1)

# Test fiona
try:
    import fiona
    print('✓ Fiona:', fiona.__version__)
except ImportError:
    print('✗ Fiona not installed')
    sys.exit(1)

# Test folium (for maps)
try:
    import folium
    print('✓ Folium:', folium.__version__)
except ImportError:
    print('⚠ Folium not installed (optional, for interactive maps)')

print('-' * 60)
print('✓ All spatial dependencies installed successfully!')
print('')
print('You can now run the full spatial analysis:')
print('  python run_analysis.py')
"""
```

## 🚀 **What Spatial Analysis Does**

Once GDAL is installed, you'll get these additional features:

### Data sources used for tiering (evidence layers)
- **HNPD (DESNZ/BEIS Heat Network Planning Database, Jan 2024)**: the primary source of up-to-date heat network scheme locations (downloaded automatically to `data/external/hnpd-january-2024.csv`).
- **London Heat Map GIS package (legacy)**: optional/fallback; provides zone / “potential network” geometries used by the Tier 2 overlay (downloaded as `data/external/GIS_All_Data.zip`).
- **EPC-derived demand**: used to compute local heat density (GWh/km²) for Tier 3–5.

### Heat Network Tier Classification
- **Tier 1**: Properties within 250m of existing heat networks
- **Tier 2**: Properties within planned Heat Network Zones
- **Tier 3**: High heat density areas (≥20 GWh/km²; configurable in `config/config.yaml`)
- **Tier 4**: Moderate heat density areas (5-20 GWh/km²)
- **Tier 5**: Low heat density areas (<5 GWh/km²)

### Outputs
1. **GeoJSON file** with all properties + tier classifications
2. **CSV summary** of pathway suitability by tier
3. **Interactive HTML map** showing tier distribution
4. **Heat density values** (GWh/km²) per property

### Analysis Features
- Geocoding from EPC coordinates
- Distance calculations to heat networks
- Spatial aggregation of heat demand
- Grid-based density calculation
- Pathway suitability recommendations

## ❓ **Troubleshooting**

### "ImportError: DLL load failed"
- **Cause**: GDAL dependencies not found
- **Solution**: Use Conda method (installs all dependencies automatically)

### "ModuleNotFoundError: No module named 'osgeo'"
- **Cause**: GDAL not installed
- **Solution**: Install GDAL before other spatial packages

### "GDAL version mismatch"
- **Cause**: Conflicting GDAL versions
- **Solution**:
  ```bash
  pip uninstall gdal fiona shapely geopandas -y
  # Then reinstall using Conda method
  ```

### "Unable to find GDAL library"
- **Cause**: GDAL not in system PATH
- **Solution**: Use Conda (sets PATH automatically)

### Still Having Issues?

**Option 1**: Skip spatial analysis
- Run: `python run_analysis.py`
- When prompted about spatial dependencies, it will skip gracefully
- You still get 85% of functionality!

**Option 2**: Use Windows Subsystem for Linux (WSL)
```bash
# In WSL
sudo apt-get install gdal-bin libgdal-dev
pip install -r requirements-spatial.txt
```

**Option 3**: Use Docker
```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y gdal-bin libgdal-dev
# ... rest of Dockerfile
```

## 📊 **Running Without Spatial Analysis**

If you choose not to install GDAL, the analysis will:

✅ Still work perfectly for:
- EPC data download and validation
- Archetype characterization
- Scenario modeling (all 5 pathways)
- Subsidy sensitivity analysis
- Visualization (charts + Excel)
- Executive summary reports

⚠️ Won't include:
- Heat network tier classification
- Heat density maps
- Spatial pathway recommendations
- Distance-to-network calculations

The pipeline automatically detects whether GDAL is available and adjusts accordingly!

## 🎓 **Understanding the Environment**

### With Conda (Recommended)
Your environment is isolated:
- `conda activate heatstreet` - activates environment
- `conda deactivate` - deactivates
- Packages don't interfere with your main Python

### Without Conda (Regular pip)
Packages install system-wide:
- Can cause conflicts with other projects
- Harder to troubleshoot GDAL issues
- But works if you get it right!

## 📚 **Additional Resources**

- [Geopandas Windows Installation Guide](https://geopandas.org/en/stable/getting_started/install.html#windows)
- [GDAL Windows Binaries](https://www.gisinternals.com/release.php)
- [Conda Documentation](https://docs.conda.io/projects/conda/en/latest/user-guide/tasks/manage-environments.html)

## ✨ **Success Checklist**

- [ ] Conda installed (if using Conda method)
- [ ] Environment activated: `conda activate heatstreet`
- [ ] Geopandas installed: `conda install -c conda-forge geopandas`
- [ ] Test passes: `python -c "import geopandas"`
- [ ] Core requirements: `pip install -r requirements.txt`
- [ ] Analysis runs: `python run_analysis.py` (or `run-conda.bat` / `.\run-conda.ps1` on Windows)
- [ ] Spatial phase completes successfully
- [ ] Map generated: `data/outputs/maps/heat_network_tiers.html`

---

**TL;DR**: Use Conda! It handles all the complexity automatically.

```bash
conda create -n heatstreet python=3.11 -y
conda activate heatstreet
conda install -c conda-forge geopandas -y
pip install -r requirements.txt
python run_analysis.py
```

Done! 🎉
