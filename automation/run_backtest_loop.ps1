<#
================================================================================
 GaganEA - automated backtest loop  (run_backtest_loop.ps1)
================================================================================
 Runs, hands-off, the full round loop on YOUR local Windows PC:

   (a) git pull the repo
   (b) copy GaganEA.mq5 into the MT5 MQL5\Experts folder
   (c) compile it headlessly with metaeditor64.exe and PARSE the compile log
       (aborting on any compile error - the metaeditor exit code is unreliable
       across builds, so we do NOT trust it)
   (d) generate a runtime tester .ini from backtest_template.ini and run
       terminal64.exe headlessly, WAITING for it to exit (ShutdownTerminal=1)
   (e) locate the HTML report MT5 wrote and copy it to
       reports\roundNN_YYYYMMDD.html
   (f) best-effort, NON-FATAL: python tools\analyze_report.py <report>
   (g) git add / commit / push the report (+ any .summary.json), gracefully
       skipping when nothing changed

 --------------------------------------------------------------------------
 AUTHORED IN A LINUX SANDBOX - NOT EXECUTED THERE.
 There is no MT5, no MQL5 compiler, and no PowerShell in the authoring
 sandbox, so this script has NOT been run end-to-end. Do a careful FIRST
 MANUAL RUN on your PC (watch the console + the log under automation\logs\)
 before you schedule it hands-off. See automation\SETUP.md.
 --------------------------------------------------------------------------

 Requires Windows PowerShell 5.1+ (ships with Windows) or PowerShell 7.
 No secrets are read, printed, or logged by this script, and it never dumps
 environment variables.

 Usage:
   .\run_backtest_loop.ps1                       # round 1, today's date
   .\run_backtest_loop.ps1 -RoundNumber 3
   .\run_backtest_loop.ps1 -RoundNumber 3 -RunDate 20260911
   (or double-click run_backtest_loop.bat)
================================================================================
#>

[CmdletBinding()]
param(
    # Iteration/round number -> reports\roundNN_YYYYMMDD.html  (zero-padded to 2).
    [int]$RoundNumber = 1,

    # Backtest date stamp as YYYYMMDD. Defaults to today.
    [string]$RunDate = (Get-Date -Format 'yyyyMMdd')
)

# ==============================================================================
# ============================  CONFIGURATION BLOCK  ===========================
# ==============================================================================
# EDIT THESE PATHS FOR YOUR PC. Every machine-specific path lives here and
# nowhere else. See automation\SETUP.md sections 3 & 4 for how to find each one.
#
# Tip: keep the backslashes; wrap in single quotes so nothing is interpreted.
# ------------------------------------------------------------------------------

$Config = @{

    # --- MetaTrader 5 program files (the INSTALL dir, e.g. C:\Program Files\...) ---
    MetaEditor64Exe = 'C:\Program Files\Fusion Markets MetaTrader 5\metaeditor64.exe'
    Terminal64Exe   = 'C:\Program Files\Fusion Markets MetaTrader 5\terminal64.exe'

    # --- Per-user MT5 DATA folder (the hashed folder, NOT the install dir) ---
    # Under %APPDATA%\MetaQuotes\Terminal\<HASH>. It is the one that contains a
    # MQL5\ subfolder and your account. SETUP.md section 3 shows how to find it.
    MT5DataDir      = 'C:\Users\gagan\AppData\Roaming\MetaQuotes\Terminal\930119AA53207C8778B41171FBFFB46F'

    # --- Sub-path (inside MT5DataDir) to the Experts folder. Rarely changes. ---
    ExpertsSubDir   = 'MQL5\Experts'

    # --- This git repo checkout on your PC (the folder containing GaganEA.mq5). ---
    # NOTE: verify this matches where you cloned happyBOT on your PC and edit if not.
    RepoDir         = 'C:\Users\gagan\happyBOT'

    # --- Name the compiled EA will have inside MQL5\Experts (no extension). ---
    # The script copies GaganEA.mq5 to <MT5DataDir>\<ExpertsSubDir>\<ExpertName>.mq5
    # and the tester loads <ExpertName>. Keep this in sync with GaganEA.mq5.
    ExpertName      = 'GaganEA'

    # --- Git branch to pull/commit/push. Match the branch you work on. ---
    # Round 0 tooling is merged into main; the loop now tracks main.
    GitBranch       = 'main'

    # --- Seconds to wait for a single backtest before giving up (safety net). ---
    TesterTimeoutSec = 3600
}

