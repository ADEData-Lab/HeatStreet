# Download EPC Data Using API
# Quick script to download London EPC data automatically

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "EPC API Data Downloader" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if virtual environment is activated
if (-not $env:VIRTUAL_ENV) {
    Write-Host "[!] Activating virtual environment..." -ForegroundColor Yellow
    if (Test-Path "venv\Scripts\Activate.ps1") {
        & .\venv\Scripts\Activate.ps1
    } else {
        Write-Host "[X] Virtual environment not found. Please run setup.ps1 first." -ForegroundColor Red
        exit 1
    }
}

# Check if .env file exists
if (-not (Test-Path ".env")) {
    Write-Host "[!] Creating .env file from .env.example..." -ForegroundColor Yellow
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host "[!] Please edit .env file and add your API credentials" -ForegroundColor Yellow
        Write-Host "    Get credentials from: https://epc.opendatacommunities.org/" -ForegroundColor Gray
        Write-Host ""
        Write-Host "Press any key after updating .env file..."
        $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
    }
}

# Show menu
Write-Host "Select download option:" -ForegroundColor Cyan
Write-Host "1. Download ALL London boroughs (will take several hours)" -ForegroundColor White
Write-Host "2. Download SINGLE borough (quick test)" -ForegroundColor White
Write-Host "3. Download with LIMIT (e.g., first 1000 records per borough)" -ForegroundColor White
Write-Host "4. Exit" -ForegroundColor White
Write-Host ""

$choice = Read-Host "Enter choice (1-4)"

switch ($choice) {
    "1" {
        Write-Host ""
        Write-Host "[OK] Starting full London download..." -ForegroundColor Green
        Write-Host "This will download ALL EPCs for ALL 33 London boroughs" -ForegroundColor Yellow
        Write-Host "Estimated time: 2-4 hours" -ForegroundColor Yellow
        Write-Host ""
        python src\acquisition\epc_api_downloader.py
    }
    "2" {
        Write-Host ""
        $borough = Read-Host "Enter borough name (e.g., Camden, Islington)"
        Write-Host ""
        Write-Host "[OK] Downloading $borough..." -ForegroundColor Green

        # Create temporary Python script
        $script = @"
from src.acquisition.epc_api_downloader import EPCAPIDownloader

downloader = EPCAPIDownloader()
df = downloader.download_borough_data('$borough', from_year=2015)
df_filtered = downloader.apply_edwardian_filters(df)
downloader.save_data(df_filtered, 'epc_${borough}_edwardian.csv')
print(f'\nDownloaded {len(df):,} records')
print(f'Filtered to {len(df_filtered):,} Edwardian terraced houses')
"@
        $script | Out-File -FilePath "temp_download.py" -Encoding UTF8
        python temp_download.py
        Remove-Item "temp_download.py"
    }
    "3" {
        Write-Host ""
        $limit = Read-Host "Enter maximum records per borough (e.g., 1000)"
        Write-Host ""
        Write-Host "[OK] Downloading with limit of $limit records per borough..." -ForegroundColor Green

        # Create temporary Python script
        $script = @"
from src.acquisition.epc_api_downloader import EPCAPIDownloader

downloader = EPCAPIDownloader()
df = downloader.download_all_london_boroughs(
    property_types=['house'],
    from_year=2015,
    max_results_per_borough=$limit
)
df_filtered = downloader.apply_edwardian_filters(df)
downloader.save_data(df_filtered, 'epc_london_edwardian_limited.csv')
print(f'\nDownloaded {len(df):,} total records')
print(f'Filtered to {len(df_filtered):,} Edwardian terraced houses')
"@
        $script | Out-File -FilePath "temp_download.py" -Encoding UTF8
        python temp_download.py
        Remove-Item "temp_download.py"
    }
    "4" {
        Write-Host "Exiting..." -ForegroundColor Yellow
        exit 0
    }
    default {
        Write-Host "[X] Invalid choice" -ForegroundColor Red
        exit 1
    }
}

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "[OK] Download Complete!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Data saved to: data\raw\" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Yellow
    Write-Host "1. Run validation: python main.py --phase clean" -ForegroundColor Gray
    Write-Host "2. Run analysis: python main.py --phase analyze" -ForegroundColor Gray
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "[X] Download failed. Check errors above." -ForegroundColor Red
    Write-Host ""
}
