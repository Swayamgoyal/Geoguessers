"""Tiled engine: process a whole DEM window by window with any backend, writing one GeoTIFF per product.

    from demlab.engine import run
    run("in.tif", {"slope": "out_slope.tif", "hillshade": "out_hs.tif"}, backend="numba", method="Horn")

Backends: "numpy" (reference, single thread), "numba" (parallel CPU, fused products), "cupy" (GPU).

Pipeline (three stages overlap, memory stays bounded whatever the grid size):
  readers  : `readers` threads, each with its own dataset handle (GDAL datasets are not thread-safe), decode
             windows ahead of time; at most `prefetch` windows are held in memory.
  compute  : the calling thread runs the kernel (Numba spreads it over the cores).
  writer   : ONE thread owns all output datasets and writes in window order. GDAL warns that writing several
             datasets from several threads contends on the block-cache lock, and handles must not be shared.
             At most `prefetch` results wait for it.
Timings: read = compute thread waiting for data, compute = kernel time, write = compute thread waiting for the
writer (back-pressure) plus closing the files; writer_busy = time the writer thread spent writing.
"""
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import rasterio
from rasterio.windows import Window

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
        return {op: cp.asnumpy(numpy_k.compute(op, zg, res, method, nodata, xp=cp)) for op in ops}
    raise ValueError(backend)


def _out_profile(info, op, compress, co):
    prof = info.profile.copy()
    for k in ("compress", "predictor", "zstd_level", "interleave", "blockxsize", "blockysize", "tiled"):
        prof.pop(k, None)
    dtype = OUT_DTYPE.get(op, "float32")
    prof.update(driver="GTiff", count=1, dtype=dtype, nodata=OUT_NODATA.get(op, numpy_k.NODATA),
                BIGTIFF="IF_SAFER", tiled=True, blockxsize=512, blockysize=512)
    if compress:
        prof.update(compress=compress, num_threads="ALL_CPUS",
                    predictor=3 if dtype == "float32" else 2)
    prof.update(co or {})
    return prof


def run(src_path, outputs, backend="numba", method="Horn", window=2048, readers=4, prefetch=6, threads=None,
        write=True, compress=None, creation_options=None):
    """outputs: {op: path}. method applies to slope/aspect/hillshade ("Horn"/"ZevenbergenThorne") or TRI
    ("Riley"/"Wilson"). write=False computes but discards results (to time compute without output).
    compress: None (uncompressed) or e.g. "ZSTD" (GDAL compresses with multiple threads)."""
    if threads and backend == "numba":
        import numba
        numba.set_num_threads(threads)
    t = {"read": 0.0, "compute": 0.0, "write": 0.0, "writer_busy": 0.0}
    t0 = time.perf_counter()
    with rasterio.open(src_path) as src:
        info = grid_info(src)
    wins = list(windows(info.width, info.height, window))

    local = threading.local()
    handles, handles_lock = [], threading.Lock()

    def load(win):
        if not hasattr(local, "src"):  # one handle per reader thread, reused for all its windows
            local.src = rasterio.open(src_path)
            with handles_lock:
                handles.append(local.src)
        return read_with_halo(local.src, win, info.nodata)

    wq = queue.Queue(maxsize=prefetch)
    writer_error = []

    def writer(dsts):
        try:
            while True:
                item = wq.get()
                if item is None:
                    return
                (r, c, h, w), res = item
                tb = time.perf_counter()
                for op, arr in res.items():
                    dsts[op].write(arr, 1, window=Window(c, r, w, h))
                t["writer_busy"] += time.perf_counter() - tb
        except Exception as e:  # surface in the main thread
            writer_error.append(e)
            while wq.get() is not None:  # drain so the producer never blocks forever
                pass

    dsts = {}
    wthread = None
    try:
        if write:
            dsts = {op: rasterio.open(path, "w", **_out_profile(info, op, compress, creation_options))
                    for op, path in outputs.items()}
            wthread = threading.Thread(target=writer, args=(dsts,), daemon=True)
            wthread.start()
        with ThreadPoolExecutor(max_workers=readers) as pool:
            pending = [pool.submit(load, w) for w in wins[:prefetch]]
            nxt = len(pending)
            for i, win in enumerate(wins):
                tw = time.perf_counter()
                z = pending[i].result()
                pending[i] = None  # free the window once used
                t["read"] += time.perf_counter() - tw
                if nxt < len(wins):  # keep at most `prefetch` windows in flight
                    pending.append(pool.submit(load, wins[nxt]))
                    nxt += 1
                tc = time.perf_counter()
                res = _compute(backend, list(outputs), z, info.res, method, info.nodata)
                t["compute"] += time.perf_counter() - tc
                if write:
                    if writer_error:
                        raise writer_error[0]
                    tw = time.perf_counter()
                    wq.put((win, res))
                    t["write"] += time.perf_counter() - tw
    finally:
        tw = time.perf_counter()
        if wthread is not None:
            wq.put(None)
            wthread.join()
        for d in dsts.values():
            d.close()
        for h in handles:
            h.close()
        t["write"] += time.perf_counter() - tw
    if writer_error:
        raise writer_error[0]
    t["total"] = time.perf_counter() - t0
    t["cells"] = info.width * info.height
    t["windows"] = len(wins)
    return t
