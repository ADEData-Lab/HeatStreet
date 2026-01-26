# Heat Street EPC Analysis — Methodology (Policy Audience, Detailed)

This methodology describes the full Heat Street analytical pipeline used to quantify low‑carbon heating potential for **London’s Edwardian terraced housing** using **EPC Register data** combined with **spatial heat network evidence** and a transparent set of externally‑sourced technical and economic parameters. It is written for a policy audience: detailed enough to understand what is being done and why, without requiring software or engineering expertise.

## 1) Purpose, scope, and what the model *is* (and is not)

### 1.1 Purpose
The Heat Street pipeline is designed to answer policy‑relevant questions such as:
- What is the current fabric and heating system baseline for Edwardian terraces in London?
- How “heat‑pump ready” is the stock today, and what enabling works are typically required?
- How do different decarbonisation pathways compare on **capital cost**, **bill impacts**, **energy demand reduction**, and **carbon savings**?
- Where might **heat networks** be a plausible alternative to individual heat pumps, based on spatial evidence of proximity, zoning, and local heat density?
- Where are there **diminishing returns** from sequential fabric measures (“tipping point”), and what is a pragmatic “sweet‑spot” fabric package?

### 1.2 Geographic and stock scope
The core case is:
- **Region:** London (33 local authorities)
- **Stock filter (“Edwardian terraces”):** EPC construction age bands consistent with **pre‑1930** plus **terraced built forms** (mid‑terrace / end‑terrace variants). Flats are excluded.
- **Certificate window:** the pipeline downloads certificates from a configurable start year (default used in the pipeline: **2015**), aiming to use comparatively recent EPCs.

### 1.3 What this analysis represents
This is a **stock model** built from administrative EPC records and a set of transparent assumptions.
- It does **not** replace a property‑by‑property survey, detailed heat‑loss calculations, or engineering design.
- It is most robust for **comparisons** and **orders of magnitude**: identifying which measures and pathways are directionally favourable, where barriers concentrate, and how spatial conditions change the pathway mix.

## 2) Data sources and inputs

The pipeline uses two kinds of inputs:
1) **Primary administrative data** (EPC Register)
2) **Secondary parameters** (costs, savings, carbon factors, etc.) and **spatial datasets** (heat networks and zones)

### 2.1 Primary dataset: UK EPC Register (domestic)
**Acquisition method**
- Data is downloaded programmatically from the UK EPC Register **domestic search API** as CSV, by London local authority code, using API pagination.

**Key EPC variables used**
The EPC Register contains many fields; Heat Street relies on a subset, grouped below by how they are used:

**A) Identification, timing, and location**
- `UPRN` (where present): used to deduplicate to the most recent certificate per dwelling
- `LODGEMENT_DATE` / `INSPECTION_DATE`: used for recency and trend charts (e.g., lodgements by year)
- `POSTCODE`: used to geocode approximate location for spatial analysis
- Local authority / borough fields: used to structure outputs and summaries

**B) Building typology (stock definition)**
- `CONSTRUCTION_AGE_BAND`: used to select pre‑1930 dwellings (Edwardian era proxy)
- `BUILT_FORM` and `PROPERTY_TYPE`: used to select terraced houses and exclude flats

**C) Fabric and systems descriptors (mostly free‑text)**
- `WALLS_DESCRIPTION` (or equivalent): used to classify wall type (solid/cavity etc.) and insulation status
- `ROOF_DESCRIPTION` and `ROOF_ENERGY_EFF`: used to infer loft insulation thickness and quality bands
- `FLOOR_DESCRIPTION` / floor indicators: used to infer floor insulation presence/absence
- Window/glazing descriptions and/or efficiency: used to classify single/double/triple glazing
- `MAINHEAT_DESCRIPTION`: used to classify heating system category (gas boiler vs communal/district etc.)
- Tenure (where present): used for tenure‑segmented summaries

**D) Performance metrics**
- `TOTAL_FLOOR_AREA` (m²): used for plausibility checking, scaling to annual kWh, and cost scaling rules
- `CURRENT_ENERGY_RATING` (A–G) and `CURRENT_ENERGY_EFFICIENCY` (SAP points): used for baseline, readiness thresholds, and policy‑relevant indicators (e.g., Band C or better)
- `ENERGY_CONSUMPTION_CURRENT`: treated as the EPC’s modelled energy intensity (kWh/m²/year), with validation to catch unit anomalies
- `CO2_EMISSIONS_CURRENT`: used to derive CO₂ intensity (kg/m²/year) and to cross‑check plausibility

**EPC Register fields used (reference list)**

The table below lists the core EPC fields used (directly or as the source for standardised categories). Field availability varies across certificates and assessment eras; where fields are missing, Heat Street either falls back to alternative fields (where possible) or excludes records (where critical).

