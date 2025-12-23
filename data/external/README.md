# Manual GIS Data Installation (DESNZ Heat Network Planning Data)

If the automatic download fails, follow these steps to manually install the DESNZ heat network planning data used for spatial analysis:

## Step 1: Download the ZIP File

**Download URL**: See the DESNZ heat network planning database download portal

- Download the latest package (format may vary: ZIP, GeoPackage, or GeoJSON)
- Use your browser or download manager to save the file

## Step 2: Extract to This Directory

**Extract the ZIP file so the final structure looks like this:**

```
data/external/
├── .gitkeep
├── desnz_heat_network_planning.zip      ← The downloaded ZIP file (optional to keep)
└── desnz_heat_network_planning/          ← EXTRACTED FOLDER (required!)
    ├── networks/                         ← Existing heat network layers
    │   └── networks.gpkg
    └── zones/                            ← Heat network zone layers
        └── zones.gpkg
```

## Optional CSV Fallback (Existing Networks Only)

If you only have the CSV extract (for example `hnpd-january-2024.csv`),
place it in `data/external/` and the analysis will use it when the GIS layers
are missing:

```
data/external/
├── hnpd-january-2024.csv
└── desnz_heat_network_planning/
```

Expected columns:
- `X-coordinate` (British National Grid Easting)
- `Y-coordinate` (British National Grid Northing)

To use a different CSV location, set `DESNZ_HEAT_NETWORK_CSV_PATH` to the file path.

## Step 3: Verify Installation

The correct path should be:
- **Windows**: `data\external\desnz_heat_network_planning\networks\`
- **Linux/Mac**: `data/external/desnz_heat_network_planning/networks/`

**You should see folders inside `desnz_heat_network_planning/`:**
1. `networks/` - Existing heat network layers
2. `zones/` - Heat network zone layers

## Step 4: Run the Analysis

Once the folder is in place, run the analysis:

```bash
# Windows
run-conda.bat

# PowerShell
.\run-conda.ps1
```

The spatial analysis will automatically detect and use the DESNZ data!

## Troubleshooting

**Problem**: "GIS data not found" error during spatial analysis

**Solution**: Check that you have this exact folder structure:
```
data/external/desnz_heat_network_planning/networks/
data/external/desnz_heat_network_planning/zones/
```

**Common mistake**: Extracting creates `data/external/desnz_heat_network_planning/desnz_heat_network_planning/` (double nested)
- If this happens, move the inner `desnz_heat_network_planning/` folder up one level

**Still not working?**:
- Verify you can see GIS layers inside the `networks/` or `zones/` folders
- GeoPackage (`.gpkg`), GeoJSON (`.geojson`), or Shapefile (`.shp`) are supported
- Make sure you extracted the entire folder, not just individual files

## Alternative: Download via Python

If you have the environment set up, you can also download via Python:

```bash
# Activate environment first
conda activate heatstreet

# Run the downloader
python -c "from src.acquisition.desnz_heat_network_downloader import DESNZHeatNetworkDownloader; DESNZHeatNetworkDownloader().download_and_prepare()"
```

---

For more details, see: [docs/GIS_DATA.md](../../docs/GIS_DATA.md)
