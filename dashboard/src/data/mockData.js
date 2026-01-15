// Mock data for the dashboard - will be replaced with actual data loading
// This file provides sample data matching the structure from the analysis outputs

// EPC band counts define the authoritative property count
const epcBandCounts = {
  A: { count: 2393, percentage: 0.3 },
  B: { count: 23691, percentage: 3.4 },
  C: { count: 200312, percentage: 28.4 },
  D: { count: 370061, percentage: 52.5 },
  E: { count: 95136, percentage: 13.5 },
  F: { count: 9836, percentage: 1.4 },
  G: { count: 3054, percentage: 0.4 }
};

// AUDIT FIX: totalProperties is derived from EPC band counts, not hard-coded
const derivedTotalProperties = Object.values(epcBandCounts).reduce((sum, band) => sum + band.count, 0);

export const executiveSummary = {
  totalProperties: derivedTotalProperties,  // Derived from EPC bands
  avgSAPScore: 63.4,
  medianSAPScore: 64.0,
  epcBands: epcBandCounts,
  wallInsulationRate: 33.7
};

export const fabricAnalysis = {
  wallTypes: [
    { type: 'Solid Brick', count: 280000, percentage: 39.7 },
    { type: 'Cavity', count: 350000, percentage: 49.7 },
    { type: 'Stone', count: 50000, percentage: 7.1 },
    { type: 'Other', count: 24292, percentage: 3.5 }
  ],
  wallInsulation: [
    { status: 'None', count: 467000, percentage: 66.3 },
    { status: 'Cavity Filled', count: 150000, percentage: 21.3 },
    { status: 'Internal', count: 50000, percentage: 7.1 },
    { status: 'External', count: 30000, percentage: 4.3 },
    { status: 'Unknown', count: 7292, percentage: 1.0 }
  ],
  roofInsulation: {
    median: 150,
    q1: 100,
    q3: 200,
    below100mm: 35.2,
    below150mm: 52.1
  },
  glazingTypes: [
    { type: 'Single', count: 150000, percentage: 21.3 },
    { type: 'Double', count: 500000, percentage: 71.0 },
    { type: 'Triple', count: 54292, percentage: 7.7 }
  ],
  anomalies: {
    total: 45000,
    percentage: 6.4,
    poorFabricGoodEPC: 38000,
    goodFabricPoorEPC: 7000
  }
};

export const tenureBreakdown = [
  { tenure: 'Owner-Occupied', properties: 425000, percentage: 60.3, avgEPCBand: 'C', medianSAP: 65 },
  { tenure: 'Private Rented', properties: 180000, percentage: 25.6, avgEPCBand: 'D', medianSAP: 62 },
  { tenure: 'Social', properties: 85000, percentage: 12.1, avgEPCBand: 'C', medianSAP: 67 },
  { tenure: 'Unknown', properties: 14292, percentage: 2.0, avgEPCBand: 'D', medianSAP: 63 }
];

export const retrofitMeasures = [
  {
    id: 'loft_insulation',
    name: 'Loft Insulation (270mm)',
    capex: 1200,
    annualSaving: 240,
    kwhSaving: 2100,
    co2Saving: 0.42,
    simplePayback: 5.0,
    discountedPayback: 5.3
  },
  {
    id: 'cavity_wall',
    name: 'Cavity Wall Insulation',
    capex: 2500,
    annualSaving: 380,
    kwhSaving: 3000,
    co2Saving: 0.65,
    simplePayback: 6.6,
    discountedPayback: 7.1
  },
  {
    id: 'solid_wall_internal',
    name: 'Solid Wall Insulation (Internal)',
    capex: 8500,
    annualSaving: 520,
    kwhSaving: 4200,
    co2Saving: 0.88,
    simplePayback: 16.3,
    discountedPayback: 19.2
  },
  {
    id: 'double_glazing',
    name: 'Double Glazing Upgrade',
    capex: 6000,
    annualSaving: 150,
    kwhSaving: 1500,
    co2Saving: 0.32,
    simplePayback: 40.0,
    discountedPayback: 52.1
  },
  {
    id: 'triple_glazing',
    name: 'Triple Glazing Upgrade',
    capex: 9000,
    annualSaving: 225,
    kwhSaving: 2250,
    co2Saving: 0.48,
    simplePayback: 40.0,
    discountedPayback: 52.1
  },
  {
    id: 'rad_upsizing',
    name: 'Radiator Upsizing',
    capex: 2500,
    annualSaving: 0,
    kwhSaving: 0,
    co2Saving: 0,
    simplePayback: null,
    discountedPayback: null,
    flowTempReduction: 10,
    note: 'Enables low-temperature heat pump operation'
  }
];

