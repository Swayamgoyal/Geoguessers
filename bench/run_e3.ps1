# Runs the E3 CPU sweep unattended. Re-running skips runs already in results\runs.csv. Log: logs\e3_log.txt.
# Outputs go to the internal D: scratch folder and are deleted after each run (the harness waits until the
# space is really freed), so D: never holds more than one run's output.
#   powershell -ExecutionPolicy Bypass -File bench\run_e3.ps1
$repo = Split-Path $PSScriptRoot -Parent
Set-Location $repo
New-Item -ItemType Directory -Force (Join-Path $repo 'logs') | Out-Null
$log = Join-Path $repo 'logs\e3_log.txt'
"[$(Get-Date -Format HH:mm:ss)] starting e3_cpu" | Out-File $log -Append -Encoding utf8
cmd /c "D:\miniforge3\Scripts\conda.exe run -n geo --no-capture-output python -u -m bench.experiments.e3_cpu >> `"$log`" 2>&1"
"[$(Get-Date -Format HH:mm:ss)] e3_cpu finished, exit code $LASTEXITCODE" | Out-File $log -Append -Encoding utf8
