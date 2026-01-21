"""
Spatial Analysis Module for Heat Network Overlay

Analyzes property locations relative to existing/planned heat networks.
Implements Section 3.3 and 4.1 of the project specification.
"""

import io
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from loguru import logger
import numpy as np
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
from tqdm import tqdm

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import (
    load_config,
    DATA_PROCESSED_DIR,
    DATA_SUPPLEMENTARY_DIR,
    DATA_OUTPUTS_DIR
)
from src.acquisition.london_gis_downloader import LondonGISDownloader
from src.acquisition.hnpd_downloader import HNPDDownloader
from src.spatial.postcode_geocoder import PostcodeGeocoder
from src.utils.profiling import (
    profile_enabled, log_memory, log_dataframe_info, log_dtype, timed_section
)


class HeatNetworkAnalyzer:
    """
    Analyzes properties relative to heat network infrastructure and zones.

    AUDIT FIX: Added documentation about tier classification assumptions and
    limitations per audit findings on Phase 7 (Spatial Analysis).

    HEAT NETWORK TIER DEFINITIONS:
    ==============================

    Tier 1 - Adjacent to Existing Network (within 250m)
    ---------------------------------------------------
    Properties within 250m of existing district heating infrastructure.
    These have the highest confidence for network connection viability.
    - Connection cost: ~£5,000 (service connection + HIU only)
    - Infrastructure: Already built, minimal new pipes needed
    - Confidence: HIGH

    Tier 2 - Within Planned Heat Network Zone
    -----------------------------------------
    Properties inside borough-designated heat priority areas.
    These areas have been identified for potential network development.
    - Connection cost: ~£5,000-8,000 (depends on timing vs network build)
    - Infrastructure: Planned but not yet built
    - Confidence: MEDIUM (depends on network actually being built)

    Tier 3 - High Heat Density (≥15 GWh/km²)
    ----------------------------------------
    Properties in areas with sufficient heat load density to economically
    justify network extension.
    - Connection cost: ~£8,000-12,000 (includes share of local distribution)
    - Infrastructure: Would require new network construction
    - Confidence: MEDIUM (economic viability depends on uptake rate)

    Tier 4 - Moderate Heat Density (5-15 GWh/km²)
    ---------------------------------------------
    Properties in areas with marginal heat density. Network extension may
    be viable with public subsidy or high uptake rates.
    - Connection cost: ~£12,000-18,000 (higher infrastructure share)
    - Recommended pathway: Individual heat pumps preferred
    - Confidence: LOW for network, HIGH for heat pump

    Tier 5 - Low Heat Density (<5 GWh/km²)
    --------------------------------------
    Properties in areas where district heating is not economically viable.
    Individual heat pumps are the clear pathway.
    - Network not recommended
    - Recommended pathway: Individual ASHP
    - Confidence: HIGH for heat pump pathway

    IMPORTANT LIMITATIONS & CAVEATS:
    ================================

    1. DENSITY-ONLY CLASSIFICATION
       The tier classification uses heat density as primary criterion.
       Real-world network viability also depends on:
       - Anchor heat loads (hospitals, leisure centres, etc.)
       - Right-of-way access for pipe installation
       - Street layout and trenching difficulty
       - Local authority support and planning
       - Existing infrastructure (gas, water, etc.)

    2. COST ASSUMPTIONS
       The ~£5,000 connection cost represents ONLY:
       - Service pipe connection from street to property
       - Heat Interface Unit (HIU) installation
       - Internal plumbing modifications

       It DOES NOT include:
       - Energy centre/generation plant (£10-50M per network)
       - Primary distribution network (£500-2000/m pipe)
       - Secondary distribution (£200-500/m pipe)

       If infrastructure costs were allocated per dwelling, the effective
       cost would be £10,000-15,000+ for new networks.

    3. CARBON INTENSITY ASSUMPTION
       The analysis assumes low-carbon heat supply (0.073 kgCO2/kWh).
       Early-stage networks may use gas CHP (0.15-0.20 kgCO2/kWh),
       reducing the carbon benefit until the network decarbonises.

    4. 72% "NETWORK VIABLE" CAVEAT
       The finding that ~72% of properties are in Tiers 1-3 should be
       interpreted as "potentially viable for network IF network is built
       in their area" - not as "72% will definitely get a network".
       Actual network deployment depends on policy, funding, and uptake.
    """

    def __init__(self):
        """Initialize the heat network analyzer."""
        self.config = load_config()

        # Heat network tier definitions were originally stored under
        # analysis. The config now keeps them under eligibility, so allow
        # both locations to avoid a hard failure when the analysis block
        # omits them.
        analysis_cfg = self.config.get('analysis', {})
        eligibility_cfg = self.config.get('eligibility', {})
        self.heat_network_tiers = (
            analysis_cfg.get('heat_network_tiers')
            or eligibility_cfg.get('heat_network_tiers')
        )

        if not self.heat_network_tiers:
            raise KeyError(
                "Missing heat network tier configuration. Expected at "
                "config['analysis']['heat_network_tiers'] or "
                "config['eligibility']['heat_network_tiers']."
            )
        self.readiness_config = self.config.get('heat_network', {}).get('readiness', {})
        self.gis_downloader = LondonGISDownloader()
        self.hnpd_downloader = HNPDDownloader()

        # Initialize postcode geocoder with caching
        cache_file = DATA_PROCESSED_DIR / "geocoding_cache.csv"
        self.geocoder = PostcodeGeocoder(cache_file=cache_file)

        logger.info("Initialized Heat Network Analyzer")

    def download_london_gis_data(self, force_redownload: bool = False) -> bool:
        """
        Download London GIS data from London Datastore.

        Args:
            force_redownload: If True, download even if data already exists

        Returns:
            True if successful, False otherwise
        """
        return self.gis_downloader.download_and_prepare(force_redownload=force_redownload)

    def load_london_heat_map_data(
        self,
        heat_networks_file: Optional[Path] = None,
        heat_zones_file: Optional[Path] = None,
        auto_download: bool = True
    ) -> Tuple[Optional[gpd.GeoDataFrame], Optional[gpd.GeoDataFrame]]:
        """
        Load London Heat Map data for heat networks and zones.

        If files are not specified, automatically attempts to use downloaded
        London Datastore GIS data.

        Args:
            heat_networks_file: Path to existing heat networks shapefile/geojson
            heat_zones_file: Path to Heat Network Zones shapefile/geojson
            auto_download: If True, automatically download GIS data if not present

        Returns:
            Tuple of (heat networks GeoDataFrame, heat zones GeoDataFrame)
        """
        logger.info("Loading London Heat Map data...")

        heat_networks = None
        heat_zones = None

        # If no files specified, try to use downloaded GIS data
        if not heat_networks_file:
            # Check if GIS data is available
            summary = self.gis_downloader.get_data_summary()

            if not summary['available'] and auto_download:
                logger.info("GIS data not found. Downloading from London Datastore...")
                if self.download_london_gis_data():
                    summary = self.gis_downloader.get_data_summary()

            if summary['available']:
                # Get existing networks file
                network_files = self.gis_downloader.get_network_files()
                if 'existing' in network_files:
                    heat_networks_file = network_files['existing']
                    logger.info(f"Using downloaded heat networks: {heat_networks_file}")

                # Also load potential networks as zones
                if 'potential_networks' in network_files:
                    heat_zones_file = network_files['potential_networks']
                    logger.info(f"Using potential networks as zones: {heat_zones_file}")

        # Try to load heat networks
        if heat_networks_file and heat_networks_file.exists():
            try:
                heat_networks = gpd.read_file(heat_networks_file)
                logger.info(f"✓ Loaded {len(heat_networks)} existing heat network features")
            except Exception as e:
                logger.error(f"Error loading heat networks: {e}")
        else:
            logger.warning("Heat networks file not found.")
            logger.info("You can download from: https://data.london.gov.uk/dataset/london-heat-map")

        # Try to load heat network zones
        if heat_zones_file and heat_zones_file.exists():
            try:
                heat_zones = gpd.read_file(heat_zones_file)
                logger.info(f"✓ Loaded {len(heat_zones)} heat network zone features")
            except Exception as e:
                logger.error(f"Error loading heat zones: {e}")
        else:
            logger.warning("Heat network zones file not found.")

        return heat_networks, heat_zones

    def load_hnpd_data(
        self,
        region: Optional[str] = None,
        auto_download: bool = True,
        use_tier_2: bool = True
    ) -> Tuple[Optional[gpd.GeoDataFrame], Optional[gpd.GeoDataFrame]]:
        """
        Load BEIS Heat Network Planning Database (HNPD) data.

        This provides more current heat network data (2024) compared to
        the London Heat Map (2012). HNPD covers all of UK, not just London.

        Args:
            region: Optional region filter (e.g., "London", "South East")
                   If None, loads all UK records
            auto_download: If True, automatically download HNPD if not present
            use_tier_2: If True, also load Tier 2 (planned) networks

        Returns:
            Tuple of (tier_1_networks GeoDataFrame, tier_2_networks GeoDataFrame)
            - tier_1_networks: Operational + Under Construction networks
            - tier_2_networks: Planning Permission Granted networks (or None if use_tier_2=False)
        """
        logger.info("Loading BEIS Heat Network Planning Database (HNPD)...")

        # Check if HNPD is available
        summary = self.hnpd_downloader.get_data_summary()

        if not summary['available'] and auto_download:
            logger.info("HNPD not found. Downloading from GOV.UK...")
            if self.hnpd_downloader.download_and_prepare():
                summary = self.hnpd_downloader.get_data_summary()

        if not summary['available']:
            logger.warning("HNPD data not available")
            logger.info("Download from: https://www.gov.uk/government/publications/heat-networks-planning-database")
            return None, None

        # Load Tier 1 networks (operational + under construction)
        tier_1_networks = self.hnpd_downloader.get_tier_1_networks(region=region)

        if tier_1_networks is not None:
            logger.info(f"✓ Loaded {len(tier_1_networks)} Tier 1 networks (operational/under construction)")
        else:
            logger.warning("No Tier 1 networks found")

        # Load Tier 2 networks (planning granted) if requested
        tier_2_networks = None
        if use_tier_2:
            tier_2_networks = self.hnpd_downloader.get_tier_2_networks(region=region)

            if tier_2_networks is not None:
                logger.info(f"✓ Loaded {len(tier_2_networks)} Tier 2 networks (planning granted)")
            else:
                logger.warning("No Tier 2 networks found")

        return tier_1_networks, tier_2_networks

    def load_heat_network_data(
        self,
        data_source: str = 'hnpd',
        region: Optional[str] = 'London',
        auto_download: bool = True
    ) -> Tuple[Optional[gpd.GeoDataFrame], Optional[gpd.GeoDataFrame]]:
        """
        Load heat network data from specified source.

        This is a unified interface that can load from either HNPD (2024, UK-wide)
        or London Heat Map (2012, London only).

        Args:
            data_source: 'hnpd' (recommended) or 'london_heat_map'
            region: Region to filter to (for HNPD), or None for all UK
            auto_download: If True, automatically download data if not present

        Returns:
            Tuple of (existing_networks, planned_networks)
        """
        if data_source == 'hnpd':
            logger.info("Using HNPD as heat network data source (2024, UK-wide)")
            return self.load_hnpd_data(region=region, auto_download=auto_download)

        elif data_source == 'london_heat_map':
            logger.info("Using London Heat Map as data source (2012, London only)")
            return self.load_london_heat_map_data(auto_download=auto_download)

        elif data_source == 'both':
            logger.info("Using hybrid approach: HNPD + London Heat Map")

            # Load HNPD first
            hnpd_tier1, hnpd_tier2 = self.load_hnpd_data(region=region, auto_download=auto_download)

            # Load London Heat Map as fallback
            lhm_networks, lhm_zones = self.load_london_heat_map_data(auto_download=auto_download)

            # Merge Tier 1 sources
            if hnpd_tier1 is not None and lhm_networks is not None:
                # Combine both sources, removing duplicates
                # HNPD takes priority as it's more current
                existing_networks = hnpd_tier1
                logger.info(f"✓ Combined networks: {len(existing_networks)} from HNPD")
            elif hnpd_tier1 is not None:
                existing_networks = hnpd_tier1
            else:
                existing_networks = lhm_networks

            # Merge Tier 2 sources
            if hnpd_tier2 is not None and lhm_zones is not None:
                planned_networks = hnpd_tier2
                logger.info(f"✓ Combined planned networks: {len(planned_networks)} from HNPD")
            elif hnpd_tier2 is not None:
                planned_networks = hnpd_tier2
            else:
                planned_networks = lhm_zones

            return existing_networks, planned_networks

        else:
            logger.error(f"Unknown data source: {data_source}")
            logger.info("Valid options: 'hnpd', 'london_heat_map', 'both'")
            return None, None

    def _create_geodataframe_lazy(self, df: pd.DataFrame) -> gpd.GeoDataFrame:
        """
        Create GeoDataFrame with geometry only for rows with valid coordinates.

        Memory-efficient: avoids creating Point objects for rows without coords,
        and avoids DataFrame.copy() operations.

        Args:
            df: DataFrame with LATITUDE and LONGITUDE columns

        Returns:
            GeoDataFrame with geometry column (None for rows without coords)
        """
        log_memory("Creating GeoDataFrame (lazy)", force=True)

        # Check for required columns
        if 'LATITUDE' not in df.columns or 'LONGITUDE' not in df.columns:
            logger.warning("Missing LATITUDE/LONGITUDE columns - cannot create geometry")
            # Create empty geometry Series filled with None
            empty_geometry = pd.Series([None] * len(df), index=df.index, dtype=object)
            return gpd.GeoDataFrame(df, geometry=empty_geometry, crs='EPSG:4326')

        # Find rows with valid coordinates
        has_coords = df['LATITUDE'].notna() & df['LONGITUDE'].notna()
        valid_count = has_coords.sum()

        if valid_count == 0:
            logger.warning("No valid coordinates found")
            # Create empty geometry Series filled with None
            empty_geometry = pd.Series([None] * len(df), index=df.index, dtype=object)
            return gpd.GeoDataFrame(df, geometry=empty_geometry, crs='EPSG:4326')

        # Create geometry Series: None for invalid coords, Point for valid coords
        # This is the correct way to create a GeoDataFrame with mixed geometry
        geometry = pd.Series([None] * len(df), index=df.index, dtype=object)

        # Create Point geometries ONLY for rows with valid coords (memory-efficient)
        # Use gpd.points_from_xy which is faster than list comprehension
        valid_geometry = gpd.points_from_xy(
            df.loc[has_coords, 'LONGITUDE'],
            df.loc[has_coords, 'LATITUDE']
        )
        geometry.loc[has_coords] = valid_geometry

        # Create GeoDataFrame with explicit geometry parameter and CRS
        gdf = gpd.GeoDataFrame(df, geometry=geometry, crs='EPSG:4326')

        logger.info(f"Created GeoDataFrame with {valid_count:,} valid geometries of {len(df):,} rows")
        log_memory("GeoDataFrame created", force=True)

        return gdf

    def geocode_properties(self, df: pd.DataFrame) -> gpd.GeoDataFrame:
        """
        Convert property addresses to geographic coordinates.

        Memory-efficient: uses Series.map for coordinate lookup, creates geometry
        lazily only for rows with valid coordinates.

        Args:
            df: Property DataFrame with postcodes

        Returns:
            GeoDataFrame with property locations
        """
        log_memory("geocode_properties START", force=True)
        logger.info("Geocoding properties...")

        # Check if coordinates already exist with actual values
        if 'LATITUDE' in df.columns and 'LONGITUDE' in df.columns:
            has_coords = df['LATITUDE'].notna() & df['LONGITUDE'].notna()
            coord_count = has_coords.sum()

            if coord_count > 0:
                logger.info(f"Using existing coordinates ({coord_count:,} properties have lat/lon)")
                gdf = self._create_geodataframe_lazy(df)
                log_memory("geocode_properties END (existing coords)", force=True)
                return gdf

        # No lat/lon columns or all NaN - geocode from postcodes
        logger.info("No valid coordinates found - will geocode from postcodes")

        # Find postcode column
        postcode_col = None
        for col in df.columns:
            if 'postcode' in col.lower():
                postcode_col = col
                break

        if not postcode_col:
            logger.error("❌ No postcode column found in EPC data")
            logger.info(f"   Available columns: {', '.join(df.columns[:15].tolist())}...")
            logger.warning("   Cannot geocode without postcodes. Skipping spatial analysis...")
            return None

        logger.info(f"Found postcode column: {postcode_col}")
        logger.info("🌐 Geocoding postcodes using free UK Postcode API (postcodes.io)")
        logger.info("   Results will be cached for faster subsequent runs")

        try:
            # Use memory-efficient in-place geocoding (no df.copy())
            df = self.geocoder.geocode_dataframe_inplace(
                df,
                postcode_column=postcode_col,
                batch_mode=True
            )

            # Create GeoDataFrame with lazy geometry
            gdf = self._create_geodataframe_lazy(df)

            if gdf is None or len(gdf) == 0:
                logger.error("❌ Geocoding failed - no coordinates obtained")
                return None

            logger.info("✓ Geocoding complete!")
            log_memory("geocode_properties END", force=True)
            return gdf

        except Exception as e:
            logger.error(f"❌ Error during geocoding: {e}")
            logger.info("   Alternative options:")
            logger.info("   1. Check your internet connection (API requires network access)")
            logger.info("   2. Try again later (API may be temporarily unavailable)")
            logger.info("   3. Download UK postcode centroids: https://www.freemaptools.com/download-uk-postcode-lat-lng.htm")
            return None

    def classify_heat_network_tiers(
        self,
        properties: gpd.GeoDataFrame,
        heat_networks: Optional[gpd.GeoDataFrame] = None,
        heat_zones: Optional[gpd.GeoDataFrame] = None
    ) -> gpd.GeoDataFrame:
        """
        Classify properties by heat network tier.

        Args:
            properties: GeoDataFrame of properties
            heat_networks: GeoDataFrame of existing heat networks
            heat_zones: GeoDataFrame of heat network zones

        Returns:
            GeoDataFrame with tier classification added
        """
        logger.info("Classifying properties by heat network tier...")
        log_memory("classify_heat_network_tiers START", force=True)

        # Initialize tier column
        properties['heat_network_tier'] = 'Tier 5: Low heat density'
        properties['tier_number'] = 5

        # Ensure CRS match (use British National Grid for distance calculations)
        if properties.crs != 'EPSG:27700':
            properties = properties.to_crs('EPSG:27700')

        # Tier 1: Adjacent to existing network (within 250m)
        if heat_networks is not None:
            logger.info("Identifying Tier 1: Adjacent to existing network...")
            log_memory("Before Tier 1 classification")

            if heat_networks.crs != 'EPSG:27700':
                heat_networks = heat_networks.to_crs('EPSG:27700')

            # Buffer heat networks by 250m
            buffer_distance = self.heat_network_tiers['tier_1']['distance_meters']
            heat_network_buffer = heat_networks.buffer(buffer_distance).unary_union

            # Check which properties are within buffer (vectorized)
            tier_1_mask = properties.geometry.within(heat_network_buffer)
            tier_1_count = tier_1_mask.sum()

            properties.loc[tier_1_mask, 'heat_network_tier'] = 'Tier 1: Adjacent to existing network'
            properties.loc[tier_1_mask, 'tier_number'] = 1

            logger.info(f"  Tier 1: {tier_1_count:,} properties ({tier_1_count/len(properties)*100:.1f}%)")
            log_memory("After Tier 1 classification")

        # Tier 2: Within planned Heat Network Zone
        if heat_zones is not None:
            logger.info("Identifying Tier 2: Within planned HNZ...")
            logger.info(f"  Processing {len(heat_zones):,} heat zone polygons...")

            if heat_zones.crs != 'EPSG:27700':
                logger.info("  Converting heat zones to EPSG:27700...")
                heat_zones = heat_zones.to_crs('EPSG:27700')

            # Use spatial join with bounding box pre-filtering for better performance
            logger.info("  Performing spatial join (optimized with bounding box pre-filtering)...")
            log_memory("Before Tier 2 spatial join")

            # Filter to properties not already classified as Tier 1
            # No .copy() needed - we're only reading from this filtered view
            unclassified_properties = properties[properties['tier_number'] > 2]

            if len(unclassified_properties) > 0:
                # Pre-filter using bounding box to reduce spatial join workload
                # This can reduce processing time by 50-80% for sparse geometries
                zones_bounds = heat_zones.total_bounds  # [minx, miny, maxx, maxy]

                # Filter to properties within bounding box of all heat zones
                props_in_bbox = unclassified_properties.cx[zones_bounds[0]:zones_bounds[2], zones_bounds[1]:zones_bounds[3]]

                if len(props_in_bbox) > 0:
                    logger.info(f"  Bounding box filter: {len(props_in_bbox):,} of {len(unclassified_properties):,} properties to check")

                    # Use sjoin to find properties within any heat zone
                    # This is much faster than unary_union + within for complex geometries
                    joined = gpd.sjoin(
                        props_in_bbox[['geometry']],
                        heat_zones[['geometry']],
                        how='left',
                        predicate='within'
                    )
                else:
                    # No properties in bounding box - create empty result
                    joined = gpd.GeoDataFrame(columns=['geometry', 'index_right'])

                log_memory("After Tier 2 spatial join")

                # Properties with a match are within a heat zone
                tier_2_indices = joined[joined.index_right.notna()].index.unique()
                tier_2_count = len(tier_2_indices)

                # Update properties
                properties.loc[tier_2_indices, 'heat_network_tier'] = 'Tier 2: Within planned HNZ'
                properties.loc[tier_2_indices, 'tier_number'] = 2

                logger.info(f"  ✓ Tier 2: {tier_2_count:,} properties ({tier_2_count/len(properties)*100:.1f}%)")
            else:
                logger.info("  ✓ Tier 2: 0 properties (all already classified as Tier 1)")

        # Tiers 3-5: Based on heat density (would require heat demand data)
        # This is a simplified placeholder - actual implementation would calculate
        # linear heat density from property characteristics and street layout

        properties = self._classify_heat_density_tiers(properties)

        # Summary
        tier_summary = properties['heat_network_tier'].value_counts().sort_index()
        logger.info("\nHeat Network Tier Summary:")
        for tier, count in tier_summary.items():
            logger.info(f"  {tier}: {count:,} ({count/len(properties)*100:.1f}%)")

        log_memory("classify_heat_network_tiers END", force=True)
        return properties

    def annotate_heat_network_readiness(
        self,
        df: pd.DataFrame,
        auto_download_gis: bool = True
    ) -> Optional[pd.DataFrame]:
        """
        Append deterministic heat network readiness flags to the EPC DataFrame.

        Adds:
        - ``hn_ready``: Boolean flag for HN eligibility
        - ``tier_number``: Integer tier classification (1-5)
        - ``distance_to_network_m``: Distance to nearest existing network (meters)
        - ``in_heat_zone``: Whether property lies inside a heat network zone polygon

        Returns the input DataFrame with the above columns populated. If spatial
        artefacts (coordinates or GIS data) are unavailable, the original
        DataFrame is returned with default "not ready" flags.
        """

        readiness_cols = ['hn_ready', 'tier_number', 'distance_to_network_m', 'in_heat_zone']

        # Avoid rework if already annotated
        if set(readiness_cols).issubset(df.columns):
            return df

        properties_gdf = self.geocode_properties(df)

        if properties_gdf is None or len(properties_gdf) == 0:
            logger.warning("Heat network readiness skipped: no geocoded properties available.")
            # Add columns in-place without copying
            df['hn_ready'] = False
            df['tier_number'] = df.get('tier_number', 5)
            df['distance_to_network_m'] = np.nan
            df['in_heat_zone'] = False
            return df

        # Use HNPD by default (2024 data), fallback to London Heat Map if needed
        # Can be configured via config file in future
        data_source = self.config.get('data_sources', {}).get('heat_networks', {}).get('primary', 'hnpd')
        region_filter = self.config.get('data_sources', {}).get('heat_networks', {}).get('hnpd', {}).get('region_filter', 'London')

        heat_networks, heat_zones = self.load_heat_network_data(
            data_source=data_source,
            region=region_filter,
            auto_download=auto_download_gis
        )

        if heat_networks is None and heat_zones is None:
            logger.warning("Heat network readiness skipped: GIS network/zone layers unavailable.")
            # Add columns in-place without copying
            df['hn_ready'] = False
            df['tier_number'] = df.get('tier_number', 5)
            df['distance_to_network_m'] = np.nan
            df['in_heat_zone'] = False
            return df

        classified = self.classify_heat_network_tiers(properties_gdf, heat_networks, heat_zones)

        # Compute distance to nearest existing network (meters)
        # Using vectorized distance calculation instead of .apply() for much better performance
        classified['distance_to_network_m'] = np.nan
        if heat_networks is not None and len(heat_networks) > 0:
            log_memory("Before distance calculation")
            networks_27700 = heat_networks.to_crs('EPSG:27700') if heat_networks.crs != 'EPSG:27700' else heat_networks
            network_union = networks_27700.unary_union
            classified_27700 = classified.to_crs('EPSG:27700')

            # Vectorized distance calculation (much faster than .apply())
            classified['distance_to_network_m'] = classified_27700.geometry.distance(network_union)
            log_memory("After distance calculation")

        # Flag whether property sits inside a heat network zone polygon
        # Using bounding box pre-filtering for better performance
        classified['in_heat_zone'] = False
        if heat_zones is not None and len(heat_zones) > 0:
            log_memory("Before zone classification")
            zones_27700 = heat_zones.to_crs('EPSG:27700') if heat_zones.crs != 'EPSG:27700' else heat_zones
            classified_27700 = classified.to_crs('EPSG:27700')

            # Pre-filter using bounding box to reduce spatial join workload
            zones_bounds = zones_27700.total_bounds  # [minx, miny, maxx, maxy]
            props_in_bbox = classified_27700.cx[zones_bounds[0]:zones_bounds[2], zones_bounds[1]:zones_bounds[3]]

            if len(props_in_bbox) > 0:
                zone_join = gpd.sjoin(
                    props_in_bbox[['geometry']],
                    zones_27700[['geometry']],
                    how='left',
                    predicate='within'
                )
                classified.loc[zone_join.index, 'in_heat_zone'] = zone_join.index_right.notna().values

            log_memory("After zone classification")

        # Derive deterministic readiness flag
        max_distance = self.readiness_config.get('max_distance_to_network_m', 250)
        min_density = self.readiness_config.get('min_density_gwh_km2', 5)
        ready_tier_max = self.readiness_config.get('ready_tier_max', 4)
        include_zones = self.readiness_config.get('heat_zone_ready', True)

        classified['hn_ready'] = (
            (classified.get('tier_number', 5) <= ready_tier_max) |
            (classified['distance_to_network_m'] <= max_distance) |
            (classified.get('heat_density_gwh_km2', np.nan) >= min_density) |
            (classified['in_heat_zone'] if include_zones else False)
        )

        readiness_df = classified[readiness_cols]
        readiness_df['tier_number'] = pd.to_numeric(readiness_df['tier_number'], errors='coerce').fillna(5).astype(int)

        # Add columns in-place without copying the full DataFrame
        for col in readiness_cols:
            df[col] = readiness_df.get(col)

        df['hn_ready'] = df['hn_ready'].fillna(False).astype(bool)
        df['in_heat_zone'] = df['in_heat_zone'].fillna(False).astype(bool)
        df['tier_number'] = df['tier_number'].fillna(5).astype(int)

        return df

    def _classify_heat_density_tiers(
        self,
        properties: gpd.GeoDataFrame
    ) -> gpd.GeoDataFrame:
        """
        Classify properties by heat density (Tiers 3-5).

        Calculates heat density using spatial aggregation on a grid.
        Tiers based on GWh/km² thresholds:
        - Tier 3: >15 GWh/km² (High density)
        - Tier 4: 5-15 GWh/km² (Medium density)
        - Tier 5: <5 GWh/km² (Low density)

        Args:
            properties: GeoDataFrame with properties

        Returns:
            GeoDataFrame with heat density tiers assigned
        """
        logger.info("Calculating heat density tiers using spatial aggregation...")

        # Check if spatial analysis is disabled
        spatial_config = self.config.get('spatial', {})
        if spatial_config.get('disable', False):
            logger.warning("Spatial analysis is disabled in config. Skipping heat density calculation.")
            return properties

        # For properties not already classified as Tier 1 or 2
        unclassified_mask = properties['tier_number'] > 2
        unclassified_count = unclassified_mask.sum()

        logger.info(f"  Analyzing {unclassified_count:,} unclassified properties...")

        if 'ENERGY_CONSUMPTION_CURRENT' not in properties.columns:
            logger.warning("No energy consumption data - using simplified tertile method")
            return self._classify_by_tertiles(properties, unclassified_mask)

        # Check which method to use
        spatial_method = spatial_config.get('method', 'grid')

        if spatial_method == 'grid':
            logger.info("  Using grid-based neighborhood aggregation (memory-efficient)")
            return self._classify_heat_density_tiers_grid(properties, unclassified_mask)
        elif spatial_method == 'buffer':
            logger.info("  Using buffer-based spatial join (legacy method)")
            return self._classify_heat_density_tiers_buffer(properties, unclassified_mask)
        else:
            logger.warning(f"Unknown spatial method '{spatial_method}'. Falling back to grid method.")
            return self._classify_heat_density_tiers_grid(properties, unclassified_mask)

    def _classify_heat_density_tiers_grid(
        self,
        properties: gpd.GeoDataFrame,
        unclassified_mask: pd.Series
    ) -> gpd.GeoDataFrame:
        """
        Classify properties by heat density using grid-based aggregation.

        This method is memory-efficient and scalable for large datasets (100k+ properties).
        Instead of creating buffers around each property, it:
        1. Assigns properties to grid cells
        2. Aggregates energy consumption per cell
        3. Computes neighborhood totals using cell offsets
        4. Assigns neighborhood values back to properties

        Args:
            properties: GeoDataFrame with all properties
            unclassified_mask: Boolean mask for properties not in Tier 1-2

        Returns:
            GeoDataFrame with heat density tiers assigned
        """
        import time

        overall_start = time.time()

        # Profiling: Log initial state
        log_memory("Grid classification START")
        log_dataframe_info(properties, "Input properties")
        logger.info(f"  Processing {len(properties):,} total properties, {unclassified_mask.sum():,} unclassified")

        spatial_config = self.config.get('spatial', {})
        grid_config = spatial_config.get('grid', {})

        # Get grid parameters from config
        cell_size_m = grid_config.get('cell_size_m', 125)
        buffer_radius_m = grid_config.get('buffer_radius_m', 250)
        use_circular_mask = grid_config.get('use_circular_mask', True)

        logger.info(f"  Grid parameters: cell_size={cell_size_m}m, radius={buffer_radius_m}m, circular_mask={use_circular_mask}")

        # Ensure we're in British National Grid (meters)
        if properties.crs != 'EPSG:27700':
            logger.info("  Converting to EPSG:27700 (British National Grid)...")
            properties_27700 = properties.to_crs('EPSG:27700')
        else:
            # No copy needed - we can work directly on the input GeoDataFrame
            properties_27700 = properties

        # Calculate absolute energy consumption for all properties
        logger.info(f"  Step 1/5: Calculating absolute energy consumption...")
        if 'TOTAL_FLOOR_AREA' in properties_27700.columns:
            properties_27700['_absolute_energy_kwh'] = (
                properties_27700['ENERGY_CONSUMPTION_CURRENT'] * properties_27700['TOTAL_FLOOR_AREA']
            )
        else:
            properties_27700['_absolute_energy_kwh'] = properties_27700['ENERGY_CONSUMPTION_CURRENT']

        # Extract coordinates (vectorized - much faster and memory-efficient)
        logger.info(f"  Step 2/5: Assigning properties to grid cells (cell_size={cell_size_m}m)...")
        start_time = time.time()

        # Use vectorized extraction instead of list comprehension
        x_coords = properties_27700.geometry.x.values
        y_coords = properties_27700.geometry.y.values

        # Assign each property to a grid cell
        cell_x = np.floor(x_coords / cell_size_m).astype(np.int64)
        cell_y = np.floor(y_coords / cell_size_m).astype(np.int64)

        # Create single integer cell_id for fast lookups (avoids tuple overhead)
        # Use a large multiplier to ensure no collisions
        y_range = cell_y.max() - cell_y.min() + 1
        multiplier = max(100000, int(y_range * 10))  # Ensure no collisions

        properties_27700['_cell_id'] = (cell_x * multiplier + cell_y).astype(np.int64)

        # Count unique cells
        unique_cells = properties_27700['_cell_id'].nunique()
        logger.info(f"  ✓ Assigned {len(properties_27700):,} properties to {unique_cells:,} grid cells ({time.time() - start_time:.1f}s)")

        # Aggregate to cell level
        logger.info(f"  Step 3/5: Aggregating energy consumption per cell...")
        start_time = time.time()

        # Add cell_x and cell_y columns BEFORE groupby (fix for column access bug)
        properties_27700['_cell_x'] = cell_x
        properties_27700['_cell_y'] = cell_y

        cell_aggregates = properties_27700.groupby('_cell_id').agg({
            '_absolute_energy_kwh': 'sum',
            'geometry': 'count'  # Count properties per cell
        }).rename(columns={'geometry': 'property_count'})

        # Get cell_x and cell_y for offset calculations
        cell_coords = properties_27700.groupby('_cell_id')[['_cell_x', '_cell_y']].first()
        cell_aggregates = cell_aggregates.join(cell_coords)

        logger.info(f"  ✓ Aggregated to {len(cell_aggregates):,} populated cells ({time.time() - start_time:.1f}s)")

        # Compute neighbor cell offsets for the given radius
        logger.info(f"  Step 4/5: Computing neighborhood totals (radius={buffer_radius_m}m)...")
        start_time = time.time()

        # Calculate how many cells to look in each direction
        max_cell_distance = int(np.ceil(buffer_radius_m / cell_size_m))

        # Generate all possible cell offsets within the radius
        offsets = []
        for dx in range(-max_cell_distance, max_cell_distance + 1):
            for dy in range(-max_cell_distance, max_cell_distance + 1):
                if use_circular_mask:
                    # Only include offsets where cell center is within radius
                    # Cell centers are at (dx * cell_size + cell_size/2, dy * cell_size + cell_size/2)
                    center_dist = np.sqrt((dx * cell_size_m) ** 2 + (dy * cell_size_m) ** 2)
                    if center_dist <= buffer_radius_m:
                        offsets.append((dx, dy))
                else:
                    # Use square Chebyshev distance (faster)
                    offsets.append((dx, dy))

        logger.info(f"  Using {len(offsets)} cell offsets for neighborhood aggregation")

        # Fully vectorized neighborhood computation using pandas Series.map()
        # Extract arrays from cell_aggregates (avoid iterrows)
        cell_ids = cell_aggregates.index.values.astype(np.int64)
        cell_x_arr = cell_aggregates['_cell_x'].values.astype(np.int64)
        cell_y_arr = cell_aggregates['_cell_y'].values.astype(np.int64)

        n_cells = len(cell_ids)

        # Create Series for O(1) vectorized lookups: cell_id -> value
        energy_series = pd.Series(
            cell_aggregates['_absolute_energy_kwh'].values,
            index=cell_ids,
            dtype=np.float64
        )
        count_series = pd.Series(
            cell_aggregates['property_count'].values,
            index=cell_ids,
            dtype=np.int64
        )

        # Initialize accumulators
        neighborhood_energy = np.zeros(n_cells, dtype=np.float64)
        neighborhood_count = np.zeros(n_cells, dtype=np.int64)

        # For each offset, compute neighbor cell_ids vectorized and lookup values
        # This is O(n_offsets) iterations with O(n_cells) vectorized ops each
        for dx, dy in offsets:
            # Compute neighbor cell_ids for all cells at this offset (vectorized)
            neighbor_cell_ids = ((cell_x_arr + dx) * multiplier + (cell_y_arr + dy)).astype(np.int64)

            # Vectorized lookup using Series.map() - returns NaN for missing
            neighbor_energy = energy_series.reindex(neighbor_cell_ids).values
            neighbor_count = count_series.reindex(neighbor_cell_ids).values

            # Accumulate (NaN becomes 0)
            neighborhood_energy += np.nan_to_num(neighbor_energy, nan=0.0)
            neighborhood_count += np.nan_to_num(neighbor_count, nan=0).astype(np.int64)

        # Create result DataFrame with int64 index to match properties
        neighborhood_df = pd.DataFrame({
            'neighborhood_energy_kwh': neighborhood_energy,
            'neighborhood_property_count': neighborhood_count
        }, index=pd.Index(cell_ids, dtype=np.int64, name='cell_id'))

        logger.info(f"  ✓ Computed neighborhood totals for {len(neighborhood_df):,} cells ({time.time() - start_time:.1f}s)")

        # Assign neighborhood values back to properties using memory-efficient Series.map()
        # (avoids DataFrame.join which creates a full copy)
        logger.info(f"  Step 5a/5: Mapping neighborhood totals to properties...")
        start_time_join = time.time()

        # Log RSS before mapping
        rss_before = log_memory("Before Step 5a mapping", force=True)

        # Ensure cell_id is int64 for fast hash lookups
        cell_id_col = properties_27700['_cell_id'].astype(np.int64)

        # Create Series for each neighborhood value (indexed by int64 cell_id)
        # neighborhood_df already has int64 index from earlier
        neigh_energy_series = neighborhood_df['neighborhood_energy_kwh']
        neigh_count_series = neighborhood_df['neighborhood_property_count']

        # Log dtypes to verify
        log_dtype(cell_id_col, "properties._cell_id")
        log_dtype(neigh_energy_series.index.to_series(), "neighborhood_df.index")

        # Map values using Series.map() - much more memory efficient than join
        # This avoids creating a copy of the entire DataFrame
        properties_27700['neighborhood_energy_kwh'] = cell_id_col.map(neigh_energy_series).fillna(0.0)
        properties_27700['neighborhood_property_count'] = cell_id_col.map(neigh_count_series).fillna(0).astype(np.int64)

        # Log RSS after mapping
        rss_after = log_memory("After Step 5a mapping", force=True)
        logger.info(f"  ✓ Neighborhood mapping complete ({time.time() - start_time_join:.1f}s, RSS delta: {rss_after - rss_before:+.1f} MB)")

        # Calculate heat density in GWh/km² (vectorized)
        logger.info(f"  Step 5b/5: Calculating heat densities and classifying tiers...")
        start_time_classify = time.time()

        buffer_area_km2 = (np.pi * buffer_radius_m ** 2) / 1_000_000
        properties_27700['heat_density_gwh_km2'] = (
            properties_27700['neighborhood_energy_kwh'] / 1_000_000
        ) / buffer_area_km2

        # Vectorized tier classification using np.select
        tier_3_threshold = self.heat_network_tiers['tier_3']['min_heat_density_gwh_km2']
        tier_4_threshold = self.heat_network_tiers['tier_4']['min_heat_density_gwh_km2']

        # Only classify unclassified properties (tier_number > 2)
        density = properties_27700.loc[unclassified_mask, 'heat_density_gwh_km2']

        # Create conditions for np.select
        conditions = [
            density >= tier_3_threshold,
            density >= tier_4_threshold
        ]

        tier_numbers = [3, 4]
        tier_labels = [
            'Tier 3: High heat density',
            'Tier 4: Medium heat density'
        ]

        # Apply tier numbers (default is 5, which is already set)
        properties.loc[unclassified_mask, 'tier_number'] = np.select(
            conditions,
            tier_numbers,
            default=5  # Tier 5 for everything else
        )

        # Apply tier labels
        properties.loc[unclassified_mask, 'heat_network_tier'] = np.select(
            conditions,
            tier_labels,
            default='Tier 5: Low heat density'
        )

        # Copy heat density values to original properties DataFrame
        properties.loc[unclassified_mask, 'heat_density_gwh_km2'] = properties_27700.loc[unclassified_mask, 'heat_density_gwh_km2']

        logger.info(f"  ✓ Tier classification complete ({time.time() - start_time_classify:.1f}s)")

        # Clean up temporary columns
        properties_27700.drop(columns=['_cell_id', '_cell_x', '_cell_y', '_absolute_energy_kwh',
                                       'neighborhood_energy_kwh', 'neighborhood_property_count'],
                             inplace=True, errors='ignore')

        tier_3_count = (properties['tier_number'] == 3).sum()
        tier_4_count = (properties['tier_number'] == 4).sum()
        tier_5_count = (properties['tier_number'] == 5).sum()

        total_step5_time = time.time() - start_time_join
        logger.info(f"  ✓ Step 5 complete: {total_step5_time:.1f}s (join: {time.time() - start_time_join:.1f}s, classify: {time.time() - start_time_classify:.1f}s)")
        logger.info(f"  Tier 3 (High density ≥{self.heat_network_tiers['tier_3']['min_heat_density_gwh_km2']} GWh/km²): {tier_3_count:,}")
        logger.info(f"  Tier 4 (Medium density {self.heat_network_tiers['tier_4']['min_heat_density_gwh_km2']}-{self.heat_network_tiers['tier_3']['min_heat_density_gwh_km2']} GWh/km²): {tier_4_count:,}")
        logger.info(f"  Tier 5 (Low density <{self.heat_network_tiers['tier_4']['min_heat_density_gwh_km2']} GWh/km²): {tier_5_count:,}")

        overall_time = time.time() - overall_start
        log_memory("Grid classification END")
        logger.info(f"  ═══════════════════════════════════════════════════════════")
        logger.info(f"  Grid-based classification COMPLETE in {overall_time:.1f}s total")
        logger.info(f"  ═══════════════════════════════════════════════════════════")

        return properties

    def _classify_heat_density_tiers_buffer(
        self,
        properties: gpd.GeoDataFrame,
        unclassified_mask: pd.Series
    ) -> gpd.GeoDataFrame:
        """
        Classify properties by heat density using buffer-based spatial join (legacy method).

        WARNING: This method is memory-intensive and may cause OOM errors with large datasets.
        Use grid-based method instead for 50k+ properties.

        Args:
            properties: GeoDataFrame with all properties
            unclassified_mask: Boolean mask for properties not in Tier 1-2

        Returns:
            GeoDataFrame with heat density tiers assigned
        """
        logger.info("  WARNING: Buffer method is memory-intensive for large datasets")
        logger.info("  Consider using grid method (spatial.method='grid') instead")

        try:
            # Legacy buffer-based heat density calculation
            logger.info("  Using vectorized spatial operations for heat density calculation...")
            logger.info("  This may take 2-5 minutes for 10K+ properties...")

            # Ensure we're in British National Grid (meters)
            if properties.crs != 'EPSG:27700':
                properties_27700 = properties.to_crs('EPSG:27700')
            else:
                properties_27700 = properties.copy()

            # Create 500m x 500m grid
            grid_size = 500  # meters

            # Get bounding box
            minx, miny, maxx, maxy = properties_27700.total_bounds

            # Create grid cells
            from shapely.geometry import box
            grid_cells = []
            x_coords = np.arange(minx, maxx, grid_size)
            y_coords = np.arange(miny, maxy, grid_size)

            # Get unclassified properties
            unclassified_props = properties_27700[unclassified_mask].copy()
            logger.info(f"  Step 1/4: Calculating absolute energy consumption...")

            # Calculate absolute energy consumption for all properties
            if 'TOTAL_FLOOR_AREA' in properties_27700.columns:
                properties_27700['_absolute_energy_kwh'] = (
                    properties_27700['ENERGY_CONSUMPTION_CURRENT'] * properties_27700['TOTAL_FLOOR_AREA']
                )
            else:
                properties_27700['_absolute_energy_kwh'] = properties_27700['ENERGY_CONSUMPTION_CURRENT']

            # Create buffers for unclassified properties (vectorized)
            logger.info(f"  Step 2/4: Creating 250m buffers for {len(unclassified_props):,} properties...")
            buffer_radius = 250  # meters
            buffer_area_km2 = (np.pi * buffer_radius**2) / 1_000_000

            # Create a GeoDataFrame with buffered geometries
            unclassified_buffered = unclassified_props.copy()
            unclassified_buffered['geometry'] = unclassified_buffered.geometry.buffer(buffer_radius)
            unclassified_buffered['_buffer_idx'] = unclassified_buffered.index

            # Spatial join to find all properties within each buffer
            logger.info(
                "  Step 3/4: Performing spatial join (slowest step; scales with property count, ~1-3 min per 10K properties — "
                "large runs can take tens of minutes)..."
            )
            import time
            start_time = time.time()

            joined = gpd.sjoin(
                unclassified_buffered[['geometry', '_buffer_idx']],
                properties_27700[['geometry', '_absolute_energy_kwh']],
                how='left',
                predicate='intersects'
            )

            elapsed = time.time() - start_time
            logger.info(f"  ✓ Spatial join completed in {elapsed:.1f} seconds")

            # Aggregate energy consumption per buffer
            logger.info(f"  Step 4/4: Aggregating heat density calculations...")
            heat_density_by_buffer = joined.groupby('_buffer_idx')['_absolute_energy_kwh'].sum()

            # Convert to GWh/km²
            heat_density_gwh_km2 = (heat_density_by_buffer / 1_000_000) / buffer_area_km2

            # Classify tiers based on heat density
            logger.info(
                f"  Classifying {len(heat_density_gwh_km2):,} properties into heat density tiers "
                "(progress bar updates every ~10s)..."
            )
            for idx, density in tqdm(
                heat_density_gwh_km2.items(),
                total=len(heat_density_gwh_km2),
                desc="Heat density tiering",
                mininterval=10,
                unit="properties",
                leave=False,
            ):
                if density >= self.heat_network_tiers['tier_3']['min_heat_density_gwh_km2']:
                    properties.loc[idx, 'heat_network_tier'] = 'Tier 3: High heat density'
                    properties.loc[idx, 'tier_number'] = 3
                    properties.loc[idx, 'heat_density_gwh_km2'] = density
                elif density >= self.heat_network_tiers['tier_4']['min_heat_density_gwh_km2']:
                    properties.loc[idx, 'heat_network_tier'] = 'Tier 4: Medium heat density'
                    properties.loc[idx, 'tier_number'] = 4
                    properties.loc[idx, 'heat_density_gwh_km2'] = density
                else:
                    # Tier 5 (already default)
                    properties.loc[idx, 'heat_density_gwh_km2'] = density

            # Clean up temporary column
            properties_27700.drop(columns=['_absolute_energy_kwh'], inplace=True, errors='ignore')

            tier_3_count = (properties['tier_number'] == 3).sum()
            tier_4_count = (properties['tier_number'] == 4).sum()
            tier_5_count = (properties['tier_number'] == 5).sum()

            logger.info(f"  Tier 3 (High density >15 GWh/km²): {tier_3_count:,}")
            logger.info(f"  Tier 4 (Medium density 5-15 GWh/km²): {tier_4_count:,}")
            logger.info(f"  Tier 5 (Low density <5 GWh/km²): {tier_5_count:,}")

        except Exception as e:
            logger.warning(f"Grid-based calculation failed: {e}. Falling back to tertile method.")
            properties = self._classify_by_tertiles(properties, unclassified_mask)

        return properties

    def _classify_by_tertiles(
        self,
        properties: gpd.GeoDataFrame,
        unclassified_mask: pd.Series
    ) -> gpd.GeoDataFrame:
        """Fallback classification using energy consumption tertiles."""
        logger.info("Classifying heat density tiers using tertile method (fallback)...")

        if 'ENERGY_CONSUMPTION_CURRENT' in properties.columns:
            unclassified_energy = properties.loc[unclassified_mask, 'ENERGY_CONSUMPTION_CURRENT']

            if len(unclassified_energy) > 0:
                # High heat density (top tertile)
                high_threshold = unclassified_energy.quantile(0.67)
                medium_threshold = unclassified_energy.quantile(0.33)

                tier_3_mask = (
                    unclassified_mask &
                    (properties['ENERGY_CONSUMPTION_CURRENT'] >= high_threshold)
                )
                tier_4_mask = (
                    unclassified_mask &
                    (properties['ENERGY_CONSUMPTION_CURRENT'] >= medium_threshold) &
                    (properties['ENERGY_CONSUMPTION_CURRENT'] < high_threshold)
                )

                tier_3_count = tier_3_mask.sum()
                tier_4_count = tier_4_mask.sum()

                properties.loc[tier_3_mask, 'heat_network_tier'] = 'Tier 3: High heat density'
                properties.loc[tier_3_mask, 'tier_number'] = 3

                properties.loc[tier_4_mask, 'heat_network_tier'] = 'Tier 4: Medium heat density'
                properties.loc[tier_4_mask, 'tier_number'] = 4

                logger.info(f"  Tier 3 (High): {tier_3_count:,}")
                logger.info(f"  Tier 4 (Medium): {tier_4_count:,}")

        return properties

    def analyze_pathway_suitability(
        self,
        properties: gpd.GeoDataFrame
    ) -> pd.DataFrame:
        """
        Analyze which decarbonization pathway is most suitable for each tier.

        AUDIT FIX: Ensures all 5 tiers are always present in output, even if
        a tier has 0 properties. This addresses the finding that Tier 2 was
        being skipped when no properties fell into that category.

        Args:
            properties: GeoDataFrame with tier classifications

        Returns:
            DataFrame summarizing pathway suitability by tier
        """
        logger.info("Analyzing decarbonization pathway suitability by tier...")

        # AUDIT FIX: Define all tiers with their full labels and recommendations
        # This ensures all tiers appear in output even if count is 0
        tier_definitions = {
            'Tier 1: Adjacent to existing network': {
                'tier_number': 1,
                'recommendation': 'District Heating (existing network connection)',
                'note': 'Within 250m of existing network infrastructure'
            },
            'Tier 2: Within planned HNZ': {
                'tier_number': 2,
                'recommendation': 'District Heating (planned network)',
                'note': 'Inside borough-designated heat priority areas'
            },
            'Tier 3: High heat density': {
                'tier_number': 3,
                'recommendation': 'District Heating (high density justifies extension)',
                'note': 'Heat density ≥15 GWh/km²'
            },
            'Tier 4: Medium heat density': {
                'tier_number': 4,
                'recommendation': 'Heat Pump (moderate density, network extension marginal)',
                'note': 'Heat density 5-15 GWh/km²'
            },
            'Tier 5: Low heat density': {
                'tier_number': 5,
                'recommendation': 'Heat Pump (low density, network not viable)',
                'note': 'Heat density <5 GWh/km²'
            }
        }

        # Count properties by tier
        tier_counts = properties['heat_network_tier'].value_counts()
        total_properties = len(properties)

        # Create summary with ALL tiers present
        summary_rows = []
        for tier_label, tier_info in tier_definitions.items():
            count = tier_counts.get(tier_label, 0)
            percentage = (count / total_properties * 100) if total_properties > 0 else 0.0

            summary_rows.append({
                'Tier': tier_label,
                'Tier Number': tier_info['tier_number'],
                'Property Count': int(count),
                'Percentage': round(percentage, 1),
                'Recommended Pathway': tier_info['recommendation'],
                'Note': tier_info['note']
            })

        summary = pd.DataFrame(summary_rows)
        summary = summary.sort_values('Tier Number')

        logger.info("\nPathway Suitability Summary (all tiers):")
        for _, row in summary.iterrows():
            count_str = f"{row['Property Count']:,}" if row['Property Count'] > 0 else "0"
            logger.info(f"  {row['Tier']}: {count_str} properties ({row['Percentage']:.1f}%) → {row['Recommended Pathway']}")

        # Add total row for validation
        total_in_tiers = summary['Property Count'].sum()
        if total_in_tiers != total_properties:
            logger.warning(
                f"Tier count mismatch: sum of tiers ({total_in_tiers:,}) != "
                f"total properties ({total_properties:,}). Difference: {total_properties - total_in_tiers:,}"
            )

        return summary

    def create_heat_network_map(
        self,
        properties: gpd.GeoDataFrame,
        output_path: Optional[Path] = None,
        image_output_path: Optional[Path] = None,
        pdf_output_path: Optional[Path] = None,
        heat_networks: Optional[gpd.GeoDataFrame] = None,
        heat_zones: Optional[gpd.GeoDataFrame] = None
    ):
        """
        Create an interactive map showing heat network tiers.

        Args:
            properties: GeoDataFrame with tier classifications
            output_path: Path to save map HTML
            image_output_path: Optional path to save a rendered PNG of the map
            pdf_output_path: Optional path to save a PDF layout including the map
        """
        try:
            import folium
            from folium import plugins
            from PIL import Image
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas
            from reportlab.lib.utils import ImageReader
            from datetime import datetime
            import matplotlib.pyplot as plt
        except ImportError as e:
            logger.warning(
                "Required mapping dependencies are missing; skipping map creation. "
                f"Install the needed packages to enable mapping. Details: {e}"
            )
            return

        def _generate_static_map_image(properties_wgs84: gpd.GeoDataFrame, output_path: Path):
            """Create a static PNG of the classified properties without folium.

            This is used as a fallback when HTML-to-PNG rendering dependencies are
            unavailable to ensure downstream PDF creation still has map imagery.
            """

            import matplotlib.pyplot as plt

            tier_colors = {
                1: "#8B0000",
                2: "#D32F2F",
                3: "#EF6C00",
                4: "#FBC02D",
                5: "#9CCC65",
            }

            if properties_wgs84.crs != "EPSG:4326":
                properties_wgs84 = properties_wgs84.to_crs("EPSG:4326")

            fig, ax = plt.subplots(figsize=(9, 10))
            ax.set_facecolor("#f7f7f7")

            margin = 0.02
            bounds = properties_wgs84.total_bounds
            x_min, y_min, x_max, y_max = bounds
            x_range = x_max - x_min
            y_range = y_max - y_min

            ax.set_xlim(x_min - margin * x_range, x_max + margin * x_range)
            ax.set_ylim(y_min - margin * y_range, y_max + margin * y_range)

            for tier_num, color in tier_colors.items():
                tier_subset = properties_wgs84[properties_wgs84.get("tier_number", 5) == tier_num]
                if len(tier_subset) == 0:
                    continue
                tier_subset.plot(
                    ax=ax,
                    color=color,
                    markersize=10,
                    alpha=0.7,
                    label=f"Tier {tier_num}"
                )

            ax.legend(title="Heat Network Tiers", loc="upper right")
            ax.set_xlabel("Longitude")
            ax.set_ylabel("Latitude")
            ax.set_title("Heat Network Tier Map (static fallback)")
            ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.6)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(output_path, dpi=200, bbox_inches="tight")
            plt.close(fig)

        try:
            logger.info("Creating heat network tier map...")

            if output_path is None:
                output_path = DATA_OUTPUTS_DIR / "maps" / "heat_network_tiers.html"

            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Convert to WGS84 for web map
            if properties.crs != 'EPSG:4326':
                properties = properties.to_crs('EPSG:4326')

            # Calculate center point
            center_lat = properties.geometry.y.mean()
            center_lon = properties.geometry.x.mean()

            # Create map
            m = folium.Map(
                location=[center_lat, center_lon],
                zoom_start=12,
                tiles='CartoDB positron'
            )

            png_generated = False

            try:
                m = folium.Map(
                    location=[center_lat, center_lon],
                    zoom_start=12,
                    tiles=None
                )
                folium.TileLayer(
                    tiles="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
                    attr="&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors"
                         " &copy; <a href='https://carto.com/attributions'>CARTO</a>",
                    name='CartoDB Positron',
                    control=False
                ).add_to(m)
                folium.TileLayer('OpenStreetMap', name='OSM fallback').add_to(m)

                # Color scheme for tiers
                tier_colors = {
                    1: 'darkred',
                    2: 'red',
                    3: 'orange',
                    4: 'yellow',
                    5: 'lightgreen'
                }

                # Add properties as markers (sample if too many)
                sample_size = min(1000, len(properties))
                if len(properties) > sample_size:
                    logger.info(f"Sampling {sample_size} properties for map visualization")
                    properties_sample = properties.sample(sample_size)
                else:
                    properties_sample = properties

                for idx, row in properties_sample.iterrows():
                    if row.geometry is not None:
                        tier_num = row.get('tier_number', 5)
                        folium.CircleMarker(
                            location=[row.geometry.y, row.geometry.x],
                            radius=3,
                            color=tier_colors.get(tier_num, 'gray'),
                            fill=True,
                            fillOpacity=0.6,
                            popup=f"Tier {tier_num}: {row.get('heat_network_tier', 'Unknown')}"
                        ).add_to(m)

                # Add legend
                legend_html = '''
                <div style="position: fixed; bottom: 50px; left: 50px; width: 300px; height: 180px;
                            background-color: white; border:2px solid grey; z-index:9999; font-size:14px;
                            padding: 10px">
                <p><strong>Heat Network Tiers</strong></p>
                <p><i class="fa fa-circle" style="color:darkred"></i> Tier 1: Adjacent to existing network</p>
                <p><i class="fa fa-circle" style="color:red"></i> Tier 2: Within planned HNZ</p>
                <p><i class="fa fa-circle" style="color:orange"></i> Tier 3: High heat density</p>
                <p><i class="fa fa-circle" style="color:yellow"></i> Tier 4: Moderate heat density</p>
                <p><i class="fa fa-circle" style="color:lightgreen"></i> Tier 5: Low heat density</p>
                </div>
                '''
                m.get_root().html.add_child(folium.Element(legend_html))

                # Save map
                m.save(str(output_path))
                logger.info(f"Map saved to: {output_path}")

                # Render to PNG if requested
                if image_output_path:
                    image_output_path.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        png_data = m._to_png(delay=3)
                        image_output_path.write_bytes(png_data)
                        png_generated = True
                        logger.info(f"Map image saved to: {image_output_path}")
                    except Exception as e:
                        logger.warning(
                            "Unable to render map PNG from folium directly. "
                            "Falling back to static renderer."
                        )
                        logger.debug(f"folium _to_png error: {e}")

            except ImportError:
                logger.warning("folium not available; skipping interactive map and HTML export")
            except Exception as e:
                logger.error(f"Error creating interactive map: {e}")

            if not png_generated and image_output_path:
                try:
                    _generate_static_map_image(properties, image_output_path)
                    logger.info(
                        f"Fallback static map image saved to: {image_output_path}"
                    )
                    png_generated = True
                except ImportError:
                    logger.warning(
                        "matplotlib not available; unable to create fallback map image."
                    )
                except Exception as e:
                    logger.error(f"Error creating fallback map image: {e}")

            if pdf_output_path:
                pdf_output_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    if not image_output_path or not image_output_path.exists():
                        logger.warning("Map image not available; skipping PDF export.")
                    else:
                        c = canvas.Canvas(str(pdf_output_path), pagesize=A4)
                        width, height = A4

                        title_text = "Heat Network Tier Map"
                        subtitle_text = f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"

                        c.setFont("Helvetica-Bold", 16)
                        c.drawString(40, height - 60, title_text)
                        c.setFont("Helvetica", 10)
                        c.drawString(40, height - 80, subtitle_text)

                        img_reader = ImageReader(str(image_output_path))
                        img_width, img_height = img_reader.getSize()

                        max_width = width - 80
                        max_height = height - 160
                        scale = min(max_width / img_width, max_height / img_height)

                        display_width = img_width * scale
                        display_height = img_height * scale

                        x_pos = (width - display_width) / 2
                        y_pos = (height - display_height) / 2 - 20

                        c.drawImage(img_reader, x_pos, y_pos, width=display_width, height=display_height)
                        c.showPage()
                        c.save()
                        logger.info(f"Map PDF saved to: {pdf_output_path}")
                except ImportError:
                    logger.warning(
                        "Unable to generate PDF layout because reportlab is not installed. "
                        "Install reportlab to enable PDF export."
                    )
                except Exception as e:
                    logger.error(f"Error creating PDF layout: {e}")

        except Exception as e:
            logger.error(f"Error creating map outputs: {e}")

    def run_complete_analysis(
        self,
        df: pd.DataFrame,
        auto_download_gis: bool = True,
        create_maps: bool = True,
    ) -> Tuple[Optional[gpd.GeoDataFrame], Optional[pd.DataFrame]]:
        """
        Run complete spatial analysis workflow.

        Args:
            df: Validated EPC DataFrame
            auto_download_gis: Automatically download GIS data if not available
            create_maps: Whether to generate interactive map outputs

        Returns:
            Tuple of (classified properties GeoDataFrame, pathway summary DataFrame)
        """
        logger.info("=" * 80)
        logger.info("SPATIAL ANALYSIS: HEAT NETWORK TIER CLASSIFICATION")
        logger.info("=" * 80)

        try:
            # Step 1: Geocode properties
            logger.info("\nStep 1: Geocoding properties...")
            properties_gdf = self.geocode_properties(df)

            if properties_gdf is None:
                logger.warning("❌ Geocoding not available. Spatial analysis cannot proceed.")
                logger.info("")
                logger.info("   Core analysis (archetype, scenarios, visualizations) completed successfully!")
                logger.info("   Add coordinates to enable heat network tier classification.")
                return None, None

            if len(properties_gdf) == 0:
                logger.warning("❌ No properties could be geocoded. Spatial analysis cannot proceed.")
                return None, None

            logger.info(f"✓ Successfully geocoded {len(properties_gdf):,} properties")

            # Step 2: Load GIS data
            logger.info("\nStep 2: Loading heat network GIS data...")
            data_source = self.config.get('data_sources', {}).get('heat_networks', {}).get('primary', 'hnpd')
            region_filter = self.config.get('data_sources', {}).get('heat_networks', {}).get('hnpd', {}).get('region_filter', 'London')

            heat_networks, heat_zones = self.load_heat_network_data(
                data_source=data_source,
                region=region_filter,
                auto_download=auto_download_gis
            )

            if heat_networks is not None:
                logger.info(f"✓ Loaded {len(heat_networks)} existing heat networks")
            if heat_zones is not None:
                logger.info(f"✓ Loaded {len(heat_zones)} potential heat network zones")

            # Step 3: Classify by heat network tiers
            logger.info("\nStep 3: Classifying properties by heat network tier...")
            properties_classified = self.classify_heat_network_tiers(
                properties_gdf,
                heat_networks,
                heat_zones
            )

            logger.info(f"✓ Classified {len(properties_classified):,} properties into 5 tiers")

            # Step 4: Analyze pathway suitability
            logger.info("\nStep 4: Analyzing decarbonization pathway suitability...")
            pathway_summary = self.analyze_pathway_suitability(properties_classified)

            logger.info("✓ Pathway analysis complete")

            # Step 5: Save results
            logger.info("\nStep 5: Saving results...")

            # Save classified properties
            output_file = DATA_PROCESSED_DIR / "epc_with_heat_network_tiers.geojson"
            output_file.parent.mkdir(parents=True, exist_ok=True)
            properties_classified.to_file(output_file, driver='GeoJSON')
            logger.info(f"✓ Saved classified properties: {output_file}")

            # Save pathway summary
            pathway_file = DATA_OUTPUTS_DIR / "pathway_suitability_by_tier.csv"
            pathway_file.parent.mkdir(parents=True, exist_ok=True)
            pathway_summary.to_csv(pathway_file, index=False)
            logger.info(f"✓ Saved pathway summary: {pathway_file}")

            if create_maps:
                # Step 6: Create interactive map
                logger.info("\nStep 6: Creating interactive heat network tier map...")
                map_output_path = DATA_OUTPUTS_DIR / "maps" / "heat_network_tiers.html"
                image_output_path = map_output_path.with_suffix('.png')
                pdf_output_path = map_output_path.with_suffix('.pdf')

                self.create_heat_network_map(
                    properties_classified,
                    output_path=map_output_path,
                    image_output_path=image_output_path,
                    pdf_output_path=pdf_output_path,
                    heat_networks=heat_networks,
                    heat_zones=heat_zones
                )
                logger.info("✓ Interactive map created")

            logger.info("\n" + "=" * 80)
            logger.info("SPATIAL ANALYSIS COMPLETE!")
            logger.info("=" * 80)

            return properties_classified, pathway_summary

        except ImportError as e:
            logger.error("=" * 80)
            logger.error("SPATIAL ANALYSIS REQUIRES GDAL/GEOPANDAS")
            logger.error("=" * 80)
            logger.error(f"\nMissing dependency: {e}")
            logger.error("\nTo install spatial dependencies:")
            logger.error("  Option 1 (Windows - Recommended): conda install -c conda-forge geopandas")
            logger.error("  Option 2 (Linux/Mac): pip install -r requirements-spatial.txt")
            logger.error("\nOr skip spatial analysis - the rest of the analysis works without it!")
            logger.error("=" * 80)
            return None, None

        except Exception as e:
            logger.error(f"Error in spatial analysis: {e}")
            logger.exception("Full traceback:")
            return None, None


