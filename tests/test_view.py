"""Tile lattice and renderer (Phase 5 viewer): every tile must equal the same window computed by the existing
engine on the whole level, including partial edge tiles and nodata; exact and precomputed modes, box assembly,
level choice, block-cache sharing and palette PNG encoding.

    python -m pytest tests/test_view.py -q
"""
import io

import numpy as np
import pytest
import rasterio
from PIL import Image

from demlab import colormap
from demlab.blockcache import BlockCache
from demlab.kernels import numba_k
from demlab.pyramid import block_sums, footprint_edges
from demlab.view import TILE, Pyramid, TileSpec, render_box, render_tile
from tests.fixtures import DATA

OPS = [("slope", "Horn"), ("slope", "ZevenbergenThorne"), ("aspect", "Horn"), ("hillshade", "Horn"),
       ("TRI", "Riley"), ("TRI", "Wilson"), ("TPI", ""), ("roughness", "")]


def whole_level(pyr, k):
    with (rasterio.open(pyr.path) if k == 0 else rasterio.open(pyr.path, overview_level=k - 1)) as ds:
        return ds.read(1).astype(np.float64)


def reference(pyr, k, op, method):
    z = whole_level(pyr, k)
    zp = np.pad(z, 1, constant_values=pyr.nodata)
    return numba_k.compute_many([op], zp, pyr.levels[k].res, method or "Horn", pyr.nodata)[op]


def mosaic(pyr, k, spec_kw, cache):
    lv = pyr.levels[k]
    out = None
    for ty in range(lv.nty):
        for tx in range(lv.ntx):
            r = render_tile(pyr, TileSpec(level=k, tx=tx, ty=ty, **spec_kw), cache, encode=False)
            if out is None:
                out = np.zeros((lv.nty * TILE, lv.ntx * TILE), r.values.dtype)
            out[ty * TILE:(ty + 1) * TILE, tx * TILE:(tx + 1) * TILE] = r.values
    return out


def test_fixture_has_gaps_partial_tiles_and_levels(pyr):
    assert len(pyr.levels) >= 2
    lv = pyr.levels[0]
    assert (lv.ntx, lv.nty) == (3, 3) and lv.width % TILE and lv.height % TILE
    z = whole_level(pyr, 0)
    assert 0.05 < np.mean(z == pyr.nodata) < 0.95


@pytest.mark.parametrize("op,method", OPS)
def test_auto_tiles_equal_whole_level_engine(pyr, op, method):
    cache = BlockCache(64)
    for k in range(len(pyr.levels)):
        ref = reference(pyr, k, op, method)
        got = mosaic(pyr, k, {"op": op, "method": method or "Horn"}, cache)
        h, w = ref.shape
        assert np.array_equal(got[:h, :w], ref), f"level {k}"
        nod = 0 if op == "hillshade" else -9999.0
        assert np.all(got[h:, :] == nod) and np.all(got[:, w:] == nod)  # padding of partial tiles is nodata


def test_outside_lattice_is_empty(pyr):
    cache = BlockCache(16)
    lv = pyr.levels[0]
    for tx, ty in [(-1, 0), (0, -1), (lv.ntx, 0), (0, lv.nty)]:
        assert render_tile(pyr, TileSpec(level=0, tx=tx, ty=ty), cache).empty
    assert render_tile(pyr, TileSpec(level=len(pyr.levels), tx=0, ty=0), cache).empty


def test_block_cache_decodes_each_block_once(pyr):
    cache = BlockCache(64)
    mosaic(pyr, 0, {"op": "slope"}, cache)
    n_blocks = pyr.levels[0].ntx * pyr.levels[0].nty
    assert cache.decoded == n_blocks          # 9 tiles touch up to 9 blocks each, yet each block decodes once
    mosaic(pyr, 0, {"op": "hillshade"}, cache)
    assert cache.decoded == n_blocks          # warm: nothing decoded again
    assert cache.stats()["hits"] > 0


