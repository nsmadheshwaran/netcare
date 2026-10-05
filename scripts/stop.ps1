<#
 Stops NetCare (containers only; your data stays on disk). Start it again with scripts\start.ps1.
 Usage:  powershell -ExecutionPolicy Bypass -File .\scripts\stop.ps1
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    foreach ($p in @("$env:ProgramFiles\Docker\Docker\resources\bin", "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin")) {
        if (Test-Path "$p\docker.exe") { $env:Path += ";$p"; break }
    }
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker is not installed, so NetCare cannot be running." -ForegroundColor Yellow; exit 0
}
cmd /c "docker info >nul 2>&1"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker Desktop is not running, so NetCare is already stopped." -ForegroundColor Yellow; exit 0
}
docker compose stop
if ($LASTEXITCODE -ne 0) { Write-Host "Could not stop NetCare." -ForegroundColor Red; exit 1 }
Write-Host "NetCare is stopped. Your data is kept; run Start NetCare to open it again." -ForegroundColor Green
