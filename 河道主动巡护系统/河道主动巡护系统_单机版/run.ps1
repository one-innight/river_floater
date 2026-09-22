$ErrorActionPreference = "Stop"
$environmentName = "river-patrol"
$condaExecutable = (Get-Command conda.exe -ErrorAction SilentlyContinue).Source

if (-not $condaExecutable) { throw "Conda executable was not found. Run this script from Miniconda Prompt." }
if (-not (Test-Path "river_litter_mvp.db")) { Write-Host "The litter MVP SQLite database will be created on first startup." -ForegroundColor Cyan }

& $condaExecutable run --no-capture-output --name $environmentName python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
if ($LASTEXITCODE -ne 0) { throw "Startup failed. Run ./setup_conda_env.ps1 first." }
