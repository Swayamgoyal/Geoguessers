# Run ONCE as administrator. Registers a scheduled task that empties the Windows
# standby (file) cache with RAMMap, so benchmark cold runs can trigger it without admin.
$ErrorActionPreference = 'Stop'
$exe = 'D:\geoguessers_data\tools\RAMMap64.exe'
$user = "$env:USERDOMAIN\$env:USERNAME"

# -Et = empty standby list (the file cache). Valid flags: -Ew -Es -Em -Et -E0
$action = New-ScheduledTaskAction -Execute $exe -Argument '-accepteula -Et'
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'GeoGuessers-FlushCache' -TaskPath '\GeoGuessers\' -Action $action `
    -Principal $principal -Settings $settings -Description 'Empty standby list (RAMMap -Et) for cold-cache benchmarks' -Force

# Log the result next to this script so the non-admin side can confirm it worked
Get-ScheduledTask -TaskName 'GeoGuessers-FlushCache' -TaskPath '\GeoGuessers\' |
    Select-Object TaskName, State | Out-File 'D:\geoguessers_data\tools\register_flush_task.log'
