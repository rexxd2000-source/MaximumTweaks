@echo off
setlocal EnableExtensions
title MaximumTweaks - NVIDIA Control Panel Restore

echo.
echo ================================================================
echo  NVIDIA CONTROL PANEL RESTORE
echo ================================================================
echo.

net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Administrator rights required - run this file as Administrator.
    pause
    exit /b 1
)

where nvidia-smi >nul 2>&1
if errorlevel 1 (
    echo [ERROR] nvidia-smi not found. Nothing to restore - exiting.
    pause
    exit /b 1
)

set "LATEST="
for /f "delims=" %%d in ('dir /b /ad "%~dp0nvidia-backups\opt-*" 2^>nul ^| sort /r') do (
    if not defined LATEST set "LATEST=%%d"
)

if defined LATEST (
    set "BKBEFORE=%~dp0nvidia-backups\%LATEST%\persistence_before.txt"
    if exist "%BKBEFORE%" (
        for /f "tokens=*" %%a in (%BKBEFORE%) do set PERS_BEFORE=%%a
        echo  Previous persistence mode was: %PERS_BEFORE%
        if /i "%PERS_BEFORE%"=="ENABLED" (
            echo  Restoring persistence mode to ENABLED.
            nvidia-smi -pm 1 >nul 2>&1
        ) else (
            echo  Restoring persistence mode to DISABLED.
            nvidia-smi -pm 0 >nul 2>&1
        )
        for /f "tokens=*" %%a in ('nvidia-smi --query-gpu^=persistence_mode --format^=csv,noheader 2^>nul') do set PERS_NOW=%%a
        echo  Verification: persistence mode is now %PERS_NOW%.
    ) else (
        echo  Backup file missing inside %LATEST% - resetting to system default.
        nvidia-smi -pm 0 >nul 2>&1
    )
) else (
    echo  No opt-* backup found. Resetting persistence mode to system default.
    nvidia-smi -pm 0 >nul 2>&1
)

echo.
echo  Restore complete. No NVIDIA Control Panel 3D settings were touched by
echo  these scripts - anything configured in the NVCP UI stays as you left it.
echo.
pause