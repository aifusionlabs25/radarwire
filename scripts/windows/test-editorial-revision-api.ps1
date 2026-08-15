param(
  [string]$Endpoint = 'https://site-export-preview.vercel.app/api/editorial-revisions',
  [string]$CredentialPath = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path '.radar-data\private\editorial-save-token.dpapi.json')
)

$ErrorActionPreference = 'Stop'
if ($Endpoint -notmatch '^https://') { throw 'Endpoint must be absolute HTTPS.' }
if (-not (Test-Path -LiteralPath $CredentialPath -PathType Leaf)) { throw "Encrypted editorial token not found: $CredentialPath" }

$envelope = Get-Content -Raw -LiteralPath $CredentialPath | ConvertFrom-Json
if ($envelope.schema_version -ne 1 -or $envelope.protection -ne 'Windows DPAPI current user' -or $envelope.vercel_env -ne 'RADAR_EDITORIAL_SAVE_TOKEN') {
  throw 'Unsupported editorial token envelope.'
}
$secure = ConvertTo-SecureString $envelope.encrypted_value
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
$token = $null
try {
  $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
  $stamp = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss')
  $body = [ordered]@{
    schema_version = 1
    client_id = 'qa-operator'
    client_name = 'RadarWire QA'
    edition_id = "production-smoke-$stamp"
    article_slug = 'revision-round-trip'
    article_title = 'Private revision API round trip'
    reading_mode = 'short'
    original_html = '<p>Original operator-controlled QA draft.</p>'
    original_text = 'Original operator-controlled QA draft.'
    edited_html = '<p>Edited operator-controlled QA draft.</p>'
    edited_text = 'Edited operator-controlled QA draft.'
    approval_status = 'submitted'
    voice_library_consent = $false
    consent_notice = 'Operator-controlled production validation; not eligible for client voice matching.'
    source_url = 'https://site-export-preview.vercel.app/reports/1099fire-weekly-review/'
  }
  $headers = @{ Authorization = "Bearer $token" }
  $saved = Invoke-RestMethod -Method Post -Uri $Endpoint -Headers $headers -ContentType 'application/json' -Body ($body | ConvertTo-Json -Depth 5 -Compress)
  if (-not $saved.ok -or $saved.approval_status -ne 'submitted' -or $saved.voice_library_eligible) {
    throw 'Revision save response failed the safety gate.'
  }
  $exportUri = $Endpoint + '?client_id=qa-operator&include_submitted=1'
  $export = Invoke-RestMethod -Method Get -Uri $exportUri -Headers $headers
  if (-not $export.ok -or @($export.revisions | Where-Object revision_id -eq $saved.revision_id).Count -ne 1) {
    throw 'Saved revision was not found in the authenticated export.'
  }
  [ordered]@{
    status = 'ok'
    saved = $true
    exported = $true
    revision_id = $saved.revision_id
    approval_status = $saved.approval_status
    voice_library_eligible = $saved.voice_library_eligible
    token_printed = $false
    sends_email = $false
    deploys = $false
    schedules = $false
  } | ConvertTo-Json
}
finally {
  if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
  Remove-Variable token, secure -ErrorAction SilentlyContinue
}
