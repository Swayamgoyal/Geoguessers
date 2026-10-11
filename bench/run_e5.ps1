# Runs the E5 timing sweep unattended (rewrites results\e5_timing.csv). Log: logs\e5_timing_log.txt.
# Needs the slope pyramids first:  python -m bench.experiments.e5_timing --precompute
# Reads only; nothing is written except the CSV.
#   powershell -ExecutionPolicy Bypass -File bench\run_e5.ps1
$repo = Split-Path $PSScriptRoot -Parent
Set-Location $repo
New-Item -ItemType Directory -Force (Join-Path $repo 'logs') | Out-Null
$log = Join-Path $repo 'logs\e5_timing_log.txt'
"[$(Get-Date -Format HH:mm:ss)] starting e5_timing" | Out-File $log -Append -Encoding utf8
cmd /c "D:\miniforge3\Scripts\conda.exe run -n geo --no-capture-output python -u -m bench.experiments.e5_timing >> `"$log`" 2>&1"
"[$(Get-Date -Format HH:mm:ss)] e5_timing finished, exit code $LASTEXITCODE" | Out-File $log -Append -Encoding utf8
