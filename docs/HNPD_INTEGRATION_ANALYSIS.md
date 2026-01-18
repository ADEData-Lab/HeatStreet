# BEIS Heat Network Planning Database (HNPD) Integration Analysis

**Date:** 2026-01-18
**HNPD Version:** January 2024
**Source:** https://assets.publishing.service.gov.uk/media/65c9f7b89c5b7f000c951cad/hnpd-january-2024.csv

---

## Executive Summary

This document analyzes the integration of the **BEIS Heat Network Planning Database (HNPD)** into HeatStreet's spatial analysis pipeline, answering three critical questions:

1. ✅ **How to integrate HNPD CSV** - Design and implementation approach
2. ✅ **Field mapping to tier system** - Direct correspondence between HNPD and current tiers
3. ✅ **Geographic coverage** - UK-wide (1,332 records), with 594 in London (45%)

**Key Finding:** The HNPD provides **2024 data vs 2012 London Heat Map**, offering 12 years of updates including hundreds of new projects. Integration would significantly improve accuracy.

---

## Question 1: How to Integrate HNPD CSV into the Analysis

### Current Data Source Issues

| Issue | Current (London Heat Map 2012) | HNPD (January 2024) |
|-------|-------------------------------|---------------------|
| **Data Age** | April 2012 (12+ years old) | January 2024 (current) |
| **Coverage** | London only | UK-wide (England, Scotland, Wales, NI) |
| **Format** | Shapefiles (requires GDAL) | CSV (simple, portable) |
| **Records** | Legacy networks only | 1,332 projects across all statuses |
| **Planned Networks** | 2005 study data | Active planning applications (2024) |

### Proposed Integration Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    HNPD Integration Layer                    │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Download   │    │   Convert    │    │   Classify   │
│  HNPD CSV    │───▶│  to GeoJSON  │───▶│   Networks   │
│              │    │  (EPSG:27700)│    │   by Tier    │
└──────────────┘    └──────────────┘    └──────────────┘
                                                │
                         ┌──────────────────────┤
                         │                      │
                         ▼                      ▼
                  ┌──────────────┐      ┌──────────────┐
                  │  Tier 1:     │      │  Tier 2:     │
                  │ Operational  │      │ Planned      │
                  │ + Under Const│      │ (Permitted)  │
                  └──────────────┘      └──────────────┘
```

### Implementation Steps

#### Step 1: Create HNPD Downloader Module

**File:** `src/acquisition/hnpd_downloader.py`

**Responsibilities:**
- Download CSV from GOV.UK assets
- Parse with proper encoding (latin-1)
- Convert to GeoDataFrame using X/Y coordinates
- Transform to EPSG:27700 (British National Grid)
- Cache locally in `data/external/`

**Key Methods:**
```python
class HNPDDownloader:
    def download_hnpd(force_redownload: bool) -> bool
    def load_hnpd_as_geodataframe(region_filter: str = 'London') -> gpd.GeoDataFrame
    def get_networks_by_status(status_list: List[str]) -> gpd.GeoDataFrame
    def get_data_summary() -> dict
```

#### Step 2: Update Heat Network Analysis

**File:** `src/spatial/heat_network_analysis.py`

**Changes Required:**

1. **Add HNPD data loading method** (parallel to London Heat Map):
```python
def load_hnpd_data(self,
                   region_filter: Optional[str] = None,
                   auto_download: bool = True
                  ) -> Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """
    Load HNPD data for heat networks and planned zones.

    Returns:
        (existing_networks, planned_networks) tuple
        - existing_networks: Operational + Under Construction
        - planned_networks: Planning Permission Granted
    """
```

2. **Update `classify_heat_network_tiers()` to accept HNPD data**:
   - Tier 1: Use HNPD "Operational" + "Under Construction" records
   - Tier 2: Use HNPD "Planning Permission Granted" records
   - Buffer both by network distribution length (if available)

3. **Add hybrid mode** - Use HNPD where available, fallback to London Heat Map for areas without HNPD coverage

#### Step 3: Configuration Updates

**File:** `config/config.yaml`

Add new section:
```yaml
data_sources:
  heat_networks:
    primary: "hnpd"  # Options: "hnpd", "london_heat_map", "both"
    hnpd:
      url: "https://assets.publishing.service.gov.uk/media/65c9f7b89c5b7f000c951cad/hnpd-january-2024.csv"
      region_filter: "London"  # Or null for UK-wide
      tier_1_statuses: ["Operational", "Under Construction"]
      tier_2_statuses: ["Planning Permission Granted", "No Application Required"]
    london_heat_map:
      fallback_enabled: true
      use_for_heat_density: true  # Still use for Tiers 3-5
