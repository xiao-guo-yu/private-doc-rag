param(
    [int]$Port = 8010
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$healthUrl = "http://127.0.0.1:$Port/api/health"
$appUrl = "http://127.0.0.1:$Port/"
$logDir = Join-Path $root "data"
$stdoutLog = Join-Path $logDir "server.out.log"
$stderrLog = Join-Path $logDir "server.err.log"

Set-Location $root
New-Item -ItemType Directory -Force $logDir | Out-Null

function Test-AppHealth {
    try {
        $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 1
        return $response.status -eq "ok"
    }
    catch {
        return $false
    }
}

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment is missing. Run: uv sync"
}

if (-not (Test-AppHealth)) {
    $process = Start-Process `
        -FilePath $python `
        -ArgumentList @(
            "-m", "uvicorn", "backend.app.main:app",
            "--host", "127.0.0.1",
            "--port", "$Port",
            "--log-level", "warning"
        ) `
        -WorkingDirectory $root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru

    Set-Content -LiteralPath (Join-Path $logDir "server.pid") -Value $process.Id

    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        Start-Sleep -Milliseconds 500
        if (Test-AppHealth) {
            $ready = $true
            break
        }
        if ($process.HasExited) {
            break
        }
    }

    if (-not $ready) {
        $details = @()
        if (Test-Path -LiteralPath $stderrLog) {
            $details += Get-Content -LiteralPath $stderrLog -Tail 40
        }
        if (Test-Path -LiteralPath $stdoutLog) {
            $details += Get-Content -LiteralPath $stdoutLog -Tail 40
        }
        throw "Pagewise server failed to start. Log: $stderrLog`n$($details -join [Environment]::NewLine)"
    }
}

Write-Host "Pagewise is ready: $appUrl"
try {
    Start-Process $appUrl
}
catch {
    Start-Process "msedge.exe" $appUrl
}
