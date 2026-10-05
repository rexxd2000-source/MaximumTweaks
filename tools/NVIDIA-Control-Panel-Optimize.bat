@echo off
setlocal EnableExtensions
title MaximumTweaks - NVIDIA Control Panel Optimize (documented settings only)

echo.
echo ================================================================
echo  NVIDIA CONTROL PANEL OPTIMIZE - documented settings only
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
    echo [ERROR] nvidia-smi not found. NVIDIA driver not installed?
    echo         No changes were made. Exiting.
    pause
    exit /b 1
)

set "QF=%TEMP%\mt_nv_qr.txt"
set "GPUNAME="
set "DRV="
nvidia-smi --query-gpu=name --format=csv,noheader > "%QF%" 2>nul
if not errorlevel 1 ( for /f "usebackq tokens=*" %%a in ("%QF%") do set GPUNAME=%%a )
nvidia-smi --query-gpu=driver_version --format=csv,noheader > "%QF%" 2>nul
if not errorlevel 1 ( for /f "usebackq tokens=*" %%a in ("%QF%") do set DRV=%%a )
del "%QF%" >nul 2>&1
if not defined GPUNAME (
    echo [ERROR] No NVIDIA GPU detected. Exiting without changes.
    pause
    exit /b 1
)

echo  GPU          : %GPUNAME%
echo  Driver       : %DRV%
echo.

for /f "tokens=2 delims==." %%a in ('wmic os get localdatetime /value 2^>nul') do set "TS=%%a"
if not defined TS set "TS=%time:~0,2%%time:~3,2%%time:~6,2%"
set "TS=%TS: =0%"
set "BKDIR=%~dp0nvidia-backups\opt-%TS:~0,8%-%TS:~8,6%"
mkdir "%BKDIR%" >nul 2>&1

nvidia-smi -q > "%BKDIR%\nvidia-smi-full.txt" 2>nul
nvidia-smi --query-gpu=persistence_mode --format=csv,noheader > "%BKDIR%\persistence_before.txt" 2>nul
set "PERS_BEFORE="
for /f "usebackq tokens=*" %%a in ("%BKDIR%\persistence_before.txt") do set PERS_BEFORE=%%a
echo  Backing up current state to: %BKDIR%
echo  Persistence mode before   : %PERS_BEFORE%
echo.

echo  [1/1] Enabling NVIDIA persistence mode (documented nvidia-smi setting)...
nvidia-smi -pm 1 >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] nvidia-smi -pm 1 failed. No other changes were made.
    pause
    exit /b 1
)
set "PERS_NOW="
nvidia-smi --query-gpu=persistence_mode --format=csv,noheader > "%QF%" 2>nul
if not errorlevel 1 ( for /f "usebackq tokens=*" %%a in ("%QF%") do set PERS_NOW=%%a )
del "%QF%" >nul 2>&1
echo        Verification: persistence mode is now %PERS_NOW%.
echo.

echo  RESTORED via: NVIDIA-Control-Panel-Restore.bat
echo.
echo  NOTE (important):
echo   - 3D profile settings (Power Management Mode = Prefer maximum
echo     performance, Low Latency Mode, Texture Filtering) are managed ONLY in
echo     NVIDIA Control Panel. MaximumTweaks deliberately does NOT write the
echo     undocumented registry keys for these - they are driver-version
echo     dependent and were the prime suspect in the 500-^>60-^>500 collapse.
echo     Set them manually in: Manage 3D Settings ^> Global Settings.
echo   - This script changed exactly one thing: GPU persistence mode.
echo.
pause