| EPC field (standardised) | What it represents | How Heat Street uses it | Notes / caveats |
|---|---|---|---|
| `LMK_KEY` | Unique certificate identifier | Counts, deduplication fallback, traceability | EPC-level, not dwelling-level |
| `UPRN` | Unique Property Reference Number | Deduplicate to latest certificate per dwelling | Not always present |
| `ADDRESS`, `ADDRESS1–3` | Address strings | Case-street extracts; QA sampling | Not used for geocoding in this pipeline |
| `POSTCODE` | UK postcode | Geocoding to postcode centroid (spatial analysis) | Postcode centroid ≠ exact address location |
| `LATITUDE` / `LONGITUDE` (where present) | Coordinate fields | Optional QA; not relied on as the primary geocoding method | Current spatial workflow uses postcode centroids for consistency |
| `LOCAL_AUTHORITY` / `LOCAL_AUTHORITY_LABEL` / borough fields | Local authority identifiers | Borough summaries and reporting | Borough code vs label varies by extract |
| `LODGEMENT_DATE` / `INSPECTION_DATE` | Certificate dates | Recency filtering and lodgement trend charts | Dates reflect assessment activity, not retrofit timing |
| `TRANSACTION_TYPE` | EPC transaction context | Optional segmentation / interpretation | Not used as a core filter |
| `PROPERTY_TYPE` | Dwelling type (house/flat etc.) | Exclude flats; stock definition | EPC categories are assessor-entered |
| `BUILT_FORM` | Built form (mid-terrace etc.) | Terraced stock definition | Misclassification can leak non-target homes in/out |
| `CONSTRUCTION_AGE_BAND` | Construction period band | Pre‑1930 filter (Edwardian proxy) | Banding is coarse and sometimes uncertain |
| `TOTAL_FLOOR_AREA` (m²) | Floor area | Plausibility filters; annual kWh scaling; cost scaling | Floor area can contain entry errors; bounded in QA |
| `NUMBER_HABITABLE_ROOMS` | Habitable rooms count | Optional QA/sanity checks | Not required for core modelling |
| `CURRENT_ENERGY_RATING` (A–G) | EPC band | Baseline descriptors; readiness thresholds; prebound/rebound factors | Band is a model output |
| `CURRENT_ENERGY_EFFICIENCY` (SAP) | SAP score (0–100) | Flow temperature proxy; band shift calculations | SAP is a model output |
| `ENERGY_CONSUMPTION_CURRENT` (kWh/m²/yr) | Modelled energy intensity | Baseline demand proxy; spatial heat density; scenario baseline | Modelled (not metered) energy |
| `CO2_EMISSIONS_CURRENT` | Modelled CO₂ emissions (typically tonnes/year in EPC data) | QA cross-checks; descriptive summaries | Normalised internally for intensity metrics |
| `WALLS_DESCRIPTION` | Wall description (free-text) | Rule-based parsing: wall type + insulation status | Free-text can be inconsistent |
| `WALLS_ENERGY_EFF` | Wall “energy efficiency” label | Secondary indicator for wall quality | Coarse ordinal descriptor |
| `ROOF_DESCRIPTION` | Roof/loft description (free-text) | Loft thickness inference; loft category + confidence | Extracts mm values where present |
| `ROOF_ENERGY_EFF` | Roof “energy efficiency” label | Loft quality bands where thickness absent | Used as medium-confidence proxy |
| `FLOOR_DESCRIPTION` / `FLOOR_ENERGY_EFF` | Floor descriptors | Floor insulation status (proxy) | Often missing / low detail |
| `WINDOWS_DESCRIPTION` / `WINDOWS_ENERGY_EFF` | Window descriptors | Glazing type (single/double/triple/mixed) | Wording varies across EPC eras |
| `MAINHEAT_DESCRIPTION` / `MAINHEAT_ENERGY_EFF` | Primary heating system | Heating system type (gas vs communal etc.) | Used to identify communal/district cases |
| `MAINHEAT_CONT_DESCRIPTION` | Heating controls | Presence of TRVs, programmers, smart controls (proxy) | Completeness varies |
| `HOTWATER_DESCRIPTION` / `HOTWATER_ENERGY_EFF` | Hot water system | Hot water type segmentation (proxy) | Completeness varies |

### 2.2 Secondary parameters (economic and technical)
Many values needed for policy assessment are not contained in EPC certificates (e.g., retrofit costs, energy price scenarios). In Heat Street these are:
- **Centralised in `config/config.yaml`** and treated as the single “source of truth”
- Documented with an embedded evidence base under `authoritative_sources` in the same file

The parameters fall into these categories:
- **Energy prices** (gas, electricity, heat network tariff) used for bill impact calculations
- **Carbon factors** (gas and electricity, plus an assumed heat network carbon intensity)
- **Retrofit measure costs** (loft top‑up, cavity/solid wall insulation, glazing, heat pump install, emitters, connection costs, electrical upgrades)
- **Energy savings assumptions** (percent demand reduction per measure, plus flow‑temperature reductions that influence heat pump performance)
- **Financial assumptions** (discount rate; analysis horizon; cost‑effectiveness thresholds)
- **Methodological adjustments** (performance gap / prebound effect and uncertainty variants)
- **Heat network tier thresholds** (distance to network, heat density thresholds, zone readiness)

**What counts as a “secondary parameter” (and where it comes from)**

Heat Street treats parameters as policy‑facing inputs that should be reviewable and updateable without changing code. The table below summarises the main parameter families and their evidence types. (Full values and links live in the `authoritative_sources` block in `config/config.yaml`.)

