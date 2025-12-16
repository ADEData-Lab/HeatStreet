## Scenario modeling outputs

Scenario modeling now produces both aggregate summaries and a per-property dataset. Outputs are saved to `data/outputs/` by the CLI and via `run_analysis.py`.

### File locations

- `scenario_modeling_results.txt`: human-readable scenario summary (existing output)
- `scenario_results_summary.csv`: tidy scenario-level metrics ready for dashboards and compendium export
- `scenario_results_by_property.parquet`: property-by-property record of how each scenario was applied

### `scenario_results_summary.csv`

Each row corresponds to a modeled scenario with capital costs, savings, readiness counts, and hybrid assignments.

| Column | Description |
| --- | --- |
| `scenario` | Scenario identifier from `config.yaml` |
| `total_properties` | Properties modeled in the scenario |
| `capital_cost_total` / `capital_cost_per_property` | Aggregate and average CAPEX |
| `annual_energy_reduction_kwh` | Total annual energy reduction |
| `annual_co2_reduction_kg` | Total annual CO₂ reduction |
| `annual_bill_savings` | Total annual bill saving |
| `baseline_bill_total` / `post_measure_bill_total` | Annual bill spend before/after measures |
| `baseline_co2_total_kg` / `post_measure_co2_total_kg` | Annual CO₂ before/after measures |
| `average_payback_years` / `median_payback_years` | Payback statistics (cost-effective homes only) |
| `ashp_ready_properties` / `ashp_fabric_required_properties` / `ashp_not_ready_properties` | ASHP readiness diagnostics |
| `ashp_fabric_applied_properties` | Homes where minimum fabric was injected to enable ASHP |
| `ashp_not_eligible_properties` | Homes where ASHP was removed because fabric could not enable eligibility |
| `hn_ready_properties` | Homes flagged as heat-network ready |
| `hn_assigned_properties` / `ashp_assigned_properties` | Hybrid split between district heating and ASHP |

### `scenario_results_by_property.parquet`

One row per property per scenario capturing diagnostics and cost/savings breakdowns.

| Column | Description |
| --- | --- |
| `property_id` / `uprn` / `postcode` | Identifiers from the validated EPC dataset |
| `scenario` | Scenario name applied |
| `measures_applied` | Ordered list of measures applied after readiness logic |
| `measures_removed` | Measures removed (e.g., ASHP dropped when not feasible) |
| `hybrid_pathway` | `heat_network` when a district heat connection was used, `ashp` otherwise |
| `hn_ready`, `tier_number`, `distance_to_network_m`, `in_heat_zone` | Heat network diagnostics |
| `ashp_ready`, `ashp_projected_ready`, `ashp_fabric_needed`, `ashp_not_ready_after_fabric` | Heat pump readiness diagnostics |
| `fabric_inserted_for_hp`, `heat_pump_removed` | Flags showing where fabric was inserted or ASHP removed |
| `capital_cost` | Scenario CAPEX for the property |
| `annual_energy_reduction_kwh` | Annual energy reduction |
| `annual_co2_reduction_kg` / `post_measure_co2_kg` / `baseline_co2_kg` | Emissions impact |
| `annual_bill_savings` / `baseline_bill` / `post_measure_bill` | Bill impact |
| `new_epc_band` | Estimated EPC band post-upgrade |
| `payback_years` | Simple payback (infinite when not cost-effective) |

> Tip: because `measures_applied` and `measures_removed` are stored as lists, use pandas with `explode` if you want to count per-measure uptake.
