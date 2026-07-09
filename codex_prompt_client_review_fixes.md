# Codex prompt — HeatStreet repo fixes from client review (Heat Street Report v11)

Copy everything below the line into Codex.

---

The client has reviewed the Heat Street report and flagged several anomalous outputs. Some are genuine model behaviour that needs clearer presentation; others are inconsistencies in the reporting layer. Make the following changes to the HeatStreet repo. Do not change the underlying economics unless stated — several "anomalies" are correct results of the assumptions and only need explanatory output.

## 1. Tier 3 vs Tier 4 cost inversion (retrofit readiness table)

In `src/analysis/retrofit_readiness.py`, `_calculate_total_retrofit_cost()` assigns Tier 4 properties a hybrid heat pump (~£8k) while all other tiers get a full ASHP (~£12k). This makes Tier 4 (£22,843 avg) cheaper than Tier 3 (£24,280) despite worse fabric, which the client flagged as a data error. The docstring says this is intentional, but the reported table hides the technology switch.

Fix the presentation, not the logic:
- Add a `system_technology` column ('ashp' or 'hybrid_ashp') to the readiness dataframe and to the per-tier summary in `generate_readiness_summary()`.
- Split the per-tier summary into `fabric_cost`, `system_cost` and `total_cost` so the table can show that Tier 4's fabric cost is higher but its assumed system is cheaper.
- Additionally output a like-for-like comparison column: `total_cost_full_ashp` where every tier is costed with a full ASHP, so a monotonic cost-by-tier series is available for the report.
- Emit a one-line explanatory note in the summary text file explaining the hybrid assumption for Tier 4.

## 2. Cost reduction levers table — totals do not reconcile

`src/reporting/dashboard_data_builder.py`, `_format_cost_levers()` hard-codes five levers: 2100 + 1800 + 1200 + 800 + 200 = £6,100. The report table says "TOTAL POTENTIAL ~£7,000" and the executive summary elsewhere claims "£3,000–£5,000 per dwelling". Three different numbers for the same thing.

- Compute the total programmatically from the lever list and include it in the returned data (add a `total` entry or field) so the report can never drift from the sum.
- Move the lever values into `config/config.yaml` (new `cost_reduction_levers` section, each with lever name, impact_gbp, difficulty, source note) so there is a single source of truth.
- Add a note field stating that levers overlap and are not fully additive; include both the arithmetic sum and a conservative combined estimate (e.g. 50–80% of the sum) so the narrative range can cite it.

## 3. Carbon abatement cost — two competing definitions

The scenario outputs contain both `carbon_abatement_cost_mean` (mean of per-property abatement costs, e.g. £681.8/tCO₂ for fabric-only) and `cost_per_tco2_20yr_gbp` (aggregate capex ÷ aggregate 20-yr CO₂, e.g. £635.0). The report quoted £681 in one place and £651 in a comment reply — the client flagged the figure as "really high" and the ambiguity makes it worse.

- In `src/modeling/scenario_model.py` / `src/reporting/report_headline_data.py`, designate `cost_per_tco2_20yr_gbp` (aggregate basis) as the headline metric; rename or clearly label the per-property mean as `carbon_abatement_cost_property_mean` and mark it diagnostic-only.
- Add the definition string (formula and 20-year lifetime assumption) to the datapoint's `definition` field wherever it is emitted so report authors can footnote it verbatim.

## 4. Borough priority ranking — narrative block with real numbers

The report has a paragraph full of [TBC] placeholders for the borough priority ranking, and the hard-coded narrative order (Croydon first) no longer matches pipeline output (latest run: Bromley 1st, Enfield 2nd, Barnet 3rd, Croydon 4th).

- In `src/analysis/additional_reports.py`, `generate_borough_priority_ranking()`: extend the .txt summary to also write a ready-to-paste report paragraph, e.g. "X ranks first with N properties, mean EPC of E, energy intensity of I kWh/m²/year, and priority score of S. Y follows with …" for the top five, plus the combined share of total target-archetype properties the top five represent.
- Include the run date and source dataset in the block so stale text is detectable.

## 5. Figure labels and annotation placement

Client comments: missing/unclear x-axis name on Figure 1, annotation boxes overlapping the tipping-point curve, and a general request for larger, clearer images.

In `src/reporting/visualizations.py`:
- Replace debug-style axis labels such as "Lodgement year (LODGEMENT_DATE; fallback INSPECTION_DATE)" with client-facing labels ("Lodgement year"); keep the field provenance in the accompanying `_calculation.md` file instead.
- In the tipping-point plot (~lines 800–860), reposition the two annotation boxes so they never overlap the curve or each other: compute their y-positions from the data range rather than fixed offsets, or use `annotate` with automatic placement above/below the curve depending on available space.
- Increase base font sizes (`plt.rcParams['font.size']` ≥ 12, axis labels ≥ 13) and set figure DPI export to 300 (already done) with larger figsize where text is cramped.

## 6. Retrofit cost envelopes — add heat network and hybrid pathways

The report's cost-envelope table only covers three fabric/heat-pump packages; the client asked where the heat network and hybrid scenarios are. The data already exists in the "Heat Network vs Heat Pump Comparison" output (capex mean/median/p10/p90 for `fabric_plus_hp_only`, `fabric_plus_hn_only`, `fabric_plus_hp_plus_hn`).

- Add a "Retrofit cost envelopes" table to the one-stop report output (e.g. in `src/reporting/one_stop_report.py`) with one row per pathway — fabric-only, fabric+ASHP, fabric+HN, hybrid — showing capex p10–p90 range, median, and a one-line note. Source the numbers from existing scenario/pathway results; do not hard-code.

## 7. Heat network payback footnote — emit the explanation with the data

Not a bug: HN has lower capex (~£20.5k vs ~£25.3k) but a ~74-yr payback vs ~47 yrs for heat pumps because the modelled HN tariff (8p/kWh, `config.yaml` `heat_network.tariff_per_kwh`) exceeds the gas price (6.24p/kWh), so connection erodes the fabric bill savings; HN's advantage is carbon (0.073 kgCO₂/kWh vs 0.183 for gas), not bills.

- Add a `payback_note` field to the HN scenario output and the HN-vs-HP comparison table stating this mechanism and citing both tariff assumptions, so the report footnote is generated from the same config values and stays in sync if the tariff changes.

## 8. Subsidy sensitivity — ensure 50% level is surfaced

The report narrative jumps from 25% to 75% subsidy; the client asked why 50% is unexplained. The pipeline already computes 50% (e.g. heat pump: payback 21.6 yrs, uptake ~10.9%). No model change needed, but in the subsidy summary output add a short per-level narrative line (payback, uptake, public spend, £/tCO₂) for every level in `subsidy_levels` so no level can be skipped when drafting.

## Constraints

- Do not alter energy prices, carbon factors, or cost assumptions in `config/config.yaml` other than adding the new `cost_reduction_levers` section.
- Keep all existing output keys backward-compatible where possible; add, don't rename, except the abatement-cost rename in item 3 (keep the old key as a deprecated alias for one release).
- Add or update unit tests for: lever total reconciliation, tier cost columns (fabric+system=total; full-ASHP series monotonic non-decreasing by tier), and presence of the new envelope table and payback note.
- Run the test suite and report results.
