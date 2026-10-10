"""Informal first look at the engine on one grid (NOT a benchmark: no cold cache, no pinning, no repeats).
Proper measurements go through the harness as experiment E3 (bench/experiments/e3_cpu.py).

    python -m bench.preview_engine [grid.tif]
"""
import sys
from pathlib import Path

from demlab.engine import run

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else r"D:\geoguessers_data\prepared\tile571_8m.tif")
OUT = Path(r"D:\geoguessers_data\bench_out")
THREE = ("slope", "aspect", "hillshade")

run(SRC, {"slope": OUT / "warmup.tif"}, backend="numba", window=1024, write=False)  # JIT compile + warm cache
cases = [
    ("numba slope, no write", dict(outputs={"slope": OUT / "a.tif"}, write=False)),
    ("numba slope, write", dict(outputs={"slope": OUT / "a.tif"})),
    ("numba slope, write ZSTD", dict(outputs={"slope": OUT / "a.tif"}, compress="ZSTD")),
    ("numba 3 products, write", dict(outputs={o: OUT / f"{o}.tif" for o in THREE})),
    ("numba 3 products, write ZSTD", dict(outputs={o: OUT / f"{o}.tif" for o in THREE}, compress="ZSTD")),
    ("numba slope, 1 thread, write", dict(outputs={"slope": OUT / "a.tif"}, threads=1)),
]
for label, kw in cases:
    t = run(SRC, backend="numba", **kw)
    print(f"{label:30s} total {t['total']:6.2f} s | wait-read {t['read']:5.2f} compute {t['compute']:5.2f} "
          f"wait-write {t['write']:5.2f} (writer busy {t['writer_busy']:5.2f}) | {t['cells'] / 1e6:.0f} M cells",
          flush=True)
    if "threads" in kw:
        import numba
        numba.set_num_threads(numba.config.NUMBA_NUM_THREADS)
for p in OUT.glob("*.tif"):
    p.unlink()
