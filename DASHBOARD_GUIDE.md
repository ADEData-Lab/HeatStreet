# Heat Street Dashboard Guide

## Recommended: one-stop HTML dashboard

Heat Street now ships a lightweight, self-contained HTML dashboard generated directly from the one-stop output:

- `data/outputs/one_stop_output.json` â€” authoritative consolidated output for reporting and QA
- `data/outputs/one_stop_dashboard.html` â€” opens in a browser and embeds the one-stop JSON (no extra data files required)

### Generate the dashboard

Run the pipeline (Conda recommended if you need the spatial module):

```bash
python run_analysis.py
```

### View the dashboard

- Open `data/outputs/one_stop_dashboard.html` (recommended)
- If you are iterating on the template `heat_street_dashboard.html`, open it and use the **Load JSON** button to select
  `data/outputs/one_stop_output.json`

### Dashboard tabs (one-stop)

- Overview
- Housing Stock
- Retrofit Readiness
- Scenario Comparison
- Subsidy Sensitivity

Notes:
- The one-stop dashboard intentionally avoids build tooling (no React/Vite) and uses Chart.js in-browser.
- All dashboard charts read from `one_stop_output.json` (embedded into `one_stop_dashboard.html` at generation time).

---

## 📊 Legacy: React dashboard (deprecated)

A legacy React dashboard exists in `dashboard/`. It is not required for the one-stop report outputs, and it is no longer the
recommended way to review results for this repo.

### Key Directories

- **`dashboard/`** – React application source, dev server, and production build system.
- **`data/outputs/dashboard/dashboard-data.json`** – Auto-generated dataset from the analysis pipeline (also copied to `dashboard/public/dashboard-data.json` for the UI).

## 🎯 Client Requirements Coverage

### ✅ All 12 Sections Fully Addressed

| Section | Requirement | Dashboard Implementation |
|---------|-------------|-------------------------|
| **§1** | Fabric Detail Granularity | Wall types, insulation status, roof thickness, glazing, ventilation with full distributions |
| **§2** | Retrofit Measures & Packages | 15+ measures catalogued with costs, savings, CO₂, packages showing diminishing returns |
| **§3** | Radiator Upsizing | Explicit measure (£2,500, 10°C flow temp reduction) standalone and in packages |
| **§4** | Window Upgrades | Double vs triple glazing comparison with marginal benefit analysis |
| **§5** | Payback Times | Simple and discounted payback (3.5% rate) for all measures and pathways |
| **§6** | Pathways & Hybrid | 5 pathways with per-home and aggregate metrics, hybrid cost breakdown |
| **§7** | EPC Anomalies | 45,000 anomalies flagged (6.4%), ±30% uncertainty ranges |
| **§8** | Tipping Point Curve | Cumulative capex vs kWh saved, marginal cost analysis |
| **§9** | Load Profiles | Hourly profiles, peak/average kW, peak-to-average ratios |
| **§10** | Penetration & Sensitivity | HN penetration scenarios, 4 price scenarios, tornado chart |
| **§11** | Tenure Filtering | Breakdown by owner-occupied, private rented, social housing |
| **§12** | Documentation | Comprehensive component documentation and explanations |

## 🚀 How to Use

### 1) Generate fresh dashboard data

Run the full analysis to export the dashboard dataset and copy it into the React app:

```bash
python run_analysis.py
# dashboard-data.json will be written to data/outputs/dashboard/ and dashboard/public/
```

### 2) Run the React development server

```bash
cd dashboard
npm install  # Only needed first time
npm run dev  # Starts http://localhost:5173 using the latest dashboard-data.json
```

### 3) Build for deployment

```bash
cd dashboard
npm run build  # Creates production build in dist/
```

## 📱 Dashboard Structure

### Navigation Tabs

1. **Executive Summary**
   - Key metrics (704,292 properties, avg SAP 63.4)
   - EPC band distribution
   - Pathway comparison table

2. **Fabric Analysis (§1, §7, §11)**
   - Wall type and insulation distributions
   - Roof insulation statistics
   - Glazing types
   - EPC anomalies (6.4% flagged)
   - Tenure breakdown

3. **Retrofit Measures (§2, §3, §4, §5)**
   - Individual measures table (15+ measures)
   - Radiator upsizing details
   - Double vs triple glazing comparison
   - Retrofit packages with payback times
   - Diminishing returns analysis

4. **Pathways & Tipping Points (§6, §8)**
   - 5 pathways comparison table
   - Capex and CO₂ charts
   - Hybrid pathway cost breakdown
   - Fabric tipping point curve
   - Heat network tier classification

5. **Load Profiles & Sensitivity (§9, §10)**
   - Hourly heat demand profiles
   - Peak/average load metrics
   - Sensitivity tornado chart
   - Price scenario overview
   - EPC distribution validation
   - Uncertainty quantification

## 📊 Key Features

### Interactive Charts

All charts are responsive and interactive:
- Hover for detailed tooltips
- Bar charts for distributions
- Line charts for time series
- Pie charts for proportions
- Area charts for cumulative data
- Tornado charts for sensitivity

