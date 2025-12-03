# Heat Street EPC Analysis - Windows Setup Script
# Run this in PowerShell to set up the project

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Heat Street EPC Analysis - Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check Python version
Write-Host "Checking Python installation..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "[OK] Found: $pythonVersion" -ForegroundColor Green

    # Extract version number
    if ($pythonVersion -match "Python (\d+)\.(\d+)") {
        $major = [int]$matches[1]
        $minor = [int]$matches[2]

        if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 9)) {
            Write-Host "[X] Python 3.9 or higher is required" -ForegroundColor Red
            Write-Host "    Please install from: https://www.python.org/downloads/" -ForegroundColor Yellow
            exit 1
        }
    }
} catch {
    Write-Host "[X] Python not found" -ForegroundColor Red
    Write-Host "    Please install Python 3.9+ from: https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}

# Check if virtual environment already exists
if (Test-Path "venv") {
    Write-Host "[OK] Virtual environment already exists" -ForegroundColor Green
} else {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    python -m venv venv
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Virtual environment created" -ForegroundColor Green
    } else {
        Write-Host "[X] Failed to create virtual environment" -ForegroundColor Red
        exit 1
    }
}

# Check execution policy
Write-Host ""
Write-Host "Checking PowerShell execution policy..." -ForegroundColor Yellow
$policy = Get-ExecutionPolicy -Scope CurrentUser

if ($policy -eq "Restricted" -or $policy -eq "Undefined") {
    Write-Host "[!] Execution policy needs to be updated" -ForegroundColor Yellow
    Write-Host "    Setting execution policy to RemoteSigned for current user..." -ForegroundColor Yellow

    try {
        Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
        Write-Host "[OK] Execution policy updated" -ForegroundColor Green
    } catch {
        Write-Host "[X] Failed to update execution policy" -ForegroundColor Red
        Write-Host "    Please run PowerShell as Administrator and try again" -ForegroundColor Yellow
        exit 1
    }
} else {
    Write-Host "[OK] Execution policy is compatible: $policy" -ForegroundColor Green
}

# Activate virtual environment
Write-Host ""
Write-Host "Activating virtual environment..." -ForegroundColor Yellow
try {
    & .\venv\Scripts\Activate.ps1
    Write-Host "[OK] Virtual environment activated" -ForegroundColor Green
} catch {
    Write-Host "[X] Failed to activate virtual environment" -ForegroundColor Red
    Write-Host "    Try running: .\venv\Scripts\Activate.ps1" -ForegroundColor Yellow
    exit 1
}

# Upgrade pip
Write-Host ""
Write-Host "Upgrading pip..." -ForegroundColor Yellow
python -m pip install --upgrade pip --quiet
Write-Host "[OK] pip upgraded" -ForegroundColor Green

# Install dependencies
Write-Host ""
Write-Host "Installing dependencies (this may take a few minutes)..." -ForegroundColor Yellow
pip install -r requirements.txt --quiet

if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Dependencies installed" -ForegroundColor Green
} else {
    Write-Host "[X] Failed to install dependencies" -ForegroundColor Red
    Write-Host "    Try running manually: pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}

# Verify installation
Write-Host ""
Write-Host "Verifying installation..." -ForegroundColor Yellow
$verification = python -c "from config.config import load_config; print('OK')" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Installation verified" -ForegroundColor Green
    Write-Host "[OK] All checks passed!" -ForegroundColor Green
} else {
    Write-Host "[X] Verification failed" -ForegroundColor Red
    Write-Host $verification
    exit 1
}

# Create data directories
Write-Host ""
Write-Host "Ensuring data directories exist..." -ForegroundColor Yellow
$directories = @("data\raw", "data\processed", "data\supplementary", "data\outputs\figures", "data\outputs\reports", "data\outputs\maps")
foreach ($dir in $directories) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
}
Write-Host "[OK] Directory structure verified" -ForegroundColor Green

# Success message
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "[OK] Setup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. Download EPC data:" -ForegroundColor White
Write-Host "   python main.py --phase acquire --download" -ForegroundColor Gray
Write-Host ""
Write-Host "2. Place EPC CSV files in: data\raw\" -ForegroundColor White
Write-Host ""
Write-Host "3. Run the analysis pipeline:" -ForegroundColor White
Write-Host "   python main.py --phase all" -ForegroundColor Gray
Write-Host ""
Write-Host "For help, see: docs\QUICKSTART_WINDOWS.md" -ForegroundColor Yellow
Write-Host ""
