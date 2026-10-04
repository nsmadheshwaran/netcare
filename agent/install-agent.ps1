<#
.SYNOPSIS
  Installs the NetCare monitoring agent on this Windows PC as a visible startup task.

.DESCRIPTION
  - Copies netcare_agent.py to C:\ProgramData\NetCare\Agent and writes agent.json there.
  - Restricts that folder to Administrators and SYSTEM (the token is a password for this agent).
  - Runs the agent once to prove it can reach NetCare, then registers the scheduled task
    "NetCare Monitoring Agent" (at startup, as SYSTEM, restarted if it stops) and starts it.
  Nothing is hidden: the task is listed in Task Scheduler, and uninstall-agent.ps1 removes everything.

.EXAMPLE
  # In an administrator PowerShell, in the folder containing these files:
  .\install-agent.ps1 -ServerUrl https://netcare.example.com -Token nca_xxxxxxxx
  .\install-agent.ps1 -ConfigFile .\agent.json
#>
[CmdletBinding(DefaultParameterSetName = "Values")]
param(
    [Parameter(ParameterSetName = "Values", Mandatory = $true)][string]$ServerUrl,
    [Parameter(ParameterSetName = "Values", Mandatory = $true)][string]$Token,
    [Parameter(ParameterSetName = "File", Mandatory = $true)][string]$ConfigFile,
    [string]$InstallDir = "$env:ProgramData\NetCare\Agent",
    [switch]$SkipTest
)
$ErrorActionPreference = "Stop"
$TaskName = "NetCare Monitoring Agent"

function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

# 1. Administrator rights (needed for ProgramData permissions and a SYSTEM task)
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Fail "Run this from an administrator PowerShell (right-click PowerShell, Run as administrator)."
}

# 2. Python 3.10 or newer
$python = $null
foreach ($candidate in @("py", "python")) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    $pyArgs = if ($candidate -eq "py") { @("-3", "-c") } else { @("-c") }
    try {
        $exe = & $cmd.Source @pyArgs "import sys; print(sys.executable if sys.version_info >= (3, 10) else '')" 2>$null
    } catch { $exe = $null }
    if ($exe -and (Test-Path $exe)) { $python = $exe.Trim(); break }
}
if (-not $python) { Fail "Python 3.10 or newer was not found. Install it from https://www.python.org (tick 'Add to PATH')." }
Write-Host "Using Python: $python"

# 3. Configuration
if ($PSCmdlet.ParameterSetName -eq "File") {
    if (-not (Test-Path $ConfigFile)) { Fail "Config file not found: $ConfigFile" }
    $cfg = Get-Content $ConfigFile -Raw | ConvertFrom-Json
    $ServerUrl = $cfg.server_url; $Token = $cfg.token
}
if ($Token -notmatch '^nca_[A-Za-z0-9_-]{20,}$') { Fail "The token does not look like a NetCare agent token (nca_...)." }
if ($ServerUrl -notmatch '^https://' -and $ServerUrl -notmatch '^http://(localhost|127\.0\.0\.1)(:\d+)?$') {
    Fail "The server address must start with https://"
}

# 4. Files, readable only by Administrators and SYSTEM
$source = Join-Path $PSScriptRoot "netcare_agent.py"
if (-not (Test-Path $source)) { Fail "netcare_agent.py must be next to this script." }
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item $source (Join-Path $InstallDir "netcare_agent.py") -Force
$configPath = Join-Path $InstallDir "agent.json"
[ordered]@{ server_url = $ServerUrl.TrimEnd("/"); token = $Token } | ConvertTo-Json | Set-Content -Path $configPath -Encoding UTF8
$acl = New-Object Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true, $false)  # no inherited access
foreach ($who in @("BUILTIN\Administrators", "NT AUTHORITY\SYSTEM")) {
    $rule = New-Object Security.AccessControl.FileSystemAccessRule($who, "FullControl", "ContainerInherit,ObjectInherit", "None", "Allow")
    $acl.AddAccessRule($rule)
}
Set-Acl -Path $InstallDir -AclObject $acl
Write-Host "Installed to $InstallDir (Administrators and SYSTEM only)"

# 5. Prove it works before scheduling it
$agentPy = Join-Path $InstallDir "netcare_agent.py"
if (-not $SkipTest) {
    Write-Host "Testing the connection to NetCare..."
    & $python $agentPy --config $configPath --once
    if ($LASTEXITCODE -eq 2) { Fail "NetCare rejected the token (revoked or mistyped). Issue a new token and try again." }
    if ($LASTEXITCODE -ne 0) { Fail "The test run failed (exit code $LASTEXITCODE). Check the server address and the internet connection." }
}

# 6. Visible startup task, restarted if it stops (a revoked token makes it stop for good: exit code 2)
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue; Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false }
$action = New-ScheduledTaskAction -Execute $python -Argument "`"$agentPy`" --config `"$configPath`"" -WorkingDirectory $InstallDir
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$task = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $task `
    -Description "NetCare monitoring agent: reports configured ping/port/SNMP checks to $ServerUrl over HTTPS. Remove with uninstall-agent.ps1." | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "Done. '$TaskName' is running and will start with Windows. It should show as online in NetCare within a minute." -ForegroundColor Green