```

---

## Question 2: Field Mapping to Current Tier Classification

### HNPD Field Structure

**Total Fields:** 56 columns
**Total Records:** 1,332 heat network projects

**Critical Fields for Integration:**

| HNPD Column | Type | Usage | Example |
|-------------|------|-------|---------|
| `Ref ID` | String | Unique identifier | "HNPD-1234" |
| `Site Name` | String | Project name | "Springfield Hospital" |
| `Development Status` | String | **PRIMARY TIER CLASSIFIER** | "Operational" |
| `X-coordinate` | Float | British National Grid Easting | 527307 |
| `Y-coordinate` | Float | British National Grid Northing | 172337 |
| `Connection to communal, district or campus heat network` | String | Network type | "District" |
| `Number of customer connections` | Integer | Network size | 150 |
| `Length of distribution network in m` | Float | **For buffer distance** | 2500 |
| `Region` | String | Geographic filter | "London" |
| `Post Code` | String | Alternative geocoding | "SW17 7DJ" |

### Direct Tier Mapping

#### **Tier 1: Adjacent to Existing Network (within 250m)**

**HNPD Filter:**
```python
tier_1_statuses = [
    "Operational",              # 53 records (4.0%)
    "Under Construction",       # 252 records (18.9%)
    "No Application Required"   # 5 records (0.4%)
]
```

**Total Tier 1 Source Networks:** 310 networks (23.3% of HNPD)

**Methodology:**
1. Filter HNPD to Tier 1 statuses
2. Convert to point geometries using (X-coordinate, Y-coordinate)
3. If `Length of distribution network in m` is available:
   - Use as buffer radius (networks are linear infrastructure)
   - Else default to 250m buffer per config

**Improvement vs 2012 London Heat Map:**
- 2012 data: ~20-30 existing networks in London
- HNPD 2024: 53 operational + 252 under construction **nationally**
- For London specifically: ~25-35 networks likely (need regional filter)

#### **Tier 2: Within Planned Heat Network Zone**

**HNPD Filter:**
```python
tier_2_statuses = [
    "Planning Permission Granted",     # 486 records (36.5%)
    "Appeal Granted",                  # 16 records (1.2%)
    "Secretary of State - Granted"     # Rare (< 1%)
]
```

**Total Tier 2 Planned Networks:** ~500 networks (37.5% of HNPD)

**Methodology:**
1. Filter HNPD to Tier 2 statuses
2. These represent **approved but not yet built** projects
3. Create polygons/buffers representing planned service areas:
   - Option A: Use postcode sector of development as zone
   - Option B: Buffer by planned `Length of distribution network in m`
   - Option C: Use 500m buffer (larger than Tier 1, represents planned coverage)

**Improvement vs 2012 London Heat Map:**
- 2012 data: Uses "Potential DH Networks" shapefile from 2005 study
- HNPD 2024: Actual planning applications **granted permission**
- Much more accurate representation of genuine near-term deployment

#### **Tiers 3-5: Heat Density Classification**

**HNPD Role:** Minimal direct contribution

**Why:** HNPD does not include heat density calculations or borough-level heat load data.

**Solution:** Continue using London Heat Map borough-level shapefiles for heat density:
- `Heat Loads/Heat_Loads_20120411{Borough}.shp`
- Calculate density as: `annual_heat_demand_gwh / area_km2`
- Tiers 3-5 classification unchanged

**Alternative Enhancement:**
- Use HNPD `Number of customer connections` as proxy for density
- High connection count (>100) in small area → High density (Tier 3)
- But this is less accurate than direct heat load data

### Status Field Complete Mapping

| Development Status | Count | HeatStreet Tier | Rationale |
|-------------------|-------|-----------------|-----------|
| **Operational** | 53 | Tier 1 | Live network, existing infrastructure |
| **Under Construction** | 252 | Tier 1 | Network being built, near-term operational |
| **Planning Permission Granted** | 486 | Tier 2 | Approved, high probability of build |
| **Appeal Granted** | 16 | Tier 2 | Granted on appeal, approved for construction |
| **No Application Required** | 5 | Tier 1 | Exempt developments, likely operational |
| Planning Application Submitted | 372 | **Not Tier 1/2** | Uncertain outcome |
| Planning Permission Refused | 51 | Excluded | Rejected, not viable |
| Planning Application Withdrawn | 51 | Excluded | Abandoned by applicant |
| Revised | 27 | **Not Tier 1/2** | Under revision, status unclear |
| Abandoned | 14 | Excluded | Project cancelled |
| Appeal Refused | 1 | Excluded | Denied after appeal |

**Conservative Approach:** Use only Operational + Under Construction (310 networks) for Tier 1

**Moderate Approach:** Add Planning Permission Granted (796 total) for Tier 2

**Aggressive Approach:** Include Planning Application Submitted (1,168 total) as Tier 2 - **NOT RECOMMENDED** (high uncertainty)

---

## Question 3: Geographic Coverage Scope

### HNPD Coverage Summary

**Total Records:** 1,332 heat network projects

**By Country:**

| Country | Records | % of Total |
|---------|---------|------------|
| **England** | 1,215 | 91.2% |
| **Scotland** | 93 | 7.0% |
| **Wales** | 23 | 1.7% |
| **Northern Ireland** | 1 | 0.1% |

**England Regional Breakdown (Top 10):**

| Region | Records | % of England | % of Total HNPD |
|--------|---------|--------------|-----------------|
| **London** | 594 | 48.9% | **44.6%** |
| South East | 182 | 15.0% | 13.7% |
| South West | 116 | 9.5% | 8.7% |
| Eastern | 89 | 7.3% | 6.7% |
| Yorkshire & Humber | 67 | 5.5% | 5.0% |
| West Midlands | 65 | 5.4% | 4.9% |
| North West | 53 | 4.4% | 4.0% |
| East Midlands | 30 | 2.5% | 2.3% |
| North East | 18 | 1.5% | 1.4% |

### Impact on HeatStreet Analysis

#### Current Scope: London Only

**Current Data:** London Heat Map 2012 (London boroughs only)

**HNPD London Records:** 594 projects (44.6% of national database)

**Implications:**
1. ✅ **London coverage is excellent** - Nearly half of all UK heat networks
2. ✅ **Directly compatible** - Can drop-in replace London Heat Map for same geography
3. ✅ **No scope change needed** - HeatStreet currently analyzes London boroughs only

#### Potential Future Expansion

**Option 1: Add Other Major Cities**

HNPD enables expansion to:
- **Manchester/Greater Manchester** (North West: 53 records)
- **Birmingham/West Midlands** (65 records)
- **Leeds/Yorkshire** (67 records)
- **Bristol/South West** (116 records)

**Requirement:** EPC data for these regions (already available via API)

**Option 2: National Analysis**

With 1,215 England records, could analyze:
- Regional heat network viability comparison
- National heat pump vs heat network pathway split
- Rural vs urban deployment patterns

**Barrier:** Heat density calculation (Tiers 3-5) requires local heat load data, which HNPD doesn't provide

### Coordinate Coverage

**Records with coordinates:** 1,324 / 1,332 (99.4%)

**Missing coordinates:** 8 records (0.6%)

**Coordinate System:** British National Grid (EPSG:27700)
- X-coordinate: Easting (meters)
- Y-coordinate: Northing (meters)

**Quality:** Excellent - near-perfect geocoding enables spatial analysis

---

## Recommendations

### Priority 1: Replace London Heat Map with HNPD for Tiers 1-2 (IMMEDIATE)

**Why:**
- 12 years more current (2024 vs 2012)
- More accurate planning application data
- Simpler format (CSV vs shapefiles)

**Implementation:**
1. Create `src/acquisition/hnpd_downloader.py`
2. Modify `src/spatial/heat_network_analysis.py` to accept HNPD
3. Update `config/config.yaml` with HNPD URL and tier status mappings
4. Keep London Heat Map for heat density (Tiers 3-5) until better source found

**Effort:** 2-3 days development + testing

### Priority 2: Hybrid Data Source Strategy (NEAR-TERM)

**Approach:**
- **Tier 1:** HNPD "Operational" + "Under Construction"
- **Tier 2:** HNPD "Planning Permission Granted"
- **Tiers 3-5:** London Heat Map borough heat load shapefiles (for density)

**Benefit:**
- Best of both datasets
- Most accurate tier classification
- Maintains heat density calculation capability

**Effort:** Additional 1-2 days to integrate both sources

### Priority 3: UK-Wide Expansion (FUTURE)

**Scope:**
- Expand analysis beyond London to other English regions
- Use HNPD for all regions (national coverage)
- Requires regional heat density data source

**Barrier:**
- Heat load data (for Tiers 3-5) not available outside London
- Would need alternative: use HNPD connection counts + building density as proxy

**Effort:** 1-2 weeks for multi-region support

---

## Technical Design: HNPD Downloader Module

### File: `src/acquisition/hnpd_downloader.py`

```python
"""
BEIS Heat Network Planning Database (HNPD) Downloader

Downloads and manages heat network data from UK Government HNPD,
providing up-to-date information on existing and planned heat networks
across the UK.

Data source: https://www.gov.uk/government/publications/heat-networks-planning-database
"""