def main():
    """Main execution function for spatial analysis."""
    logger.info("Starting spatial analysis...")

    # Load validated data
    input_file = DATA_PROCESSED_DIR / "epc_london_validated.csv"

    if not input_file.exists():
        logger.error(f"Input file not found: {input_file}")
        return

    logger.info(f"Loading data from: {input_file}")
    df = pd.read_csv(input_file)

    # Initialize analyzer
    analyzer = HeatNetworkAnalyzer()

    # Geocode properties
    properties_gdf = analyzer.geocode_properties(df)

    if len(properties_gdf) > 0:
        # Load heat network data (if available)
        heat_networks_file = DATA_SUPPLEMENTARY_DIR / "london_heat_networks.geojson"
        heat_zones_file = DATA_SUPPLEMENTARY_DIR / "london_heat_zones.geojson"

        heat_networks, heat_zones = analyzer.load_london_heat_map_data(
            heat_networks_file,
            heat_zones_file
        )

        # Classify properties by tier
        properties_classified = analyzer.classify_heat_network_tiers(
            properties_gdf,
            heat_networks,
            heat_zones
        )

        # Analyze pathway suitability
        pathway_summary = analyzer.analyze_pathway_suitability(properties_classified)

        # Save results
        output_file = DATA_PROCESSED_DIR / "epc_london_with_tiers.geojson"
        properties_classified.to_file(output_file, driver='GeoJSON')
        logger.info(f"Classified properties saved to: {output_file}")

        # Save pathway summary
        pathway_file = DATA_OUTPUTS_DIR / "pathway_suitability_by_tier.csv"
        pathway_summary.to_csv(pathway_file, index=False)
        logger.info(f"Pathway summary saved to: {pathway_file}")

        # Create map
        map_output_path = DATA_OUTPUTS_DIR / "maps" / "heat_network_tiers.html"
        image_output_path = map_output_path.with_suffix('.png')
        pdf_output_path = map_output_path.with_suffix('.pdf')

        analyzer.create_heat_network_map(
            properties_classified,
            output_path=map_output_path,
            image_output_path=image_output_path,
            pdf_output_path=pdf_output_path,
            heat_networks=heat_networks,
            heat_zones=heat_zones
        )

        logger.info("Spatial analysis complete!")
    else:
        logger.warning("No geocoded properties available for spatial analysis")


if __name__ == "__main__":
    main()
