"""Reproject the real DEMs onto aligned UTM 44N grids and write them as COGs with overviews.

Outputs go under $GEO_DATA (default D:\\geoguessers_data):
    prepared/tile571_90m.tif, tile571_30m.tif, tile571_8m.tif   (HMA tile-571 extent)
    prepared/chamoli_2m.tif                                      (Chamoli 2 m composite extent)
    synthetic/tile571_2m_cubic.tif, tile571_1m_cubic.tif         (--synthetic only; TIMING ONLY,
        cubic upsample of prepared/tile571_8m.tif: ~10 GB and ~40 GB uncompressed)

Grids are snapped to multiples of 360 m (divisible by 90, 30, 8 and 2), so every
grid shares the same origin.  Reprojection is bilinear, except chamoli_2m (nearest,
see JOBS).  Overviews (the pyramid) use AVERAGE resampling.

Usage:  python datasets/prepare.py [--force] [--synthetic]
"""
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
from osgeo import gdal, osr

gdal.UseExceptions()

# Raw downloads (only read here, never benchmarked) live in this datasets/ folder; $GEO_RAW overrides it.
HERE = Path(os.environ.get("GEO_RAW", Path(__file__).resolve().parent))
ROOT = Path(os.environ.get("GEO_DATA", r"D:\geoguessers_data"))
OUT = ROOT / "prepared"
SYN = ROOT / "synthetic"
DST_EPSG = 32644  # WGS 84 / UTM 44N
SNAP = 360
NODATA = -9999.0

TILE_SRC = HERE / "HMA_DEM8m_MOS_20170716_tile-571.tif"
CHAMOLI_SRC = HERE / "Chamoli_Sept2015_Composite_DEM2m_wmean.tif"

# (output name, source, resolution m, extent source, resampling)
# chamoli_2m uses "near": the source is already 2 m UTM 44N, offset from our grid by only
# 0.09 / 0.16 m, so nearest keeps every elevation value unchanged (bilinear would smooth
# the dataset we use as accuracy truth).
JOBS = [
    (OUT / "tile571_90m.tif", HERE / "cop90_tile571.tif", 90, TILE_SRC, "bilinear"),
    (OUT / "tile571_30m.tif", HERE / "cop30_tile571.tif", 30, TILE_SRC, "bilinear"),
    (OUT / "tile571_8m.tif", TILE_SRC, 8, TILE_SRC, "bilinear"),
    (OUT / "chamoli_2m.tif", CHAMOLI_SRC, 2, CHAMOLI_SRC, "near"),
]
# Timing-only grids, cubic (nearest/bilinear distort compression and IO; see PROJECT_PLAN §3.6)
SYNTHETIC_JOBS = [
    (SYN / "tile571_2m_cubic.tif", OUT / "tile571_8m.tif", 2, TILE_SRC, "cubic"),
    (SYN / "tile571_1m_cubic.tif", OUT / "tile571_8m.tif", 1, TILE_SRC, "cubic"),
]

COG_OPTS = ["BLOCKSIZE=512", "COMPRESS=ZSTD", "PREDICTOR=FLOATING_POINT", "LEVEL=9",
            "OVERVIEW_RESAMPLING=AVERAGE", "NUM_THREADS=ALL_CPUS", "BIGTIFF=IF_SAFER"]


def utm_extent(path):
    """Bounds of a raster in UTM 44N, shrunk inward to the SNAP grid (so no padding cells)."""
    ds = gdal.Open(str(path))
    srs = osr.SpatialReference(wkt=ds.GetProjection())
    dst = osr.SpatialReference()
    dst.ImportFromEPSG(DST_EPSG)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    gt = ds.GetGeoTransform()
    xmin, ymax = gt[0], gt[3]
    xmax, ymin = xmin + gt[1] * ds.RasterXSize, ymax + gt[5] * ds.RasterYSize
    xmin, ymin, xmax, ymax = osr.CoordinateTransformation(srs, dst).TransformBounds(xmin, ymin, xmax, ymax, 21)
    return (math.ceil(xmin / SNAP) * SNAP, math.ceil(ymin / SNAP) * SNAP,
            math.floor(xmax / SNAP) * SNAP, math.floor(ymax / SNAP) * SNAP)


def complete(path):
    """False if the file is still downloading / truncated: its last block cannot be read."""
    try:
        ds = gdal.Open(str(path))  # keep a reference, or the band is invalidated
        b = ds.GetRasterBand(1)
        bx, by = b.GetBlockSize()
        b.ReadAsArray((b.XSize - 1) // bx * bx, (b.YSize - 1) // by * by, 1, 1)
        return True
    except RuntimeError:
        return False


def summarize(path):
    ds = gdal.Open(str(path))
    b = ds.GetRasterBand(1)
    lo, hi = b.ComputeRasterMinMax(False)  # exact, full resolution
    # valid fraction from the finest overview at most ~4000 px wide keeps this fast on large grids
    ovs = [b.GetOverview(i) for i in range(b.GetOverviewCount())]
    small = [o for o in ovs if o.XSize <= 4000]
    a = (small[0] if small else ovs[-1] if ovs else b).ReadAsArray()
    mb = path.stat().st_size / 2**20
    print(f"  {ds.RasterXSize} x {ds.RasterYSize} = {ds.RasterXSize * ds.RasterYSize:,} cells, "
          f"{mb:.0f} MB on disk, ~{100 * (a != NODATA).mean():.1f}% valid, elev {lo:.0f}..{hi:.0f} m, "
          f"overviews: {[b.GetOverview(i).XSize for i in range(b.GetOverviewCount())]}")


def main():
    force = "--force" in sys.argv
    jobs = JOBS + (SYNTHETIC_JOBS if "--synthetic" in sys.argv else [])
    for dst, src, res, extent_src, resample in jobs:
        dst.parent.mkdir(parents=True, exist_ok=True)
        name = dst.name
        if not src.exists() or not extent_src.exists():
            print(f"{name}: source missing ({src.name}), skipping")
            continue
        if not complete(src):
            print(f"{name}: source incomplete ({src.name} still downloading?), skipping")
            continue
        if dst.exists() and not force:
            print(f"{name}: exists, skipping (use --force to rebuild)")
            summarize(dst)
            continue
        te = utm_extent(extent_src)
        print(f"{name}: {src.name} -> {res} m, extent {te}")
        t = time.perf_counter()
        gdal.Warp(str(dst), str(src), options=gdal.WarpOptions(
            format="COG", dstSRS=f"EPSG:{DST_EPSG}", outputBounds=te, xRes=res, yRes=res,
            resampleAlg=resample, dstNodata=NODATA, outputType=gdal.GDT_Float32, multithread=True,
            warpMemoryLimit=2048,
            warpOptions=["NUM_THREADS=ALL_CPUS"], creationOptions=COG_OPTS))
        print(f"  done in {time.perf_counter() - t:.1f} s")
        summarize(dst)


if __name__ == "__main__":
    main()
