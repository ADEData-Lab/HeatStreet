@echo off
REM Heat Street EPC Analysis - Quick Launcher
REM Single command to run complete analysis

echo ========================================
echo Heat Street EPC Analysis
echo ========================================
echo.

REM Check if virtual environment exists
if not exist "venv" (
    echo [!] Virtual environment not found. Running setup...
    echo.
    call setup.bat
    if errorlevel 1 (
        echo [X] Setup failed. Please run setup.bat manually.
        pause
        exit /b 1
    )
)

REM Activate virtual environment
echo [OK] Activating virtual environment...
call venv\Scripts\activate.bat

REM Check if dependencies are installed
echo [OK] Checking dependencies...
python -c "import questionary; import rich; print('OK')" >nul 2>&1

if errorlevel 1 (
    echo [!] Installing missing dependencies...
    pip install questionary rich --quiet
)

REM Run the interactive analysis
echo [OK] Starting interactive analysis...
echo.

python run_analysis.py

if %errorlevel% equ 0 (
    echo.
    echo [OK] Analysis complete!
) else (
    echo.
    echo [X] Analysis failed. Check errors above.
)

pause
