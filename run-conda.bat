@echo off
REM Heat Street EPC Analysis - Conda Launcher
REM Automatically sets up Conda environment with spatial dependencies

echo ========================================
echo Heat Street EPC Analysis (Conda)
echo ========================================
echo.

REM Check if conda is installed
where conda >nul 2>nul
if errorlevel 1 (
    echo [X] Conda not found!
    echo.
    echo Please install Miniconda or Anaconda first:
    echo   https://docs.conda.io/en/latest/miniconda.html
    echo.
    echo After installation:
    echo   1. Restart this terminal
    echo   2. Run this script again
    echo.
    pause
    exit /b 1
)

echo [OK] Conda found!
echo.

REM Check if environment exists
conda env list | findstr /C:"heatstreet" >nul 2>nul
if errorlevel 1 (
    echo [!] Creating conda environment 'heatstreet'...
    echo This will take a few minutes on first run...
    echo.

    conda create -n heatstreet python=3.11 -y

    if errorlevel 1 (
        echo [X] Failed to create conda environment
        pause
        exit /b 1
    )

    echo.
    echo [OK] Environment created!
    echo.
) else (
    echo [OK] Environment 'heatstreet' already exists
    echo.
)

REM Activate environment
echo [OK] Activating conda environment...
call conda activate heatstreet

if errorlevel 1 (
    echo [X] Failed to activate environment
    echo.
    echo Try running this command manually:
    echo   conda activate heatstreet
    echo.
    pause
    exit /b 1
)

REM Check if geopandas is installed
python -c "import geopandas" >nul 2>nul
if errorlevel 1 (
    echo [!] Installing spatial dependencies (geopandas + GDAL)...
    echo This may take 5-10 minutes on first run...
    echo.

    conda install -c conda-forge geopandas -y

    if errorlevel 1 (
        echo [X] Failed to install geopandas
        pause
        exit /b 1
    )

    echo.
    echo [OK] Spatial dependencies installed!
    echo.
) else (
    echo [OK] Geopandas already installed
    echo.
)

REM Install core dependencies
echo [OK] Installing/updating core dependencies...
echo.

pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

if errorlevel 1 (
    echo [!] Some packages failed to install. Trying without quiet mode...
    pip install -r requirements.txt
)

echo.
echo [OK] All dependencies ready!
echo.

REM Verify spatial dependencies
echo [OK] Verifying spatial analysis capabilities...
python -c "import geopandas; from osgeo import gdal; print('[OK] GDAL version:', gdal.__version__); print('[OK] Geopandas version:', geopandas.__version__)"

if errorlevel 1 (
    echo [!] Spatial verification failed, but continuing...
    echo.
)

echo.

REM Run the analysis
echo ========================================
echo Starting Interactive Analysis
echo ========================================
echo.

python run_analysis.py

if %errorlevel% equ 0 (
    echo.
    echo [OK] Analysis complete!
    echo.
    echo Check data\outputs\ for results:
    echo   - Figures: data\outputs\figures\
    echo   - Reports: data\outputs\reports\
    echo   - Excel: data\outputs\*.xlsx
    echo   - Maps: data\outputs\maps\ (spatial analysis)
    echo   - GeoJSON: data\outputs\properties_with_tiers.geojson
) else (
    echo.
    echo [X] Analysis failed. Check errors above.
)

echo.
echo ========================================
echo To use this environment again:
echo   conda activate heatstreet
echo   python run_analysis.py
echo ========================================
echo.
pause
