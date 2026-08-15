param(
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
  [string]$ReviewBaseUrl = 'https://site-export-preview.vercel.app/reports/1099fire-weekly-review/',
  [string]$CredentialPath = ''
)

$ErrorActionPreference = 'Stop'
if (-not $CredentialPath) {
  $CredentialPath = Join-Path $ProjectRoot '.radar-data\private\editorial-save-token.dpapi.json'
}
if (-not (Test-Path -LiteralPath $CredentialPath -PathType Leaf)) {
  throw "Encrypted editorial token not found: $CredentialPath"
}

$envelope = Get-Content -Raw -LiteralPath $CredentialPath | ConvertFrom-Json
if ($envelope.schema_version -ne 1 -or $envelope.protection -ne 'Windows DPAPI current user' -or $envelope.vercel_env -ne 'RADAR_EDITORIAL_SAVE_TOKEN') {
  throw 'Unsupported editorial token envelope.'
}

$secure = ConvertTo-SecureString $envelope.encrypted_value
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
  $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
  if ($token -notmatch '^[A-Za-z0-9_-]{32,128}$') { throw 'Recovered editorial token has an invalid shape.' }
  $privateLink = $ReviewBaseUrl.TrimEnd('/') + '/#review=' + [Uri]::EscapeDataString($token)
  Set-Clipboard -Value $privateLink
  [ordered]@{
    status = 'copied'
    destination = 'Windows clipboard'
    review_host = ([Uri]$ReviewBaseUrl).Host
    token_printed = $false
    sends_email = $false
    opens_browser = $false
  } | ConvertTo-Json
}
finally {
  if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
  Remove-Variable token -ErrorAction SilentlyContinue
  Remove-Variable privateLink -ErrorAction SilentlyContinue
}
