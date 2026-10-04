<#
 Restores a NetCare backup (OVERWRITES the current database and documents).
 Usage:  powershell -ExecutionPolicy Bypass -File .\scripts\restore.ps1 -BackupFile .\backups\netcare-XXXX.sql.gz
 The matching -files.tar.gz next to it is restored too. Add -Yes to skip the confirmation question.
#>
param([Parameter(Mandatory = $true)][string]$BackupFile, [switch]$Yes)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    foreach ($p in @("$env:ProgramFiles\Docker\Docker\resources\bin", "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin")) {
        if (Test-Path "$p\docker.exe") { $env:Path += ";$p"; break }
    }
}

function Fail($msg) { Write-Host "RESTORE FAILED: $msg" -ForegroundColor Red; exit 1 }

if (-not (Test-Path $BackupFile)) { Fail "backup file not found: $BackupFile" }
$sql = (Resolve-Path $BackupFile).Path
if ($sql -notmatch "\.sql\.gz$") { Fail "give the .sql.gz file, not the -files.tar.gz one." }
$files = $sql -replace "\.sql\.gz$", "-files.tar.gz"

if (-not $Yes) {
    $answer = Read-Host "This will OVERWRITE the current NetCare database and documents. Type YES to continue"
    if ($answer -ne "YES") { Write-Host "Cancelled."; exit 1 }
}

docker compose stop backend
if ($LASTEXITCODE -ne 0) { Fail "could not stop the backend." }
docker compose cp $sql db:/tmp/nc-restore.sql.gz
if ($LASTEXITCODE -ne 0) { Fail "could not copy the backup into the database container." }
docker compose exec -T db sh -c 'gunzip -c /tmp/nc-restore.sql.gz | psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -q -o /dev/null'
$dbExit = $LASTEXITCODE
docker compose exec -T db rm -f /tmp/nc-restore.sql.gz
if ($dbExit -ne 0) { docker compose start backend; Fail "the database restore reported errors (see above). The backend was started again." }
Write-Host "Database restored."

if (Test-Path $files) {
    $dir = Split-Path -Parent $files
    $name = Split-Path -Leaf $files
    docker compose run --rm -T --no-deps -v "${dir}:/restore:ro" --entrypoint sh backend -c "rm -rf /app/storage/* && tar -C /app/storage -xzf /restore/$name"
    if ($LASTEXITCODE -ne 0) { docker compose start backend; Fail "could not restore the documents archive." }
    Write-Host "Documents restored from $name."
} else {
    Write-Host "No documents archive found next to the backup: database only."
}
docker compose start backend
if ($LASTEXITCODE -ne 0) { Fail "could not start the backend again." }
Write-Host "Restore finished. NetCare is starting again." -ForegroundColor Green