| Parameter family | Examples (not exhaustive) | Typical evidence base used | Why it matters |
|---|---|---|---|
| Energy prices | Gas/electricity unit rates; heat network tariffs; price scenarios | UK regulator and government projections (e.g., Ofgem; DESNZ), plus plausible ranges | Determines bill impacts and payback periods |
| Carbon factors | Gas and grid electricity kgCO₂/kWh; grid decarbonisation trajectories | DESNZ conversion factors; National Grid ESO / system scenario projections | Determines carbon savings and abatement costs |
| Measure costs | Loft/wall/glazing costs; heat pump install; heat network connection | Public guidance (Energy Saving Trust), scheme benchmarks (e.g., BUS), industry quotes | Drives CAPEX totals and cost-effectiveness |
| Measure savings | % heating demand reduction; flow temperature reductions | Evidence synthesis; trials; engineering judgement bounded by literature | Drives energy savings and heat pump COP changes |
| Heat pump performance | COP vs flow temperature curve; SCOP; heating fraction | Trials/field evidence (e.g., Electrification of Heat), reviewed ranges | Converts heat demand to electricity demand and bills |
| Financial parameters | Discount rate; analysis horizon; payback thresholds | HM Treasury Green Book; policy appraisal practice | Aligns outputs with policy evaluation norms |
| Heat network screening thresholds | Tier distances; minimum density thresholds; distribution efficiency; carbon intensity | Government guidance and zoning methods; academic DH studies | Screens where HN is plausible vs HP |
| Uncertainty parameters | Demand error bounds; sensitivity variants | Literature on EPC uncertainty and performance gap | Prevents over-precision and supports sensitivity ranges |

### 2.3 Spatial datasets (heat networks and zones)
Spatial analysis combines EPC‑derived property locations (postcode centroid) with:
- **BEIS/DESNZ Heat Network Planning Database (HNPD)** (January 2024 release): points for operational/under‑construction and planned networks with permission
- **London Datastore Heat Map GIS layers (legacy, ~2012)** used as a fallback and for some supporting layers
- **Heat network zone polygons** (where available): borough heat priority areas / potential network zones

## 3) Pipeline structure: modules and what each does

The pipeline is structured into phases. Each phase is designed to be auditable: it logs key metrics and writes outputs to disk so results can be inspected and reproduced.

### Phase 1 — Data acquisition (EPC + optional spatial inputs)
**Objective:** obtain a consistent EPC dataset for the target stock, plus any supporting spatial layers.

**How it works**
- EPC data is downloaded borough‑by‑borough via the EPC Register API, using pagination (`search-after`).
- A stock filter is applied to keep only pre‑1930 terraced houses (Edwardian proxy), based on EPC age bands and built form.
- Raw and filtered datasets are saved to `data/raw/`.

**Key assumptions / implications**
- EPC age bands are treated as the authoritative indicator for build period; mis‑classification in EPCs can propagate into the stock definition.
- Using a start year (default 2015) improves comparability but can bias toward more recently assessed homes.

### Phase 2 — Data validation and cleaning
**Objective:** address known issues in EPC data quality so that subsequent calculations are mathematically sound and policy‑relevant.

**Why this matters**
Academic evidence suggests EPCs can contain errors; Heat Street therefore includes explicit QA steps to reduce distortions in aggregate results.

**Main validation steps**
1) **Standardise column names:** EPC API fields are normalised to consistent uppercase with underscores (e.g., hyphens removed).
2) **Deduplicate:** where `UPRN` exists, keep the most recent certificate per UPRN; otherwise deduplicate by address proxy. This avoids over‑counting homes with multiple certificates.
3) **Floor area plausibility bounds:** remove implausible `TOTAL_FLOOR_AREA` values outside configured ranges.
4) **Critical field completeness:** enforce presence of required fields (postcode, built form, construction age band, energy rating, wall/heating descriptions, etc.).
5) **Negative/implausible energy/CO₂ values:** clamp small negative values to zero (to handle edge cases such as onsite generation) and remove severely negative values (likely data errors).
6) **Consistency checks:** flag illogical insulation strings (e.g., “cavity filled” on a “solid wall” description) for awareness.

**Standardisation (turning free‑text into usable categories)**
The pipeline converts EPC descriptive fields into consistent categorical variables:
- Wall type and insulation status (solid brick / cavity / etc.; insulated vs not; internal/external/cavity filled)
- Loft/roof insulation thickness bands (where mm values are present) or quality bands (where only “Good/Poor” is given)
- Glazing type (single/double/triple/mixed)
- Heating system type (gas boiler vs communal/district/other)
- Ventilation type (coarse categories)
- Tenure (where present)

**Memory efficiency trade‑off**
To enable large‑N processing on typical machines, many high‑cardinality string fields are converted to categorical data types. This reduces memory footprint substantially, at the cost of making ad‑hoc string operations slightly less convenient downstream (a deliberate engineering trade‑off to keep the model runnable).

### Phase 2.5 — Methodological adjustments (evidence‑based corrections and uncertainty)
**Objective:** improve realism and avoid over‑claiming by adjusting EPC‑modelled baselines and representing uncertainty.

This phase applies three main adjustments:

