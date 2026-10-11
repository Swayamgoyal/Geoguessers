"""E4 crossover: from which window size is the GPU faster than the CPU, once the copies are counted?

In one process, on one real elevation block (Chamoli 2 m), for square windows of 128 ... 8192 cells per side:
  cpu_numba          our Numba kernel, 12 threads (process pinned to the performance cores), data in RAM
  gpu_kernel         CUDA kernel only, data already on the GPU (float32)
  gpu_kernel_fp64    the same with float64 arithmetic
  gpu_e2e_pinned     window in RAM -> pinned buffer -> GPU -> kernel -> back to RAM (what the engine does)
  gpu_e2e_pageable   the same, copying from ordinary memory, no pinned buffers
for slope alone and for slope + aspect + hillshade. No disk reads or writes. Each case is repeated until it has
run for at least 0.3 s (at least 5, at most 200 times); the median is kept. The workload is tiny for the GPU
(milliseconds); the GPU temperature is checked before starting.
Writes results/e4_crossover.csv.

    python -m bench.experiments.e4_crossover
"""
import csv
import time
from pathlib import Path

import cupy as cp
import numba
import numpy as np
import psutil
import rasterio
from rasterio.windows import Window

from bench.harness import performance_cpus
from bench.sweep import DATA, gpu_cooldown
from demlab.gpu import CudaBackend
from demlab.kernels import cuda_k, numba_k

SIZES = [128, 256, 512, 1024, 2048, 4096, 8192]
OPS = {"slope": ["slope"], "slope+aspect+hillshade": ["slope", "aspect", "hillshade"]}
SRC = DATA / "prepared" / "chamoli_2m.tif"
OUT = Path(__file__).resolve().parents[2] / "results" / "e4_crossover.csv"


def bench(fn, min_time=0.3, min_reps=5, max_reps=200):
    fn()  # warm-up
    times = []
    t_start = time.perf_counter()
    while len(times) < max_reps and (len(times) < min_reps or time.perf_counter() - t_start < min_time):
        t = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t)
    return float(np.median(times)), len(times)


def main():
    psutil.Process().cpu_affinity(performance_cpus())
    numba.set_num_threads(12)
    print("GPU temperature before:", gpu_cooldown(), "C")
    n_max = SIZES[-1] + 2
    with rasterio.open(SRC) as src:
        r0, c0 = (src.height - n_max) // 2, (src.width - n_max) // 2
        block = src.read(1, window=Window(c0, r0, n_max, n_max)).astype(np.float32)
        res, nodata = src.res[0], src.nodata
    print(f"block {n_max}^2 from the centre of {SRC.name}: {np.mean(block != nodata):.1%} valid")
    rows = []
    for label, ops in OPS.items():
        for n in SIZES:
            z32 = np.ascontiguousarray(block[:n + 2, :n + 2])
            z64 = z32.astype(np.float64)
            zg = cp.asarray(z32)
            cases = {
                "cpu_numba": lambda: numba_k.compute_many(ops, z64, res, "Horn", nodata),
                "gpu_kernel": lambda: (cuda_k.compute_many(ops, zg, res, "Horn", nodata, "fp32"),
                                       cp.cuda.Device().synchronize()),
                "gpu_kernel_fp64": lambda: (cuda_k.compute_many(ops, zg, res, "Horn", nodata, "fp64"),
                                            cp.cuda.Device().synchronize()),
            }
            for pinned, name in ((True, "gpu_e2e_pinned"), (False, "gpu_e2e_pageable")):
                be = CudaBackend(ops, res, "Horn", nodata, "fp32", pinned=pinned, streams=1)
                cases[name] = lambda be=be: be.collect(be.submit(z32))
            for version, fn in cases.items():
                med, reps = bench(fn)
                rows.append({"ops": label, "window": n, "cells": n * n, "version": version, "median_s": med,
                             "ns_per_cell": med / (n * n) * 1e9, "reps": reps})
                print(f"{label:23s} {n:5d}^2 {version:17s} {med * 1e3:9.3f} ms  {med / (n * n) * 1e9:7.3f} ns/cell"
                      f"  ({reps} reps)", flush=True)
            del zg
            cp.get_default_memory_pool().free_all_blocks()
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print("wrote", OUT, "| GPU temperature after:", gpu_cooldown(), "C")


if __name__ == "__main__":
    main()
