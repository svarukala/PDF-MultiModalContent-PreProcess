$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Create the Python environment first: py -3.12 -m venv .venv"
}
if (-not (Test-Path "local.settings.json")) {
    throw "Copy local.settings.json.example to local.settings.json first."
}

$env:VIRTUAL_ENV = Join-Path $PWD ".venv"
$env:PATH = (Join-Path $env:VIRTUAL_ENV "Scripts") + ";" + $env:PATH
& ".\node_modules\.bin\func.cmd" start --port 7071 @args
exit $LASTEXITCODE