# ==============================================================================
# ==========================  END CONFIGURATION BLOCK  =========================
# ==============================================================================


$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# --- Resolve this script's own directory (so relative paths are robust). ------
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir     = Join-Path $ScriptDir 'logs'
$TemplateIni = Join-Path $ScriptDir 'backtest_template.ini'

if (-not (Test-Path -LiteralPath $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$RoundTag  = 'round{0:D2}' -f $RoundNumber
$LogStamp  = Get-Date -Format 'yyyyMMdd_HHmmss'
$LogFile   = Join-Path $LogDir ("{0}_{1}.log" -f $RoundTag, $LogStamp)

# ------------------------------------------------------------------------------
# Logging: everything goes to the console AND the timestamped log file.
# ------------------------------------------------------------------------------
function Write-Log {
    param(
        [Parameter(Mandatory)] [string]$Message,
        [ValidateSet('INFO', 'WARN', 'ERROR', 'STEP')] [string]$Level = 'INFO'
    )
    $line = '{0} [{1}] {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message
    switch ($Level) {
        'ERROR' { Write-Host $line -ForegroundColor Red }
        'WARN'  { Write-Host $line -ForegroundColor Yellow }
        'STEP'  { Write-Host $line -ForegroundColor Cyan }
        default { Write-Host $line }
    }
    Add-Content -LiteralPath $LogFile -Value $line
}

function Fail {
    param([string]$Message)
    Write-Log $Message 'ERROR'
    Write-Log ("Aborting. Full log: {0}" -f $LogFile) 'ERROR'
    exit 1
}

# ------------------------------------------------------------------------------
# Run an external exe and wait for it to fully exit. Returns the exit code.
# ------------------------------------------------------------------------------
function Invoke-AndWait {
    param(
        [Parameter(Mandatory)] [string]$FilePath,
        [string[]]$Arguments = @(),
        [int]$TimeoutSec = 0
    )
    if (-not (Test-Path -LiteralPath $FilePath)) {
        throw "Executable not found: $FilePath"
    }
    $p = Start-Process -FilePath $FilePath -ArgumentList $Arguments -PassThru -NoNewWindow
    if ($TimeoutSec -gt 0) {
        if (-not $p.WaitForExit($TimeoutSec * 1000)) {
            try { $p.Kill() } catch { }
            throw "Process timed out after $TimeoutSec s: $FilePath"
        }
    } else {
        $p.WaitForExit()
    }
    return $p.ExitCode
}

# ------------------------------------------------------------------------------
# Run git and decide success by EXIT CODE ONLY.
#
# git writes plenty of NORMAL, non-error text to stderr (e.g. "Already on
# 'main'", "Your branch is up to date", clone/pull progress). With
# $ErrorActionPreference = 'Stop', piping `git ... 2>&1` would turn that benign
# stderr into a TERMINATING error and abort the script even though git actually
# succeeded. To avoid that we temporarily set $ErrorActionPreference to
# 'Continue' for the duration of the git call, merge stderr into stdout for
# logging, and then judge the outcome purely by $LASTEXITCODE. Returns the git
# exit code.
# ------------------------------------------------------------------------------
function Invoke-Git {
    param([Parameter(Mandatory)] [string[]]$GitArgs)

    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        # 2>&1 merges git's stderr into the success stream so we can log it;
        # because EAP is 'Continue' here, stderr records do NOT throw.
        & git @GitArgs 2>&1 | ForEach-Object { Write-Log ("  git: {0}" -f $_) }
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prevEAP
    }
    return $code
}

Write-Log ("=== GaganEA backtest loop: {0}, RunDate {1} ===" -f $RoundTag, $RunDate) 'STEP'
Write-Log ("Log file: {0}" -f $LogFile)

# --- Sanity-check the configuration before we touch anything. -----------------
try {
    if ($RunDate -notmatch '^\d{8}$') {
        throw "RunDate must be YYYYMMDD (8 digits); got '$RunDate'."
    }
    $ExpertsDir = Join-Path $Config.MT5DataDir $Config.ExpertsSubDir
    $ReportsDir = Join-Path $Config.RepoDir 'reports'

    foreach ($pair in @(
            @{ n = 'MetaEditor64Exe'; v = $Config.MetaEditor64Exe },
            @{ n = 'Terminal64Exe';   v = $Config.Terminal64Exe },
            @{ n = 'RepoDir';         v = $Config.RepoDir },
            @{ n = 'MT5 Experts dir'; v = $ExpertsDir },
            @{ n = 'backtest_template.ini'; v = $TemplateIni }
        )) {
        if (-not (Test-Path -LiteralPath $pair.v)) {
            throw ("{0} not found: {1}  (fix the CONFIGURATION BLOCK / SETUP.md)" -f $pair.n, $pair.v)
        }
    }
} catch {
    Fail ("Configuration check failed: {0}" -f $_.Exception.Message)
}

# ==============================================================================
# STEP (a) - git pull
# ==============================================================================
try {
    Write-Log "STEP (a) git pull" 'STEP'
    Push-Location -LiteralPath $Config.RepoDir
    try {
        # checkout: "Already on 'main'" is written to stderr but is NOT an error.
        # Judge by exit code (Invoke-Git handles the stderr-is-not-fatal detail).
        $coCode = Invoke-Git @('checkout', $Config.GitBranch)
        if ($coCode -ne 0) {
            throw ("git checkout {0} failed (exit {1})." -f $Config.GitBranch, $coCode)
        }
        $pullCode = Invoke-Git @('pull', '--ff-only', 'origin', $Config.GitBranch)
        if ($pullCode -ne 0) {
            Write-Log "git pull returned non-zero; continuing with the local checkout." 'WARN'
        }
    } finally {
        Pop-Location
    }
} catch {
    Fail ("git pull step failed: {0}" -f $_.Exception.Message)
}

# ==============================================================================
# STEP (b) - copy the EA source into MT5's MQL5\Experts
# ==============================================================================
$ExpertMq5InRepo = Join-Path $Config.RepoDir 'GaganEA.mq5'
$ExpertMq5InMt5  = Join-Path $ExpertsDir ("{0}.mq5" -f $Config.ExpertName)
try {
    Write-Log "STEP (b) copy EA into MT5 Experts folder" 'STEP'
    if (-not (Test-Path -LiteralPath $ExpertMq5InRepo)) {
        throw "GaganEA.mq5 not found in repo: $ExpertMq5InRepo"
    }
    Copy-Item -LiteralPath $ExpertMq5InRepo -Destination $ExpertMq5InMt5 -Force
    Write-Log ("Copied {0} -> {1}" -f $ExpertMq5InRepo, $ExpertMq5InMt5)
} catch {
    Fail ("copy-EA step failed: {0}" -f $_.Exception.Message)
}

# ==============================================================================
# STEP (c) - headless compile + PARSE the log (exit code is unreliable)
# ==============================================================================
$CompileLog = Join-Path $LogDir ("compile_{0}_{1}.log" -f $RoundTag, $LogStamp)
try {
    Write-Log "STEP (c) compile EA with metaeditor64.exe" 'STEP'
    # metaeditor64 returns quickly; /log writes the compile result to a file.
    $null = Invoke-AndWait -FilePath $Config.MetaEditor64Exe -Arguments @(
        ("/compile:{0}" -f $ExpertMq5InMt5),
        ("/log:{0}"     -f $CompileLog)
    )

    # The exit code cannot be trusted across builds, so parse the log. MetaEditor
    # logs are commonly UTF-16; read as Unicode and fall back to default.
    Start-Sleep -Milliseconds 500
    if (-not (Test-Path -LiteralPath $CompileLog)) {
        throw "compile log was not produced: $CompileLog"
    }
    $logText = ''
    try   { $logText = Get-Content -LiteralPath $CompileLog -Encoding Unicode -Raw }
    catch { $logText = Get-Content -LiteralPath $CompileLog -Raw }
    if ([string]::IsNullOrWhiteSpace($logText)) {
        $logText = Get-Content -LiteralPath $CompileLog -Raw
    }

    foreach ($l in ($logText -split "`r?`n")) {
        if ($l.Trim().Length -gt 0) { Write-Log ("  meta: {0}" -f $l.Trim()) }
    }

    # A clean build reports "0 errors". Any "N error(s)" with N>0, or an explicit
    # MetaEditor error line, means abort.
    $errorCount = $null
    $m = [regex]::Match($logText, '(?im)(\d+)\s+error')
    if ($m.Success) { $errorCount = [int]$m.Groups[1].Value }

    # Match MetaEditor's actual per-error line format, which is:
    #   <path>(<line>,<col>) : error <code>: <message>
    # Anchor on the "(line,col) : error" position marker so a source/report
    # PATH that merely contains the literal substring ": error " cannot
    # false-positive and abort an otherwise clean build. We deliberately do
    # NOT match a bare ": error " anywhere in the text.
    $hasErrorLine = [regex]::IsMatch($logText, '(?im)\(\d+,\d+\)\s*:\s*error\s')

    if (($errorCount -ne $null -and $errorCount -gt 0) -or $hasErrorLine) {
        throw "compile reported errors (see $CompileLog). Fix GaganEA.mq5 and retry."
    }
    Write-Log "Compile OK (no errors found in log)."
} catch {
    Fail ("compile step failed: {0}" -f $_.Exception.Message)
}

# ==============================================================================
# STEP (d) - generate runtime .ini and run terminal64 headlessly, WAIT for exit
# ==============================================================================
$ReportBaseName = "{0}_{1}" -f $RoundTag, $RunDate     # e.g. round03_20260911
$ReportInMt5    = Join-Path $ExpertsDir ("..\..\{0}.html" -f $ReportBaseName)  # MT5 data root
$ReportInMt5    = [System.IO.Path]::GetFullPath($ReportInMt5)
$RuntimeIni     = Join-Path $LogDir ("tester_{0}_{1}.ini" -f $RoundTag, $LogStamp)
try {
    Write-Log "STEP (d) generate runtime tester .ini and run terminal64" 'STEP'

    $tpl = Get-Content -LiteralPath $TemplateIni -Raw
    # Expert path is relative to MQL5\Experts, no extension (MT5 convention).
    $tpl = $tpl.Replace('__EXPERT_PATH__', $Config.ExpertName)
    $tpl = $tpl.Replace('__REPORT_PATH__', $ReportInMt5)
    # Write the runtime ini (MT5 reads /config ini reliably as ANSI/UTF-8).
    Set-Content -LiteralPath $RuntimeIni -Value $tpl -Encoding ASCII
    Write-Log ("Runtime ini: {0}" -f $RuntimeIni)
    Write-Log ("Report will be written to: {0}" -f $ReportInMt5)

    $code = Invoke-AndWait -FilePath $Config.Terminal64Exe `
                           -Arguments @(("/config:{0}" -f $RuntimeIni)) `
                           -TimeoutSec $Config.TesterTimeoutSec
    Write-Log ("terminal64 exited (code {0}). ShutdownTerminal=1 self-terminates it." -f $code)
} catch {
    Fail ("backtest step failed: {0}" -f $_.Exception.Message)
}

# ==============================================================================
# STEP (e) - locate the report and copy it to reports\roundNN_YYYYMMDD.html
# ==============================================================================
$FinalReport = Join-Path $ReportsDir ("{0}.html" -f $ReportBaseName)
try {
    Write-Log "STEP (e) locate + rename the report" 'STEP'
    if (-not (Test-Path -LiteralPath $ReportsDir)) {
        New-Item -ItemType Directory -Path $ReportsDir -Force | Out-Null
    }

    # MT5 may append .html itself, or write next to the data root. Try both.
    $candidates = @(
        $ReportInMt5,
        ($ReportInMt5 + '.html'),
        (Join-Path $Config.MT5DataDir ("{0}.html" -f $ReportBaseName))
    ) | Select-Object -Unique

    $found = $null
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c) { $found = $c; break }
    }
    if (-not $found) {
        throw ("report not found. Looked for: {0}. Check the Report path / MT5 data folder (see SETUP.md section 9)." -f ($candidates -join '  |  '))
    }
    Copy-Item -LiteralPath $found -Destination $FinalReport -Force
    Write-Log ("Report -> {0}" -f $FinalReport)
} catch {
    Fail ("report-locate step failed: {0}" -f $_.Exception.Message)
}

