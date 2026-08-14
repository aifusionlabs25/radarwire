param(
    [string]$Python = "python",
    [string]$Config = "config.pilot.hermes-placeholder-bounded-clean3-local-capture.yaml",
    [string]$RealConfig = "config.pilot.hermes-placeholder-bounded-clean3-email-test.yaml",
    [string]$RunId = "42915827efff",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 1025,
    [int]$TimeoutSeconds = 60,
    [string]$ReportUrl = "https://site-export-preview.vercel.app/reports/1099fire-radar/",
    [string]$ScratchRoot = ".radar-data",
    [string]$Timestamp = ""
)

$ErrorActionPreference = "Stop"

function Test-PortOpen {
    param([string]$HostName, [int]$Port)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(300)) { return $false }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Wait-PortOpen {
    param([string]$HostName, [int]$Port, [int]$Seconds)
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortOpen -HostName $HostName -Port $Port) { return }
        Start-Sleep -Milliseconds 200
    }
    throw "Timed out waiting for $HostName`:$Port to listen"
}

function Assert-PortFree {
    param([string]$HostName, [int]$Port)
    if (Test-PortOpen -HostName $HostName -Port $Port) {
        throw "Port $HostName`:$Port is still listening after local capture test"
    }
}

function Start-CleanCaptureProcess {
    param([string]$FilePath, [string[]]$Arguments)
    $quoted = $Arguments | ForEach-Object { '"' + ([string]$_).Replace('"', '\"') + '"' }
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $FilePath
    $start.Arguments = $quoted -join ' '
    $start.WorkingDirectory = (Get-Location).Path
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $start
    if (-not $process.Start()) { throw 'Failed to start local SMTP capture helper.' }
    return $process
}

if (Test-PortOpen -HostName $HostName -Port $Port) {
    throw "Refusing to start: $HostName`:$Port is already listening"
}

$prepArgs = @(
    "scripts/prepare_local_capture_scratch.py",
    "--source-config", $Config,
    "--run-id", $RunId,
    "--scratch-root", $ScratchRoot,
    "--host", $HostName,
    "--port", "$Port",
    "--report-url", $ReportUrl
)
if ($Timestamp -ne "") {
    $prepArgs += @("--timestamp", $Timestamp)
}

$prepJson = & $Python @prepArgs
if ($LASTEXITCODE -ne 0) {
    throw "prepare_local_capture_scratch.py exited with code $LASTEXITCODE"
}
$prep = $prepJson | ConvertFrom-Json
$sendConfig = $prep.config_path
$outputDir = $prep.capture_output_dir
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
$captureLog = Join-Path $outputDir "$RunId.capture.stdout.log"
$captureErr = Join-Path $outputDir "$RunId.capture.stderr.log"

$captureArgs = @(
    "scripts/local_smtp_capture.py",
    "--host", $HostName,
    "--port", "$Port",
    "--run-id", $RunId,
    "--output-dir", $outputDir,
    "--timeout-seconds", "$TimeoutSeconds"
)

$proc = Start-CleanCaptureProcess -FilePath $Python -Arguments $captureArgs
try {
    Wait-PortOpen -HostName $HostName -Port $Port -Seconds 10

    & $Python -m radar.cli deliver-report --config $sendConfig --run-id $RunId --send
    if ($LASTEXITCODE -ne 0) {
        throw "deliver-report exited with code $LASTEXITCODE"
    }

    if (-not $proc.WaitForExit(($TimeoutSeconds + 10) * 1000)) {
        $proc.Kill()
        throw "Capture helper did not exit; stopped child process $($proc.Id)"
    }
    $proc.StandardOutput.ReadToEnd() | Set-Content -Path $captureLog -Encoding UTF8
    $proc.StandardError.ReadToEnd() | Set-Content -Path $captureErr -Encoding UTF8
    $proc.Refresh()
    $helperExitCode = $proc.ExitCode
    $captureMeta = Join-Path $outputDir "$RunId.json"
    if ($null -eq $helperExitCode -and (Test-Path $captureMeta)) {
        # Windows PowerShell can occasionally leave ExitCode null for a short-lived
        # redirected child even after WaitForExit(). Treat an already-written
        # capture metadata file as proof the helper completed its success path.
        $helperExitCode = 0
    }
    if ($helperExitCode -ne 0) {
        throw "Capture helper exited with code $helperExitCode"
    }

    Assert-PortFree -HostName $HostName -Port $Port

    & $Python -m radar.cli state-audit --config $sendConfig
    & $Python -m radar.cli state-audit --config $RealConfig
    Write-Output "local_capture_result=ok"
    Write-Output "scratch_config=$sendConfig"
    Write-Output "scratch_data_dir=$($prep.data_dir)"
    Write-Output "capture_log=$captureLog"
    Write-Output "capture_err=$captureErr"
} finally {
    if ($proc -and -not $proc.HasExited) {
        $proc.Kill()
    }
    Assert-PortFree -HostName $HostName -Port $Port
}
