# Scaling Guide for HeatStreet Pipeline

This document provides guidance for running the HeatStreet pipeline on large datasets (100k+ properties) with limited memory.

## Quick Start

For a typical 16GB laptop processing ~700k properties:

```bash
export HEATSTREET_WORKERS=2
export HEATSTREET_CHUNK_SIZE=50000
export HEATSTREET_PROFILE=1  # Optional: enable timing/memory logs

python run_analysis.py
```

## Environment Variables

### `HEATSTREET_WORKERS`

Controls the number of parallel worker processes for scenario modeling.

| Setting | RAM Required | Use Case |
|---------|-------------|----------|
| `1` | ~8GB | Memory-constrained systems |
| `2` (default) | ~12GB | Laptops with 16GB RAM |
| `4` | ~20GB | Workstations with 32GB+ RAM |
| `8+` | ~40GB+ | Servers with 64GB+ RAM |

**Default:** 2 workers

### `HEATSTREET_CHUNK_SIZE`

Controls how many properties are processed per batch in scenario modeling.

| Setting | Memory Impact | Speed |
|---------|--------------|-------|
| `25000` | Lower memory | Slower (more GC overhead) |
| `50000` (default) | Balanced | Good |
| `100000` | Higher memory | Faster |

**Default:** 50,000 rows per chunk

### `HEATSTREET_PROFILE`

Enables detailed profiling logs including:
- Memory usage (RSS) at key checkpoints
- Timing for each processing step
- DataFrame sizes and dtypes

```bash
export HEATSTREET_PROFILE=1  # Enable
export HEATSTREET_PROFILE=0  # Disable (default)
```

## Expected Runtime

On a modern laptop (8-core CPU, 16GB RAM, SSD) processing ~700k properties:

| Stage | Expected Time | Notes |
|-------|--------------|-------|
| Data loading | 30-60s | Depends on disk speed |
| Archetype analysis | 1-2 min | Single-threaded |
| Spatial analysis (grid) | 30-60s | Vectorized, memory-efficient |
| Scenario modeling (per scenario) | 10-20 min | Parallel, chunked |
| Report generation | 1-2 min | Single-threaded |

**Total for full pipeline:** 30-60 minutes (depending on number of scenarios)

## Memory Usage Patterns

### Spatial Analysis (Grid Method)

The grid-based spatial analysis is memory-efficient:

- **Step 1-3:** O(n) memory for property DataFrame
- **Step 4:** O(cells) memory for neighborhood computation (~50k cells for 700k properties)
- **Step 5:** O(n) memory for join operation
- **Peak:** ~7-8GB RSS for 700k properties

### Scenario Modeling

With chunked processing and limited workers:

- **Per chunk:** ~200-400MB per worker
- **Peak:** workers × chunk_memory + base DataFrame
- **With 2 workers, 50k chunks:** ~10-12GB peak RSS

## Troubleshooting

### OOM during scenario modeling

Symptoms: Process killed without error message, or "Killed" in terminal.

Solutions:
1. Reduce workers: `export HEATSTREET_WORKERS=1`
2. Reduce chunk size: `export HEATSTREET_CHUNK_SIZE=25000`
3. Close other applications to free RAM
4. Enable profiling to identify memory spikes: `export HEATSTREET_PROFILE=1`

### Spatial analysis running slowly

Symptoms: Step 4/5 taking more than 5 minutes.

Solutions:
1. Verify grid method is being used (check for "grid-based" in logs)
2. Check that vectorized code is running (no "apply" warnings in logs)
3. Enable profiling to see timing breakdown

### High CPU but slow progress

Symptoms: 100% CPU usage but progress is slow.

This usually indicates Python-level loops instead of vectorized operations. Check:
1. Logs for any warnings about fallback methods
2. That the latest code version is being used

## Advanced Configuration

### Grid Parameters (config.yaml)

```yaml
spatial:
  method: "grid"  # Use grid for large datasets
  grid:
    cell_size_m: 125      # Grid cell size in meters
    buffer_radius_m: 250  # Neighborhood radius
    use_circular_mask: true  # More accurate but slightly slower
```

### Disabling Spatial Analysis

If you don't need heat network tier classification:

```yaml
spatial:
  disable: true
```

This skips the spatial analysis entirely and assigns all properties to Tier 5.

## Profiling Output Example

With `HEATSTREET_PROFILE=1`, you'll see logs like:

```
[MEMORY] Grid classification START: 4523.2 MB RSS
[PROFILE] Input properties: 707,783 rows, 45 cols, ~2.1 GB
[PROFILE] properties._cell_id dtype: int64
[PROFILE] neighborhood_df.index dtype: int64
[MEMORY] Before join: 7234.1 MB RSS
[MEMORY] Grid classification END: 7456.8 MB RSS
```

This helps identify:
- Memory growth patterns
- Dtype mismatches that could cause slow joins
- Steps that consume the most memory
