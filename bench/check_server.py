"""Phase 5 server gates (FINAL_PLAN Phase 2), against a real server process on Chamoli 2 m.

1. Isolation: foreground tile latency p50 / p95 on an idle server vs with the background queue saturated by
   prefetch (256 cold tiles). Gate: p95 within 10%. Foreground tiles use warm blocks and a fresh product each round,
   so both rounds do the same work (kernel + colour + encode, no decode).
2. Cancellation, time from aborting the HTTP request to the server reporting the job cancelled (GET /stats):
   a) a queued job (all foreground workers busy with slow exact tiles): gate within 50 ms;
   b) a running exact-mode tile: stops at its next stage boundary (one strip read, about one block row).
The free-memory guard that pauses prefetch is lowered to 0.5 GB for the isolation round (env var).

    python -m bench.check_server [--port 8799]
"""
import argparse
import asyncio
import os
import subprocess
import sys
import time

import httpx
import numpy as np

DS = "chamoli_2m"


async def wait_up(c, url):
    for _ in range(200):
        try:
            if (await c.get(url + "/info")).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(0.25)
    raise SystemExit("server did not start")


async def fg_round(c, url, tiles, op, conc=4):
    sem = asyncio.Semaphore(conc)
    lat = []

    async def one(tx, ty):
        async with sem:
            t = time.perf_counter()
            r = await c.get(f"{url}/tiles/{DS}/0/{tx}/{ty}.png?op={op}", headers={"X-Priority": "fg"})
            lat.append(time.perf_counter() - t)
            assert r.status_code in (200, 204), r.status_code

    await asyncio.gather(*(one(tx, ty) for tx, ty in tiles))
    a = np.array(lat) * 1e3
    return np.median(a), np.percentile(a, 95)


async def main_async(port):
    url = f"http://127.0.0.1:{port}"
    async with httpx.AsyncClient(timeout=60) as c:
        await wait_up(c, url)
        fg = [(tx, ty) for ty in range(10, 20) for tx in range(5, 15)]            # 100 tiles inside the data
        await fg_round(c, url, fg, "slope")                                       # warm the blocks
        await fg_round(c, url, fg, "TRI")                                         # warm the kernels
        cold_rows = iter(range(0, 35))
        idle, busy = [], []
        for rnd, az in enumerate((0, 60, 120, 180, 240, 300)):                    # same work every round
            loaded = rnd % 2 == 1
            if loaded:
                rows = [next(cold_rows) for _ in range(8)]
                bg = [[tx, ty] for ty in rows for tx in range(16, 28)][:256]      # other, cold tiles
                await c.post(f"{url}/prefetch", json={"dataset": DS, "session": f"load{rnd}", "gen": 1, "level": 0,
                                                      "tiles": bg, "op": "slope"})
                await asyncio.sleep(0.2)
            res = await fg_round(c, url, fg, f"hillshade&azimuth={az}")
            st = (await c.get(f"{url}/stats")).json()["scheduler"]
            (busy if loaded else idle).append(res)
            print(f"round {rnd + 1} {'loaded' if loaded else 'idle  '}: p50 {res[0]:5.1f} ms  p95 {res[1]:5.1f} ms  "
                  f"(bg queued {st['queued']['bg']}, running {st['running']['bg']}, "
                  f"bg busy so far {st['busy_s']['bg']:.1f} s)")
            if loaded:
                await c.post(f"{url}/session/load{rnd}/gen", json={"gen": 99, "cancel_bg": True})
                await asyncio.sleep(0.5)
        i50, i95 = np.median([x[0] for x in idle]), np.median([x[1] for x in idle])
        b50, b95 = np.median([x[0] for x in busy]), np.median([x[1] for x in busy])
        print(f"foreground idle:   p50 {i50:5.1f} ms  p95 {i95:5.1f} ms  (median of 3 rounds x 100 tiles)")
        print(f"foreground loaded: p50 {b50:5.1f} ms  p95 {b95:5.1f} ms  -> p95 {100 * (b95 / i95 - 1):+.1f}% "
              f"(gate: <= +10%)")

        # cancellation a) queued job: occupy all fg workers with slow exact tiles, abort one queued behind them
        slow = [asyncio.create_task(c.get(f"{url}/tiles/{DS}/4/{tx}/{ty}.png?op=slope&mode=exact&zfactor=7"))
                for tx, ty in [(0, 0), (1, 0), (0, 1), (1, 1), (0, 2), (1, 2), (2, 0), (2, 1)]]
        await asyncio.sleep(0.3)
        queued = []
        for i in range(8):
            task = asyncio.create_task(c.get(f"{url}/tiles/{DS}/3/{i % 4}/{2 + i // 4}.png?op=slope&mode=exact"))
            await asyncio.sleep(0.1)
            queued.append(await cancel_delay(c, url, task))
        for t_ in slow:
            t_.cancel()
        await asyncio.sleep(1.0)
        # b) running exact job: abort after 300 ms
        running = []
        for i, (tx, ty) in enumerate([(0, 1), (1, 1), (1, 0), (0, 2), (1, 2)]):
            while (await c.get(f"{url}/stats")).json()["scheduler"]["running"]["fg"]:
                await asyncio.sleep(0.05)
            task = asyncio.create_task(c.get(f"{url}/tiles/{DS}/4/{tx}/{ty}.png?op=slope&mode=exact&zfactor={i}"))
            await asyncio.sleep(0.3)
            running.append(await cancel_delay(c, url, task))
        s = (await c.get(f"{url}/stats")).json()["scheduler"]["counters"]
        print(f"abort -> queued job cancelled:        {', '.join(f'{d:.1f}' for d in queued)} ms "
              f"(median {np.median(queued):.1f}; gate: <= 50 ms)")
        print(f"abort -> running exact job cancelled: {', '.join(f'{d:.0f}' for d in running)} ms "
              f"(stops at the next strip); cancelled at stages {s['cancelled_at']}")


async def cancel_delay(c, url, task):
    """Abort the request and return ms until the server cancelled the job (server-side timestamp)."""
    before = (await c.get(f"{url}/stats")).json()["scheduler"]["last_cancel_wall"]
    t0 = time.time()
    task.cancel()
    for _ in range(500):
        await asyncio.sleep(0.02)
        last = (await c.get(f"{url}/stats")).json()["scheduler"]["last_cancel_wall"]
        if last > before and last >= t0 - 0.001:
            return (last - t0) * 1e3
    return float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--no-yield", action="store_true", help="prefetch does not wait for the foreground")
    a = ap.parse_args()
    env = dict(os.environ, DEMLAB_BG_MIN_FREE_GB="0.5", DEMLAB_BG_YIELD="0" if a.no_yield else "1")
    proc = subprocess.Popen([sys.executable, "-m", "server", "--port", str(a.port)], env=env)
    try:
        asyncio.run(main_async(a.port))
    finally:
        proc.terminate()
        proc.wait(10)


if __name__ == "__main__":
    main()
