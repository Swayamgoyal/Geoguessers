# Copy the GeoGuessers terrain plugin into a QGIS profile (default profile unless -Profile is given).
#   powershell -ExecutionPolicy Bypass -File qgis_plugin\install.ps1 [-Profile default]
# Then in QGIS: Plugins > Manage and Install Plugins > Installed > tick "GeoGuessers terrain".
param([string]$Profile = "default")

$src = Join-Path $PSScriptRoot "geoguessers_view"
$plugins = Join-Path $env:APPDATA "QGIS\QGIS3\profiles\$Profile\python\plugins"
$dst = Join-Path $plugins "geoguessers_view"
New-Item -ItemType Directory -Force $plugins | Out-Null
if (Test-Path $dst) {
    # keep the previous copy instead of overwriting it
    $old = "$dst.previous_" + (Get-Date -Format "yyyyMMdd_HHmmss")
    Move-Item $dst $old
    Write-Host "Previous copy moved to $old"
}
Copy-Item -Recurse $src $dst
Get-ChildItem $dst -Recurse -Include "__pycache__" | Remove-Item -Recurse -Force -Confirm:$false
Write-Host "Installed to $dst"
