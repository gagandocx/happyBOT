@echo off
REM ==========================================================================
REM  GaganEA backtest loop — double-click wrapper for run_backtest_loop.ps1
REM ==========================================================================
REM  Launches the PowerShell harness in the SAME folder as this .bat, bypassing
REM  the execution policy for this one invocation only (does NOT change system
REM  policy) and skipping the user profile for a clean, fast start.
REM
REM  You can double-click this file, or run it with the same params as the .ps1:
REM      run_backtest_loop.bat
REM      run_backtest_loop.bat -RoundNumber 3
REM      run_backtest_loop.bat -RoundNumber 3 -RunDate 20260911
REM
REM  All arguments (%*) are forwarded to the script. The window pauses at the
REM  end so a double-click session stays open to show results / errors.
REM ==========================================================================

setlocal

REM %~dp0 = the directory this .bat lives in (with trailing backslash).
set "SCRIPT_DIR=%~dp0"

powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%SCRIPT_DIR%run_backtest_loop.ps1" %*
set "RC=%ERRORLEVEL%"

echo.
echo ==========================================================================
echo  run_backtest_loop.ps1 finished with exit code %RC%.
echo  (0 = success; non-zero = a step failed — scroll up or read the log under
echo   automation\logs\ for details.)
echo ==========================================================================
echo.

pause
endlocal & exit /b %RC%
