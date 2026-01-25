# EPC API Usage Guide

This guide explains how to use the EPC API downloader to automatically fetch data from the UK EPC Register.

## Setup

### 1. Get API Credentials

1. Visit [https://epc.opendatacommunities.org/](https://epc.opendatacommunities.org/)
2. Register for an account (free)
3. Your API credentials will be emailed to you:
   - Email address (username)
   - API key

### 2. Configure Credentials

**Option A: Using .env file (Recommended)**

```bash
# Copy the example file
cp .env.example .env

# Edit .env and add your credentials
# .env file will look like:
EPC_API_EMAIL=your.email@example.com
EPC_API_KEY=your_api_key_here
```

⚠️ **Important**: The `.env` file is already in `.gitignore` and will NOT be committed to git.

**Option B: Set environment variables**

Windows PowerShell:
```powershell
$env:EPC_API_EMAIL="your.email@example.com"
$env:EPC_API_KEY="your_api_key_here"
```

Linux/Mac:
```bash
export EPC_API_EMAIL="your.email@example.com"
export EPC_API_KEY="your_api_key_here"
```

## Usage

### Quick Start

Download all London EPC data for Edwardian terraced houses:

```python
from src.acquisition.epc_api_downloader import EPCAPIDownloader

# Initialize downloader (reads credentials from .env)
downloader = EPCAPIDownloader()

# Download all London boroughs (this will take a while!)
df = downloader.download_all_london_boroughs(
    property_types=['house'],
    from_year=2015
)

# Apply Edwardian filters
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
1. Download all London house EPCs from 2015 onwards
2. Apply Edwardian terraced filters
3. Save both raw and filtered data to `data/raw/`

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

### Property Type
- `house` - All house types (detached, semi-detached, terraced)

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
# Build custom query
query_params = {
    'local-authority': 'E09000007',  # Camden
    'property-type': 'house',
    'from-year': 2015,
    'size': 5000
}

# Make request
df, next_search_after = downloader._make_api_request(query_params)
```

## API Limits

- **Page size**: Maximum 5,000 records per request
- **Total results**: No limit (use pagination)
- **Rate limiting**: The API may have rate limits - the downloader includes automatic retry logic

## Data Output

Downloaded data is saved to:
- `data/raw/epc_london_raw.csv` - All downloaded data
- `data/raw/epc_london_raw.parquet` - Same data in Parquet format (faster)
- `data/raw/epc_london_filtered.csv` - Filtered for Edwardian terraced
- `data/raw/epc_london_filtered.parquet` - Filtered data in Parquet

## Troubleshooting

### "API credentials not found"

Make sure you have either:
- Created a `.env` file with your credentials, OR
- Set environment variables

### "HTTP Error 401: Unauthorized"

Your credentials are incorrect. Double-check:
- Email address
- API key (no spaces or extra characters)

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
1. Immediately revoke them at [https://epc.opendatacommunities.org/](https://epc.opendatacommunities.org/)
2. Request new credentials
3. Remove the commit from git history

## Example Session

Complete example downloading and analyzing Camden EPCs:

```python
from src.acquisition.epc_api_downloader import EPCAPIDownloader
import pandas as pd

# Initialize
downloader = EPCAPIDownloader()

# Download Camden data
print("Downloading Camden EPCs...")
df = downloader.download_borough_data('Camden', from_year=2015)
print(f"Downloaded: {len(df):,} records")

# Apply filters
print("\nApplying Edwardian filters...")
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

Full API documentation: [https://epc.opendatacommunities.org/docs/api/domestic](https://epc.opendatacommunities.org/docs/api/domestic)

## Support

If you encounter issues:
1. Check the API documentation
2. Verify your credentials
3. Check the log output for specific error messages
4. Open an issue on GitHub with the error details
