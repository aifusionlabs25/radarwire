param(
  [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path,
  [string]$ConfigPath = "$ProjectRoot\config.pilot.local.yaml",
  [string]$PythonExe = $env:RADAR_PYTHON_EXE,
  [string]$VercelExe = $env:RADAR_VERCEL_EXE,
  [string]$SiteRoot = "$ProjectRoot\.radar-data\site-export-preview",
  [string]$RouteName = 'latest',
  [string]$HostedBaseUrl = 'https://site-export-preview.vercel.app',
  [string]$DeliveryConfigPath = "$ProjectRoot\.radar-data\weekly-publish\email-delivery.yaml",
  [string]$CredentialPath = "$ProjectRoot\.radar-data\weekly-publish\smtp-credential.dpapi.json",
  [string]$EditorialReviewDir,
  [string]$EditorialReviewUrl,
  [string]$RunId,
  [switch]$EnableEmailDelivery,
  [switch]$AllowRadarDigestEmail,
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

function Sync-DeploymentShell([string]$SourceRoot, [string]$DestinationRoot) {
  $Files = @(
    'index.html',
    'vercel.json',
    'package.json',
    'package-lock.json',
    'api\editorial-revisions.js',
    'api\_editorial_revision_core.mjs',
    'api\editorial-jobs.js',
    'api\_editorial_job_core.mjs',
    'api\editorial-attachments.js',
    'api\_editorial_attachment_core.mjs',
    'api\editorial-session.js',
    'api\_editorial_session_core.mjs',
    'api\editorial-status.js',
    'api\_editorial_status_core.mjs',
    'api\_published_snapshot_core.mjs'
  )
  foreach ($RelativePath in $Files) {
    $SourcePath = Join-Path $SourceRoot $RelativePath
    if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
      throw "Deployment shell source missing: $RelativePath"
    }
    $DestinationPath = Join-Path $DestinationRoot $RelativePath
    $DestinationDirectory = Split-Path -Parent $DestinationPath
    New-Item -ItemType Directory -Force -Path $DestinationDirectory | Out-Null
    Copy-Item -LiteralPath $SourcePath -Destination $DestinationPath -Force
  }
}

function Import-SmtpCredential([string]$Path) {
  $Envelope = Get-Content -Raw $Path | ConvertFrom-Json
  if ($Envelope.version -ne 1 -or $Envelope.protection -ne 'Windows DPAPI current user') {
    throw 'Unsupported SMTP credential envelope.'
  }
  if ($Envelope.username_env -ne 'RADAR_SMTP_USERNAME' -or $Envelope.password_env -ne 'RADAR_SMTP_PASSWORD') {
    throw 'Unexpected SMTP credential environment variable names.'
  }
  $SecurePassword = ConvertTo-SecureString $Envelope.password_dpapi
  $Pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecurePassword)
  try {
    $PlainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer)
    [Environment]::SetEnvironmentVariable($Envelope.username_env, [string]$Envelope.username, 'Process')
    [Environment]::SetEnvironmentVariable($Envelope.password_env, $PlainPassword, 'Process')
  } catch {
    [Environment]::SetEnvironmentVariable('RADAR_SMTP_USERNAME', $null, 'Process')
    [Environment]::SetEnvironmentVariable('RADAR_SMTP_PASSWORD', $null, 'Process')
    throw
  } finally {
    if ($Pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer) }
    Remove-Variable PlainPassword, SecurePassword -ErrorAction SilentlyContinue
  }
  return @([string]$Envelope.username_env, [string]$Envelope.password_env)
}

function Clear-SmtpCredential([string[]]$Names) {
  foreach ($Name in $Names) {
    if ($Name) { [Environment]::SetEnvironmentVariable($Name, $null, 'Process') }
  }
}

$ProjectRoot = (Resolve-Path $ProjectRoot).Path
if (-not [IO.Path]::IsPathRooted($ConfigPath)) { $ConfigPath = Join-Path $ProjectRoot $ConfigPath }
if (-not [IO.Path]::IsPathRooted($SiteRoot)) { $SiteRoot = Join-Path $ProjectRoot $SiteRoot }
if (-not [IO.Path]::IsPathRooted($DeliveryConfigPath)) { $DeliveryConfigPath = Join-Path $ProjectRoot $DeliveryConfigPath }
if (-not [IO.Path]::IsPathRooted($CredentialPath)) { $CredentialPath = Join-Path $ProjectRoot $CredentialPath }
if ($EditorialReviewDir -and -not [IO.Path]::IsPathRooted($EditorialReviewDir)) { $EditorialReviewDir = Join-Path $ProjectRoot $EditorialReviewDir }
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
    sends_email = [bool]$EnableEmailDelivery
    email_mode = if (-not $EnableEmailDelivery) { 'disabled' } elseif ($EditorialReviewDir) { 'editorial_review' } else { 'radar_digest' }
    editorial_review_dir = if ($EditorialReviewDir) { $EditorialReviewDir } else { $null }
    editorial_review_url = if ($EditorialReviewUrl) { $EditorialReviewUrl } else { $null }
    delivery_config_path = if ($EnableEmailDelivery) { $DeliveryConfigPath } else { $null }
    credential_path = if ($EnableEmailDelivery) { $CredentialPath } else { $null }
  } | ConvertTo-Json
  exit 0
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$env:PYTHONPATH = Join-Path $ProjectRoot 'src'
$Preflight = Invoke-RadarJson @('-m', 'radar.cli', 'publish-preflight', '--config', $ConfigPath)
if (-not $Preflight.ok) { throw 'Publish preflight refused this config.' }
if ($EnableEmailDelivery) {
  if (-not (Test-Path $DeliveryConfigPath)) { throw "Delivery config not found: $DeliveryConfigPath" }
  if (-not (Test-Path $CredentialPath)) { throw "Encrypted SMTP credential not found: $CredentialPath" }
  if ($EditorialReviewDir) {
    if (-not (Test-Path $EditorialReviewDir)) { throw "Editorial review directory not found: $EditorialReviewDir" }
    if ($EditorialReviewUrl -notmatch '^https://') { throw 'EditorialReviewUrl must be an absolute HTTPS URL.' }
  } elseif (-not $AllowRadarDigestEmail) {
    throw 'Client-facing automatic email requires EditorialReviewDir and EditorialReviewUrl. Use AllowRadarDigestEmail only for an explicitly approved internal research digest.'
  }
}

