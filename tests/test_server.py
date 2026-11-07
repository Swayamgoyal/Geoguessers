"""Tile server API (FastAPI test client) on the fixture pyramid: info, tiles (cache tiers, headers, empty tiles),
overview, prefetch, generations, box view as PNG and GeoTIFF, stats.

    python -m pytest tests/test_server.py -q
"""
import io
import json

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from PIL import Image

from demlab.service import TileService
from server.app import create_app


@pytest.fixture(scope="module")
def client(cog):
    svc = TileService({"fixture": (cog[0], cog[1])}, block_mb=64, result_mb=32, fg_workers=4, bg_workers=1,
                      bg_min_free_gb=0)
    with TestClient(create_app(service=svc)) as c:
        yield c


def test_info(client):
    d = client.get("/info").json()
    lv = d["datasets"]["fixture"]["levels"]
    assert len(lv) >= 2 and lv[0]["ntx"] == 3 and d["tile"] == 512
    assert "slope" in d["legends"] and d["datasets"]["fixture"]["precomputed"]


def test_tile_cold_warm_then_result_cache(client):
    url = "/tiles/fixture/0/1/1.png?op=slope"
    r1 = client.get(url, headers={"X-Session": "t", "X-Gen": "1"})
    assert r1.status_code == 200 and r1.headers["content-type"] == "image/png"
    assert r1.headers["x-cache-tier"] in ("cold", "warm")
    st = r1.headers["server-timing"]
    for stage in ("queue", "read", "decode", "kernel", "colormap", "encode"):
        assert f"{stage};dur=" in st
    im = Image.open(io.BytesIO(r1.content))
    assert im.size == (512, 512) and im.mode == "P"
    r2 = client.get(url)
    assert r2.headers["x-cache-tier"] == "result" and r2.content == r1.content
    assert r2.headers["etag"] == r1.headers["etag"]
    r3 = client.get("/tiles/fixture/0/1/1.png?op=hillshade")
    assert r3.headers["x-cache-tier"] == "warm"                      # same blocks, other product: no decode


def test_outside_and_bad_requests(client):
    assert client.get("/tiles/fixture/0/9/9.png").status_code == 204
    assert client.get("/tiles/fixture/99/0/0.png").status_code == 204
    assert client.get("/tiles/nope/0/0/0.png").status_code == 404
    assert client.get("/tiles/fixture/0/0/0.png?op=volume").status_code == 400
    assert client.get("/tiles/fixture/0/0/0.png?op=aspect&mode=precomputed").status_code == 400


def test_expected_error_header(client):
    r = client.get("/tiles/fixture/0/0/0.png?op=slope")
    assert r.headers["x-expected-error"] == "0.00"                      # level 0: full resolution, no error
    r = client.get("/tiles/fixture/1/0/0.png?op=slope")
    assert "x-expected-error" not in r.headers                           # no E5 number for the fixture dataset
    r = client.get("/tiles/fixture/1/0/0.png?op=slope&mode=exact")
    assert r.status_code == 200 and r.headers["x-cache-tier"] == "cold" and r.headers["x-expected-error"] == "0.00"


def test_overview(client):
    r = client.get("/overview/fixture.png?op=hillshade")
    assert r.status_code == 200
    b = json.loads(r.headers["x-bounds"])
    assert len(b) == 4 and b[0] < b[2] and b[1] < b[3]


def test_prefetch_then_foreground_hits_cache(client):
    r = client.post("/prefetch", json={"dataset": "fixture", "session": "p", "gen": 1, "level": 0,
                                       "tiles": [[0, 2], [1, 2], [2, 2]], "op": "TPI"})
    assert r.status_code == 202 and r.json()["queued"] == 3
    import time
    time.sleep(1.5)
    tiers = [client.get(f"/tiles/fixture/0/{tx}/2.png?op=TPI").headers["x-cache-tier"] for tx in range(3)]
    assert tiers == ["result"] * 3
    assert client.post("/prefetch", json={"dataset": "fixture", "session": "p", "gen": 1, "level": 0,
                                          "tiles": [[0, 2]], "op": "TPI"}).json()["queued"] == 0


def test_generation_endpoint(client):
    r = client.post("/session/z/gen", json={"gen": 5, "cancel_bg": True})
    assert r.status_code == 200 and "cancelled" in r.json()


def test_view_png_and_geotiff(client):
    info = client.get("/info").json()["datasets"]["fixture"]
    l, b, r_, t = info["bounds"]
    bbox = [l + 0.2 * (r_ - l), b + 0.2 * (t - b), l + 0.7 * (r_ - l), b + 0.8 * (t - b)]
    p = client.post("/view", json={"dataset": "fixture", "bbox": bbox, "width": 4000, "op": "slope"})
    assert p.status_code == 200 and p.headers["content-type"] == "image/png"
    w, h = json.loads(p.headers["x-size"])
    assert Image.open(io.BytesIO(p.content)).size == (w, h)
    g = client.post("/view", json={"dataset": "fixture", "bbox": bbox, "width": 4000, "op": "slope",
                                   "format": "tif"})
    with rasterio.open(io.BytesIO(g.content)) as ds:
        assert (ds.width, ds.height) == (w, h) and ds.crs is not None
        v = ds.read(1)
        assert ds.nodata == -9999.0 and np.any(v != -9999.0)
        gt = json.loads(g.headers["x-geotransform"])
        assert ds.transform.c == pytest.approx(gt[0]) and ds.transform.f == pytest.approx(gt[3])


def test_stats(client):
    s = client.get("/stats").json()
    assert {"blocks", "results", "scheduler", "rss_mb"} <= set(s)
    assert s["blocks"]["decoded"] >= 1 and s["scheduler"]["counters"]["completed"] >= 1
