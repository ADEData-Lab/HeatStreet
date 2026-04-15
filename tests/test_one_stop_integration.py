import json
from pathlib import Path

import pandas as pd

import run_analysis
from src.reporting.dashboard_data_builder import DashboardDataBuilder
from src.reporting.one_stop_report import OneStopReportGenerator


def test_model_scenarios_generates_comparisons_when_one_stop_only(monkeypatch, tmp_path):
    comparison_calls = []

    class FakeScenarioModeler:
        def model_all_scenarios(self, df):
            return {
                "heat_pump": {
                    "capital_cost_per_property": 10000,
                    "capital_cost_total": 100000,
                    "annual_co2_reduction_kg": 1000,
                    "annual_bill_savings": 500,
                    "average_payback_years": 20,
                }
            }

        def model_subsidy_sensitivity_multi(self, df, scenario_names=None):
            return {"heat_pump": {"base": {"capital_cost_per_property": 10000}}}

        def save_results(self):
            return {}

    class FakePathwayModeler:
        def __init__(self):
            self.output_dir = tmp_path / "outputs"
            self.output_dir.mkdir(parents=True, exist_ok=True)

        def model_all_pathways(self, df):
            return pd.DataFrame({"pathway_id": ["fabric_plus_hp_only"], "total_capex": [1000]})

        def generate_pathway_summary(self, df):
            return pd.DataFrame({"Tier": ["Tier 3"], "Property Count": [1], "Percentage": [100], "Recommended Pathway": ["Heat Pump"]})

        def export_results(self, pathway_results, pathway_summary):
            property_path = self.output_dir / "pathway_results_by_property.parquet"
            summary_path = self.output_dir / "pathway_results_summary.csv"
            property_path.write_text("placeholder", encoding="utf-8")
            pathway_summary.to_csv(summary_path, index=False)
            return property_path, summary_path

    class FakeComparisonReporter:
        def __init__(self):
            self.comparisons_dir = tmp_path / "comparisons"
            self.comparisons_dir.mkdir(parents=True, exist_ok=True)

        def generate_comparisons(self, results_path=None):
            comparison_calls.append(results_path)
            output = self.comparisons_dir / "hn_vs_hp_comparison.csv"
            pd.DataFrame(
                [
                    {
                        "pathway_id": "fabric_plus_hp_only",
                        "pathway_name": "Heat Pump",
                        "n_homes": 1,
                        "capex_mean": 1000,
                        "bill_saving_mean": 120,
                        "co2_saving_mean": 0.5,
                        "payback_mean": 8,
                    }
                ]
            ).to_csv(output, index=False)
            return pd.read_csv(output)

    class FakeReportGenerator:
        def plot_fabric_tipping_point_analysis(self):
            return None

    monkeypatch.setattr(run_analysis, "ScenarioModeler", FakeScenarioModeler)
    monkeypatch.setattr(run_analysis, "PathwayModeler", FakePathwayModeler)
    monkeypatch.setattr(run_analysis, "ComparisonReporter", FakeComparisonReporter)
    monkeypatch.setattr(run_analysis, "is_one_stop_only", lambda config=None: True)

    import src.reporting.visualizations as visualizations

    monkeypatch.setattr(visualizations, "ReportGenerator", FakeReportGenerator)

    scenario_results, subsidy_results = run_analysis.model_scenarios(pd.DataFrame({"value": [1]}))

    assert scenario_results["heat_pump"]["capital_cost_per_property"] == 10000
    assert subsidy_results == {"base": {"capital_cost_per_property": 10000}}
    assert len(comparison_calls) == 1


def test_generate_one_stop_report_attempts_comparison_rebuild(monkeypatch, tmp_path):
    rebuild_calls = []

    def fake_ensure(df=None, analysis_logger=None):
        rebuild_calls.append(df is not None)
        comparison_dir = tmp_path / "data" / "outputs" / "comparisons"
        comparison_dir.mkdir(parents=True, exist_ok=True)
        comparison_path = comparison_dir / "hn_vs_hp_comparison.csv"
        pd.DataFrame(
            [
                {
                    "pathway_id": "fabric_plus_hp_only",
                    "pathway_name": "Heat Pump",
                    "n_homes": 5,
                    "capex_mean": 10000,
                    "bill_saving_mean": 250,
                    "co2_saving_mean": 1.2,
                    "payback_mean": 18,
                }
            ]
        ).to_csv(comparison_path, index=False)
        return {"comparison_csv": comparison_path, "rebuilt": True}

    class FakeGenerator:
        def generate(self):
            comparison_path = tmp_path / "data" / "outputs" / "comparisons" / "hn_vs_hp_comparison.csv"
            assert comparison_path.exists()
            output_path = tmp_path / "data" / "outputs" / "one_stop_output.json"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("{}", encoding="utf-8")
            return output_path

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_analysis, "ensure_hp_hn_comparison_outputs", fake_ensure)

    import src.reporting.one_stop_report as one_stop_report

    monkeypatch.setattr(one_stop_report, "OneStopReportGenerator", FakeGenerator)

    output_path = run_analysis.generate_one_stop_report(pd.DataFrame({"value": [1]}))

    assert output_path.exists()
    assert rebuild_calls == [True]


