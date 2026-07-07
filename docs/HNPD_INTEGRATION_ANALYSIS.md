# HNPD Integration Status

**HNPD version:** January 2024

HeatStreet now treats the Heat Network Planning Database (HNPD) as the only external heat-network infrastructure source.

## Current Role

HNPD supplies Tier 1-2 evidence:

- **Tier 1:** operational, under construction, and no-application-required schemes.
- **Tier 2:** planning-permission-granted and equivalent approved schemes.

HNPD records are loaded from CSV, converted to point geometries using British National Grid coordinates, and filtered by the configured region in `config/config.yaml`.

## Density Classification

HNPD does not provide the local heat-density surface used for Tier 3-5 screening. HeatStreet calculates those tiers from EPC/property heat-demand data and the configured spatial grid aggregation method.

## Failure Mode

If HNPD acquisition fails, HeatStreet does not attempt another external infrastructure source. The model reports that Tier 1-2 network proximity evidence may be unavailable, while Tier 3-5 density-based classification can still run.

## Implementation

- Downloader: `src/acquisition/hnpd_downloader.py`
- Spatial loader: `HeatNetworkAnalyzer.load_heat_network_data(data_source="hnpd")`
- Config: `data_sources.heat_networks.primary: "hnpd"`

Legacy source names passed to `load_heat_network_data` are rejected with a warning and return no network layers.