export const retrofitPackages = [
  {
    id: 'loft_only',
    name: 'Loft Insulation Only',
    capex: 1200,
    annualSaving: 240,
    kwhSaving: 2100,
    co2Saving: 0.42,
    simplePayback: 5.0,
    discountedPayback: 5.3
  },
  {
    id: 'value_package',
    name: 'Value Sweet Spot',
    capex: 3700,
    annualSaving: 600,
    kwhSaving: 4800,
    co2Saving: 1.02,
    simplePayback: 6.2,
    discountedPayback: 6.7,
    measures: ['Loft Insulation', 'Cavity Wall Insulation']
  },
  {
    id: 'full_fabric',
    name: 'Full Fabric Package',
    capex: 12200,
    annualSaving: 1200,
    kwhSaving: 9300,
    co2Saving: 2.0,
    simplePayback: 10.2,
    discountedPayback: 12.1,
    measures: ['Loft', 'Walls', 'Glazing', 'Draught Proofing']
  },
  {
    id: 'max_retrofit',
    name: 'Maximum ("Rolls Royce")',
    capex: 21200,
    annualSaving: 1450,
    kwhSaving: 11000,
    co2Saving: 2.38,
    simplePayback: 14.6,
    discountedPayback: 18.2,
    measures: ['Loft', 'Solid Walls', 'Triple Glazing', 'Radiators', 'Ventilation']
  }
];

export const pathwayResults = [
  {
    id: 'baseline',
    name: 'Baseline (No Action)',
    capex: 0,
    capexPerProperty: 0,
    annualBillSavings: 0,
    annualBillSavingsPerProperty: 0,
    co2Reduction: 0,
    co2ReductionPerProperty: 0,
    payback: 0
  },
  {
    id: 'fabric_only',
    name: 'Fabric Only',
    capex: 20012059552,
    capexPerProperty: 28407,
    annualBillSavings: 601028444,
    annualBillSavingsPerProperty: 853,
    co2Reduction: 1762631,
    co2ReductionPerProperty: 2.5,
    payback: 35.0
  },
  {
    id: 'fabric_plus_hp',
    name: 'Fabric + Heat Pump',
    capex: 29924381152,
    capexPerProperty: 42477,
    annualBillSavings: 1183843906,
    annualBillSavingsPerProperty: 1681,
    co2Reduction: 3471850,
    co2ReductionPerProperty: 4.93,
    payback: 28.1
  },
  {
    id: 'fabric_plus_hn',
    name: 'Fabric + Heat Network',
    capex: 23534474552,
    capexPerProperty: 33407,
    annualBillSavings: 601028444,
    annualBillSavingsPerProperty: 853,
    co2Reduction: 1762631,
    co2ReductionPerProperty: 2.5,
    payback: 41.5
  },
  {
    id: 'hybrid',
    name: 'Hybrid (HN where available, HP elsewhere)',
    capex: 20012059552,
    capexPerProperty: 28407,
    annualBillSavings: 437111596,
    annualBillSavingsPerProperty: 621,
    co2Reduction: 1281914,
    co2ReductionPerProperty: 1.82,
    payback: 47.2
  }
];

export const tippingPointData = [
  { step: 0, measure: 'Baseline', cumulativeCapex: 0, cumulativeKWh: 0, marginalCost: 0, beyondTippingPoint: false },
  { step: 1, measure: 'Draught Proofing', cumulativeCapex: 500, cumulativeKWh: 750, marginalCost: 0.67, beyondTippingPoint: false },
  { step: 2, measure: 'Loft Insulation', cumulativeCapex: 1700, cumulativeKWh: 2850, marginalCost: 0.57, beyondTippingPoint: false },
  { step: 3, measure: 'Cavity Wall', cumulativeCapex: 4200, cumulativeKWh: 5850, marginalCost: 0.83, beyondTippingPoint: false },
  { step: 4, measure: 'Floor Insulation', cumulativeCapex: 6200, cumulativeKWh: 7350, marginalCost: 1.33, beyondTippingPoint: false },
  { step: 5, measure: 'Double Glazing', cumulativeCapex: 12200, cumulativeKWh: 8850, marginalCost: 4.00, beyondTippingPoint: true },
  { step: 6, measure: 'Solid Wall (Internal)', cumulativeCapex: 20700, cumulativeKWh: 13050, marginalCost: 2.02, beyondTippingPoint: true },
  { step: 7, measure: 'Triple Glazing', cumulativeCapex: 29700, cumulativeKWh: 14550, marginalCost: 6.00, beyondTippingPoint: true }
];

