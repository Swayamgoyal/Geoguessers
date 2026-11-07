"""E6: interactive viewing. The virtual client (bench/vclient.py, the browser's policy in Python) replays seeded
traces (bench/traces) against a fresh tile server, one factor changed at a time around the defaults.

Protocol, per (configuration, trace): 1 warm-up + 5 measured runs. Every run starts a new server process (empty
block and result caches; numba kernels warmed on the other dataset first), the OS file cache warm (or flushed for
`cold`), and the client loads the overview and the first view with its prefetch ring before the trace clock starts.
Server counters are read from /stats at the trace start and end; RSS, free memory and CPU are sampled every 50 ms.

Writes (rows appended as runs finish; an interrupted sweep resumes where it stopped):
    results/runs.csv          one row per measured run (experiment E6), metrics in `extra`
    results/e6_requests.csv   every tile request of the measured runs
    results/e6_gestures.csv   every zoom gesture: time to first frame / complete view, tiles requested
    results/e6_frames.csv     every 60 Hz frame of rep 1 (exact / fallback / overview area, in-flight, cache)
    results/e6_memory.csv     server RSS every 50 ms, rep 1 of zoom-pan and box

    python -m bench.experiments.e6_view                     # the whole sweep (about 2.5 hours)
    python -m bench.experiments.e6_view --only base --reps 1 --warmup 0     # pilot
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import psutil

from bench.cache import flush
from bench.harness import Recorder, _disk_read_bytes, check_power, keep_awake, snapshot_env
from bench.vclient import load_policy, run, run_trace
from demlab.cpus import core_sets

REPO = Path(__file__).resolve().parents[2]
RES = REPO / "results"
TRACES = REPO / "bench" / "traces"
PORT = 8766
BASE = f"http://127.0.0.1:{PORT}"

PAN = ["pan-line-0.5", "pan-line-1", "pan-line-2", "pan-reverse-0.5", "pan-reverse-1", "pan-reverse-2", "pan-walk"]
ZOOM = ["zoom-burst-in-0.3", "zoom-burst-out-0.3", "zoom-burst-in-1", "zoom-burst-out-1", "zoom-burst-in-2",
        "zoom-burst-out-2", "zoom-pan"]
MIX = ["pan-walk", "zoom-pan", "zoom-burst-in-1", "zoom-burst-out-1", "box"]
ALL = PAN + ZOOM + ["box"]

# server environment for every run: prefetch pauses only below 0.5 GB free (this laptop often has < 2 GB free with
# the editor open; 503 answers are counted in every run, so a pause would show)
SERVER_ENV = {"DEMLAB_BG_MIN_FREE_GB": "0.5"}


def configs():
    """(name, factor, server env, policy overrides, dataset, params, cache state, traces); `base` = the defaults."""
    hs = {"op": "hillshade", "method": "Horn", "mode": "auto"}
    out = [("base", "base", {}, {}, "chamoli_2m", hs, "warm", ALL)]
    for d in (0, 100, 150, 250):
        out.append((f"debounce-{d or 'off'}", "debounce", {}, {"debounceMs": d}, "chamoli_2m", hs, "warm", ZOOM))
    out.append(("maxwait-500", "debounce", {}, {"maxWaitMs": 500}, "chamoli_2m", hs, "warm", ZOOM))
    out.append(("prefetch-off", "prefetch", {}, {"prefetch": {"enabled": False}}, "chamoli_2m", hs, "warm",
                PAN + ["zoom-pan", "box"]))
    for name, ms in (("backoff-100", 100), ("prefetch-no-backoff", 1e9)):    # base: 250 ms
        out.append((name, "prefetch", {}, {"prefetch": {"backoffP95Ms": ms}}, "chamoli_2m", hs, "warm",
                    PAN + ["zoom-pan"]))
    out.append(("ring-fixed-order", "prefetch", {}, {"prefetch": {"order": "fixed"}}, "chamoli_2m", hs, "warm", PAN))
    out.append(("bg-shared-pcores", "placement", {"DEMLAB_BG_SHARED": "1"}, {}, "chamoli_2m", hs, "warm",
                PAN + ["zoom-pan"]))
    out.append(("bg-no-yield", "placement", {"DEMLAB_BG_YIELD": "0"}, {}, "chamoli_2m", hs, "warm",
                PAN + ["zoom-pan"]))
    for n in (4, 6):
        out.append((f"fg-workers-{n}", "workers", {"DEMLAB_FG_WORKERS": str(n)}, {}, "chamoli_2m", hs, "warm", MIX))
    for n in (2, 4):
        out.append((f"bg-workers-{n}", "workers", {"DEMLAB_BG_WORKERS": str(n)}, {}, "chamoli_2m", hs, "warm",
                    PAN + ["zoom-pan"]))
    for mb in (0, 256):
        out.append((f"block-cache-{mb}", "caches", {"DEMLAB_BLOCK_CACHE_MB": str(mb)}, {}, "chamoli_2m", hs, "warm",
                    MIX))
    out.append(("result-cache-off", "caches", {"DEMLAB_RESULT_CACHE_MB": "0"}, {}, "chamoli_2m", hs, "warm", MIX))
    for op in ("slope", "aspect"):
        out.append((f"op-{op}", "op", {}, {}, "chamoli_2m", {"op": op, "method": "Horn", "mode": "auto"}, "warm", MIX))
    out.append(("mode-precomputed", "mode", {}, {}, "chamoli_2m", {"op": "slope", "method": "Horn",
                                                                   "mode": "precomputed"}, "warm", MIX))
    out.append(("tile571-8m", "dataset", {}, {}, "tile571_8m", hs, "warm", MIX + ["pan-line-1", "zoom-burst-in-2"]))
    out.append(("cold", "cache_state", {}, {}, "chamoli_2m", hs, "cold", MIX))
    return out


FIELDS_REQ = ["run_id", "config", "trace", "rep", "phase", "gesture", "gen", "priority", "level", "tx", "ty",
              "t_start", "t_end", "ms", "status", "tier", "queue", "read", "decode", "kernel", "colormap", "encode",
              "bytes", "cancel_stage", "drawn"]
FIELDS_FRAME = ["run_id", "config", "trace", "t", "level", "ideal", "gesture_active", "visible", "exact",
                "exact_share", "fallback_share", "overview_share", "data_share", "fg_inflight", "bg_inflight",
                "cache_mib"]
FIELDS_GEST = ["run_id", "config", "trace", "rep", "gesture", "kind", "t_first", "t_last", "duration", "ticks",
               "level_before", "ttff_ms", "complete_ms", "fg_requested", "fg_ok", "fg_aborted", "fg_superseded"]
FIELDS_MEM = ["run_id", "config", "trace", "t", "rss_mb", "free_mb"]


def append(path, fields, rows):
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore")
        if new:
            w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})


# ---------------------------------------------------------------- server process
def start_server(env_over):
    env = {**os.environ, **SERVER_ENV, **env_over}
    p = subprocess.Popen([sys.executable, "-m", "server", "--port", str(PORT)], cwd=REPO, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t0 = time.time()
    while time.time() - t0 < 90:
        if p.poll() is not None:
            raise RuntimeError("tile server exited at start")
        try:
            if httpx.get(BASE + "/info", timeout=1, trust_env=False).status_code == 200:
                return p
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    p.kill()
    raise RuntimeError("tile server did not start")


def stop_server(p):
    p.kill()
    p.wait(timeout=30)


def warm_kernels(info, dataset, params):
    """Compile / load the numba kernels and the encoder on the *other* dataset, so the trace's caches stay empty."""
    other = next((n for n in info["datasets"] if n != dataset), dataset)
    lv = info["datasets"][other]["levels"][-1]
    q = "&".join(f"{k}={v}" for k, v in params.items() if k != "mode")
    httpx.get(f"{BASE}/tiles/{other}/{lv['k']}/0/0.png?{q}", timeout=60, trust_env=False)