def test_package_dashboard_assets_rebuilds_missing_comparison_for_dashboard(monkeypatch, tmp_path):
    def fake_ensure(df=None, analysis_logger=None):
        comparison_dir = tmp_path / "data" / "outputs" / "comparisons"
        comparison_dir.mkdir(parents=True, exist_ok=True)
        comparison_path = comparison_dir / "hn_vs_hp_comparison.csv"
        pd.DataFrame(
            [
                {
                    "pathway_id": "fabric_plus_hp_only",
                    "pathway_name": "Heat Pump",
                    "n_homes": 10,
                    "capex_mean": 10000,
                    "bill_saving_mean": 250,
                    "co2_saving_mean": 1.2,
                    "payback_mean": 18,
                }
            ]
        ).to_csv(comparison_path, index=False)
        return {"comparison_csv": comparison_path, "rebuilt": True}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_analysis, "ensure_hp_hn_comparison_outputs", fake_ensure)

    import src.reporting.dashboard_data_builder as dashboard_data_builder

    class LocalBuilder(dashboard_data_builder.DashboardDataBuilder):
        def __init__(self):
            super().__init__(output_dir=tmp_path / "data" / "outputs")

    monkeypatch.setattr(dashboard_data_builder, "DashboardDataBuilder", LocalBuilder)

    result = run_analysis.package_dashboard_assets(
        archetype_results={},
        scenario_results={},
        readiness_summary={},
        pathway_summary=None,
        additional_reports={},
        subsidy_results={},
        df_validated=pd.DataFrame({"value": [1]}),
        analysis_logger=None,
    )

    dataset_path = tmp_path / "data" / "outputs" / "dashboard" / "dashboard-data.json"
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))

    assert result is True
    assert len(payload["hnVsHpComparisonData"]) == 1


def test_dashboard_data_builder_includes_integrated_one_stop_outputs(tmp_path):
    builder = DashboardDataBuilder(output_dir=tmp_path)
    dataset = builder.build_dataset(
        archetype_results={},
        scenario_results={},
        readiness_summary={},
        pathway_summary=pd.DataFrame(
            [{"Tier": "Tier 3", "Property Count": 10, "Percentage": 50, "Recommended Pathway": "Heat Pump"}]
        ),
        borough_breakdown=pd.DataFrame(
            [{"LOCAL_AUTHORITY": "E09000025", "property_count": 12, "mean_epc_rating": 61.2, "mean_energy_kwh_m2_year": 240.5}]
        ),
        borough_priority_ranking=pd.DataFrame(
            [{"borough": "Newham", "property_count": 12, "mean_epc_score": 61.2, "mean_energy_intensity_kwh_m2_year": 240.5, "composite_priority_score": 0.9123, "rank": 1}]
        ),
        tenure_segmentation=pd.DataFrame(
            [{"tenure_group": "private_rented_sector", "property_count": 5, "share_pct": 50.0, "mean_sap_score": 58.4, "mean_energy_intensity_kwh_m2_year": 220.5, "wall_insulation_rate_pct": 10.0, "pct_gas_boiler": 80.0, "pct_heat_pump": 10.0, "pct_district": 10.0}]
        ),
        case_street_summary={"case_street": {"street_name": "Shakespeare Crescent", "property_count": 3, "mean_sap_score": 62.0, "mode_epc_band": "D", "epc_band_distribution": {"D": 3}}},
        case_street_df=pd.DataFrame(
            [{"ADDRESS1": "1 Shakespeare Crescent", "POSTCODE": "E12 1AA", "CURRENT_ENERGY_RATING": "D", "CURRENT_ENERGY_EFFICIENCY": 62}]
        ),
        heat_network_thresholds=pd.DataFrame(
            [{"tier": "Tier 3", "properties_in_tier": 10, "connection_rate": 0.6, "properties_connected": 6, "total_infrastructure_cost": 100000, "total_annual_revenue": 12000, "network_payback_years": 8.3, "viable_25yr_threshold": True}]
        ),
        hn_vs_hp_comparison=pd.DataFrame(
            [
                {"pathway_id": "fabric_plus_hp_only", "pathway_name": "Heat Pump", "n_homes": 10, "capex_mean": 10000, "bill_saving_mean": 250, "co2_saving_mean": 1.2, "payback_mean": 18},
                {"pathway_id": "fabric_plus_hn_only", "pathway_name": "Heat Network", "n_homes": 8, "capex_mean": 9000, "bill_saving_mean": 180, "co2_saving_mean": 0.9, "payback_mean": 22},
            ]
        ),
        subsidy_results={},
        df_validated=pd.DataFrame(),
    )

    assert dataset["boroughPriorityData"][0]["borough"] == "Newham"
    assert dataset["tenureSegmentationData"][0]["label"] == "Private rented"
    assert dataset["caseStreetData"]["summary"]["streetName"] == "Shakespeare Crescent"
    assert dataset["heatNetworkThresholdData"][0]["viable25yrThreshold"] is True
    assert len(dataset["hnVsHpComparisonData"]) == 2
    assert dataset["summaryStats"]["costAdvantageDHvsHP"] == 1000.0


