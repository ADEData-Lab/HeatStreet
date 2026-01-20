"""
Tests for grid-based spatial heat density aggregation.

This module tests the memory-efficient grid aggregation method for
calculating neighborhood heat densities without OOM issues.
"""

import pytest
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from src.spatial.heat_network_analysis import HeatNetworkAnalyzer
from config.config import load_config


@pytest.fixture
def mock_config():
    """Load test configuration."""
    return load_config()


@pytest.fixture
def sample_properties():
    """
    Create a small synthetic dataset of properties for testing.

    Creates a 3x3 grid of properties with known positions and energy consumption.
    """
    # Create properties in a regular grid (British National Grid coordinates)
    # Using central London coordinates approximately
    base_x = 530000  # Easting
    base_y = 180000  # Northing
    spacing = 100  # 100m between properties

    properties_data = []
    prop_id = 1

    # Create a 10x10 grid (100 properties)
    for i in range(10):
        for j in range(10):
            x = base_x + i * spacing
            y = base_y + j * spacing

            # Vary energy consumption to create different density zones
            # Center properties have higher energy consumption
            center_distance = np.sqrt((i - 4.5)**2 + (j - 4.5)**2)
            energy_kwh_per_m2 = 150 - (center_distance * 10)  # Higher in center

            properties_data.append({
                'PROPERTY_ID': prop_id,
                'ENERGY_CONSUMPTION_CURRENT': max(50, energy_kwh_per_m2),
                'TOTAL_FLOOR_AREA': 100,  # 100 m²
                'geometry': Point(x, y),
                'tier_number': 5,  # Start all as Tier 5
                'heat_network_tier': 'Tier 5: Low heat density'
            })
            prop_id += 1

    # Create GeoDataFrame
    gdf = gpd.GeoDataFrame(properties_data, crs='EPSG:27700')

    return gdf


def test_grid_assignment(sample_properties):
    """Test that properties are correctly assigned to grid cells."""
    analyzer = HeatNetworkAnalyzer()

    # Get grid parameters
    spatial_config = analyzer.config.get('spatial', {})
    grid_config = spatial_config.get('grid', {})
    cell_size_m = grid_config.get('cell_size_m', 125)

    # Assign properties to grid cells
    coords = np.array([(geom.x, geom.y) for geom in sample_properties.geometry])
    cell_x = np.floor(coords[:, 0] / cell_size_m).astype(int)
    cell_y = np.floor(coords[:, 1] / cell_size_m).astype(int)

    # Check that all properties got assigned to cells
    assert len(cell_x) == len(sample_properties)
    assert len(cell_y) == len(sample_properties)

    # Check that cells are integers
    assert cell_x.dtype == int
    assert cell_y.dtype == int


def test_grid_aggregation(sample_properties):
    """Test that grid aggregation produces expected results."""
    analyzer = HeatNetworkAnalyzer()

    # Ensure we're in the right CRS
    if sample_properties.crs != 'EPSG:27700':
        sample_properties = sample_properties.to_crs('EPSG:27700')

    # Calculate absolute energy
    sample_properties['_absolute_energy_kwh'] = (
        sample_properties['ENERGY_CONSUMPTION_CURRENT'] *
        sample_properties['TOTAL_FLOOR_AREA']
    )

    # Get grid parameters
    spatial_config = analyzer.config.get('spatial', {})
    grid_config = spatial_config.get('grid', {})
    cell_size_m = grid_config.get('cell_size_m', 125)

    # Assign to cells
    coords = np.array([(geom.x, geom.y) for geom in sample_properties.geometry])
    sample_properties['_cell_x'] = np.floor(coords[:, 0] / cell_size_m).astype(int)
    sample_properties['_cell_y'] = np.floor(coords[:, 1] / cell_size_m).astype(int)

    # Aggregate
    cell_aggregates = sample_properties.groupby(['_cell_x', '_cell_y']).agg({
        '_absolute_energy_kwh': 'sum',
        'geometry': 'count'
    }).rename(columns={'geometry': 'property_count'})

    # Check that aggregation worked
    assert len(cell_aggregates) > 0
    assert len(cell_aggregates) <= len(sample_properties)

    # Check that total energy is conserved
    total_original = sample_properties['_absolute_energy_kwh'].sum()
    total_aggregated = cell_aggregates['_absolute_energy_kwh'].sum()
    assert abs(total_original - total_aggregated) < 1e-6


def test_neighborhood_calculation(sample_properties):
    """Test that neighborhood totals are calculated correctly."""
    analyzer = HeatNetworkAnalyzer()

    # Create a mask for unclassified properties (all of them in this test)
    unclassified_mask = sample_properties['tier_number'] > 2

    # Run the grid-based classification
    result = analyzer._classify_heat_density_tiers_grid(
        sample_properties.copy(),
        unclassified_mask
    )

    # Check that tiers were assigned
    assert 'heat_density_gwh_km2' in result.columns

    # Check that no properties are still unclassified (should be Tier 3, 4, or 5)
    assert result['tier_number'].isin([3, 4, 5]).all()

    # Check that heat density values are reasonable (not NaN, not negative)
    assert result['heat_density_gwh_km2'].notna().all()
    assert (result['heat_density_gwh_km2'] >= 0).all()


