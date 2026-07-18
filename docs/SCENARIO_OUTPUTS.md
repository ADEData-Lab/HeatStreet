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
| `aggregate_simple_payback_years` | `capital_cost_total / annual_bill_savings`; null when aggregate savings are non-positive |
| `property_simple_payback_mean_years` / `property_simple_payback_median_years` | Mean/median across all valid finite property paybacks with positive finite savings; no 100-year truncation |
| `payback_valid_denominator_count` | Properties included in the mean and median |
| `payback_non_positive_savings_count` | Finite inputs with zero or negative annual savings |
| `payback_missing_input_count` | Capital cost or annual savings is missing |
| `payback_non_finite_input_count` | A present capital-cost or savings input is non-finite |
| `payback_infinite_count` | Division produced a mathematically infinite result; does not include other invalid categories |
| `excluded_by_truncation_count` / `truncation_threshold_years` | Always `0` / null under the no-truncation policy |
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
# Model-family and publication contract

Public scenario, comparison, subsidy, dashboard, and one-stop outputs come only from the `stock_scenario` family. `pathway_results_by_property.parquet`, `pathway_results_summary.csv`, and the diagnostic HP/HN comparison remain internal and carry `diagnostic_full_fabric_pathway` metadata with `headline_reporting_eligible=false`.

Public payback fields are `aggregate_simple_payback_years`, `property_simple_payback_mean_years`, and `property_simple_payback_median_years`, accompanied by status, denominator, non-positive-savings, infinite, and truncation-count fields. The zero-subsidy aggregate must reconcile exactly to the corresponding canonical scenario aggregate. Subsidy uptake is labelled “modelled sensitivity, not forecast.”

`window_economics.csv` is generated from configured glazing costs, saving fractions, gas price, the explicit simple-payback definition, and source notes. `subsidy_sensitivity_analysis_simple_gbp.csv` is retired.

Canonical readiness labels are **Tier 1: Ready now**, **Tier 2: Minor work**, **Tier 3: Moderate work**, **Tier 4: Significant work**, and **Tier 5: Extensive intervention / currently unsuitable for a standard ASHP**. They describe fabric and heat-demand readiness and prescribe no heating technology.

Semantic QA reconciles percentage distributions within 0.1 percentage points and costs within GBP 1 absolute / 1e-9 relative tolerance. A mixed HN-ready cohort must allocate both HN and ASHP homes; publication fails if its hybrid output collapses to either pure pathway across the contracted comparison fields.
