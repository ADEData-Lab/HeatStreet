# EPC API Usage Guide

This guide explains how to use the EPC API downloader to automatically fetch data from the Energy Certificate Data API.

## Setup

### 1. Get API Credentials

1. Visit [https://get-energy-performance-data.communities.gov.uk/](https://get-energy-performance-data.communities.gov.uk/)
2. Sign in or create a GOV.UK One Login account
3. Copy your bearer token from your my account page

### 2. Configure Credentials

**Option A: Using .env file (Recommended)**

```bash
# Copy the example file
cp .env.example .env

# Edit .env and add your bearer token
# .env file will look like:
EPC_API_TOKEN=your_bearer_token_here
```

⚠️ **Important**: The `.env` file is already in `.gitignore` and will NOT be committed to git.

**Option B: Set environment variables**

Windows PowerShell:
```powershell
$env:EPC_API_TOKEN="your_bearer_token_here"
```

Linux/Mac:
```bash
export EPC_API_TOKEN="your_bearer_token_here"
```

## Usage

### Quick Start

Download all London house EPC data and derive the London pre-1930 terraced subset:

```python
from src.acquisition.epc_api_downloader import EPCAPIDownloader

# Initialize downloader with the full-load source of truth for stock definition
downloader = EPCAPIDownloader(download_mode="full_load")

# Download all London house records (this will take a while!)
df = downloader.download_all_london_boroughs(
    property_types=['house'],
    from_year=2015
)

# Apply the London pre-1930 terraced-house stock definition
df_filtered = downloader.apply_edwardian_filters(df)

# Save results
downloader.save_data(df_filtered, "epc_london_edwardian.csv")
```

### Download a Single Borough

```python
from src.acquisition.epc_api_downloader import EPCAPIDownloader

downloader = EPCAPIDownloader()

# Download just Camden
df = downloader.download_borough_data(
    borough_name='Camden',
    property_type='house',
    from_year=2015
)

print(f"Downloaded {len(df):,} records for Camden")
```

### Limit Results for Testing

```python
# Download only first 1000 records per borough
df = downloader.download_all_london_boroughs(
    property_types=['house'],
    from_year=2015,
    max_results_per_borough=1000
)
```

### Command Line Usage

Run the downloader directly:

```bash
# Activate virtual environment first
python src/acquisition/epc_api_downloader.py
```

This will:
1. Download all London house EPCs from the full-load extract
2. Apply the London pre-1930 terraced-house stock definition
3. Save both raw London house records and the filtered London pre-1930 terraced subset to `data/raw/`

## Available London Boroughs

The downloader automatically handles all 33 London boroughs:

- Barking and Dagenham
- Barnet
- Bexley
- Brent
- Bromley
- Camden
- City of London
- Croydon
- Ealing
- Enfield
- Greenwich
- Hackney
- Hammersmith and Fulham
- Haringey
- Harrow
- Havering
- Hillingdon
- Hounslow
- Islington
- Kensington and Chelsea
- Kingston upon Thames
- Lambeth
- Lewisham
- Merton
- Newham
- Redbridge
- Richmond upon Thames
- Southwark
- Sutton
- Tower Hamlets
- Waltham Forest
- Wandsworth
- Westminster

## Filters Applied

`apply_edwardian_filters()` requires these EPC columns to be present:
- `PROPERTY_TYPE`
- `BUILT_FORM`
- `CONSTRUCTION_AGE_BAND`

Use `download_mode="full_load"` for any workflow that needs the stock-definition filter. The search API can be useful for quick connectivity tests, but it does not reliably expose the full stock-definition schema.

### Property Type
- `house` - House records only

### Construction Period (Edwardian)
- Before 1900
- 1900-1929
- 1900-1920
- 1920-1929

### Built Form (Terraced)
- Mid-Terrace
- End-Terrace
- Enclosed Mid-Terrace
- Enclosed End-Terrace

## Advanced Usage

### Custom Filters

```python
# Download multiple property types
df = downloader.download_all_london_boroughs(
    property_types=['house', 'bungalow'],
    from_year=2010
)

# Download specific boroughs only
target_boroughs = ['Camden', 'Islington', 'Hackney']

all_data = []
for borough in target_boroughs:
    df = downloader.download_borough_data(borough)
    all_data.append(df)

combined = pd.concat(all_data, ignore_index=True)
```

### Access Raw API

```python
# Use the shared request helper if you need custom API access
params = {
    "council[]": ["Camden"],
    "date_start": "2015-01-01",
    "date_end": "2015-12-31",
    "current_page": 1,
    "page_size": 5000,
}

payload = downloader._request_json(downloader.SEARCH_URL, params)
records = payload.get("data", [])
```

## API Limits

- **Page size**: Maximum 5,000 records per request
- **Total results**: No limit for search requests, subject to pagination
- **Rate limiting**: The API limits applications to 6000 requests per 5 minutes; the downloader includes retry logic for 429 responses

## Data Output

Downloaded data is saved to:
- `data/raw/epc_london_raw.csv` - Raw London house records from the EPC full-load extract
- `data/raw/epc_london_raw.parquet` - Same data in Parquet format (faster)
- `data/raw/epc_london_filtered.csv` - London pre-1930 terraced house subset
- `data/raw/epc_london_filtered.parquet` - London pre-1930 terraced house subset in Parquet

## Troubleshooting

### "API token not found"

Make sure you have either:
- Created a `.env` file with your bearer token, OR
- Set environment variables

### "HTTP Error 401: Unauthorized"

Your bearer token is incorrect, expired, or copied incorrectly.

### "HTTP Error 429: Too Many Requests"

You've hit the API rate limit. The downloader will automatically wait and retry.

### Download is slow

This is normal! Downloading all London EPCs can take several hours due to:
- Large number of records (~500k+)
- API pagination (5000 records per page)
- Network latency

Tips:
- Start with a single borough for testing
- Use `max_results_per_borough` to limit results
- Download runs in background - you can continue working

## Integration with Main Pipeline

The API downloader integrates with the main pipeline:

```bash
# Option 1: Use API downloader
python src/acquisition/epc_api_downloader.py

# Then continue with the pipeline
python run_analysis.py
```

Or integrate directly:

```python
from src.acquisition.epc_api_downloader import EPCAPIDownloader

# Download data via API
downloader = EPCAPIDownloader()
df = downloader.download_all_london_boroughs()

# Continue with analysis
from src.cleaning.data_validator import EPCDataValidator
validator = EPCDataValidator()
df_validated, report = validator.validate_dataset(df)
```

## Security Notes

⚠️ **NEVER commit your .env file or API credentials to git!**

The `.env` file is already in `.gitignore` to prevent accidental commits.

If you accidentally commit credentials:
1. Immediately revoke them at [https://get-energy-performance-data.communities.gov.uk/](https://get-energy-performance-data.communities.gov.uk/)
2. Request new credentials
3. Remove the commit from git history

## Example Session

Complete example downloading and analyzing Camden EPCs:

```python
from src.acquisition.epc_api_downloader import EPCAPIDownloader
import pandas as pd

# Initialize
downloader = EPCAPIDownloader(download_mode="full_load")

# Download Camden house data from the full-load extract
print("Downloading Camden EPCs...")
df = downloader.download_borough_data('Camden', from_year=2015)
print(f"Downloaded: {len(df):,} records")

# Apply filters
print("\nApplying London pre-1930 terraced-house filters...")
df_filtered = downloader.apply_edwardian_filters(df)
print(f"After filtering: {len(df_filtered):,} records")

# Check what we got
print("\nEPC Band Distribution:")
print(df_filtered['CURRENT_ENERGY_RATING'].value_counts())

print("\nConstruction Age Bands:")
print(df_filtered['CONSTRUCTION_AGE_BAND'].value_counts())

# Save
downloader.save_data(df_filtered, "camden_edwardian.csv")
print("\nData saved to data/raw/camden_edwardian.csv")
```

## API Documentation

Full API documentation: [https://get-energy-performance-data.communities.gov.uk/api-technical-documentation](https://get-energy-performance-data.communities.gov.uk/api-technical-documentation)

## Support

If you encounter issues:
1. Check the API documentation
2. Verify your credentials
3. Check the log output for specific error messages
4. Open an issue on GitHub with the error details