import csv
from pathlib import Path
from typing import Optional, List, Dict
import subprocess
from loguru import logger
import geopandas as gpd
from shapely.geometry import Point

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
EXTERNAL_DIR = DATA_DIR / "external"


class HNPDDownloader:
    """Downloads and manages BEIS Heat Network Planning Database."""

    # GOV.UK HNPD URL (January 2024 version)
    HNPD_URL = "https://assets.publishing.service.gov.uk/media/65c9f7b89c5b7f000c951cad/hnpd-january-2024.csv"

    # Tier classification mappings
    TIER_1_STATUSES = [
        "Operational",
        "Under Construction",
        "No Application Required"
    ]

    TIER_2_STATUSES = [
        "Planning Permission Granted",
        "Appeal Granted",
        "Secretary of State - Granted"
    ]

    def __init__(self):
        """Initialize the HNPD downloader."""
        logger.info("Initialized HNPD Downloader")
        EXTERNAL_DIR.mkdir(parents=True, exist_ok=True)

    def download_hnpd(self, force_redownload: bool = False) -> bool:
        """
        Download HNPD CSV from GOV.UK.

        Args:
            force_redownload: If True, download even if file exists

        Returns:
            True if successful, False otherwise
        """
        csv_path = EXTERNAL_DIR / "hnpd-january-2024.csv"

        if csv_path.exists() and not force_redownload:
            logger.info(f"HNPD data already downloaded: {csv_path}")
            return True

        logger.info("Downloading BEIS Heat Network Planning Database...")
        logger.info(f"URL: {self.HNPD_URL}")

        try:
            cmd = [
                'wget',
                '--no-check-certificate',
                '--progress=bar:force',
                '-O', str(csv_path),
                self.HNPD_URL
            ]

            result = subprocess.run(cmd, capture_output=False, text=True)

            if result.returncode == 0:
                size_kb = csv_path.stat().st_size / 1024
                logger.info(f"✓ Downloaded HNPD: {size_kb:.0f} KB")
                return True
            else:
                logger.error(f"Download failed with exit code {result.returncode}")
                return False

        except Exception as e:
            logger.error(f"Error downloading HNPD: {e}")
            return False

    def load_hnpd_csv(self, region_filter: Optional[str] = None) -> List[Dict]:
        """
        Load HNPD CSV and return as list of dictionaries.

        Args:
            region_filter: Optional region name (e.g., "London", "South East")

        Returns:
            List of network records as dictionaries
        """
        csv_path = EXTERNAL_DIR / "hnpd-january-2024.csv"

        if not csv_path.exists():
            logger.error(f"HNPD CSV not found: {csv_path}")
            return []

        try:
            with open(csv_path, 'r', encoding='latin-1') as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            if region_filter:
                rows = [r for r in rows if r.get('Region') == region_filter]
                logger.info(f"Filtered to {region_filter}: {len(rows)} records")

            return rows

        except Exception as e:
            logger.error(f"Error loading HNPD CSV: {e}")
            return []

    def load_hnpd_as_geodataframe(self,
                                   region_filter: Optional[str] = None,
                                   status_filter: Optional[List[str]] = None
                                  ) -> Optional[gpd.GeoDataFrame]:
        """
        Load HNPD as GeoDataFrame with point geometries.

        Args:
            region_filter: Optional region (e.g., "London")
            status_filter: Optional list of statuses to include

        Returns:
            GeoDataFrame in EPSG:27700 (British National Grid)
        """
        rows = self.load_hnpd_csv(region_filter=region_filter)

        if not rows:
            return None

        # Filter by status if specified
        if status_filter:
            rows = [r for r in rows
                   if r.get('Development Status') in status_filter]
            logger.info(f"Filtered to statuses {status_filter}: {len(rows)} records")

        # Convert to GeoDataFrame
        geometries = []
        valid_rows = []

        for row in rows:
            try:
                x = float(row.get('X-coordinate', ''))
                y = float(row.get('Y-coordinate', ''))
                geometries.append(Point(x, y))
                valid_rows.append(row)
            except (ValueError, TypeError):
                # Skip records without valid coordinates
                continue

        if not valid_rows:
            logger.warning("No records with valid coordinates found")
            return None

        gdf = gpd.GeoDataFrame(valid_rows, geometry=geometries, crs='EPSG:27700')
        logger.info(f"✓ Created GeoDataFrame: {len(gdf)} networks with coordinates")

        return gdf

    def get_tier_1_networks(self, region: Optional[str] = None) -> Optional[gpd.GeoDataFrame]:
        """Get existing/under construction networks (Tier 1 sources)."""
        return self.load_hnpd_as_geodataframe(
            region_filter=region,
            status_filter=self.TIER_1_STATUSES
        )

    def get_tier_2_networks(self, region: Optional[str] = None) -> Optional[gpd.GeoDataFrame]:
        """Get planned networks with permission (Tier 2 sources)."""
        return self.load_hnpd_as_geodataframe(
            region_filter=region,
            status_filter=self.TIER_2_STATUSES
        )

    def get_data_summary(self) -> Dict:
        """Get summary of available HNPD data."""
        csv_path = EXTERNAL_DIR / "hnpd-january-2024.csv"

        if not csv_path.exists():
            return {
                'available': False,
                'message': 'HNPD not downloaded yet'
            }

        rows = self.load_hnpd_csv()

        return {
            'available': True,
            'total_records': len(rows),
            'tier_1_networks': len([r for r in rows if r.get('Development Status') in self.TIER_1_STATUSES]),
            'tier_2_networks': len([r for r in rows if r.get('Development Status') in self.TIER_2_STATUSES]),
            'regions': list(set(r.get('Region', '') for r in rows if r.get('Region'))),
            'csv_path': str(csv_path)
        }


