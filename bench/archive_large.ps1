# Moves LARGE files (default > 1 GB) produced by runs from a data folder to the external drive, so the internal
# disk does not fill up. Use only after the run's results are recorded in results\runs.csv. Each file is copied,
# checked by SHA-256, and only then removed from the source. Small files are never moved.
#   powershell -ExecutionPolicy Bypass -File bench\archive_large.ps1 -Source D:\geoguessers_data\e2
param(
    [Parameter(Mandatory = $true)][string]$Source,
    [string]$Archive = $(if ($env:GEO_ARCHIVE) { $env:GEO_ARCHIVE } else { 'K:\spatial project' }),
    [double]$MinGB = 1
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path $Archive)) { Write-Error "Archive $Archive not found: connect the external drive"; exit 1 }
$dest = Join-Path $Archive (Split-Path $Source -Leaf)
$big = Get-ChildItem -LiteralPath $Source -Recurse -File | Where-Object { $_.Length -gt $MinGB * 1GB }
foreach ($f in $big) {
    $target = $dest + $f.FullName.Substring($Source.TrimEnd('\').Length)
    New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
    Copy-Item -LiteralPath $f.FullName $target -Force
    if ((Get-FileHash -LiteralPath $f.FullName).Hash -eq (Get-FileHash -LiteralPath $target).Hash) {
        Remove-Item -LiteralPath $f.FullName -Force
        "{0,8:N2} GB  moved  {1}" -f ($f.Length / 1GB), $target
    } else {
        Remove-Item -LiteralPath $target -Force
        "MISMATCH, kept original: $($f.FullName)"
    }
}
"{0} large file(s) handled; smaller files left in place" -f @($big).Count
