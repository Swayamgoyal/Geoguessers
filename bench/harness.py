"""Benchmark runner: runs one external command per measurement and appends a row to a CSV.

For each run it records wall time, and (exact, from the exited process's handle) peak memory
(peak working set), average CPU cores used and bytes the process read/wrote; plus bytes
actually read from the physical disks (separates real disk reads from cache hits). Cold runs empty the Windows
file cache first (bench/cache.py). Rows are written as soon as each run ends, and runs
already in the CSV are skipped, so an interrupted sweep can simply be restarted.
"""
import csv
import ctypes
import ctypes.wintypes as wt
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import psutil

from bench.cache import flush

REPO = Path(__file__).resolve().parent.parent
FIELDS = ["run_id", "experiment", "machine_id", "dataset", "res_m", "cells", "real_or_synthetic", "format",
          "compression", "op", "method", "impl", "device", "threads", "cache_state", "rep", "t_total",
          "peak_rss_mb", "avg_cores", "proc_read_mb", "proc_write_mb", "disk_read_mb", "ok", "error",
          "git_sha", "cmd"]
# a run is identified by these; used to skip runs already in the CSV
KEY = ["experiment", "dataset", "op", "method", "impl", "cache_state", "rep"]


def machine_id():
    try:
        return json.loads((REPO / "results" / "machine.json").read_text())["machine_id"]
    except (OSError, KeyError, ValueError):
        return os.environ.get("COMPUTERNAME", "unknown")


def git_sha():
    r = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip()


def keep_awake(on=True):
    """Stop Windows sleeping during a long sweep (ES_CONTINUOUS | ES_SYSTEM_REQUIRED)."""
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | (0x00000001 if on else 0))


def check_power(allow_battery=False):
    b = psutil.sensors_battery()
    if b is not None and not b.power_plugged and not allow_battery:
        raise SystemExit("On battery: plug in the charger (timings change on battery), or pass --allow-battery")


def _disk_read_bytes():
    return sum(d.read_bytes for d in psutil.disk_io_counters(perdisk=True).values())


class _MemCounters(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


class _IoCounters(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount",
                "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


def _final_counters(handle):
    """Exact totals for an exited process, read from its still-open handle:
    peak working set (bytes), CPU time (s), bytes read, bytes written."""
    k32 = ctypes.windll.kernel32
    mem = _MemCounters(cb=ctypes.sizeof(_MemCounters))
    k32.K32GetProcessMemoryInfo(handle, ctypes.byref(mem), mem.cb)
    t = [wt.FILETIME() for _ in range(4)]  # creation, exit, kernel, user
    k32.GetProcessTimes(handle, *[ctypes.byref(x) for x in t])
    cpu = sum((x.dwHighDateTime << 32 | x.dwLowDateTime) for x in t[2:]) / 1e7
    io = _IoCounters()
    k32.GetProcessIoCounters(handle, ctypes.byref(io))
    return mem.PeakWorkingSetSize, cpu, io.ReadTransferCount, io.WriteTransferCount


def measure(cmd, cache_state):
    """Run cmd once and return its measurements. cache_state 'cold' empties the file cache first."""
    if cache_state == "cold":
        flush()
    disk0 = _disk_read_bytes()
    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    _, err = proc.communicate()
    wall = time.perf_counter() - t0
    disk = _disk_read_bytes() - disk0
    peak, cpu, rd, wr = _final_counters(int(proc._handle))  # handle stays open until proc is deleted
    return {
        "t_total": round(wall, 4),
        "peak_rss_mb": round(peak / 2**20, 1),
        "avg_cores": round(cpu / wall, 2) if wall else "",
        "proc_read_mb": round(rd / 2**20, 1),
        "proc_write_mb": round(wr / 2**20, 1),
        "disk_read_mb": round(disk / 2**20, 1),
        "ok": proc.returncode == 0,
        "error": "" if proc.returncode == 0 else err.decode(errors="ignore").strip()[-300:],
    }


class Recorder:
    def __init__(self, csv_path):
        self.path = Path(csv_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.done = set()
        self.next_id = 1
        if self.path.exists():
            with self.path.open(newline="") as f:
                for row in csv.DictReader(f):
                    self.next_id = max(self.next_id, int(row["run_id"]) + 1)
                    if row["ok"] == "True":
                        self.done.add(tuple(row[k] for k in KEY))
        else:
            with self.path.open("w", newline="") as f:
                csv.DictWriter(f, FIELDS).writeheader()
        self.common = {"machine_id": machine_id(), "git_sha": git_sha()}

    def is_done(self, meta):
        return tuple(str(meta[k]) for k in KEY) in self.done

    def write(self, meta, result, cmd):
        row = {**self.common, **meta, **result, "run_id": self.next_id,
               "cmd": " ".join(str(c) for c in cmd)}
        with self.path.open("a", newline="") as f:
            csv.DictWriter(f, FIELDS, extrasaction="ignore").writerow(row)
        self.next_id += 1
        if result["ok"]:
            self.done.add(tuple(str(meta[k]) for k in KEY))


def tool(name):
    path = shutil.which(name)
    if not path:
        raise SystemExit(f"{name} not found: run inside the 'geo' conda env")
    return path
