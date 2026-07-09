# Codex prompt — fix mutually-exclusive glazing measures in the fabric tipping point sequence

Copy everything below the line into Codex.

---

There is a bug in the fabric investment tipping point analysis: `double_glazing_upgrade` and `triple_glazing_upgrade` are mutually exclusive window treatments (you fit one or the other, not both), but the sequencing algorithm treats them as independent, stackable fabric measures. This produces an inconsistent and physically nonsensical curve.

## Where the bug is

In `src/analysis/retrofit_packages.py`, the measure catalogue defines eligibility that already signals these are alternatives, not additions:
- `double_glazing_upgrade` — `requires_check=True`, eligible only when `'single' in glazing_type` (line ~519-521)
- `triple_glazing_upgrade` — `requires_check=True`, eligible when `glazing_type in ['single', 'double', 'mixed']` (line ~523-525)

Both can replace single glazing. Installing double glazing and then triple glazing on the same windows in the same sequence double-counts the same physical intervention.

In `src/analysis/fabric_tipping_point.py`, `generate_fabric_measure_sequence()` (line ~117) greedily ranks catalogue measures purely by kWh-saved-per-£ on the remaining demand fraction, with no concept of mutual exclusivity. It happily inserts both `triple_glazing_upgrade` and `double_glazing_upgrade` as separate steps in the same cumulative curve. `calculate_tipping_point_curve()` (line ~170) then applies both measures' savings cumulatively and cumulative capex includes both £9,000 (triple) and £6,000 (double) — £15,000 spent on window replacement in one sequence.

This is why the report's own narrative and the pipeline output can contradict each other. The "Window Upgrade Economics" section (computed separately) explicitly frames triple glazing as an incremental £3,000 step *from* double glazing, and concludes triple offers poor marginal value and should not be prioritised. But because the greedy sequence in `fabric_tipping_point.py` evaluates both measures independently against the same single-glazing baseline, it can rank triple glazing's raw £/kWh as better than double's at the point it's evaluated (in the current run: triple scores 75.2 kWh/£1k vs double's 63.9 kWh/£1k), inserting triple into the cumulative curve first, then adding double glazing again on top. The ordering also isn't stable run-to-run because it depends on where in the greedy sequence the comparison happens to fall.

## Required fix

1. In `src/analysis/retrofit_packages.py`, add an explicit mutual-exclusivity grouping for measures that treat the same building element (start with glazing). A simple approach: add a `mutually_exclusive_group: Optional[str]` field to `Measure` (e.g. `mutually_exclusive_group='glazing'` on both `double_glazing_upgrade` and `triple_glazing_upgrade`), analogous to how `scenario_model.py` already resolves ASHP vs heat network exclusivity for scenario measures.

2. In `fabric_tipping_point.py`, update `generate_fabric_measure_sequence()` so that when a measure with a `mutually_exclusive_group` is selected, every other measure sharing that group is removed from `remaining_measures` (not just the one selected) — mirroring the pattern already used elsewhere in the codebase for ASHP/HN exclusivity. Only one glazing measure should ever appear in the sequence and cumulative curve.

3. Selection rule between double and triple: since triple glazing's cost/benefit should be evaluated relative to a double-glazed baseline (as the narrative describes: triple over double costs a marginal £3,000 for a marginal 750 kWh/year), consider whether the catalogue should also expose a `triple_glazing_upgrade_from_double` variant for cases where a property already has double glazing, rather than only a from-single variant. At minimum, make the greedy selection pick whichever of the two (compared on equal footing, both computed from the same baseline) delivers the better £/kWh, and drop the other entirely from the sequence and from `fabric_tipping_point_curve.csv`.

4. Update `build_cost_performance_table()` similarly — it should not list both glazing measures as independent, stackable entries if one is presented as the tipping-point sequence choice; keep both visible for the standalone "Window Upgrade Economics" comparison table (that's a legitimate side-by-side comparison, not a cumulative sequence), but exclude the non-selected one from the cumulative tipping-point curve and its downstream chart (`src/reporting/visualizations.py::plot_fabric_tipping_point_analysis`, which reads directly from `fabric_tipping_point_curve.csv` and will pick up the fix automatically once the CSV only contains one glazing row).

5. Re-run the pipeline and confirm:
   - `fabric_tipping_point_curve.csv` contains exactly one glazing measure row (not both `double_glazing_upgrade` and `triple_glazing_upgrade`).
   - Cumulative capex at the final step no longer includes both £6,000 and £9,000 for glazing.
   - The regenerated `tipping_point.png`/`.svg` chart's glazing bar matches whichever measure is actually in the sequence.
   - Table 7 in the report (currently sourced from this CSV) and the "Window Upgrade Economics" narrative are consistent with each other about which glazing option is being recommended.

6. Add a unit test asserting that any two measures sharing a `mutually_exclusive_group` never both appear in `generate_fabric_measure_sequence()`'s output, and that `calculate_tipping_point_curve()`'s final cumulative capex equals the sum of `measure_capex` for the returned sequence only (no hidden double-counting).

## Constraints

- Don't change the standalone glazing cost/saving assumptions in `config/config.yaml` (double £6,000/1,500 kWh, triple £9,000/2,250 kWh) — only the sequencing/selection logic.
- Keep the "Window Upgrade Economics" comparison table as-is (it correctly compares both options side by side); the fix is scoped to the cumulative tipping-point sequence and its chart.
- Report back which glazing measure the corrected greedy sequence selects and its new position/step number, so the report text can be checked against it.
