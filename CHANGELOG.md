# Changelog

## [Unreleased] - 2026-01-25

### Multi-pathway subsidy sensitivity + one-stop dashboard tab

- **Extended** subsidy sensitivity to run for multiple scenarios (`heat_pump`, `hybrid`, `heat_network`) and export a consolidated table.
- **Fixed** one-stop Section 9 so subsidy results are embedded cleanly (no duplicated/unknown% datapoints) and include a full results table.
- **Added** a "Subsidy Sensitivity" tab to the one-stop HTML dashboard template (`heat_street_dashboard.html`), driven only from `one_stop_output.json`.
- **Separated** the legacy simple-GBP subsidy analysis output to avoid overwriting the canonical `subsidy_sensitivity_analysis.csv`.

### Property Count Reconciliation Audit Fix

### Property Count Reconciliation Audit Fix

This release addresses critical audit findings related to property count mismatches between different pipeline stages and ensures all reported figures are derived from actual data rather than hard-coded values.

#### Key Changes

##### 1. Run Metadata Infrastructure (`src/utils/run_metadata.py`)
- **NEW**: `RunMetadataManager` class tracks property counts at each pipeline stage
- Records counts for: raw_loaded, after_validation, after_geocoding, scenario_input, final_modeled
- Automatically detects and warns about count drops exceeding configurable thresholds
- Generates reconciliation table for audit trail
- Saves to `data/outputs/run_metadata.json`

##### 2. Hard-Coded Value Removal
- **FIXED**: `generate_dashboard_data.py` - totalProperties now computed from EPC band data
- **FIXED**: `dashboard/src/data/dashboardData.js` - totalProperties derived from epcBandData array
- **FIXED**: `dashboard/src/data/mockData.js` - totalProperties computed from EPC band counts
- **FIXED**: `dashboard_data_builder.py` - reads from run_metadata.json as authoritative source

##### 3. Heat Network Tier Labeling (`src/spatial/heat_network_analysis.py`)
- **FIXED**: All 5 tiers now always appear in output (Tier 1-5)
- **FIXED**: Tier 2 (planned network indicator) no longer skipped when count is 0
- Added explicit notes for each tier definition

##### 4. Scenario Model Improvements (`src/modeling/scenario_model.py`)
- **FIXED**: `hn_assigned_properties` and `ashp_assigned_properties` populated for ALL scenarios
  - Heat pump scenarios: ashp_assigned = HP count, hn_assigned = 0
  - Heat network scenarios: hn_assigned = HN count, ashp_assigned = 0
  - Hybrid scenarios: both populated based on hybrid_pathway column
  - Fabric-only/baseline: both set to 0
- **DOCUMENTED**: "Not cost-effective" edge cases (properties with infinite payback)
  - Added logging for properties with zero/negative baseline bills
  - These are flagged for investigation rather than excluded

##### 5. Executive Summary Generator (`src/reporting/executive_summary.py`)
- **NEW**: Generates markdown summary from actual output files
- Pulls data from run_metadata.json, scenario_results_summary.csv, pathway_suitability_by_tier.csv
- Includes stage count reconciliation table
- Adds explanatory notes for counterintuitive results:
  - Why lower CAPEX can have longer payback
  - Why tipping-point fabric can outperform minimum fabric

##### 6. Pipeline Integration (`run_analysis.py`)
- Added `RunMetadataManager` integration across all phases
- Counts recorded at: acquisition, validation, modeling start, modeling end, geocoding
- Metadata saved automatically at pipeline completion
- Reconciliation table logged for visibility

#### Acceptance Criteria Met

1. No hard-coded totals remain in code paths
2. All outputs report totals matching their actual dataset
3. Count drops between stages are explicitly quantified and explained
4. Run metadata provides audit trail for count reconciliation
5. Tier labeling is sequential and complete (Tiers 1-5)
6. Assigned properties fields populated for all scenario types

#### Files Changed

- `run_analysis.py` - Added metadata tracking and reconciliation
- `src/utils/run_metadata.py` - NEW: Stage count tracking
- `src/reporting/executive_summary.py` - NEW: Summary generator
- `src/reporting/dashboard_data_builder.py` - Uses run_metadata
- `src/modeling/scenario_model.py` - Fixed assigned properties logic
- `src/spatial/heat_network_analysis.py` - Fixed tier labeling
- `generate_dashboard_data.py` - Derived counts
- `dashboard/src/data/dashboardData.js` - Derived counts
- `dashboard/src/data/mockData.js` - Derived counts, added Tier 2

#### Testing

Run the full pipeline to verify:
```bash
python run_analysis.py
```

Check reconciliation:
```bash
cat data/outputs/run_metadata.json
cat data/outputs/reports/executive_summary.md
```

Verify no hard-coded constants remain:
```bash
rg -n "704483|703993|704,483|703,993" src/
```
