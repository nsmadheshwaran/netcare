<#
 Backs up the NetCare database and uploaded documents (Windows + Docker Desktop).
 Writes backups\netcare-YYYYMMDD-HHMMSS.sql.gz and backups\netcare-YYYYMMDD-HHMMSS-files.tar.gz
 Keeps the newest 30 backups. Usage:  powershell -ExecutionPolicy Bypass -File .\scripts\backup.ps1
#>
param([int]$Keep = 30)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    foreach ($p in @("$env:ProgramFiles\Docker\Docker\resources\bin", "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin")) {
        if (Test-Path "$p\docker.exe") { $env:Path += ";$p"; break }
    }
}

function Fail($msg) { Write-Host "BACKUP FAILED: $msg" -ForegroundColor Red; exit 1 }
function Test-Gzip([string]$path) {
    try {
        $fs = [IO.File]::OpenRead($path)
        $gz = New-Object IO.Compression.GZipStream($fs, [IO.Compression.CompressionMode]::Decompress)
        $buf = New-Object byte[] 65536
        $total = 0
        while (($n = $gz.Read($buf, 0, $buf.Length)) -gt 0) { $total += $n }
        $gz.Dispose(); $fs.Dispose()
        return $total -gt 0
    } catch { return $false }
}

$backups = Join-Path $root "backups"
New-Item -ItemType Directory -Force -Path $backups | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$sql = Join-Path $backups "netcare-$stamp.sql.gz"
$files = Join-Path $backups "netcare-$stamp-files.tar.gz"

# The dump runs inside the containers (so binary data never passes through the PowerShell pipeline), then is copied out.
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists > /tmp/nc.sql && gzip -f /tmp/nc.sql'
if ($LASTEXITCODE -ne 0) { Fail "could not dump the database. Is NetCare running (docker compose ps)?" }
docker compose cp db:/tmp/nc.sql.gz $sql
if ($LASTEXITCODE -ne 0) { Fail "could not copy the database dump out of the container." }
docker compose exec -T db rm -f /tmp/nc.sql.gz

docker compose exec -T backend sh -c 'tar -C /app/storage -czf /tmp/nc-files.tar.gz .'
if ($LASTEXITCODE -ne 0) { Fail "could not archive uploaded documents." }
docker compose cp backend:/tmp/nc-files.tar.gz $files
if ($LASTEXITCODE -ne 0) { Fail "could not copy the documents archive out of the container." }
docker compose exec -T backend rm -f /tmp/nc-files.tar.gz

if (-not (Test-Gzip $sql)) { Fail "the database backup file is empty or damaged: $sql" }
if (-not (Test-Gzip $files)) { Write-Host "Note: the documents archive is empty (no documents uploaded yet)." }

Get-ChildItem $backups -Filter "netcare-*.sql.gz" | Sort-Object Name -Descending | Select-Object -Skip $Keep | ForEach-Object {
    Remove-Item $_.FullName -Force
    $pair = $_.FullName -replace "\.sql\.gz$", "-files.tar.gz"
    if (Test-Path $pair) { Remove-Item $pair -Force }
}
Write-Host ("Backup OK: {0} ({1:N0} KB) and {2}" -f $sql, ((Get-Item $sql).Length / 1KB), $files) -ForegroundColor Green
