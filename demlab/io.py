"""Window-by-window raster access with a halo, so 3x3 operators are exact at window edges.

A window is (row_off, col_off, height, width) in the full grid. read_with_halo returns the window plus one
extra cell on every side; outside the grid the halo is filled with nodata, which reproduces gdaldem's
behaviour of leaving the outermost ring as nodata.
"""
from dataclasses import dataclass

import numpy as np
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
    """Window plus a 1-cell halo, as `dtype`; cells outside the grid are nodata.

    Reads only the part inside the grid and pads the rest itself: rasterio's boundless=True read goes through a
    virtual warped raster and is several times slower."""
    r, c, h, w = win
    r0, c0 = max(r - HALO, 0), max(c - HALO, 0)
    r1, c1 = min(r + h + HALO, src.height), min(c + w + HALO, src.width)
    out = np.full((h + 2 * HALO, w + 2 * HALO), nodata, dtype=dtype)
    out[r0 - (r - HALO):r1 - (r - HALO), c0 - (c - HALO):c1 - (c - HALO)] = \
        src.read(1, window=Window(c0, r0, c1 - c0, r1 - r0))
    return out
