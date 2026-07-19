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

    def generate(self) -> Path:
        """Ensure Route A outputs exist, then generate the integrated report."""
        summary_path = self.output_dir / "implementation_results_summary.csv"
        qa_path = self.output_dir / "implementation_qa.json"
        properties_path = self.output_dir / "implementation_results_by_property.parquet"

        if not (summary_path.is_file() and qa_path.is_file() and properties_path.is_file()):
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
