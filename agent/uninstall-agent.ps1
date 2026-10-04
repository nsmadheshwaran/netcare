<#
.SYNOPSIS
  Removes the NetCare monitoring agent from this PC: stops and deletes its scheduled task and its folder.
  Also revoke the agent in NetCare (Network monitoring > Agents > Revoke) so its token stops working.
.EXAMPLE
  .\uninstall-agent.ps1
#>
param([string]$InstallDir = "$env:ProgramData\NetCare\Agent")
$ErrorActionPreference = "Stop"
$TaskName = "NetCare Monitoring Agent"

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERROR: Run this from an administrator PowerShell." -ForegroundColor Red; exit 1
}
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed the scheduled task '$TaskName'."
} else {
    Write-Host "No scheduled task '$TaskName' found."
}
# Only ever removes the agent's own folder, and only if it looks like one.
if ((Test-Path (Join-Path $InstallDir "netcare_agent.py")) -or (Test-Path (Join-Path $InstallDir "agent.json"))) {
    Remove-Item -Recurse -Force $InstallDir
    Write-Host "Removed $InstallDir."
} elseif (Test-Path $InstallDir) {
    Write-Host "$InstallDir does not look like a NetCare agent folder; left it alone."
}
Write-Host "Uninstalled. Remember to revoke this agent in NetCare." -ForegroundColor Green
