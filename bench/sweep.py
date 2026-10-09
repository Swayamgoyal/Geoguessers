"""Shared pieces for the E1/E2 sweeps: commands for each operation, and the run loop."""
import os
import shutil
import sys
import time
from pathlib import Path

from osgeo import gdal

from bench.harness import Recorder, check_power, keep_awake, measure, performance_cpus, snapshot_env, tool

gdal.UseExceptions()
DATA = Path(os.environ.get("GEO_DATA", r"D:\geoguessers_data"))
OUT_DIR = DATA / "bench_out"
CSV = Path(__file__).resolve().parents[1] / "results" / "runs.csv"

# Stage references: 'read' = read + decompress every full-res block (bench/read_blocks.py, reports
# t_internal without start-up); 'copy' = gdal_translate to an uncompressed GTiff, i.e. the same read
# plus a same-size float32 write as gdaldem. In analysis: write ~ copy - read, compute ~ gdaldem - copy.
REFS = [("read", "blocks"), ("copy", "gtiff")]


def raster_meta(path):
    ds = gdal.Open(str(path))
    s = ds.GetMetadata("IMAGE_STRUCTURE")
    return ds.RasterXSize * ds.RasterYSize, s.get("LAYOUT", "GTiff"), s.get("COMPRESSION", "none")


def command(op, method, src, out):
    if op == "read":
        return [sys.executable, "-m", "bench.read_blocks", str(src)]
    if op == "copy":
        return [tool("gdal_translate"), "-q", "-of", "GTiff", str(src), str(out)]
    cmd = [tool("gdaldem"), op, str(src), str(out), "-q"]
    return cmd + (["-alg", method] if method else [])


def impl_of(op):
    return {"read": "gdal_blocks", "copy": "gdal_translate"}.get(op, "gdaldem")


def cleanup():
    for p in OUT_DIR.glob("out.*"):
        p.unlink()


def run_jobs(jobs, experiment, csv_path=CSV, plan_only=False, allow_battery=False):
    """jobs: dicts with the CSV metadata plus '_src' (input path) and optional '_cmd' (prebuilt command)."""
    rec = Recorder(csv_path)
    todo = [j for j in jobs if not rec.is_done(j)]
    print(f"{len(jobs)} runs planned, {len(jobs) - len(todo)} already in {csv_path}, {len(todo)} to run", flush=True)
    if plan_only:
        for key in dict.fromkeys((j["dataset"], j.get("variant", "")) for j in jobs):
            n = sum(1 for j in todo if (j["dataset"], j.get("variant", "")) == key)
            print(f"  {key[0]:18s} {key[1]:16s} {n:4d} runs to do")
        return
    if not todo:
        return
    check_power(allow_battery)
    cpus = performance_cpus()
    env = snapshot_env(experiment)
    print(f"pinned to {cpus}; power: {env['power_scheme']}", flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    keep_awake(True)
    t_start = time.perf_counter()
    try:
        for i, job in enumerate(todo, 1):
            if shutil.disk_usage(OUT_DIR).free < job["cells"] * 4 * 1.1 + 5 * 2**30:
                raise SystemExit(f"Not enough free space on {OUT_DIR} for {job['dataset']} output")
            cmd = job.get("_cmd") or command(job["op"], job["method"], job["_src"], OUT_DIR / "out.tif")
            res = measure(cmd, job["cache_state"], cpus)
            cleanup()
            rec.write({k: v for k, v in job.items() if not k.startswith("_")}, res, cmd)
            el = time.perf_counter() - t_start
            print(f"[{i}/{len(todo)}] {job['dataset']} {job.get('variant', '')} {job['op']} {job['method']} "
                  f"{job['cache_state']} rep{job['rep']}: {res['t_total']:.2f} s, peak {res['peak_rss_mb']:.0f} MB, "
                  f"disk read {res['disk_read_mb']:.0f} MB{'' if res['ok'] else '  FAILED: ' + res['error']}"
                  f"  | elapsed {el / 60:.0f} min, ETA {el / i * (len(todo) - i) / 60:.0f} min", flush=True)
    finally:
        keep_awake(False)
        cleanup()
