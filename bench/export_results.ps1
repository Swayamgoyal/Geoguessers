# Copies computed results (results\: runs.csv, tables, plots, env snapshots, machine.json) and any sweep logs
# to the external archive. Results stay in the repo too (they are committed); the archive is the off-laptop copy.
# Sweep logs (*_log.txt on the data drive) are moved, not copied: they are not needed on the laptop.
#   powershell -ExecutionPolicy Bypass -File bench\export_results.ps1
$archive = if ($env:GEO_ARCHIVE) { $env:GEO_ARCHIVE } else { 'K:\spatial project' }
$data = if ($env:GEO_DATA) { $env:GEO_DATA } else { 'D:\geoguessers_data' }
if (-not (Test-Path $archive)) { Write-Error "Archive $archive not found: connect the external drive"; exit 1 }
$repo = Split-Path $PSScriptRoot -Parent
robocopy (Join-Path $repo 'results') (Join-Path $archive 'results_export') /E /COPY:DAT /R:2 /W:5 /NP /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) { Write-Error "robocopy failed ($LASTEXITCODE)"; exit 1 }
Get-ChildItem $data -Filter '*_log.txt' -File -ErrorAction SilentlyContinue | ForEach-Object {
    Move-Item $_.FullName (Join-Path $archive 'logs') -Force
}
"exported results to $archive\results_export"
