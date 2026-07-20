"""One-stop report with mandatory Route A implementation pathways."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.integration.route_a_pipeline import RouteAOneStopMixin
from src.reporting.one_stop_report_core import *  # noqa: F401,F403
from src.reporting.one_stop_report_core import (
    AnnotatedDatapoint,
    OneStopReportGenerator as _CoreOneStopReportGenerator,
)
from src.utils.implementation_phase import run_implementation_phase


class OneStopReportGenerator(RouteAOneStopMixin, _CoreOneStopReportGenerator):
    """Generate the one-stop report with Route A as the headline pathway contract."""

    _annotated_datapoint_class = AnnotatedDatapoint

    def _route_a_paths(self) -> tuple[Path, Path, Path]:
        return (
            self.output_dir / "implementation_results_summary.csv",
            self.output_dir / "implementation_qa.json",
            self.output_dir / "implementation_results_by_property.parquet",
        )

    def _route_a_required_for_run(self) -> bool:
        """Return True only for a real run-scoped pipeline invocation.

        Direct generator use in unit tests and compatibility tooling may provide
        existing integrated report artifacts without a run root. Those callers
        should exercise the core one-stop generator rather than trying to rerun
        Route A from a dataset they deliberately did not create.
        """
        return bool(self.run_context is not None and self.run_context.run_root is not None)

    def generate(self) -> Path:
        """Run Route A for real run-scoped reports, otherwise preserve compatibility."""
        summary_path, qa_path, properties_path = self._route_a_paths()
        route_a_paths = (summary_path, qa_path, properties_path)
        route_a_complete = all(path.is_file() for path in route_a_paths)
        route_a_partial = any(path.is_file() for path in route_a_paths)

        if route_a_partial and not route_a_complete:
            missing = [str(path) for path in route_a_paths if not path.is_file()]
            raise RuntimeError(
                "Route A outputs are incomplete before one-stop report generation: "
                + ", ".join(missing)
            )

        if route_a_complete:
            return super().generate()

        if not self._route_a_required_for_run():
            return _CoreOneStopReportGenerator.generate(self)

        spatial_path = self.processed_dir / "epc_london_adjusted_spatial.parquet"
        if not spatial_path.is_file():
            raise RuntimeError(
                "Route A requires the authoritative spatially enriched dataset before "
                "one-stop report generation"
            )

        frame = pd.read_parquet(spatial_path)
        run_implementation_phase(
            frame,
            context=self.run_context,
            outputs_dir=self.output_dir,
            config=self.config,
        )
        return super().generate()