class Sampler(threading.Thread):
    """Server RSS and free memory every 50 ms."""

    def __init__(self, pid):
        super().__init__(daemon=True)
        self.proc = psutil.Process(pid)
        self.rows, self.stop = [], threading.Event()

    def run(self):
        while not self.stop.is_set():
            try:
                self.rows.append({"abs": time.perf_counter(), "rss_mb": self.proc.memory_info().rss / 2**20,
                                  "free_mb": psutil.virtual_memory().available / 2**20})
            except psutil.Error:
                return
            self.stop.wait(0.05)


def class_util(c0, c1, sets):
    """Busy share of each core class between two psutil.cpu_times(percpu=True) snapshots."""
    out = {}
    for name, cpus in sets.items():
        busy = total = 0.0
        for c in cpus:
            a, b = c0[c], c1[c]
            t = sum(b) - sum(a)
            busy += t - (b.idle - a.idle)
            total += t
        out[name] = busy / total if total else None
    return out


def delta(a, b):
    if isinstance(b, dict):
        return {k: delta(a.get(k, 0) if isinstance(a, dict) else 0, v) for k, v in b.items()}
    if isinstance(b, (int, float)):
        return b - (a or 0)
    return b


# ---------------------------------------------------------------- one run
def run_once(cfg, trace, sets):
    name, factor, env_over, pol_over, dataset, params, cache, _ = cfg
    if cache == "cold":
        flush()
    srv = start_server(env_over)
    try:
        info = httpx.get(BASE + "/info", trust_env=False).json()
        warm_kernels(info, dataset, params)
        proc = psutil.Process(srv.pid)
        snap = {}

        async def ready():
            snap["stats"] = httpx.get(BASE + "/stats", trust_env=False).json()
            snap["cpu"] = psutil.cpu_times(percpu=True)
            snap["proc_cpu"] = sum(proc.cpu_times()[:2])
            snap["io"] = proc.io_counters().read_bytes
            snap["disk"] = _disk_read_bytes()
            snap["t"] = time.perf_counter()

        sampler = Sampler(srv.pid)
        sampler.start()
        out = run(run_trace(BASE, info, dataset, params, trace, policy=load_policy(pol_over),
                                    on_ready=ready))
        t1 = time.perf_counter()
        s1 = httpx.get(BASE + "/stats", trust_env=False).json()
        cpu1 = psutil.cpu_times(percpu=True)
        proc_cpu1 = sum(proc.cpu_times()[:2])
        io1, disk1 = proc.io_counters().read_bytes, _disk_read_bytes()
        sampler.stop.set()
        sampler.join(2)
    finally:
        stop_server(srv)
    s0 = snap["stats"]
    sched = delta(s0["scheduler"], s1["scheduler"])
    dur = t1 - snap["t"]
    mem = [{"t": r["abs"] - snap["t"], "rss_mb": r["rss_mb"], "free_mb": r["free_mb"]} for r in sampler.rows
           if r["abs"] >= snap["t"]]
    ran = {}
    for pool in ("fg", "bg"):
        per = {}
        for cpu, n in sched["ran_on"][pool].items():
            cls = next((k for k, v in sets.items() if int(cpu) in v), "other")
            per[cls] = per.get(cls, 0) + n
        ran[pool] = per
    wheel = sum(1 for g in out["gestures"] if g["kind"] == "wheel")
    bp = sched["by_pool"]
    server = {
        "fg_completed": bp["fg"]["completed"], "fg_cancelled_running": bp["fg"]["cancelled_running"],
        "fg_cancelled_queued": bp["fg"]["cancelled_queued"], "bg_completed": bp["bg"]["completed"],
        "bg_cancelled_running": bp["bg"]["cancelled_running"], "bg_cancelled_queued": bp["bg"]["cancelled_queued"],
        "joined": sched["counters"]["joined"], "promoted": sched["counters"]["promoted"],
        "cpu_s": sched["cpu_s"], "ran_on_class": ran, "class_util": class_util(snap["cpu"], cpu1, sets),
        "blocks_decoded": s1["blocks"]["decoded"] - s0["blocks"]["decoded"],
        "block_hits": s1["blocks"]["hits"] - s0["blocks"]["hits"],
        "block_misses": s1["blocks"]["misses"] - s0["blocks"]["misses"],
        "result_hits": s1["results"]["hits"] - s0["results"]["hits"],
        "block_cache_mb": s1["blocks"]["bytes"] / 2**20, "result_cache_mb": s1["results"]["bytes"] / 2**20,
        "rss_end_mb": s1["rss_mb"], "rss_peak_mb": max((r["rss_mb"] for r in mem), default=None),
        "free_min_mb": min((r["free_mb"] for r in mem), default=None),
    }
    computed_fg = server["fg_completed"] + server["fg_cancelled_running"]
    server["server_fg_tiles_per_wheel_gesture"] = computed_fg / wheel if wheel else None
    return out, server, dur, proc_cpu1 - snap["proc_cpu"], (io1 - snap["io"]) / 1e6, (disk1 - snap["disk"]) / 1e6, mem


