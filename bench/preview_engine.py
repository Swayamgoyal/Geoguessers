"""Informal first look at the engine on one grid (NOT a benchmark: no cold cache, no pinning, no repeats).
Proper measurements will go through the harness as experiments E3/E4.

    python -m bench.preview_engine [grid.tif]
"""
import sys
import time
from pathlib import Path

from demlab.engine import run

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else r"D:\geoguessers_data\prepared\tile571_8m.tif")
OUT = Path(r"D:\geoguessers_data\bench_out")

run(SRC, {"slope": OUT / "warmup.tif"}, backend="numba", window=1024, write=False)  # JIT compile + warm cache
for label, kw in [("numba slope, no write", dict(outputs={"slope": OUT / "a.tif"}, backend="numba", write=False)),
                  ("numba slope, write", dict(outputs={"slope": OUT / "a.tif"}, backend="numba")),
                  ("numba slope+aspect+hillshade, write",
                   dict(outputs={o: OUT / f"{o}.tif" for o in ("slope", "aspect", "hillshade")}, backend="numba")),
                  ("cupy slope, no write", dict(outputs={"slope": OUT / "a.tif"}, backend="cupy", write=False)),
                  ("numpy slope, no write", dict(outputs={"slope": OUT / "a.tif"}, backend="numpy", write=False))]:
    t = run(SRC, **kw)
    print(f"{label:38s} total {t['total']:6.2f} s | wait-for-read {t['read']:5.2f}  compute {t['compute']:5.2f}"
          f"  write {t['write']:5.2f} | {t['cells'] / 1e6:.0f} M cells, {t['windows']} windows", flush=True)
for p in OUT.glob("*.tif"):
    p.unlink()
