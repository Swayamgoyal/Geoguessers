# Runs the E4 GPU sweep unattended. Re-running skips runs already in results\runs.csv. Log: logs\e4_log.txt.
# Outputs go to the internal D: scratch folder and are deleted after each run (the harness waits until the
# space is really freed), so D: never holds more than one run's output.
#   powershell -ExecutionPolicy Bypass -File bench\run_e4.ps1
$repo = Split-Path $PSScriptRoot -Parent
Set-Location $repo
New-Item -ItemType Directory -Force (Join-Path $repo 'logs') | Out-Null
$log = Join-Path $repo 'logs\e4_log.txt'
"[$(Get-Date -Format HH:mm:ss)] starting e4_gpu" | Out-File $log -Append -Encoding utf8
cmd /c "D:\miniforge3\Scripts\conda.exe run -n geo --no-capture-output python -u -m bench.experiments.e4_gpu >> `"$log`" 2>&1"
"[$(Get-Date -Format HH:mm:ss)] e4_gpu finished, exit code $LASTEXITCODE" | Out-File $log -Append -Encoding utf8
