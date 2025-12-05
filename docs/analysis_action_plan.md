# Analysis improvement action plan

This to-do list captures the follow-up items from the review call and assigns owners plus target timelines. Dates are expressed relative to the next reporting cycle; adjust as schedules firm up.

## 1) Fixes and consistency checks in current modelling
- **Hybrid pathway cost anomaly**  
  - *Owner:* Phil / modelling team  
  - *Action:* Investigate why the hybrid (fabric + heat pump + heat network) pathway costs match the fabric-only case; correct any modelling or input issues and rerun the comparison.  
  - *Target:* Before next pathway results refresh.
- **Radiator upsizing assumption**  
  - *Owner:* Phil  
  - *Action:* Document that radiator upsizing is currently modelled as a standalone measure. If time allows, add a variant that applies upsizing after key fabric upgrades to quantify the remaining emitter work.  
  - *Target:* Document now; variant by upcoming sprint end.

## 2) Retrofit / fabric analysis improvements
- **Combined retrofit packages**  
  - *Owner:* Phil  
  - *Action:* Add package scenarios that bundle top measures (e.g. loft + walls + radiators), reporting total capex, energy/carbon savings, and marginal savings per additional £. Capture bundle cost reductions and diminishing returns.  
  - *Target:* Next results drop.
- **“Rolls Royce” and 2-measure bundles**  
  - *Owner:* Phil  
  - *Action:* Include a max retrofit package (all main measures) and at least one high-impact pairing (e.g. loft + radiators) to show cost vs impact.  
  - *Target:* Next results drop.
- **Split hybrid system options**  
  - *Owner:* Phil  
  - *Action:* Model three distinct scenarios: (1) fabric + heat pump + heat network, (2) fabric + heat pump only, (3) fabric + heat network only. Compare cost, bills, and carbon.  
  - *Target:* Next pathway update.
- **Payback times**  
  - *Owner:* Phil  
  - *Action:* Calculate simple (and ideally discounted) payback for each main package/pathway using bill savings; publish alongside capex and annual savings.  
  - *Target:* Next pathway update.
- **Window treatment (double vs triple glazing)**  
  - *Owner:* Phil  
  - *Action:* State glazing assumptions clearly and either shift to triple-glazing values or add a double vs triple comparison showing cost and savings deltas.  
  - *Target:* Upcoming retrofit modelling refresh.
- **Granular EPC fabric breakdown**  
  - *Owner:* Phil  
  - *Action:* Extend EPC analysis to show wall type vs insulation status, loft/roof insulation levels, and floor insulation to characterise the retrofit gap.  
  - *Target:* Next EPC data cut.

## 3) Scenario and system-level improvements
- **Interactive sensitivity on heat-network share & prices**  
  - *Owner:* Phil  
  - *Action:* Build a lightweight slider-based tool (offline HTML acceptable) to vary heat-network uptake and price assumptions (gas/electric/heat) and show resulting pathway costs.  
  - *Target:* Prototype for next stakeholder review.
- **Foreground system-level benefits (load profile)**  
  - *Owner:* Phil  
  - *Action:* Use modelling to show how pathways change peak vs average heat demand and highlight implications for system costs; make this a headline in the summary/conclusions.  
  - *Target:* Next report draft.

## 4) EPC data treatment and uncertainty
- **Tenure filtering**  
  - *Owner:* Phil  
  - *Action:* Re-run key stats for owner-occupied Edwardian terraces; note if findings change materially.  
  - *Target:* Next EPC data cut.
- **EPC anomalies (uninsulated but band D)**  
  - *Owner:* Phil with DEA input  
  - *Action:* Flag inconsistencies and adjust using literature-based EPC reliability insights (e.g., accounting for LEDs/new boilers).  
  - *Target:* Next EPC data cut.
- **EPC error / pre-bound treatment**  
  - *Owner:* Phil; DEA to provide literature review inputs  
  - *Action:* Incorporate DEA feedback into sensitivity ranges or adjustment factors for EPC-derived demand, and document the approach in a methodological appendix.  
  - *Target:* After DEA literature feedback.

## Coordination
- **DEA literature feedback**  
  - *Owner:* DEA team  
  - *Action:* Share written comments on EPC error and pre-bound effects; coordinate with Phil to integrate into modelling.  
  - *Target:* Before methodological appendix is finalised.
