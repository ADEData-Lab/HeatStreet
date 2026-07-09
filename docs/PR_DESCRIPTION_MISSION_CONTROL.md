# HeatStreet Mission Control Terminal UX

## Summary
- Adds an optional Rich-based HeatStreet Mission Control dashboard for `run_analysis.py`.
- Adds CLI flags for TUI control, quiet/verbose output, sample windows, existing/fresh data selection, report mode, download scope, borough selection, and opening results.
- Instruments EPC full-load staging with structured progress callbacks without importing UI code into acquisition modules.
- Keeps `analysis_log.json` as the audit source and preserves analysis calculations, assumptions, schemas, and output locations.

## Notes
- The live dashboard is an operator view only; audit semantics remain in `AnalysisLogger`.
- CI, redirected output, `TERM=dumb`, `HEATSTREET_TUI=0`, `--no-tui`, and `--quiet` avoid live rendering.
- No scientific assumptions, filters, modelling formulas, or report schemas were intentionally changed.

## Tests Run
- `python -m py_compile run_analysis.py src\acquisition\epc_api_downloader.py src\ui\events.py src\ui\formatters.py src\ui\compat.py src\ui\live_dashboard.py` - passed
- `python -m pytest tests\test_ui_formatters.py tests\test_live_dashboard.py tests\test_run_analysis_args.py tests\test_epc_api_downloader.py::test_download_national_domestic_dataset_emits_progress_callback_events tests\test_epc_api_downloader.py::test_download_national_domestic_dataset_callback_reports_reusable_stage -q` - passed
- `python -m pytest tests\test_run_analysis_failures.py tests\test_startup_preflight.py tests\test_staged_processing.py tests\test_dashboard_packaging.py tests\test_one_stop_integration.py -q` - passed
- `python -m pytest -q` - collection failed on untracked scratch directory `temp_verify_dir/pytest-basetemp` with `PermissionError`
- `python -m pytest tests -q` - 121 passed, 4 failed in pre-existing areas outside this change:
  - `tests/test_data_validator.py::test_negative_energy_and_co2_rows_removed`
  - `tests/test_scaling.py::TestSpatialGridScaling::test_grid_classification_completes_quickly`
  - `tests/test_scaling.py::TestScenarioModelingScaling::test_chunked_processing_works`
  - `tests/test_spatial_grid_aggregation.py::test_circular_mask`
