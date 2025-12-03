# Interactive Analysis Mode

Run the complete EPC analysis from start to finish in one window with interactive prompts.

## Quick Start

### Windows

**PowerShell**:
```powershell
.\run.ps1
```

**Command Prompt**:
```cmd
run.bat
```

### Linux/Mac

```bash
python run_analysis.py
```

## What It Does

The interactive mode runs the complete analysis pipeline:

1. **✓ Checks credentials** - Prompts for API credentials if missing
2. **✓ Downloads data** - Fetches EPC data via API with your choice of scope
3. **✓ Validates data** - Runs quality checks and cleaning
4. **✓ Analyzes properties** - Characterizes the housing stock
5. **✓ Models scenarios** - Calculates costs and impacts for decarbonization
6. **✓ Generates reports** - Creates charts and summaries

All in one seamless workflow!

## Interactive Prompts

### 1. Data Download Scope

You'll be asked what to download:

**Quick Test** (2-5 minutes)
- Single borough
- Limited to 1000 records
- Perfect for testing the pipeline

**Medium Dataset** (30-60 minutes)
- 5 boroughs (Camden, Islington, Hackney, Westminster, Tower Hamlets)
- Last 5 years of data
- Good balance of coverage and speed

**Full Dataset** (2-4 hours)
- All 33 London boroughs
- Complete EPC history from 2015
- Production-ready dataset

**Custom Selection**
- Choose specific boroughs
- Select date range
- Set record limits
- Full control over scope

### 2. API Credentials

If not already configured, you'll be prompted for:
- Email address
- API key

These are saved to `.env` for future use.

### 3. Confirmation

Review your settings before starting:
- Data scope
- Time estimate
- Storage requirements

## Output

### Console Output

Real-time progress indicators:
- Download progress bars
- Validation statistics
- Analysis summaries
- Key findings

### Files Created

