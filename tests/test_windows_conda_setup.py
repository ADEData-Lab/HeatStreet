from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def read_text(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_environment_yml_is_canonical_windows_setup():
    text = read_text("environment.yml")

    assert "name: heatstreet" in text
    assert "- conda-forge" in text
    assert "- python=3.11" in text
    assert "- geopandas" in text
    assert "- fiona" in text
    assert "- gdal" in text
    assert "- pyproj" in text
    assert "- shapely" in text
    assert "- rtree" in text
    assert "- pyogrio" in text
    assert "- folium" in text
    assert "- pip:" in text
    assert "- -r requirements.txt" in text


def test_requirements_spatial_warns_windows_users_off_pip():
    text = read_text("requirements-spatial.txt").lower()

    assert "do not use this file as the primary windows install path" in text
    assert "environment.yml" in text
    assert "gdal_version" in text
    assert "gdal-config" in text
    assert "linux or macos" in text


def test_run_conda_powershell_checks_for_mixed_interpreters():
    text = read_text("run-conda.ps1")

    expected_snippets = [
        "environment.yml",
        "where python",
        "where pip",
        "conda info --json",
        'conda list | findstr /i "python geopandas fiona gdal shapely"',
        "appdata\\roaming\\python",
        "Python 3.13 and 3.14 are not a supported default",
        "python --version does not match the active Conda environment interpreter.",
        "python is running outside the active Conda environment.",
        "python does not resolve inside the active Conda environment.",
        "pip does not resolve inside the active Conda environment.",
    ]

    for snippet in expected_snippets:
        assert snippet in text


def test_run_conda_batch_delegates_to_powershell_launcher():
    text = read_text("run-conda.bat")

    assert "run-conda.ps1" in text
    assert "-ExecutionPolicy Bypass" in text


def test_run_conda_only_prints_success_footer_on_zero_exit():
    text = read_text("run-conda.ps1")

    assert "python run_analysis.py" in text
    assert "$analysisExitCode = $LASTEXITCODE" in text
    assert "if ($analysisExitCode -eq 0)" in text
    assert 'Write-Host "[OK] Analysis complete"' in text
    assert 'Write-Host "[X] Analysis failed. Check the errors above."' in text
    assert "exit $analysisExitCode" in text


def test_run_conda_reports_canonical_windows_launcher_and_alignment():
    text = read_text("run-conda.ps1")

    assert 'Write-Host "[OK] python executable = $pythonExecutable"' in text
    assert 'Write-Host "[OK] pip executable = $pipPath"' in text
    assert "Canonical Windows launch path = .\\run-conda.ps1 (or run-conda.bat)" in text


def test_windows_setup_docs_reference_environment_yml():
    for relative_path in (
        "README.md",
        "QUICKSTART.md",
        "docs/SPATIAL_SETUP.md",
        "docs/GIS_DATA.md",
    ):
        text = read_text(relative_path)
        assert "environment.yml" in text, relative_path


def test_runtime_guidance_prefers_conda_on_windows():
    run_analysis_text = read_text("run_analysis.py")
    spatial_text = read_text("src/spatial/heat_network_analysis.py")

    assert "conda env create -f environment.yml" in run_analysis_text
    assert "where python" in run_analysis_text
    assert "where pip" in run_analysis_text
    assert "GDAL_VERSION or gdal-config" in run_analysis_text

    assert "conda env create -f environment.yml" in spatial_text
    assert "If Fiona/GDAL asks for GDAL_VERSION or gdal-config on Windows" in spatial_text


def test_runtime_mismatch_docs_describe_startup_diagnostics_workflow():
    text = read_text("README.md")

    assert "Runtime mismatch: startup diagnostics show old Phase 1 behavior" in text
    assert "sys.executable" in text
    assert "run_analysis.__file__" in text
    assert "download_data line" in text
    assert "download_national_domestic_dataset line" in text
    assert "different checkout" in text
    assert "wrong interpreter" in text
