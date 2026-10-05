@echo off
rem Double-click this to install NetCare. For use from other PCs in the office, use
rem "Install NetCare (Office Network).bat" instead, which needs Administrator.
title NetCare installer
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install\install.ps1"
if errorlevel 1 (
    echo.
    echo Something went wrong - see the message above.
    pause
)
