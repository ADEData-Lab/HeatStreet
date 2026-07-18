from copy import deepcopy
from pathlib import Path
import os
import subprocess
import sys

import pytest

import run_analysis
from config.config import (
    RUN_CONFIG_ENV,
    build_run_config,
    get_energy_price_profiles,
    get_scenario_definitions,
    get_resolved_energy_prices,
    load_config,
)
from src.reporting.window_economics import generate_window_economics
from src.reporting.one_stop_report import OneStopReportGenerator
from src.utils.run_integrity import RunContext


JANUARY_ID = "january_client_report_provisional"


def test_utf8_run_snapshot_loads_when_windows_utf8_mode_is_disabled(tmp_path):
    snapshot = tmp_path / "config_snapshot.yaml"
    snapshot.write_text(
        "energy_price_profiles:\n"
        "  default_profile: unicode_profile\n"
        "  profiles:\n"
        "    unicode_profile:\n"
        "      label: 'Period → verified'\n"
        "      effective_period: 'Test period'\n"
        "      gas_gbp_per_kwh: 0.1\n"
        "      electricity_gbp_per_kwh: 0.2\n"
        "      standing_charges_included: false\n"
        "      source_note: 'UTF-8 regression'\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env[RUN_CONFIG_ENV] = str(snapshot)
    completed = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8=0",
            "-c",
            "from config.config import load_config; assert load_config()['energy_price_profiles']['default_profile'] == 'unicode_profile'",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_january_provisional_profile_is_exact_configured_default():
    section = get_energy_price_profiles(load_config())
    profile = section["profiles"][JANUARY_ID]
    assert section["default_profile"] == JANUARY_ID
    assert profile["label"] == "January client report provisional prices"
    assert profile["gas_gbp_per_kwh"] == 0.0624
    assert profile["electricity_gbp_per_kwh"] == 0.245
    assert profile["standing_charges_included"] is False
    assert profile["status"] == "legacy reproducibility profile"


def test_run_config_selection_is_isolated_and_does_not_rewrite_yaml():
    config_path = Path("config/config.yaml")
    before = config_path.read_bytes()
    config = load_config()
    configured = deepcopy(config)
    configured["energy_price_profiles"]["profiles"]["verified_test_period"] = {
        "label": "Verified test period",
        "effective_period": "Test only",
        "effective_start": "2026-01-01",
        "effective_end": "2026-03-31",
        "gas_gbp_per_kwh": 0.08,
        "electricity_gbp_per_kwh": 0.30,
        "standing_charges_included": False,
        "status": "test fixture",
        "source_note": "Test fixture source",
        "validation_note": "Test fixture only",
    }
    run_config = build_run_config(
        configured, "verified_test_period", explicit_selection=True
    )
    assert get_resolved_energy_prices(run_config) == {
        "gas": 0.08,
        "electricity": 0.30,
        "profile_id": "verified_test_period",
    }
    assert "resolved_energy_price_profile" not in config
    assert config_path.read_bytes() == before


def test_unknown_cli_profile_fails_clearly(capsys):
    with pytest.raises(SystemExit):
        run_analysis.parse_args(["--energy-price-profile", "does_not_exist"])
    assert "unknown energy price profile" in capsys.readouterr().err


def test_default_cli_profile_is_january():
    args = run_analysis.parse_args([])
    profile_id, explicit = run_analysis._select_energy_price_profile(
        args, object(), load_config()
    )
    assert profile_id == JANUARY_ID
    assert explicit is False


def test_studio_energy_period_control_displays_rates_and_standing_charge_treatment(monkeypatch):
    captured = {}

    def prompt(_ui, prompt_type, **kwargs):
        captured.update(kwargs)
        assert prompt_type == "select"
        return kwargs["choices"][0]

    monkeypatch.setattr(run_analysis, "_tui_prompt", prompt)
    args = run_analysis.parse_args([])
    ui = type("Studio", (), {"is_full_tui": True})()
    selected, explicit = run_analysis._select_energy_price_profile(args, ui, load_config())
    assert selected == JANUARY_ID
    assert explicit is True
    assert captured["title"] == "Energy price period"
    assert "gas 6.24 p/kWh" in captured["labels"][0]
    assert "electricity 24.50 p/kWh" in captured["labels"][0]
    assert "standing charges excluded" in captured["labels"][0]
    assert "original client report" in captured["message"]


def test_window_economics_uses_run_snapshot_profile(tmp_path, monkeypatch):
    config = build_run_config(load_config(), JANUARY_ID)
    monkeypatch.setattr("src.reporting.window_economics.load_config", lambda: config)
    frame = generate_window_economics(tmp_path / "windows.csv")
    assert frame["energy_price_gbp_per_kwh"].eq(0.0624).all()


def test_spatial_hybrid_stock_scenario_remains_distinct():
    config = load_config()
    scenarios = get_scenario_definitions()
    assert "hybrid" in config["scenarios"]["publish"]
    label = scenarios["hybrid"]["name"]
    assert "heat network" in label.casefold() or "spatial" in label.casefold()
    assert "boiler" not in label.casefold()


def test_selected_profile_is_carried_by_run_and_one_stop_metadata(tmp_path):
    profile = build_run_config(load_config(), JANUARY_ID)["resolved_energy_price_profile"]
    context = RunContext("run-one", dataset_fingerprint="fingerprint", energy_price_profile=profile)
    assert context.to_dict()["energy_price_profile"]["profile_id"] == JANUARY_ID
    section = OneStopReportGenerator(output_dir=tmp_path, processed_dir=tmp_path)._build_section_1(
        {"energy_price_profile": profile}
    )
    values = {item["key"]: item["value"] for item in section["datapoints"]}
    assert values["energy_price_profile_id"] == JANUARY_ID