1) **Performance gap / prebound effect (baseline correction)**
- EPCs can systematically over‑predict actual metered energy use, especially for low‑rated homes (which may under‑heat for affordability).
- Heat Street applies band‑specific “performance gap factors” to adjust the baseline demand.
- The pipeline retains central and sensitivity variants (e.g., low/high) to support uncertainty ranges.

2) **Rebound / comfort‑taking (savings realism)**
- For poorly performing homes, some theoretical savings may be “taken back” as improved comfort rather than reduced energy use.
- Heat Street applies a rebound factor (by EPC band) to reduce realised energy savings where appropriate.

3) **Heat pump flow temperature and COP linkage**
- Heat pump efficiency depends on operating temperatures. The pipeline estimates required flow temperature using SAP as a proxy for fabric quality, then maps flow temperature to heat‑pump COP using a configured COP curve (central/low/high).
- Fabric measures and emitter upgrades reduce the estimated flow temperature requirement, improving COP.

### Phase 3 — Archetype characterisation (baseline descriptive statistics)
**Objective:** describe the current state of the stock in a way that is meaningful for policy and programme design.

The archetype module produces distributions and summary statistics for:
- EPC bands and SAP scores
- Wall types and insulation rates
- Loft insulation thickness/quality (with “confidence tier” where thickness is inferred)
- Floor insulation and glazing types
- Heating system types and basic controls indicators
- Energy intensity (kWh/m²/year) and CO₂ intensity (kg/m²/year)

This phase is descriptive rather than intervention modelling: it provides the baseline “starting point” and identifies where barriers are concentrated (e.g., prevalence of solid walls).

**Supporting module: detailed fabric tables and anomaly flags**
Alongside the archetype summaries, the pipeline can generate “report‑ready” fabric breakdown tables and anomaly flags that help interpret EPC quality and target interventions:
- **Fabric breakdown tables:** distributions of wall type/insulation status, loft insulation thickness bands, glazing type, ventilation, and cross‑tabs (e.g., wall type × insulation status).
- **Tenure segmentation:** where tenure is present, the same breakdowns are produced by tenure group.
- **Anomaly flags:** properties can be flagged where EPC ratings appear inconsistent with fabric indicators (e.g., a comparatively good EPC band but very weak fabric descriptors), signalling higher uncertainty and a need for caution in interpreting that subset.

### Phase 4 — Scenario modelling (policy “what‑if” cases)
**Objective:** model full‑deployment scenarios consistently across the stock and compare their implications.

**Scenario definition**
Scenarios are defined in config and generally assume **full deployment** (100% uptake) unless explicitly stated otherwise. This is deliberate: it allows clean “like‑for‑like” comparisons between pathways as upper‑bound system needs (policy can then layer on realistic uptake separately).

**Key calculated outputs per scenario**
For each property (and then aggregated), the model estimates:
- Capital expenditure (CAPEX), including enabling works where applicable
- Post‑intervention energy use (kWh/year) and reduction from baseline
- Bill impacts using energy prices
- CO₂ impacts using carbon factors
- Simple and discounted payback indicators
- Cost per tonne CO₂ abated (over the analysis horizon)
- EPC band shifts (with guardrails to prevent implausible leaps)

**Core modelling logic**
1) Select a baseline energy intensity (prioritising adjusted baselines where available).
2) Convert to annual kWh using floor area.
3) Apply fabric measures as **multiplicative** reductions in heating demand (reflecting diminishing returns as each subsequent measure acts on a reduced baseline).
4) Apply rebound/comfort factors to realised savings (where configured).
5) For heat pumps: convert heating demand to electricity demand using COP (and keep non‑heating energy on its baseline fuel using a configured “heating fraction” split).
6) For heat networks: apply distribution efficiency losses and an assumed tariff and carbon intensity.

**Costing approach**
Costs come from `config.yaml` and are applied using a common costing engine:
- Some measures are treated as **fixed per dwelling** costs
- Some costs scale with **floor area** or “units per dwelling” (e.g., radiators per 15m²)
- Caps and minimums prevent outlier properties generating implausible costs
- A size‑adjustment factor scales fixed costs for very small or very large homes (a pragmatic correction for stock heterogeneity)

**Supporting module: retrofit measures and packages**
To make the modelling transparent and modular, Heat Street defines an explicit catalogue of measures (capex + savings + applicability notes) and groups them into named packages (e.g., “loft only”, “walls + emitters”, “max retrofit”). For each package, the pipeline can compute:
- Total capex (with the same cost rules used elsewhere)
- Total energy savings using the same sequential “diminishing returns” approach
- Simple and discounted payback indicators
- Comparison of window upgrade options (double vs triple glazing) including marginal benefit

**Supporting module: fabric “tipping point” analysis (diminishing returns curve)**
The pipeline includes a dedicated tipping point analysis to identify a pragmatic stopping point for sequential fabric measures:
- Measures are ordered using a greedy “best kWh saved per £ on the remaining demand” approach (so later measures naturally have smaller marginal impact).
- At each step, the model records marginal kWh saved, marginal capex, and marginal cost‑effectiveness.
- A simple, transparent tipping‑point heuristic is used: the point at which marginal cost per kWh saved exceeds **2×** the minimum observed marginal cost.
- The resulting curve supports a “fabric bundle to tipping point” scenario: a policy‑relevant package that prioritises high‑value measures before expensive, low‑return steps.

