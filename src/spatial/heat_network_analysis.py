"""
Spatial Analysis Module for Heat Network Overlay

Analyzes property locations relative to existing/planned heat networks.
Implements Section 3.3 and 4.1 of the project specification.
"""

import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from loguru import logger
import numpy as np

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import (
    load_config,
    DATA_PROCESSED_DIR,
    DATA_SUPPLEMENTARY_DIR,
    DATA_OUTPUTS_DIR
)
from src.acquisition.london_gis_downloader import LondonGISDownloader


class HeatNetworkAnalyzer:
    """
    Analyzes properties relative to heat network infrastructure and zones.
    """

    def __init__(self):
        """Initialize the heat network analyzer."""
        self.config = load_config()
        self.heat_network_tiers = self.config['analysis']['heat_network_tiers']
        self.gis_downloader = LondonGISDownloader()

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

    def geocode_properties(self, df: pd.DataFrame) -> gpd.GeoDataFrame:
        """
        Convert property addresses to geographic coordinates.

        Args:
            df: Property DataFrame with postcodes

        Returns:
            GeoDataFrame with property locations
        """
        logger.info("Geocoding properties...")

        # Check if coordinates already exist in dataset
        if 'LATITUDE' in df.columns and 'LONGITUDE' in df.columns:
            logger.info("Using existing coordinates from EPC data")

            # Create geometry from lat/lon
            geometry = [
                Point(lon, lat) if pd.notna(lon) and pd.notna(lat) else None
                for lon, lat in zip(df['LONGITUDE'], df['LATITUDE'])
            ]

            gdf = gpd.GeoDataFrame(df, geometry=geometry, crs='EPSG:4326')

            # Remove properties without coordinates
            initial_count = len(gdf)
            gdf = gdf[gdf.geometry.notna()].copy()
            logger.info(f"Geocoded {len(gdf):,} of {initial_count:,} properties ({len(gdf)/initial_count*100:.1f}%)")

            return gdf

        else:
            logger.warning("No coordinate columns found in EPC data")
            logger.info("Would need to geocode from postcodes - requires external geocoding service")

            # Placeholder for geocoding logic
            # In practice, would use:
            # - UK postcode centroid database
            # - Geocoding API (Google, Nominatim, etc.)
            # - OS AddressBase data

            return gpd.GeoDataFrame(df, geometry=[], crs='EPSG:4326')

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

        # Initialize tier column
        properties['heat_network_tier'] = 'Tier 5: Low heat density'
        properties['tier_number'] = 5

        # Ensure CRS match (use British National Grid for distance calculations)
        if properties.crs != 'EPSG:27700':
            properties = properties.to_crs('EPSG:27700')

        # Tier 1: Adjacent to existing network (within 250m)
        if heat_networks is not None:
            logger.info("Identifying Tier 1: Adjacent to existing network...")

            if heat_networks.crs != 'EPSG:27700':
                heat_networks = heat_networks.to_crs('EPSG:27700')

            # Buffer heat networks by 250m
            buffer_distance = self.heat_network_tiers['tier_1']['distance_meters']
            heat_network_buffer = heat_networks.buffer(buffer_distance).unary_union

            # Check which properties are within buffer
            tier_1_mask = properties.geometry.within(heat_network_buffer)
            tier_1_count = tier_1_mask.sum()

            properties.loc[tier_1_mask, 'heat_network_tier'] = 'Tier 1: Adjacent to existing network'
            properties.loc[tier_1_mask, 'tier_number'] = 1

            logger.info(f"  Tier 1: {tier_1_count:,} properties ({tier_1_count/len(properties)*100:.1f}%)")

        # Tier 2: Within planned Heat Network Zone
        if heat_zones is not None:
            logger.info("Identifying Tier 2: Within planned HNZ...")

            if heat_zones.crs != 'EPSG:27700':
                heat_zones = heat_zones.to_crs('EPSG:27700')

            # Union all heat zones
            heat_zones_union = heat_zones.unary_union

            # Check which properties are within zones (and not already Tier 1)
            tier_2_mask = (
                properties.geometry.within(heat_zones_union) &
                (properties['tier_number'] > 2)
            )
            tier_2_count = tier_2_mask.sum()

            properties.loc[tier_2_mask, 'heat_network_tier'] = 'Tier 2: Within planned HNZ'
            properties.loc[tier_2_mask, 'tier_number'] = 2

            logger.info(f"  Tier 2: {tier_2_count:,} properties ({tier_2_count/len(properties)*100:.1f}%)")

        # Tiers 3-5: Based on heat density (would require heat demand data)
        # This is a simplified placeholder - actual implementation would calculate
        # linear heat density from property characteristics and street layout

        properties = self._classify_heat_density_tiers(properties)

        # Summary
        tier_summary = properties['heat_network_tier'].value_counts().sort_index()
        logger.info("\nHeat Network Tier Summary:")
        for tier, count in tier_summary.items():
            logger.info(f"  {tier}: {count:,} ({count/len(properties)*100:.1f}%)")

        return properties

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

        # For properties not already classified as Tier 1 or 2
        unclassified_mask = properties['tier_number'] > 2

        if 'ENERGY_CONSUMPTION_CURRENT' not in properties.columns:
            logger.warning("No energy consumption data - using simplified tertile method")
            return self._classify_by_tertiles(properties, unclassified_mask)

        try:
            # Method 1: Grid-based heat density (proper implementation)
            logger.info("Using grid-based heat density calculation...")

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

            logger.info(f"Creating {len(x_coords) * len(y_coords)} grid cells...")

            # For each unclassified property, calculate heat density in its vicinity
            for idx, prop in properties_27700[unclassified_mask].iterrows():
                # Create 500m buffer around property
                buffer = prop.geometry.buffer(250)  # 250m radius = 500m diameter
                buffer_area_km2 = buffer.area / 1_000_000  # Convert m² to km²

                # Find all properties within this buffer
                nearby_mask = properties_27700.geometry.within(buffer)
                nearby_props = properties_27700[nearby_mask]

                if len(nearby_props) > 0:
                    # Sum energy consumption (kWh/year)
                    total_energy_kwh = nearby_props['ENERGY_CONSUMPTION_CURRENT'].sum()

                    # Convert to GWh/km²
                    heat_density_gwh_km2 = (total_energy_kwh / 1_000_000) / buffer_area_km2

                    # Classify by heat density thresholds
                    if heat_density_gwh_km2 >= self.heat_network_tiers['tier_3']['min_heat_density_gwh_km2']:
                        properties.loc[idx, 'heat_network_tier'] = 'Tier 3: High heat density'
                        properties.loc[idx, 'tier_number'] = 3
                        properties.loc[idx, 'heat_density_gwh_km2'] = heat_density_gwh_km2
                    elif heat_density_gwh_km2 >= self.heat_network_tiers['tier_4']['min_heat_density_gwh_km2']:
                        properties.loc[idx, 'heat_network_tier'] = 'Tier 4: Medium heat density'
                        properties.loc[idx, 'tier_number'] = 4
                        properties.loc[idx, 'heat_density_gwh_km2'] = heat_density_gwh_km2
                    else:
                        # Tier 5 (already default)
                        properties.loc[idx, 'heat_density_gwh_km2'] = heat_density_gwh_km2

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

        Args:
            properties: GeoDataFrame with tier classifications

        Returns:
            DataFrame summarizing pathway suitability by tier
        """
        logger.info("Analyzing decarbonization pathway suitability by tier...")

        pathway_suitability = {
            'Tier 1': 'District Heating (existing network connection)',
            'Tier 2': 'District Heating (planned network)',
            'Tier 3': 'District Heating (high density justifies extension)',
            'Tier 4': 'Heat Pump (moderate density, network extension marginal)',
            'Tier 5': 'Heat Pump (low density, network not viable)'
        }

        # Count properties by tier
        tier_counts = properties['heat_network_tier'].value_counts()

        # Create summary DataFrame
        summary = pd.DataFrame({
            'Tier': tier_counts.index,
            'Property Count': tier_counts.values,
            'Percentage': (tier_counts.values / len(properties) * 100).round(1),
            'Recommended Pathway': [pathway_suitability.get(tier.split(':')[0], 'Unknown') for tier in tier_counts.index]
        })

        summary = summary.sort_values('Tier')

        logger.info("\nPathway Suitability Summary:")
        for _, row in summary.iterrows():
            logger.info(f"  {row['Tier']}: {row['Property Count']:,} properties → {row['Recommended Pathway']}")

        return summary

    def create_heat_network_map(
        self,
        properties: gpd.GeoDataFrame,
        output_path: Optional[Path] = None
    ):
        """
        Create an interactive map showing heat network tiers.

        Args:
            properties: GeoDataFrame with tier classifications
            output_path: Path to save map HTML
        """
        try:
            import folium
            from folium import plugins

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
                tiles='OpenStreetMap'
            )

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

        except ImportError:
            logger.warning("folium not available, skipping map creation")
        except Exception as e:
            logger.error(f"Error creating map: {e}")

    def run_complete_analysis(
        self,
        df: pd.DataFrame,
        auto_download_gis: bool = True
    ) -> Tuple[Optional[gpd.GeoDataFrame], Optional[pd.DataFrame]]:
        """
        Run complete spatial analysis workflow.

        Args:
            df: Validated EPC DataFrame
            auto_download_gis: Automatically download GIS data if not available

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

            if len(properties_gdf) == 0:
                logger.warning("No properties could be geocoded. Spatial analysis cannot proceed.")
                return None, None

            logger.info(f"✓ Successfully geocoded {len(properties_gdf):,} properties")

            # Step 2: Load GIS data
            logger.info("\nStep 2: Loading London heat network GIS data...")
            heat_networks, heat_zones = self.load_london_heat_map_data(
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

            # Step 6: Create interactive map
            logger.info("\nStep 6: Creating interactive heat network tier map...")
            self.create_heat_network_map(properties_classified)
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
    df = pd.read_csv(input_file, low_memory=False)

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
        analyzer.create_heat_network_map(properties_classified)

        logger.info("Spatial analysis complete!")
    else:
        logger.warning("No geocoded properties available for spatial analysis")


if __name__ == "__main__":
    main()
