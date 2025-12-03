# Heat Street EPC Analysis - Conda Launcher (PowerShell)
# Automatically sets up Conda environment with spatial dependencies

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Heat Street EPC Analysis (Conda)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if conda is installed
$condaPath = Get-Command conda -ErrorAction SilentlyContinue

if (-not $condaPath) {
    Write-Host "[X] Conda not found!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please install Miniconda or Anaconda first:" -ForegroundColor Yellow
    Write-Host "  https://docs.conda.io/en/latest/miniconda.html" -ForegroundColor White
    Write-Host ""
    Write-Host "After installation:" -ForegroundColor Yellow
    Write-Host "  1. Restart this terminal" -ForegroundColor White
    Write-Host "  2. Run this script again" -ForegroundColor White
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "[OK] Conda found!" -ForegroundColor Green
Write-Host ""

# Check if environment exists
$envExists = conda env list | Select-String "heatstreet"

if (-not $envExists) {
    Write-Host "[!] Creating conda environment 'heatstreet'..." -ForegroundColor Yellow
    Write-Host "This will take a few minutes on first run..." -ForegroundColor Yellow
    Write-Host ""

    conda create -n heatstreet python=3.11 -y

    if ($LASTEXITCODE -ne 0) {
        Write-Host "[X] Failed to create conda environment" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }

    Write-Host ""
    Write-Host "[OK] Environment created!" -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "[OK] Environment 'heatstreet' already exists" -ForegroundColor Green
    Write-Host ""
}

# Activate environment
Write-Host "[OK] Activating conda environment..." -ForegroundColor Green
conda activate heatstreet

if ($LASTEXITCODE -ne 0) {
    Write-Host "[X] Failed to activate environment" -ForegroundColor Red
    Write-Host ""
    Write-Host "Try running this command manually:" -ForegroundColor Yellow
    Write-Host "  conda activate heatstreet" -ForegroundColor White
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

# Check if geopandas is installed
python -c "import geopandas" 2>$null

if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] Installing spatial dependencies (geopandas + GDAL)..." -ForegroundColor Yellow
    Write-Host "This may take 5-10 minutes on first run..." -ForegroundColor Yellow
    Write-Host ""

    conda install -c conda-forge geopandas -y

    if ($LASTEXITCODE -ne 0) {
        Write-Host "[X] Failed to install geopandas" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }

    Write-Host ""
    Write-Host "[OK] Spatial dependencies installed!" -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "[OK] Geopandas already installed" -ForegroundColor Green
    Write-Host ""
}

# Install core dependencies
Write-Host "[OK] Installing/updating core dependencies..." -ForegroundColor Green
Write-Host ""

pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] Some packages failed to install. Trying without quiet mode..." -ForegroundColor Yellow
    pip install -r requirements.txt
}

Write-Host ""
Write-Host "[OK] All dependencies ready!" -ForegroundColor Green
Write-Host ""

# Verify spatial dependencies
Write-Host "[OK] Verifying spatial analysis capabilities..." -ForegroundColor Green
python -c "import geopandas; from osgeo import gdal; print('[OK] GDAL version:', gdal.__version__); print('[OK] Geopandas version:', geopandas.__version__)"

if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] Spatial verification failed, but continuing..." -ForegroundColor Yellow
    Write-Host ""
}

Write-Host ""

# Run the analysis
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Starting Interactive Analysis" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

python run_analysis.py

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "[OK] Analysis complete!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Check data\outputs\ for results:" -ForegroundColor Cyan
    Write-Host "  - Figures: data\outputs\figures\" -ForegroundColor White
    Write-Host "  - Reports: data\outputs\reports\" -ForegroundColor White
    Write-Host "  - Excel: data\outputs\*.xlsx" -ForegroundColor White
    Write-Host "  - Maps: data\outputs\maps\ (spatial analysis)" -ForegroundColor White
    Write-Host "  - GeoJSON: data\outputs\properties_with_tiers.geojson" -ForegroundColor White
} else {
    Write-Host ""
    Write-Host "[X] Analysis failed. Check errors above." -ForegroundColor Red
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "To use this environment again:" -ForegroundColor Cyan
Write-Host "  conda activate heatstreet" -ForegroundColor White
Write-Host "  python run_analysis.py" -ForegroundColor White
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Read-Host "Press Enter to exit"