# ==============================================================================
# STEP (f) - best-effort, NON-FATAL analyzer run
# ==============================================================================
try {
    Write-Log "STEP (f) analyze (best-effort, non-fatal)" 'STEP'
    $analyzer = Join-Path $Config.RepoDir 'tools\analyze_report.py'
    $python   = $null
    foreach ($cand in @('python', 'python3', 'py')) {
        $cmd = Get-Command $cand -ErrorAction SilentlyContinue
        if ($cmd) { $python = $cmd.Source; break }
    }

    if (-not (Test-Path -LiteralPath $analyzer)) {
        Write-Log "analyzer tools\analyze_report.py not found - skipping analysis." 'WARN'
    } elseif (-not $python) {
        Write-Log "Python not found on PATH - skipping analysis (install Python 3 to enable)." 'WARN'
    } else {
        Push-Location -LiteralPath $Config.RepoDir
        try {
            & $python 'tools\analyze_report.py' $FinalReport 2>&1 | ForEach-Object { Write-Log ("  analyze: {0}" -f $_) }
            if ($LASTEXITCODE -ne 0) {
                Write-Log ("analyzer exited non-zero ({0}); continuing anyway." -f $LASTEXITCODE) 'WARN'
            }
        } finally {
            Pop-Location
        }
    }
} catch {
    # Non-fatal by design.
    Write-Log ("analysis step raised an error (non-fatal): {0}" -f $_.Exception.Message) 'WARN'
}

