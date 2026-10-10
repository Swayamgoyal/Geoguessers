"""Parallel CPU terrain operators (Numba). Same conventions and results as numpy_k (float64 per cell).

`gradient_ops` is fused: it computes the gradient of each cell once and writes any of slope, aspect and
hillshade, so several products cost one pass over the data. Rows are spread over threads with prange;
numba.set_num_threads() controls how many.
Input z has a 1-cell halo: shape (H+2, W+2); outputs are (H, W).
"""
import math

import numba as nb
import numpy as np

NODATA = -9999.0


@nb.njit(parallel=True, fastmath=False, cache=True)
def gradient_ops(z, res, nodata, horn, do_slope, do_aspect, do_hs, az, alt, zfactor,
                 out_slope, out_aspect, out_hs):
    H, W = z.shape[0] - 2, z.shape[1] - 2
    inv8 = 1.0 / (8.0 * res)
    inv2 = 1.0 / (2.0 * res)
    sx, sy, sz = math.sin(az) * math.cos(alt), math.cos(az) * math.cos(alt), math.sin(alt)
    for r in nb.prange(H):
        for c in range(W):
            a, b, cc = z[r, c], z[r, c + 1], z[r, c + 2]
            d, e, f = z[r + 1, c], z[r + 1, c + 1], z[r + 1, c + 2]
            g, h, i = z[r + 2, c], z[r + 2, c + 1], z[r + 2, c + 2]
            bad = (a == nodata or b == nodata or cc == nodata or d == nodata or e == nodata or
                   f == nodata or g == nodata or h == nodata or i == nodata or
                   a != a or b != b or cc != cc or d != d or e != e or f != f or g != g or h != h or i != i)
            if bad:
                if do_slope:
                    out_slope[r, c] = NODATA
                if do_aspect:
                    out_aspect[r, c] = NODATA
                if do_hs:
                    out_hs[r, c] = 0
                continue
            if horn:
                dzdx = ((cc + 2.0 * f + i) - (a + 2.0 * d + g)) * inv8
                dzdy = ((a + 2.0 * b + cc) - (g + 2.0 * h + i)) * inv8
            else:
                dzdx = (f - d) * inv2
                dzdy = (b - h) * inv2
            if do_slope:
                out_slope[r, c] = math.degrees(math.atan(math.sqrt(dzdx * dzdx + dzdy * dzdy)))
            if do_aspect:
                if dzdx == 0.0 and dzdy == 0.0:
                    out_aspect[r, c] = NODATA
                else:
                    asp = math.degrees(math.atan2(-dzdx, -dzdy))
                    out_aspect[r, c] = asp + 360.0 if asp < 0.0 else asp
            if do_hs:
                gx, gy = dzdx * zfactor, dzdy * zfactor
                cang = (-gx * sx - gy * sy + sz) / math.sqrt(1.0 + gx * gx + gy * gy)
                v = 1.0 if cang <= 0.0 else 1.0 + 254.0 * cang
                out_hs[r, c] = min(255, int(math.floor(v + 0.5)))


@nb.njit(parallel=True, cache=True)
def neighbourhood_op(z, nodata, kind, out):
    """kind: 0 = TRI Riley, 1 = TRI Wilson, 2 = TPI, 3 = roughness."""
    H, W = z.shape[0] - 2, z.shape[1] - 2
    for r in nb.prange(H):
        for c in range(W):
            e = z[r + 1, c + 1]
            bad = False
            s, sabs, ssq = 0.0, 0.0, 0.0
            hi, lo = -1e300, 1e300
            for dr in range(3):
                for dc in range(3):
                    v = z[r + dr, c + dc]
                    if v == nodata or v != v:
                        bad = True
                    hi = max(hi, v)
                    lo = min(lo, v)
                    if not (dr == 1 and dc == 1):
                        s += v
                        sabs += abs(v - e)
                        ssq += (v - e) * (v - e)
            if bad:
                out[r, c] = NODATA
            elif kind == 0:
                out[r, c] = math.sqrt(ssq)
            elif kind == 1:
                out[r, c] = sabs / 8.0
            elif kind == 2:
                out[r, c] = e - s / 8.0
            else:
                out[r, c] = hi - lo


KINDS = {("TRI", "Riley"): 0, ("TRI", ""): 0, ("TRI", "Wilson"): 1, ("TPI", ""): 2, ("roughness", ""): 3}


def compute_many(ops, z, res, method="Horn", nodata=NODATA, azimuth=315.0, altitude=45.0, zfactor=1.0):
    """Compute several operators on one window. ops: iterable of names; returns {name: array}.
    slope / aspect / hillshade share one fused pass (same `method`)."""
    H, W = z.shape[0] - 2, z.shape[1] - 2
    ops = list(ops)
    out = {}
    grad = [o for o in ops if o in ("slope", "aspect", "hillshade")]
    if grad:
        s = np.empty((H, W), np.float32) if "slope" in grad else np.empty((1, 1), np.float32)
        a = np.empty((H, W), np.float32) if "aspect" in grad else np.empty((1, 1), np.float32)
        h = np.empty((H, W), np.uint8) if "hillshade" in grad else np.empty((1, 1), np.uint8)
        gradient_ops(z, float(res), float(nodata), method != "ZevenbergenThorne", "slope" in grad,
                     "aspect" in grad, "hillshade" in grad, math.radians(azimuth), math.radians(altitude),
                     float(zfactor), s, a, h)
        out.update({k: v for k, v in (("slope", s), ("aspect", a), ("hillshade", h)) if k in grad})
    for o in ops:
        if o in ("TRI", "TPI", "roughness"):
            key = (o, method if o == "TRI" and method in ("Riley", "Wilson") else "")
            res_arr = np.empty((H, W), np.float32)
            neighbourhood_op(z, float(nodata), KINDS[key], res_arr)
            out[o] = res_arr
    return out
