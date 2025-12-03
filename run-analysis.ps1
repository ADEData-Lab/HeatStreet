# Heat Street EPC Analysis - Run Analysis Script
# Quick script to run the full analysis pipeline

param(
    [Parameter(Mandatory=$false)]
    [ValidateSet('all', 'acquire', 'clean', 'analyze', 'model', 'spatial', 'report')]
    [string]$Phase = 'all',

    [Parameter(Mandatory=$false)]
    [switch]$Download
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Heat Street EPC Analysis" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if virtual environment is activated
if (-not $env:VIRTUAL_ENV) {
    Write-Host "⚠ Virtual environment not activated" -ForegroundColor Yellow
    Write-Host "Activating virtual environment..." -ForegroundColor Yellow

    if (Test-Path "venv\Scripts\Activate.ps1") {
        & .\venv\Scripts\Activate.ps1
        Write-Host "✓ Virtual environment activated" -ForegroundColor Green
    } else {
        Write-Host "✗ Virtual environment not found" -ForegroundColor Red
        Write-Host "Please run setup.ps1 first" -ForegroundColor Yellow
        exit 1
    }
}

# Build command
$command = "python main.py --phase $Phase"

if ($Download) {
    $command += " --download"
}

Write-Host "Running: $command" -ForegroundColor Cyan
Write-Host ""

# Run the analysis
Invoke-Expression $command

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "✓ Analysis Complete!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "View results in:" -ForegroundColor Cyan
    Write-Host "  data\outputs\figures\" -ForegroundColor White
    Write-Host "  data\outputs\reports\" -ForegroundColor White
    Write-Host "  data\outputs\maps\" -ForegroundColor White
    Write-Host ""
    Write-Host "Open output folder:" -ForegroundColor Yellow
    Write-Host "  explorer data\outputs" -ForegroundColor Gray
} else {
    Write-Host ""
    Write-Host "✗ Analysis failed" -ForegroundColor Red
    Write-Host "Check the log for errors" -ForegroundColor Yellow
    exit 1
}
