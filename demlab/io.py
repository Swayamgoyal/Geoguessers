"""Window-by-window raster access with a halo, so 3x3 operators are exact at window edges.

A window is (row_off, col_off, height, width) in the full grid. read_with_halo returns the window plus one
extra cell on every side; outside the grid the halo is filled with nodata, which reproduces gdaldem's
behaviour of leaving the outermost ring as nodata.
"""
from dataclasses import dataclass

import numpy as np
import rasterio
from rasterio.windows import Window

HALO = 1


@dataclass
class GridInfo:
    width: int
    height: int
    res: float
    nodata: float
    profile: dict


def grid_info(src):
    res_x, res_y = src.res
    if abs(res_x - res_y) > 1e-9:
        raise ValueError(f"non-square cells {src.res}: reproject first")
    nodata = src.nodata if src.nodata is not None else -9999.0
    return GridInfo(src.width, src.height, res_x, nodata, src.profile.copy())


def windows(width, height, size):
    """Tile the grid into size x size windows (the last row/column may be smaller)."""
    for r in range(0, height, size):
        for c in range(0, width, size):
            yield r, c, min(size, height - r), min(size, width - c)


def read_with_halo(src, win, nodata, dtype=np.float64):
    """Window plus a 1-cell halo, as float64; cells outside the grid are nodata."""
    r, c, h, w = win
    rw = Window(c - HALO, r - HALO, w + 2 * HALO, h + 2 * HALO)
    a = src.read(1, window=rw, boundless=True, fill_value=nodata, out_dtype=dtype)
    return a
