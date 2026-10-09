"""Empty the Windows standby (file) cache before cold-cache benchmark runs.

Triggers the scheduled task \\GeoGuessers\\GeoGuessers-FlushCache (RAMMap -Et, runs elevated),
so the benchmark itself does not need admin rights. One-time setup, as administrator:
    powershell -ExecutionPolicy Bypass -File bench\\register_flush_task.ps1
"""
import subprocess
import time

TASK = r"\GeoGuessers\GeoGuessers-FlushCache"


def _ps(cmd):
    return subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                          capture_output=True, text=True, check=True).stdout.strip()


def standby_mb():
    """Current size of the standby list (cached file pages), in MB."""
    q = ("(Get-Counter '\\Memory\\Standby Cache Normal Priority Bytes',"
         "'\\Memory\\Standby Cache Reserve Bytes','\\Memory\\Standby Cache Core Bytes')"
         ".CounterSamples | Measure-Object CookedValue -Sum | % Sum")
    return float(_ps(q)) / 2**20


def flush(timeout=60):
    """Run the flush task and wait until it finishes. Returns seconds taken."""
    t = time.perf_counter()
    subprocess.run(["schtasks", "/run", "/tn", TASK], capture_output=True, text=True, check=True)
    time.sleep(0.5)
    state = f"(Get-ScheduledTask -TaskPath '\\GeoGuessers\\' -TaskName 'GeoGuessers-FlushCache').State"
    while _ps(state) == "Running":
        if time.perf_counter() - t > timeout:
            raise TimeoutError("cache flush task did not finish")
        time.sleep(0.2)
    result = _ps("(Get-ScheduledTaskInfo -TaskPath '\\GeoGuessers\\' -TaskName 'GeoGuessers-FlushCache').LastTaskResult")
    if result != "0":
        raise RuntimeError(f"cache flush task failed, LastTaskResult={result}")
    return time.perf_counter() - t
