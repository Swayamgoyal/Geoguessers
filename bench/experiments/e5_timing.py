"""E5 timing: what one view costs at each pyramid level, three ways (the time side of the accuracy trade-off).

Routes, for a view at pyramid level k:
  on_demand    read the view from the DEM pyramid level k (+1-cell halo) and compute slope at that level's cell
               size (what the planned tile server does; error measured by e5_accuracy.py)
  full_res     read the same ground area at full resolution (+halo), compute slope there and average it over each
               coarse cell (the exact answer, without any precomputation)
  precomputed  read the view from a slope pyramid built in advance (exact answer; needs a full-resolution pass and
               extra storage once per derivative; built by --precompute)
Views:
  tile         one 512 x 512-cell display tile at level k, at 8 random places fully inside the data (>= 90% valid)
  whole        the whole grid at level k
Cache: cold = Windows file cache emptied (bench/cache.py) before each measurement; warm = file already in the
OS cache, median of 3. Every measurement opens a fresh dataset handle (not timed), so GDAL's own block cache never
hides the decoding. Measured in one long-running process, like a tile server, pinned to the 12 performance-core
threads, Numba kernel with 12 threads, GDAL_NUM_THREADS=ALL_CPUS for decoding (same for all routes).
Writes results/e5_timing.csv and (with --precompute) results/e5_precompute.csv.

    python -m bench.experiments.e5_timing --precompute     # once: slope pyramids (needed by e5_accuracy too)
    python -m bench.experiments.e5_timing
"""
import argparse
import csv
import os
import time
from pathlib import Path

import numba
import numpy as np
import psutil
import rasterio
from osgeo import gdal
from rasterio.windows import Window

from bench.cache import flush
from bench.harness import check_power, keep_awake, performance_cpus, snapshot_env
from bench.sweep import DATA, OUT_DIR
from demlab.engine import run
from demlab.io import read_with_halo
from demlab.kernels import numba_k
from demlab.pyramid import block_sums, footprint_edges, level_dataset, level_res

gdal.UseExceptions()
GRIDS = {"chamoli_2m": DATA / "prepared" / "chamoli_2m.tif", "tile571_8m": DATA / "prepared" / "tile571_8m.tif"}
TILE, POSITIONS, WARM_REPS, WHOLE_REPS = 512, 8, 3, 3
RES = Path(__file__).resolve().parents[2] / "results"
FIELDS = ["dataset", "view", "level", "res_m", "route", "cache", "position", "row", "col", "seconds",
          "cells_read", "cells_out"]


def precomputed_path(name):
    return OUT_DIR / f"e5_slope_{name}.tif"


def slope(z, res, nodata):
    return numba_k.compute_many(["slope"], z, res, "Horn", nodata)["slope"]


# ---------------------------------------------------------------- the three routes (one view each)
def on_demand(path, k, win, nodata):
    with level_dataset(path, k) as ds:
        t = time.perf_counter()
        z = read_with_halo(ds, win, nodata)
        out = slope(z, level_res(ds), nodata)
        return time.perf_counter() - t, z.size, out.size


def full_res(path, k, win, nodata, shape0, shape_k):
    r, c, h, w = win
    re = footprint_edges(shape0[0], shape_k[0], r, r + h)
    ce = footprint_edges(shape0[1], shape_k[1], c, c + w)
    with rasterio.open(path) as ds:
        t = time.perf_counter()
        z = read_with_halo(ds, (re[0], ce[0], re[-1] - re[0], ce[-1] - ce[0]), nodata)
        s = slope(z, ds.res[0], nodata)
        sums, counts = block_sums(s, s != numba_k.NODATA, re - re[0], ce - ce[0])
        out = np.where(counts > 0, sums / np.maximum(counts, 1), numba_k.NODATA).astype(np.float32)
        return time.perf_counter() - t, z.size, out.size


def precomputed(path, k, win):
    r, c, h, w = win
    with level_dataset(path, k) as ds:
        t = time.perf_counter()
        out = ds.read(1, window=Window(c, r, w, h))
        return time.perf_counter() - t, out.size, out.size


def measure(route, name, path, k, win, nodata, shape0, shape_k, cold):
    if cold:
        flush()
    if route == "on_demand":
        return on_demand(path, k, win, nodata)
    if route == "full_res":
        return full_res(path, k, win, nodata, shape0, shape_k)
    return precomputed(precomputed_path(name), k, win)


