"""Tiled engine: process a whole DEM window by window with any backend, writing one GeoTIFF per product.

    from demlab.engine import run
    run("in.tif", {"slope": "out_slope.tif", "hillshade": "out_hs.tif"}, backend="numba", method="Horn")

Backends: "numpy" (reference, single thread), "numba" (parallel CPU, fused products), "cupy" (GPU).
Reading: a pool of reader threads decompresses upcoming windows while the current one is computed (GDAL
releases Python's lock while decoding). Writing happens in the main thread, in window order.
Returns per-stage timings so experiments can report read / compute / write separately.
"""
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import rasterio

from demlab.io import grid_info, read_with_halo, windows
from demlab.kernels import numba_k, numpy_k

OUT_DTYPE = {"hillshade": "uint8"}
OUT_NODATA = {"hillshade": 0}


def _compute(backend, ops, z, res, method, nodata):
    if backend == "numba":
        return numba_k.compute_many(ops, z, res, method, nodata)
    if backend == "numpy":
        return {op: numpy_k.compute(op, z, res, method, nodata) for op in ops}
    if backend == "cupy":
        import cupy as cp
        zg = cp.asarray(z)
        out = {op: cp.asnumpy(numpy_k.compute(op, zg, res, method, nodata, xp=cp)) for op in ops}
        return out
    raise ValueError(backend)


def run(src_path, outputs, backend="numba", method="Horn", window=2048, readers=4, threads=None,
        write=True, creation_options=None):
    """outputs: {op: path}. method applies to slope/aspect/hillshade ("Horn"/"ZevenbergenThorne") or TRI
    ("Riley"/"Wilson"). write=False computes but discards results (to time compute without output)."""
    if threads and backend == "numba":
        import numba
        numba.set_num_threads(threads)
    co = creation_options or {"tiled": True, "blockxsize": 512, "blockysize": 512}
    t = {"read": 0.0, "compute": 0.0, "write": 0.0}
    t0 = time.perf_counter()
    with rasterio.open(src_path) as src:
        info = grid_info(src)
        wins = list(windows(info.width, info.height, window))
        dsts = {}
        if write:
            for op, path in outputs.items():
                prof = info.profile.copy()
                prof.update(driver="GTiff", count=1, dtype=OUT_DTYPE.get(op, "float32"),
                            nodata=OUT_NODATA.get(op, numpy_k.NODATA), compress=None, BIGTIFF="IF_SAFER", **co)
                prof.pop("blockxsize", None) if not co.get("tiled") else None
                dsts[op] = rasterio.open(path, "w", **prof)

        def load(win):
            # each reader thread opens its own handle: rasterio datasets are not thread-safe
            ts = time.perf_counter()
            with rasterio.open(src_path) as s:
                z = read_with_halo(s, win, info.nodata)
            return z, time.perf_counter() - ts

        try:
            with ThreadPoolExecutor(max_workers=readers) as pool:
                futures = [pool.submit(load, w) for w in wins]
                for win, fut in zip(wins, futures):
                    tw = time.perf_counter()
                    z, read_s = fut.result()
                    t["read"] += time.perf_counter() - tw  # time spent waiting for data
                    tc = time.perf_counter()
                    res = _compute(backend, list(outputs), z, info.res, method, info.nodata)
                    t["compute"] += time.perf_counter() - tc
                    if write:
                        tw = time.perf_counter()
                        r, c, h, w = win
                        for op, arr in res.items():
                            dsts[op].write(arr, 1, window=rasterio.windows.Window(c, r, w, h))
                        t["write"] += time.perf_counter() - tw
        finally:
            tw = time.perf_counter()
            for d in dsts.values():
                d.close()
            t["write"] += time.perf_counter() - tw
    t["total"] = time.perf_counter() - t0
    t["cells"] = info.width * info.height
    t["windows"] = len(wins)
    return t
