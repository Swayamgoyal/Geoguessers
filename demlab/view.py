"""Tile lattice and tile renderer for the interactive viewer (Phase 5).

Every pyramid level k has its own lattice of 512 × 512-cell tiles aligned to that level's block grid: tile (tx, ty)
covers level cells [512·ty, 512·ty + 512) × [512·tx, 512·tx + 512). The lattice comes from each level's own size and
geotransform, because GDAL rounds overview sizes down (Phase 4), so levels are not exact 2^k scalings.

Level choice: with s the ground size of one screen pixel and c_0 < c_1 < ... the level cell sizes,
k = max{j : c_j <= s} (k = 0 when s < c_0): the coarsest level whose cell is still no larger than a pixel. A hysteresis band (±10% on s) keeps the previous level when it is still
valid, so a gesture ending near a boundary does not flip levels.

Modes:
  auto         compute at level k from that level's DEM (constant cost; expected error per level from E5)
  exact        compute at full resolution and average over each level-k cell (exact; cost grows 4× per level)
  precomputed  read the level-k cell from a slope pyramid built in advance (E5; slope Horn only)

    pyr = Pyramid("D:/geoguessers_data/prepared/chamoli_2m.tif")
    k = pyr.choose_level(metres_per_pixel)
    res = render_tile(pyr, TileSpec(level=k, tx=3, ty=5, op="slope"), blockcache)
    res.png, res.values, res.timings
"""
import csv
import math
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from functools import lru_cache
from pathlib import Path

import numpy as np
import rasterio

from demlab import colormap
from demlab.cancel import NEVER
from demlab.kernels import tile_k
from demlab.pyramid import block_sums, footprint_edges

TILE = 512
NODATA = -9999.0
OPS = ("slope", "aspect", "hillshade", "TRI", "TPI", "roughness")
RESULTS = Path(__file__).resolve().parents[1] / "results"


@dataclass(frozen=True)
class Level:
    k: int
    width: int
    height: int
    transform: tuple    # affine (a, b, c, d, e, f): x = a·col + b·row + c, y = d·col + e·row + f
    res: float          # one cell size (geometric mean of x and y), metres
    block: int

    @property
    def ntx(self):
        return math.ceil(self.width / TILE)

    @property
    def nty(self):
        return math.ceil(self.height / TILE)


