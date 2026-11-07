# Runs the E6 sweep unattended (about 2.5 hours; appends to results\runs.csv and results\e6_*.csv; an interrupted
# sweep resumes where it stopped). Log: logs\e6_log.txt. Keep the laptop plugged in; it is kept awake.
# Cold runs need the cache-flush task (bench\register_flush_task.ps1, once, as administrator).
#   powershell -ExecutionPolicy Bypass -File bench\run_e6.ps1
$repo = Split-Path $PSScriptRoot -Parent
Set-Location $repo
New-Item -ItemType Directory -Force (Join-Path $repo 'logs') | Out-Null
$log = Join-Path $repo 'logs\e6_log.txt'
"[$(Get-Date -Format HH:mm:ss)] starting e6_view" | Out-File $log -Append -Encoding utf8
cmd /c "D:\miniforge3\Scripts\conda.exe run -n geo --no-capture-output python -u -m bench.experiments.e6_view >> `"$log`" 2>&1"
"[$(Get-Date -Format HH:mm:ss)] e6_view finished, exit code $LASTEXITCODE" | Out-File $log -Append -Encoding utf8
