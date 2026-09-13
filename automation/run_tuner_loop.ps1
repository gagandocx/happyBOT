<#
================================================================================
 GaganEA - CONTINUOUS auto-tuner loop  (run_tuner_loop.ps1)
================================================================================
 Runs, hands-off and BACK-TO-BACK (no sleep gap), the full tune-and-backtest
 loop on YOUR local Windows PC. Each iteration:

   (a) git pull --ff-only the repo
   (b) copy GaganEA.mq5 into the MT5 MQL5\Experts folder. The params in the EA
       were written by the PREVIOUS iteration's tuner call (or, on the very
       first iteration, they are the committed defaults).
   (c) compile it headlessly with metaeditor64.exe and PARSE the compile log
       (the metaeditor exit code is unreliable across builds, so we do NOT
       trust it). On a compile FAILURE we log and `continue` to the next
       iteration instead of killing the whole loop.
   (d) generate a runtime tester .ini from backtest_template.ini and run
       terminal64.exe headlessly, WAITING for it to exit (ShutdownTerminal=1)
   (e) locate the HTML report MT5 wrote and copy it to
       reports\tuner\iterNNNN.html  (NNNN is the zero-padded iteration index
       read from automation\tuner\tuner_state.json so it is restart-safe; see
       the "ITERATION INDEXING" note below)
   (f) run tools\analyze_report.py on it to produce iterNNNN.summary.json
   (g) invoke the tuner: it ingests THIS result, updates state/best, and writes
       the NEXT params into GaganEA.mq5 (ready for the next iteration's compile).
       If the tuner exits non-zero the state counter is NOT bumped, so this
       cycle's report is renamed iterNNNN_notuned_<stamp> before commit so the
       next cycle's reused iter index cannot overwrite it (see step (g) body).
   (h) prune old full HTMLs beyond the retention cap (keep every .summary.json)
   (i) git add / commit / push the report + summary + tuner_state.json +
       current_params.json + GaganEA.mq5, gracefully skipping when nothing
       changed
   then loop IMMEDIATELY (no Start-Sleep).

 A per-STEP failure logs a WARN/ERROR and `continue`s to the next iteration so
 one bad backtest never stops the grind. Only a fatal CONFIGURATION error exits.

 --------------------------------------------------------------------------
 ITERATION INDEXING (restart-safe):
 tuner_state.json holds "iteration" = the number of results already ingested.
 The tuner BUMPS that counter to N+1 when it ingests the report produced this
 cycle. So at the TOP of a cycle we read the state counter N and name this
 cycle's report iter(N+1) - the same index the tuner will stamp on the history
 record for this result. That makes reports\tuner\iterNNNN.html map 1:1 to the
 tuner history record with iteration=NNNN and to the params that produced it.
 If the state file is missing (first-ever run) we treat the counter as 0, so
 the first report is iter0001. Reading the counter from the tracked state file
 (not an in-memory variable) is what makes the naming survive restarts.
 --------------------------------------------------------------------------

 --------------------------------------------------------------------------
 AUTHORED IN A LINUX SANDBOX - NOT EXECUTED THERE.
 There is no MT5, no MQL5 compiler, and no PowerShell in the authoring
 sandbox, so this script has NOT been run end-to-end. Do a careful FIRST
 MANUAL RUN on your PC - and, as automation\tuner\README.md recommends
 STRONGLY, run ONE manual tuner iteration (a single backtest + one
 tuner.py invocation) before you start this infinite loop. See
 automation\SETUP.md and automation\tuner\README.md.
 --------------------------------------------------------------------------

 Requires Windows PowerShell 5.1+ (ships with Windows) or PowerShell 7.
 No secrets are read, printed, or logged by this script, and it never dumps
 environment variables.

 Usage:
   .\run_tuner_loop.ps1                 # run forever until you close/Ctrl+C it
   .\run_tuner_loop.ps1 -MaxIterations 50   # stop after 50 cycles (0 = forever)
   .\run_tuner_loop.ps1 -TunerHtmlKeep 30   # keep the newest 30 full HTMLs
   (or double-click run_tuner_loop.bat)

 STOP it by: closing the window, pressing Ctrl+C, or ending the scheduled task.
================================================================================
#>

[CmdletBinding()]
param(
    # Safety cap on the number of cycles. 0 (default) means run forever.
    [int]$MaxIterations = 0,

    # How many full iterNNNN.html reports to KEEP in the repo (newest N). Older
    # ones are git-rm'd each cycle. Every .summary.json is ALWAYS kept.
    [int]$TunerHtmlKeep = 20
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
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir      = Join-Path $ScriptDir 'logs'
$TemplateIni = Join-Path $ScriptDir 'backtest_template.ini'

if (-not (Test-Path -LiteralPath $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$LoopStamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$LogFile   = Join-Path $LogDir ("tuner_loop_{0}.log" -f $LoopStamp)

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

# Fatal-config-only exit. Per-iteration failures use `continue`, NOT Fail.
function Fail {
    param([string]$Message)
    Write-Log $Message 'ERROR'
    Write-Log ("Aborting the loop. Full log: {0}" -f $LogFile) 'ERROR'
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
# stderr into a TERMINATING error and abort even though git actually succeeded.
# To avoid that we temporarily set $ErrorActionPreference to 'Continue' for the
# duration of the git call, merge stderr into stdout for logging, and then judge
# the outcome purely by $LASTEXITCODE. Returns the git exit code.
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

# ------------------------------------------------------------------------------
# Read the current iteration counter from tuner_state.json. Returns 0 if the
# file is missing or unreadable (first-ever run). This is what makes the report
# naming restart-safe: the counter lives in the tracked state file, not memory.
# ------------------------------------------------------------------------------
function Get-TunerIteration {
    param([Parameter(Mandatory)] [string]$StatePath)
    if (-not (Test-Path -LiteralPath $StatePath)) {
        return 0
    }
    try {
        $raw = Get-Content -LiteralPath $StatePath -Raw
        if ([string]::IsNullOrWhiteSpace($raw)) { return 0 }
        $obj = $raw | ConvertFrom-Json
        if ($null -ne $obj -and $null -ne $obj.iteration) {
            return [int]$obj.iteration
        }
        return 0
    } catch {
        Write-Log ("could not read iteration from {0} (treating as 0): {1}" -f $StatePath, $_.Exception.Message) 'WARN'
        return 0
    }
}

# ------------------------------------------------------------------------------
# Resolve a python launcher once. Returns the executable path or $null.
# ------------------------------------------------------------------------------
function Resolve-Python {
    foreach ($cand in @('python', 'python3', 'py')) {
        $cmd = Get-Command $cand -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

Write-Log ("=== GaganEA CONTINUOUS auto-tuner loop starting (MaxIterations={0}, TunerHtmlKeep={1}) ===" -f $MaxIterations, $TunerHtmlKeep) 'STEP'
Write-Log ("Log file: {0}" -f $LogFile)
Write-Log "Stop with: close the window, Ctrl+C, or end the scheduled task."

# --- Sanity-check the configuration ONCE before entering the loop. ------------
try {
    $ExpertsDir = Join-Path $Config.MT5DataDir $Config.ExpertsSubDir
    $ReportsDir = Join-Path $Config.RepoDir 'reports'
    $TunerDir   = Join-Path $ReportsDir 'tuner'
    $StatePath  = Join-Path $Config.RepoDir 'automation\tuner\tuner_state.json'
    $CurrentParamsPath = Join-Path $Config.RepoDir 'automation\tuner\current_params.json'
    $TunerScript = Join-Path $Config.RepoDir 'automation\tuner\tuner.py'
    $Analyzer    = Join-Path $Config.RepoDir 'tools\analyze_report.py'

    foreach ($pair in @(
            @{ n = 'MetaEditor64Exe'; v = $Config.MetaEditor64Exe },
            @{ n = 'Terminal64Exe';   v = $Config.Terminal64Exe },
            @{ n = 'RepoDir';         v = $Config.RepoDir },
            @{ n = 'MT5 Experts dir'; v = $ExpertsDir },
            @{ n = 'backtest_template.ini'; v = $TemplateIni },
            @{ n = 'tuner.py';        v = $TunerScript }
        )) {
        if (-not (Test-Path -LiteralPath $pair.v)) {
            throw ("{0} not found: {1}  (fix the CONFIGURATION BLOCK / SETUP.md)" -f $pair.n, $pair.v)
        }
    }

    $Python = Resolve-Python
    if (-not $Python) {
        throw "Python not found on PATH. The tuner requires Python 3 (install it and re-run). See automation\tuner\README.md."
    }
    Write-Log ("Using python: {0}" -f $Python)
} catch {
    Fail ("Configuration check failed: {0}" -f $_.Exception.Message)
}

# ==============================================================================
# ==============================  THE CONTINUOUS LOOP  =========================
# ==============================================================================
$ExpertMq5InRepo = Join-Path $Config.RepoDir 'GaganEA.mq5'
$ExpertMq5InMt5  = Join-Path $ExpertsDir ("{0}.mq5" -f $Config.ExpertName)
$LoopCount = 0

while ($true) {

    $LoopCount++
    if ($MaxIterations -gt 0 -and $LoopCount -gt $MaxIterations) {
        Write-Log ("Reached MaxIterations ({0}); stopping cleanly." -f $MaxIterations) 'STEP'
        break
    }

    # This cycle's report index = current state counter + 1 (the index the tuner
    # will stamp when it ingests THIS report). See ITERATION INDEXING above.
    $StateIter = Get-TunerIteration -StatePath $StatePath
    $IterIndex = $StateIter + 1
    $IterTag   = 'iter{0:D4}' -f $IterIndex
    $IterStamp = Get-Date -Format 'yyyyMMdd_HHmmss'

    Write-Log ("===== CYCLE {0}: {1} (state iteration={2}) =====" -f $LoopCount, $IterTag, $StateIter) 'STEP'

    try {
        # ----------------------------------------------------------------------
        # STEP (a) - git pull --ff-only
        # ----------------------------------------------------------------------
        Write-Log "STEP (a) git pull --ff-only" 'STEP'
        Push-Location -LiteralPath $Config.RepoDir
        try {
            $coCode = Invoke-Git @('checkout', $Config.GitBranch)
            if ($coCode -ne 0) {
                Write-Log ("git checkout {0} failed (exit {1}); skipping this cycle." -f $Config.GitBranch, $coCode) 'WARN'
                continue
            }
            $pullCode = Invoke-Git @('pull', '--ff-only', 'origin', $Config.GitBranch)
            if ($pullCode -ne 0) {
                Write-Log "git pull returned non-zero; continuing with the local checkout." 'WARN'
            }
        } finally {
            Pop-Location
        }

        # ----------------------------------------------------------------------
        # STEP (b) - copy the EA source into MT5's MQL5\Experts
        # The params in GaganEA.mq5 were written by the PREVIOUS cycle's tuner
        # (or are the committed defaults on the first cycle).
        # ----------------------------------------------------------------------
        Write-Log "STEP (b) copy EA into MT5 Experts folder" 'STEP'
        if (-not (Test-Path -LiteralPath $ExpertMq5InRepo)) {
            Write-Log ("GaganEA.mq5 not found in repo: {0}; skipping this cycle." -f $ExpertMq5InRepo) 'WARN'
            continue
        }
        Copy-Item -LiteralPath $ExpertMq5InRepo -Destination $ExpertMq5InMt5 -Force
        Write-Log ("Copied {0} -> {1}" -f $ExpertMq5InRepo, $ExpertMq5InMt5)

        # ----------------------------------------------------------------------
        # STEP (c) - headless compile + PARSE the log (exit code is unreliable).
        # On a compile failure we log and `continue` rather than kill the loop.
        # ----------------------------------------------------------------------
        Write-Log "STEP (c) compile EA with metaeditor64.exe" 'STEP'
        $CompileLog = Join-Path $LogDir ("compile_{0}_{1}.log" -f $IterTag, $IterStamp)
        $null = Invoke-AndWait -FilePath $Config.MetaEditor64Exe -Arguments @(
            ("/compile:{0}" -f $ExpertMq5InMt5),
            ("/log:{0}"     -f $CompileLog)
        )
        Start-Sleep -Milliseconds 500
        if (-not (Test-Path -LiteralPath $CompileLog)) {
            Write-Log ("compile log was not produced: {0}; skipping this cycle." -f $CompileLog) 'WARN'
            continue
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

        # A clean build reports "0 errors". Any "N error(s)" with N>0, or an
        # explicit MetaEditor per-error line "(line,col) : error", means the
        # build failed. We anchor on the "(line,col) : error" marker so a
        # source/report PATH that merely contains ": error " cannot
        # false-positive. We do NOT match a bare ": error " anywhere.
        $errorCount = $null
        $m = [regex]::Match($logText, '(?im)(\d+)\s+error')
        if ($m.Success) { $errorCount = [int]$m.Groups[1].Value }
        $hasErrorLine = [regex]::IsMatch($logText, '(?im)\(\d+,\d+\)\s*:\s*error\s')

        if (($errorCount -ne $null -and $errorCount -gt 0) -or $hasErrorLine) {
            Write-Log ("compile reported errors (see {0}); skipping this cycle. params.py should guarantee valid inputs - inspect the log if this recurs." -f $CompileLog) 'ERROR'
            continue
        }
        Write-Log "Compile OK (no errors found in log)."

        # ----------------------------------------------------------------------
        # STEP (d) - generate runtime .ini and run terminal64 headlessly, WAIT.
        # ----------------------------------------------------------------------
        Write-Log "STEP (d) generate runtime tester .ini and run terminal64" 'STEP'
        $RuntimeIni = Join-Path $LogDir ("tester_{0}_{1}.ini" -f $IterTag, $IterStamp)
        $tpl = Get-Content -LiteralPath $TemplateIni -Raw
        $tpl = $tpl.Replace('__EXPERT_PATH__', $Config.ExpertName)
        $tpl = $tpl.Replace('__REPORT_NAME__', $IterTag)
        Set-Content -LiteralPath $RuntimeIni -Value $tpl -Encoding ASCII
        Write-Log ("Runtime ini: {0}" -f $RuntimeIni)
        Write-Log ("Report base name: {0} - MT5 writes it (as .htm/.html) under the data-folder root: {1}" -f $IterTag, $Config.MT5DataDir)

        $runStart = Get-Date
        $code = Invoke-AndWait -FilePath $Config.Terminal64Exe `
                               -Arguments @(("/config:{0}" -f $RuntimeIni)) `
                               -TimeoutSec $Config.TesterTimeoutSec
        Write-Log ("terminal64 exited (code {0}). ShutdownTerminal=1 self-terminates it." -f $code)

        # ----------------------------------------------------------------------
        # STEP (e) - locate the report and copy it to reports\tuner\iterNNNN.html
        # ----------------------------------------------------------------------
        Write-Log "STEP (e) locate + copy the report" 'STEP'
        if (-not (Test-Path -LiteralPath $TunerDir)) {
            New-Item -ItemType Directory -Path $TunerDir -Force | Out-Null
        }
        $FinalReport = Join-Path $TunerDir ("{0}.html" -f $IterTag)

        # On build 6191 MT5 writes the report (bare Report= name) RELATIVE TO THE
        # DATA-FOLDER ROOT, typically as <base>.htm and on some builds <base>.html.
        $primaryCandidates = @(
            (Join-Path $Config.MT5DataDir ("{0}.htm"  -f $IterTag)),
            (Join-Path $Config.MT5DataDir ("{0}.html" -f $IterTag)),
            (Join-Path $ExpertsDir ("..\..\{0}.htm"  -f $IterTag)),
            (Join-Path $ExpertsDir ("..\..\{0}.html" -f $IterTag)),
            (Join-Path $ExpertsDir ("..\..\{0}"      -f $IterTag))
        ) | Select-Object -Unique

        $found = $null
        foreach ($c in $primaryCandidates) {
            Write-Log ("  checking: {0}" -f $c)
            if (Test-Path -LiteralPath $c -PathType Leaf) {
                $lwt = (Get-Item -LiteralPath $c).LastWriteTime
                if ($lwt -lt $runStart) {
                    Write-Log ("  WARNING: matched report predates this run's launch ({0} < {1}) - it may be STALE, not fresh output. Check the tester log if you expected new results." -f $lwt, $runStart) 'WARN'
                }
                $found = $c; break
            }
        }

        if (-not $found) {
            Write-Log "  no explicit candidate matched; searching recursively under MT5DataDir." 'WARN'
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

            foreach ($f in $all) {
                if ($f.BaseName -ieq $IterTag) {
                    if ($f.LastWriteTime -ge $runStart) {
                        Write-Log ("  candidate (exact base-name match, fresh): {0}  [LastWriteTime {1}]" -f $f.FullName, $f.LastWriteTime)
                        $found = $f.FullName
                        break
                    } else {
                        Write-Log ("  skipping stale exact base-name match (predates run start {0}): {1}  [LastWriteTime {2}]" -f $runStart, $f.FullName, $f.LastWriteTime) 'WARN'
                    }
                }
            }

            if (-not $found) {
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
            Write-Log "No report file was produced by MT5. Tailing the newest tester log:" 'ERROR'
            Write-NewestTesterLogTail -Mt5DataDir $Config.MT5DataDir
            Write-Log ("report not found for {0}; skipping the tuner call this cycle. Confirm XAUUSD M1 real-tick history for the tester window is downloaded (Model=4 needs it) and see SETUP.md sections 5 and 10." -f $IterTag) 'ERROR'
            continue
        }

        # Normalize .htm -> .html on copy (analyzer reads HTML by content).
        Copy-Item -LiteralPath $found -Destination $FinalReport -Force
        Write-Log ("Report {0} -> {1}" -f $found, $FinalReport)

        # ----------------------------------------------------------------------
        # STEP (f) - analyze the report to produce iterNNNN.summary.json alongside
        # ----------------------------------------------------------------------
        Write-Log "STEP (f) analyze report -> summary.json" 'STEP'
        $SummaryJson = Join-Path $TunerDir ("{0}.summary.json" -f $IterTag)
        if (-not (Test-Path -LiteralPath $Analyzer)) {
            Write-Log ("analyzer {0} not found; skipping analysis + tuner this cycle." -f $Analyzer) 'WARN'
            continue
        }
        $analyzeCode = 0
        Push-Location -LiteralPath $Config.RepoDir
        try {
            & $Python 'tools\analyze_report.py' $FinalReport 2>&1 | ForEach-Object { Write-Log ("  analyze: {0}" -f $_) }
            $analyzeCode = $LASTEXITCODE
        } finally {
            # `continue` inside a try runs this finally FIRST, so popping here
            # keeps the location stack balanced on both the normal and skip paths.
            Pop-Location
        }
        if ($analyzeCode -ne 0) {
            Write-Log ("analyzer exited non-zero ({0}); skipping the tuner call this cycle." -f $analyzeCode) 'WARN'
            continue
        }
        if (-not (Test-Path -LiteralPath $SummaryJson)) {
            Write-Log ("expected summary not produced: {0}; skipping the tuner call this cycle." -f $SummaryJson) 'WARN'
            continue
        }

        # ----------------------------------------------------------------------
        # STEP (g) - invoke the tuner: ingest THIS result, update state/best,
        # and write the NEXT params into GaganEA.mq5 (ready for next compile).
        # ----------------------------------------------------------------------
        Write-Log "STEP (g) invoke the auto-tuner" 'STEP'
        Push-Location -LiteralPath $Config.RepoDir
        try {
            & $Python 'automation\tuner\tuner.py' `
                '--summary-json' $SummaryJson `
                '--state'        $StatePath `
                '--mq5'          $ExpertMq5InRepo 2>&1 | ForEach-Object { Write-Log ("  tuner: {0}" -f $_) }
            $tunerCode = $LASTEXITCODE
        } finally {
            Pop-Location
        }
        # The committed report name defaults to this cycle's iterNNNN. But the
        # iteration counter in tuner_state.json is bumped ONLY when the tuner
        # ingests successfully; on a tuner FAILURE the counter stays at N, so the
        # NEXT cycle would recompute the SAME iter(N+1) index and OVERWRITE the
        # HTML + summary we are about to commit here. To keep a tuner-failed
        # cycle's artifact from being silently clobbered, rename it to a distinct
        # iterNNNN_notuned_<stamp> name (both the .html and its .summary.json)
        # before we prune/commit, and commit under that name instead.
        $CommitReport  = $FinalReport
        $CommitSummary = $SummaryJson
        $CommitHtmlRel    = "reports/tuner/$IterTag.html"
        $CommitSummaryRel = "reports/tuner/$IterTag.summary.json"
        if ($tunerCode -ne 0) {
            Write-Log ("tuner exited non-zero ({0}); it did NOT write new params and did NOT bump the state counter, so iter{1} would be reused next cycle. Renaming this cycle's report with a _notuned suffix so it is not overwritten, then continuing." -f $tunerCode, ('{0:D4}' -f $IterIndex)) 'WARN'
            $NoTuneTag  = '{0}_notuned_{1}' -f $IterTag, $IterStamp
            $AltReport  = Join-Path $TunerDir ("{0}.html" -f $NoTuneTag)
            $AltSummary = Join-Path $TunerDir ("{0}.summary.json" -f $NoTuneTag)
            try {
                if (Test-Path -LiteralPath $FinalReport) {
                    Move-Item -LiteralPath $FinalReport -Destination $AltReport -Force
                    $CommitReport = $AltReport
                    $CommitHtmlRel = "reports/tuner/$NoTuneTag.html"
                }
                if (Test-Path -LiteralPath $SummaryJson) {
                    Move-Item -LiteralPath $SummaryJson -Destination $AltSummary -Force
                    $CommitSummary = $AltSummary
                    $CommitSummaryRel = "reports/tuner/$NoTuneTag.summary.json"
                }
                Write-Log ("renamed tuner-failed report to {0} (+ .summary.json) so the reused iter index does not overwrite it." -f $NoTuneTag) 'WARN'
            } catch {
                Write-Log ("could not rename tuner-failed report (committing under original name; it MAY be overwritten next cycle): {0}" -f $_.Exception.Message) 'WARN'
            }
        } else {
            Write-Log "tuner OK: ingested result, updated state, wrote next params into GaganEA.mq5."
        }

        # ----------------------------------------------------------------------
        # STEP (h) - prune old full HTMLs beyond the retention cap. Keep the
        # newest $TunerHtmlKeep iter*.html; git rm the rest. Every .summary.json
        # is ALWAYS kept (they are tiny and are the permanent history).
        # ----------------------------------------------------------------------
        Write-Log ("STEP (h) prune old full HTMLs (keep newest {0})" -f $TunerHtmlKeep) 'STEP'
        if ($TunerHtmlKeep -gt 0) {
            $htmls = Get-ChildItem -LiteralPath $TunerDir -Filter 'iter*.html' -File -ErrorAction SilentlyContinue |
                     Sort-Object Name -Descending
            if ($htmls -and @($htmls).Count -gt $TunerHtmlKeep) {
                $toPrune = @($htmls) | Select-Object -Skip $TunerHtmlKeep
                Push-Location -LiteralPath $Config.RepoDir
                try {
                    foreach ($old in $toPrune) {
                        $rel = "reports/tuner/$($old.Name)"
                        $rmCode = Invoke-Git @('rm', '-q', '--ignore-unmatch', '--', $rel)
                        if ($rmCode -ne 0) {
                            # Not yet tracked (never committed): just delete it.
                            Remove-Item -LiteralPath $old.FullName -Force -ErrorAction SilentlyContinue
                            Write-Log ("  pruned untracked HTML: {0}" -f $rel)
                        } else {
                            Write-Log ("  pruned (git rm) old HTML: {0}" -f $rel)
                        }
                    }
                } finally {
                    Pop-Location
                }
            } else {
                Write-Log "  nothing to prune."
            }
        }

        # ----------------------------------------------------------------------
        # STEP (i) - git add / commit / push this cycle's artifacts.
        # Staged set: the iter HTML + its summary + tuner_state.json +
        # current_params.json + GaganEA.mq5 (plus any HTML git-rm'd above).
        # ----------------------------------------------------------------------
        Write-Log "STEP (i) git add / commit / push" 'STEP'
        Push-Location -LiteralPath $Config.RepoDir
        try {
            # Use the (possibly _notuned-renamed) report paths so a tuner-failed
            # cycle commits its distinct artifact instead of the reusable
            # iterNNNN name. On the success path these are the plain iterNNNN.
            $addTargets = @(
                $CommitHtmlRel,
                $CommitSummaryRel,
                "automation/tuner/tuner_state.json",
                "automation/tuner/current_params.json",
                "GaganEA.mq5"
            )
            $addOk = $true
            foreach ($t in $addTargets) {
                if (Test-Path -LiteralPath (Join-Path $Config.RepoDir $t)) {
                    $addCode = Invoke-Git @('add', '--', $t)
                    if ($addCode -ne 0) {
                        Write-Log ("git add of {0} failed (exit {1}); is it ignored by .gitignore? (see automation\tuner\README.md / SETUP.md)." -f $t, $addCode) 'ERROR'
                        $addOk = $false
                    }
                } else {
                    Write-Log ("  skip add (not present): {0}" -f $t) 'WARN'
                }
            }
            if (-not $addOk) {
                Write-Log "one or more git add calls failed; skipping commit/push this cycle." 'WARN'
            } else {
                $staged = & git diff --cached --name-only
                if ([string]::IsNullOrWhiteSpace(($staged -join ''))) {
                    Write-Log "Nothing changed to commit - skipping commit/push." 'WARN'
                } else {
                    $msg = "Tuner {0}: backtest report + next params" -f $IterTag
                    $commitCode = Invoke-Git @('commit', '-m', $msg)
                    if ($commitCode -ne 0) {
                        Write-Log ("git commit failed (exit {0}; see log); skipping push this cycle." -f $commitCode) 'ERROR'
                    } else {
                        $pushCode = Invoke-Git @('push', 'origin', $Config.GitBranch)
                        if ($pushCode -ne 0) {
                            Write-Log ("git push failed (exit {0}; check auth / credential helper - SETUP.md section 10)." -f $pushCode) 'ERROR'
                        } else {
                            Write-Log ("Committed + pushed: {0}" -f $msg)
                        }
                    }
                }
            }
        } finally {
            Pop-Location
        }

        Write-Log ("===== CYCLE {0} done: {1}. Report: {2} =====" -f $LoopCount, $IterTag, $CommitReport) 'STEP'

    } catch {
        # Any unexpected per-cycle error: log and continue to the next cycle so
        # one bad iteration never kills the continuous grind.
        Write-Log ("cycle {0} ({1}) raised an error (continuing to next cycle): {2}" -f $LoopCount, $IterTag, $_.Exception.Message) 'ERROR'
        # Drain any locations this cycle may have pushed but not popped, so the
        # next cycle starts from a clean location stack. Each inner block above
        # pops in its own finally, so this is normally a no-op safety net; the
        # bounded loop + break-on-error stops when the stack is empty.
        for ($popGuard = 0; $popGuard -lt 8; $popGuard++) {
            try { Pop-Location -ErrorAction Stop } catch { break }
        }
        continue
    }
}

Write-Log "=== Auto-tuner loop stopped. ===" 'STEP'
Write-Log "Reminder: periodically VALIDATE the current best on the FULL 6-month window (FromDate=2026.03.01) - continuous tuning on the ~1-month window overfits. See automation\tuner\README.md."
exit 0
