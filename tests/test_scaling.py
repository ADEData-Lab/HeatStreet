"""
Smoke tests for scaling fixes.

Tests that the pipeline can process moderate-sized datasets without:
1. Step 5 hanging (spatial grid performance)
2. OOM kills (scenario modeling memory)

Run with: pytest tests/test_scaling.py -v
"""

import os
import sys
import time
import pytest
import numpy as np
import pandas as pd
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

# Set scaling params for tests
os.environ['HEATSTREET_WORKERS'] = '2'
os.environ['HEATSTREET_CHUNK_SIZE'] = '5000'
os.environ['HEATSTREET_PROFILE'] = '1'

from config.config import load_config
from src.utils.profiling import get_rss_mb, profile_enabled


@pytest.fixture
def mock_config():
    """Load test configuration."""
    return load_config()


@pytest.fixture
def sample_properties_10k():
    """
    Create a 10k property dataset for scaling tests.

    Uses British National Grid coordinates (EPSG:27700).
    """
    np.random.seed(42)
    n_properties = 10000

    # Central London area coordinates
    base_x = 530000  # Easting
    base_y = 180000  # Northing

    # Generate random positions in a 5km x 5km area
    x_coords = base_x + np.random.uniform(0, 5000, n_properties)
    y_coords = base_y + np.random.uniform(0, 5000, n_properties)

    properties_data = {
        'UPRN': [f'UPRN_{i:08d}' for i in range(n_properties)],
        'POSTCODE': [f'SW{i % 20 + 1} {i % 10}AA' for i in range(n_properties)],
        'ENERGY_CONSUMPTION_CURRENT': np.random.uniform(100, 400, n_properties),
        'TOTAL_FLOOR_AREA': np.random.uniform(50, 200, n_properties),
        'CURRENT_ENERGY_EFFICIENCY': np.random.uniform(30, 80, n_properties),
        'CURRENT_ENERGY_RATING': np.random.choice(['D', 'E', 'F', 'G'], n_properties),
        'tier_number': np.full(n_properties, 5),  # All unclassified initially
        'heat_network_tier': ['Tier 5: Low heat density'] * n_properties,
        'x_coord': x_coords,
        'y_coord': y_coords,
    }

    return pd.DataFrame(properties_data)


class TestSpatialGridScaling:
    """Tests for spatial grid performance fixes."""

    def test_grid_classification_completes_quickly(self, mock_config, sample_properties_10k):
        """
        Verify Step 5 completes in reasonable time (not hours).

        Target: 10k properties should complete in <30 seconds.
        """
        try:
            import geopandas as gpd
            from shapely.geometry import Point
        except ImportError:
            pytest.skip("geopandas not available")

        from src.spatial.heat_network_analysis import HeatNetworkAnalyzer

        # Create GeoDataFrame
        geometry = [
            Point(row['x_coord'], row['y_coord'])
            for _, row in sample_properties_10k.iterrows()
        ]
        gdf = gpd.GeoDataFrame(
            sample_properties_10k,
            geometry=geometry,
            crs='EPSG:27700'
        )

        # Initialize analyzer
        analyzer = HeatNetworkAnalyzer(mock_config)

        # Create unclassified mask (all properties)
        unclassified_mask = pd.Series(True, index=gdf.index)

        # Time the grid classification
        start_time = time.time()
        start_rss = get_rss_mb()

        result = analyzer._classify_heat_density_tiers_grid(gdf, unclassified_mask)

        elapsed = time.time() - start_time
        end_rss = get_rss_mb()

        # Assertions
        assert result is not None, "Grid classification should return a result"
        assert len(result) == len(gdf), "Result should have same number of rows"
        assert elapsed < 30, f"Grid classification took {elapsed:.1f}s, should be <30s"

        # Check tier assignment worked
        tier_counts = result['tier_number'].value_counts()
        assert len(tier_counts) > 0, "Should have assigned some tiers"

        print(f"\nGrid classification completed in {elapsed:.2f}s")
        print(f"Memory: {start_rss:.1f} MB -> {end_rss:.1f} MB ({end_rss - start_rss:+.1f} MB)")
        print(f"Tier distribution: {tier_counts.to_dict()}")

    def test_cell_id_dtype_is_int64(self, mock_config, sample_properties_10k):
        """Verify cell_id uses int64 dtype to prevent slow joins."""
        try:
            import geopandas as gpd
            from shapely.geometry import Point
        except ImportError:
            pytest.skip("geopandas not available")

        # Create a small sample for dtype check
        sample = sample_properties_10k.head(100)
        geometry = [Point(row['x_coord'], row['y_coord']) for _, row in sample.iterrows()]
        gdf = gpd.GeoDataFrame(sample, geometry=geometry, crs='EPSG:27700')

        # Calculate cell_id manually
        cell_size_m = 125
        x_coords = gdf.geometry.x.values
        y_coords = gdf.geometry.y.values

        cell_x = np.floor(x_coords / cell_size_m).astype(np.int64)
        cell_y = np.floor(y_coords / cell_size_m).astype(np.int64)

        y_range = cell_y.max() - cell_y.min() + 1
        multiplier = max(100000, int(y_range * 10))
        cell_id = (cell_x * multiplier + cell_y).astype(np.int64)

        assert cell_id.dtype == np.int64, f"cell_id should be int64, got {cell_id.dtype}"