$PreviousState = $null
if (Test-Path $StatePath) {
  try { $PreviousState = Get-Content -Raw $StatePath | ConvertFrom-Json } catch { $PreviousState = $null }
}
$ResumableStatuses = @('pending_export', 'pending_deploy', 'failed_export', 'failed_deploy', 'failed_verify', 'pending_email', 'failed_email')
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

  # Keep the stable site shell and private editorial API in every weekly artifact.
  Sync-DeploymentShell $ProjectRoot $SiteRoot

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

  $PublishedAt = [DateTime]::UtcNow.ToString('o')
  if (-not $EnableEmailDelivery) {
    Save-PublishState @{ status = 'published'; run_id = $RunId; article_count = [int]$RemoteMetadata.article_count; exported_at = $RemoteMetadata.exported_at; published_at = $PublishedAt; log_path = $LogPath; report_url = $ReportUrl }
    Write-Host "Published and verified run $RunId at $ReportUrl"
    exit 0
  }

  Save-PublishState @{ status = 'pending_email'; run_id = $RunId; article_count = [int]$RemoteMetadata.article_count; exported_at = $RemoteMetadata.exported_at; published_at = $PublishedAt; log_path = $LogPath; report_url = $ReportUrl }
  $CredentialEnvNames = @()
  try {
    $CredentialEnvNames = Import-SmtpCredential $CredentialPath
    if ($EditorialReviewDir) {
      $EditorialPage = Invoke-WebRequest -Uri $EditorialReviewUrl -Method Get -UseBasicParsing -Headers @{ 'Cache-Control' = 'no-cache' }
      if ($EditorialPage.StatusCode -ne 200) { throw 'Hosted editorial review route did not return HTTP 200.' }
      $EmailPreflight = Invoke-RadarJson @('-m', 'radar.cli', 'editorial-email-preflight', '--config', $DeliveryConfigPath, '--review-dir', $EditorialReviewDir, '--expected-review-url', $EditorialReviewUrl)
      if (-not $EmailPreflight.ok) { throw 'Editorial email delivery preflight refused this package.' }
      $DeliveryResult = Invoke-RadarJson @('-m', 'radar.cli', 'deliver-editorial-review', '--config', $DeliveryConfigPath, '--review-dir', $EditorialReviewDir, '--send')
      $EmailMode = 'editorial_review'
    } else {
      $EmailPreflight = Invoke-RadarJson @('-m', 'radar.cli', 'email-delivery-preflight', '--config', $DeliveryConfigPath, '--run-id', $RunId, '--expected-report-url', $ReportUrl)
      if (-not $EmailPreflight.ok -or $EmailPreflight.run_id -ne $RunId) { throw 'Automatic radar digest delivery preflight refused this run.' }
      $DeliveryResult = Invoke-RadarJson @('-m', 'radar.cli', 'deliver-report', '--config', $DeliveryConfigPath, '--run-id', $RunId, '--send')
      $EmailMode = 'radar_digest'
    }
    $DeliveryStatus = [string]$DeliveryResult.delivery.status
    if ($DeliveryStatus -notin @('sent', 'duplicate_skipped')) { throw "Unexpected delivery status: $DeliveryStatus" }
    Save-PublishState @{ status = 'delivered'; run_id = $RunId; article_count = [int]$RemoteMetadata.article_count; exported_at = $RemoteMetadata.exported_at; published_at = $PublishedAt; delivered_at = [DateTime]::UtcNow.ToString('o'); delivery_status = $DeliveryStatus; email_mode = $EmailMode; editorial_review_url = $EditorialReviewUrl; log_path = $LogPath; report_url = $ReportUrl }
    Write-Host "Published, verified, and delivered run $RunId."
  } catch {
    Save-PublishState @{ status = 'failed_email'; run_id = $RunId; article_count = [int]$RemoteMetadata.article_count; exported_at = $RemoteMetadata.exported_at; published_at = $PublishedAt; log_path = $LogPath; report_url = $ReportUrl; error = $_.Exception.Message }
    throw
  } finally {
    Clear-SmtpCredential $CredentialEnvNames
  }
} finally {
  Pop-Location
}
