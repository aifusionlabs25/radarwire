param(
  [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path,
  [string]$SourceConfigPath = "$ProjectRoot\config.pilot.local.yaml",
  [string]$DeliveryConfigPath = "$ProjectRoot\.radar-data\weekly-publish\email-delivery.yaml",
  [string]$CredentialPath = "$ProjectRoot\.radar-data\weekly-publish\smtp-credential.dpapi.json",
  [string]$PythonExe = $env:RADAR_PYTHON_EXE,
  [string]$SmtpHost = 'smtp.gmail.com',
  [int]$SmtpPort = 587,
  [string]$ReportUrl = 'https://site-export-preview.vercel.app/reports/1099fire-radar/',
  [string]$SenderEmail,
  [string]$RecipientEmail,
  [string]$ReplyToEmail,
  [switch]$Force
)
$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($PythonExe)) {
  $VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
  $KnownPython = 'C:\Users\AI Fusion Labs\AppData\Local\Programs\Python\Python311\python.exe'
  if (Test-Path $VenvPython) { $PythonExe = $VenvPython }
  elseif (Test-Path $KnownPython) { $PythonExe = $KnownPython }
  else { throw 'Python executable could not be resolved.' }
}
if (-not (Test-Path $SourceConfigPath)) { throw "Source config not found: $SourceConfigPath" }
if ((Test-Path $DeliveryConfigPath) -and -not $Force) { throw "Delivery config already exists: $DeliveryConfigPath" }
if ((Test-Path $CredentialPath) -and -not $Force) { throw "Encrypted credential already exists: $CredentialPath" }

if ([string]::IsNullOrWhiteSpace($SenderEmail)) { $SenderEmail = Read-Host 'From email address' }
if ([string]::IsNullOrWhiteSpace($RecipientEmail)) { $RecipientEmail = Read-Host 'Client recipient email address' }
if ([string]::IsNullOrWhiteSpace($ReplyToEmail)) { $ReplyToEmail = Read-Host 'Reply-To email address' }
$Username = Read-Host 'SMTP username'
if ([string]::IsNullOrWhiteSpace($Username)) { throw 'SMTP username cannot be empty.' }
$Password = Read-Host 'SMTP app password' -AsSecureString
if ($Password.Length -eq 0) { throw 'SMTP app password cannot be empty.' }
$EncryptedPassword = ConvertFrom-SecureString $Password

$env:PYTHONPATH = Join-Path $ProjectRoot 'src'
$PrepareArgs = @(
  '-m', 'radar.cli', 'prepare-email-delivery-config',
  '--source-config', $SourceConfigPath,
  '--output-config', $DeliveryConfigPath,
  '--smtp-host', $SmtpHost,
  '--smtp-port', [string]$SmtpPort,
  '--report-url', $ReportUrl,
  '--sender-email', $SenderEmail,
  '--recipient-email', $RecipientEmail,
  '--reply-to-email', $ReplyToEmail
)
if ($Force) { $PrepareArgs += '--overwrite' }
& $PythonExe @PrepareArgs
if ($LASTEXITCODE -ne 0) { throw "Delivery config preparation failed with exit code $LASTEXITCODE." }

$CredentialDir = Split-Path -Parent $CredentialPath
New-Item -ItemType Directory -Force -Path $CredentialDir | Out-Null
[ordered]@{
  version = 1
  protection = 'Windows DPAPI current user'
  username_env = 'RADAR_SMTP_USERNAME'
  password_env = 'RADAR_SMTP_PASSWORD'
  username = $Username
  password_dpapi = $EncryptedPassword
  created_at = [DateTime]::UtcNow.ToString('o')
} | ConvertTo-Json | Set-Content -Path $CredentialPath -Encoding UTF8

Remove-Variable SenderEmail, RecipientEmail, ReplyToEmail, Username, Password, EncryptedPassword -ErrorAction SilentlyContinue
Write-Host 'Weekly email delivery files prepared. No email was sent and no scheduled task was changed.'
