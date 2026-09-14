@echo off
REM ==========================================================================
REM  HappyBot - one-click UPDATE + COMPILE
REM ==========================================================================
REM  Double-click this file (it lives in your happyBOT folder) to:
REM    1. pull ALL the latest fixes / updated files from GitHub,
REM    2. copy the freshly-updated HappyBot.mq5 into MT5's Experts folder,
REM    3. compile it headlessly with MetaEditor (checks for compile errors),
REM  so all you have to do in MT5 is right-click Navigator -> Refresh and the
REM  latest compiled HappyBot is ready to drop on a chart / run in the tester.
REM
REM  It does NOT push and does NOT run a backtest - it only updates + compiles.
REM ==========================================================================

setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM ==========================================================================
REM  CONFIG - edit these only if your MT5 install / data folder ever moves.
REM  (Find the data folder in MT5 via File -> Open Data Folder.)
REM ==========================================================================
set "METAEDITOR=C:\Program Files\Fusion Markets MetaTrader 5\metaeditor64.exe"
set "MT5_DATA_DIR=C:\Users\gagan\AppData\Roaming\MetaQuotes\Terminal\930119AA53207C8778B41171FBFFB46F"
set "EXPERT_NAME=HappyBot"
REM ==========================================================================

set "EXPERTS_DIR=%MT5_DATA_DIR%\MQL5\Experts"
set "SRC_MQ5=%CD%\%EXPERT_NAME%.mq5"
set "DST_MQ5=%EXPERTS_DIR%\%EXPERT_NAME%.mq5"
set "COMPILE_LOG=%CD%\update_compile.log"

echo ==========================================================================
echo  HappyBot update + compile - folder: %CD%
echo ==========================================================================
echo.

REM --- Sanity: are we inside the git repo? ---
git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
  echo [ERROR] This folder is not a git repository.
  echo         Put update.bat inside your cloned happyBOT folder
  echo         ^(the one that contains HappyBot.mq5^) and try again.
  echo.
  pause
  endlocal
  exit /b 1
)

for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD') do set "BRANCH=%%b"
echo Current branch: %BRANCH%
echo.

REM ==========================================================================
REM  STEP 1 - update from GitHub
REM ==========================================================================
echo [1/3] Updating from origin/%BRANCH% ...

REM Commit any local changes first so the merge can't jam on them.
git diff --quiet
set "UNSTAGED=!ERRORLEVEL!"
git diff --cached --quiet
set "STAGED=!ERRORLEVEL!"
set "UNTRACKED="
for /f "delims=" %%f in ('git ls-files --others --exclude-standard') do set "UNTRACKED=1"

if "!UNSTAGED!"=="1" set "NEEDCOMMIT=1"
if "!STAGED!"=="1" set "NEEDCOMMIT=1"
if defined UNTRACKED set "NEEDCOMMIT=1"

if defined NEEDCOMMIT (
  echo       Local changes detected - committing them first so the update is clean...
  git add -A
  git commit -m "Local changes before update (auto-saved by update.bat)"
)

git pull --no-rebase --no-edit origin %BRANCH%
if not "!ERRORLEVEL!"=="0" (
  echo.
  echo [ERROR] Update did not complete cleanly (likely a real merge conflict).
  echo         Nothing was lost. Send Kiro the output above, or run:
  echo           git merge --abort
  echo         then try update.bat again.
  echo.
  pause
  endlocal
  exit /b 1
)
echo       Update OK.
echo.

REM ==========================================================================
REM  STEP 2 - copy the updated EA into MT5's Experts folder
REM ==========================================================================
echo [2/3] Copying %EXPERT_NAME%.mq5 into MT5 Experts folder ...

if not exist "%SRC_MQ5%" (
  echo [ERROR] %SRC_MQ5% not found ^(is the EA named %EXPERT_NAME%.mq5?^).
  pause
  endlocal
  exit /b 1
)
if not exist "%EXPERTS_DIR%" (
  echo [ERROR] MT5 Experts folder not found:
  echo         %EXPERTS_DIR%
  echo         Fix MT5_DATA_DIR in the CONFIG block at the top of this file
  echo         ^(MT5: File -^> Open Data Folder shows the right path^).
  pause
  endlocal
  exit /b 1
)
copy /y "%SRC_MQ5%" "%DST_MQ5%" >nul
if not "!ERRORLEVEL!"=="0" (
  echo [ERROR] Could not copy the EA into %EXPERTS_DIR%.
  pause
  endlocal
  exit /b 1
)
echo       Copied to %DST_MQ5%
echo.

REM ==========================================================================
REM  STEP 3 - compile headlessly with MetaEditor
REM ==========================================================================
echo [3/3] Compiling with MetaEditor ...

if not exist "%METAEDITOR%" (
  echo [ERROR] MetaEditor not found:
  echo         %METAEDITOR%
  echo         Fix METAEDITOR in the CONFIG block at the top of this file.
  pause
  endlocal
  exit /b 1
)

REM MetaEditor's exit code is unreliable across builds, so we compile with a
REM /log and then scan the log for a real "(line,col) : error" marker.
if exist "%COMPILE_LOG%" del /q "%COMPILE_LOG%" >nul 2>&1
"%METAEDITOR%" /compile:"%DST_MQ5%" /log:"%COMPILE_LOG%"

REM Give the log a moment to flush.
ping -n 2 127.0.0.1 >nul

if not exist "%COMPILE_LOG%" (
  echo [WARN] No compile log was produced. If MT5 shows HappyBot after a
  echo        Navigator refresh, the compile likely still succeeded.
  goto done
)

REM Look for a genuine MetaEditor error line: "...(line,col) : error ...".
REM findstr /R uses limited regex; this pattern matches ") : error".
findstr /R /C:") : error" "%COMPILE_LOG%" >nul 2>&1
if "!ERRORLEVEL!"=="0" (
  echo.
  echo [ERROR] Compile reported errors. See the log:
  echo         %COMPILE_LOG%
  echo         (Send it to Kiro to fix.)
  echo.
  type "%COMPILE_LOG%"
  pause
  endlocal
  exit /b 1
)
echo       Compile OK (no errors found in the log).

:done
echo.
echo ==========================================================================
echo  DONE - updated + compiled.
echo  In MetaTrader 5: right-click Navigator -^> Refresh, and the latest
echo  compiled %EXPERT_NAME% is ready. Version:
git --no-pager grep -h "#property version" -- %EXPERT_NAME%.mq5 2>nul
echo ==========================================================================
echo.
pause
endlocal
exit /b 0
