"""E1: baseline scaling of gdaldem terrain operators across the resolution ladder.

For every dataset, operator and method: cold runs (file cache emptied before each) and warm
runs (1 warm-up, rep 0, then measured repeats). Two reference runs per dataset give a stage
breakdown: 'read' (gdalinfo -checksum: read + decompress only) and 'copy' (gdal_translate to an
uncompressed GTiff: same read + same-size write as gdaldem). Derived in analysis:
write ~ copy - read, compute ~ gdaldem - copy.

Run from the repo root, inside the geo env:
    python -m bench.experiments.e1_baseline --plan          # list what would run
    python -m bench.experiments.e1_baseline                 # run (skips runs already in the CSV)
    python -m bench.experiments.e1_baseline --datasets tile571_90m tile571_30m
"""
import argparse
import os
import shutil
import time
from pathlib import Path

from osgeo import gdal

from bench.harness import Recorder, check_power, keep_awake, measure, tool

gdal.UseExceptions()
DATA = Path(os.environ.get("GEO_DATA", r"D:\geoguessers_data"))
OUT_DIR = DATA / "bench_out"
CSV = Path(__file__).resolve().parents[2] / "results" / "runs.csv"

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
# Agreed (trimmed) protocol. Real grids: all ops, 5 cold + warm-up + 5 warm.
# Grids above LARGE_CELLS (synthetic 2 m and 1 m): only slope Horn + hillshade Horn (+ read/copy),
# 3 cold + 1 warm. The last cold run has just loaded the file, so it serves as the warm-up.
# Method/operator comparisons are size-independent and come from the real grids.
LARGE_CELLS = 1_000_000_000
LARGE_OPS = [("slope", "Horn"), ("hillshade", "Horn")]


def dataset_meta(path):
    ds = gdal.Open(str(path))
    s = ds.GetMetadata("IMAGE_STRUCTURE")
    return ds.RasterXSize * ds.RasterYSize, s.get("LAYOUT", "GTiff"), s.get("COMPRESSION", "none")


def runs_for(cells):
    """(ops, cold reps, warm reps) for a grid of this size."""
    refs = [("read", "checksum"), ("copy", "gtiff")]
    if cells > LARGE_CELLS:
        return refs + LARGE_OPS, range(1, 4), range(1, 2)
    return refs + OPS, range(1, 6), range(0, 6)


def command(op, method, src, out):
    if op == "read":
        # OVERVIEW_LEVEL=NONE: checksum only the full-resolution data, which is all gdaldem reads
        return [tool("gdalinfo"), "-checksum", "-nomd", "-norat", "-noct", "-oo", "OVERVIEW_LEVEL=NONE", str(src)]
    if op == "copy":
        return [tool("gdal_translate"), "-q", "-of", "GTiff", str(src), str(out)]
    cmd = [tool("gdaldem"), op, str(src), str(out), "-q"]
    return cmd + (["-alg", method] if method else [])


def cleanup():
    for p in OUT_DIR.glob("out.*"):
        p.unlink()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", nargs="*", help="subset of dataset names")
    ap.add_argument("--plan", action="store_true", help="only list the runs")
    ap.add_argument("--csv", default=str(CSV))
    ap.add_argument("--allow-battery", action="store_true")
    a = ap.parse_args()

    chosen = [d for d in DATASETS if not a.datasets or d[0] in a.datasets]
    jobs = []
    for name, path, res, kind in chosen:
        if not path.exists():
            print(f"{name}: missing ({path}), skipped")
            continue
        cells, layout, comp = dataset_meta(path)
        ops, cold_reps, warm_reps = runs_for(cells)
        for op, method in ops:
            for cache, reps in (("cold", cold_reps), ("warm", warm_reps)):
                for rep in reps:
                    jobs.append({"experiment": "E1", "dataset": name, "res_m": res, "cells": cells,
                                 "real_or_synthetic": kind, "format": layout, "compression": comp,
                                 "op": op, "method": method,
                                 "impl": "gdaldem" if op not in ("read", "copy") else op,
                                 "device": "cpu", "threads": 1, "cache_state": cache, "rep": rep,
                                 "_src": path})

    rec = Recorder(a.csv)
    todo = [j for j in jobs if not rec.is_done(j)]
    print(f"{len(jobs)} runs planned, {len(jobs) - len(todo)} already in {a.csv}, {len(todo)} to run")
    if a.plan:
        for name in dict.fromkeys(j["dataset"] for j in jobs):
            sub = [j for j in todo if j["dataset"] == name]
            print(f"  {name:18s} {len(sub):4d} runs to do")
        return

    check_power(a.allow_battery)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    keep_awake(True)
    t_start = time.perf_counter()
    try:
        for i, job in enumerate(todo, 1):
            need = job["cells"] * 4 * 1.1
            if shutil.disk_usage(OUT_DIR).free < need:
                raise SystemExit(f"Not enough free space on {OUT_DIR} for {job['dataset']} output")
            out = OUT_DIR / "out.tif"
            cmd = command(job["op"], job["method"], job["_src"], out)
            res = measure(cmd, job["cache_state"])
            cleanup()
            meta = {k: v for k, v in job.items() if not k.startswith("_")}
            rec.write(meta, res, cmd)
            el = time.perf_counter() - t_start
            print(f"[{i}/{len(todo)}] {job['dataset']} {job['op']} {job['method']} {job['cache_state']} "
                  f"rep{job['rep']}: {res['t_total']:.2f} s, peak {res['peak_rss_mb']:.0f} MB, "
                  f"disk read {res['disk_read_mb']:.0f} MB{'' if res['ok'] else '  FAILED: ' + res['error']}"
                  f"  | elapsed {el / 60:.0f} min, ETA {el / i * (len(todo) - i) / 60:.0f} min", flush=True)
    finally:
        keep_awake(False)
        cleanup()


if __name__ == "__main__":
    main()
