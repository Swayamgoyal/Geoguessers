"""Cache of rendered tile PNGs, keyed by a canonical hash of everything that defines a tile.

The key covers the dataset and its version, level, tile column and row, tile size, operator, method, z-factor,
sun azimuth and altitude (rounded to 1 degree, so a slider does not create a new key per pixel of travel), mode and
colour map. The compute device is left out: CPU and GPU give the same values (Phase 3). Tiles that were prefetched
enter the probation segment and move up only when the user really views them (SLRU).

    key = tile_key(spec_dict)
    png = cache.get_or_render(key, render)     # concurrent identical requests render once
"""
import hashlib
import json

from demlab.slru import SLRU, SingleFlight


def canonical(spec):
    """Normalised, JSON-serialisable form of a tile spec (rounding where values are continuous)."""
    s = dict(spec)
    for k in ("azimuth", "altitude"):
        if k in s and s[k] is not None:
            s[k] = round(float(s[k]))
    if "zfactor" in s and s["zfactor"] is not None:
        s["zfactor"] = round(float(s["zfactor"]), 2)
    for k in ("vmin", "vmax"):
        if k in s and s[k] is not None:
            s[k] = round(float(s[k]), 3)
    s.pop("device", None)
    return s


def tile_key(spec):
    blob = json.dumps(canonical(spec), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.blake2b(blob.encode(), digest_size=16).hexdigest()


class ResultCache:
    def __init__(self, budget_mb=512):
        self.cache = SLRU(budget_mb * 2**20, len)
        self.flight = SingleFlight()

    def get(self, key):
        return self.cache.get(key)

    def put(self, key, png):
        self.cache.put(key, png)

    def get_or_render(self, key, render):
        """(png, hit). `render()` returns PNG bytes; runs once per key at a time."""
        png = self.cache.get(key)
        if png is not None:
            return png, True

        def work():
            p = render()
            if p is not None:
                self.cache.put(key, p)
            return p

        return self.flight.do(key, work), False

    def stats(self):
        s = self.cache.stats()
        s["joined"] = self.flight.joined
        return s
