"""Moving windows through the GPU: host -> device copy, CUDA kernels, device -> host copy, each stage timed with
CUDA events.

Options (what E4 compares):
  pinned  : copy through page-locked (pinned) host buffers. From ordinary (pageable) memory the driver has to
            stage every copy through its own buffer, which is slower and cannot overlap with kernels.
  streams : 1 = one window at a time (copy in, compute, copy out, wait). 2 or more = windows go round-robin over
            that many CUDA streams, so one window's copies overlap another window's kernels.
Safety: the CuPy memory pool is capped (vram_limit_gb, default 4 of the 8 GB), so a run can never take the whole
card; a window that does not fit fails with an out-of-memory error. Each kernel is milliseconds of work, far
below the 2 s Windows GPU watchdog. Nothing here changes clocks, power limits or driver settings.
"""
import time

import cupy as cp
import cupyx
import numpy as np

from demlab.kernels import cuda_k


class CudaBackend:
    def __init__(self, ops, res, method, nodata, precision="fp32", pinned=True, streams=2, vram_limit_gb=4.0):
        t0 = time.perf_counter()
        cp.cuda.Device(0).use()
        self.pool = cp.get_default_memory_pool()
        self.pool.set_limit(size=int(vram_limit_gb * 2**30))
        cuda_k.module(precision).get_function("gradient_ops")  # compile, or load the cached binary
        cp.cuda.Device(0).synchronize()
        self.init_s = time.perf_counter() - t0
        self.ops, self.res, self.method, self.nodata, self.precision = list(ops), res, method, nodata, precision
        self.pinned = pinned
        self.streams = [cp.cuda.Stream(non_blocking=True) for _ in range(max(1, streams))]
        self.depth = len(self.streams)
        self.k = 0
        self.t = {"h2d": 0.0, "kernel": 0.0, "d2h": 0.0, "host_copy": 0.0}
        self.peak_vram = 0

    def submit(self, z):
        """Queue one window (numpy float32, with halo) on the next stream; returns a handle for collect()."""
        s = self.streams[self.k % self.depth]
        self.k += 1
        ev = [cp.cuda.Event() for _ in range(4)]
        th = time.perf_counter()
        if self.pinned:
            hz = cupyx.empty_pinned(z.shape, np.float32)
            hz[...] = z
        else:
            hz = np.ascontiguousarray(z, dtype=np.float32)
        self.t["host_copy"] += time.perf_counter() - th
        with s:
            ev[0].record(s)
            zg = cp.empty(z.shape, cp.float32)
            zg.set(hz, stream=s)
            ev[1].record(s)
            outs = cuda_k.compute_many(self.ops, zg, self.res, self.method, self.nodata, self.precision)
            ev[2].record(s)
            host = {}
            for op, a in outs.items():
                if self.pinned:
                    h = cupyx.empty_pinned(a.shape, a.dtype)
                    a.get(stream=s, out=h, blocking=False)
                else:
                    h = a.get(stream=s)
                host[op] = h
            ev[3].record(s)
        self.peak_vram = max(self.peak_vram, self.pool.total_bytes())
        return ev, host, (hz, zg, outs)  # keep buffers alive until the stream is done with them

    def collect(self, handle):
        """Wait for a submitted window; returns {op: numpy array} and adds its stage times."""
        ev, host, _ = handle
        ev[3].synchronize()
        self.t["h2d"] += cp.cuda.get_elapsed_time(ev[0], ev[1]) / 1000
        self.t["kernel"] += cp.cuda.get_elapsed_time(ev[1], ev[2]) / 1000
        self.t["d2h"] += cp.cuda.get_elapsed_time(ev[2], ev[3]) / 1000
        return host

    def timings(self):
        return {"gpu_init": self.init_s, **{f"gpu_{k}": v for k, v in self.t.items()},
                "peak_vram_mb": self.peak_vram / 2**20}
