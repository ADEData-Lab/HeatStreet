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

Download EPC data for configured local authorities:

```python
from src.acquisition.epc_api_downloader import EPCAPIDownloader

# Initialize downloader (reads credentials from .env)
downloader = EPCAPIDownloader()

# Download all configured local authorities (this will take a while!)
df = downloader.download_all_local_authorities(
    property_types=['house', 'flat'],
    from_year=2015
)

# Apply configured property filters
df_filtered = downloader.apply_property_filters(df)

# Save results
downloader.save_data(df_filtered, "epc_england_wales_filtered.csv")
```

### Download a Single Local Authority

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
# Download only first 1000 records per local authority
df = downloader.download_all_local_authorities(
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
1. Download all configured local authority EPCs from 2015 onwards
2. Apply configured property filters
3. Save both raw and filtered data to `data/raw/`

## Configuring Local Authorities

To analyze England and Wales, populate `config/config.yaml` with local authority codes:

```yaml
geography:
  local_authority_codes:
    Camden: "E09000007"
    Islington: "E09000019"
    Cardiff: "W06000015"
```

If no codes are provided, the downloader defaults to London boroughs and logs a warning.

## Filters Applied

### Property Type
- Configurable via `property_filters.property_types`

### Construction Age Bands
- Configurable via `property_filters.construction_age_bands`

### Built Form
- Configurable via `property_filters.built_forms`

## Advanced Usage

### Custom Filters

```python
# Download multiple property types
df = downloader.download_all_local_authorities(
    property_types=['house', 'bungalow', 'flat'],
    from_year=2010
)

# Download specific local authorities only
target_authorities = ['Camden', 'Islington', 'Hackney']

all_data = []
for authority in target_authorities:
    df = downloader.download_borough_data(authority)
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
- `data/raw/epc_england_wales_raw.csv` - All downloaded data
- `data/raw/epc_england_wales_raw.parquet` - Same data in Parquet format (faster)
- `data/raw/epc_england_wales_filtered.csv` - Filtered based on config
- `data/raw/epc_england_wales_filtered.parquet` - Filtered data in Parquet

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

This is normal! Downloading all England and Wales EPCs can take several hours due to:
- Large number of records (~500k+)
- API pagination (5000 records per page)
- Network latency

Tips:
- Start with a single local authority for testing
- Use `max_results_per_borough` to limit results
- Download runs in background - you can continue working

## Integration with Main Pipeline

The API downloader integrates with the main pipeline:

```bash
# Option 1: Use API downloader
python src/acquisition/epc_api_downloader.py

# Then continue with the pipeline
python main.py --phase clean
python main.py --phase analyze
```

Or integrate directly:

```python
from src.acquisition.epc_api_downloader import EPCAPIDownloader

# Download data via API
downloader = EPCAPIDownloader()
df = downloader.download_all_local_authorities()

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
print("\nApplying configured property filters...")
df_filtered = downloader.apply_property_filters(df)
print(f"After filtering: {len(df_filtered):,} records")

# Check what we got
print("\nEPC Band Distribution:")
print(df_filtered['CURRENT_ENERGY_RATING'].value_counts())

print("\nConstruction Age Bands:")
print(df_filtered['CONSTRUCTION_AGE_BAND'].value_counts())

# Save
downloader.save_data(df_filtered, "camden_filtered.csv")
print("\nData saved to data/raw/camden_filtered.csv")
```

## API Documentation

Full API documentation: [https://epc.opendatacommunities.org/docs/api/domestic](https://epc.opendatacommunities.org/docs/api/domestic)

## Support

If you encounter issues:
1. Check the API documentation
2. Verify your credentials
3. Check the log output for specific error messages
4. Open an issue on GitHub with the error details
