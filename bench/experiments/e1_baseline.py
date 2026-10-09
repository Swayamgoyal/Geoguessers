"""E1: baseline scaling of gdaldem terrain operators across the resolution ladder.

For every dataset, operator and method: cold runs (file cache emptied before each) and warm runs.
Read and copy reference runs give the stage breakdown (see bench/sweep.py). All tools are pinned
to the performance cores (see bench/harness.py).

Protocol (agreed, trimmed):
  real grids (<= 1 B cells): all 10 gdaldem configs, 5 cold + warm-up (rep 0) + 5 warm
  synthetic 2 m / 1 m:       slope Horn + hillshade Horn only, 3 cold + 1 warm (the last cold
                             run is the warm-up). Method/operator comparisons come from the real grids.

Run from the repo root, inside the geo env:
    python -m bench.experiments.e1_baseline --plan          # list what would run
    python -m bench.experiments.e1_baseline                 # run (skips runs already in the CSV)
    python -m bench.experiments.e1_baseline --datasets tile571_90m tile571_30m
"""
import argparse

from bench.sweep import CSV, DATA, REFS, impl_of, raster_meta, run_jobs

# name, path, resolution (m), real or synthetic; ordered small -> large
DATASETS = [
    ("tile571_90m", DATA / "prepared" / "tile571_90m.tif", 90, "real"),
    ("tile571_30m", DATA / "prepared" / "tile571_30m.tif", 30, "real"),
    ("tile571_8m", DATA / "prepared" / "tile571_8m.tif", 8, "real"),
    ("chamoli_2m", DATA / "prepared" / "chamoli_2m.tif", 2, "real"),
    ("tile571_2m_cubic", DATA / "synthetic" / "tile571_2m_cubic.tif", 2, "synthetic"),
    ("tile571_1m_cubic", DATA / "synthetic" / "tile571_1m_cubic.tif", 1, "synthetic"),
]
# gdaldem operator, -alg value ("" = operator has no method choice)
OPS = [("slope", "Horn"), ("slope", "ZevenbergenThorne"),
       ("aspect", "Horn"), ("aspect", "ZevenbergenThorne"),
       ("hillshade", "Horn"), ("hillshade", "ZevenbergenThorne"),
       ("TRI", "Riley"), ("TRI", "Wilson"),
       ("TPI", ""), ("roughness", "")]
LARGE_CELLS = 1_000_000_000
LARGE_OPS = [("slope", "Horn"), ("hillshade", "Horn")]


def runs_for(cells):
    """(ops, cold reps, warm reps) for a grid of this size."""
    if cells > LARGE_CELLS:
        return REFS + LARGE_OPS, range(1, 4), range(1, 2)
    return REFS + OPS, range(1, 6), range(0, 6)


def jobs_for(names=None):
    jobs = []
    for name, path, res, kind in DATASETS:
        if names and name not in names:
            continue
        if not path.exists():
            print(f"{name}: missing ({path}), skipped")
            continue
        cells, layout, comp = raster_meta(path)
        ops, cold_reps, warm_reps = runs_for(cells)
        for op, method in ops:
            for cache, reps in (("cold", cold_reps), ("warm", warm_reps)):
                for rep in reps:
                    jobs.append({"experiment": "E1", "dataset": name, "variant": "cog", "res_m": res,
                                 "cells": cells, "real_or_synthetic": kind, "format": layout,
                                 "compression": comp, "op": op, "method": method, "impl": impl_of(op),
                                 "device": "cpu", "threads": 1, "cache_state": cache, "rep": rep, "_src": path})
    return jobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", nargs="*", help="subset of dataset names")
    ap.add_argument("--plan", action="store_true", help="only list the runs")
    ap.add_argument("--csv", default=str(CSV))
    ap.add_argument("--allow-battery", action="store_true")
    a = ap.parse_args()
    run_jobs(jobs_for(a.datasets), "E1", a.csv, a.plan, a.allow_battery)


if __name__ == "__main__":
    main()
