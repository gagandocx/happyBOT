@echo off
REM ==========================================================================
REM  HappyBot - one-click updater
REM ==========================================================================
REM  Double-click this file (it lives in your happyBOT folder) to pull ALL the
REM  latest fixes and updated files from GitHub into your local copy.
REM
REM  It is robust to the usual snag: if you have committed something locally
REM  (e.g. a backtest report you dropped in data/ or reports/) AND the remote
REM  has new commits, a plain "git pull" can stop with a merge/editor prompt.
REM  This script:
REM    1. stashes/commits any local changes so nothing is lost,
REM    2. pulls with an automatic merge (no text editor opens),
REM    3. tells you clearly whether it succeeded.
REM
REM  It does NOT push. It only brings your local folder up to date. Use the
REM  other scripts (automation\...) to run backtests.
REM ==========================================================================

setlocal
REM Run from the folder this .bat lives in (the repo root).
cd /d "%~dp0"

echo ==========================================================================
echo  HappyBot updater - folder: %CD%
echo ==========================================================================
echo.

REM --- Sanity: are we actually inside the git repo? ---
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

REM --- Figure out the current branch (should be main). ---
for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD') do set "BRANCH=%%b"
echo Current branch: %BRANCH%
echo.

REM --- If you have uncommitted local changes, commit them first so the merge
REM     cannot fail on "unstaged changes" and nothing you added is lost. ---
git diff --quiet
set "UNSTAGED=%ERRORLEVEL%"
git diff --cached --quiet
set "STAGED=%ERRORLEVEL%"
REM Also catch brand-new untracked files (reports you dropped in, etc.).
set "UNTRACKED="
for /f "delims=" %%f in ('git ls-files --others --exclude-standard') do set "UNTRACKED=1"

if "%UNSTAGED%"=="1" goto do_local_commit
if "%STAGED%"=="1" goto do_local_commit
if defined UNTRACKED goto do_local_commit
goto after_local_commit

:do_local_commit
echo Local changes detected - committing them first so the update is clean...
git add -A
git commit -m "Local changes before update (auto-saved by update.bat)"
echo.

:after_local_commit

REM --- Fetch + merge the latest from origin. --no-edit avoids the Vim prompt;
REM     --no-rebase keeps it a simple merge that never rewrites your commits. ---
echo Fetching and merging the latest from origin/%BRANCH% ...
git pull --no-rebase --no-edit origin %BRANCH%
set "RC=%ERRORLEVEL%"
echo.

if not "%RC%"=="0" goto pull_failed

echo ==========================================================================
echo  SUCCESS - your happyBOT folder is now up to date.
echo  Latest EA + tools + automation are pulled. You can run a backtest now.
echo ==========================================================================
echo.
echo Current version line in HappyBot.mq5:
git --no-pager grep -h "#property version" -- HappyBot.mq5 2>nul
echo.
pause
endlocal
exit /b 0

:pull_failed
echo ==========================================================================
echo  [ERROR] The update did not complete cleanly (exit code %RC%).
echo  Most likely a genuine merge conflict (the same file changed both here and
echo  on GitHub). Nothing was lost. Options:
echo    - Send Kiro the output above, or
echo    - Run:  git merge --abort   then try update.bat again, or
echo    - If you do not care about local edits to tracked files:
echo        git reset --hard origin/%BRANCH%    ^(WARNING: discards local edits^)
echo ==========================================================================
echo.
pause
endlocal
exit /b %RC%
