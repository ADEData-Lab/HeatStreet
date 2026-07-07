# External Data Cache

This directory stores downloaded external datasets used by HeatStreet.

## Active Heat Network Source

HeatStreet uses the Heat Network Planning Database (HNPD) as its only external heat-network infrastructure source.

Expected cache file:

```text
data/external/hnpd-january-2024.csv
```

The pipeline can download this file automatically through `src/acquisition/hnpd_downloader.py`.

## If HNPD Is Missing

If HNPD cannot be downloaded or read, HeatStreet does not fall back to another external heat-network infrastructure source. Tier 1-2 network-proximity evidence may be unavailable, but Tier 3-5 density-based classification can still run from EPC/property heat-density calculations.

## Local Files

Do not commit downloaded datasets from this directory unless they are intentionally small fixtures. The `.gitkeep` file keeps the directory present in fresh clones.
