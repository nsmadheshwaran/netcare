@echo off
title Stop NetCare
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1"
pause
