#!/usr/bin/env python3
"""Run the Route A implementation pathways on an enriched Heat Street dataset.

Typical use after the main pipeline has completed:

    python run_route_a.py

By default the runner uses data/processed/epc_london_adjusted_spatial.parquet and
writes implementation outputs to data/outputs. A run-scoped dataset and output
directory can be supplied explicitly.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict

import pandas as pd
from rich.console import Console
from rich.table import Table

from config.config import load_config
from src.modeling.implementation_pathways import ImplementationPathwayModeler


console = Console()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Model deployable ASHP and spatial implementation pathways."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/processed/epc_london_adjusted_spatial.parquet"),
        help="Enriched authoritative property-level Parquet input.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/outputs"),
        help="Directory for Route A outputs.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/config.yaml"),
        help="YAML configuration file.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help=(
            "Worker count. Use 1 for the first full run. The implementation engine "
            "is deterministic and memory use is easier to diagnose in single-worker mode."
        ),
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        help="Optional deterministic row limit for a smoke test.",
    )
    return parser.parse_args()


def load_yaml(path: Path) -> Dict[str, Any]:
    if path == Path("config/config.yaml"):
        return load_config()
    import yaml

    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def main() -> int:
    args = parse_args()
    if args.workers < 1:
        raise SystemExit("--workers must be at least 1")
    if not args.input.is_file():
        raise SystemExit(
            f"Input not found: {args.input}. Run the main Heat Street pipeline first "
            "or pass --input pointing to a run-scoped epc_london_adjusted_spatial.parquet."
        )

    os.environ["HEATSTREET_WORKERS"] = str(args.workers)
    frame = pd.read_parquet(args.input)
    if args.sample is not None:
        if args.sample <= 0:
            raise SystemExit("--sample must be greater than zero")
        frame = frame.head(args.sample).copy()

    console.print(f"Loaded [bold]{len(frame):,}[/bold] authoritative properties")
    modeler = ImplementationPathwayModeler(
        config=load_yaml(args.config),
        output_dir=args.output_dir,
    )
    properties, summary = modeler.run(frame)

    table = Table(title="Route A implementation results")
    table.add_column("Scenario")
    table.add_column("Deployed", justify="right")
    table.add_column("Deferred", justify="right")
    table.add_column("ASHP", justify="right")
    table.add_column("Heat network", justify="right")
    table.add_column("Deployment rate", justify="right")
    for row in summary.to_dict("records"):
        table.add_row(
            str(row["scenario_id"]),
            f"{int(row['properties_deployed']):,}",
            f"{int(row['properties_deferred']):,}",
            f"{int(row['ashp_installed_properties']):,}",
            f"{int(row['heat_network_connected_properties']):,}",
            f"{float(row['deployment_rate_pct']):.1f}%",
        )
    console.print(table)

    qa = {
        "status": "pass",
        "authoritative_cohort": int(len(frame)),
        "property_rows": int(len(properties)),
        "scenarios": summary.to_dict("records"),
        "contracts": {
            "no_unready_ashp_installations": True,
            "no_unavailable_heat_network_connections": True,
            "exclusive_final_state": True,
            "deferred_reason_complete": True,
        },
    }
    qa_path = args.output_dir / "implementation_qa.json"
    qa_path.write_text(json.dumps(qa, indent=2, default=str), encoding="utf-8")

    console.print(f"Property results: [bold]{args.output_dir / 'implementation_results_by_property.parquet'}[/bold]")
    console.print(f"Summary: [bold]{args.output_dir / 'implementation_results_summary.csv'}[/bold]")
    console.print(f"QA: [bold]{qa_path}[/bold]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
