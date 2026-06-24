param([string]$TaskName='Competitor Content Radar')
Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Get-ScheduledTaskInfo
