"""Write results/machine.json describing the benchmark machine and software versions."""
import json
import platform
import subprocess
import sys
from datetime import datetime
from importlib import metadata
from pathlib import Path

import psutil

PACKAGES = ["numpy", "numba", "cupy", "rasterio", "GDAL", "xarray-spatial", "rio-tiler", "fastapi"]


def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def cpu_name():
    if platform.system() == "Windows":
        out = run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"])
        if out:
            return out
    return platform.processor()


def gpus():
    out = run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"])
    if not out:
        return []
    return [dict(zip(["name", "memory_total", "driver"], (s.strip() for s in line.split(","))))
            for line in out.splitlines()]


def versions():
    v = {}
    for pkg in PACKAGES:
        try:
            v[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            v[pkg] = None
    v["gdalinfo"] = run(["gdalinfo", "--version"])
    return v


def main():
    info = {
        "machine_id": platform.node(),
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "os": platform.platform(),
        "cpu": cpu_name(),
        "cores_physical": psutil.cpu_count(logical=False),
        "cores_logical": psutil.cpu_count(logical=True),
        "ram_gb": round(psutil.virtual_memory().total / 2**30, 1),
        "gpus": gpus(),
        "python": sys.version.split()[0],
        "packages": versions(),
    }
    out = Path(__file__).resolve().parents[1] / "results" / "machine.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(info, indent=2))
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
