$ErrorActionPreference = "Stop"
$environmentName = "river-patrol"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$condaExecutable = (Get-Command conda.exe -ErrorAction SilentlyContinue).Source

if (-not $condaExecutable) {
    throw "Conda executable was not found. Run this script from Miniconda Prompt."
}

Push-Location $projectRoot
try {
    $environmentList = (& $condaExecutable env list --json | ConvertFrom-Json).envs
    $environmentExists = @($environmentList | Where-Object { [IO.Path]::GetFileName($_) -eq $environmentName }).Count -gt 0
    if ($environmentExists) {
        Write-Host "Updating Conda environment: $environmentName" -ForegroundColor Cyan
        & $condaExecutable env update --name $environmentName --file environment.yml
    }
    else {
        Write-Host "Creating Conda environment: $environmentName" -ForegroundColor Cyan
        & $condaExecutable env create --file environment.yml
    }
    if ($LASTEXITCODE -ne 0) { throw "Conda environment creation or update failed." }

    Write-Host "Installing CPU PyTorch and project dependencies..." -ForegroundColor Cyan
    & $condaExecutable run --no-capture-output --name $environmentName python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
    if ($LASTEXITCODE -ne 0) { throw "PyTorch installation failed." }
    & $condaExecutable run --no-capture-output --name $environmentName python -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw "Project dependency installation failed." }

    Write-Host "Verifying model runtime..." -ForegroundColor Cyan
    & $condaExecutable run --no-capture-output --name $environmentName python -c "import torch; from ultralytics import YOLO; print('Python environment ready | torch=' + torch.__version__); YOLO('weights/river_floater.pt'); print('river_floater.pt loaded')"
    if ($LASTEXITCODE -ne 0) { throw "Model verification failed." }
    Write-Host "Done. Start the system with ./run.ps1" -ForegroundColor Green
}
finally {
    Pop-Location
}
