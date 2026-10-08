# Local Oncometra workspace. Dependencies live in .\.venv. Files under .\data.
$ErrorActionPreference = "Stop"
if (Test-Path variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}
Set-Location (Resolve-Path (Join-Path $PSScriptRoot ".."))

$venvPython = ".\.venv\Scripts\python.exe"
$savedPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$venvOk = $false
if (Test-Path $venvPython) {
    & $venvPython -c "import sys" *> $null
    $venvOk = $LASTEXITCODE -eq 0
}
$ErrorActionPreference = $savedPreference
if (-not $venvOk) {
    if (Test-Path ".\.venv") { Remove-Item -Recurse -Force ".\.venv" }
    $python = (Get-Command python -ErrorAction Stop).Source
    & $python -m venv .venv
}

$ErrorActionPreference = "Continue"
& $venvPython -c "import uvicorn, fastapi, SimpleITK" *> $null
$missingDeps = $LASTEXITCODE -ne 0
$ErrorActionPreference = $savedPreference
if ($missingDeps) {
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r requirements-demo.txt
}

New-Item -ItemType Directory -Force -Path ".\data" | Out-Null
$env:APP_STORAGE_ROOT = (Resolve-Path ".\data").Path
$env:DEMO_EPHEMERAL = "false"
if (-not $env:CATALOG_WORKER_MODE) { $env:CATALOG_WORKER_MODE = "inline" }
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue

& $venvPython -m app.oncometra
