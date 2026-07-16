# Heat Street EPC Analysis - Conda Launcher (PowerShell)
# Requires a clean, activated Conda environment built from environment.yml.

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$environmentFile = Join-Path $repoRoot "environment.yml"
$requirementsFile = Join-Path $repoRoot "requirements.txt"
$supportedPythonVersions = @("3.11", "3.12")
$spatialPackages = @("geopandas", "fiona", "gdal", "pyproj", "shapely", "rtree", "pyogrio", "folium")

function Write-Section {
    param(
        [string]$Message,
        [ConsoleColor]$Color = [ConsoleColor]::Cyan
    )

    Write-Host $Message -ForegroundColor $Color
}

function Write-CommandBlock {
    param([string[]]$Commands)

    foreach ($command in $Commands) {
        Write-Host "  $command" -ForegroundColor White
    }
}

function Fail-WithGuidance {
    param(
        [string]$Message,
        [string[]]$Details = @()
    )

    Write-Host "[X] $Message" -ForegroundColor Red
    if ($Details.Count -gt 0) {
        Write-Host ""
        foreach ($detail in $Details) {
            Write-Host "  - $detail" -ForegroundColor Yellow
        }
    }

    Write-Host ""
    Write-Host "Diagnosis commands:" -ForegroundColor Cyan
    Write-CommandBlock @(
        "where python",
        "where pip",
        "conda info",
        'conda list | findstr /i "python geopandas fiona gdal shapely"'
    )
    exit 1
}

function Get-FirstWhereResult {
    param([string]$Name)

    $results = @(where.exe $Name 2>$null)
    if ($LASTEXITCODE -ne 0 -or $results.Count -eq 0) {
        return $null
    }

    return $results[0].Trim()
}

