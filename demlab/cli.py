"""Command line for the engine, so the benchmark harness can measure it as a separate process (like gdaldem).

    python -m demlab.cli <dem.tif> --ops slope[,aspect,...] --out-dir DIR [--impl numba|numpy|naive]
                         [--method Horn] [--threads N] [--window 2048] [--no-write] [--compress ZSTD --zstd-level 1]

impl:
  numba : tiled pipeline, parallel fused kernel (our engine)
  numpy : tiled pipeline, NumPy reference kernel (single-threaded)
  naive : the simplest possible program: read the WHOLE grid into memory, compute with NumPy, write. No tiling.
          Expected to run out of memory once the grid no longer fits in RAM (the "memory-hungry approach").
Prints one JSON line at the end: {"t_internal": seconds after imports, "read": ..., "compute": ..., ...}.
"""
import argparse
import json
import time

T_START = time.perf_counter()

import numpy as np  # noqa: E402
import rasterio  # noqa: E402

from demlab.engine import OUT_DTYPE, OUT_NODATA, run  # noqa: E402
from demlab.kernels import numpy_k  # noqa: E402


def naive(src_path, outputs, method, write):
    """Whole-array version: one read, one compute per product, one write. Peak memory ~ many x grid size."""
    t = {}
    t0 = time.perf_counter()
    with rasterio.open(src_path) as src:
        z = src.read(1)  # float32, the whole grid
        prof = src.profile.copy()
        nodata = src.nodata if src.nodata is not None else -9999.0
        res = src.res[0]
    z = np.pad(z, 1, constant_values=nodata)  # halo of nodata around the grid, like gdaldem's edge
    t["read"] = time.perf_counter() - t0
    t1 = time.perf_counter()
    results = {op: numpy_k.compute(op, z, res, method, nodata) for op in outputs}
    t["compute"] = time.perf_counter() - t1
    t2 = time.perf_counter()
    if write:
        for op, arr in results.items():
            p = prof.copy()
            for k in ("compress", "predictor", "zstd_level", "blockxsize", "blockysize", "tiled", "interleave"):
                p.pop(k, None)
            p.update(driver="GTiff", count=1, dtype=OUT_DTYPE.get(op, "float32"),
                     nodata=OUT_NODATA.get(op, numpy_k.NODATA), BIGTIFF="IF_SAFER", tiled=True,
                     blockxsize=512, blockysize=512)
            with rasterio.open(outputs[op], "w", **p) as dst:
                dst.write(arr, 1)
    t["write"] = time.perf_counter() - t2
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--ops", default="slope")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--impl", default="numba", choices=["numba", "numpy", "naive"])
    ap.add_argument("--method", default="Horn")
    ap.add_argument("--threads", type=int)
    ap.add_argument("--window", type=int, default=2048)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--compress")
    ap.add_argument("--zstd-level", type=int)
    a = ap.parse_args()
    ops = a.ops.split(",")
    outputs = {op: f"{a.out_dir}/out_{op}.tif" for op in ops}
    t_imports = time.perf_counter() - T_START
    t0 = time.perf_counter()
    if a.impl == "naive":
        t = naive(a.src, outputs, a.method, not a.no_write)
    else:
        co = {"zstd_level": a.zstd_level} if a.zstd_level else None
        t = run(a.src, outputs, backend=a.impl, method=a.method, window=a.window, threads=a.threads,
                write=not a.no_write, compress=a.compress, creation_options=co)
    t = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in t.items()}
    print(json.dumps({"t_internal": round(time.perf_counter() - t0, 4), "t_imports": round(t_imports, 3), **t}))


if __name__ == "__main__":
    main()
