"""Tile service: datasets + block cache + result cache + scheduler, independent of HTTP (used by server/app.py,
the tests and the E6 benchmark).

Request path for one tile: result cache hit -> answer at once (tier "result"); otherwise submit a job to the
scheduler (single-flight by tile key) -> render (tier "warm" if every block came from the block cache, "cold" if any
block was decoded) -> store the PNG in the result cache.

    svc = TileService.from_env()
    out = svc.cached(spec_kw...)            # or ticket = svc.submit(...); out = ticket.future.result()
"""
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from demlab import colormap
from demlab.blockcache import BlockCache
from demlab.resultcache import ResultCache, tile_key
from demlab.sched import Scheduler
from demlab.view import TILE, OPS, Pyramid, TileSpec, expected_error, render_tile

DATA = Path(os.environ.get("GEO_DATA", r"D:\geoguessers_data"))


def default_datasets():
    """{name: (dem path, precomputed slope pyramid path or None)} for the datasets that exist on this machine."""
    out = {}
    for name in ("chamoli_2m", "tile571_8m"):
        dem = DATA / "prepared" / f"{name}.tif"
        pre = DATA / "bench_out" / f"e5_slope_{name}.tif"
        if dem.exists():
            out[name] = (dem, pre if pre.exists() else None)
    return out


@dataclass
class TileOutcome:
    png: bytes = None           # None = empty tile (outside the DEM or all nodata)
    tier: str = ""              # result / warm / cold
    timings: dict = field(default_factory=dict)   # ms per stage, incl. queue
    level_cell: float = 0.0
    blocks: dict = field(default_factory=dict)


class TileService:
    def __init__(self, datasets, block_mb=1024, result_mb=512, fg_workers=8, bg_workers=3, bg_shared=False,
                 bg_cap=256, bg_min_free_gb=1.0, bg_yield=True):
        os.environ.setdefault("GDAL_CACHEMAX", "128")  # small: each thread-local handle keeps its own copy
        self.pyramids = {name: Pyramid(p, name=name, precomputed=pre) for name, (p, pre) in datasets.items()}
        self.blocks = BlockCache(block_mb)
        self.results = ResultCache(result_mb)
        self.sched = Scheduler(self._run, fg_workers=fg_workers, bg_workers=bg_workers, bg_shared=bg_shared,
                               bg_cap=bg_cap, bg_min_free_gb=bg_min_free_gb, bg_yield=bg_yield)
        self.started = time.time()

    @classmethod
    def from_env(cls, datasets=None):
        e = os.environ.get
        return cls(datasets or default_datasets(), block_mb=int(e("DEMLAB_BLOCK_CACHE_MB", 1024)),
                   result_mb=int(e("DEMLAB_RESULT_CACHE_MB", 512)), fg_workers=int(e("DEMLAB_FG_WORKERS", 8)),
                   bg_workers=int(e("DEMLAB_BG_WORKERS", 3)), bg_shared=e("DEMLAB_BG_SHARED", "0") == "1",
                   bg_min_free_gb=float(e("DEMLAB_BG_MIN_FREE_GB", 1.0)),
                   bg_yield=e("DEMLAB_BG_YIELD", "1") == "1")

    # ---------------------------------------------------------------- specs
    def spec(self, dataset, level, tx, ty, **kw):
        if dataset not in self.pyramids:
            raise KeyError(f"unknown dataset {dataset!r}")
        if kw.get("op", "slope") not in OPS:
            raise ValueError(f"unknown op {kw.get('op')!r}")
        if kw.get("mode", "auto") not in ("auto", "exact", "precomputed"):
            raise ValueError(f"unknown mode {kw.get('mode')!r}")
        return self.pyramids[dataset], TileSpec(level=int(level), tx=int(tx), ty=int(ty), **kw)

    def key(self, pyr, spec):
        return tile_key(spec.key_dict(pyr))

    # ---------------------------------------------------------------- tiles
    def cached(self, pyr, spec):
        """TileOutcome from the result cache, or None."""
        png = self.results.get(self.key(pyr, spec))
        if png is None:
            return None
        return TileOutcome(png=png or None, tier="result", level_cell=pyr.levels[spec.level].res)

    def submit(self, pyr, spec, session="", gen=0, priority="fg", order=0.0):
        return self.sched.submit(self.key(pyr, spec), (pyr, spec), session=session, gen=gen, priority=priority,
                                 order=order)

    def _run(self, job):
        pyr, spec = job.payload
        queue_ms = (job.started_at - job.queued_at) * 1e3
        r = render_tile(pyr, spec, self.blocks, job.token)
        png = None if r.empty else r.png
        self.results.put(job.key, png or b"")  # empty tiles cached as b"" (0 bytes)
        t = {k: v * 1e3 for k, v in r.timings.items()}
        t["queue"] = queue_ms
        tier = "cold" if r.blocks.get("decoded") or spec.mode == "exact" else "warm"
        return TileOutcome(png=png, tier=tier, timings=t, level_cell=pyr.levels[spec.level].res, blocks=r.blocks)

    def tile_sync(self, pyr, spec, priority="fg"):
        """Blocking convenience: cache or render (used by tests and scripts)."""
        hit = self.cached(pyr, spec)
        if hit is not None:
            return hit
        return self.submit(pyr, spec, priority=priority).future.result()

    # ---------------------------------------------------------------- whole-map overview
    def overview(self, dataset, **kw):
        """(png, bounds) of the coarsest level as one image; bounds cover the whole lattice of that level."""
        pyr = self.pyramids[dataset]
        k = len(pyr.levels) - 1
        lv = pyr.levels[k]
        spec0 = TileSpec(level=k, tx=0, ty=0, **kw)
        nod = 0 if spec0.op == "hillshade" else -9999.0
        mosaic = None
        for ty in range(lv.nty):
            for tx in range(lv.ntx):
                r = render_tile(pyr, TileSpec(level=k, tx=tx, ty=ty, **kw), self.blocks, encode=False)
                if mosaic is None:
                    mosaic = np.full((lv.nty * TILE, lv.ntx * TILE), nod, r.values.dtype)
                mosaic[ty * TILE:(ty + 1) * TILE, tx * TILE:(tx + 1) * TILE] = r.values
        cmap = spec0.colormap()
        png = colormap.encode_png(colormap.quantise(spec0.op, mosaic, cmap), colormap.palette(cmap["name"]))
        a, _, c, _, e, f = lv.transform
        bounds = (c, f + e * lv.nty * TILE, c + a * lv.ntx * TILE, f)
        return png, bounds, k

    # ---------------------------------------------------------------- info, stats
    def info(self):
        out = {"tile": TILE, "ops": list(OPS), "modes": ["auto", "exact", "precomputed"], "datasets": {}}
        for name, pyr in self.pyramids.items():
            d = pyr.info()
            for lv in d["levels"]:
                ee = expected_error(name, lv["k"])
                lv["expected_rmse"], lv["expected_bias"] = (ee if ee else (None, None))
            out["datasets"][name] = d
        out["legends"] = {op: colormap.legend(op) for op in OPS}
        out["colormaps"] = colormap.DEFAULTS
        return out

    def stats(self):
        import psutil
        p = psutil.Process()
        return {"uptime_s": time.time() - self.started, "rss_mb": p.memory_info().rss / 2**20,
                "free_mb": psutil.virtual_memory().available / 2**20,
                "blocks": self.blocks.stats(), "results": self.results.stats(), "scheduler": self.sched.stats()}

    def close(self):
        self.sched.shutdown()
