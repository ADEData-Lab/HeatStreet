# Manual GIS Data Installation (London-only)

If the automatic download fails, follow these steps to manually install the London GIS data used for optional London spatial analysis:

## Step 1: Download the ZIP File

**Download URL**: https://data.london.gov.uk/download/2ogw5/1c75726b-0b5e-4f2c-9fd6-25fc83b32454/GIS_All_Data.zip

- File name: `GIS_All_Data.zip`
- Size: ~2.2 MB
- Use your browser or download manager to save this file

## Step 2: Extract to This Directory

**Extract the ZIP file so the final structure looks like this:**

```
data/external/
├── .gitkeep
├── GIS_All_Data.zip           ← The downloaded ZIP file (optional to keep)
└── GIS_All_Data/              ← EXTRACTED FOLDER (required!)
    ├── Heat Loads/
    │   ├── Heat_Loads_20120411Barking_and_Dagenham.shp
    │   ├── Heat_Loads_20120411Islington.shp
    │   └── ... (33 boroughs total)
    ├── Heat Supply/
    │   ├── Heat_Supply_20120411Islington.shp
    │   └── ... (33 boroughs total)
    ├── Networks/
    │   ├── 2.3.1_Existing_DH_Networks.shp
    │   ├── 2.3.2.1_Potential_DH_Transmission_Line.shp
    │   ├── 2.3.2.2._Potential_DH_Networks.shp
    │   └── 2.3.2.3_Potential_Networks_2005_Study.shp
    └── LDD 2010/
        └── ... (development database)
```

## Step 3: Verify Installation

The correct path should be:
- **Windows**: `data\external\GIS_All_Data\Heat Loads\`
- **Linux/Mac**: `data/external/GIS_All_Data/Heat Loads/`

**You should see 3 main folders inside `GIS_All_Data/`:**
1. `Heat Loads/` - Contains 33 shapefiles (one per London borough)
2. `Heat Supply/` - Contains 33 shapefiles
3. `Networks/` - Contains 4 network shapefiles

## Step 4: Run the Analysis

Once the folder is in place, run the analysis:

```bash
# Windows
run-conda.bat

# PowerShell
.\run-conda.ps1
```

The spatial analysis will automatically detect and use the GIS data!

## Troubleshooting

**Problem**: "GIS data not found" error during spatial analysis

**Solution**: Check that you have this exact folder structure:
```
data/external/GIS_All_Data/Heat Loads/
data/external/GIS_All_Data/Heat Supply/
data/external/GIS_All_Data/Networks/
```

**Common mistake**: Extracting creates `data/external/GIS_All_Data/GIS_All_Data/` (double nested)
- If this happens, move the inner `GIS_All_Data/` folder up one level

**Still not working?**:
- Verify you can see `.shp` files inside the `Heat Loads/` folder
- Each shapefile comes with multiple files (.shp, .shx, .dbf, .prj) - this is normal
- Make sure you extracted the entire folder, not just individual files

## Alternative: Download via Python

If you have the environment set up, you can also download via Python:

```bash
# Activate environment first
conda activate heatstreet

# Run the downloader
python -c "from src.acquisition.london_gis_downloader import LondonGISDownloader; LondonGISDownloader().download_and_prepare()"
```

---

For more details, see: [docs/GIS_DATA.md](../../docs/GIS_DATA.md)