# ---------------------------------------------------------------- setup
def tile_positions(path, k, nodata, rng):
    """POSITIONS random 512 x 512 windows of level k that are >= 90% valid (read once, untimed)."""
    with level_dataset(path, k) as ds:
        z = ds.read(1)
    H, W = z.shape
    v = (z != nodata).astype(np.float64)
    cs = np.pad(v.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    pos = []
    for _ in range(20000):
        r, c = int(rng.integers(0, H - TILE + 1)), int(rng.integers(0, W - TILE + 1))
        frac = (cs[r + TILE, c + TILE] - cs[r, c + TILE] - cs[r + TILE, c] + cs[r, c]) / TILE**2
        if frac >= 0.9:
            pos.append((r, c))
        if len(pos) == POSITIONS:
            break
    return pos


def precompute(writer_rows):
    """Slope pyramid made in advance: full-resolution slope (CPU engine) -> COG with AVERAGE overviews."""
    for name, path in GRIDS.items():
        raw, cog = OUT_DIR / f"out_e5_slope_{name}_raw.tif", precomputed_path(name)
        flush()
        t0 = time.perf_counter()
        run(path, {"slope": str(raw)}, backend="numba")
        t1 = time.perf_counter()
        gdal.Translate(str(cog), str(raw), format="COG",
                       creationOptions=["COMPRESS=ZSTD", "PREDICTOR=3", "BLOCKSIZE=512", "OVERVIEW_RESAMPLING=AVERAGE",
                                        "NUM_THREADS=ALL_CPUS", "BIGTIFF=IF_SAFER"])
        t2 = time.perf_counter()
        raw.unlink()
        row = {"dataset": name, "slope_full_res_s": t1 - t0, "cog_with_overviews_s": t2 - t1,
               "total_s": t2 - t0, "slope_pyramid_mb": cog.stat().st_size / 2**20,
               "dem_pyramid_mb": Path(path).stat().st_size / 2**20}
        writer_rows.append(row)
        print(f"{name}: slope {t1 - t0:.1f} s + COG/overviews {t2 - t1:.1f} s, "
              f"{row['slope_pyramid_mb']:.0f} MB (DEM COG {row['dem_pyramid_mb']:.0f} MB)", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--precompute", action="store_true")
    ap.add_argument("--datasets", nargs="*")
    a = ap.parse_args()
    check_power()
    os.environ["GDAL_NUM_THREADS"] = "ALL_CPUS"
    psutil.Process().cpu_affinity(performance_cpus())
    numba.set_num_threads(len(performance_cpus()))
    slope(np.zeros((10, 10)), 1.0, -9999.0)  # compile / load the kernel before timing
    keep_awake(True)
    try:
        if a.precompute:
            rows = []
            precompute(rows)
            with open(RES / "e5_precompute.csv", "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            return
        snapshot_env("E5")
        rng = np.random.default_rng(5)
        with open(RES / "e5_timing.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            for name, path in GRIDS.items():
                if a.datasets and name not in a.datasets:
                    continue
                with rasterio.open(path) as src:
                    shape0, nodata, levels = (src.height, src.width), src.nodata, len(src.overviews(1))
                shapes = {}
                for k in range(levels + 1):
                    with level_dataset(path, k) as ds:
                        shapes[k] = ((ds.height, ds.width), level_res(ds))
                jobs = []
                for k in range(levels + 1):
                    (hk, wk), rk = shapes[k]
                    routes = ["on_demand", "precomputed"] + (["full_res"] if k else [])
                    if min(hk, wk) >= TILE:
                        for p, (r, c) in enumerate(tile_positions(path, k, nodata, rng)):
                            jobs += [("tile", k, rk, route, p, (r, c, TILE, TILE)) for route in routes]
                    jobs += [("whole", k, rk, route, p, (0, 0, hk, wk)) for route in routes for p in range(WHOLE_REPS)]
                t_start = time.perf_counter()
                for i, (view, k, rk, route, p, win) in enumerate(jobs, 1):
                    for cache in ("cold", "warm"):
                        if cache == "warm":
                            measure(route, name, path, k, win, nodata, shape0, shapes[k][0], False)  # into OS cache
                            ts = [measure(route, name, path, k, win, nodata, shape0, shapes[k][0], False)
                                  for _ in range(WARM_REPS)]
                            sec, n_in, n_out = float(np.median([x[0] for x in ts])), ts[0][1], ts[0][2]
                        else:
                            sec, n_in, n_out = measure(route, name, path, k, win, nodata, shape0, shapes[k][0], True)
                        w.writerow({"dataset": name, "view": view, "level": k, "res_m": round(rk, 3), "route": route,
                                    "cache": cache, "position": p, "row": win[0], "col": win[1], "seconds": sec,
                                    "cells_read": n_in, "cells_out": n_out})
                    f.flush()
                    el = time.perf_counter() - t_start
                    print(f"[{name} {i}/{len(jobs)}] {view} L{k} {route}: cold+warm done | elapsed {el / 60:.0f} min, "
                          f"ETA {el / i * (len(jobs) - i) / 60:.0f} min", flush=True)
    finally:
        keep_awake(False)


if __name__ == "__main__":
    main()
