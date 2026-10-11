"""Pyramid (COG overview) access for on-demand derivatives, and exact block aggregation for checking them.

Level 0 is the full-resolution grid; level k is the k-th overview, built by GDAL with AVERAGE resampling. GDAL
halves each overview's size from the previous one, rounding down (Chamoli 2 m: 17460 rows -> 8730 -> 4365 ->
2182 -> 1091 ...), and every level keeps the full extent. So a level's cells are only *nearly* 2^k fine cells
wide when the grid size is not divisible by 2^k (2182 rows over 17460 fine rows = 8.0018 fine rows each). The
footprint of a coarse cell is therefore taken from the geometry: the fine cells whose centres fall inside it.

    with level_dataset(path, k) as ds: ...            # the overview as an ordinary rasterio dataset
    edges = footprint_edges(n_fine, n_coarse)          # fine-cell boundaries of every coarse cell
    sums, counts = block_sums(a, valid, row_edges, col_edges)
"""
import math

import numpy as np
import rasterio


def level_dataset(path, level):
    """Open pyramid level `level` (0 = full resolution) as a rasterio dataset."""
    return rasterio.open(path) if level == 0 else rasterio.open(path, overview_level=level - 1)


def level_res(ds):
    """One cell size for a level. Overview cells can be very slightly non-square (rows and columns are rounded
    separately; at most 0.04 % apart on our grids); the geometric mean is used for the slope formula."""
    return math.sqrt(abs(ds.res[0] * ds.res[1]))


def footprint_edges(n_fine, n_coarse, start=0, stop=None):
    """Fine-cell index boundaries of coarse cells start..stop-1: coarse cell i covers fine cells
    [edges[i - start], edges[i - start + 1]), i.e. those whose centres lie inside it. Exact blocks of
    n_fine / n_coarse cells when that ratio is an integer."""
    stop = n_coarse if stop is None else stop
    r = n_fine / n_coarse
    i = np.arange(start, stop + 1, dtype=np.float64)
    return np.minimum(np.ceil(i * r - 0.5).astype(np.int64), n_fine)


def block_sums(a, valid, row_edges, col_edges, dtype=np.float64, chunk_rows=2048):
    """Sum of a[valid] and count of valid cells over every footprint rectangle; the edges index into a.
    Works through about `chunk_rows` fine rows at a time, so temporaries stay small on very large grids."""
    c0, c1 = col_edges[0], col_edges[-1]
    ce = col_edges[:-1] - c0
    n = len(row_edges) - 1
    sums = np.empty((n, len(ce)), dtype)
    counts = np.empty((n, len(ce)), np.int64)
    i = 0
    while i < n:
        j = i + 1
        while j < n and row_edges[j + 1] - row_edges[i] <= chunk_rows:
            j += 1
        rows = slice(row_edges[i], row_edges[j])
        av, vv = a[rows, c0:c1], valid[rows, c0:c1]
        re = row_edges[i:j] - row_edges[i]
        x = np.where(vv, av, 0).astype(dtype, copy=False)
        sums[i:j] = np.add.reduceat(np.add.reduceat(x, re, axis=0), ce, axis=1)
        counts[i:j] = np.add.reduceat(np.add.reduceat(vv.astype(np.int32), re, axis=0), ce, axis=1)
        i = j
    return sums, counts


def block_area(row_edges, col_edges):
    """Number of fine cells in every footprint rectangle."""
    return np.outer(np.diff(row_edges), np.diff(col_edges))
