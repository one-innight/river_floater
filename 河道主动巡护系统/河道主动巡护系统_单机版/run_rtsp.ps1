$ErrorActionPreference = "Stop"
$environmentName = "river-patrol"
$condaExecutable = (Get-Command conda.exe -ErrorAction SilentlyContinue).Source

if (-not $condaExecutable) { throw "Conda executable was not found. Run this script from Miniconda Prompt." }
if (-not $env:RIVER_CAMERA_SOURCE) { throw "Set RIVER_CAMERA_SOURCE to the RTSP URL before starting." }
if (-not $env:RIVER_CAMERA_INTERVAL) { $env:RIVER_CAMERA_INTERVAL = "8" }
$env:RIVER_CAMERA_AUTOSTART = "true"

& $condaExecutable run --no-capture-output --name $environmentName python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
if ($LASTEXITCODE -ne 0) { throw "RTSP service startup failed." }
