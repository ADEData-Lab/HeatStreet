# DESNZ Heat Network Planning Data Integration

The Heat Street EPC Analysis can optionally use DESNZ heat network planning data to
enhance spatial analysis capabilities for UK-wide runs.

## What's Included

The DESNZ heat network planning database typically provides:

- **Existing heat networks** (current infrastructure).
- **Heat network zones** (planned or designated areas).

Exact layer names and formats may vary by release.

## Data Source

**DESNZ Heat Network Planning Database**
- Collection: https://www.gov.uk/government/collections/heat-networks
- Download the latest planning dataset and extract it locally.

## Heat network readiness flags

`ScenarioModeler` asks the spatial analyzer to compute deterministic heat network
flags before scenarios run. The pipeline in `src/spatial/heat_network_analysis.py`
geocodes EPC rows, loads DESNZ planning layers, and appends four columns to the EPC
DataFrame:

- `tier_number` – tier classification (1–5) driven by distance to existing networks,
  whether the point falls inside a heat-network zone polygon, and buffered heat density.
- `distance_to_network_m` – metres to the nearest existing network (EPSG:27700).
- `in_heat_zone` – `True` if the property intersects a zone polygon.
- `hn_ready` – readiness flag based on thresholds in `config/config.yaml` under
  `heat_network.readiness` (`max_distance_to_network_m`, `heat_zone_ready`,
  `min_density_gwh_km2`, `ready_tier_max`).

These columns are consumed by both the hybrid scenario builder and `PathwayModeler`,
replacing any random assignment of heat network access.

## How to Install

### Option 1: Manual Download (Most Reliable)

1. Download the DESNZ heat network planning dataset.
2. Create the directory (if it doesn't exist):
   ```bash
   mkdir -p data/external/desnz_heat_network_planning
   ```
3. Extract layers into the following structure:
   ```
   data/external/desnz_heat_network_planning/
   ├── networks/   # Existing heat network layers
   └── zones/      # Heat network zone layers
   ```

Supported formats: GeoPackage (`.gpkg`), GeoJSON (`.geojson`), or Shapefile (`.shp`).

### Option 2: Automatic Download

The interactive CLI can attempt a download if `DESNZ_HEAT_NETWORK_DATA_URL` is set:

```bash
export DESNZ_HEAT_NETWORK_DATA_URL="https://example.com/desnz_heat_network_planning.zip"
python run_analysis.py
```

## Usage in Analysis

```python
from src.spatial.heat_network_analysis import HeatNetworkAnalyzer

analyzer = HeatNetworkAnalyzer()

# Load heat networks (automatically uses downloaded data)
heat_networks, heat_zones = analyzer.load_desnz_heat_network_data()

# Classify properties by heat network tiers
properties_gdf = analyzer.classify_heat_network_tiers(
    properties=df_validated,
    heat_networks=heat_networks,
    heat_zones=heat_zones,
)
```

## Requirements

### For Basic Download
- No additional dependencies required.

### For Spatial Analysis (Reading GIS layers)

If you want to use the GIS data for spatial analysis, install spatial dependencies:

```bash
pip install -r requirements-spatial.txt
```

This includes:
- geopandas
- shapely
- fiona
- GDAL (see [WINDOWS_INSTALLATION.md](WINDOWS_INSTALLATION.md) for Windows setup)

## Troubleshooting

### Data Not Found

If you see "GIS data not found", verify the directory structure:

```
data/external/desnz_heat_network_planning/networks/
data/external/desnz_heat_network_planning/zones/
```

### Cannot Read Layers

If you get errors reading GIS layers:

1. Check GDAL installation:
   ```powershell
   python -c "import geopandas; print('OK')"
   ```
2. Install spatial dependencies:
   ```powershell
   pip install -r requirements-spatial.txt
   ```
3. Windows users: see [WINDOWS_INSTALLATION.md](WINDOWS_INSTALLATION.md).