**data/raw/**
- `epc_london_raw.csv` - All downloaded data
- `epc_london_filtered.csv` - Filtered for Edwardian terraced
- `.parquet` versions for faster loading

**data/processed/**
- `epc_london_validated.csv` - Cleaned and validated data
- `validation_report.txt` - Quality assurance summary

**data/outputs/**
- `archetype_analysis_results.txt` - Property characteristics
- `scenario_modeling_results.txt` - Scenario cost-benefit
- `figures/` - Charts and graphs
- `reports/` - Executive summaries

## Example Session

```
========================================
Heat Street EPC Analysis
Complete Interactive Pipeline
London Edwardian Terraced Housing Analysis
========================================

✓ API credentials configured

Data Download Options:

? What would you like to download?
  ❯ Quick test (single borough, limited data)
    Medium dataset (5 boroughs, last 5 years)
    Full dataset (all 33 London boroughs)
    Custom selection

? Select a borough for testing: Camden

Analysis Configuration

Mode: single
From year: 2020
Boroughs: 1

? Start analysis? Yes

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 1: Data Download
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Downloading Camden data...
Camden: 100%|██████████| 5234/5234 [00:45<00:00, 115.42 records/s]
✓ Downloaded 5,234 records
Applying Edwardian terraced housing filters...
✓ Filtered to 1,247 Edwardian terraced houses
Saving data...
✓ Data saved to data/raw/

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 2: Data Validation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Running quality assurance checks...
✓ Validation complete
    Records passed: 1,198 (96.1%)
    Duplicates removed: 34
    Invalid records: 49
✓ Validated data saved

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 3: Archetype Analysis
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Analyzing property characteristics...
✓ Archetype analysis complete

EPC Band Distribution:
    Band D: 234 (19.5%)
    Band E: 567 (47.3%)
    Band F: 312 (26.0%)
    Band G: 85 (7.1%)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 4: Scenario Modeling
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Modeling decarbonization scenarios...
✓ Scenario modeling complete

Scenario Summary:
    baseline: £0 per property
    fabric_only: £11,250 per property
    heat_pump: £24,500 per property
    heat_network: £8,750 per property
    hybrid: £16,125 per property

Running subsidy sensitivity analysis...
✓ Results saved

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 5: Report Generation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Generating reports and visualizations...
✓ Reports generated
    Location: data/outputs/

╭───────────────────────────────────────╮
│    ✓ Analysis Complete!               │
│                                       │
│ Time elapsed: 3.2 minutes             │
│ Properties analyzed: 1,198            │
│                                       │
│ Results saved to:                     │
│   • data/processed/ (validated data)  │
│   • data/outputs/ (reports & charts)  │
╰───────────────────────────────────────╯

? Open results folder? Yes
```

## Features

### Automatic Setup

- Creates `.env` file if missing
- Prompts for credentials
- Validates configuration
- Ensures directories exist

### Smart Defaults

- Sensible download presets
- Optimal filtering for Edwardian terraced
- Automatic file naming
- Both CSV and Parquet formats

### Progress Indicators

- Real-time progress bars
- Status updates
- Time estimates
- Clear success/failure messages

### Error Handling

- Validates API credentials
- Checks for empty datasets
- Handles network errors
- Clear error messages

### Interactive Choices

- Multiple download scopes
- Borough selection
- Date range selection
- Record limits

## Advanced Usage

### Direct Python

```python
from run_analysis import main

# Run with all prompts
main()
```

### With Custom Config

```python
from run_analysis import (
    download_data,
    validate_data,
    analyze_archetype,
    model_scenarios,
    generate_reports
)

# Define custom scope
scope = {
    'mode': 'multiple',
    'boroughs': ['Camden', 'Islington'],
    'from_year': 2020,
    'max_per_borough': 5000
}

# Run pipeline
df = download_data(scope)
df_validated = validate_data(df)
archetype_results = analyze_archetype(df_validated)
scenario_results, subsidy_results = model_scenarios(df_validated)
generate_reports(archetype_results, scenario_results)
```

### Environment Variables

Set these to skip prompts:

```powershell
# PowerShell
$env:EPC_API_EMAIL="your.email@example.com"
$env:EPC_API_KEY="your_api_key"

# Then run
python run_analysis.py
```

## Troubleshooting

### "API credentials not found"

The script will prompt for credentials. They're saved to `.env` for future runs.

### "No data downloaded"

Check:
- API credentials are correct
- Borough name is spelled correctly
- Network connection is working
- API service is online

### "Analysis stopped - no valid data"

The downloaded data failed validation. Check:
- Date range isn't too restrictive
- Borough has EPC data available
- Filters aren't too strict

### Progress bar freezes

This is normal during:
- API requests (waiting for server)
- Large dataset processing
- File I/O operations

Wait a minute before assuming it's stuck.

## Tips

1. **Start with Quick Test** - Verify everything works before full download
2. **Check storage** - Full dataset is ~2GB
3. **Let it run** - Full download takes time, but it's hands-off
4. **Save results** - Output files are reusable for further analysis
5. **Rerun phases** - Can run analysis again on existing data

## Comparison with Manual Mode

| Feature | Interactive | Manual |
|---------|-------------|--------|
| **Setup** | Automatic | Run each script |
| **Prompts** | Interactive | Edit code |
| **Progress** | Visual | Log files |
| **Errors** | Friendly | Technical |
| **Speed** | Same | Same |
| **Control** | Guided | Full |

Use **Interactive** for:
- First time users
- Quick analysis
- Testing
- Demos

Use **Manual** for:
- Automation
- Custom workflows
- Integration
- Advanced control

## Next Steps

After running the interactive analysis:

1. **Review outputs** in `data/outputs/`
2. **Check validation report** for data quality
3. **Examine charts** in `data/outputs/figures/`
4. **Read executive summary** in `data/outputs/reports/`
5. **Customize** scenarios in `config/config.yaml`
6. **Rerun** analysis with different parameters

## Support

If you encounter issues:
1. Check the error message
2. Review this documentation
3. Check `docs/API_USAGE.md`
4. Open an issue on GitHub

Happy analyzing! 🏠📊
