# Quick Start Guide - Windows

## Getting Started on Windows in 5 Minutes

This guide is specifically for Windows users running PowerShell or Command Prompt.

## Prerequisites Check

Open PowerShell and check:

```powershell
# Check Python version (need 3.9+)
python --version

# Check pip
pip --version
```

If Python is not installed, download from: https://www.python.org/downloads/

⚠️ **Important**: When installing Python, check "Add Python to PATH"

## Automated Setup (Recommended)

### Option 1: Run Setup Script

1. **Open PowerShell** in the project directory
2. **Run the setup script**:

```powershell
.\setup.ps1
```

This will automatically:
- ✅ Check Python version
- ✅ Create virtual environment
- ✅ Set execution policy if needed
- ✅ Install all dependencies
- ✅ Verify installation

If you get an execution policy error, run this first:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then run `.\setup.ps1` again.

## Manual Setup

If you prefer to set up manually:

### Step 1: Clone the Repository

```powershell
git clone https://github.com/ADEData-Lab/HeatStreet.git
cd HeatStreet
```

### Step 2: Create Virtual Environment

```powershell
python -m venv venv
```

### Step 3: Activate Virtual Environment

**In PowerShell**:
```powershell
.\venv\Scripts\Activate.ps1
```

**In Command Prompt (cmd)**:
```cmd
venv\Scripts\activate.bat
```

You should see `(venv)` appear at the start of your prompt.

### Step 4: Install Dependencies

```powershell
pip install -r requirements.txt
```

This may take 2-5 minutes.

### Step 5: Verify Installation

```powershell
python -c "from config.config import load_config; print('✅ Installation successful!')"
```

## Getting EPC Data

### Download Instructions

```powershell
python main.py --phase acquire --download
```

This creates a file: `data\raw\DOWNLOAD_INSTRUCTIONS.txt`

### Where to Get Data

1. **Visit**: https://epc.opendatacommunities.org/
2. **Register** for an account (free)
3. **Download** bulk EPC data for London boroughs
4. **Save** CSV files to: `data\raw\`
5. **Name** files as: `epc_*.csv` (e.g., `epc_camden.csv`)

## Running Your First Analysis

### Full Pipeline

Once you have data in `data\raw\`:

```powershell
python main.py --phase all
```

This runs all phases (may take 10-30 minutes depending on data size).

### Individual Phases

Run phases separately:

```powershell
# Clean and validate data
python main.py --phase clean

# Analyze property characteristics
python main.py --phase analyze

# Model scenarios
python main.py --phase model

# Spatial analysis
python main.py --phase spatial

# Generate reports
python main.py --phase report
```

## Viewing Results

### Open Output Folder

```powershell
# Open data folder in Explorer
explorer data\outputs

# Open figures folder
explorer data\outputs\figures

# Open maps folder
explorer data\outputs\maps
```

### View Text Reports

```powershell
# View archetype analysis
type data\outputs\archetype_analysis_results.txt

# View scenario results
type data\outputs\scenario_modeling_results.txt

# View executive summary
type data\outputs\reports\executive_summary.txt
```

### Open Interactive Map

```powershell
# Open heat network map in default browser
start data\outputs\maps\heat_network_tiers.html
```

## Common Windows Issues

### Issue 1: "python is not recognized"

**Solution**: Add Python to PATH
1. Search for "Environment Variables" in Windows
2. Click "Environment Variables"
3. Under "User variables", find "Path"
4. Add Python installation directory (e.g., `C:\Users\YourName\AppData\Local\Programs\Python\Python311`)

Or reinstall Python and check "Add Python to PATH"

### Issue 2: "cannot be loaded because running scripts is disabled"

**Solution**: Update execution policy
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Issue 3: "pip is not recognized"

**Solution**: Use python -m pip instead
```powershell
python -m pip install -r requirements.txt
```

### Issue 4: Virtual environment won't activate

**Solution A**: Try with full path
```powershell
& "$PWD\venv\Scripts\Activate.ps1"
```

**Solution B**: Use Command Prompt instead
```cmd
venv\Scripts\activate.bat
```

### Issue 5: Module import errors

**Solution**: Make sure virtual environment is activated
```powershell
# You should see (venv) in your prompt
# If not, activate it:
.\venv\Scripts\Activate.ps1

# Then reinstall:
pip install -r requirements.txt
```

## PowerShell Tips

### Useful Aliases

```powershell
# Navigate up one directory
cd ..

# List files
dir
# or
ls

# Clear screen
cls
# or
clear

# View file contents
type filename.txt
# or
cat filename.txt
```

### Running Python Scripts

```powershell
# Run a specific module
python src\acquisition\epc_downloader.py

# Run with arguments
python main.py --phase clean --log-file mylog.log
```

### Copy Commands Easily

Right-click in PowerShell to paste commands from this guide.

## Configuration

Edit configuration in Notepad or your favorite editor:

```powershell
# Open config in Notepad
notepad config\config.yaml

# Or use VS Code if installed
code config\config.yaml
```

## PowerShell vs Command Prompt

| Task | PowerShell | Command Prompt |
|------|------------|----------------|
| **Activate venv** | `.\venv\Scripts\Activate.ps1` | `venv\Scripts\activate.bat` |
| **List files** | `dir` or `ls` | `dir` |
| **View file** | `type` or `cat` | `type` |
| **Clear screen** | `cls` or `clear` | `cls` |
| **Run Python** | `python script.py` | `python script.py` |

Both work fine - use whichever you prefer!

## Deactivating Virtual Environment

When you're done:

```powershell
deactivate
```

This returns you to your normal Python environment.

## Complete Example Session

Here's a complete example of a first-time setup and run:

```powershell
# 1. Clone and setup
git clone https://github.com/ADEData-Lab/HeatStreet.git
cd HeatStreet
.\setup.ps1

# 2. Get download instructions
python main.py --phase acquire --download

# 3. (After downloading EPC data to data\raw\)

# 4. Run analysis
python main.py --phase all

# 5. View results
explorer data\outputs

# 6. When done
deactivate
```

## Next Steps

1. ✅ **Setup complete** - You're ready to go!
2. 📥 **Download data** - Get EPC data from government portal
3. 🔧 **Customize** - Edit `config\config.yaml` for your needs
4. 🚀 **Run analysis** - Process your data
5. 📊 **Review results** - Check outputs and visualizations

## Getting Help

- 📖 **Full documentation**: `README.md`
- 🔧 **Configuration guide**: `config\config.yaml`
- 🐛 **Report issues**: https://github.com/ADEData-Lab/HeatStreet/issues

## Success Checklist

- [ ] Python 3.9+ installed with PATH set
- [ ] Repository cloned
- [ ] Virtual environment created and activated
- [ ] Dependencies installed
- [ ] Installation verified
- [ ] Download instructions generated
- [ ] EPC data obtained and placed in `data\raw\`
- [ ] First analysis run successful
- [ ] Results viewed in `data\outputs\`

---

**You're all set for Windows!** 🪟🚀

Need help? Check the main README.md or open an issue on GitHub.
