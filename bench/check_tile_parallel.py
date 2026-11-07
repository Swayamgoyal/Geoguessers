"""Phase 5 gate: do tiles render in parallel on worker threads (GIL released)?

Renders the same 64 Chamoli 2 m level-0 tiles with 1, 2, 4 and 8 threads, process pinned to the performance cores,
block cache warm (so the threads compete only on computing, colouring and encoding). Gate (FINAL_PLAN Phase 1):
8 threads at least 5× faster than 1 thread. Also reports the kernel alone and a cold-cache pass.

    python -m bench.check_tile_parallel
"""
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import psutil

from bench.harness import performance_cpus
from bench.sweep import DATA
from demlab.blockcache import BlockCache
from demlab.kernels import tile_k
from demlab.view import Pyramid, TileSpec, render_tile


def main():
    psutil.Process().cpu_affinity(performance_cpus())
    pyr = Pyramid(DATA / "prepared" / "chamoli_2m.tif")
    lv = pyr.levels[0]
    tiles = [(tx, ty) for ty in range(12, 20) for tx in range(10, 18)]  # 64 tiles inside the data
    cache = BlockCache(1024)
    t = time.perf_counter()
    for tx, ty in tiles:  # cold pass, one thread: decode included
        render_tile(pyr, TileSpec(level=0, tx=tx, ty=ty), cache)
    cold = time.perf_counter() - t
    print(f"cold, 1 thread: {cold:.2f} s for 64 tiles ({cold / 64 * 1e3:.1f} ms/tile), "
          f"blocks decoded {cache.decoded} (vs up to {64 * 9} without the cache)")

    def full(n):
        with ThreadPoolExecutor(n) as ex:
            t = time.perf_counter()
            list(ex.map(lambda p: render_tile(pyr, TileSpec(level=0, tx=p[0], ty=p[1]), cache), tiles))
            return time.perf_counter() - t

    z = np.random.default_rng(0).random((514, 514), dtype=np.float32) * 3000

    def kernel(n):
        with ThreadPoolExecutor(n) as ex:
            t = time.perf_counter()
            list(ex.map(lambda _: tile_k.compute("slope", z, 2.0), range(64)))
            return time.perf_counter() - t

    for name, fn in (("full render (warm blocks)", full), ("kernel only", kernel)):
        fn(1)
        base = min(fn(1) for _ in range(3))
        row = []
        for n in (1, 2, 4, 8):
            best = min(fn(n) for _ in range(3))
            row.append(f"{n} thr {best * 1e3:6.0f} ms ({base / best:4.1f}x)")
        print(f"{name:26s}: " + " | ".join(row))
    print("gate: 8 threads >= 5x faster than 1 thread (full render)")


if __name__ == "__main__":
    main()
