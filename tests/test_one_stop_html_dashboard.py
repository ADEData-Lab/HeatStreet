import json

from src.reporting.one_stop_html_dashboard import _render_heat_street_dashboard_html


def test_rich_dashboard_uses_current_one_stop_schema_and_complete_categories():
    payload = {
        "metadata": {},
        "sections": {
            "section_3": {
                "datapoints": [
                    {
                        "key": "glazing_distribution",
                        "value": {"double": 10, "single": 2, "mixed": 3, "triple": 0, "unknown": 1},
                    },
                    {"key": "wall_type_distribution", "value": {"solid_brick": 12, "unknown": 4}},
                ],
                "tables": [],
            },
            "section_6": {
                "datapoints": [],
                "tables": [
                    {
                        "caption": "Route A Implementation Pathways",
                        "data": [{"scenario_id": "ashp_implementation", "capital_cost_total": 1}],
                    },
                    {
                        "caption": "Stock-wide Scenario Stress Tests",
                        "data": [
                            {
                                "scenario_id": "hybrid",
                                "capital_cost_per_property": 26659.81,
                                "aggregate_simple_payback_years": 72.85,
                            }
                        ],
                    },
                ],
            },
            "section_7": {
                "datapoints": [],
                "tables": [
                    {
                        "caption": "Heat Network vs Heat Pump Comparison",
                        "data": [
                            {
                                "scenario_id": "heat_pump",
                                "scenario": "Heat pump pathway",
                                "total_properties": 10,
                                "capital_cost_per_property": 10000,
                                "annual_bill_savings": 2500,
                                "annual_co2_reduction_kg": 12000,
                                "property_simple_payback_mean_years": 18,
                            }
                        ],
                    }
                ],
            },
            "section_8": {
                "datapoints": [
                    {
                        "key": "tipping_point_analysis_status",
                        "value": "Not available (curve file not generated)",
                    }
                ],
                "tables": [],
            },
            "section_9": {
                "datapoints": [],
                "tables": [
                    {
                        "caption": "Subsidy Sensitivity Analysis - Full Results",
                        "data": [
                            {
                                "scenario": "heat_pump",
                                "subsidy_percentage": 0,
                                "aggregate_simple_payback_years": 67.5,
                                "estimated_uptake_rate": 0.02,
                                "properties_upgraded": 10,
                                "public_expenditure_total": 0,
                            }
                        ],
                    }
                ],
            },
            "section_10": {
                "datapoints": [],
                "tables": [
                    {
                        "caption": "Borough-Level Breakdown - Full Data",
                        "data": [{"LOCAL_AUTHORITY": "E09000025", "property_count": 10}],
                    }
                ],
            },
        },
    }

    html = _render_heat_street_dashboard_html(payload)

    assert html is not None
    assert "findSectionTable(oneStop, 'section_6', 'stock-wide scenario')" in html
    assert "r.aggregate_simple_payback_years" in html
    assert "row.capital_cost_per_property" in html
    assert "row.annual_bill_savings" in html
    assert "btn.hidden = !scenarioData[btn.dataset.scenario]" in html
    assert "function orderedDistribution(distribution, preferred = [])" in html
    assert "ordered.push(...[...values.values()]" in html
    assert "{ key: 'mixed', label: 'Mixed Glazing' }" in html
    assert "{ key: 'unknown', label: 'Unknown' }" in html
    assert "r.aggregate_simple_payback_years" in html
    assert "tipping_point_analysis_status" in html
    assert "BOROUGH_NAME_BY_CODE[code]" in html
    assert "if (v === null || v === undefined" in html
    embedded = json.dumps(payload, ensure_ascii=False)
    assert embedded in html