// AUDIT FIX: Ensure all 5 tiers are present, including Tier 2 (even if 0 properties)
export const heatNetworkTiers = [
  {
    tier: 'Tier 1: Adjacent to existing network',
    properties: 1270,
    percentage: 0.2,
    recommendation: 'District Heating (existing network connection)'
  },
  {
    tier: 'Tier 2: Within planned HNZ',
    properties: 0,  // May be 0 if no planned heat network zones in dataset
    percentage: 0.0,
    recommendation: 'District Heating (planned network)',
    note: 'Zero properties indicates no planned heat network zone data available'
  },
  {
    tier: 'Tier 3: High heat density',
    properties: 234719,
    percentage: 33.3,
    recommendation: 'District Heating (high density justifies extension)'
  },
  {
    tier: 'Tier 4: Medium heat density',
    properties: 239077,
    percentage: 33.9,
    recommendation: 'Heat Pump (moderate density, network extension marginal)'
  },
  {
    tier: 'Tier 5: Low heat density',
    properties: 229226,
    percentage: 32.5,
    recommendation: 'Heat Pump (low density, network not viable)'
  }
];

export const sensitivityAnalysis = {
  parameters: [
    {
      parameter: 'Gas price (p/kWh)',
      lowValue: 5.0,
      highValue: 12.0,
      impactLow: 650,
      impactHigh: 1100,
      sensitivityRange: 450
    },
    {
      parameter: 'Electricity price (p/kWh)',
      lowValue: 18.0,
      highValue: 35.0,
      impactLow: 600,
      impactHigh: 1050,
      sensitivityRange: 450
    },
    {
      parameter: 'Heat pump COP',
      lowValue: 2.5,
      highValue: 3.8,
      impactLow: 950,
      impactHigh: 700,
      sensitivityRange: 250
    },
    {
      parameter: 'Air tightness (ACH)',
      lowValue: 5.0,
      highValue: 12.0,
      impactLow: 750,
      impactHigh: 880,
      sensitivityRange: 130
    },
    {
      parameter: 'Fabric cost (£)',
      lowValue: 5000,
      highValue: 12000,
      impactLow: 775,
      impactHigh: 850,
      sensitivityRange: 75
    }
  ],
  baseCaseValue: 800
};

export const epcDistribution = [
  { band: 'A', shakespeareCrescent: 0.0, londonPre1930: 0.4, national: 0.4 },
  { band: 'B', shakespeareCrescent: 0.0, londonPre1930: 2.2, national: 2.1 },
  { band: 'C', shakespeareCrescent: 57.1, londonPre1930: 42.3, national: 40.2 },
  { band: 'D', shakespeareCrescent: 42.9, londonPre1930: 47.9, national: 45.5 },
  { band: 'E', shakespeareCrescent: 0.0, londonPre1930: 6.0, national: 5.7 },
  { band: 'F', shakespeareCrescent: 0.0, londonPre1930: 0.8, national: 0.7 },
  { band: 'G', shakespeareCrescent: 0.0, londonPre1930: 0.4, national: 0.4 }
];

export const loadProfiles = {
  hourly: Array.from({ length: 24 }, (_, hour) => ({
    hour,
    baseline: hour < 6 ? 1.5 : hour < 9 ? 3.5 : hour < 17 ? 2.0 : hour < 22 ? 4.0 : 2.5,
    fabricOnly: hour < 6 ? 1.0 : hour < 9 ? 2.8 : hour < 17 ? 1.5 : hour < 22 ? 3.2 : 2.0,
    heatPump: hour < 6 ? 0.8 : hour < 9 ? 2.5 : hour < 17 ? 1.3 : hour < 22 ? 2.9 : 1.7
  })),
  summary: [
    { pathway: 'Baseline', peakKW: 4.2, avgKW: 2.3, peakToAvgRatio: 1.83 },
    { pathway: 'Fabric Only', peakKW: 3.4, avgKW: 1.8, peakToAvgRatio: 1.89 },
    { pathway: 'Heat Pump', peakKW: 3.0, avgKW: 1.6, peakToAvgRatio: 1.88 },
    { pathway: 'Heat Network', peakKW: 3.5, avgKW: 1.9, peakToAvgRatio: 1.84 }
  ]
};
