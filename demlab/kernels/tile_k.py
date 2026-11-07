"""Single-threaded, GIL-free terrain kernels for the tile server (Phase 5 viewer).

Same formulas, conventions and float64 arithmetic as `numba_k` (which the batch engine uses with parallel=True and
which stays unchanged, so E3/E4 remain reproducible). Here every kernel is serial and compiled with nogil=True: the
server runs many 512² tiles at once on worker threads ("tile-level parallelism") instead of one tile on many cores.
Input z has a 1-cell halo, shape (H+2, W+2), float32 or float64; outputs are (H, W).
"""
import math

import numba as nb
import numpy as np

NODATA = -9999.0
KINDS = {("TRI", "Riley"): 0, ("TRI", ""): 0, ("TRI", "Wilson"): 1, ("TPI", ""): 2, ("roughness", ""): 3}


@nb.njit(nogil=True, fastmath=False, cache=True)
def gradient_ops(z, res, nodata, horn, do_slope, do_aspect, do_hs, az, alt, zfactor, out_slope, out_aspect, out_hs):
    H, W = z.shape[0] - 2, z.shape[1] - 2
    inv8 = 1.0 / (8.0 * res)
    inv2 = 1.0 / (2.0 * res)
    sx, sy, sz = math.sin(az) * math.cos(alt), math.cos(az) * math.cos(alt), math.sin(alt)
    for r in range(H):
        for c in range(W):
            a, b, cc = np.float64(z[r, c]), np.float64(z[r, c + 1]), np.float64(z[r, c + 2])
            d, e, f = np.float64(z[r + 1, c]), np.float64(z[r + 1, c + 1]), np.float64(z[r + 1, c + 2])
            g, h, i = np.float64(z[r + 2, c]), np.float64(z[r + 2, c + 1]), np.float64(z[r + 2, c + 2])
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


@nb.njit(nogil=True, cache=True)
def neighbourhood_op(z, nodata, kind, out):
    """kind: 0 = TRI Riley, 1 = TRI Wilson, 2 = TPI, 3 = roughness."""
    H, W = z.shape[0] - 2, z.shape[1] - 2
    for r in range(H):
        for c in range(W):
            e = np.float64(z[r + 1, c + 1])
            bad = False
            s, sabs, ssq = 0.0, 0.0, 0.0
            hi, lo = -1e300, 1e300
            for dr in range(3):
                for dc in range(3):
                    v = np.float64(z[r + dr, c + dc])
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


def compute(op, z, res, method="Horn", nodata=NODATA, azimuth=315.0, altitude=45.0, zfactor=1.0):
    """One operator on one window (with halo). slope/aspect float32 (-9999 nodata), hillshade uint8 (0 nodata),
    TRI/TPI/roughness float32."""
    H, W = z.shape[0] - 2, z.shape[1] - 2
    if op in ("slope", "aspect", "hillshade"):
        s = np.empty((H, W) if op == "slope" else (1, 1), np.float32)
        a = np.empty((H, W) if op == "aspect" else (1, 1), np.float32)
        h = np.empty((H, W) if op == "hillshade" else (1, 1), np.uint8)
        gradient_ops(z, float(res), float(nodata), method != "ZevenbergenThorne", op == "slope", op == "aspect",
                     op == "hillshade", math.radians(azimuth), math.radians(altitude), float(zfactor), s, a, h)
        return {"slope": s, "aspect": a, "hillshade": h}[op]
    if op in ("TRI", "TPI", "roughness"):
        key = (op, method if op == "TRI" and method in ("Riley", "Wilson") else "")
        out = np.empty((H, W), np.float32)
        neighbourhood_op(z, float(nodata), KINDS[key], out)
        return out
    raise ValueError(f"unknown op {op!r}")
