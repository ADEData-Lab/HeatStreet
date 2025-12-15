# Data & Calculation Audit for `run_ade_analysis`

This document catalogs every formula, parameter, and external datapoint used when executing the ADE analysis workflow (i.e., the full modeling and retrofit pipeline invoked by `run_ade_analysis`). Each item includes the code location and a short note on provenance/usage so values can be independently validated.

## Core Financial and Carbon Inputs
- **Retail energy prices (£/kWh)**
  - Current cap: gas £0.0624, electricity £0.245 (Ofgem Q4 2024 price cap).【F:config/config.yaml†L214-L229】
  - Projections: gas £0.07/£0.08 and electricity £0.22/£0.18 for 2030/2040 scenarios respectively.【F:config/config.yaml†L223-L229】
- **Carbon intensity (kgCO₂/kWh)**
  - Current factors: gas 0.183, electricity 0.233 (DESNZ 2024 & SAP 10.0).【F:config/config.yaml†L230-L244】
  - Future grid factors: electricity 0.100 (2030) and 0.050 (2040); gas held at 0.183.【F:config/config.yaml†L239-L244】
- **Heat network assumptions**
  - Tariff £0.08/kWh delivered; distribution efficiency 0.90 (10% losses); penetration scenarios 0.2–10%.【F:config/config.yaml†L255-L263】
- **Financial parameters**
  - Discount rate 3.5% real; 20‑year analysis horizon; price scenario blocks (baseline/low/high/2030).【F:config/config.yaml†L265-L289】

## Methodological Adjustments
- **Prebound adjustment (Few et al., 2023)**
  - EPC energy consumption is scaled by EPC‑band factors (e.g., D = 0.82, E = 0.72, F = 0.55). Adjusted intensity feeds baseline annual consumption when floor area is available.【F:src/analysis/methodological_adjustments.py†L19-L98】
- **Heat pump flow‑temperature model**
  - Base flow temperature derived by linear interpolation between 70 °C at SAP 40 and 45 °C at SAP 80, then adjusted +5 K for uninsulated walls and +3 K for single glazing. Flow temperature is clipped to 45–80 °C and mapped to emitter‑upgrade tiers with corresponding cost placeholders (£0/£1500/£3500/£6000).【F:src/analysis/methodological_adjustments.py†L101-L168】【F:src/analysis/methodological_adjustments.py†L31-L37】
- **Measurement uncertainty (Crawley et al., 2019)**
  - SAP uncertainty bands: ±2.4 (SAP≥85), ±4.0 (70–84), ±6.0 (55–69), ±8.0 (<55). 95% confidence interval for mean computed as 1.96·(mean uncertainty)/√n.【F:src/analysis/methodological_adjustments.py†L171-L219】
- **Demand uncertainty wrapper**
  - Default bounds ±20% (±30% for anomaly flags) applied multiplicatively to demand, bill savings, and CO₂ savings; derived payback bounds use capex divided by low/high bill savings.【F:src/analysis/methodological_adjustments.py†L320-L373】

## Scenario Modeling (`ScenarioModeler` / `run_ade_analysis` backbone)
- **Capital cost build‑ups (per property)**
  - Loft top‑up: loft area = 0.9·floor area; cost = loft area·`loft_insulation_per_m2`; saving = 15% of absolute energy use.
  - Wall insulation: cavity cost uses lump sum `cavity_wall_insulation` with 20% saving; solid walls assume wall area = 1.5·floor area, cost = wall area·`internal_wall_insulation_per_m2`, saving = 30%.
  - Double glazing: window area = 0.2·floor area; cost = window area·`double_glazing_per_m2`; saving = 10% of absolute energy use.
  - ASHP installation: capex adds `ashp_installation`; heating demand assumed 80% of total absolute energy; gas saved equals heating demand; electricity use = heating demand / SCOP; net energy reduction = gas saved − electricity use.
  - Emitter upgrades: radiator count = floor area / 15; cost = radiators·`emitter_upgrade_per_radiator`.
  - District heating: capex adds `district_heating_connection`; energy reduction = 15% of absolute energy use.
  - Fabric improvement bundles combine loft, wall, and glazing costs above with a 40% energy‑reduction lump sum.
  - All formulas computed inside `_calculate_property_upgrade_worker`.【F:src/modeling/scenario_model.py†L42-L116】
