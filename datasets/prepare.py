"""Reproject the real DEMs onto aligned UTM 44N grids and write them as COGs with overviews.

Outputs go to $GEO_DATA/prepared (default D:\\geoguessers_data\\prepared):
    tile571_90m.tif, tile571_30m.tif, tile571_8m.tif   (HMA tile-571 extent)
    chamoli_2m.tif                                      (Chamoli 2 m composite extent)

Grids are snapped to multiples of 360 m (divisible by 90, 30, 8 and 2), so every
grid shares the same origin.  Overviews (the pyramid) use AVERAGE resampling.

Usage:  python datasets/prepare.py [--force]
"""
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
from osgeo import gdal, osr

gdal.UseExceptions()

HERE = Path(__file__).resolve().parent
OUT = Path(os.environ.get("GEO_DATA", r"D:\geoguessers_data")) / "prepared"
DST_EPSG = 32644  # WGS 84 / UTM 44N
SNAP = 360
NODATA = -9999.0

TILE_SRC = HERE / "HMA_DEM8m_MOS_20170716_tile-571.tif"
CHAMOLI_SRC = HERE / "Chamoli_Sept2015_Composite_DEM2m_wmean.tif"

# (output name, source, resolution m, extent source)
JOBS = [
    ("tile571_90m.tif", HERE / "cop90_tile571.tif", 90, TILE_SRC),
    ("tile571_30m.tif", HERE / "cop30_tile571.tif", 30, TILE_SRC),
    ("tile571_8m.tif", TILE_SRC, 8, TILE_SRC),
    ("chamoli_2m.tif", CHAMOLI_SRC, 2, CHAMOLI_SRC),
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
    # valid fraction from the first overview keeps this fast on large grids
    a = (b.GetOverview(0) if b.GetOverviewCount() else b).ReadAsArray()
    mb = path.stat().st_size / 2**20
    print(f"  {ds.RasterXSize} x {ds.RasterYSize} = {ds.RasterXSize * ds.RasterYSize:,} cells, "
          f"{mb:.0f} MB on disk, ~{100 * (a != NODATA).mean():.1f}% valid, elev {lo:.0f}..{hi:.0f} m, "
          f"overviews: {[b.GetOverview(i).XSize for i in range(b.GetOverviewCount())]}")


def main():
    force = "--force" in sys.argv
    OUT.mkdir(parents=True, exist_ok=True)
    for name, src, res, extent_src in JOBS:
        dst = OUT / name
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
            resampleAlg="bilinear", dstNodata=NODATA, outputType=gdal.GDT_Float32, multithread=True,
            warpOptions=["NUM_THREADS=ALL_CPUS"], creationOptions=COG_OPTS))
        print(f"  done in {time.perf_counter() - t:.1f} s")
        summarize(dst)


if __name__ == "__main__":
    main()
