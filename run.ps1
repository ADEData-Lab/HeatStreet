# Heat Street EPC Analysis - Quick Launcher
# Single command to run complete analysis

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
        exit 1
    }
}

# Activate virtual environment
Write-Host "[OK] Activating virtual environment..." -ForegroundColor Green
& .\venv\Scripts\Activate.ps1

# Check if dependencies are installed
Write-Host "[OK] Checking dependencies..." -ForegroundColor Green
$pythonOutput = python -c "import questionary; import rich; print('OK')" 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] Installing missing dependencies..." -ForegroundColor Yellow
    pip install questionary rich --quiet
}

# Run the interactive analysis
Write-Host "[OK] Starting interactive analysis..." -ForegroundColor Green
Write-Host ""

python run_analysis.py

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "[OK] Analysis complete!" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "[X] Analysis failed. Check errors above." -ForegroundColor Red
}