**Supporting module: load profiles and system impacts (peak vs average demand)**
For system planning conversations (networks and electricity distribution), the pipeline can translate annual demand into stylised profiles:
- A representative winter‑day hourly shape (morning/evening peaks) and a seasonal daily profile (winter‑dominated) are used to estimate **peak kW per dwelling** and **peak‑to‑average** ratios.
- For heat pumps, thermal demand is converted to electrical demand using SCOP/COP assumptions.
- For streets (multiple homes), a diversity factor reduces coincident peak to reflect that not all homes peak simultaneously.

**Supporting module: sensitivity analysis (uptake, penetration, and price conditions)**
Because policy rarely delivers 100% uptake instantly, the pipeline includes sensitivity tools to explore:
- Subsidy/uptake sensitivity (how uptake might respond to subsidy levels)
- Heat network penetration and price sensitivity (how outcomes change under different assumed HN shares and energy price conditions)

#### Subsidy sensitivity (Section 9)
**Objective:** explore how capital subsidies can change payback, uptake, and public expenditure under consistent assumptions.

The subsidy sensitivity module is run **per pathway** (e.g., `heat_pump`, `hybrid`, `heat_network`) and iterates over a configured set of subsidy levels
(default 0%, 25%, 50%, 75%, 100% of modeled capital cost). For each pathway and subsidy level, the pipeline:
1) Applies the subsidy to the pathway's modeled capital cost.
2) Recalculates simple payback using the pathway's modeled annual bill savings.
3) Maps payback to an *illustrative uptake rate* using a smooth logistic adoption curve (a floor captures early adopters; a ceiling captures practical saturation).
4) Converts uptake into upgraded properties and public expenditure, and computes an implied public cost per tonne of CO2 abated over the analysis horizon.

Interpretation guidance:
- This is a sensitivity tool, not a forecast. It does not model delivery capacity, consumer confidence, finance availability, planning constraints, or installer supply.
- Uptake is driven by a single payback value per pathway in this simplified model, so it should be treated as a policy-facing proxy for relative responsiveness.
- Results are best used to compare pathways and to identify where subsidy changes materially affect outcomes (e.g., diminishing returns at higher subsidy levels).

Outputs:
- A consolidated table is exported to `data/outputs/subsidy_sensitivity_analysis.csv` and embedded in the one-stop JSON (Section 9) for the HTML dashboard.

### Phase 4.3 — Retrofit readiness analysis (heat pump readiness tiers)
**Objective:** classify homes into **readiness tiers** and identify typical prerequisites and costs to reach “heat‑pump ready”.

The readiness module:
- Computes baseline heat demand intensity (kWh/m²/year)
- Flags barriers (e.g., loft insulation below threshold; walls uninsulated; glazing issues)
- Estimates post‑fabric heat demand
- Estimates flow temperature and therefore likely heat pump performance
- Classifies each dwelling into a tier (Tier 1 “ready now” through Tier 5 “major intervention needed”) using a documented deficiency score approach
- Estimates prerequisite costs and total retrofit costs using the shared costing rules

Policy interpretation guidance:
- “Ready now” does not mean “install‑ready”: practical delivery still requires property‑specific checks (emitters, electrics, hot water cylinder, constraints).
- “Not suitable for standard HP” means “requires major enabling works or alternative pathway”, not “impossible”.

### Phase 4.5 — Spatial analysis (optional; requires GIS libraries)
**Objective:** determine where heat networks are plausible alternatives to individual heat pumps, based on spatial evidence.

Spatial analysis is optional because it requires geospatial dependencies (GDAL/geopandas). When available, it:
1) Geocodes EPC postcodes to approximate points (postcode centroid)
2) Overlays these points with heat network datasets and zone polygons
3) Computes proximity and local heat density to assign “heat network tiers”
4) Writes `hn_ready`, `tier_number`, and distance/zone indicators back onto the property dataset for hybrid pathway allocation

See Section 5 for detail (methods + trade‑offs).

### Phase 5 — Reporting and outputs
Outputs are written to `data/outputs/` and include:
- Consolidated JSON “one‑stop” output (for report generation and audit)
- Analysis logs with timings and key metrics
- Tables and figures for the report and dashboard
- A dashboard‑ready JSON payload that consolidates key results into an interactive schema (for exploration and QA)

For auditability, intermediate outputs can be **archived per run** to `data/outputs/bin/run_<timestamp>/` rather than deleted.

## 4) Key formulas (explained)

This section summarises the “core maths” used across modules. The exact parameter values (costs, factors, thresholds) are configured in `config/config.yaml` with an embedded evidence base.

### 4.1 Converting EPC energy intensity to annual demand
EPC supplies an energy intensity measure (typically kWh/m²/year). Heat Street converts to an annualised demand:

`Annual energy (kWh/year) = Energy intensity (kWh/m²/year) × Floor area (m²)`

This is used as a consistent baseline for bills, carbon, and savings calculations.

### 4.2 Sequential fabric savings (diminishing returns)
Fabric measures are applied sequentially as multiplicative reductions:

`Remaining demand = Remaining demand × (1 − saving_pct)`

