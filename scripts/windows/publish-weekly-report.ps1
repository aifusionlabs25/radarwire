param(
  [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path,
  [string]$ConfigPath = "$ProjectRoot\config.pilot.local.yaml",
  [string]$PythonExe = $env:RADAR_PYTHON_EXE,
  [string]$VercelExe = $env:RADAR_VERCEL_EXE,
  [string]$SiteRoot = "$ProjectRoot\.radar-data\site-export-preview",
  [string]$RouteName = 'latest',
  [string]$HostedBaseUrl = 'https://site-export-preview.vercel.app',
  [string]$RunId,
  [switch]$NoDeploy,
  [switch]$ForceNewScan,
  [switch]$PlanOnly
)
$ErrorActionPreference = 'Stop'

function Resolve-Executable([string]$Configured, [string]$LocalCandidate, [string]$KnownCandidate, [string]$CommandName) {
  if (-not [string]::IsNullOrWhiteSpace($Configured)) {
    if (Test-Path $Configured) { return (Resolve-Path $Configured).Path }
    $ConfiguredCommand = Get-Command $Configured -ErrorAction SilentlyContinue
    if ($ConfiguredCommand) { return $ConfiguredCommand.Source }
    throw "$CommandName executable not found: $Configured"
  }
  if ($LocalCandidate -and (Test-Path $LocalCandidate)) { return (Resolve-Path $LocalCandidate).Path }
  if ($KnownCandidate -and (Test-Path $KnownCandidate)) { return (Resolve-Path $KnownCandidate).Path }
  $Discovered = Get-Command $CommandName -ErrorAction SilentlyContinue
  if ($Discovered) { return $Discovered.Source }
  throw "$CommandName executable could not be resolved."
}

function Save-PublishState([hashtable]$Payload) {
  $Payload.updated_at = [DateTime]::UtcNow.ToString('o')
  $Payload | ConvertTo-Json -Depth 8 | Set-Content -Path $StatePath -Encoding UTF8
}

function Invoke-RadarJson([string[]]$Arguments) {
  $Output = & $PythonExe @Arguments 2>&1 | Out-String
  $Code = $LASTEXITCODE
  if ($Code -ne 0) { throw "Radar command failed with exit code $Code.`n$Output" }
  return ($Output | ConvertFrom-Json)
}

function Invoke-NativeLogged([string]$Executable, [string[]]$Arguments, [string]$Log) {
  $PreviousPreference = $ErrorActionPreference
  try {
    # Several Windows CLI shims write normal progress banners to stderr.
    $ErrorActionPreference = 'Continue'
    & $Executable @Arguments *>> $Log
    return $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $PreviousPreference
  }
}

$ProjectRoot = (Resolve-Path $ProjectRoot).Path
if (-not [IO.Path]::IsPathRooted($ConfigPath)) { $ConfigPath = Join-Path $ProjectRoot $ConfigPath }
if (-not [IO.Path]::IsPathRooted($SiteRoot)) { $SiteRoot = Join-Path $ProjectRoot $SiteRoot }
if (-not (Test-Path $ConfigPath)) { throw "Config not found: $ConfigPath" }
if ($RouteName -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$') { throw 'RouteName must be one safe URL segment.' }

$PythonExe = Resolve-Executable $PythonExe "$ProjectRoot\.venv\Scripts\python.exe" 'C:\Users\AI Fusion Labs\AppData\Local\Programs\Python\Python311\python.exe' 'python'
$VercelExe = Resolve-Executable $VercelExe $null 'C:\Users\AI Fusion Labs\AppData\Roaming\npm\vercel.ps1' 'vercel'
$WorkerDir = Join-Path $ProjectRoot '.radar-data\weekly-publish'
$LogDir = Join-Path $WorkerDir 'logs'
$StatePath = Join-Path $WorkerDir 'state.json'
$MetadataPath = Join-Path $SiteRoot "reports\$RouteName\report-site.json"
$ReportUrl = $HostedBaseUrl.TrimEnd('/') + "/reports/$RouteName/"
$MetadataUrl = $ReportUrl + 'report-site.json'

if ($PlanOnly) {
  [ordered]@{
    status = 'plan_only'
    project_root = $ProjectRoot
    config_path = $ConfigPath
    site_root = $SiteRoot
    route_name = $RouteName
    report_url = $ReportUrl
    deploys = -not $NoDeploy
    sends_email = $false
  } | ConvertTo-Json
  exit 0
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$env:PYTHONPATH = Join-Path $ProjectRoot 'src'
$Preflight = Invoke-RadarJson @('-m', 'radar.cli', 'publish-preflight', '--config', $ConfigPath)
if (-not $Preflight.ok) { throw 'Publish preflight refused this config.' }

$PreviousState = $null
if (Test-Path $StatePath) {
  try { $PreviousState = Get-Content -Raw $StatePath | ConvertFrom-Json } catch { $PreviousState = $null }
}
$ResumableStatuses = @('pending_export', 'pending_deploy', 'failed_export', 'failed_deploy', 'failed_verify')
if (-not $RunId -and -not $ForceNewScan -and $PreviousState -and $PreviousState.status -in $ResumableStatuses) {
  $RunId = [string]$PreviousState.run_id
}

$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$LogPath = Join-Path $LogDir "weekly-$Stamp.log"

Push-Location $ProjectRoot
try {
  if (-not $RunId) {
    Save-PublishState @{ status = 'scanning'; run_id = $null; log_path = $LogPath; report_url = $ReportUrl }
    $ScanCode = Invoke-NativeLogged $PythonExe @('-m', 'radar.cli', 'scan', '--config', $ConfigPath, '--fail-on-source-errors') $LogPath
    if ($ScanCode -ne 0) {
      Save-PublishState @{ status = 'failed_scan'; run_id = $null; exit_code = $ScanCode; log_path = $LogPath; report_url = $ReportUrl }
      throw "Weekly scan failed with exit code $ScanCode. Stable report was not changed."
    }
  }

  $Audit = Invoke-RadarJson @('-m', 'radar.cli', 'state-audit', '--config', $ConfigPath)
  $Latest = $Audit.latest_run
  if (-not $Latest) { throw 'No completed RadarWire run exists for this config.' }
  if (-not $RunId) { $RunId = [string]$Latest.id }
  if ($RunId -ne [string]$Latest.id) { throw "Requested run $RunId is not the latest audited run $($Latest.id)." }
  if ($Latest.status -ne 'ok' -or $Latest.stage -ne 'finished') { throw "Run $RunId is not complete and clean." }
  if ([int]$Latest.source_error_count -ne 0 -or @($Latest.failed_sources).Count -ne 0 -or $Latest.has_warnings) {
    throw "Run $RunId failed the clean-source publish gate."
  }
  if ([int]$Latest.analyzed_article_count -le 0) {
    Save-PublishState @{ status = 'no_changes'; run_id = $RunId; article_count = 0; log_path = $LogPath; report_url = $ReportUrl }
    Write-Host 'No changed articles were analyzed. Existing stable report remains live.'
    exit 0
  }

  Save-PublishState @{ status = 'pending_export'; run_id = $RunId; article_count = [int]$Latest.analyzed_article_count; log_path = $LogPath; report_url = $ReportUrl }
  try {
    $ExportCode = Invoke-NativeLogged $PythonExe @('-m', 'radar.cli', 'export-report-site', '--config', $ConfigPath, '--run-id', $RunId, '--output-dir', $SiteRoot, '--route-name', $RouteName, '--base-url', $HostedBaseUrl, '--overwrite') $LogPath
    if ($ExportCode -ne 0) { throw "Report export failed with exit code $ExportCode." }
  } catch {
    Save-PublishState @{ status = 'failed_export'; run_id = $RunId; article_count = [int]$Latest.analyzed_article_count; log_path = $LogPath; report_url = $ReportUrl; error = $_.Exception.Message }
    throw
  }

  if (-not (Test-Path $MetadataPath)) { throw "Export metadata not found: $MetadataPath" }
  $LocalMetadata = Get-Content -Raw $MetadataPath | ConvertFrom-Json
  if ($LocalMetadata.run_id -ne $RunId -or [int]$LocalMetadata.source_error_count -ne 0) {
    throw 'Export metadata did not pass run ID and source-error validation.'
  }

  if ($NoDeploy) {
    Save-PublishState @{ status = 'exported_not_deployed'; run_id = $RunId; article_count = [int]$LocalMetadata.article_count; log_path = $LogPath; report_url = $ReportUrl }
    Write-Host "Exported run $RunId without deployment."
    exit 0
  }

  Save-PublishState @{ status = 'pending_deploy'; run_id = $RunId; article_count = [int]$LocalMetadata.article_count; log_path = $LogPath; report_url = $ReportUrl }
  try {
    $DeployCode = Invoke-NativeLogged $VercelExe @('deploy', '--prod', '--yes', '--cwd', $SiteRoot) $LogPath
    if ($DeployCode -ne 0) { throw "Vercel deploy failed with exit code $DeployCode." }
  } catch {
    Save-PublishState @{ status = 'failed_deploy'; run_id = $RunId; article_count = [int]$LocalMetadata.article_count; log_path = $LogPath; report_url = $ReportUrl; error = $_.Exception.Message }
    throw
  }

  $Verified = $false
  for ($Attempt = 1; $Attempt -le 8; $Attempt++) {
    try {
      $RemoteMetadata = Invoke-RestMethod -Uri "${MetadataUrl}?run=$RunId" -Method Get -Headers @{ 'Cache-Control' = 'no-cache' }
      $Page = Invoke-WebRequest -Uri "${ReportUrl}?run=$RunId" -Method Get -UseBasicParsing -Headers @{ 'Cache-Control' = 'no-cache' }
      if ($Page.StatusCode -eq 200 -and $RemoteMetadata.run_id -eq $RunId -and [int]$RemoteMetadata.source_error_count -eq 0) {
        $Verified = $true
        break
      }
    } catch {
      # The production alias can take a few seconds to settle after an atomic deploy.
    }
    Start-Sleep -Seconds 5
  }
  if (-not $Verified) {
    Save-PublishState @{ status = 'failed_verify'; run_id = $RunId; article_count = [int]$LocalMetadata.article_count; log_path = $LogPath; report_url = $ReportUrl; error = 'Live route did not return the expected run metadata.' }
    throw "Live verification failed for run $RunId."
  }

  Save-PublishState @{ status = 'published'; run_id = $RunId; article_count = [int]$RemoteMetadata.article_count; exported_at = $RemoteMetadata.exported_at; published_at = [DateTime]::UtcNow.ToString('o'); log_path = $LogPath; report_url = $ReportUrl }
  Write-Host "Published and verified run $RunId at $ReportUrl"
} finally {
  Pop-Location
}
