@echo off
title NetCare backup
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0backup.ps1"
pause
