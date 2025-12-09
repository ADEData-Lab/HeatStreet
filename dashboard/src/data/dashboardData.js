// Dashboard Data - All data structures following HEAT_STREET_DASHBOARD_SPECIFICATION.md
// This file provides data matching the exact schemas defined in the specification

// Section 5.1: EPC Band Distribution
export const epcBandData = [
  { band: 'A', count: 2393, percentage: 0.3, color: '#1a472a' },
  { band: 'B', count: 23691, percentage: 3.4, color: '#2d6a4f' },
  { band: 'C', count: 200312, percentage: 28.4, color: '#40916c' },
  { band: 'D', count: 370061, percentage: 52.5, color: '#f4a261' },
  { band: 'E', count: 95136, percentage: 13.5, color: '#e76f51' },
  { band: 'F', count: 9836, percentage: 1.4, color: '#d62828' },
  { band: 'G', count: 3054, percentage: 0.4, color: '#9d0208' }
];

// Section 5.2: Case Street vs London Comparison
export const epcComparisonData = [
  { band: 'A', shakespeareCrescent: 0.0, londonAverage: 0.3 },
  { band: 'B', shakespeareCrescent: 0.0, londonAverage: 3.4 },
  { band: 'C', shakespeareCrescent: 57.1, londonAverage: 28.4 },
  { band: 'D', shakespeareCrescent: 42.9, londonAverage: 52.5 },
  { band: 'E', shakespeareCrescent: 0.0, londonAverage: 13.5 },
  { band: 'F', shakespeareCrescent: 0.0, londonAverage: 1.4 },
  { band: 'G', shakespeareCrescent: 0.0, londonAverage: 0.4 }
];

// Section 5.3: Wall Construction Types
export const wallTypeData = [
  { type: 'Solid Brick', count: 440296, percentage: 62.5, insulated: 3.2 },
  { type: 'Cavity', count: 246368, percentage: 35.0, insulated: 68.4 },
  { type: 'Timber Frame', count: 14090, percentage: 2.0, insulated: 12.1 },
  { type: 'Other', count: 3729, percentage: 0.5, insulated: 8.9 }
];

// Section 5.4: Heating Systems
export const heatingSystemData = [
  { name: 'Gas Boiler', value: 95.8, count: 675096 },
  { name: 'Electric', value: 2.8, count: 19726 },
  { name: 'Oil/Solid Fuel', value: 0.9, count: 6340 },
  { name: 'Other', value: 0.5, count: 3321 }
];

// Section 5.5: Scenario Modelling Results
export const scenarioData = [
  {
    scenario: 'Baseline',
    capitalCost: 0,
    costPerProperty: 0,
    co2Reduction: 0,
    billSavings: 0,
    paybackYears: 0
  },
  {
    scenario: 'Fabric Only',
    capitalCost: 20012,
    costPerProperty: 28407,
    co2Reduction: 1762631,
    billSavings: 853,
    paybackYears: 35.0
  },
  {
    scenario: 'Heat Pump',
    capitalCost: 29924,
    costPerProperty: 42477,
    co2Reduction: 3471850,
    billSavings: 1681,
    paybackYears: 28.1
  },
  {
    scenario: 'Heat Network',
    capitalCost: 23534,
    costPerProperty: 33407,
    co2Reduction: 1762631,
    billSavings: 853,
    paybackYears: 41.5
  },
  {
    scenario: 'Hybrid',
    capitalCost: 20012,
    costPerProperty: 28407,
    co2Reduction: 1281914,
    billSavings: 621,
    paybackYears: 47.2
  }
];

// Section 5.6: Heat Network Tier Classification
export const tierData = [
  {
    tier: 'Tier 1: Adjacent',
    properties: 1270,
    percentage: 0.2,
    recommendation: 'DH (existing)'
  },
  {
    tier: 'Tier 2: Near DH',
    properties: 2247,
    percentage: 0.3,
    recommendation: 'DH (extension)'
  },
  {
    tier: 'Tier 3: High Density',
    properties: 232472,
    percentage: 33.0,
    recommendation: 'DH (extension)'
  },
  {
    tier: 'Tier 4: Medium Density',
    properties: 239077,
    percentage: 33.9,
    recommendation: 'Heat Pump'
  },
  {
    tier: 'Tier 5: Low Density',
    properties: 229417,
    percentage: 32.6,
    recommendation: 'Heat Pump'
  }
];

// Section 5.7: Retrofit Readiness Tiers
export const retrofitReadinessData = [
  {
    tier: 'Tier 1 (Ready)',
    properties: 56344,
    percentage: 8.0,
    avgCost: 15420
  },
  {
    tier: 'Tier 2 (Minor Work)',
    properties: 178179,
    percentage: 25.3,
    avgCost: 20280
  },
  {
    tier: 'Tier 3 (Moderate Work)',
    properties: 251438,
    percentage: 35.7,
    avgCost: 24650
  },
  {
    tier: 'Tier 4 (Major Work)',
    properties: 162449,
    percentage: 23.1,
    avgCost: 29840
  },
  {
    tier: 'Tier 5 (Extensive Work)',
    properties: 56073,
    percentage: 7.9,
    avgCost: 38720
  }
];