def test_one_stop_report_embeds_integrated_tables(tmp_path):
    output_dir = tmp_path / "outputs"
    processed_dir = tmp_path / "processed"
    (output_dir / "comparisons").mkdir(parents=True, exist_ok=True)
    (output_dir / "reports").mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    (processed_dir / "validation_report.json").write_text("{}", encoding="utf-8")
    (processed_dir / "methodological_adjustments_summary.json").write_text("{}", encoding="utf-8")
    (output_dir / "run_metadata.json").write_text("{}", encoding="utf-8")

    pd.DataFrame(
        [
            {
                "pathway_id": "fabric_plus_hp_only",
                "pathway_name": "Heat Pump",
                "n_homes": 10,
                "capex_mean": 10000,
                "bill_saving_mean": 250,
                "co2_saving_mean": 1.2,
                "payback_mean": 18,
            }
        ]
    ).to_csv(output_dir / "comparisons" / "hn_vs_hp_comparison.csv", index=False)
    pd.DataFrame(
        [{"LOCAL_AUTHORITY": "E09000025", "LOCAL_AUTHORITY_NAME": "Newham", "property_count": 12, "mean_epc_rating": 61.2, "mean_energy_kwh_m2_year": 240.5}]
    ).to_csv(output_dir / "borough_breakdown.csv", index=False)
    pd.DataFrame(
        [{"borough": "Newham", "property_count": 12, "mean_epc_score": 61.2, "mean_energy_intensity_kwh_m2_year": 240.5, "composite_priority_score": 0.9123, "rank": 1}]
    ).to_csv(output_dir / "reports" / "borough_priority_ranking.csv", index=False)
    pd.DataFrame(
        [{"tenure_group": "private_rented_sector", "property_count": 5, "share_pct": 50.0, "mean_sap_score": 58.4, "mean_energy_intensity_kwh_m2_year": 220.5, "wall_insulation_rate_pct": 10.0, "pct_gas_boiler": 80.0, "pct_heat_pump": 10.0, "pct_district": 10.0}]
    ).to_csv(output_dir / "reports" / "tenure_segmentation.csv", index=False)
    pd.DataFrame(
        [{"tier": "Tier 3", "properties_in_tier": 10, "connection_rate": 0.6, "properties_connected": 6, "total_infrastructure_cost": 100000, "annual_standing_charge_revenue": 1000, "annual_heat_revenue": 11000, "total_annual_revenue": 12000, "network_payback_years": 8.3, "viable_25yr_threshold": True, "avg_consumption_per_property": 15000}]
    ).to_csv(output_dir / "heat_network_connection_thresholds.csv", index=False)
    pd.DataFrame(
        [{"ADDRESS1": "1 Shakespeare Crescent", "POSTCODE": "E12 1AA", "CURRENT_ENERGY_RATING": "D", "CURRENT_ENERGY_EFFICIENCY": 62}]
    ).to_csv(output_dir / "shakespeare_crescent_extract.csv", index=False)

    report_path = OneStopReportGenerator(output_dir=output_dir, processed_dir=processed_dir).generate()
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    section_7 = payload["sections"]["section_7"]
    section_10 = payload["sections"]["section_10"]
    section_11 = payload["sections"]["section_11"]

    assert section_7["tables"][0]["caption"] == "Heat Network vs Heat Pump Comparison"
    assert any(table["caption"] == "Borough Priority Ranking" for table in section_10["tables"])
    assert any(table["caption"] == "Tenure Segmentation" for table in section_10["tables"])
    assert any(table["caption"] == "Heat Network Connection Thresholds" for table in section_10["tables"])
    assert any(dp["key"] == "top_priority_borough" for dp in section_10["datapoints"])
    assert section_11["tables"][0]["caption"] == "Case Street Sample (first 20 properties)"