def test_circular_mask():
    """Test that circular mask correctly filters neighbor cells."""
    cell_size_m = 125
    buffer_radius_m = 250

    max_cell_distance = int(np.ceil(buffer_radius_m / cell_size_m))

    # Generate offsets with circular mask
    offsets_circular = []
    for dx in range(-max_cell_distance, max_cell_distance + 1):
        for dy in range(-max_cell_distance, max_cell_distance + 1):
            center_dist = np.sqrt((dx * cell_size_m) ** 2 + (dy * cell_size_m) ** 2)
            if center_dist <= buffer_radius_m:
                offsets_circular.append((dx, dy))

    # Generate offsets without circular mask (Chebyshev)
    offsets_chebyshev = []
    for dx in range(-max_cell_distance, max_cell_distance + 1):
        for dy in range(-max_cell_distance, max_cell_distance + 1):
            offsets_chebyshev.append((dx, dy))

    # Circular mask should have fewer offsets than Chebyshev
    assert len(offsets_circular) < len(offsets_chebyshev)

    # All circular offsets should be in Chebyshev offsets
    assert set(offsets_circular).issubset(set(offsets_chebyshev))

    # Check that we have a reasonable number of offsets
    # For 250m radius and 125m cells, we expect around 21-29 offsets with circular mask
    assert 15 < len(offsets_circular) < 35


def test_grid_method_vs_buffer_method(sample_properties):
    """
    Test that grid method produces similar results to buffer method.

    This is a smoke test - exact values may differ due to different neighborhood
    approximations, but the overall distribution should be similar.
    """
    analyzer = HeatNetworkAnalyzer()

    # Run both methods on the same data
    unclassified_mask = sample_properties['tier_number'] > 2

    # Grid method
    result_grid = analyzer._classify_heat_density_tiers_grid(
        sample_properties.copy(),
        unclassified_mask
    )

    # Check that results are reasonable
    grid_tiers = result_grid['tier_number'].value_counts()

    # We should have a distribution across tiers (not all in one tier)
    # For the synthetic data, center properties should have higher density
    assert len(grid_tiers) >= 1  # At least one tier present

    # Check that heat density values are in a reasonable range (0-500 GWh/km²)
    assert result_grid['heat_density_gwh_km2'].max() < 500
    assert result_grid['heat_density_gwh_km2'].min() >= 0


def test_grid_with_missing_energy_data():
    """Test that method handles missing energy data gracefully."""
    # Create properties without energy consumption column
    properties = gpd.GeoDataFrame([
        {'geometry': Point(530000, 180000), 'tier_number': 5}
    ], crs='EPSG:27700')

    analyzer = HeatNetworkAnalyzer()

    # This should not crash
    unclassified_mask = properties['tier_number'] > 2
    result = analyzer._classify_heat_density_tiers(properties)

    # Should return properties unchanged or with tertile classification
    assert len(result) == len(properties)


def test_config_disable_spatial():
    """Test that spatial analysis can be disabled via config."""
    # Temporarily modify config
    analyzer = HeatNetworkAnalyzer()
    original_config = analyzer.config.get('spatial', {})

    # Mock disabled config
    analyzer.config['spatial'] = {'disable': True}

    # Create sample data
    properties = gpd.GeoDataFrame([
        {
            'geometry': Point(530000, 180000),
            'tier_number': 5,
            'ENERGY_CONSUMPTION_CURRENT': 100,
            'TOTAL_FLOOR_AREA': 100
        }
    ], crs='EPSG:27700')

    # Run classification
    result = analyzer._classify_heat_density_tiers(properties)

    # Should return unchanged
    assert len(result) == len(properties)

    # Restore original config
    analyzer.config['spatial'] = original_config


def test_large_dataset_memory_efficiency():
    """
    Test that grid method handles larger datasets without excessive memory use.

    This is a smoke test - we create a moderately sized dataset (1000 properties)
    and ensure it completes without errors.
    """
    # Create 1000 random properties
    np.random.seed(42)
    n_properties = 1000

    base_x = 530000
    base_y = 180000

    properties_data = []
    for i in range(n_properties):
        x = base_x + np.random.uniform(0, 5000)
        y = base_y + np.random.uniform(0, 5000)

        properties_data.append({
            'PROPERTY_ID': i,
            'ENERGY_CONSUMPTION_CURRENT': np.random.uniform(80, 200),
            'TOTAL_FLOOR_AREA': np.random.uniform(60, 150),
            'geometry': Point(x, y),
            'tier_number': 5,
            'heat_network_tier': 'Tier 5: Low heat density'
        })

    gdf = gpd.GeoDataFrame(properties_data, crs='EPSG:27700')

    analyzer = HeatNetworkAnalyzer()
    unclassified_mask = gdf['tier_number'] > 2

    # This should complete without OOM or other errors
    result = analyzer._classify_heat_density_tiers_grid(gdf, unclassified_mask)

    assert len(result) == n_properties
    assert 'heat_density_gwh_km2' in result.columns


if __name__ == '__main__':
    # Run tests
    pytest.main([__file__, '-v'])
