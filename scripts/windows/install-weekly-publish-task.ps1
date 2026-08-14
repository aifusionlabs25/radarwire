param(
  [string]$TaskName = 'RadarWire Weekly Publish',
  [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path,
  [string]$ConfigPath = "$ProjectRoot\config.pilot.local.yaml",
  [string]$PythonExe = 'C:\Users\AI Fusion Labs\AppData\Local\Programs\Python\Python311\python.exe',
  [string]$VercelExe = 'C:\Users\AI Fusion Labs\AppData\Roaming\npm\vercel.ps1',
  [string]$SiteRoot = "$ProjectRoot\.radar-data\site-export-preview",
  [string]$RouteName = 'latest',
  [string]$HostedBaseUrl = 'https://site-export-preview.vercel.app',
  [string]$DeliveryConfigPath = "$ProjectRoot\.radar-data\weekly-publish\email-delivery.yaml",
  [string]$CredentialPath = "$ProjectRoot\.radar-data\weekly-publish\smtp-credential.dpapi.json",
  [string]$EditorialReviewDir,
  [string]$EditorialReviewUrl,
  [switch]$EnableEmailDelivery,
  [switch]$AllowRadarDigestEmail,
  [bool]$WhatIfOnly = $true
)
$ErrorActionPreference = 'Stop'
$Worker = Join-Path $ProjectRoot 'scripts\windows\publish-weekly-report.ps1'
if (-not (Test-Path $Worker)) { throw "Weekly publisher not found: $Worker" }
if (-not (Test-Path $ConfigPath)) { throw "Config not found: $ConfigPath" }

$ActionArguments = @(
  '-NoProfile'
  '-NonInteractive'
  '-ExecutionPolicy Bypass'
  '-File', "`"$Worker`""
  '-ProjectRoot', "`"$ProjectRoot`""
  '-ConfigPath', "`"$ConfigPath`""
  '-PythonExe', "`"$PythonExe`""
  '-VercelExe', "`"$VercelExe`""
  '-SiteRoot', "`"$SiteRoot`""
  '-RouteName', "`"$RouteName`""
  '-HostedBaseUrl', "`"$HostedBaseUrl`""
) -join ' '

if ($EnableEmailDelivery) {
  $ActionArguments += " -DeliveryConfigPath `"$DeliveryConfigPath`" -CredentialPath `"$CredentialPath`" -EnableEmailDelivery"
  if ($EditorialReviewDir) {
    $ActionArguments += " -EditorialReviewDir `"$EditorialReviewDir`" -EditorialReviewUrl `"$EditorialReviewUrl`""
  } elseif ($AllowRadarDigestEmail) {
    $ActionArguments += ' -AllowRadarDigestEmail'
  }
}

if ($WhatIfOnly) {
  [ordered]@{
    status = 'prepared_only'
    task_name = $TaskName
    schedule = 'Sunday 6:00 PM local time'
    action = 'PowerShell.exe'
    arguments = $ActionArguments
    start_when_available = $true
    restart_count = 3
    sends_email = [bool]$EnableEmailDelivery
    email_mode = if (-not $EnableEmailDelivery) { 'disabled' } elseif ($EditorialReviewDir) { 'editorial_review' } else { 'radar_digest' }
    registered = $false
  } | ConvertTo-Json -Depth 4
  exit 0
}

if ($EnableEmailDelivery) {
  if (-not (Test-Path $DeliveryConfigPath)) { throw "Delivery config not found: $DeliveryConfigPath" }
  if (-not (Test-Path $CredentialPath)) { throw "Encrypted SMTP credential not found: $CredentialPath" }
  if ($EditorialReviewDir) {
    if (-not (Test-Path $EditorialReviewDir)) { throw "Editorial review directory not found: $EditorialReviewDir" }
    if ($EditorialReviewUrl -notmatch '^https://') { throw 'EditorialReviewUrl must be an absolute HTTPS URL.' }
  } elseif (-not $AllowRadarDigestEmail) {
    throw 'Client-facing scheduled email requires an editorial review directory and hosted URL.'
  }
}

$Action = New-ScheduledTaskAction -Execute 'PowerShell.exe' -Argument $ActionArguments -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 6:00PM
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 4) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 15)
$Task = New-ScheduledTask -Action $Action -Trigger $Trigger -Settings $Settings -Description 'Headless weekly RadarWire scan, stable report export, Vercel publish, and live verification. Email remains config-gated.'
Register-ScheduledTask -TaskName $TaskName -InputObject $Task -Force | Out-Null
Write-Host "Registered $TaskName for Sunday at 6:00 PM local time. The task was not started."
