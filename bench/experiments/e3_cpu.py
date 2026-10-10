"""E3: our CPU engine (demlab) against the gdaldem baseline of E1, on the same grids, harness and machine.

Each run is one `python -m demlab.cli` process measured like gdaldem (wall time incl. Python start-up, peak
memory, CPU, bytes). Variants (CSV column `variant`):
  engine_all_<ops>     numba tiled pipeline, all 22 logical CPUs (P + E + LP cores), 22 threads
  engine_perf_slope    same, pinned to the 12 performance-core threads, 12 threads (same cores as gdaldem)
  engine_all_slope_nowrite   compute only, no output (shows what writing costs)
  engine_all_slope_zstd1     output compressed with ZSTD level 1 (multi-threaded by GDAL)
  numpy_tiled_slope    same tiled pipeline with the single-threaded NumPy reference kernel
  naive_slope          whole grid in memory, NumPy, no tiling: the memory-hungry approach (15 min time limit)
  threads_<n>          thread scaling: slope + write with n threads, pinned to the performance cores
  window_<n>           window (tile) size n x n cells instead of 2048; otherwise as engine_perf_slope
<ops> is slope, aspect, hillshade, or 3prod (slope+aspect+hillshade in one fused pass).

Repeats: real grids 3-5 cold + warm; synthetic grids fewer (see PLAN below); thread sweep warm only.

    python -m bench.experiments.e3_cpu --plan
    python -m bench.experiments.e3_cpu
"""
import argparse
import sys

from bench.sweep import CSV, DATA, OUT_DIR, raster_meta, run_jobs

DATASETS = {
    "tile571_8m": (DATA / "prepared" / "tile571_8m.tif", 8, "real"),
    "chamoli_2m": (DATA / "prepared" / "chamoli_2m.tif", 2, "real"),
    "tile571_2m_cubic": (DATA / "synthetic" / "tile571_2m_cubic.tif", 2, "synthetic"),
    "tile571_1m_cubic": (DATA / "synthetic" / "tile571_1m_cubic.tif", 1, "synthetic"),
}
REAL = ["tile571_8m", "chamoli_2m"]
SYN2, SYN1 = "tile571_2m_cubic", "tile571_1m_cubic"
THREE = "slope,aspect,hillshade"
FULL, SHORT, ONE = (range(1, 6), range(0, 6)), (range(1, 4), range(1, 2)), (range(1, 2), range(0))
WARM3 = (range(0), range(0, 4))
TILE = (range(1, 4), range(0, 4))
WINDOWS = (512, 1024, 4096, 8192)  # 2048 is the default, measured by engine_perf_slope
TIMEOUT_NAIVE = 900

# variant: (impl, ops, cpus, threads, extra cli args, output bytes per cell)
VARIANTS = {
    "engine_all_slope": ("numba", "slope", "all", 22, [], 4),
    "engine_all_aspect": ("numba", "aspect", "all", 22, [], 4),
    "engine_all_hillshade": ("numba", "hillshade", "all", 22, [], 1),
    "engine_all_3prod": ("numba", THREE, "all", 22, [], 9),
    "engine_perf_slope": ("numba", "slope", "perf", 12, [], 4),
    "engine_all_slope_nowrite": ("numba", "slope", "all", 22, ["--no-write"], 0),
    "engine_all_slope_zstd1": ("numba", "slope", "all", 22, ["--compress", "ZSTD", "--zstd-level", "1"], 4),
    "numpy_tiled_slope": ("numpy", "slope", "perf", 1, [], 4),
    "naive_slope": ("naive", "slope", "perf", 1, [], 4),
    **{f"threads_{n}": ("numba", "slope", "perf", n, [], 4) for n in (1, 2, 4, 8)},
    **{f"window_{n}": ("numba", "slope", "perf", 12, ["--window", str(n)], 4) for n in WINDOWS},
}
# which variants run on which grids, with which (cold reps, warm reps)
PLAN = {
    "tile571_8m": {**{v: FULL for v in ("engine_all_slope", "engine_all_aspect", "engine_all_hillshade",
                                        "engine_all_3prod", "engine_perf_slope", "engine_all_slope_nowrite",
                                        "engine_all_slope_zstd1")},
                   "numpy_tiled_slope": SHORT, "naive_slope": SHORT,
                   **{f"threads_{n}": WARM3 for n in (1, 2, 4, 8)},
                   **{f"window_{n}": TILE for n in WINDOWS}},
}
PLAN["chamoli_2m"] = dict(PLAN["tile571_8m"])
PLAN[SYN2] = {**{v: SHORT for v in ("engine_all_slope", "engine_all_aspect", "engine_all_hillshade",
                                    "engine_all_3prod", "engine_perf_slope", "engine_all_slope_nowrite",
                                    "engine_all_slope_zstd1")},
              "numpy_tiled_slope": ONE, "naive_slope": ONE,
              **{f"threads_{n}": WARM3 for n in (1, 2, 4, 8)},
              **{f"window_{n}": TILE for n in WINDOWS}}
PLAN[SYN1] = {"engine_all_slope": SHORT, "engine_perf_slope": SHORT, "engine_all_slope_nowrite": SHORT,
              "engine_all_3prod": (range(1, 2), range(1, 2)), "naive_slope": ONE}


def command(variant, src):
    impl, ops, _, threads, extra, _ = VARIANTS[variant]
    return [sys.executable, "-m", "demlab.cli", str(src), "--ops", ops, "--impl", impl, "--threads", str(threads),
            "--out-dir", str(OUT_DIR), *extra]


def jobs_for(names=None):
    jobs = []
    for name, (path, res, kind) in DATASETS.items():
        if names and name not in names:
            continue
        if not path.exists():
            print(f"{name}: missing ({path}), skipped")
            continue
        cells, layout, comp = raster_meta(path)
        for variant, (cold, warm) in PLAN[name].items():
            impl, ops, cpus, threads, _, bpc = VARIANTS[variant]
            for cache, reps in (("cold", cold), ("warm", warm)):
                for rep in reps:
                    jobs.append({"experiment": "E3", "dataset": name, "variant": variant, "res_m": res,
                                 "cells": cells, "real_or_synthetic": kind, "format": layout, "compression": comp,
                                 "op": ops.replace(",", "+"), "method": "Horn", "impl": f"demlab_{impl}",
                                 "device": "cpu", "threads": threads, "cache_state": cache, "rep": rep,
                                 "_src": path, "_cmd": command(variant, path), "_cpus": cpus, "_scratch": True,
                                 "_out_bpc": bpc, "_timeout": TIMEOUT_NAIVE if impl == "naive" else 3600})
    return jobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", nargs="*")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--csv", default=str(CSV))
    ap.add_argument("--allow-battery", action="store_true")
    a = ap.parse_args()
    run_jobs(jobs_for(a.datasets), "E3", a.csv, a.plan, a.allow_battery)


if __name__ == "__main__":
    main()
