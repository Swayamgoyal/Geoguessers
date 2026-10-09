"""Download Copernicus GLO-30 and GLO-90 from OpenTopography for the study area (HMA tile-571 extent).

Usage:
    set OPENTOPO_API_KEY=<your key>        (PowerShell: $env:OPENTOPO_API_KEY = "<your key>")
    python datasets/download_cop.py
"""
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# HMA_DEM8m_MOS tile-571 is W 79.1250 S 30.0333 E 80.2352 N 30.9701; pad by ~2 km so
# the reprojected 30/90 m grids fully cover the 8 m tile.
BBOX = dict(west=79.10, south=30.01, east=80.26, north=30.99)
DEMS = {"COP30": "cop30_tile571.tif", "COP90": "cop90_tile571.tif"}
API = "https://portal.opentopography.org/API/globaldem"
OUT_DIR = Path(__file__).resolve().parent


def main():
    key = os.environ.get("OPENTOPO_API_KEY")
    if not key:
        sys.exit("Set OPENTOPO_API_KEY first.")
    for demtype, name in DEMS.items():
        out = OUT_DIR / name
        if out.exists():
            print(f"{name} exists, skipping")
            continue
        url = API + "?" + urllib.parse.urlencode({"demtype": demtype, "outputFormat": "GTiff", "API_Key": key, **BBOX})
        print(f"downloading {demtype} -> {out}")
        with urllib.request.urlopen(url, timeout=600) as r, open(out, "wb") as f:
            f.write(r.read())
        print(f"  {out.stat().st_size / 2**20:.1f} MB")


if __name__ == "__main__":
    main()
