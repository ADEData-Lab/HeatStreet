"""
Comparison reporting utilities for HP vs HN pathways.

Generates CSV, markdown snippets, and optional figures comparing
heat pump and heat network outcomes using pathway_results_by_property.parquet.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from loguru import logger

from config.config import DATA_OUTPUTS_DIR, get_cost_assumptions, get_heat_network_params, load_config
from src.modeling.pathway_model import PATHWAYS


@dataclass
class ComparisonResult:
    pathway_id: str
    pathway_name: str
    n_homes: int
    stats: Dict[str, Dict[str, float]]


class ComparisonReporter:
    """Generate comparison artefacts between HP and HN pathways."""

    def __init__(self, outputs_dir: Optional[Path] = None):
        self.outputs_dir = outputs_dir or DATA_OUTPUTS_DIR
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.comparisons_dir = self.outputs_dir / "comparisons"
        self.comparisons_dir.mkdir(parents=True, exist_ok=True)
        self.figures_dir = self.outputs_dir / "figures"
        self.figures_dir.mkdir(parents=True, exist_ok=True)

        sns.set_style("whitegrid")
        sns.set_palette("husl")
        plt.rcParams['figure.figsize'] = (12, 6)
        plt.rcParams['font.size'] = 11

        self.config = load_config()
        self.costs = get_cost_assumptions()
        self.hn_params = get_heat_network_params()
        self.hybrid_warning = False

    @staticmethod
    def _summary(series: pd.Series) -> Dict[str, float]:
        clean = series.replace([np.inf, -np.inf], np.nan).dropna()
        if clean.empty:
            return {k: np.nan for k in ['mean', 'median', 'p10', 'p90', 'min', 'max']}

        return {
            'mean': clean.mean(),
            'median': clean.median(),
            'p10': clean.quantile(0.10),
            'p90': clean.quantile(0.90),
            'min': clean.min(),
            'max': clean.max(),
        }

    def _prepare_metrics(self, df: pd.DataFrame) -> Dict[str, Dict[str, float]]:
        metrics = {
            'capex': self._summary(df['total_capex']),
            'bill_saving': self._summary(df['annual_bill_saving']),
            'bill_change': self._summary(df['annual_bill'] - df['baseline_bill']),
            'co2_saving': self._summary(df['co2_saving_tonnes']),
            'co2_change': self._summary(df['annual_co2_tonnes'] - df['baseline_co2_tonnes']),
            'payback': self._summary(df['simple_payback_years']),
        }
        return metrics

    def _format_range(self, stats: Dict[str, float]) -> str:
        if np.isnan(stats.get('p10', np.nan)):
            return "N/A"
        return f"{stats['p10']:.0f}–{stats['p90']:.0f}"

    def _scenario_name(self, pathway_id: str) -> str:
        pathway = PATHWAYS.get(pathway_id)
        return pathway.name if pathway else pathway_id

    def load_results(self, path: Optional[Path] = None) -> pd.DataFrame:
        results_path = path or (self.outputs_dir / "pathway_results_by_property.parquet")
        logger.info(f"Loading pathway results from {results_path}")
        return pd.read_parquet(results_path)

    def _filter_scenarios(self, df: pd.DataFrame, requested: Iterable[str]) -> List[ComparisonResult]:
        available_ids = set(df['pathway_id'].unique())
        comparison_results: List[ComparisonResult] = []

        for pathway_id in requested:
            if pathway_id not in available_ids:
                logger.warning(f"Pathway {pathway_id} not found in results; skipping")
                continue

            subset = df[df['pathway_id'] == pathway_id]
            comparison_results.append(
                ComparisonResult(
                    pathway_id=pathway_id,
                    pathway_name=self._scenario_name(pathway_id),
                    n_homes=len(subset),
                    stats=self._prepare_metrics(subset)
                )
            )
        return comparison_results

    def _comparison_rows(self, comparisons: List[ComparisonResult]) -> pd.DataFrame:
        records = []
        for comp in comparisons:
            row = {
                'pathway_id': comp.pathway_id,
                'pathway_name': comp.pathway_name,
                'n_homes': comp.n_homes,
            }
            for metric, stats in comp.stats.items():
                for stat_name, value in stats.items():
                    row[f"{metric}_{stat_name}"] = value
            records.append(row)
        return pd.DataFrame(records)

    def _write_markdown(self, comparisons: List[ComparisonResult]):
        snippet_path = self.comparisons_dir / "hn_vs_hp_report_snippet.md"

        tariff_info = self.config.get('energy_prices', {}).get('current', {})
        hp_cop = self.config.get('heat_pump', {}).get('scop', 3.0)
        connection_cost = self.costs.get('district_heating_connection', 5000)
        hn_efficiency = self.hn_params.get('distribution_efficiency', 1.0)
        hn_carbon = self.hn_params.get(
            'carbon_intensity_kg_per_kwh',
            self.config.get('carbon_factors', {}).get('current', {}).get('heat_network')
        )

        lines = [
            "# Heat pump vs heat network comparison",
            "",
            "**Sign convention:** savings columns are positive when costs/emissions fall;",
            " change columns (bill_change/co2_change) are negative when costs/emissions drop.",
            "", "**Tariffs & performance assumptions:**", f"- Electricity: £{tariff_info.get('electricity', 0.245):.3f}/kWh",
            f"- Gas: £{tariff_info.get('gas', 0.0624):.4f}/kWh",
            f"- Heat network tariff: £{self.hn_params.get('tariff_per_kwh', 0.08):.3f}/kWh",
            f"- Heat network delivery efficiency: {hn_efficiency*100:.0f}% (tariff applied to input energy)",
            f"- Heat network carbon intensity: {hn_carbon:.3f} kgCO₂/kWh supplied" if hn_carbon is not None else "- Heat network carbon intensity: not specified",
            f"- Heat pump COP (SCOP): {hp_cop:.2f}; shared ground loop proxy shown if available.",
            f"- HN connection cost assumption: £{connection_cost:,.0f} per home (sensitivity available via CLI).",
            "", "## Scenario ranges (p10–p90)",
        ]

        for comp in comparisons:
            lines.append(f"- **{comp.pathway_name}**: capex {self._format_range(comp.stats['capex'])} £, "
                         f"bill saving {self._format_range(comp.stats['bill_saving'])} £/yr, "
                         f"CO₂ saving {self._format_range(comp.stats['co2_saving'])} t/yr, "
                         f"payback {self._format_range(comp.stats['payback'])} yrs")

        lines.append("")
        lines.append("*Note: bill/CO₂ savings use baseline-minus-scenario values (positive = saving); "
                     "bill_change/co2_change columns show signed deltas where negatives indicate reductions." \
                     " Heat networks are modelled as a supply switch (no extra demand reduction; non-heating demand remains on gas) with network tariffs and carbon applied to supplied heat.*")

        lines.append("")
        lines.append("*Hybrid pathway routing is mutually exclusive: homes connect to heat networks where ready, with others receiving ASHPs to avoid double-counting benefits.*")

        if self.hybrid_warning:
            lines.append("")
            lines.append("> Warning: Hybrid pathway averages match fabric-only results; review heat tech assumptions.")

        snippet_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"Wrote markdown snippet to {snippet_path}")

        if self.hybrid_warning:
            logger.warning("Hybrid pathway averages match fabric-only results; review assumptions.")

    def _plot_comparison(self, df: pd.DataFrame):
        plot_path = self.figures_dir / "hn_vs_hp_comparison.png"
        metrics = ['capex_mean', 'bill_saving_mean', 'co2_saving_mean']
        metric_labels = ['CAPEX (£)', 'Annual bill saving (£/yr)', 'Annual CO₂ saving (t/yr)']

        plt.clf()
        fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=False)

        for ax, metric, label in zip(axes, metrics, metric_labels):
            sns.barplot(data=df, x='pathway_name', y=metric, ax=ax, edgecolor='black')
            ax.set_xlabel('Pathway')
            ax.set_ylabel(label)
            plt.setp(ax.get_xticklabels(), rotation=30, ha='right')
            ax.axhline(0, color='black', linewidth=0.8)

        plt.tight_layout()
        fig.savefig(plot_path, dpi=300, bbox_inches='tight')
        plt.close(fig)
        logger.info(f"Saved comparison plot to {plot_path}")

    def _warn_if_hybrid_equals_fabric(self, df: pd.DataFrame):
        fabric = df[df['pathway_id'] == 'fabric_only']['total_capex'].mean()
        hybrid = df[df['pathway_id'] == 'fabric_plus_hp_plus_hn']['total_capex'].mean()

        if pd.isna(fabric) or pd.isna(hybrid):
            return

        if np.isclose(fabric, hybrid):
            self.hybrid_warning = True
            logger.warning(
                "Hybrid pathway average cost matches fabric-only; this may indicate missing heat technology costs."
            )

    def generate_comparisons(
        self,
        df: Optional[pd.DataFrame] = None,
        results_path: Optional[Path] = None,
    ) -> pd.DataFrame:
        """Generate CSV, markdown, and optional figure comparing HP/HN scenarios."""
        self.hybrid_warning = False
        results_df = df if df is not None else self.load_results(results_path)

        self._warn_if_hybrid_equals_fabric(results_df)

        scenario_ids = [
            'fabric_plus_hp_only',
            'fabric_plus_hn_only',
            'fabric_plus_hp_plus_hn',
        ]

        if 'fabric_plus_shared_ground_loop_proxy' in results_df['pathway_id'].unique():
            scenario_ids.append('fabric_plus_shared_ground_loop_proxy')

        comparisons = self._filter_scenarios(results_df, scenario_ids)
        comparison_df = self._comparison_rows(comparisons)

        csv_path = self.comparisons_dir / "hn_vs_hp_comparison.csv"
        comparison_df.to_csv(csv_path, index=False)
        logger.info(f"Saved comparison CSV to {csv_path}")

        self._write_markdown(comparisons)
        if not comparison_df.empty:
            self._plot_comparison(comparison_df)

        return comparison_df
