# Spatial Data Inputs

HeatStreet no longer downloads or loads third-party London GIS packages at runtime. Heat network modelling now uses:

- **HNPD** for Tier 1-2 external heat network infrastructure evidence.
- **EPC/property heat-density analysis** for Tier 3-5 classification.

## HNPD

The Heat Network Planning Database is downloaded by `src/acquisition/hnpd_downloader.py` and cached in `data/external/hnpd-january-2024.csv`.

The configured source lives in `config/config.yaml` under `data_sources.heat_networks.hnpd`.

HNPD records are converted to point geometries using British National Grid coordinates:

- Tier 1 evidence: operational, under construction, and no-application-required schemes.
- Tier 2 evidence: planning-permission-granted and equivalent approved schemes.

If HNPD is unavailable, HeatStreet does not use another external heat-network infrastructure source. Tier 1-2 proximity evidence may be unavailable, but Tier 3-5 density classification can still run.

## Readiness Columns

`ScenarioModeler` asks the spatial analyzer to compute deterministic heat network readiness flags before scenarios run. The spatial analyzer geocodes EPC rows, loads HNPD when available, and appends:

- `tier_number`: tier classification from 1 to 5.
- `distance_to_network_m`: metres to the nearest HNPD Tier 1 network point proxy.
- `in_heat_zone`: `True` when a property is within the configured planned-network proxy distance.
- `hn_ready`: readiness flag based on `config/config.yaml` thresholds under `heat_network.readiness`.

These columns are consumed by the hybrid scenario builder and `PathwayModeler`.

## Density Tiers

Tier 3-5 classification is calculated from EPC-derived heat demand and local spatial aggregation:

1. Geocode EPC rows to property/postcode-centroid points.
2. Aggregate heat demand across the configured grid neighbourhood.
3. Assign Tier 3, Tier 4, or Tier 5 using the configured GWh/km2 thresholds.

The grid settings are configured under `spatial.grid` in `config/config.yaml`.

## Requirements

Spatial analysis requires the geopandas/GDAL stack. On Windows, use the supported Conda workflow:

```bash
conda env create -f environment.yml
conda activate heatstreet
.\run-conda.ps1
```

On Linux/macOS or advanced setups with working GDAL tooling:

```bash
pip install -r requirements-spatial.txt
```

## Usage

```python
from src.spatial.heat_network_analysis import HeatNetworkAnalyzer

analyzer = HeatNetworkAnalyzer()
heat_networks, heat_zones = analyzer.load_heat_network_data(data_source="hnpd")
```

`data_source="hnpd"` is the only supported external heat-network source. Legacy source names return no network layers and log a warning.

## Related Documentation

- [Spatial Setup](SPATIAL_SETUP.md)
- [API Usage](API_USAGE.md)
- [Quickstart Guide](../QUICKSTART.md)