def main():
    """Example usage."""
    downloader = HNPDDownloader()

    # Download data
    success = downloader.download_hnpd()

    if success:
        # Show summary
        summary = downloader.get_data_summary()
        print("\nHNPD Summary:")
        print(f"  Total records: {summary['total_records']}")
        print(f"  Tier 1 networks: {summary['tier_1_networks']}")
        print(f"  Tier 2 networks: {summary['tier_2_networks']}")
        print(f"  Regions: {len(summary['regions'])}")

        # Load London networks
        london_tier1 = downloader.get_tier_1_networks(region="London")
        if london_tier1 is not None:
            print(f"\nLondon Tier 1 Networks: {len(london_tier1)}")
            print(london_tier1[['Site Name', 'Development Status', 'Post Code']].head())


if __name__ == "__main__":
    main()
```

---

## Next Steps

1. **Review this analysis** with stakeholders
2. **Approve integration approach** (Priority 1 recommended)
3. **Implement HNPD downloader** as designed above
4. **Update heat network analysis** to use HNPD for Tiers 1-2
5. **Test on London data** to validate accuracy improvement
6. **Update documentation** with new data sources

---

## Appendix: Sample HNPD Records

### London Operational Network (Tier 1)

```
Site Name: Springfield Hospital
Status: Under Construction
Type: District
Coordinates: (527307, 172337) [EPSG:27700]
Postcode: SW17 7DJ
Region: London
Country: England
```

### London Planned Network (Tier 2)

```
Site Name: Ruskin Square Development
Status: Under Construction
Type: District
Coordinates: (532835, 165717) [EPSG:27700]
Postcode: CR0 1LF
Region: London
Country: England
```

---

**Document Status:** Draft for Review
**Author:** HeatStreet Analysis Team
**Last Updated:** 2026-01-18