// Section 5.8: Intervention Requirements
export const interventionData = [
  { intervention: 'Radiator Upsizing', percentage: 96.3, count: 678419 },
  { intervention: 'Loft Insulation', percentage: 86.1, count: 606560 },
  { intervention: 'Wall Insulation', percentage: 77.4, count: 545270 },
  { intervention: 'Floor Insulation', percentage: 68.2, count: 480458 },
  { intervention: 'Draught Proofing', percentage: 52.8, count: 371967 },
  { intervention: 'Window Upgrade', percentage: 21.5, count: 151465 },
  { intervention: 'Ventilation System', percentage: 15.3, count: 107786 }
];

// Section 5.9: Borough Data
export const boroughData = [
  { borough: 'Newham', borough_name: 'Newham', code: 'E09000025', count: 89234, meanEPC: 62.1, energy: 238 },
  { borough: 'Croydon', borough_name: 'Croydon', code: 'E09000008', count: 76512, meanEPC: 64.3, energy: 227 },
  { borough: 'Lambeth', borough_name: 'Lambeth', code: 'E09000022', count: 68947, meanEPC: 63.8, energy: 230 },
  { borough: 'Wandsworth', borough_name: 'Wandsworth', code: 'E09000032', count: 64823, meanEPC: 65.2, energy: 223 },
  { borough: 'Lewisham', borough_name: 'Lewisham', code: 'E09000023', count: 58392, meanEPC: 63.4, energy: 232 },
  { borough: 'Southwark', borough_name: 'Southwark', code: 'E09000028', count: 52167, meanEPC: 62.9, energy: 235 },
  { borough: 'Ealing', borough_name: 'Ealing', code: 'E09000009', count: 48934, meanEPC: 64.7, energy: 225 },
  { borough: 'Brent', borough_name: 'Brent', code: 'E09000005', count: 45621, meanEPC: 63.2, energy: 233 },
  { borough: 'Haringey', borough_name: 'Haringey', code: 'E09000014', count: 42156, meanEPC: 63.5, energy: 231 },
  { borough: 'Islington', borough_name: 'Islington', code: 'E09000019', count: 39874, meanEPC: 64.1, energy: 228 },
  { borough: 'Hackney', borough_name: 'Hackney', code: 'E09000012', count: 37295, meanEPC: 62.8, energy: 236 },
  { borough: 'Greenwich', borough_name: 'Greenwich', code: 'E09000011', count: 35418, meanEPC: 63.9, energy: 229 },
  { borough: 'Hammersmith and Fulham', borough_name: 'Hammersmith and Fulham', code: 'E09000013', count: 32567, meanEPC: 65.8, energy: 220 },
  { borough: 'Camden', borough_name: 'Camden', code: 'E09000007', count: 29834, meanEPC: 64.5, energy: 226 },
  { borough: 'Westminster', borough_name: 'Westminster', code: 'E09000033', count: 27705, meanEPC: 66.2, energy: 218 }
];

// Section 5.10: Heat Demand Confidence Bands
export const confidenceBandsData = [
  { stage: 'Baseline', estimate: 18500, lower: 15725, upper: 21275 },
  { stage: 'Loft', estimate: 16200, lower: 13770, upper: 18630 },
  { stage: 'Walls', estimate: 13800, lower: 11730, upper: 15870 },
  { stage: 'Floor', estimate: 12500, lower: 10625, upper: 14375 },
  { stage: 'Full Retrofit', estimate: 11600, lower: 9860, upper: 13340 }
];

// Section 5.11: Sensitivity Analysis Data
export const sensitivityData = [
  { parameter: 'Gas price', lowImpact: 650, highImpact: 1100, range: 450 },
  { parameter: 'Electricity price', lowImpact: 600, highImpact: 1050, range: 450 },
  { parameter: 'Heat pump COP', lowImpact: 700, highImpact: 950, range: 250 },
  { parameter: 'Air tightness', lowImpact: 750, highImpact: 880, range: 130 },
  { parameter: 'Fabric cost', lowImpact: 775, highImpact: 850, range: 75 }
];

// Section 5.12: Grid Peak Load Data
export const gridPeakData = [
  { scenario: 'Baseline', peak: 520, average: 320 },
  { scenario: 'Fabric Only', peak: 440, average: 270 },
  { scenario: 'Heat Pump', peak: 310, average: 190 },
  { scenario: 'Heat Network', peak: 80, average: 45 }
];

