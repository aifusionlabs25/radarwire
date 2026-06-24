param([string]$TaskName='Competitor Content Radar', [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path, [switch]$WhatIfOnly=$true)
$Action = New-ScheduledTaskAction -Execute 'PowerShell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ProjectRoot\scripts\windows\run-radar.ps1`" -ProjectRoot `"$ProjectRoot`""
$Trigger1 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Tuesday -At 8:00AM
$Trigger2 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At 8:00AM
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 60) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 10)
$Task = New-ScheduledTask -Action $Action -Trigger @($Trigger1,$Trigger2) -Settings $Settings -Description 'Headless Competitor Content Radar. Does not open Hermes Desktop.'
if ($WhatIfOnly) { $Task | Format-List *; Write-Host 'Prepared only. Re-run with -WhatIfOnly:$false to register intentionally.'; exit 0 }
Register-ScheduledTask -TaskName $TaskName -InputObject $Task -Force | Out-Null
Write-Host "Registered task $TaskName (not started)."