- **Energy/CO₂/bill impact translations**
  - Annual CO₂ reduction = energy reduction · current gas carbon factor (0.183 kgCO₂/kWh).【F:src/modeling/scenario_model.py†L117-L118】【F:config/config.yaml†L236-L238】
  - Annual bill savings = energy reduction · current gas unit price (£0.0624/kWh).【F:src/modeling/scenario_model.py†L120-L121】【F:config/config.yaml†L219-L223】
- **EPC uplift estimation**
  - Improvement points = (energy reduction ÷ floor area) · 0.5; added to current SAP score, capped at 100; mapped to bands A–G using SAP thresholds (A≥92, B≥81, C≥69, D≥55, E≥39, F≥21, else G).【F:src/modeling/scenario_model.py†L123-L141】
- **Payback computation**
  - Simple payback = capital_cost ÷ bill_savings; set to ∞ if savings ≤0, NaN, or bill_savings missing; 0 if capex ≤0.【F:src/modeling/scenario_model.py†L143-L151】

## Retrofit Package Analysis
- **Measure‑level parameters**
  - Default capex (e.g., loft £800, solid‑wall EWI £12,000, triple glazing £9,000, draught proofing £500, radiator upsizing £2,500) and fractional heat‑demand savings (e.g., loft 15%, solid wall 35%, double glazing 10%, triple glazing 15%, draught proofing 5%). Flow‑temperature reductions per measure (e.g., radiator upsizing −10 K).【F:src/analysis/retrofit_packages.py†L59-L219】
- **Package aggregation logic**
  - Total capital cost = sum of applicable measure capex. Total heat‑demand saving uses a diminishing‑returns multiplicative model: starting from remaining_demand=1, each measure multiplies remaining_demand by (1−saving_pct); total saving = 1−remaining_demand. Flow‑temperature reductions sum arithmetically.【F:src/analysis/retrofit_packages.py†L385-L425】
- **Baseline energy & conversions**
  - Annual heat demand = `ENERGY_CONSUMPTION_CURRENT` (kWh/m²/yr) · `TOTAL_FLOOR_AREA`; bill savings = annual_kwh_saving · gas price (default £0.0624/kWh); CO₂ saving (tonnes) = annual_kwh_saving · gas carbon factor / 1000.【F:src/analysis/retrofit_packages.py†L400-L430】【F:config/config.yaml†L219-L223】【F:config/config.yaml†L236-L238】
- **Payback metrics**
  - Simple payback = total_capex ÷ annual_bill_saving (∞ if savings ≤0). Discounted payback iteratively discounts annual savings by (1+discount_rate)^year until cumulative savings exceed capex, up to 50 years (∞ otherwise). Discount rate defaults to 3.5% from config financial block.【F:src/analysis/retrofit_packages.py†L431-L455】【F:src/analysis/retrofit_packages.py†L503-L522】【F:config/config.yaml†L265-L269】

## Validation/Usage Notes
- All financial, carbon, and tariff inputs trace back to cited regulatory sources (Ofgem, DESNZ, HM Treasury) via `config/config.yaml`; any variation in `run_ade_analysis` scenarios should reference the same config block for reproducibility.
- Methodological adjustments explicitly document academic sources (Few et al., 2023; Crawley et al., 2019) and implement deterministic formulas that can be re‑computed from EPC fields.
- Payback and savings calculations consistently apply current gas price and carbon factor unless scenario overrides are supplied in the calling pipeline, ensuring a single point of truth for secondary datapoints.
