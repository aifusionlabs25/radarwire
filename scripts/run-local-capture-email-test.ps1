param(
    [string]$Python = "python",
    [string]$Config = "config.pilot.hermes-placeholder-bounded-clean3-local-capture.yaml",
    [string]$RealConfig = "config.pilot.hermes-placeholder-bounded-clean3-email-test.yaml",
    [string]$RunId = "42915827efff",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 1025,
    [int]$TimeoutSeconds = 60,
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

if (Test-PortOpen -HostName $HostName -Port $Port) {
    throw "Refusing to start: $HostName`:$Port is already listening"
}

$prepArgs = @(
    "scripts/prepare_local_capture_scratch.py",
    "--source-config", $Config,
    "--run-id", $RunId,
    "--scratch-root", $ScratchRoot,
    "--host", $HostName,
    "--port", "$Port"
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

$proc = Start-Process -FilePath $Python -ArgumentList $captureArgs -PassThru -NoNewWindow -RedirectStandardOutput $captureLog -RedirectStandardError $captureErr
try {
    Wait-PortOpen -HostName $HostName -Port $Port -Seconds 10

    & $Python -m radar.cli deliver-report --config $sendConfig --run-id $RunId --send
    if ($LASTEXITCODE -ne 0) {
        throw "deliver-report exited with code $LASTEXITCODE"
    }

    if (-not $proc.WaitForExit(($TimeoutSeconds + 10) * 1000)) {
        Stop-Process -Id $proc.Id -Force
        throw "Capture helper did not exit; stopped child process $($proc.Id)"
    }
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
        Stop-Process -Id $proc.Id -Force
    }
    Assert-PortFree -HostName $HostName -Port $Port
}
