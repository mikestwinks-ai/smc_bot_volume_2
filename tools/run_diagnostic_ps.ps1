# Controlled startup diagnostic (timestamps only)
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$log = Join-Path $root "logs\startup_diagnostic_trace.log"
if (-not (Test-Path "logs")) { New-Item -ItemType Directory -Path "logs" | Out-Null }

function Write-Ts([string]$msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"
    $line = "[$ts] $msg"
    Write-Host $line
    Add-Content -Path $log -Value $line -Encoding UTF8
}

Add-Content $log -Value ""
Write-Ts "======== STARTUP DIAGNOSTIC (PowerShell) ========"
Write-Ts ("STEP 0 | cwd = " + (Get-Location))

Write-Ts "STEP 1 | python --version (system PATH)"
& python --version 2>&1 | ForEach-Object { Write-Ts ("  " + $_) }

Write-Ts "STEP 2 | before venv activate"
if (Test-Path "venv\Scripts\Activate.ps1") {
    Write-Ts "  [INFO] Activating virtual environment..."
    & "venv\Scripts\Activate.ps1"
    $pyCmd = (Get-Command python -ErrorAction SilentlyContinue).Source
    Write-Ts ("STEP 3 | after venv activate | python=" + $pyCmd)
}
else {
    Write-Ts "STEP 3 | no Activate.ps1; using venv\Scripts\python.exe"
}

Write-Ts "STEP 4 | before python main.py"
Write-Ts "  SMC Trading Bot - Starting (diagnostic banner)"

$py = Join-Path $root "venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

Write-Ts ("STEP 5 | launching: " + $py + " -u main.py (60s max)")
$outFile = Join-Path $root "logs\diagnostic_main_stdout.tmp"
$job = Start-Job -ScriptBlock {
    param($exe, $dir, $out)
    Set-Location $dir
    & $exe -u main.py 2>&1 | Tee-Object -FilePath $out
} -ArgumentList $py, $root, $outFile

$deadline = (Get-Date).AddSeconds(60)
$sawFirst = $false
$sawAfterMt5 = $false
while ((Get-Date) -lt $deadline) {
    if (Test-Path $outFile) {
        $lines = Get-Content $outFile -ErrorAction SilentlyContinue
        foreach ($ln in $lines) {
            if (-not $sawFirst -and $ln.Trim()) {
                Write-Ts "STEP 5a | first Python stdout line"
                Write-Ts ("  STDOUT: " + $ln)
                $sawFirst = $true
            }
            if ($ln -match "\[TRACE\]") {
                Write-Ts ("  STDOUT: " + $ln)
            }
            if ($ln -match "after MT5 connect") { $sawAfterMt5 = $true }
        }
        if ($sawAfterMt5) { break }
    }
    if ($job.State -eq "Completed" -or $job.State -eq "Failed") { break }
    Start-Sleep -Milliseconds 250
}

if ($job.State -eq "Running") {
    Write-Ts "STEP 5b | stopping job after 60s window"
    Stop-Job $job
    Remove-Job $job -Force
}
else {
    Receive-Job $job | Out-Null
    Remove-Job $job -Force
}

if (Test-Path $outFile) {
    Get-Content $outFile | ForEach-Object {
        if ($_ -match "\[TRACE\]") { }
    }
}

Write-Ts "STEP 6 | capture window ended"
Write-Ts "DIAGNOSTIC POWERSHELL COMPLETE"
