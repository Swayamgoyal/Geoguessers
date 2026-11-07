"""Segmented LRU, single-flight, result-cache keys, cancellation tokens.

    python -m pytest tests/test_caches.py -q
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from demlab.cancel import Cancelled, CancelToken
from demlab.resultcache import ResultCache, tile_key
from demlab.slru import SLRU, SingleFlight

BASE = {"dataset": "chamoli_2m", "version": "v1", "level": 3, "tx": 4, "ty": 7, "tile": 512, "op": "hillshade",
        "method": "Horn", "mode": "auto", "zfactor": 1.0, "azimuth": 315.0, "altitude": 45.0, "cmap": "",
        "vmin": None, "vmax": None}


def test_slru_budget_and_eviction_order():
    c = SLRU(100, len)
    for i in range(10):
        c.put(i, b"x" * 10)
    assert c.stats()["bytes"] <= 100
    c.get(0)                      # 0 moves to protected
    for i in range(10, 20):       # a scan of new entries
        c.put(i, b"x" * 10)
    assert c.get(0) is not None   # the reused entry survived the scan
    assert c.get(1) is None       # an unused old entry did not


def test_slru_rejects_oversized():
    c = SLRU(10, len)
    c.put("big", b"x" * 11)
    assert c.get("big") is None


def test_single_flight_runs_once():
    sf = SingleFlight()
    calls = []

    def compute():
        calls.append(1)
        time.sleep(0.05)
        return 42

    with ThreadPoolExecutor(100) as ex:
        results = list(ex.map(lambda _: sf.do("k", compute), range(100)))
    assert results == [42] * 100 and len(calls) == 1


def test_result_cache_concurrent_identical_requests_render_once():
    rc = ResultCache(8)
    calls = []
    lock = threading.Lock()

    def render():
        with lock:
            calls.append(1)
        time.sleep(0.05)
        return b"png"

    key = tile_key(BASE)
    with ThreadPoolExecutor(100) as ex:
        out = list(ex.map(lambda _: rc.get_or_render(key, render)[0], range(100)))
    assert out == [b"png"] * 100 and len(calls) == 1
    assert rc.get_or_render(key, render) == (b"png", True)


def test_tile_key_stable_and_sensitive():
    k = tile_key(BASE)
    assert k == tile_key(dict(reversed(list(BASE.items()))))          # order does not matter
    assert len(k) == 32
    for field, new in [("dataset", "tile571_8m"), ("version", "v2"), ("level", 4), ("tx", 5), ("ty", 8),
                       ("op", "slope"), ("method", "ZevenbergenThorne"), ("mode", "exact"), ("zfactor", 2.0),
                       ("azimuth", 300.0), ("altitude", 30.0), ("cmap", "gray"), ("vmin", 5.0), ("vmax", 50.0)]:
        assert tile_key({**BASE, field: new}) != k, field
    assert tile_key({**BASE, "azimuth": 315.4}) == k                   # sun angles rounded to 1 degree
    assert tile_key({**BASE, "device": "cuda"}) == k                  # device does not change the result


def test_cancel_token():
    t = CancelToken()
    t.check("read")
    t.cancel()
    with pytest.raises(Cancelled):
        t.check("kernel")
    assert t.stage == "kernel"
