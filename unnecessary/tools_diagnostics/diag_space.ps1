# READ-ONLY diagnostics for unexplained used space on D: (run as admin). Writes diag_space.txt.
$out = 'D:\geoguessers_data\tools\diag_space.txt'
& {
    '=== vssadmin list shadowstorage'; vssadmin list shadowstorage
    '=== vssadmin list shadows /for=D:'; vssadmin list shadows /for=D:
    '=== System Volume Information size (D:)'
    $s = (Get-ChildItem 'D:\System Volume Information' -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
    "{0:N1} GB" -f ($s / 1GB)
    '=== largest files in System Volume Information'
    Get-ChildItem 'D:\System Volume Information' -Recurse -Force -File -ErrorAction SilentlyContinue |
        Sort-Object Length -Descending | Select-Object -First 10 FullName, @{n='GB'; e={[math]::Round($_.Length / 1GB, 2)}} | Format-Table -AutoSize | Out-String -Width 250
    '=== $RECYCLE.BIN size (all users)'
    $r = (Get-ChildItem 'D:\$RECYCLE.BIN' -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
    "{0:N1} GB" -f ($r / 1GB)
    '=== fsutil volume diskfree D:'; fsutil volume diskfree D:
    '=== System Restore protection'; Get-ComputerRestorePoint -ErrorAction SilentlyContinue | Select-Object SequenceNumber, Description | Format-Table | Out-String
} *>&1 | Out-File $out -Encoding utf8