This avoids the common error of adding percentages (which can over‑state savings when combining measures).

### 4.3 Rebound / comfort‑taking adjustment
To reflect that some “theoretical” savings may appear as comfort rather than reduced fuel use, the model scales realised fabric savings by a rebound factor (higher rebound in poorer homes):

`Realised savings = Modelled savings × rebound_factor`

### 4.4 Bills and carbon
Bills are calculated using current fuel prices and the post‑intervention energy use on each fuel:

`Bill = (Gas kWh × gas_price) + (Electricity kWh × electricity_price) + (Heat network input kWh × heat_network_tariff)`

Carbon is similarly:

`CO₂ = Σ(fuel_kWh × fuel_carbon_factor)`

Heat networks include a distribution efficiency term (losses):

`Heat network input = Delivered heat / distribution_efficiency`

### 4.5 Payback and cost‑effectiveness
The model reports:
- **Simple payback:** `capex / annual_bill_saving` (if savings are positive)
- **Discounted payback:** the year when cumulative discounted savings exceed CAPEX, using the configured discount rate (Green Book‑aligned)
- **Cost per tonne CO₂ abated:** `capex / (annual_co2_saving_tonnes × years)` over the analysis horizon

These indicators are used to classify upgrades into cost‑effective / marginal / not cost‑effective tiers (policy‑useful rather than purely financial investor metrics).

### 4.6 Heat pump performance (flow temperature → COP)
Heat pumps are more efficient at lower flow temperatures. The pipeline:
1) Estimates an operating flow temperature (from SAP proxy and measure‑driven reductions)
2) Interpolates a COP from a configured COP curve (central and uncertainty bounds)
3) Converts heating demand to electrical demand:

`Heat pump electricity (kWh) = Heating demand after fabric (kWh) / COP`

### 4.7 Heating vs “non‑heating” energy split (simplified operational accounting)
EPC metrics do not provide a full metered split of end uses. For policy‑level comparability, Heat Street uses a simple split:
- A configured **heating fraction** represents the share of baseline annual demand that is treated as space/water heating and therefore switches fuel under a heat pump or heat network pathway.
- The remaining share is treated as **non‑heating demand** and is left on the baseline fuel in the scenario accounting.

This is a pragmatic modelling choice to avoid false precision when EPC fields do not support a detailed end‑use model. It is explicitly surfaced as a limitation (Section 8.5).

### 4.8 EPC band shifts (how “post‑retrofit EPC” is approximated)
To report EPC band shifts consistently across scenarios, Heat Street approximates changes in SAP score from the percentage energy reduction:
- First, percent savings are computed from baseline vs post‑measure kWh.
- Then SAP gains are estimated using a **diminishing‑returns** mapping (large savings yield progressively smaller incremental SAP gains), reflecting that SAP does not move linearly with energy demand.
- The post‑retrofit SAP score is converted back to an EPC band using standard SAP→band thresholds.

**Guardrails** are applied to avoid implausible leaps driven by simplified assumptions:
- Maximum improvement per intervention is capped (e.g., no more than two bands in one “step”).
- A “Band A” guardrail flags results where an implausibly large share of the stock reaches Band A, prompting review of assumptions rather than silently accepting unrealistic outputs.

## 5) Spatial analysis methodology (heat networks)

Spatial analysis determines where district heating is potentially viable and therefore where a **hybrid pathway** (HN in viable areas, HP elsewhere) is plausible.

### 5.1 Geocoding: postcode → point
**Input:** EPC `POSTCODE` values.

**Method:** postcode centroids are obtained via a UK postcode geocoding service (with caching and rate limiting).
- Only postcodes (not full addresses) are geocoded.
- Results are cached to reduce repeated API calls across runs.

**Limitation:** postcode centroids are approximate; they are suitable for neighbourhood‑scale heat density and proximity screening, but not for detailed street‑works engineering design.

### 5.2 Coordinate system for distance and area
For reliable distance calculations, geometries are converted to **British National Grid (EPSG:27700)**. Distances in this CRS are measured in meters.

### 5.3 Heat network “tiers”: what they mean
The pipeline assigns each dwelling a heat network tier, reflecting increasing uncertainty and infrastructure requirements:

- **Tier 1:** within a configured distance (default 250m) of an existing network (highest confidence)
- **Tier 2:** *planned network indicator* — either inside a zone/priority polygon layer (if available) **or** within a configured buffer of an HNPD planned scheme point (proxy)
- **Tier 3:** high local heat density (≥ threshold, default 20 GWh/km²) indicating plausible economic viability *if* networks are built and anchor loads exist
- **Tier 4:** moderate density (between Tier 4 threshold and Tier 3 threshold) — borderline cases that may require subsidy, anchor loads, or high uptake
- **Tier 5:** low density — heat networks are unlikely to be economic, so heat pumps are usually preferred

Policy interpretation guidance:
- This is a **screening** tool, not a definitive network feasibility study.
- “Viable” here means “potentially viable under favourable delivery conditions”, not guaranteed deployment.

### 5.4 Heat density calculation (grid method)
Heat density is calculated as local annual heat demand per unit area (GWh/km²). To scale to large datasets, Heat Street uses a **grid aggregation approach**:

