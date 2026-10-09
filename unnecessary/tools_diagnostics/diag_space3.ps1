# READ-ONLY: NTFS allocation report for D: and every process holding files open on D:. Writes diag_space3.txt.
$out = 'D:\geoguessers_data\tools\diag_space3.txt'
& {
    '=== fsutil volume allocationreport D:'; fsutil volume allocationreport D:
    '=== open handles on D: (handle64)'
    & 'D:\geoguessers_data\tools\handle64.exe' -accepteula -nobanner 'D:\'
} *>&1 | Out-File $out -Encoding utf8
