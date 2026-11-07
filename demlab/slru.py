"""Thread-safe, byte-budgeted segmented LRU (SLRU) cache, and single-flight de-duplication.

SLRU: new entries go to a *probation* segment (default 20% of the budget); an entry hit again moves to the
*protected* segment (80%). Eviction takes the least recently used probation entry first; when protected overflows,
its oldest entry is demoted back to probation. A one-off scan (e.g. a prefetch ring the user never visits) therefore
cannot flush the entries that are really reused.

    cache = SLRU(budget_bytes=512 * 2**20, size_of=len)
    cache.put(key, value); value = cache.get(key)    # None on a miss
    flight = SingleFlight(); value = flight.do(key, compute)   # concurrent callers share one compute
"""
import threading
from collections import OrderedDict
from concurrent.futures import Future


class SLRU:
    def __init__(self, budget_bytes, size_of, protected_share=0.8):
        self.budget = int(budget_bytes)
        self.protected_budget = int(self.budget * protected_share)
        self.size_of = size_of
        self._prob, self._prot = OrderedDict(), OrderedDict()
        self._prob_bytes = self._prot_bytes = 0
        self._lock = threading.Lock()
        self.hits = self.misses = self.evictions = self.inserts = 0

    def get(self, key):
        with self._lock:
            if key in self._prot:
                self._prot.move_to_end(key)
                self.hits += 1
                return self._prot[key][0]
            if key in self._prob:
                value, size = self._prob.pop(key)
                self._prob_bytes -= size
                self._prot[key] = (value, size)
                self._prot_bytes += size
                self._rebalance()
                self.hits += 1
                return value
            self.misses += 1
            return None

    def __contains__(self, key):
        with self._lock:
            return key in self._prot or key in self._prob

    def put(self, key, value):
        size = int(self.size_of(value))
        if size > self.budget:
            return  # larger than the whole cache: not cached
        with self._lock:
            if key in self._prot or key in self._prob:
                return
            self._prob[key] = (value, size)
            self._prob_bytes += size
            self.inserts += 1
            self._rebalance()

    def _rebalance(self):
        while self._prot_bytes > self.protected_budget and self._prot:
            k, (v, s) = self._prot.popitem(last=False)
            self._prot_bytes -= s
            self._prob[k] = (v, s)
            self._prob_bytes += s
        while self._prob_bytes + self._prot_bytes > self.budget and (self._prob or self._prot):
            seg = self._prob if self._prob else self._prot
            k, (v, s) = seg.popitem(last=False)
            if seg is self._prob:
                self._prob_bytes -= s
            else:
                self._prot_bytes -= s
            self.evictions += 1

    def clear(self):
        with self._lock:
            self._prob.clear()
            self._prot.clear()
            self._prob_bytes = self._prot_bytes = 0

    def stats(self):
        with self._lock:
            n = self.hits + self.misses
            return {"entries": len(self._prob) + len(self._prot), "bytes": self._prob_bytes + self._prot_bytes,
                    "budget": self.budget, "protected_entries": len(self._prot), "hits": self.hits,
                    "misses": self.misses, "hit_rate": self.hits / n if n else 0.0, "inserts": self.inserts,
                    "evictions": self.evictions}


class SingleFlight:
    """Run `compute()` once per key at a time; concurrent callers with the same key wait for the same result."""

    def __init__(self):
        self._lock = threading.Lock()
        self._inflight = {}
        self.joined = 0

    def do(self, key, compute):
        with self._lock:
            fut = self._inflight.get(key)
            owner = fut is None
            if owner:
                fut = self._inflight[key] = Future()
            else:
                self.joined += 1
        if not owner:
            return fut.result()
        try:
            value = compute()
        except BaseException as e:
            fut.set_exception(e)
            raise
        else:
            fut.set_result(value)
            return value
        finally:
            with self._lock:
                self._inflight.pop(key, None)
