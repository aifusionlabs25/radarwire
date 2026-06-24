param(
  [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path,
  [string]$ConfigPath = "$ProjectRoot\config.v0.2.example.yaml",
  [string]$PythonExe = $env:RADAR_PYTHON_EXE,
  [string[]]$ExtraArgs = @()
)
$ErrorActionPreference='Stop'

if ([string]::IsNullOrWhiteSpace($PythonExe)) {
  $VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
  if (Test-Path $VenvPython) {
    $PythonExe = $VenvPython
  } else {
    $KnownSystemPython = 'C:\Users\AI Fusion Labs\AppData\Local\Programs\Python\Python311\python.exe'
    if (Test-Path $KnownSystemPython) {
      $PythonExe = $KnownSystemPython
    } else {
      throw 'PythonExe was not provided, RADAR_PYTHON_EXE is not set, and neither .venv nor known system Python was found.'
    }
  }
}

if (-not (Test-Path $PythonExe)) { throw "PythonExe not found: $PythonExe" }

$LogDir = Join-Path $ProjectRoot '.radar-data\logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$log = Join-Path $LogDir "run-$stamp.log"

Push-Location $ProjectRoot
try {
  $ArgsList = @('-m', 'radar.cli', 'scan', '--config', $ConfigPath) + $ExtraArgs
  & $PythonExe @ArgsList *>> $log
  $code=$LASTEXITCODE
} finally {
  Pop-Location
}
exit $code
