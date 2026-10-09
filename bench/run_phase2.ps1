# Runs the Phase 2 sweeps in order (E1, E2, E1-QGIS), unattended. Re-running skips runs already in
# results\runs.csv. Progress log: logs\phase2_log.txt in the repo.
#   powershell -ExecutionPolicy Bypass -File bench\run_phase2.ps1
$repo = Split-Path $PSScriptRoot -Parent
Set-Location $repo
New-Item -ItemType Directory -Force (Join-Path $repo 'logs') | Out-Null
$log = Join-Path $repo 'logs\phase2_log.txt'
foreach ($m in 'e1_baseline', 'e2_storage', 'e1_qgis') {
    "[$(Get-Date -Format HH:mm:ss)] starting $m" | Out-File $log -Append -Encoding utf8
    cmd /c "D:\miniforge3\Scripts\conda.exe run -n geo --no-capture-output python -u -m bench.experiments.$m >> `"$log`" 2>&1"
    "[$(Get-Date -Format HH:mm:ss)] $m finished, exit code $LASTEXITCODE" | Out-File $log -Append -Encoding utf8
}
"[$(Get-Date -Format HH:mm:ss)] ALL DONE" | Out-File $log -Append -Encoding utf8
