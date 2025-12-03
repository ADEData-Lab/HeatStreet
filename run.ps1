# Heat Street EPC Analysis - Complete Launcher
# Automatically installs all dependencies and runs analysis

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Heat Street EPC Analysis" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if virtual environment exists
if (-not (Test-Path "venv")) {
    Write-Host "[!] Virtual environment not found. Running setup..." -ForegroundColor Yellow
    Write-Host ""
    & .\setup.ps1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[X] Setup failed. Please run setup.ps1 manually." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
}

# Activate virtual environment
Write-Host "[OK] Activating virtual environment..." -ForegroundColor Green
& .\venv\Scripts\Activate.ps1

# Install/upgrade all core dependencies
Write-Host "[OK] Checking and installing dependencies..." -ForegroundColor Green
Write-Host ""
Write-Host "This may take a few minutes on first run..." -ForegroundColor Yellow
Write-Host ""

# Install core requirements
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] Some packages failed to install. Trying without quiet mode..." -ForegroundColor Yellow
    pip install -r requirements.txt
}

Write-Host ""
Write-Host "[OK] All core dependencies installed!" -ForegroundColor Green
Write-Host ""

# Check if user wants spatial analysis (optional)
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Optional: Spatial Analysis Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Spatial analysis requires GDAL/geopandas (for heat network tiers)."
Write-Host "This can be tricky to install on Windows."
Write-Host ""
Write-Host "Recommended: Use Conda (see docs\SPATIAL_SETUP.md)"
Write-Host "Alternative: Try installing now (may fail on some systems)"
Write-Host ""

$choice = Read-Host "Install spatial dependencies? (Y=Yes, N=Skip, S=Show guide)"

if ($choice -eq 'S' -or $choice -eq 's') {
    Write-Host ""
    Write-Host "Opening setup guide..." -ForegroundColor Cyan
    Start-Process "docs\SPATIAL_SETUP.md"
    Read-Host "Press Enter to continue without spatial dependencies"
    $choice = 'N'
}

if ($choice -eq 'Y' -or $choice -eq 'y') {
    Write-Host ""
    Write-Host "[!] Attempting to install spatial dependencies..." -ForegroundColor Yellow
    Write-Host "[!] This may fail - if it does, use Conda method instead!" -ForegroundColor Yellow
    Write-Host ""

    pip install -r requirements-spatial.txt

    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "[X] Spatial dependencies failed to install." -ForegroundColor Red
        Write-Host "[!] This is normal on Windows! The analysis will work without them." -ForegroundColor Yellow
        Write-Host ""
        Write-Host "For spatial analysis, use Conda:" -ForegroundColor Cyan
        Write-Host "  conda install -c conda-forge geopandas" -ForegroundColor White
        Write-Host ""
        Write-Host "See docs\SPATIAL_SETUP.md for full guide." -ForegroundColor Cyan
        Write-Host ""
        Read-Host "Press Enter to continue"
    } else {
        Write-Host ""
        Write-Host "[OK] Spatial dependencies installed successfully!" -ForegroundColor Green
        Write-Host ""
    }
}

# Run the interactive analysis
Write-Host ""
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
    Write-Host "  - Maps: data\outputs\maps\ (if spatial analysis ran)" -ForegroundColor White
} else {
    Write-Host ""
    Write-Host "[X] Analysis failed. Check errors above." -ForegroundColor Red
}

Write-Host ""
Read-Host "Press Enter to exit"
