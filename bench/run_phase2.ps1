# Runs the Phase 2 sweeps in order (E1, E2, E1-QGIS), unattended. Progress: $env:GEO_DATA\phase2_log.txt
# (default D:\geoguessers_data\phase2_log.txt). Re-running skips runs already in results\runs.csv.
#   powershell -ExecutionPolicy Bypass -File bench\run_phase2.ps1
$data = if ($env:GEO_DATA) { $env:GEO_DATA } else { 'D:\geoguessers_data' }
$log = Join-Path $data 'phase2_log.txt'
Set-Location (Split-Path $PSScriptRoot -Parent)
foreach ($m in 'e1_baseline', 'e2_storage', 'e1_qgis') {
    "[$(Get-Date -Format HH:mm:ss)] starting $m" | Out-File $log -Append -Encoding utf8
    cmd /c "D:\miniforge3\Scripts\conda.exe run -n geo --no-capture-output python -u -m bench.experiments.$m >> `"$log`" 2>&1"
    "[$(Get-Date -Format HH:mm:ss)] $m finished, exit code $LASTEXITCODE" | Out-File $log -Append -Encoding utf8
}
"[$(Get-Date -Format HH:mm:ss)] ALL DONE" | Out-File $log -Append -Encoding utf8