// Section 5.13: Indoor Climate Data
export const indoorClimateData = [
  { hour: '06:00', temperature: 17.5, humidity: 62 },
  { hour: '09:00', temperature: 18.9, humidity: 58 },
  { hour: '12:00', temperature: 19.6, humidity: 55 },
  { hour: '15:00', temperature: 20.4, humidity: 53 },
  { hour: '18:00', temperature: 20.1, humidity: 54 },
  { hour: '21:00', temperature: 19.3, humidity: 57 }
];

// Section 5.14: Cost Reduction Levers
export const costLeversData = [
  { lever: 'Shared ground loops', impact: 2100, difficulty: 'Medium' },
  { lever: 'Supply chain optimisation', impact: 1800, difficulty: 'Low' },
  { lever: 'Bulk procurement', impact: 1200, difficulty: 'Low' },
  { lever: 'Standardised designs', impact: 800, difficulty: 'Low' },
  { lever: 'Street-by-street delivery', impact: 200, difficulty: 'Medium' }
];

// Section 5.15: Loft Insulation Categories
export const loftInsulationData = [
  { thickness: 'None', properties: 160000 },
  { thickness: '100-200mm', properties: 440000 },
  { thickness: '≥270mm', properties: 100000 }
];

// Section 5.16: Cost-Benefit Optimisation Data
export const costBenefitTierData = [
  {
    tier: 'Tier 1',
    tierLabel: 'Ready Now',
    properties: 56344,
    share: 8.0,
    fabricCost: 2150,
    totalCost: 15420,
    heatDemand: 108,
    reduction: 142,
    reductionPct: 56.8,
    coldDays: 4.2,
    comfortScore: 94,
    efficiency: 29.3
  },
  {
    tier: 'Tier 2',
    tierLabel: 'Minor Work',
    properties: 178179,
    share: 25.3,
    fabricCost: 4280,
    totalCost: 20280,
    heatDemand: 125,
    reduction: 125,
    reductionPct: 50.0,
    coldDays: 7.8,
    comfortScore: 88,
    efficiency: 21.2
  },
  {
    tier: 'Tier 3',
    tierLabel: 'Moderate Work',
    properties: 251438,
    share: 35.7,
    fabricCost: 7650,
    totalCost: 24650,
    heatDemand: 145,
    reduction: 105,
    reductionPct: 42.0,
    coldDays: 14.3,
    comfortScore: 78,
    efficiency: 9.2
  },
  {
    tier: 'Tier 4',
    tierLabel: 'Major Work',
    properties: 162449,
    share: 23.1,
    fabricCost: 12840,
    totalCost: 29840,
    heatDemand: 162,
    reduction: 88,
    reductionPct: 35.2,
    coldDays: 22.1,
    comfortScore: 68,
    efficiency: 7.8
  },
  {
    tier: 'Tier 5',
    tierLabel: 'Extensive Work',
    properties: 56073,
    share: 7.9,
    fabricCost: 18720,
    totalCost: 38720,
    heatDemand: 178,
    reduction: 72,
    reductionPct: 28.8,
    coldDays: 31.5,
    comfortScore: 58,
    efficiency: 6.9
  }
];

// Cost Curve Data for Cost-Benefit Analysis
export const costCurveData = [
  { measure: 'Baseline', cost: 0, savings: 0 },
  { measure: 'Tier 1', cost: 2150, savings: 620 },
  { measure: 'Tier 2', cost: 4280, savings: 1080 },
  { measure: 'Tier 3', cost: 7650, savings: 1420 },
  { measure: 'Tier 4', cost: 12840, savings: 1675 },
  { measure: 'Tier 5', cost: 18720, savings: 1810 }
];

// Glazing Analysis Data for Housing Stock tab
export const glazingData = [
  { type: 'Single', share: 3.9, uValue: 4.8 },
  { type: 'Double', share: 81.2, uValue: 2.0 },
  { type: 'Triple', share: 0.1, uValue: 1.0 },
  { type: 'Unknown', share: 14.8, uValue: 2.8 }
];

// Summary Statistics (Derived)
export const summaryStats = {
  totalProperties: 704483,
  meanSAPScore: 63.4,
  wallInsulationRate: 33.7,
  dhViableProperties: 235989,
  gasBoilerDependency: 95.8,
  belowBandC: 67.8,
  costAdvantageDHvsHP: 9070,
  peakGridReduction: 85,
  optimalInvestmentPoint: 4500,
  meanFabricCost: 7710,
  meanTotalRetrofitCost: 22177,
  heatDemandReduction: 37.4,
  readyOrNearReady: 33.3
};

export const defaultDashboardData = {
  epcBandData,
  epcComparisonData,
  wallTypeData,
  heatingSystemData,
  scenarioData,
  tierData,
  retrofitReadinessData,
  interventionData,
  boroughData,
  confidenceBandsData,
  sensitivityData,
  gridPeakData,
  indoorClimateData,
  costLeversData,
  loftInsulationData,
  costBenefitTierData,
  costCurveData,
  glazingData,
  summaryStats,
};
