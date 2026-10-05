@echo off
setlocal EnableExtensions
title MaximumTweaks - Revert FPS-collapse tweaks (500->60->500)

echo.
echo ================================================================
echo  REVERT FPS-COLLAPSE TWEAKS  (500-^>60-^>500)
echo  Undoes the GPU PowerMizer + timer-resolution tweaks that were
echo  identified as the collapse causes. Safe to run on any PC,
echo  with or without MaximumTweaks installed.
echo ================================================================
echo.

net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Administrator rights required - run this file as Administrator.
    pause
    exit /b 1
)

for /f "tokens=2 delims==." %%a in ('wmic os get localdatetime /value 2^>nul') do set "TS=%%a"
if not defined TS set "TS=%time:~0,2%%time:~3,2%%time:~6,2%"
set "TS=%TS: =0%"
set "BKDIR=%~dp0nvidia-backups\collapse-revert-%TS:~0,8%-%TS:~8,6%"
mkdir "%BKDIR%" >nul 2>&1

reg export "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\kernel" "%BKDIR%\kernel-timer.reg" /y >nul 2>&1
reg query "HKLM\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000" /v PerfLevelSrc > "%BKDIR%\gpu-powermizer-before.txt" 2>&1
reg query "HKLM\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000" /v PowerMizerLevel >> "%BKDIR%\gpu-powermizer-before.txt" 2>&1
reg query "HKLM\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000" /v PowerMizerLevelAC >> "%BKDIR%\gpu-powermizer-before.txt" 2>&1
reg query "HKLM\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000" /v PowerMizerEnable >> "%BKDIR%\gpu-powermizer-before.txt" 2>&1
reg query "HKLM\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\*\Curver" /v PowerMizerLevelAC >> "%BKDIR%\gpu-powermizer-before.txt" 2>&1

echo  Backed up current state to: %BKDIR%
echo.

set "FIXED=0"
set "FAIL=0"

echo  [1/2] NVIDIA GPU PowerMizer values (fpsb-004 / nv-003 / wgr-007)
call :DelVal "HKLM\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000" "PerfLevelSrc"
call :DelVal "HKLM\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000" "PowerMizerLevel"
call :DelVal "HKLM\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000" "PowerMizerLevelAC"
call :DelVal "HKLM\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000" "PowerMizerEnable"
call :DelVal "HKLM\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\*\Curver" "PowerMizerLevelAC"

echo.
echo  [2/2] Timer-resolution overrides (perf-001 / power-017 / fpsb-018 / timer_resolution)
call :DelVal "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\kernel" "GlobalTimerResolutionRequests"
call :DelVal "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\kernel" "GlobalTimerResolution"
call :DelVal "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\kernel" "TimerResolution"

echo.
echo ================================================================
set "SUMM=%FIXED% value(s) removed, %FAIL% error(s)"
echo  %SUMM%
echo ================================================================
if %FAIL% GTR 0 (
    echo  [WARNING] %FAIL% values could not be removed. Re-check admin rights.
) else (
    echo  Revert complete. Deleting these values returns them to Windows/driver
    echo  defaults, same as the app's own revert does.
)
echo.
echo  A REBOOT is recommended before judging FPS - GPU class-key and
echo  timer changes apply after a boot / driver reload.
echo.
echo  Backup of the removed state (if you ever need it): %BKDIR%
echo.
pause
exit /b %FAIL%

:DelVal
set "PATHARG=%~1"
set "NAME=%~2"
reg delete "%PATHARG%" /v "%NAME%" /f >nul 2>&1
if errorlevel 1 (
    reg query "%PATHARG%" /v "%NAME%" >nul 2>&1
    if errorlevel 1 (
        echo   [clean] %PATHARG% :: %NAME% not present
    ) else (
        echo   [error] %PATHARG% :: %NAME% still present after delete
        set /a FAIL+=1
    )
) else (
    echo   [ok]    removed %PATHARG% :: %NAME%
    set /a FIXED+=1
)
exit /b 0