1) Convert each property’s annual demand to an absolute annual kWh (using floor area).
2) Assign each property point to a grid cell (cell size configured, default 125m).
3) Aggregate kWh per grid cell.
4) For each cell, sum energy in neighbouring cells whose centres fall within a radius (default 250m) to approximate a circular neighbourhood.
5) Convert to heat density:

`Heat density (GWh/km²) = (Neighbourhood energy_kWh / 1,000,000) / (π × r² / 1,000,000)`

This yields a neighbourhood‑scale density aligned with how heat networks are commonly screened in zoning and strategic studies.

### 5.5 Proximity and zone overlays (performance optimisations)
To make spatial analysis practical on typical machines:
- Spatial joins are **pre‑filtered** with bounding boxes before running polygon containment checks.
- Distances to networks are computed using **vectorised** geometry operations rather than per‑row loops.
- Large intermediate joins are avoided where possible (e.g., using `map` operations instead of full DataFrame joins).

### 5.6 Heat network readiness flag used by pathway allocation
A boolean readiness flag (`hn_ready`) is derived deterministically using configured rules, typically treating a property as “HN‑ready” if it meets any of:
- Tier number ≤ 3 (Tier 1–3)
- Distance to existing network ≤ 250m
- Heat density ≥ configured threshold
- Inside a heat network zone polygon (if enabled)
- Inside a planned-network indicator area (zone polygon if available; otherwise the HNPD buffer proxy)

This is used to allocate properties to heat networks in the hybrid scenario.

## 6) Computational approach and memory/performance trade‑offs

The pipeline is designed to be runnable on standard analyst machines while handling large datasets.

Key strategies include:

### 6.1 Chunking and parallelism where safe
- Borough downloads can run in parallel threads (bounded workers).
- Independent archetype statistics can run in parallel.
- Scenario modelling uses multiprocessing with a worker initializer to avoid repeatedly copying large configuration objects.
- Chunk size and worker counts are configurable (e.g., via environment variables) to suit different machines and dataset sizes.

### 6.2 Avoiding unnecessary copies
Large DataFrames can easily exceed memory if repeatedly copied. The pipeline uses:
- In‑place operations where safe
- Mapping operations rather than full joins for adding columns
- Explicit garbage collection after memory‑intensive phases

### 6.3 Data type optimisation
For large‑N string columns (EPC bands, age bands, categories), converting to categorical types materially reduces memory use.

### 6.4 Output formats and audit trail
CSV is always written (max compatibility). Parquet is written where possible (faster reload, smaller size), with controlled type conversions to maintain compatibility.

### 6.5 Spatial method selection
The spatial module supports two methods for heat density:
- **Grid method (default):** scalable and memory‑efficient
- **Buffer‑per‑property method:** conceptually straightforward but computationally expensive and memory‑intensive for large datasets

## 7) Outputs, auditability, and transparency

The pipeline produces:
- A consolidated “one‑stop” JSON output for reporting
- A structured analysis log (phase timings, key metrics, output paths)
- Supporting CSV/Parquet tables and figures for the report and dashboard

To support QA and reproducibility:
- The evidence base for assumptions is embedded in `config/config.yaml` (`authoritative_sources`)
- The one‑stop JSON is designed to be self‑describing: datapoints can include definitions, denominators, and provenance (which upstream output/file produced them)
- Outputs can be archived per run to a timestamped folder

## 8) Limitations (what to be cautious about)

This model is designed for policy‑level insight, but it has important limitations:

### 8.1 EPCs are modelled, not metered
EPC energy and emissions are model outputs, not measured consumption. The pipeline applies evidence‑based corrections (prebound, rebound) but cannot fully eliminate uncertainty.

### 8.2 Fabric and system descriptors are imperfect proxies
Many key indicators (wall type, insulation, glazing) come from EPC assessor descriptions. Parsing and classification can misinterpret unusual wording or incomplete assessments.

### 8.3 Costs are indicative and context‑dependent
Cost assumptions are drawn from reputable sources and bounded with caps, but real costs vary by:
- London labour and access constraints
- Conservation area requirements
- Supply chain conditions and programme scale

### 8.4 Heat network “viability” is screening‑level
Heat network tiers use proximity, zones, and heat density. Real deployment depends on:
- Anchor loads, rights‑of‑way, street works constraints
- Business models and regulation
- Local authority leadership and funding
- Network carbon intensity over time
- Upstream network CAPEX and phasing (dwelling “connection costs” do not represent full network build costs)

### 8.5 Simplified operational modelling
The model estimates bills and carbon using average prices and carbon factors and simplified splits of heating vs non‑heating energy. It does not model:
- Hour‑by‑hour weather variation for COP
- Network hydraulic constraints
- Electrical network reinforcement requirements
- Behavioural uptake dynamics (beyond sensitivity runs)

### 8.6 Sampling and representativeness
EPCs are an administrative dataset, not a random sample of homes. Coverage is influenced by market activity (sales/lettings), compliance regimes, and assessment practices. Heat Street mitigates some issues (deduplication, recency filters) but policymakers should treat results as:
- Strongest for **relative comparisons** and identifying “where barriers concentrate”
- Weaker for precise estimates of absolute totals if EPC coverage is uneven by tenure, geography, or building condition