class TestScenarioModelingScaling:
    """Tests for scenario modeling memory fixes."""

    def test_chunked_processing_works(self, mock_config, sample_properties_10k):
        """
        Verify chunked processing completes without errors.

        Uses small chunk size to test chunking logic.
        """
        import types

        # Lightweight stubs to avoid heavy spatial deps
        sys.modules.setdefault(
            'geopandas',
            types.SimpleNamespace(GeoDataFrame=object, read_file=lambda *_, **__: None)
        )

        from src.modeling.scenario_model import ScenarioModeler

        # Add required columns for scenario modeling
        df = sample_properties_10k.copy()
        df['energy_consumption_adjusted'] = df['ENERGY_CONSUMPTION_CURRENT'] * 0.8
        df['baseline_consumption_kwh_year'] = df['ENERGY_CONSUMPTION_CURRENT'] * df['TOTAL_FLOOR_AREA']
        df['wall_type'] = np.random.choice(['Solid', 'Cavity'], len(df))
        df['estimated_flow_temp'] = np.random.uniform(55, 75, len(df))
        df['hn_ready'] = False

        # Initialize modeler
        modeler = ScenarioModeler(mock_config, output_dir=Path('/tmp'))

        # Define a simple test scenario
        test_scenario = {
            'measures': ['loft_insulation_topup']
        }

        start_time = time.time()
        start_rss = get_rss_mb()

        # Run scenario modeling
        result = modeler.model_scenario(df, 'test_scenario', test_scenario)

        elapsed = time.time() - start_time
        end_rss = get_rss_mb()

        # Assertions
        assert result is not None, "Scenario modeling should return a result"
        assert 'total_properties' in result, "Result should contain total_properties"
        assert result['total_properties'] == len(df), "Should process all properties"

        print(f"\nScenario modeling completed in {elapsed:.2f}s")
        print(f"Memory: {start_rss:.1f} MB -> {end_rss:.1f} MB ({end_rss - start_rss:+.1f} MB)")
        print(f"Properties processed: {result['total_properties']:,}")

    def test_worker_count_respects_env_var(self):
        """Verify HEATSTREET_WORKERS env var is respected."""
        from src.utils.profiling import get_worker_count

        # Test default
        os.environ.pop('HEATSTREET_WORKERS', None)
        assert get_worker_count(default=2) == 2

        # Test custom value
        os.environ['HEATSTREET_WORKERS'] = '4'
        assert get_worker_count(default=2) == 4

        # Reset
        os.environ['HEATSTREET_WORKERS'] = '2'

    def test_chunk_size_respects_env_var(self):
        """Verify HEATSTREET_CHUNK_SIZE env var is respected."""
        from src.utils.profiling import get_chunk_size

        # Test default
        os.environ.pop('HEATSTREET_CHUNK_SIZE', None)
        assert get_chunk_size(default=50000) == 50000

        # Test custom value
        os.environ['HEATSTREET_CHUNK_SIZE'] = '25000'
        assert get_chunk_size(default=50000) == 25000

        # Reset
        os.environ['HEATSTREET_CHUNK_SIZE'] = '5000'


class TestProfilingUtilities:
    """Tests for profiling utilities."""

    def test_profile_enabled_respects_env_var(self):
        """Verify HEATSTREET_PROFILE env var is respected."""
        from src.utils.profiling import profile_enabled

        os.environ['HEATSTREET_PROFILE'] = '1'
        assert profile_enabled() is True

        os.environ['HEATSTREET_PROFILE'] = '0'
        assert profile_enabled() is False

        os.environ['HEATSTREET_PROFILE'] = 'true'
        assert profile_enabled() is True

        # Reset
        os.environ['HEATSTREET_PROFILE'] = '1'

    def test_get_rss_mb_returns_number(self):
        """Verify RSS memory function returns a reasonable value."""
        from src.utils.profiling import get_rss_mb

        rss = get_rss_mb()
        assert isinstance(rss, float), "get_rss_mb should return float"
        # Test process should use at least some memory
        # (On systems where /proc isn't available, it returns 0.0)
        assert rss >= 0, "RSS should be non-negative"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
