param(
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
  [string]$ConfigPath = "$ProjectRoot\config.pilot.amy-huffman-hermes-full-preview.yaml",
  [string]$Endpoint = 'https://site-export-preview.vercel.app/api/editorial-jobs',
  [string]$CredentialPath = "$ProjectRoot\.radar-data\private\editorial-save-token.dpapi.json",
  [string]$PythonExe = $env:RADAR_PYTHON_EXE,
  [ValidateRange(5, 300)]
  [int]$PollSeconds = 10,
  [switch]$Watch
)

$ErrorActionPreference = 'Stop'
if (-not $PythonExe) {
  $PythonExe = 'C:\Users\AI Fusion Labs\AppData\Local\Programs\Python\Python311\python.exe'
}
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { throw "Python not found: $PythonExe" }
if (-not (Test-Path -LiteralPath $CredentialPath -PathType Leaf)) { throw "Encrypted editorial credential not found: $CredentialPath" }

# Codex and PowerShell 7 can prepend incompatible modules when launching Windows PowerShell.
if ($PSVersionTable.PSEdition -eq 'Desktop') {
  $env:PSModulePath = @(
    "$HOME\Documents\WindowsPowerShell\Modules",
    "$env:ProgramFiles\WindowsPowerShell\Modules",
    "$env:WINDIR\system32\WindowsPowerShell\v1.0\Modules"
  ) -join ';'
}
Import-Module Microsoft.PowerShell.Security -ErrorAction Stop

$envelope = Get-Content -LiteralPath $CredentialPath -Raw | ConvertFrom-Json
$secure = ConvertTo-SecureString $envelope.encrypted_value
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
$logDir = Join-Path $ProjectRoot '.radar-data\editorial-worker\logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$logPath = Join-Path $logDir ('worker-' + (Get-Date -Format 'yyyyMMdd') + '.log')
$workerExitCode = 1

try {
  $env:RADAR_EDITORIAL_SAVE_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
  $arguments = @(
    '-m', 'radar.cli', 'editorial-worker',
    '--config', $ConfigPath,
    '--endpoint', $Endpoint,
    '--truth-profile', "$ProjectRoot\hermes\radarwire-editorial-reviser\references\1099fire-truth-profile.json"
  )
  if ($Watch) { $arguments += @('--watch', '--poll-seconds', [string]$PollSeconds) }
  Push-Location $ProjectRoot
  try {
    $env:PYTHONPATH = 'src'
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
      & $PythonExe @arguments *>> $logPath
      $workerExitCode = $LASTEXITCODE
    }
    finally {
      $ErrorActionPreference = $previousErrorAction
    }
  }
  finally { Pop-Location }
}
finally {
  Remove-Item Env:RADAR_EDITORIAL_SAVE_TOKEN -ErrorAction SilentlyContinue
  if ($ptr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
  Remove-Variable secure -ErrorAction SilentlyContinue
}
exit $workerExitCode
