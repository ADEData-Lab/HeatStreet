# Download DESNZ heat network planning data
#
# Downloads heat network planning data for use with the Heat Street EPC
# analysis spatial features.

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "DESNZ Heat Network Data Downloader" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if virtual environment exists
if (-not (Test-Path "venv")) {
    Write-Host "[!] Virtual environment not found. Please run setup.ps1 first." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

# Activate virtual environment
Write-Host "[OK] Activating virtual environment..." -ForegroundColor Green
& .\venv\Scripts\Activate.ps1

# Run the GIS downloader
Write-Host ""
Write-Host "Starting GIS data download..." -ForegroundColor Cyan
Write-Host ""

python -c "
from src.acquisition.desnz_heat_network_downloader import DESNZHeatNetworkDownloader

downloader = DESNZHeatNetworkDownloader()

print('Downloading DESNZ heat network planning data...')
print('This includes:')
print('  - Existing heat networks')
print('  - Heat network zones')
print()

success = downloader.download_and_prepare()

if success:
    print()
    print('=' * 60)
    print('GIS DATA DOWNLOAD COMPLETE')
    print('=' * 60)

    summary = downloader.get_data_summary()
    print()
    print(f'Network files: {summary[\"network_files\"]}')
    print()
    print(f'Data location: {summary[\"data_path\"]}')
    print()
    print('The GIS data is now ready for use in spatial analysis!')
else:
    print()
    print('GIS data download failed. Please check the error messages above.')
"

Write-Host ""
Write-Host "[OK] Complete!" -ForegroundColor Green
Write-Host ""
Read-Host "Press Enter to exit"
