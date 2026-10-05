@echo off
rem Double-click this if staff on OTHER PCs in the office need to open NetCare too.
rem It needs Administrator (to add the firewall rule) and will ask Windows to confirm that.
title NetCare installer (office network)
net session >nul 2>&1
if %errorlevel% == 0 goto :elevated

powershell.exe -NoProfile -Command "Start-Process powershell.exe -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"%~dp0install\install.ps1\" -AllowLan'"
goto :eof

:elevated
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install\install.ps1" -AllowLan
if errorlevel 1 (
    echo.
    echo Something went wrong - see the message above.
    pause
)
