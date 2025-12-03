# Heat Street EPC Analysis - View Results Script
# Quick script to open and view analysis results

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Heat Street EPC Analysis - Results Viewer" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Define result locations
$resultsPath = "data\outputs"
$figuresPath = "$resultsPath\figures"
$reportsPath = "$resultsPath\reports"
$mapsPath = "$resultsPath\maps"

# Check if results exist
if (-not (Test-Path $resultsPath)) {
    Write-Host "✗ No results found" -ForegroundColor Red
    Write-Host "Please run the analysis first:" -ForegroundColor Yellow
    Write-Host "  .\run-analysis.ps1" -ForegroundColor Gray
    exit 1
}

# Show menu
Write-Host "Available results:" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. Open outputs folder" -ForegroundColor White
Write-Host "2. View figures (charts)" -ForegroundColor White
Write-Host "3. View reports (text)" -ForegroundColor White
Write-Host "4. View interactive map" -ForegroundColor White
Write-Host "5. View executive summary" -ForegroundColor White
Write-Host "6. View archetype analysis" -ForegroundColor White
Write-Host "7. View scenario results" -ForegroundColor White
Write-Host "8. Exit" -ForegroundColor White
Write-Host ""

$choice = Read-Host "Select option (1-8)"

switch ($choice) {
    "1" {
        Write-Host "Opening outputs folder..." -ForegroundColor Yellow
        if (Test-Path $resultsPath) {
            explorer $resultsPath
        } else {
            Write-Host "✗ Outputs folder not found" -ForegroundColor Red
        }
    }
    "2" {
        Write-Host "Opening figures folder..." -ForegroundColor Yellow
        if (Test-Path $figuresPath) {
            explorer $figuresPath
        } else {
            Write-Host "✗ Figures folder not found" -ForegroundColor Red
        }
    }
    "3" {
        Write-Host "Opening reports folder..." -ForegroundColor Yellow
        if (Test-Path $reportsPath) {
            explorer $reportsPath
        } else {
            Write-Host "✗ Reports folder not found" -ForegroundColor Red
        }
    }
    "4" {
        Write-Host "Opening interactive map..." -ForegroundColor Yellow
        $mapFile = "$mapsPath\heat_network_tiers.html"
        if (Test-Path $mapFile) {
            start $mapFile
        } else {
            Write-Host "✗ Map file not found" -ForegroundColor Red
            Write-Host "Run spatial analysis phase to generate map:" -ForegroundColor Yellow
            Write-Host "  python main.py --phase spatial" -ForegroundColor Gray
        }
    }
    "5" {
        Write-Host "Displaying executive summary..." -ForegroundColor Yellow
        Write-Host ""
        $summaryFile = "$reportsPath\executive_summary.txt"
        if (Test-Path $summaryFile) {
            Get-Content $summaryFile
        } else {
            Write-Host "✗ Executive summary not found" -ForegroundColor Red
            Write-Host "Run report phase to generate summary:" -ForegroundColor Yellow
            Write-Host "  python main.py --phase report" -ForegroundColor Gray
        }
    }
    "6" {
        Write-Host "Displaying archetype analysis..." -ForegroundColor Yellow
        Write-Host ""
        $archetypeFile = "$resultsPath\archetype_analysis_results.txt"
        if (Test-Path $archetypeFile) {
            Get-Content $archetypeFile
        } else {
            Write-Host "✗ Archetype analysis not found" -ForegroundColor Red
            Write-Host "Run analyze phase:" -ForegroundColor Yellow
            Write-Host "  python main.py --phase analyze" -ForegroundColor Gray
        }
    }
    "7" {
        Write-Host "Displaying scenario results..." -ForegroundColor Yellow
        Write-Host ""
        $scenarioFile = "$resultsPath\scenario_modeling_results.txt"
        if (Test-Path $scenarioFile) {
            Get-Content $scenarioFile
        } else {
            Write-Host "✗ Scenario results not found" -ForegroundColor Red
            Write-Host "Run model phase:" -ForegroundColor Yellow
            Write-Host "  python main.py --phase model" -ForegroundColor Gray
        }
    }
    "8" {
        Write-Host "Goodbye!" -ForegroundColor Green
        exit 0
    }
    default {
        Write-Host "Invalid choice" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "Done!" -ForegroundColor Green
