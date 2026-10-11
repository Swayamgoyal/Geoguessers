"""Shared pieces for the E1/E2 sweeps: commands for each operation, and the run loop."""
import json
import os
import shutil
import subprocess
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
    for p in OUT_DIR.glob("out*.tif*"):  # out.tif (gdaldem) and out_<op>.tif (demlab.cli)
        p.unlink()


def wait_for_space(free_before, timeout=900):
    """Wait until deleting the run's output has really freed its space.

    Windows only releases a deleted file once every handle to it is closed; until then it sits in
    the hidden NTFS $Deleted area. Defender scanning a 10-40 GB output can hold it for minutes, and
    in the first E2 attempt 108 GB piled up and filled D:. Waiting here (outside the timed part)
    also means the next run does not start while that scan is still busy."""
    t = time.perf_counter()
    while shutil.disk_usage(OUT_DIR).free < free_before - 2**30:
        if time.perf_counter() - t > timeout:
            return False
        time.sleep(2)
    return True


GPU_COOL, GPU_RESUME, GPU_STOP = 75, 65, 85  # deg C: wait before a run / resume below / stop the sweep at


def gpu_temp():
    """GPU temperature in deg C (nvidia-smi, read-only), or None if it cannot be read."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=20).stdout
        return int(out.split()[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def gpu_cooldown():
    """Before a GPU run: if the card is warm, wait (outside the timed part) until it has cooled down."""
    t = gpu_temp()
    if t is None:
        raise SystemExit("Cannot read the GPU temperature (nvidia-smi); not running GPU jobs blind")
    if t >= GPU_COOL:
        print(f"GPU at {t} C: waiting until it is below {GPU_RESUME} C", flush=True)
        start = time.perf_counter()
        while (t := gpu_temp()) is None or t > GPU_RESUME:
            if time.perf_counter() - start > 900:
                raise SystemExit("GPU did not cool down within 15 min; stopping the sweep")
            time.sleep(10)
    return t


def run_jobs(jobs, experiment, csv_path=CSV, plan_only=False, allow_battery=False, snapshot=True):
    """jobs: dicts with the CSV metadata plus '_src' (input path) and optional private keys:
    _cmd (prebuilt command), _cpus ("all" = every logical CPU; default the performance cores), _timeout (s),
    _out_bpc (output bytes per cell, for the free-space check; default 4), _scratch (writes into OUT_DIR and
    must wait for the deleted output to be released; default: no _cmd), _gpu (uses the GPU: wait for it to cool
    below GPU_COOL before the run, record its temperature, stop the sweep if it reaches GPU_STOP).
    snapshot: record the run conditions (results/env); callers that run one sweep in parts pass it once."""
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
    if snapshot:
        env = snapshot_env(experiment)
        print(f"pinned to {cpus}; power: {env['power_scheme']}", flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    keep_awake(True)
    t_start = time.perf_counter()
    try:
        for i, job in enumerate(todo, 1):
            if shutil.disk_usage(OUT_DIR).free < job["cells"] * job.get("_out_bpc", 4) * 1.1 + 5 * 2**30:
                raise SystemExit(f"Not enough free space on {OUT_DIR} for {job['dataset']} output")
            cmd = job.get("_cmd") or command(job["op"], job["method"], job["_src"], OUT_DIR / "out.tif")
            free_before = shutil.disk_usage(OUT_DIR).free
            job_cpus = list(range(os.cpu_count())) if job.get("_cpus") == "all" else cpus
            gpu_before = gpu_cooldown() if job.get("_gpu") else None
            res = measure(cmd, job["cache_state"], job_cpus, timeout=job.get("_timeout"))
            gpu_after = gpu_temp() if job.get("_gpu") else None
            if job.get("_gpu"):
                extra = json.loads(res["extra"]) if res["extra"] else {}
                res["extra"] = json.dumps({**extra, "gpu_temp_before": gpu_before, "gpu_temp_after": gpu_after})
            cleanup()
            if job.get("_scratch", not job.get("_cmd")) and not wait_for_space(free_before):
                raise SystemExit(f"Deleted output was not released within 15 min ({OUT_DIR}); stopping before "
                                 f"the disk fills. A restart frees it.")
            rec.write({k: v for k, v in job.items() if not k.startswith("_")}, res, cmd)
            el = time.perf_counter() - t_start
            print(f"[{i}/{len(todo)}] {job['dataset']} {job.get('variant', '')} {job['op']} {job['method']} "
                  f"{job['cache_state']} rep{job['rep']}: {res['t_total']:.2f} s, peak {res['peak_rss_mb']:.0f} MB, "
                  f"disk read {res['disk_read_mb']:.0f} MB{'' if res['ok'] else '  FAILED: ' + res['error']}"
                  f"{f', GPU {gpu_before}->{gpu_after} C' if job.get('_gpu') else ''}"
                  f"  | elapsed {el / 60:.0f} min, ETA {el / i * (len(todo) - i) / 60:.0f} min", flush=True)
            if gpu_after is not None and gpu_after >= GPU_STOP:
                raise SystemExit(f"GPU reached {gpu_after} C (limit {GPU_STOP} C); stopping the sweep to protect it")
    finally:
        keep_awake(False)
        cleanup()
