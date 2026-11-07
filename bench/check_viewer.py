"""Browser check of the web viewer (final plan Phase 3): runs /viewer/?selftest=1 (viz/web/js/selftest.js) in
real-time headless Chrome against a fresh tile server and prints the result. Driven over the Chrome DevTools
protocol (websockets), not --virtual-time-budget: virtual time fast-forwards timers and distorts every network wait,
which made the prefetch checks fail spuriously.

    python -m bench.check_viewer          # exit code 0 when all four checks pass
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time

import httpx
import websockets

from bench.e6_browser import CDP_PORT, CHROME, cdp_eval
from bench.experiments.e6_view import BASE, start_server, stop_server


async def selftest(url, timeout=120):
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
            await asyncio.sleep(0.5)
            v = await cdp_eval(ws, "(document.getElementById('selftest') || {}).textContent || ''")
            if v:
                return json.loads(v)
    raise TimeoutError("self-test did not finish")


def main():
    exe = next((c for c in CHROME if os.path.exists(c)), None)
    if exe is None:
        raise SystemExit("Chrome not found")
    srv = start_server({})
    try:
        with tempfile.TemporaryDirectory(prefix="viewer_check_", ignore_cleanup_errors=True) as prof:
            ch = subprocess.Popen([exe, "--headless=new", f"--remote-debugging-port={CDP_PORT}",
                                   f"--user-data-dir={prof}", "--window-size=1500,900", "--no-first-run",
                                   "--disable-extensions", "about:blank"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                out = asyncio.run(selftest(f"{BASE}/viewer/?selftest=1"))
            finally:
                ch.kill()
                ch.wait(timeout=30)
    finally:
        stop_server(srv)
    for name, c in out["checks"].items():
        print(f"{'PASS' if c['pass'] else 'FAIL'}  {name}  "
              f"{ {k: (round(v, 1) if isinstance(v, float) else v) for k, v in c.items() if k != 'pass'} }")
    print("ALL PASS" if out["ok"] else "FAILED")
    sys.exit(0 if out["ok"] else 1)


if __name__ == "__main__":
    main()
