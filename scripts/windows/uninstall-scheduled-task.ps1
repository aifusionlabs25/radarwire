param([string]$TaskName='Competitor Content Radar', [switch]$WhatIfOnly=$true)
if ($WhatIfOnly) { Write-Host "Would unregister $TaskName. Re-run with -WhatIfOnly:$false."; exit 0 }
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
