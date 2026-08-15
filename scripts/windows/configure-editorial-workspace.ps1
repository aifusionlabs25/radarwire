param(
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
  [string]$VercelExe = 'C:\Users\AI Fusion Labs\AppData\Roaming\npm\vercel.ps1',
  [string]$CredentialPath = '',
  [switch]$Force
)

$ErrorActionPreference = 'Stop'
if (-not $CredentialPath) {
  $CredentialPath = Join-Path $ProjectRoot '.radar-data\private\editorial-save-token.dpapi.json'
}
if (-not (Test-Path -LiteralPath $VercelExe -PathType Leaf)) {
  throw "Vercel CLI not found: $VercelExe"
}
if ((Test-Path -LiteralPath $CredentialPath) -and -not $Force) {
  throw "Encrypted editorial token already exists. Use -Force only to rotate it: $CredentialPath"
}

function Invoke-Vercel([string[]]$Arguments, [string]$InputValue = '') {
  $start = New-Object Diagnostics.ProcessStartInfo
  $node = (Get-Command node.exe -ErrorAction Stop).Source
  $vercelEntry = Join-Path (Split-Path -Parent $VercelExe) 'node_modules\vercel\dist\vc.js'
  if (-not (Test-Path -LiteralPath $vercelEntry -PathType Leaf)) { throw "Vercel Node entrypoint not found: $vercelEntry" }
  $transport = Join-Path $PSScriptRoot 'vercel-env-stdin.mjs'
  if (-not (Test-Path -LiteralPath $transport -PathType Leaf)) { throw "Vercel stdin transport not found: $transport" }
  $start.FileName = $node
  $start.WorkingDirectory = $ProjectRoot
  $quoted = @($Arguments | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' })
  $start.Arguments = '"' + $transport + '" "' + $vercelEntry + '" ' + ($quoted -join ' ')
  $start.UseShellExecute = $false
  $start.CreateNoWindow = $true
  $start.RedirectStandardOutput = $true
  $start.RedirectStandardError = $true
  if ($InputValue) { $start.EnvironmentVariables['RADAR_EDITORIAL_TEMP_INPUT'] = $InputValue }
  $process = New-Object Diagnostics.Process
  $process.StartInfo = $start
  [void]$process.Start()
  $stdout = $process.StandardOutput.ReadToEnd()
  $stderr = $process.StandardError.ReadToEnd()
  $process.WaitForExit()
  [pscustomobject]@{ ExitCode = $process.ExitCode; Stdout = $stdout; Stderr = $stderr }
}

$inspection = Invoke-Vercel @('env', 'ls')
if ($inspection.ExitCode -ne 0) { throw 'Unable to inspect the linked Vercel project.' }
$existing = $inspection.Stdout + $inspection.Stderr
if ($existing -match '(?m)^\s*RADAR_EDITORIAL_SAVE_TOKEN\s' -and -not $Force) {
  throw 'RADAR_EDITORIAL_SAVE_TOKEN already exists in Vercel. Use -Force only to rotate it.'
}

$bytes = New-Object byte[] 32
$generator = [Security.Cryptography.RandomNumberGenerator]::Create()
$generator.GetBytes($bytes)
$generator.Dispose()
$token = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')

try {
  foreach ($environment in @('production', 'preview', 'development')) {
    $arguments = @('env', 'add', 'RADAR_EDITORIAL_SAVE_TOKEN', $environment, '--force')
    if ($environment -ne 'development') { $arguments += '--sensitive' }
    $result = Invoke-Vercel $arguments $token
    if ($result.Stdout) { Write-Host $result.Stdout.Trim() }
    if ($result.Stderr) { Write-Host $result.Stderr.Trim() }
    if ($result.ExitCode -ne 0) { throw "Unable to configure RADAR_EDITORIAL_SAVE_TOKEN for $environment." }
  }

  $parent = Split-Path -Parent $CredentialPath
  New-Item -ItemType Directory -Path $parent -Force | Out-Null
  if (Test-Path -LiteralPath $CredentialPath) {
    $existingCredential = Get-Item -LiteralPath $CredentialPath -Force
    $existingCredential.Attributes = $existingCredential.Attributes -band (-bnot [IO.FileAttributes]::Hidden)
  }
  $secure = ConvertTo-SecureString $token -AsPlainText -Force
  $payload = [ordered]@{
    schema_version = 1
    purpose = 'RadarWire private editorial revision API'
    protected_for = "$env:USERDOMAIN\$env:USERNAME"
    protection = 'Windows DPAPI current user'
    vercel_env = 'RADAR_EDITORIAL_SAVE_TOKEN'
    encrypted_value = ConvertFrom-SecureString $secure
  }
  $payload | ConvertTo-Json | Set-Content -LiteralPath $CredentialPath -Encoding UTF8
  $credentialFile = Get-Item -LiteralPath $CredentialPath -Force
  $credentialFile.Attributes = $credentialFile.Attributes -bor [IO.FileAttributes]::Hidden

  [ordered]@{
    status = 'configured'
    vercel_env = 'RADAR_EDITORIAL_SAVE_TOKEN'
    environments = @('production', 'preview', 'development')
    encrypted_credential_path = $CredentialPath
    protection = 'Windows DPAPI current user'
    token_printed = $false
    sends_email = $false
    deploys = $false
    schedules = $false
  } | ConvertTo-Json
}
finally {
  if ($bytes) { [Array]::Clear($bytes, 0, $bytes.Length) }
  Remove-Variable token -ErrorAction SilentlyContinue
  Remove-Variable secure -ErrorAction SilentlyContinue
}
