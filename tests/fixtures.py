"""Small test grids cut from the prepared benchmark data, and gdaldem reference outputs for them.

Crops are 1024 x 1024 cells, written to $GEO_DATA/test_fixtures (created on first use):
  8m_gaps    : 8 m tile, south-east area with nodata gaps (tests nodata handling)
  chamoli_2m : real 2 m data, steep valley (tests steep slopes)
"""
import os
import subprocess
from pathlib import Path

import numpy as np
import rasterio

DATA = Path(os.environ.get("GEO_DATA", r"D:\geoguessers_data"))
FIX = DATA / "test_fixtures"
CROPS = {
    # name: (source, xoff, yoff) for a 1024 x 1024 -srcwin
    "8m_gaps": (DATA / "prepared" / "tile571_8m.tif", 11500, 10500),
    "chamoli_2m": (DATA / "prepared" / "chamoli_2m.tif", 7000, 8000),
}
SIZE = 1024
OPS = [("slope", "Horn"), ("slope", "ZevenbergenThorne"), ("aspect", "Horn"), ("aspect", "ZevenbergenThorne"),
       ("hillshade", "Horn"), ("hillshade", "ZevenbergenThorne"), ("TRI", "Riley"), ("TRI", "Wilson"),
       ("TPI", ""), ("roughness", "")]


def crop(name):
    """Path of the crop GeoTIFF (uncompressed, tiled), created if missing."""
    FIX.mkdir(parents=True, exist_ok=True)
    out = FIX / f"{name}.tif"
    if not out.exists():
        src, x, y = CROPS[name]
        subprocess.run(["gdal_translate", "-q", "-srcwin", str(x), str(y), str(SIZE), str(SIZE),
                        "-co", "TILED=YES", str(src), str(out)], check=True)
    return out


def gdaldem_ref(name, op, method):
    """gdaldem output for a crop (default options, i.e. no -compute_edges), as an array."""
    tag = f"{op}_{method}" if method else op
    out = FIX / f"{name}__{tag}.tif"
    if not out.exists():
        cmd = ["gdaldem", op, str(crop(name)), str(out), "-q"]
        if method:
            cmd += ["-alg", method]
        subprocess.run(cmd, check=True)
    with rasterio.open(out) as ds:
        return ds.read(1), ds.nodata


def load(name):
    with rasterio.open(crop(name)) as ds:
        return ds.read(1).astype(np.float64), ds.res[0], ds.nodata
