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

# ------------------------------------------------------------------------------
# On a no-report failure, tail the newest MT5 Tester log so the failure is
# diagnosable in one shot. MT5 build 6191 writes tester agent logs under
# <MT5DataDir>\Tester\logs\*.log and general logs under <MT5DataDir>\logs\*.log.
# We pick the file with the newest LastWriteTime across BOTH locations and log
# its last ~40 lines. Non-crashing: if no log exists we just log a WARN.
# ------------------------------------------------------------------------------
function Write-NewestTesterLogTail {
    param(
        [Parameter(Mandatory)] [string]$Mt5DataDir,
        [int]$TailLines = 40
    )
    try {
        $logDirs = @(
            (Join-Path $Mt5DataDir 'Tester\logs'),
            (Join-Path $Mt5DataDir 'logs')
        )
        $logs = @()
        foreach ($d in $logDirs) {
            if (Test-Path -LiteralPath $d) {
                $logs += Get-ChildItem -LiteralPath $d -Filter '*.log' -File -ErrorAction SilentlyContinue
            }
        }
        if (-not $logs -or $logs.Count -eq 0) {
            Write-Log ("No MT5 tester log found under {0} or {1}." -f $logDirs[0], $logDirs[1]) 'WARN'
            return
        }
        $newest = $logs | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        Write-Log ("Tailing newest tester log ({0} lines): {1}" -f $TailLines, $newest.FullName) 'WARN'
        $tail = Get-Content -LiteralPath $newest.FullName -Tail $TailLines -ErrorAction SilentlyContinue
        if (-not $tail) {
            $tail = Get-Content -LiteralPath $newest.FullName -ErrorAction SilentlyContinue | Select-Object -Last $TailLines
        }
        foreach ($t in $tail) {
            Write-Log ("  tlog: {0}" -f $t)
        }
    } catch {
        Write-Log ("could not read tester log (non-fatal): {0}" -f $_.Exception.Message) 'WARN'
    }
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
$RuntimeIni     = Join-Path $LogDir ("tester_{0}_{1}.ini" -f $RoundTag, $LogStamp)
$runStart       = $null                                 # set right before launch
try {
    Write-Log "STEP (d) generate runtime tester .ini and run terminal64" 'STEP'

    $tpl = Get-Content -LiteralPath $TemplateIni -Raw
    # Expert path is relative to MQL5\Experts, no extension (MT5 convention).
    $tpl = $tpl.Replace('__EXPERT_PATH__', $Config.ExpertName)
    # Report= is a BARE filename (no dir, no ext). On build 6191 MT5 writes it
    # relative to the data-folder ROOT (as .htm, sometimes .html) and commonly
    # ignores an absolute path - so we hand it just the base name and search for
    # the produced file(s) in step (e).
    $tpl = $tpl.Replace('__REPORT_NAME__', $ReportBaseName)
    # Write the runtime ini (MT5 reads /config ini reliably as ANSI/UTF-8).
    Set-Content -LiteralPath $RuntimeIni -Value $tpl -Encoding ASCII
    Write-Log ("Runtime ini: {0}" -f $RuntimeIni)
    Write-Log ("Report base name: {0} - MT5 writes it (as .htm/.html) under the data-folder root: {1}" -f $ReportBaseName, $Config.MT5DataDir)

    # Capture a run-start timestamp so step (e) can fall back to "any report
    # written since we launched" if the exact base-name file is not found.
    $runStart = Get-Date
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

    # On build 6191 MT5 writes the report (bare Report= name) RELATIVE TO THE
    # DATA-FOLDER ROOT, typically as <base>.htm and on some builds <base>.html.
    # Build an explicit list of PRIMARY candidates under MT5DataDir for both
    # extensions, plus legacy locations for backward-compat, and LOG each one.
    $primaryCandidates = @(
        (Join-Path $Config.MT5DataDir ("{0}.htm"  -f $ReportBaseName)),
        (Join-Path $Config.MT5DataDir ("{0}.html" -f $ReportBaseName)),
        # Legacy: older harness assumed the data root via ..\..\ from Experts.
        (Join-Path $ExpertsDir ("..\..\{0}.htm"  -f $ReportBaseName)),
        (Join-Path $ExpertsDir ("..\..\{0}.html" -f $ReportBaseName)),
        (Join-Path $ExpertsDir ("..\..\{0}"      -f $ReportBaseName))
    ) | Select-Object -Unique

    $found = $null
    foreach ($c in $primaryCandidates) {
        Write-Log ("  checking: {0}" -f $c)
        if (Test-Path -LiteralPath $c -PathType Leaf) {
            # Warn (but still accept) if this happy-path candidate predates the
            # launch - on a same-day rerun that wrote no new report it could be
            # a stale prior report with the same name masking a stall.
            if ($runStart) {
                $lwt = (Get-Item -LiteralPath $c).LastWriteTime
                if ($lwt -lt $runStart) {
                    Write-Log ("  WARNING: matched report predates this run's launch ({0} < {1}) - it may be a STALE report from an earlier same-day run, not fresh output. Check the tester log if you expected new results." -f $lwt, $runStart) 'WARN'
                }
            }
            $found = $c; break
        }
    }

    # No explicit candidate hit: do a RECURSIVE search under MT5DataDir. Prefer
    # an exact BaseName match on $ReportBaseName; otherwise fall back to any
    # *.htm/*.html written since we launched terminal64 ($runStart).
    if (-not $found) {
        Write-Log "  no explicit candidate matched; searching recursively under MT5DataDir." 'WARN'
        # Scope the recursion to the data root plus the folders MT5 actually
        # writes reports/artifacts into (data root itself, Tester, MQL5\Files,
        # reports) rather than the ENTIRE data tree - a real install carries
        # large bases\ (tick history) and Tester cache subtrees whose full
        # recursive walk would make this failure-path diagnostic slow and
        # I/O-heavy. -Depth caps how deep each search root is walked.
        $searchRoots = @(
            $Config.MT5DataDir,
            (Join-Path $Config.MT5DataDir 'Tester'),
            (Join-Path $Config.MT5DataDir 'MQL5\Files'),
            (Join-Path $Config.MT5DataDir 'reports')
        ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -Unique
        $all = @()
        foreach ($root in $searchRoots) {
            $all += Get-ChildItem -LiteralPath $root -Recurse -Depth 3 -Include *.htm, *.html -File -ErrorAction SilentlyContinue
        }
        $all = $all | Sort-Object FullName -Unique

        # (1) exact base-name match, but only if the file was written since we
        # launched terminal64 - otherwise a same-day rerun that wrote NO new
        # report could silently re-adopt a stale prior report with the same
        # roundNN_YYYYMMDD name and mask the stall as a false success.
        foreach ($f in $all) {
            if ($f.BaseName -ieq $ReportBaseName) {
                if ($runStart -and $f.LastWriteTime -ge $runStart) {
                    Write-Log ("  candidate (exact base-name match, fresh): {0}  [LastWriteTime {1}]" -f $f.FullName, $f.LastWriteTime)
                    $found = $f.FullName
                    break
                } else {
                    Write-Log ("  skipping stale exact base-name match (predates run start {0}): {1}  [LastWriteTime {2}]" -f $runStart, $f.FullName, $f.LastWriteTime) 'WARN'
                }
            }
        }

        # (2) looser fallback: newest *.htm/*.html written since the run started.
        if (-not $found -and $runStart) {
            $recent = $all |
                Where-Object { $_.LastWriteTime -ge $runStart } |
                Sort-Object LastWriteTime -Descending
            foreach ($f in $recent) {
                Write-Log ("  candidate (written since run start {0}): {1}  [LastWriteTime {2}]" -f $runStart, $f.FullName, $f.LastWriteTime)
            }
            if ($recent -and @($recent).Count -gt 0) {
                $found = @($recent)[0].FullName
                Write-Log ("  selected newest report written since run start: {0}" -f $found)
            } else {
                Write-Log "  no *.htm/*.html was written under MT5DataDir since the run started." 'WARN'
            }
        }
    }

    if (-not $found) {
        # Self-diagnosing failure: surface the newest tester log before failing.
        Write-Log "No report file was produced by MT5. Tailing the newest tester log:" 'ERROR'
        Write-NewestTesterLogTail -Mt5DataDir $Config.MT5DataDir
        Fail (("report not found. Primary candidates checked: {0}. " -f ($primaryCandidates -join '  |  ')) +
              "MT5 exited without writing a report - most often the tester pass never actually STARTED. " +
              "Confirm XAUUSD M1 real-tick history for 2026.03.01-2026.09.11 is downloaded (Model=4 needs it), " +
              "try the Model=1 diagnostic fallback (SETUP.md section 5), and check the tester log guidance in SETUP.md section 10.")
    }

    # Normalize .htm -> .html on copy (analyzer reads HTML by content).
    Copy-Item -LiteralPath $found -Destination $FinalReport -Force
    Write-Log ("Report {0} -> {1}" -f $found, $FinalReport)
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
            throw "git add of reports/$ReportBaseName.html failed (exit $addCode); is it ignored by .gitignore? (see SETUP.md section 10)."
        }
        $summaryRel = "reports/$ReportBaseName.summary.json"
        if (Test-Path -LiteralPath (Join-Path $Config.RepoDir $summaryRel)) {
            $addSumCode = Invoke-Git @('add', '--', $summaryRel)
            if ($addSumCode -ne 0) {
                throw "git add of $summaryRel failed (exit $addSumCode). It exists but git refused to stage it, most likely an .gitignore rule shadows reports/*.summary.json; ensure the '!reports/round*.summary.json' negation is present (see SETUP.md section 10)."
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
                throw "git push failed (exit $pushCode; check auth / credential helper - SETUP.md section 10)."
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
Write-Log "Reminder: sanity-check this round by hand (see SETUP.md section 11) to avoid overfitting; goal is under 15% drawdown on XAUUSD."
exit 0
