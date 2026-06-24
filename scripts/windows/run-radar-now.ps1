param(
  [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path,
  [string]$PythonExe = $env:RADAR_PYTHON_EXE,
  [string[]]$ExtraArgs = @()
)
& "$PSScriptRoot\run-radar.ps1" -ProjectRoot $ProjectRoot -PythonExe $PythonExe -ExtraArgs $ExtraArgs
exit $LASTEXITCODE
