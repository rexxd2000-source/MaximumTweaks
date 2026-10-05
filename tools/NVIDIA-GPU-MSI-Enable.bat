@echo off
setlocal EnableExtensions
title MaximumTweaks - NVIDIA GPU MSI Mode Enable (advanced)

echo.
echo ================================================================
echo  NVIDIA GPU MESSAGE-SIGNALED INTERRUPTS (MSI) - ENABLE
echo  ADVANCED option. NOT a guaranteed performance gain.
echo ================================================================
echo.

net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Administrator rights required - run this file as Administrator.
    pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0NVIDIA-GPU-MSI-Enable.ps1"
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%