# ==============================================================================
# STEP (g) - git add / commit / push, gracefully skipping when nothing changed
# ==============================================================================
try {
    Write-Log "STEP (g) git add / commit / push" 'STEP'
    Push-Location -LiteralPath $Config.RepoDir
    try {
        # Stage the report and any summary the analyzer produced (by name).
        # NOTE: git add of an explicitly-named IGNORED path exits non-zero and
        # stages nothing, so we MUST check the exit code after each add or a
        # botched .gitignore would let the artifact silently never get committed.
        # The report .html is never ignored; the per-round .summary.json is
        # kept out of the ignore rule via a negation in .gitignore
        # (!reports/round*.summary.json) so it stages cleanly too.
        # All git calls go through Invoke-Git so git's benign stderr (progress,
        # "up to date", etc.) is NOT mistaken for a fatal error.
        $addCode = Invoke-Git @('add', '--', "reports/$ReportBaseName.html")
        if ($addCode -ne 0) {
            throw "git add of reports/$ReportBaseName.html failed (exit $addCode); is it ignored by .gitignore? (see SETUP.md section 9)."
        }
        $summaryRel = "reports/$ReportBaseName.summary.json"
        if (Test-Path -LiteralPath (Join-Path $Config.RepoDir $summaryRel)) {
            $addSumCode = Invoke-Git @('add', '--', $summaryRel)
            if ($addSumCode -ne 0) {
                throw "git add of $summaryRel failed (exit $addSumCode). It exists but git refused to stage it, most likely an .gitignore rule shadows reports/*.summary.json; ensure the '!reports/round*.summary.json' negation is present (see SETUP.md section 9)."
            }
        }

        # Nothing staged? Skip commit/push without erroring.
        $staged = & git diff --cached --name-only
        if ([string]::IsNullOrWhiteSpace(($staged -join ''))) {
            Write-Log "Nothing changed to commit - skipping commit/push." 'WARN'
        } else {
            $prettyDate = '{0}-{1}-{2}' -f $RunDate.Substring(0,4), $RunDate.Substring(4,2), $RunDate.Substring(6,2)
            $msg = "Round {0} backtest report ({1})" -f $RoundNumber, $prettyDate
            $commitCode = Invoke-Git @('commit', '-m', $msg)
            if ($commitCode -ne 0) {
                throw "git commit failed (exit $commitCode; see log)."
            }
            $pushCode = Invoke-Git @('push', 'origin', $Config.GitBranch)
            if ($pushCode -ne 0) {
                throw "git push failed (exit $pushCode; check auth / credential helper - SETUP.md section 9)."
            }
            Write-Log ("Committed + pushed: {0}" -f $msg)
        }
    } finally {
        Pop-Location
    }
} catch {
    Fail ("git commit/push step failed: {0}" -f $_.Exception.Message)
}

Write-Log ("=== DONE: {0} ({1}). Report: {2} ===" -f $RoundTag, $RunDate, $FinalReport) 'STEP'
Write-Log "Reminder: sanity-check this round by hand (see SETUP.md section 10) to avoid overfitting; goal is under 15% drawdown on XAUUSD."
exit 0
