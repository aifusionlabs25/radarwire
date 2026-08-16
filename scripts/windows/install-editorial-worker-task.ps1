param(
  [string]$TaskName = 'RadarWire Editorial Worker',
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
  [switch]$WhatIfOnly = $true
)

$ErrorActionPreference = 'Stop'
$runner = Join-Path $ProjectRoot 'scripts\windows\run-editorial-worker.ps1'
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) { throw "Worker runner not found: $runner" }
$argument = "-NoProfile -ExecutionPolicy Bypass -File `"$runner`" -ProjectRoot `"$ProjectRoot`" -Watch"
if ($WhatIfOnly) {
  [ordered]@{
    status = 'prepared_only'
    task_name = $TaskName
    execute = 'PowerShell.exe'
    argument = $argument
    trigger = 'AtLogOn'
    start_when_available = $true
    restart_count = 5
    registered = $false
    started = $false
  } | ConvertTo-Json
  exit 0
}
$action = New-ScheduledTaskAction -Execute 'PowerShell.exe' -Argument $argument
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 2) -ExecutionTimeLimit ([TimeSpan]::Zero)
$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Description 'Outbound-only RadarWire editorial revision worker. Does not open Hermes Desktop.'
Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force -ErrorAction Stop | Out-Null
$registeredTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
if (-not $registeredTask) { throw "Task registration could not be verified: $TaskName" }
Write-Host "Registered $TaskName. It was not started."
