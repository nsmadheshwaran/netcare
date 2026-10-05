<#
 Starts NetCare if it is stopped (containers only; it does not rebuild).
 Usage:  powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
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
    Write-Host "Docker is not installed. Install Docker Desktop from docker.com." -ForegroundColor Red; exit 1
}
cmd /c "docker info >nul 2>&1"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Starting Docker Desktop..."
    foreach ($p in @("$env:ProgramFiles\Docker\Docker\Docker Desktop.exe", "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe")) {
        if (Test-Path $p) { Start-Process $p; break }
    }
    $up = $false
    for ($i = 0; $i -lt 60; $i++) { cmd /c "docker info >nul 2>&1"; if ($LASTEXITCODE -eq 0) { $up = $true; break }; Start-Sleep 5 }
    if (-not $up) { Write-Host "Docker Desktop did not start in time. Open it by hand, wait until it says it is running, then try again." -ForegroundColor Red; exit 1 }
}

docker compose start
if ($LASTEXITCODE -ne 0) { Write-Host "Could not start NetCare. Run 'docker compose logs' to see why." -ForegroundColor Red; exit 1 }

$port = "8080"
if (Test-Path .env) {
    $m = [regex]::Match((Get-Content .env -Raw), "(?m)^NETCARE_PORT=(\d+)\s*$")
    if ($m.Success) { $port = $m.Groups[1].Value }
}
for ($i = 0; $i -lt 60; $i++) {
    try { if ((Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$port/ready" -TimeoutSec 3).StatusCode -eq 200) { break } } catch { }
    Start-Sleep 2
}
Write-Host "NetCare is running at http://localhost:$port" -ForegroundColor Green
Start-Process "http://localhost:$port"