def main():
    global RES
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="configuration names (default: all)")
    ap.add_argument("--traces", nargs="*", help="limit to these traces")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--warmup", type=int, default=1)
    ap.add_argument("--allow-battery", action="store_true")
    ap.add_argument("--results", default=str(RES), help="output folder (default results/; a pilot can go elsewhere)")
    a = ap.parse_args()
    RES = Path(a.results)
    RES.mkdir(parents=True, exist_ok=True)
    check_power(a.allow_battery)
    keep_awake(True)
    if RES == REPO / "results":
        snapshot_env("E6")
    p, e, lp = core_sets()
    sets = {"P": p, "E": e, "LP": lp}
    rec = Recorder(RES / "runs.csv")
    traces = {t.stem: json.loads(t.read_text()) for t in TRACES.glob("*.json")}
    plan = [c for c in configs() if not a.only or c[0] in a.only]
    total = sum(len([t for t in c[7] if not a.traces or t in a.traces]) for c in plan) * (a.reps + a.warmup)
    done = 0
    t_start = time.time()
    for cfg in plan:
        name, factor, env_over, pol_over, dataset, params, cache, tnames = cfg
        for tname in tnames:
            if a.traces and tname not in a.traces:
                continue
            trace = traces[tname]
            for rep in range(1 - a.warmup, a.reps + 1):
                done += 1
                meta = {"experiment": "E6", "dataset": dataset, "variant": f"{name}|{tname}", "op": params["op"],
                        "method": params.get("method", ""), "impl": "tile-server+vclient", "cache_state": cache,
                        "rep": rep}
                if rep >= 1 and rec.is_done(meta):
                    continue
                try:
                    out, server, dur, cpu_s, io_mb, disk_mb, mem = run_once(cfg, trace, sets)
                    ok, err = True, ""
                except Exception as ex:  # noqa: BLE001 - recorded, sweep continues
                    ok, err, out = False, f"{type(ex).__name__}: {ex}", None
                el = time.time() - t_start
                print(f"[{done}/{total} {el / 60:.0f} min] {name} {tname} rep {rep}: "
                      f"{'ok' if ok else err}", flush=True)
                if rep < 1:
                    continue
                run_id = rec.next_id
                if not ok:
                    rec.write({**meta, "variant": meta["variant"]}, {"ok": False, "error": err[:300]}, ["e6_view"])
                    continue
                sm = out["summary"]
                tag = {"run_id": run_id, "config": name, "trace": tname, "rep": rep}
                append(RES / "e6_requests.csv", FIELDS_REQ, [{**tag, **r} for r in out["requests"]])
                append(RES / "e6_gestures.csv", FIELDS_GEST, [{**tag, **g} for g in out["gestures"]])
                if rep == 1:
                    append(RES / "e6_frames.csv", FIELDS_FRAME, [{**tag, **f} for f in out["frames"]])
                    if tname in ("zoom-pan", "box"):
                        append(RES / "e6_memory.csv", FIELDS_MEM, [{**tag, **m} for m in mem])
                ds_res = {"chamoli_2m": 2, "tile571_8m": 8}.get(dataset, "")
                extra = {"factor": factor, "config": name, "trace": tname, "family": trace["family"],
                         "mode": params.get("mode"), "server_env": env_over, "policy": pol_over, **sm, **server}
                rec.write({**meta, "res_m": ds_res, "real_or_synthetic": "real", "format": "COG",
                           "compression": "ZSTD", "device": "cpu",
                           "threads": int(env_over.get("DEMLAB_FG_WORKERS", 8)),
                           "cpu_set": ("fg P-cores, bg P-cores (yield)" if env_over.get("DEMLAB_BG_SHARED") == "1"
                                       else "fg P-cores, bg E-cores")},
                          {"t_total": round(dur, 3), "t_internal": round(sm["duration_s"], 3),
                           "peak_rss_mb": round(server["rss_peak_mb"] or 0, 1),
                           "avg_cores": round(cpu_s / dur, 2) if dur else "",
                           "proc_read_mb": round(io_mb, 1), "disk_read_mb": round(disk_mb, 1), "ok": True,
                           "error": "", "extra": json.dumps(extra, default=float)},
                          ["python -m bench.experiments.e6_view", name, tname])
    keep_awake(False)


if __name__ == "__main__":
    main()
