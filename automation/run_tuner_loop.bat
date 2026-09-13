@echo off
REM ==========================================================================
REM  GaganEA CONTINUOUS auto-tuner loop - double-click wrapper
REM  for run_tuner_loop.ps1
REM ==========================================================================
REM  Launches the PowerShell auto-tuner harness in the SAME folder as this
REM  .bat, bypassing the execution policy for this one invocation only (does
REM  NOT change system policy) and skipping the user profile for a clean start.
REM
REM  This loop runs FOREVER (back-to-back backtests, no gap) until you STOP it:
REM      * close this window, or
REM      * press Ctrl+C in this window, or
REM      * end the scheduled task (if you run it via Task Scheduler).
REM
REM  STRONG recommendation (see automation\tuner\README.md): run ONE manual
REM  tuner iteration first (a single backtest + one tuner.py invocation) and
REM  eyeball the result before starting this infinite loop.
REM
REM  You can double-click this file, or run it with the same params as the .ps1:
REM      run_tuner_loop.bat
REM      run_tuner_loop.bat -MaxIterations 50
REM      run_tuner_loop.bat -TunerHtmlKeep 30
REM
REM  All arguments (%*) are forwarded to the script. The window pauses at the
REM  end (after the loop stops) so a double-click session stays open to show
REM  the final status / errors.
REM ==========================================================================

setlocal

REM %~dp0 = the directory this .bat lives in (with trailing backslash).
set "SCRIPT_DIR=%~dp0"

powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%SCRIPT_DIR%run_tuner_loop.ps1" %*
set "RC=%ERRORLEVEL%"

echo.
echo ==========================================================================
echo  run_tuner_loop.ps1 finished with exit code %RC%.
echo  (0 = clean stop; non-zero = a FATAL config error - scroll up or read the
echo   log under automation\logs\ for details.)
echo ==========================================================================
echo.

pause
endlocal & exit /b %RC%
