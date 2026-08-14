param(
  [string]$TaskName = 'RadarWire Weekly Publish',
  [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
)
$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$Info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
$StatePath = Join-Path $ProjectRoot '.radar-data\weekly-publish\state.json'
$PublishState = if (Test-Path $StatePath) { Get-Content -Raw $StatePath | ConvertFrom-Json } else { $null }

[ordered]@{
  task_registered = [bool]$Task
  task_state = if ($Task) { [string]$Task.State } else { $null }
  next_run_time = if ($Info) { $Info.NextRunTime.ToString('o') } else { $null }
  last_run_time = if ($Info) { $Info.LastRunTime.ToString('o') } else { $null }
  last_task_result = if ($Info) { $Info.LastTaskResult } else { $null }
  publish_state = $PublishState
} | ConvertTo-Json -Depth 8
