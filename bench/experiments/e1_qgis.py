"""E1-QGIS: how long QGIS takes to open and draw a DEM, with and without a pyramid.

Measures the display side of the baseline: open the layer (incl. QGIS's default min/max stretch)
and render one 1920x1080 view, either the full extent or a 1920 m x 1080 m zoom at the centre.
Pyramid 'use' = the file's internal overviews; 'none' = hidden, as for a plain GeoTIFF.
Per case: 3 cold + 1 warm (the last cold run is the warm-up). GDAL's .aux.xml statistics caches are
disabled (GDAL_PAM_ENABLED=NO), so every open starts from the same clean state.

op='render', method='<view>-<overviews>', t_total = whole QGIS process incl. start-up,
t_internal = render time; extra = {t_init, t_open, peak_mb, filled}. peak_rss_mb is the QGIS
python process itself (the harness only sees the .bat wrapper).

    python -m bench.experiments.e1_qgis --plan
    python -m bench.experiments.e1_qgis
"""
import argparse
import json
import os
import time
from pathlib import Path

from bench.harness import (Recorder, check_power, keep_awake, measure, performance_cpus,
                           snapshot_env)
from bench.sweep import CSV, DATA, OUT_DIR, raster_meta

QGIS_PY = Path(os.environ.get("QGIS_PY", r"C:\Program Files\QGIS 3.44.14\bin\python-qgis-ltr.bat"))
SCRIPT = Path(__file__).resolve().parents[1] / "qgis_render.py"
DATASETS = [
    ("tile571_8m", DATA / "prepared" / "tile571_8m.tif", 8, "real"),
    ("tile571_2m_cubic", DATA / "synthetic" / "tile571_2m_cubic.tif", 2, "synthetic"),
    ("tile571_1m_cubic", DATA / "synthetic" / "tile571_1m_cubic.tif", 1, "synthetic"),
]
# conda's GDAL/PROJ settings must not leak into QGIS's own GDAL
LEAKY = ("GDAL_DATA", "GDAL_DRIVER_PATH", "PROJ_LIB", "PROJ_DATA", "PYTHONHOME", "PYTHONPATH", "CONDA_PREFIX",
         "CONDA_DEFAULT_ENV", "CONDA_PYTHON_EXE", "CONDA_EXE", "CONDA_SHLVL", "CONDA_PROMPT_MODIFIER")


def qgis_env(cpus):
    env = {k: v for k, v in os.environ.items() if k.upper() not in LEAKY and not k.upper().startswith("CONDA_")}
    env["PATH"] = ";".join(p for p in env.get("PATH", "").split(";") if "miniforge" not in p.lower())
    env["BENCH_AFFINITY_MASK"] = str(sum(1 << c for c in cpus))
    # No .aux.xml statistics caches: otherwise the first open writes min/max/histogram next to the grid and
    # every later run reuses it, so 'open' would no longer measure what a fresh open costs.
    env["GDAL_PAM_ENABLED"] = "NO"
    return env


def jobs_for():
    jobs = []
    for name, path, res, kind in DATASETS:
        if not path.exists():
            print(f"{name}: missing ({path}), skipped")
            continue
        cells, layout, comp = raster_meta(path)
        for overviews in ("use", "none"):
            for view in ("full", "zoom"):
                for cache, reps in (("cold", range(1, 4)), ("warm", range(1, 2))):
                    for rep in reps:
                        jobs.append({"experiment": "E1q", "dataset": name, "variant": "cog", "res_m": res,
                                     "cells": cells, "real_or_synthetic": kind, "format": layout,
                                     "compression": comp, "op": "render", "method": f"{view}-{overviews}",
                                     "impl": "qgis", "device": "cpu", "threads": "", "cache_state": cache,
                                     "rep": rep, "_src": path, "_ov": overviews, "_view": view})
    return jobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--csv", default=str(CSV))
    ap.add_argument("--allow-battery", action="store_true")
    a = ap.parse_args()
    rec = Recorder(a.csv)
    jobs = jobs_for()
    todo = [j for j in jobs if not rec.is_done(j)]
    print(f"{len(jobs)} runs planned, {len(todo)} to run", flush=True)
    if a.plan or not todo:
        return
    check_power(a.allow_battery)
    cpus = performance_cpus()
    snapshot_env("E1q")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    env = qgis_env(cpus)
    keep_awake(True)
    t_start = time.perf_counter()
    try:
        for i, job in enumerate(todo, 1):
            png = OUT_DIR / f"qgis_{job['dataset']}_{job['method']}.png"
            cmd = [str(QGIS_PY), str(SCRIPT), str(job["_src"]), job["_ov"], job["_view"], str(png)]
            res = measure(cmd, job["cache_state"], cpus, env=env)
            extra = json.loads(res["extra"]) if res["extra"] else {}
            if "peak_mb" in extra:
                res["peak_rss_mb"] = extra["peak_mb"]
            rec.write({k: v for k, v in job.items() if not k.startswith("_")}, res, cmd)
            el = time.perf_counter() - t_start
            print(f"[{i}/{len(todo)}] {job['dataset']} {job['method']} {job['cache_state']} rep{job['rep']}: "
                  f"render {res['t_internal']} s, open {extra.get('t_open')} s, peak {res['peak_rss_mb']} MB, "
                  f"filled {extra.get('filled')}{'' if res['ok'] else '  FAILED: ' + res['error']}"
                  f"  | elapsed {el / 60:.0f} min, ETA {el / i * (len(todo) - i) / 60:.0f} min", flush=True)
    finally:
        keep_awake(False)


if __name__ == "__main__":
    main()
