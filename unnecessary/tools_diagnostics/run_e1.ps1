# Waits for synthetic-grid generation to finish, then runs the E1 sweep. Progress: D:\geoguessers_data\e1_log.txt
param([int]$WaitPid = 0)
$log = 'D:\geoguessers_data\e1_log.txt'
Set-Location 'C:\Users\swayam goyal\Desktop\spatial info\Geoguessers'
"[$(Get-Date -Format HH:mm:ss)] launcher started" | Out-File $log -Encoding utf8
if ($WaitPid -and (Get-Process -Id $WaitPid -ErrorAction SilentlyContinue)) {
    "[$(Get-Date -Format HH:mm:ss)] waiting for grid generation (PID $WaitPid) to finish..." | Out-File $log -Append -Encoding utf8
    Wait-Process -Id $WaitPid
}
if (Get-ChildItem 'D:\geoguessers_data\synthetic\*.tmp' -ErrorAction SilentlyContinue) {
    "[$(Get-Date -Format HH:mm:ss)] ERROR: generation left .tmp files; not starting E1" | Out-File $log -Append -Encoding utf8
    exit 1
}
"[$(Get-Date -Format HH:mm:ss)] starting E1 sweep" | Out-File $log -Append -Encoding utf8
cmd /c "D:\miniforge3\Scripts\conda.exe run -n geo --no-capture-output python -u -m bench.experiments.e1_baseline >> `"$log`" 2>&1"
"[$(Get-Date -Format HH:mm:ss)] E1 finished, exit code $LASTEXITCODE" | Out-File $log -Append -Encoding utf8