function Get-WhereResults {
    param([string]$Name)

    $results = @(where.exe $Name 2>$null)
    if ($LASTEXITCODE -ne 0) {
        return @()
    }

    return @($results | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}

function Test-PathWithinPrefix {
    param(
        [string]$Candidate,
        [string]$Prefix
    )

    if ([string]::IsNullOrWhiteSpace($Candidate) -or [string]::IsNullOrWhiteSpace($Prefix)) {
        return $false
    }

    return $Candidate.TrimEnd('\').ToLowerInvariant().StartsWith($Prefix.TrimEnd('\').ToLowerInvariant())
}

Write-Section "========================================"
Write-Section "Heat Street EPC Analysis (Conda)"
Write-Section "========================================"
Write-Host ""

if (-not (Test-Path $environmentFile)) {
    Fail-WithGuidance "environment.yml is missing from the repo root." @(
        "The Windows spatial workflow depends on environment.yml as the canonical setup artifact."
    )
}

if (-not (Test-Path $requirementsFile)) {
    Fail-WithGuidance "requirements.txt is missing from the repo root."
}

$condaCommand = Get-Command conda -ErrorAction SilentlyContinue
if (-not $condaCommand) {
    Fail-WithGuidance "Conda was not found on PATH." @(
        "Install Miniconda or Anaconda first: https://docs.conda.io/en/latest/miniconda.html",
        "Then create the HeatStreet environment with: conda env create -f environment.yml"
    )
}

Write-Host "[OK] Conda found" -ForegroundColor Green
Write-Host ""

if (-not $env:CONDA_DEFAULT_ENV -or $env:CONDA_DEFAULT_ENV -eq "base" -or -not $env:CONDA_PREFIX) {
    Fail-WithGuidance "Activate a dedicated Conda environment before running this launcher." @(
        "Create the canonical environment with: conda env create -f environment.yml",
        "Or update it with: conda env update -n heatstreet -f environment.yml --prune",
        "Then activate it with: conda activate heatstreet",
        "The supported Windows spatial stack is Python 3.11 or 3.12 from conda-forge."
    )
}

$targetEnv = $env:CONDA_DEFAULT_ENV
$condaPrefix = try {
    (Resolve-Path $env:CONDA_PREFIX).Path
} catch {
    $env:CONDA_PREFIX
}

$condaInfoRaw = conda info --json
if ($LASTEXITCODE -ne 0) {
    Fail-WithGuidance "conda info failed, so the active environment could not be verified."
}

$condaInfo = $condaInfoRaw | ConvertFrom-Json
$activePrefixName = $condaInfo.active_prefix_name
$activePrefixPath = if ($condaInfo.active_prefix) {
    try {
        (Resolve-Path $condaInfo.active_prefix).Path
    } catch {
        $condaInfo.active_prefix
    }
} else {
    ""
}

if ($activePrefixName -ne $targetEnv -or -not (Test-PathWithinPrefix $activePrefixPath $condaPrefix)) {
    Fail-WithGuidance "conda reports a different active environment than the current shell." @(
        "CONDA_DEFAULT_ENV = $targetEnv",
        "CONDA_PREFIX = $condaPrefix",
        "conda info active_prefix_name = $activePrefixName",
        "conda info active_prefix = $activePrefixPath"
    )
}

$pythonPath = Get-FirstWhereResult "python"
$pipPath = Get-FirstWhereResult "pip"

if (-not $pythonPath -or -not $pipPath) {
    Fail-WithGuidance "python and pip must both resolve on PATH inside the active Conda environment."
}

if (-not (Test-PathWithinPrefix $pythonPath $condaPrefix)) {
    Fail-WithGuidance "python does not resolve inside the active Conda environment." @(
        "python path = $pythonPath",
        "expected prefix = $condaPrefix"
    )
}

if (-not (Test-PathWithinPrefix $pipPath $condaPrefix)) {
    Fail-WithGuidance "pip does not resolve inside the active Conda environment." @(
        "pip path = $pipPath",
        "expected prefix = $condaPrefix"
    )
}

$pythonInfo = @(python -c "import sys; print(sys.executable); print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>$null)
if ($LASTEXITCODE -ne 0 -or $pythonInfo.Count -lt 2) {
    Fail-WithGuidance "Unable to inspect the active python interpreter."
}

$condaPythonInfo = @(conda run -n $targetEnv python -c "import sys; print(sys.executable); print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>$null)
if ($LASTEXITCODE -ne 0 -or $condaPythonInfo.Count -lt 2) {
    Fail-WithGuidance "Unable to inspect the Conda environment interpreter via 'conda run'."
}

$pythonExecutable = $pythonInfo[0].Trim()
$pythonVersion = $pythonInfo[1].Trim()
$condaPythonExecutable = $condaPythonInfo[0].Trim()
$condaPythonVersion = $condaPythonInfo[1].Trim()

if (-not (Test-PathWithinPrefix $pythonExecutable $condaPrefix)) {
    Fail-WithGuidance "python is running outside the active Conda environment." @(
        "python executable = $pythonExecutable",
        "expected prefix = $condaPrefix"
    )
}

if ($pythonExecutable -ne $condaPythonExecutable -or $pythonVersion -ne $condaPythonVersion) {
    Fail-WithGuidance "python --version does not match the active Conda environment interpreter." @(
        "python executable = $pythonExecutable",
        "conda run executable = $condaPythonExecutable",
        "python version = $pythonVersion",
        "conda run version = $condaPythonVersion"
    )
}

if ($supportedPythonVersions -notcontains $pythonVersion) {
    Fail-WithGuidance "Unsupported Python version for the Windows spatial workflow: $pythonVersion" @(
        "Use Python 3.11 or 3.12 in a fresh Conda environment built from environment.yml.",
        "Python 3.13 and 3.14 are not a supported default for Windows spatial installs in this repo."
    )
}

$pythonPathMatches = Get-WhereResults "python"
$pipPathMatches = Get-WhereResults "pip"
$contaminationPaths = @(
    $pythonPathMatches + $pipPathMatches |
    Where-Object {
        $_.ToLowerInvariant().Contains("appdata\roaming\python")
    }
) | Select-Object -Unique

if ($contaminationPaths.Count -gt 0) {
    Write-Host "[!] User-site Python executables were also found on PATH." -ForegroundColor Yellow
    Write-Host "    The active environment is usable, but this shell is not perfectly clean:" -ForegroundColor Yellow
    foreach ($contaminationPath in $contaminationPaths) {
        Write-Host "      $contaminationPath" -ForegroundColor Yellow
    }
    Write-Host ""
}

Write-Host "[OK] Using active Conda environment '$targetEnv'" -ForegroundColor Green
Write-Host "[OK] Python $pythonVersion resolves inside $condaPrefix" -ForegroundColor Green
Write-Host "[OK] python executable = $pythonExecutable" -ForegroundColor Green
Write-Host "[OK] pip executable = $pipPath" -ForegroundColor Green
Write-Host "[OK] Canonical Windows launch path = .\run-conda.ps1 (or run-conda.bat)" -ForegroundColor Green
Write-Host ""

Push-Location $repoRoot
try {
    python -c "import geopandas, fiona, pyogrio, pyproj, shapely, folium; from osgeo import gdal" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[!] Installing spatial dependencies from conda-forge..." -ForegroundColor Yellow
        Write-Host "    This is the only supported automatic install path on Windows." -ForegroundColor Yellow
        Write-Host ""

        conda install -n $targetEnv -c conda-forge $spatialPackages -y
        if ($LASTEXITCODE -ne 0) {
            Fail-WithGuidance "Failed to install the Conda spatial stack." @(
                "Rebuild the environment with: conda env update -n $targetEnv -f environment.yml --prune"
            )
        }

        Write-Host ""
        Write-Host "[OK] Spatial dependencies installed from conda-forge" -ForegroundColor Green
        Write-Host ""
    } else {
        Write-Host "[OK] Spatial dependencies already import successfully" -ForegroundColor Green
        Write-Host ""
    }

    Write-Host "[OK] Installing/updating core Python dependencies..." -ForegroundColor Green
    Write-Host ""

    python -m pip install --upgrade pip --quiet
    python -m pip install -r requirements.txt --quiet

    if ($LASTEXITCODE -ne 0) {
        Write-Host "[!] Quiet install failed. Retrying with full output..." -ForegroundColor Yellow
        python -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) {
            Fail-WithGuidance "requirements.txt installation failed."
        }
    }

    Write-Host ""
    Write-Host "[OK] Verifying spatial analysis imports..." -ForegroundColor Green
    python -c "import geopandas, fiona, pyogrio, pyproj, shapely, folium; from osgeo import gdal; print('[OK] Geopandas version:', geopandas.__version__); print('[OK] Fiona version:', fiona.__version__); print('[OK] GDAL version:', gdal.VersionInfo('RELEASE_NAME'))"
    if ($LASTEXITCODE -ne 0) {
        Fail-WithGuidance "Spatial verification failed after installation."
    }

    Write-Host ""
    Write-Section "========================================"
    Write-Section "Starting Interactive Analysis"
    Write-Section "========================================"
    Write-Host ""

    python run_analysis.py @args
    $analysisExitCode = $LASTEXITCODE

    if ($analysisExitCode -eq 0) {
        Write-Host ""
        Write-Host "[OK] Analysis complete" -ForegroundColor Green
        Write-Host "    Check data\outputs\ for reports, figures, maps, and GeoJSON exports." -ForegroundColor Cyan
    } else {
        Write-Host ""
        Write-Host "[X] Analysis failed." -ForegroundColor Red

        $checkpoint = Get-ChildItem -Path (Join-Path $repoRoot "data") -Filter "analysis_checkpoint.json" -Recurse -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -First 1

        if ($null -ne $checkpoint) {
            try {
                $failure = Get-Content -LiteralPath $checkpoint.FullName -Raw | ConvertFrom-Json
                if ($failure.failed_phase) {
                    Write-Host "    Failed phase: $($failure.failed_phase)" -ForegroundColor Red
                }
                if ($failure.exception_message) {
                    Write-Host "    Error: $($failure.exception_message)" -ForegroundColor Red
                }
                Write-Host "    Checkpoint: $($checkpoint.FullName)" -ForegroundColor Cyan

                $logPath = Join-Path $checkpoint.DirectoryName "analysis_log.txt"
                if (Test-Path -LiteralPath $logPath) {
                    Write-Host "    Log: $logPath" -ForegroundColor Cyan
                } else {
                    Write-Host "    Log directory: $($checkpoint.DirectoryName)" -ForegroundColor Cyan
                }
            } catch {
                Write-Host "    Could not read failure checkpoint: $($checkpoint.FullName)" -ForegroundColor Yellow
            }
        } else {
            Write-Host "    No analysis checkpoint was found under data\. Review the errors above." -ForegroundColor Yellow
        }
    }

    exit $analysisExitCode
} finally {
    Pop-Location
}
