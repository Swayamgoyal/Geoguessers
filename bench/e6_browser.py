"""E6 browser check: replay traces in real headless Chrome and compare with the virtual client.

For each trace and repeat: a fresh tile server (same settings as E6), headless Chrome on a throw-away profile, the
page /viewer/?trace=<name> (viz/web/js/tracerun.js replays the trace in the real viewer, in real time), results read
back over the Chrome DevTools protocol (websockets; no Playwright needed). Writes results/e6_browser.csv, one row per
gesture (or one per run for traces without gestures), and prints the browser medians next to the virtual client's
E6 `base` medians from results/runs.csv.

    python -m bench.e6_browser [--traces zoom-burst-in-1 pan-line-1 box] [--reps 3]
"""
import argparse
import asyncio
import csv
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from statistics import median

import httpx
import websockets

from bench.experiments.e6_view import BASE, start_server, stop_server, warm_kernels

REPO = Path(__file__).resolve().parent.parent
RES = REPO / "results"
CHROME = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
          r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]
CDP_PORT = 9333
FIELDS = ["trace", "rep", "ready", "commits", "fg_requests", "fg_tiles", "bg_tiles", "prefetched_during_trace",
          "gesture", "kind", "ticks", "ttff_ms", "complete_ms"]


async def cdp_eval(ws, expr, _id=[0]):
    _id[0] += 1
    await ws.send(json.dumps({"id": _id[0], "method": "Runtime.evaluate",
                              "params": {"expression": expr, "returnByValue": True}}))
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("id") == _id[0]:
            return msg.get("result", {}).get("result", {}).get("value")


async def replay(url, timeout=90):
    for _ in range(100):
        try:
            pages = httpx.get(f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=1, trust_env=False).json()
            page = next(p for p in pages if p.get("type") == "page")
            break
        except (httpx.HTTPError, StopIteration, ValueError):
            await asyncio.sleep(0.2)
    else:
        raise RuntimeError("Chrome DevTools endpoint did not come up")
    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
        await ws.send(json.dumps({"id": 0, "method": "Page.navigate", "params": {"url": url}}))
        t0 = time.time()
        while time.time() - t0 < timeout:
            v = await cdp_eval(ws, "(document.getElementById('tracerun') || {}).textContent || ''")
            if v:
                return json.loads(v)
            err = await cdp_eval(ws, "document.body ? document.body.innerText.includes('Viewer failed') : false")
            if err:
                raise RuntimeError("viewer failed to start")
            await asyncio.sleep(0.25)
    raise TimeoutError("trace replay did not finish")


def run_once(trace, dataset="chamoli_2m"):
    exe = next((c for c in CHROME if os.path.exists(c)), None)
    if exe is None:
        raise SystemExit("Chrome not found")
    srv = start_server({})
    try:
        info = httpx.get(BASE + "/info", trust_env=False).json()
        warm_kernels(info, dataset, {"op": "hillshade", "method": "Horn"})
        with tempfile.TemporaryDirectory(prefix="e6_chrome_", ignore_cleanup_errors=True) as prof:
            chrome = subprocess.Popen([exe, "--headless=new", f"--remote-debugging-port={CDP_PORT}",
                                       f"--user-data-dir={prof}", "--window-size=1920,1080", "--no-first-run",
                                       "--disable-extensions", "--mute-audio", "--disable-background-timer-throttling",
                                       "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows",
                                       "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                return asyncio.run(replay(f"{BASE}/viewer/?trace={trace}"))
            finally:
                chrome.kill()
                chrome.wait(timeout=30)
                time.sleep(0.5)
    finally:
        stop_server(srv)


def vclient_base(trace):
    """Virtual-client medians for the same trace from the E6 sweep (config base)."""
    p = RES / "runs.csv"
    rows = []
    if p.exists():
        for r in csv.DictReader(open(p, newline="")):
            if r["experiment"] == "E6" and r["ok"] == "True" and r["variant"] == f"base|{trace}" and int(r["rep"]) >= 1:
                rows.append(json.loads(r["extra"]))
    if not rows:
        return {}
    m = lambda k: median([x[k] for x in rows if x.get(k) is not None]) if any(x.get(k) is not None for x in rows) \
        else None  # noqa: E731
    return {"commits": m("commits"), "fg_requests": m("fg_requests"), "ttff_ms": m("ttff_ms_median"),
            "complete_ms": m("complete_ms_median"), "runs": len(rows)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", nargs="*", default=["zoom-burst-in-1", "pan-line-1", "box"])
    ap.add_argument("--reps", type=int, default=3)
    a = ap.parse_args()
    out_rows = []
    summary = {}
    for tr in a.traces:
        runs = []
        for rep in range(1, a.reps + 1):
            res = run_once(tr)
            runs.append(res)
            base = {"trace": tr, "rep": rep, **{k: res.get(k) for k in FIELDS if k in res}}
            gs = res.get("gestures") or [{}]
            for g in gs:
                out_rows.append({**base, **{k: g.get(k) for k in ("gesture", "kind", "ticks", "ttff_ms",
                                                                     "complete_ms")}})
            print(f"{tr} rep {rep}: commits {res['commits']}, fg requests {res['fg_requests']}, "
                  f"gestures {[(round(g['ttff_ms'] or -1), round(g['complete_ms'] or -1)) for g in res['gestures']]}",
                  flush=True)
        ttff = [g["ttff_ms"] for r in runs for g in r["gestures"] if g.get("ttff_ms") is not None]
        comp = [g["complete_ms"] for r in runs for g in r["gestures"] if g.get("complete_ms") is not None]
        summary[tr] = {"browser": {"commits": median(r["commits"] for r in runs),
                                   "fg_requests": median(r["fg_requests"] for r in runs),
                                   "ttff_ms": median(ttff) if ttff else None,
                                   "complete_ms": median(comp) if comp else None, "runs": len(runs)},
                       "virtual client (E6 base)": vclient_base(tr)}
    with open(RES / "e6_browser.csv", "w", newline="") as f:
        w = csv.DictWriter(f, FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(out_rows)
    (RES / "e6_browser_summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
