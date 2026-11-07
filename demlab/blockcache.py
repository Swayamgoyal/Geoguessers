"""Shared cache of decoded COG blocks, and windows assembled from it.

Every pyramid level is stored as 512 × 512 compressed blocks. A 512² view tile with its 1-cell halo touches up to 9
blocks, and its neighbours need the same border blocks again (E3: the halo re-decoding). Readers therefore ask this
cache first: each block is decoded once (single-flight), kept as float32, and shared by every tile that touches it.
All-nodata blocks are stored as a 0-byte sentinel and never decoded twice.

    cache = BlockCache(budget_mb=1024)
    z, info = cache.read_window(pyr, level, row0, col0, height, width, token)   # cells outside the grid = nodata
"""
import threading
import time

import numpy as np
import rasterio
from rasterio.windows import Window

from demlab.cancel import NEVER
from demlab.slru import SLRU, SingleFlight

EMPTY = "nodata"  # sentinel value for an all-nodata block


def _size(v):
    return 0 if isinstance(v, str) else v.nbytes


class BlockCache:
    def __init__(self, budget_mb=1024):
        self.cache = SLRU(budget_mb * 2**20, _size)
        self.flight = SingleFlight()
        self._local = threading.local()
        self._lock = threading.Lock()
        self.decoded = 0          # blocks actually decoded from disk
        self.decode_s = 0.0       # time spent decoding them
        self.empty_blocks = 0

    def _handle(self, path, level):
        handles = getattr(self._local, "handles", None)
        if handles is None:
            handles = self._local.handles = {}
        key = (path, level)
        ds = handles.get(key)
        if ds is None:  # one dataset handle per thread and level (GDAL handles are not thread-safe)
            ds = handles[key] = (rasterio.open(path) if level == 0 else
                                 rasterio.open(path, overview_level=level - 1))
        return ds

    def block(self, pyr, level, bx, by):
        """Decoded block (bx, by) of a level: float32 array, or EMPTY if every cell is nodata."""
        key = (pyr.version, level, bx, by)
        v = self.cache.get(key)
        if v is not None:
            return v, False

        def decode():
            lv = pyr.levels[level]
            t = time.perf_counter()
            r0, c0 = by * lv.block, bx * lv.block
            h, w = min(lv.block, lv.height - r0), min(lv.block, lv.width - c0)
            a = self._handle(pyr.path, level).read(1, window=Window(c0, r0, w, h)).astype(np.float32, copy=False)
            out = EMPTY if not np.any((a != pyr.nodata) & ~np.isnan(a)) else a
            with self._lock:
                self.decoded += 1
                self.decode_s += time.perf_counter() - t
                self.empty_blocks += out is EMPTY
            self.cache.put(key, out)
            return out

        return self.flight.do(key, decode), True

    def read_window(self, pyr, level, row0, col0, height, width, token=NEVER):
        """Cells [row0, row0+height) × [col0, col0+width) of a level as float32; outside the grid = nodata.
        Returns (array, info) with blocks touched / decoded and the time spent."""
        lv = pyr.levels[level]
        t = time.perf_counter()
        out = np.full((height, width), pyr.nodata, np.float32)
        r_lo, r_hi = max(row0, 0), min(row0 + height, lv.height)
        c_lo, c_hi = max(col0, 0), min(col0 + width, lv.width)
        touched = decoded = 0
        decode_s = 0.0
        if r_lo < r_hi and c_lo < c_hi:
            B = lv.block
            for by in range(r_lo // B, (r_hi - 1) // B + 1):
                for bx in range(c_lo // B, (c_hi - 1) // B + 1):
                    tb = time.perf_counter()
                    blk, was_decoded = self.block(pyr, level, bx, by)
                    if was_decoded:
                        decode_s += time.perf_counter() - tb
                    token.check("read")
                    touched += 1
                    decoded += was_decoded
                    if blk is EMPTY:
                        continue
                    br0, bc0 = by * B, bx * B
                    rr0, rr1 = max(r_lo, br0), min(r_hi, br0 + blk.shape[0])
                    cc0, cc1 = max(c_lo, bc0), min(c_hi, bc0 + blk.shape[1])
                    out[rr0 - row0:rr1 - row0, cc0 - col0:cc1 - col0] = blk[rr0 - br0:rr1 - br0, cc0 - bc0:cc1 - bc0]
        return out, {"blocks": touched, "decoded": decoded, "read_s": time.perf_counter() - t,
                     "decode_s": decode_s}

    def stats(self):
        s = self.cache.stats()
        s.update(decoded=self.decoded, decode_s=self.decode_s, empty_blocks=self.empty_blocks,
                 joined=self.flight.joined)
        return s
