# READ-ONLY: size of every top-level item on D: (incl. hidden/system) and the 25 largest files. Writes diag_space2.txt.
$out = 'D:\geoguessers_data\tools\diag_space2.txt'
& {
    '=== top-level items on D: (GB)'
    Get-ChildItem D:\ -Force -ErrorAction SilentlyContinue | ForEach-Object {
        $s = if ($_.PSIsContainer) { (Get-ChildItem -LiteralPath $_.FullName -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum } else { $_.Length }
        [pscustomobject]@{ GB = [math]::Round($s / 1GB, 2); Name = $_.Name; Attr = $_.Attributes }
    } | Sort-Object GB -Descending | Format-Table -AutoSize | Out-String -Width 250
    '=== 25 largest files on D:'
    Get-ChildItem D:\ -Recurse -Force -File -ErrorAction SilentlyContinue | Sort-Object Length -Descending |
        Select-Object -First 25 @{n='GB'; e={[math]::Round($_.Length / 1GB, 2)}}, FullName | Format-Table -AutoSize | Out-String -Width 300
    '=== access errors during scan (first 15)'
    Get-ChildItem D:\ -Recurse -Force -ErrorAction SilentlyContinue -ErrorVariable errs | Out-Null
    $errs | Select-Object -First 15 | ForEach-Object { $_.TargetObject }
} *>&1 | Out-File $out -Encoding utf8
