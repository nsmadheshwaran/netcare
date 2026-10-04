<#
 NetCare installer for a Windows PC or server that has Docker Desktop.
 Run from the project folder:  powershell -ExecutionPolicy Bypass -File .\install\install.ps1
   -Port 8080     port to open the app on
   -AllowLan      let other PCs on the shop network open the app (needs Administrator for the firewall rule)
   -NoBackupTask  do not create the daily backup task
   -NoBrowser     do not open the browser at the end
#>
param(
    [int]$Port = 8080,
    [switch]$AllowLan,
    [switch]$NoBackupTask,
    [switch]$NoBrowser
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    foreach ($p in @("$env:ProgramFiles\Docker\Docker\resources\bin", "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin")) {
        if (Test-Path "$p\docker.exe") { $env:Path += ";$p"; break }
    }
}

function Fail($msg) { Write-Host ""; Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }
function Step($msg) { Write-Host ""; Write-Host "== $msg" -ForegroundColor Cyan }
function New-Secret([int]$bytes) {
    $b = New-Object byte[] $bytes
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($b); $rng.Dispose()
    return ([Convert]::ToBase64String($b)).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}
function Set-EnvLine([string]$text, [string]$key, [string]$value) {
    $pattern = "(?m)^$([regex]::Escape($key))=.*$"
    if ([regex]::IsMatch($text, $pattern)) { return [regex]::Replace($text, $pattern, "$key=$value") }
    return $text.TrimEnd() + "`n$key=$value`n"
}

if ($Port -lt 1 -or $Port -gt 65535) { Fail "Port must be between 1 and 65535." }

Step "Checking Docker"
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail "Docker is not installed or not on PATH. Install Docker Desktop from docker.com, start it, then run this again."
}
cmd /c "docker info >nul 2>&1"
if ($LASTEXITCODE -ne 0) { Fail "Docker is installed but not running. Open Docker Desktop, wait until it says it is running, then run this again." }
cmd /c "docker compose version >nul 2>&1"
if ($LASTEXITCODE -ne 0) { Fail "'docker compose' is not available. Update Docker Desktop." }

Step "Preparing settings (.env)"
$envPath = Join-Path $root ".env"
if (Test-Path $envPath) {
    Write-Host "A .env file already exists, so it is kept as it is (your passwords are not changed)."
    $existing = Get-Content $envPath -Raw
    $m = [regex]::Match($existing, "(?m)^NETCARE_PORT=(\d+)\s*$")
    if ($m.Success) { $Port = [int]$m.Groups[1].Value }
} else {
    # A new .env means a new database password; it cannot open a database created with the old one.
    $project = ($env:COMPOSE_PROJECT_NAME, (Split-Path -Leaf $root) | Where-Object { $_ } | Select-Object -First 1).ToLower() -replace '[^a-z0-9_-]', ''
    $volumes = @(cmd /c "docker volume ls -q")
    if ($volumes -contains "${project}_pgdata") {
        Fail ("NetCare data from an earlier install exists on this PC, but the .env file with its password is missing. " +
              "Restore your original .env file here and run this again. To throw the old data away and start empty, run 'docker compose down -v' first.")
    }
    $text = (Get-Content (Join-Path $root ".env.example") -Raw).Replace("`r`n", "`n")
    $hostName = $env:COMPUTERNAME.ToLower()
    $origins = "http://localhost:$Port"
    $bind = "127.0.0.1"
    if ($AllowLan) { $origins = "http://localhost:$Port,http://${hostName}:$Port"; $bind = "0.0.0.0" }
    $text = Set-EnvLine $text "POSTGRES_PASSWORD" (New-Secret 32)
    $text = Set-EnvLine $text "NETCARE_SECRET_KEY" (New-Secret 48)
    $text = Set-EnvLine $text "NETCARE_CORS_ORIGINS" $origins
    $text = Set-EnvLine $text "NETCARE_APP_URL" ($origins.Split(',')[-1])
    $text = Set-EnvLine $text "NETCARE_PORT" "$Port"
    $text = Set-EnvLine $text "NETCARE_BIND" $bind
    [IO.File]::WriteAllText($envPath, $text, (New-Object Text.UTF8Encoding $false))
    Write-Host "Created .env with new random passwords. Keep this file safe and private."
}

Step "Building and starting NetCare (the first time this takes several minutes)"
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { Fail "docker compose could not start NetCare. Run 'docker compose logs' to see why." }

Step "Waiting for NetCare to be ready"
$ready = $false
for ($i = 0; $i -lt 90; $i++) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/ready" -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    Start-Sleep -Seconds 2
}
if (-not $ready) { Fail "NetCare did not become ready in 3 minutes. Run 'docker compose logs backend' to see why." }
Write-Host "NetCare is running." -ForegroundColor Green

if ($AllowLan) {
    Step "Opening the port for other PCs on this network"
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        Write-Host "Not running as Administrator, so the firewall rule was not added. Re-run this PowerShell as Administrator with -AllowLan." -ForegroundColor Yellow
    } else {
        $rule = "NetCare (port $Port)"
        if (-not (Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue)) {
            New-NetFirewallRule -DisplayName $rule -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Private | Out-Null
        }
        Write-Host "Other PCs on a Private network can open http://$($env:COMPUTERNAME.ToLower()):$Port"
    }
}

if (-not $NoBackupTask) {
    Step "Scheduling a daily backup at 2:00 AM"
    $taskName = "NetCare Daily Backup"
    $backup = Join-Path $root "scripts\backup.ps1"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$backup`"" -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -Daily -At 2:00AM
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Host "Task '$taskName' created. Backups go to $(Join-Path $root 'backups'). Copy that folder to another disk or cloud drive regularly."
}

Write-Host ""
Write-Host "Done. Open http://localhost:$Port and create the owner account (Create an account)." -ForegroundColor Green
if (-not $NoBrowser) { Start-Process "http://localhost:$Port" }
