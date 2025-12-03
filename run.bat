@echo off
REM Heat Street EPC Analysis - Complete Launcher
REM Automatically installs all dependencies and runs analysis

echo ========================================
echo Heat Street EPC Analysis
echo ========================================
echo.

REM Check if virtual environment exists
if not exist "venv" (
    echo [!] Virtual environment not found. Running setup...
    echo.
    call setup.bat
    if errorlevel 1 (
        echo [X] Setup failed. Please run setup.bat manually.
        pause
        exit /b 1
    )
)

REM Activate virtual environment
echo [OK] Activating virtual environment...
call venv\Scripts\activate.bat

REM Install/upgrade all core dependencies
echo [OK] Checking and installing dependencies...
echo.
echo This may take a few minutes on first run...
echo.

REM Install core requirements
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

if errorlevel 1 (
    echo [!] Some packages failed to install. Trying without quiet mode...
    pip install -r requirements.txt
)

echo.
echo [OK] All core dependencies installed!
echo.

REM Check if user wants spatial analysis (optional)
echo ========================================
echo Optional: Spatial Analysis Setup
echo ========================================
echo.
echo Spatial analysis requires GDAL/geopandas (for heat network tiers).
echo This can be tricky to install on Windows.
echo.
echo Recommended: Use Conda (see docs\SPATIAL_SETUP.md)
echo Alternative: Try installing now (may fail on some systems)
echo.

choice /C YNS /M "Install spatial dependencies? (Y=Yes, N=Skip, S=Show guide)"

if errorlevel 3 (
    echo.
    echo Opening setup guide...
    start docs\SPATIAL_SETUP.md
    pause
    goto :skip_spatial
)

if errorlevel 2 goto :skip_spatial

echo.
echo [!] Attempting to install spatial dependencies...
echo [!] This may fail - if it does, use Conda method instead!
echo.

pip install -r requirements-spatial.txt

if errorlevel 1 (
    echo.
    echo [X] Spatial dependencies failed to install.
    echo [!] This is normal on Windows! The analysis will work without them.
    echo.
    echo For spatial analysis, use Conda:
    echo   conda install -c conda-forge geopandas
    echo.
    echo See docs\SPATIAL_SETUP.md for full guide.
    echo.
    pause
) else (
    echo.
    echo [OK] Spatial dependencies installed successfully!
    echo.
)

:skip_spatial

REM Run the interactive analysis
echo.
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
    echo   - Maps: data\outputs\maps\ (if spatial analysis ran)
) else (
    echo.
    echo [X] Analysis failed. Check errors above.
)

echo.
pause