class Pyramid:
    """A DEM COG and its overview levels."""

    def __init__(self, path, name=None, precomputed=None):
        self.path = str(path)
        self.name = name or Path(path).stem
        st = os.stat(self.path)
        self.version = f"{self.name}:{st.st_size}:{int(st.st_mtime)}"
        levels = []
        with rasterio.open(self.path) as src:
            self.nodata = float(src.nodata if src.nodata is not None else NODATA)
            self.crs = src.crs.to_string() if src.crs else ""
            self.bounds = tuple(src.bounds)
            n_ov = len(src.overviews(1))
        for k in range(n_ov + 1):
            with (rasterio.open(self.path) if k == 0 else rasterio.open(self.path, overview_level=k - 1)) as ds:
                t = ds.transform
                levels.append(Level(k, ds.width, ds.height, (t.a, t.b, t.c, t.d, t.e, t.f),
                                    math.sqrt(abs(ds.res[0] * ds.res[1])), ds.block_shapes[0][0]))
        self.levels = levels
        self.precomputed = Pyramid(precomputed, name=f"{self.name}-slope") if precomputed else None
        self._local = threading.local()

    # ---------------------------------------------------------------- geometry
    def choose_level(self, metres_per_pixel, prev=None, hysteresis=0.10):
        """Pyramid level for a screen pixel of `metres_per_pixel` metres (see module docstring)."""
        def pick(s):
            k = 0
            for lv in self.levels:
                if lv.res <= s:
                    k = lv.k
            return k

        s = float(metres_per_pixel)
        if prev is not None and pick(s / (1 + hysteresis)) <= prev <= pick(s * (1 + hysteresis)):
            return prev
        return pick(s)

    def tile_bounds(self, k, tx, ty):
        """(xmin, ymin, xmax, ymax) of tile (tx, ty) at level k, clipped to the level's extent."""
        lv = self.levels[k]
        a, _, c, _, e, f = lv.transform
        c0, r0 = tx * TILE, ty * TILE
        c1, r1 = min(c0 + TILE, lv.width), min(r0 + TILE, lv.height)
        return (c + a * c0, f + e * r1, c + a * c1, f + e * r0)

    def tiles_for_bbox(self, k, bbox):
        """Lattice tiles (tx, ty) at level k that intersect bbox (xmin, ymin, xmax, ymax), clipped to the grid."""
        lv = self.levels[k]
        a, _, c, _, e, f = lv.transform
        xmin, ymin, xmax, ymax = bbox
        c0 = max(int(math.floor((xmin - c) / a)), 0)
        c1 = min(int(math.ceil((xmax - c) / a)), lv.width)
        r0 = max(int(math.floor((ymax - f) / e)), 0)
        r1 = min(int(math.ceil((ymin - f) / e)), lv.height)
        if c0 >= c1 or r0 >= r1:
            return []
        return [(tx, ty) for ty in range(r0 // TILE, (r1 - 1) // TILE + 1)
                for tx in range(c0 // TILE, (c1 - 1) // TILE + 1)]

    def in_lattice(self, k, tx, ty):
        lv = self.levels[k] if 0 <= k < len(self.levels) else None
        return lv is not None and 0 <= tx < lv.ntx and 0 <= ty < lv.nty

    def handle(self, k):
        """Thread-local rasterio handle of level k (for reads that bypass the block cache)."""
        hs = getattr(self._local, "h", None)
        if hs is None:
            hs = self._local.h = {}
        if k not in hs:
            hs[k] = rasterio.open(self.path) if k == 0 else rasterio.open(self.path, overview_level=k - 1)
        return hs[k]

    def info(self):
        return {"name": self.name, "version": self.version, "crs": self.crs, "bounds": self.bounds,
                "nodata": self.nodata, "tile": TILE, "precomputed": self.precomputed is not None,
                "levels": [{**asdict(lv), "ntx": lv.ntx, "nty": lv.nty} for lv in self.levels]}


@dataclass(frozen=True)
class TileSpec:
    level: int
    tx: int
    ty: int
    op: str = "slope"
    method: str = "Horn"        # Horn / ZevenbergenThorne; Riley / Wilson for TRI
    mode: str = "auto"          # auto / exact / precomputed
    zfactor: float = 1.0
    azimuth: float = 315.0
    altitude: float = 45.0
    cmap: str = ""              # "" = the operator's default colour map
    vmin: float = None
    vmax: float = None

    def key_dict(self, pyr):
        d = asdict(self)
        d.update(dataset=pyr.name, version=pyr.version, tile=TILE)
        if self.op != "hillshade":  # sun and z-factor only change hillshade
            d.pop("azimuth"), d.pop("altitude")
        return d

    def colormap(self):
        c = dict(colormap.DEFAULTS[self.op])
        if self.cmap:
            c["name"] = self.cmap
        if self.vmin is not None:
            c["vmin"] = self.vmin
        if self.vmax is not None:
            c["vmax"] = self.vmax
        return c


@dataclass
class TileResult:
    values: np.ndarray = None   # 512 × 512 product values (float32, -9999 nodata; hillshade uint8, 0 nodata)
    png: bytes = None
    empty: bool = False         # tile outside the DEM or all nodata
    timings: dict = field(default_factory=dict)   # seconds per stage: read, decode, kernel, colormap, encode
    blocks: dict = field(default_factory=dict)    # blocks touched / decoded


def _nodata_of(op):
    return 0 if op == "hillshade" else NODATA


def render_tile(pyr, spec, blockcache, token=NEVER, encode=True):
    """Compute one lattice tile. Cells outside the DEM are nodata (transparent); the tile stays 512 × 512."""
    if spec.op not in OPS:
        raise ValueError(f"unknown op {spec.op!r}")
    if not pyr.in_lattice(spec.level, spec.tx, spec.ty):
        return TileResult(empty=True)
    t0 = time.perf_counter()
    token.check("start")
    if spec.mode == "auto":
        values, info = _auto(pyr, spec, blockcache, token)
    elif spec.mode == "exact":
        values, info = _exact(pyr, spec, token)
    elif spec.mode == "precomputed":
        values, info = _precomputed(pyr, spec, blockcache, token)
    else:
        raise ValueError(f"unknown mode {spec.mode!r}")
    res = TileResult(values=values, timings=info.pop("timings"), blocks=info)
    if not np.any(values != _nodata_of(spec.op)):
        res.empty = True
    if encode and not res.empty:
        token.check("colormap")
        t = time.perf_counter()
        cmap = spec.colormap()
        idx = colormap.quantise(spec.op, values, cmap)
        res.timings["colormap"] = time.perf_counter() - t
        token.check("encode")
        t = time.perf_counter()
        res.png = colormap.encode_png(idx, colormap.palette(cmap["name"]))
        res.timings["encode"] = time.perf_counter() - t
    res.timings["total"] = time.perf_counter() - t0
    return res


def _pad_to_tile(a, fill):
    """Pad a (h, w) array with `fill` to TILE × TILE (partial tiles at the right / bottom edge)."""
    if a.shape == (TILE, TILE):
        return a
    out = np.full((TILE, TILE), fill, a.dtype)
    out[:a.shape[0], :a.shape[1]] = a
    return out


def _auto(pyr, spec, blockcache, token):
    lv = pyr.levels[spec.level]
    r0, c0 = spec.ty * TILE, spec.tx * TILE
    h, w = min(TILE, lv.height - r0), min(TILE, lv.width - c0)
    z, info = blockcache.read_window(pyr, spec.level, r0 - 1, c0 - 1, h + 2, w + 2, token)
    token.check("kernel")
    t = time.perf_counter()
    v = tile_k.compute(spec.op, z, lv.res, spec.method, pyr.nodata, spec.azimuth, spec.altitude, spec.zfactor)
    kernel_s = time.perf_counter() - t
    info["timings"] = {"read": info.pop("read_s"), "decode": info.pop("decode_s"), "kernel": kernel_s}
    return _pad_to_tile(v, _nodata_of(spec.op)), info


EXACT_STRIP_CELLS = 16_000_000  # fine cells per strip in exact mode: bounds memory (~0.2 GB) whatever the level
EXACT_STRIP_ROWS = 512          # ... and about one stored block row per strip: reads line up with the file's blocks
                                # and a cancelled job stops within one strip (tens of ms)


def _exact(pyr, spec, token):
    """Full-resolution route of E5: compute at level 0 over the tile's footprint, average over each level-k cell
    (mean of valid fine values; aspect: circular mean). Reads directly (not through the block cache, which a large
    footprint would flush), in strips of coarse rows so memory stays bounded."""
    from demlab.io import read_with_halo
    lv, l0 = pyr.levels[spec.level], pyr.levels[0]
    r0, c0 = spec.ty * TILE, spec.tx * TILE
    h, w = min(TILE, lv.height - r0), min(TILE, lv.width - c0)
    nod = _nodata_of(spec.op)
    if spec.level == 0:
        z = read_with_halo(pyr.handle(0), (r0, c0, h, w), pyr.nodata)
        t = time.perf_counter()
        v = tile_k.compute(spec.op, z, l0.res, spec.method, pyr.nodata, spec.azimuth, spec.altitude, spec.zfactor)
        return _pad_to_tile(v, nod), {"timings": {"read": 0.0, "decode": 0.0, "kernel": time.perf_counter() - t},
                                      "blocks": 0, "decoded": 0, "fine_cells": h * w}
    re = footprint_edges(l0.height, lv.height, r0, r0 + h)
    ce = footprint_edges(l0.width, lv.width, c0, c0 + w)
    fine_w = int(ce[-1] - ce[0])
    out = np.full((h, w), nod, np.float32 if spec.op != "hillshade" else np.uint8)
    read_s = kern_s = 0.0
    i = 0
    while i < h:
        j = i + 1
        while j < h and (re[j + 1] - re[i]) <= EXACT_STRIP_ROWS and (re[j + 1] - re[i]) * fine_w <= EXACT_STRIP_CELLS:
            j += 1
        token.check("read")
        t = time.perf_counter()
        z = read_with_halo(pyr.handle(0), (int(re[i]), int(ce[0]), int(re[j] - re[i]), fine_w), pyr.nodata)
        read_s += time.perf_counter() - t
        token.check("kernel")
        t = time.perf_counter()
        f = tile_k.compute(spec.op, z, l0.res, spec.method, pyr.nodata, spec.azimuth, spec.altitude, spec.zfactor)
        rows, cols = re[i:j + 1] - re[i], ce - ce[0]
        if spec.op == "aspect":
            ok = f != NODATA
            rad = np.radians(np.where(ok, f, 0.0))
            ss, n = block_sums(np.sin(rad), ok, rows, cols)
            cs, _ = block_sums(np.cos(rad), ok, rows, cols)
            m = np.degrees(np.arctan2(ss, cs)) % 360.0
        else:
            ok = f != nod
            s, n = block_sums(f, ok, rows, cols)
            m = s / np.maximum(n, 1)
            if spec.op == "hillshade":
                m = np.clip(np.floor(m + 0.5), 1, 255)
        out[i:j] = np.where(n > 0, m, nod).astype(out.dtype)
        kern_s += time.perf_counter() - t
        i = j
    info = {"timings": {"read": read_s, "decode": read_s, "kernel": kern_s}, "blocks": 0, "decoded": 0,
            "fine_cells": int((re[-1] - re[0]) * fine_w)}
    return _pad_to_tile(out, nod), info


def _precomputed(pyr, spec, blockcache, token):
    if pyr.precomputed is None or spec.op != "slope" or spec.method != "Horn":
        raise ValueError("precomputed mode needs a slope pyramid and op=slope, method=Horn")
    pre = pyr.precomputed
    lv = pre.levels[spec.level]
    r0, c0 = spec.ty * TILE, spec.tx * TILE
    h, w = min(TILE, lv.height - r0), min(TILE, lv.width - c0)
    v, info = blockcache.read_window(pre, spec.level, r0, c0, h, w, token)
    info["timings"] = {"read": info.pop("read_s"), "decode": info.pop("decode_s"), "kernel": 0.0}
    v = np.where(v == pre.nodata, NODATA, v).astype(np.float32)
    return _pad_to_tile(v, NODATA), info


def render_box(pyr, bbox, out_width, spec_kw, blockcache, token=NEVER, level=None):
    """A bounding box (UTM) at the level chosen for an image `out_width` pixels wide, assembled from lattice tiles
    (so it shares the caches with pan / zoom). Returns (values, transform, level) with values cropped to the box in
    level cells; transform is the GDAL geotransform tuple of the result."""
    xmin, ymin, xmax, ymax = bbox
    k = pyr.choose_level((xmax - xmin) / max(out_width, 1)) if level is None else level
    lv = pyr.levels[k]
    a, _, c, _, e, f = lv.transform
    c0 = max(int(math.floor((xmin - c) / a)), 0)
    c1 = min(int(math.ceil((xmax - c) / a)), lv.width)
    r0 = max(int(math.floor((ymax - f) / e)), 0)
    r1 = min(int(math.ceil((ymin - f) / e)), lv.height)
    if c0 >= c1 or r0 >= r1:
        return None, None, k
    nod = _nodata_of(spec_kw.get("op", "slope"))
    tx0, tx1, ty0, ty1 = c0 // TILE, (c1 - 1) // TILE, r0 // TILE, (r1 - 1) // TILE
    mosaic = None
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            res = render_tile(pyr, TileSpec(level=k, tx=tx, ty=ty, **spec_kw), blockcache, token, encode=False)
            if mosaic is None:
                mosaic = np.full(((ty1 - ty0 + 1) * TILE, (tx1 - tx0 + 1) * TILE), nod, res.values.dtype)
            mosaic[(ty - ty0) * TILE:(ty - ty0 + 1) * TILE, (tx - tx0) * TILE:(tx - tx0 + 1) * TILE] = res.values
    vals = mosaic[r0 - ty0 * TILE:r1 - ty0 * TILE, c0 - tx0 * TILE:c1 - tx0 * TILE]
    gt = (c + a * c0, a, 0.0, f + e * r0, 0.0, e)
    return vals, gt, k


@lru_cache(maxsize=None)
def _e5_table():
    """{(dataset, level): (slope rmse, slope bias)} for the COG pyramid, from E5 (results/e5_accuracy.csv)."""
    out = {}
    p = RESULTS / "e5_accuracy.csv"
    if p.exists():
        with open(p, newline="") as fh:
            for r in csv.DictReader(fh):
                if r["source"] == "on demand (COG overview)":
                    out[(r["dataset"], int(r["level"]))] = (float(r["rmse"]), float(r["bias"]))
    return out


def expected_error(dataset, level, mode="auto"):
    """Expected slope error (RMSE, bias in degrees) of a level in auto mode, from E5; exact/precomputed/level 0 = 0.
    None if E5 has no number for this dataset / level."""
    if mode != "auto" or level == 0:
        return 0.0, 0.0
    return _e5_table().get((dataset, level))
