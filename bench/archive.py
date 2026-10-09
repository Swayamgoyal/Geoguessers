"""Move large run files (> 1 GB) to the external archive drive so the internal disk does not fill up.

Same rule as bench/archive_large.ps1: copy, check SHA-256, only then remove from the laptop. Never called
while a measurement is running. If the archive drive is not connected the file simply stays where it is.
"""
import hashlib
import os
import shutil
from pathlib import Path

ARCHIVE = Path(os.environ.get("GEO_ARCHIVE", r"K:\spatial project"))
MIN_BYTES = 2**30  # 1 GB


def _sha256(path, chunk=16 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def archive_large(path, subfolder):
    """Move one file to ARCHIVE/subfolder if it is larger than 1 GB. Returns a short status string."""
    path = Path(path)
    if not path.exists() or path.stat().st_size <= MIN_BYTES:
        return f"kept {path.name} (small or missing)"
    if not ARCHIVE.exists():
        return f"kept {path.name}: archive drive {ARCHIVE} not connected"
    dst = ARCHIVE / subfolder / path.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, dst)
    if _sha256(path) != _sha256(dst):
        dst.unlink()
        return f"kept {path.name}: checksum mismatch after copy"
    path.unlink()
    return f"moved {path.name} ({dst.stat().st_size / 2**30:.1f} GB) -> {dst}"