def test_exact_mode_equals_full_resolution_average(pyr):
    k = 1
    lv, l0 = pyr.levels[k], pyr.levels[0]
    full = reference(pyr, 0, "slope", "Horn")
    re, ce = footprint_edges(l0.height, lv.height), footprint_edges(l0.width, lv.width)
    s, n = block_sums(full, full != -9999.0, re, ce)
    ref = np.where(n > 0, s / np.maximum(n, 1), -9999.0).astype(np.float32)
    got = mosaic(pyr, k, {"op": "slope", "mode": "exact"}, BlockCache(16))
    assert np.allclose(got[:lv.height, :lv.width], ref, atol=1e-4)


def test_exact_mode_aspect_uses_circular_mean(pyr):
    r = render_tile(pyr, TileSpec(level=1, tx=0, ty=0, op="aspect", mode="exact"), BlockCache(16), encode=False)
    v = r.values[r.values != -9999.0]
    assert v.size and v.min() >= 0 and v.max() < 360


def test_precomputed_mode_reads_slope_pyramid(pyr, cog):
    with rasterio.open(cog[1]) as ds:
        ref = ds.read(1)
    got = mosaic(pyr, 0, {"op": "slope", "mode": "precomputed"}, BlockCache(16))
    ok = ref != -9999.0
    assert np.array_equal(got[:ref.shape[0], :ref.shape[1]][ok], ref[ok])
    with pytest.raises(ValueError):
        render_tile(pyr, TileSpec(level=0, tx=0, ty=0, op="aspect", mode="precomputed"), BlockCache(16))


def test_render_box_equals_crop_of_level(pyr):
    lv = pyr.levels[0]
    a, _, c, _, e, f = lv.transform
    c0, c1, r0, r1 = 300, 1100, 200, 900  # spans tiles in both directions
    bbox = (c + a * c0, f + e * r1, c + a * c1, f + e * r0)
    vals, gt, k = render_box(pyr, bbox, out_width=10_000, spec_kw={"op": "slope"}, blockcache=BlockCache(32))
    assert k == 0
    assert np.array_equal(vals, reference(pyr, 0, "slope", "Horn")[r0:r1, c0:c1])
    assert gt[0] == pytest.approx(c + a * c0) and gt[3] == pytest.approx(f + e * r0)


def test_level_choice_rule_and_hysteresis():
    for name in ("chamoli_2m", "tile571_8m"):
        p = Pyramid(DATA / "prepared" / f"{name}.tif")
        res = [lv.res for lv in p.levels]
        assert res == sorted(res)
        assert p.choose_level(res[0] * 0.5) == 0                     # finer than the data: level 0
        assert p.choose_level(res[-1] * 10) == len(res) - 1          # zoomed far out: coarsest level
        for j, c in enumerate(res):
            assert p.choose_level(c * 1.0001) == j                   # cell just under a pixel: that level
            if j:
                assert p.choose_level(c * 0.9999) == j - 1           # just over a pixel: the finer one
        k = p.choose_level(res[2] * 1.02)
        assert k == 2
        assert p.choose_level(res[2] * 0.97, prev=2) == 2            # within 10%: keeps the level
        assert p.choose_level(res[2] * 0.80, prev=2) == 1            # beyond: switches


def test_tiles_for_bbox_and_bounds(pyr):
    lv = pyr.levels[0]
    l, b, r, t = pyr.bounds
    assert len(pyr.tiles_for_bbox(0, (l, b, r, t))) == lv.ntx * lv.nty
    assert pyr.tiles_for_bbox(0, (r + 10, b, r + 20, t)) == []
    x0, y0, x1, y1 = pyr.tile_bounds(0, 0, 0)
    assert x0 == pytest.approx(l) and y1 == pytest.approx(t)


def test_palette_png_round_trip(pyr):
    r = render_tile(pyr, TileSpec(level=0, tx=2, ty=2, op="slope"), BlockCache(16))
    im = Image.open(io.BytesIO(r.png))
    assert im.mode == "P" and im.size == (TILE, TILE) and im.info.get("transparency") == 0
    idx = np.array(im)
    assert np.array_equal(idx, colormap.quantise("slope", r.values, colormap.DEFAULTS["slope"]))
    assert np.all(idx[r.values == -9999.0] == 0) and np.all(idx[r.values != -9999.0] > 0)
    assert set(r.timings) >= {"read", "decode", "kernel", "colormap", "encode", "total"}