### 8.7 Spatial precision and privacy
Spatial analysis is conducted at postcode‑centroid resolution to protect privacy and because EPC address geocoding is not consistently reliable at scale. This supports neighbourhood‑scale screening but is not suitable for detailed engineering design or street‑works planning without local validation.

## 9) Strengths (why this is still useful for policy)

Despite the limitations, the pipeline has important strengths:
- **Scale:** uses a large administrative dataset covering the target stock across London
- **Consistency:** applies one coherent set of assumptions across scenarios for clean comparison
- **Transparency:** assumptions are centralised and auditable; outputs are logged and reproducible
- **Policy relevance:** produces readiness tiers, cost‑effectiveness bands, pathway comparisons, and spatially‑aware hybrid allocations
- **Practicality:** designed to run on typical analyst hardware with explicit performance trade‑offs
- **Iterability:** parameter values are externalised (with evidence) so scenarios can be updated as prices, policy, or technology change

---

## Appendix A — Where parameters and evidence are stored

For exact parameter values and the supporting evidence base, see:
- `config/config.yaml` (especially the `authoritative_sources` block)
- `FORMULA_AUDIT.md` and `CALCULATION_FORMULAS_AUDIT.md` (full audit narratives)

## Appendix B — Implementation modules (for audit trail)

The analysis is implemented across these high‑level modules. This appendix is primarily for auditability (so an analyst can trace “what produced what”), but the descriptions are written in plain language.

**Orchestration and logging**
- Pipeline orchestrator: `run_analysis.py` (end‑to‑end run order; optional “one‑stop only” mode; archiving/cleanup)
- Run metadata: `src/utils/run_metadata.py` (provenance: run time, config snapshot, environment hints)
- Analysis log: `src/utils/analysis_logger.py` (phase timings, metrics, and output artefact registry)

**Acquisition**
- EPC download: `src/acquisition/epc_api_downloader.py` (EPC API queries by borough; pagination; stock filters; raw outputs)
- Heat network planning data: `src/acquisition/hnpd_downloader.py` (downloads and filters HNPD)
- London GIS layers: `src/acquisition/london_gis_downloader.py` (downloads and prepares London Datastore layers when used)

**Cleaning and validation**
- QA and standardisation: `src/cleaning/data_validator.py`
  - Duplicate handling and plausibility filters
  - Free‑text parsing into standard categories (walls/roof/glazing/heating)
  - Energy and CO₂ sanity checks (including negative value handling)
  - Memory optimisation (categorical dtypes)

**Core analysis (descriptive and diagnostic)**
- Archetype characterisation: `src/analysis/archetype_analysis.py` (baseline distributions of EPC bands, fabric, systems)
- Fabric breakdown tables: `src/analysis/fabric_analysis.py` (report-ready summaries and anomaly segmentation)
- Methodological adjustments: `src/analysis/methodological_adjustments.py` (prebound factors; rebound; flow temp & COP curve)
- Retrofit readiness tiers: `src/analysis/retrofit_readiness.py` (readiness tiering; prerequisites; indicative costs)
- Retrofit measures/packages: `src/analysis/retrofit_packages.py` (catalogue + packages; diminishing returns math)
- Fabric tipping point: `src/analysis/fabric_tipping_point.py` (sequential fabric curve; tipping heuristic; CSV output)
- Load profiles: `src/analysis/load_profiles.py` (stylised peak/average profiles for system planning discussion)
- Sensitivity tools: `src/analysis/penetration_sensitivity.py` (price × penetration grids for dashboard exploration)
- Additional reporting extracts: `src/analysis/additional_reports.py` (borough breakdown; case street extract; QA report)

**Modelling (interventions and scenarios)**
- Cost engine: `src/modeling/costing.py` (rule-based and scaled costing; caps; size adjustment)
- Scenario model: `src/modeling/scenario_model.py` (full-deployment scenario runs; chunking; payback/abatement; band shifts)
- Pathway model: `src/modeling/pathway_model.py` (pathway bundles; hybrid cost logic; HP vs HN comparators)
- Shared modelling utilities: `src/utils/modeling_utils.py` (baseline selection; diminishing returns; COP; payback; guardrails)

**Spatial**
- Postcode geocoding: `src/spatial/postcode_geocoder.py` (postcode → centroid; caching; rate limiting)
- Heat network tiers and heat density: `src/spatial/heat_network_analysis.py` (Tier 1–5 assignment; grid method; optional maps)

**Reporting and packaging**
- Figures and charts: `src/reporting/visualizations.py` (report figures including EPC lodgements and tipping point)
- One‑stop JSON report: `src/reporting/one_stop_report.py` (compiles outputs into `one_stop_output.json` with metadata)
- Output patching (QA alignment): `src/reporting/patch_one_stop_output.py` (post-processing for consistency where needed)
- HP vs HN comparison artefacts: `src/reporting/comparisons.py` (CSV + markdown snippet + optional plot)
- Dashboard packaging: `src/reporting/dashboard_data_builder.py` (dashboard-friendly exports)
- Executive summary helpers: `src/reporting/executive_summary.py`, `src/reporting/report_headline_data.py`
