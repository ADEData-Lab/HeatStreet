@echo off
REM Heat Street EPC Analysis - Windows Batch Setup Script
REM For users who prefer Command Prompt over PowerShell

echo ========================================
echo Heat Street EPC Analysis - Setup
echo ========================================
echo.

REM Check Python
echo Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] Python not found
    echo     Please install Python 3.9+ from: https://www.python.org/downloads/
    pause
    exit /b 1
)

python --version
echo [OK] Python found
echo.

REM Create virtual environment
if exist "venv" (
    echo [OK] Virtual environment already exists
) else (
    echo Creating virtual environment...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [X] Failed to create virtual environment
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created
)
echo.

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo [X] Failed to activate virtual environment
    pause
    exit /b 1
)
echo [OK] Virtual environment activated
echo.

REM Upgrade pip
echo Upgrading pip...
python -m pip install --upgrade pip --quiet
echo [OK] pip upgraded
echo.

REM Install dependencies
echo Installing dependencies (this may take a few minutes)...
pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [X] Failed to install dependencies
    echo     Try running manually: pip install -r requirements.txt
    pause
    exit /b 1
)
echo [OK] Dependencies installed
echo.

REM Verify installation
echo Verifying installation...
python -c "from config.config import load_config; print('[OK] Installation verified')"
if %errorlevel% neq 0 (
    echo [X] Verification failed
    pause
    exit /b 1
)
echo.

REM Success
echo ========================================
echo [OK] Setup Complete!
echo ========================================
echo.
echo Next steps:
echo 1. Download EPC data:
echo    python main.py --phase acquire --download
echo.
echo 2. Place EPC CSV files in: data\raw\
echo.
echo 3. Run the analysis pipeline:
echo    python main.py --phase all
echo.
echo For help, see: docs\QUICKSTART_WINDOWS.md
echo.
pause
