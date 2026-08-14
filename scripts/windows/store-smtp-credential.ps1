param(
  [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path,
  [string]$CredentialPath = "$ProjectRoot\.radar-data\weekly-publish\smtp-credential.dpapi.json",
  [string]$Username = 'aifusionlabs@gmail.com',
  [switch]$Force
)
$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($Username)) { throw 'SMTP username cannot be empty.' }
if ((Test-Path $CredentialPath) -and -not $Force) {
  throw "Encrypted SMTP credential already exists: $CredentialPath"
}

$Password = Read-Host 'Paste the Gmail app password, then press Enter' -AsSecureString
if ($Password.Length -eq 0) { throw 'SMTP app password cannot be empty.' }
$Pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Password)
try {
  $PlainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer)
  $NormalizedPassword = $PlainPassword -replace '\s', ''
  if ($NormalizedPassword.Length -ne 16) {
    throw 'A Gmail app password must contain exactly 16 non-space characters.'
  }
  $NormalizedSecurePassword = ConvertTo-SecureString $NormalizedPassword -AsPlainText -Force
  $EncryptedPassword = ConvertFrom-SecureString $NormalizedSecurePassword
} finally {
  if ($Pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer) }
  Remove-Variable PlainPassword, NormalizedPassword, NormalizedSecurePassword, Password -ErrorAction SilentlyContinue
}

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

Remove-Variable EncryptedPassword -ErrorAction SilentlyContinue
Write-Host 'Encrypted SMTP credential stored for the current Windows user. No email was sent.'
