"""E4: our engine on the GPU (RTX 4060 Laptop, 8 GB), against the CPU engine of E3 and gdaldem of E1.

Each run is one `python -m demlab.cli --impl cuda|cupy` process, measured like every other run. The GPU stages
(host -> device copy, kernel, device -> host copy) are timed inside with CUDA events and land in `extra`.
All GPU runs are pinned to the 12 performance-core threads (the CPU side only reads, decodes and writes).
Variants (CSV column `variant`), the optimisation ladder first:
  gpu_cupy_slope        straightforward port: the NumPy reference code on CuPy arrays (float64, many temporaries)
  gpu_pageable_slope    our CUDA kernel, copies from ordinary (pageable) memory, one window at a time
  gpu_pinned_slope      + pinned (page-locked) host buffers
  gpu_slope             + 2 CUDA streams, so copies of one window overlap the kernel of the next (the default)
  gpu_slope_fp64        the default but with float64 arithmetic (consumer GPUs: FP64 at 1/64 of FP32)
  gpu_slope_nowrite     the default without writing the output
  gpu_slope_r8          the default with 8 reader threads instead of 4 (decoding the input is now the limit)
  gpu_3prod             slope + aspect + hillshade fused in one pass
  gpu_<op>[_<method>]   every other gdaldem configuration of E1 (8 m and 2 m real grids)
  gpu_window_<n>        window size n instead of 2048
Safety: GPU memory use is capped at 4 GB (demlab/gpu.py); before every run the harness waits until the GPU is
below 75 C and it stops the sweep if a run ends at 85 C or more (bench/sweep.py). No clocks, power limits or
driver settings are touched.

    python -m bench.experiments.e4_gpu --plan
    python -m bench.experiments.e4_gpu
"""
import argparse
import sys

from bench.experiments.e3_cpu import DATASETS, FULL, ONE, SHORT, TILE
from bench.sweep import CSV, OUT_DIR, raster_meta, run_jobs

THREE = "slope,aspect,hillshade"
WINDOWS = (1024, 4096, 8192)

# variant: (impl, ops, method, extra cli args, output bytes per cell)
VARIANTS = {
    "gpu_cupy_slope": ("cupy", "slope", "Horn", [], 4),
    "gpu_pageable_slope": ("cuda", "slope", "Horn", ["--no-pinned", "--gpu-streams", "1"], 4),
    "gpu_pinned_slope": ("cuda", "slope", "Horn", ["--gpu-streams", "1"], 4),
    "gpu_slope": ("cuda", "slope", "Horn", [], 4),
    "gpu_slope_fp64": ("cuda", "slope", "Horn", ["--precision", "fp64"], 4),
    "gpu_slope_nowrite": ("cuda", "slope", "Horn", ["--no-write"], 0),
    "gpu_slope_r8": ("cuda", "slope", "Horn", ["--readers", "8"], 4),
    "gpu_3prod": ("cuda", THREE, "Horn", [], 9),
    "gpu_aspect": ("cuda", "aspect", "Horn", [], 4),
    "gpu_hillshade": ("cuda", "hillshade", "Horn", [], 1),
    **{f"gpu_{op}_zt": ("cuda", op, "ZevenbergenThorne", [], 4) for op in ("slope", "aspect", "hillshade")},
    "gpu_tri_riley": ("cuda", "TRI", "Riley", [], 4),
    "gpu_tri_wilson": ("cuda", "TRI", "Wilson", [], 4),
    "gpu_tpi": ("cuda", "TPI", "", [], 4),
    "gpu_roughness": ("cuda", "roughness", "", [], 4),
    **{f"gpu_window_{n}": ("cuda", "slope", "Horn", ["--window", str(n)], 4) for n in WINDOWS},
}
LADDER = ["gpu_cupy_slope", "gpu_pageable_slope", "gpu_pinned_slope", "gpu_slope", "gpu_slope_fp64",
          "gpu_slope_nowrite", "gpu_slope_r8", "gpu_3prod"]
OPERATORS = ["gpu_aspect", "gpu_hillshade", "gpu_slope_zt", "gpu_aspect_zt", "gpu_hillshade_zt", "gpu_tri_riley",
             "gpu_tri_wilson", "gpu_tpi", "gpu_roughness"]
GPU_WINDOWS = [f"gpu_window_{n}" for n in WINDOWS]

PLAN = {
    "tile571_8m": {**{v: FULL for v in LADDER + OPERATORS}, **{v: TILE for v in GPU_WINDOWS}},
    "chamoli_2m": {**{v: FULL for v in LADDER + OPERATORS}, **{v: TILE for v in GPU_WINDOWS}},
    "tile571_2m_cubic": {**{v: SHORT for v in LADDER}, **{v: TILE for v in GPU_WINDOWS}},
    "tile571_1m_cubic": {"gpu_slope": SHORT, "gpu_slope_nowrite": SHORT, "gpu_slope_r8": SHORT,
                         "gpu_3prod": (range(1, 2), range(1, 2)), "gpu_pinned_slope": ONE},
}


def command(variant, src):
    impl, ops, method, extra, _ = VARIANTS[variant]
    return [sys.executable, "-m", "demlab.cli", str(src), "--ops", ops, "--impl", impl,
            "--method", method or "Horn", "--out-dir", str(OUT_DIR), *extra]


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
            impl, ops, method, extra, bpc = VARIANTS[variant]
            for cache, reps in (("cold", cold), ("warm", warm)):
                for rep in reps:
                    jobs.append({"experiment": "E4", "dataset": name, "variant": variant, "res_m": res,
                                 "cells": cells, "real_or_synthetic": kind, "format": layout, "compression": comp,
                                 "op": ops.replace(",", "+"), "method": method, "impl": f"demlab_{impl}",
                                 "device": "gpu", "threads": "", "cache_state": cache, "rep": rep,
                                 "_src": path, "_cmd": command(variant, path), "_cpus": "perf", "_scratch": True,
                                 "_out_bpc": bpc, "_timeout": 3600, "_gpu": True})
    return jobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", nargs="*")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--csv", default=str(CSV))
    ap.add_argument("--allow-battery", action="store_true")
    a = ap.parse_args()
    run_jobs(jobs_for(a.datasets), "E4", a.csv, a.plan, a.allow_battery)


if __name__ == "__main__":
    main()