### Data Tables

Comprehensive tables with:
- Sortable columns
- Color-coded badges
- Formatted numbers (£, kWh, tonnes)
- Explanatory footnotes

### Metric Cards

Eye-catching gradient cards showing:
- Total properties (704,292)
- Average SAP scores
- Insulation rates
- Peak load reductions
- Cost breakdowns

## 🎨 Design Highlights

- **Gradient Headers:** Purple-blue gradient for professional look
- **Card-Based Layout:** Clean, modern cards for each section
- **Responsive Design:** Works on desktop, tablet, and mobile
- **Color-Coded Status:** Green (success), yellow (warning), red (danger)
- **Tabbed Navigation:** Easy switching between analysis sections

## 📈 Key Findings Presented

### Fabric Analysis
- 33.7% wall insulation rate
- 150mm median roof insulation
- 6.4% properties with EPC anomalies

### Retrofit Measures
- Value package: £3,700 for 61% of max savings
- Radiator upsizing: £2,500, enables HP operation
- Triple glazing: £3,000 premium over double

### Pathways
- Fabric + HP: Best CO₂ reduction (4.93t/property)
- Hybrid pathway: £28,407/property realistic cost
- Heat pump pathway: 28.1 year payback

### Sensitivity
- Gas/electricity prices: Highest impact (£450/yr range)
- Heat pump COP: Moderate impact (£250/yr range)
- Fabric costs: Lowest impact (£75/yr range)

## 🔧 Customization

### Updating Data

Run `python run_analysis.py` to regenerate `dashboard-data.json` with the latest validated EPC data, scenario modelling, and spatial summaries. The JSON is copied automatically into `dashboard/public/` for the React app and `data/outputs/dashboard/` for archives.

For mock/demo tweaks without rerunning the analysis, you can still adjust `dashboard/src/data/mockData.js`; these values are only used if the live dataset is unavailable.

### Styling Changes

Edit `dashboard/src/index.css` for:
- Colors and gradients
- Typography
- Card layouts
- Spacing and sizing

### Adding New Sections

1. Create component in `dashboard/src/components/`
2. Import in `dashboard/src/App.jsx`
3. Add tab to navigation array

## 📤 Sharing the Dashboard

### Email
Zip and share the latest `dashboard/dist/` build (after running `npm run build`). Include the companion `dashboard-data.json` from `data/outputs/dashboard/` if you want recipients to view the newest analysis results offline.

### Cloud Storage
Upload to Dropbox, Google Drive, OneDrive

### Web Hosting
Deploy `dashboard/dist/` to:
- Netlify (drag & drop)
- Vercel (GitHub integration)
- GitHub Pages
- AWS S3

### Offline Presentations
Copy the built `dist/` folder plus `dashboard-data.json` to a USB drive or local network share

## 🎓 Technical Details

### Technologies
- React 18 (UI framework)
- Recharts 2.10 (charts)
- Vite 5 (build tool)
- Modern ES6+ JavaScript

### Browser Support
- Chrome/Edge 90+
- Firefox 88+
- Safari 14+
- All modern browsers

### Performance
- Production build optimized by Vite
- Data pulled from lightweight JSON (`dashboard-data.json`)
- Smooth chart interactions
- Responsive to window resize

## ✅ Quality Assurance

### Requirements Coverage
- ✅ All 12 client sections implemented
- ✅ All key metrics displayed
- ✅ All analysis types represented
- ✅ Interactive and visual

### Data Accuracy
- Uses same calculations as analysis pipeline
- Matches CLIENT_QUESTIONS_VERIFICATION.md
- Consistent with data/outputs/ files
- Documented assumptions

### Usability
- Clear navigation
- Intuitive layout
- Responsive design
- Print-friendly

## 📞 Next Steps

### Immediate Use
1. Run `python run_analysis.py` to refresh `dashboard-data.json`
2. Start the dev server with `npm run dev` inside `dashboard/`
3. Navigate through tabs to review all 12 sections
4. Share the built `dist/` folder (plus `dashboard-data.json`) with stakeholders

### Customization
1. Update mock data for demos (live data comes from `dashboard-data.json`)
2. Adjust colors/styling to brand
3. Add additional charts if needed
4. Rebuild production assets with `npm run build`

### Deployment
1. Choose hosting platform
2. Build production version
3. Upload and test
4. Share URL with team

## 🎉 Summary

You now have:
- ✅ **Comprehensive dashboard** covering all 12 client requirements
- ✅ **React source code** for customization
- ✅ **Interactive charts** for all analyses powered by the latest analysis outputs
- ✅ **Professional design** suitable for stakeholder presentations

The dashboard successfully addresses every requirement in CLIENT_QUESTIONS_VERIFICATION.md and now pulls its visuals from the latest analysis outputs.

---

**Generated:** 2025-12-08
**Status:** ✅ Production Ready
**Files:** dashboard/ directory + data/outputs/dashboard/dashboard-data.json
