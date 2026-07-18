"""Traceable, configuration-backed window economics output."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from config.config import DATA_OUTPUTS_DIR, load_config
from src.modeling.contracts import PAYBACK_DEFINITION


def generate_window_economics(output_path: Path | None = None) -> pd.DataFrame:
    config = load_config()
    assumptions = config.get("window_economics", {})
    costs = config.get("costs", {})
    from config.config import get_resolved_energy_prices
    gas_price = float(get_resolved_energy_prices(config)["gas"])
    annual_energy = float(assumptions.get("assumed_annual_energy_kwh", 0))
    rows = []
    for measure in assumptions.get("measures", []):
        capital_cost = float(costs[measure["capital_cost_key"]])
        saving_fraction = float(measure["saving_fraction"])
        annual_energy_saving = annual_energy * saving_fraction
        annual_bill_saving = annual_energy_saving * gas_price
        rows.append({
            "measure": measure["measure"],
            "capital_cost_gbp": capital_cost,
            "assumed_annual_energy_kwh": annual_energy,
            "energy_saving_fraction": saving_fraction,
            "annual_energy_saving_kwh": annual_energy_saving,
            "energy_price_gbp_per_kwh": gas_price,
            "annual_bill_saving_gbp": annual_bill_saving,
            "simple_payback_years": capital_cost / annual_bill_saving if annual_bill_saving > 0 else None,
            "payback_status": "valid" if annual_bill_saving > 0 else "non_positive_annual_savings",
            "payback_definition": PAYBACK_DEFINITION,
            "assumption_source": measure["source"],
            "interpretation": assumptions.get("interpretation", ""),
        })
    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError("window_economics.measures must configure at least one measure")
    path = Path(output_path or (DATA_OUTPUTS_DIR / "window_economics.csv"))
    path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(path, index=False)
    return result
