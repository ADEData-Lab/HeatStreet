"""One-stop report with mandatory Route A implementation pathways."""

from __future__ import annotations

from src.integration.route_a_pipeline import RouteAOneStopMixin
from src.reporting.one_stop_report_core import *  # noqa: F401,F403
from src.reporting.one_stop_report_core import (
    AnnotatedDatapoint,
    OneStopReportGenerator as _CoreOneStopReportGenerator,
)


class OneStopReportGenerator(RouteAOneStopMixin, _CoreOneStopReportGenerator):
    """Generate the one-stop report with Route A as the headline pathway contract."""

    _annotated_datapoint_class = AnnotatedDatapoint
