# External Data Inputs

This directory stores manually supplied external datasets used by HeatStreet. These files are not committed to Git.

## Heat Networks Planning Database

HeatStreet expects the current Q1 2026 Heat Networks Planning Database export at exactly:

```text
data/external/heat_networks_procurement_pipeline_Q1_2026.csv
```

Download the CSV manually from the GOV.UK Heat Networks Pipelines publication page:

```text
https://www.gov.uk/government/publications/heat-networks-pipelines
```

Place the downloaded file in `data/external` without changing its filename. HeatStreet validates the schema, British National Grid coordinates, London coverage, file size and SHA-256 fingerprint before using it.

The expected file is the Q1 2026 procurement pipeline CSV. It contains the columns used by HeatStreet, including `Ref ID`, `Site Name`, `Region`, `Development Status`, `Development Status (short)`, `X-coordinate` and `Y-coordinate`.

## Missing or invalid file

HeatStreet does not automatically download an older HNPD release and does not substitute density-only classification for missing Tier 1 and Tier 2 evidence. When the file is missing or invalid, the log tells the user which file to download and where to place it.

When a later quarterly release is adopted, update the configured filename and regression expectations rather than renaming the new file to look like Q1 2026.
