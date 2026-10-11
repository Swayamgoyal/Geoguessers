"""GPU terrain operators as CUDA kernels (CuPy RawModule). Same operators and conventions as numba_k.

One GPU thread per output cell. Input z is a float32 window with a 1-cell halo, shape (H+2, W+2), on the GPU;
outputs are (H, W).

precision:
  "fp32" (default): arithmetic in float. The Horn neighbour sums are then exactly gdaldem's (GDAL adds the float32
          window values in float too); slope / aspect differ from the float64 CPU engine only by float32 rounding.
  "fp64": arithmetic in double, like the CPU engine. Consumer GPUs (RTX 4060) run FP64 at 1/64 of the FP32 rate.
The kernels only touch their own window, and one window is milliseconds of work, far below the 2 s Windows
GPU watchdog (TDR).
"""
import math

import cupy as cp
import numpy as np

NODATA = -9999.0

_SRC = r"""
#define DEG ((real)57.29577951308232)
#define OUT_NODATA (-9999.0f)

__device__ __forceinline__ bool bad(float v, float nodata) { return v == nodata || isnan(v); }

extern "C" __global__ void gradient_ops(
        const float* __restrict__ z, const int H, const int W, const real res, const float nodata,
        const int horn, const int do_s, const int do_a, const int do_h,
        const real sx, const real sy, const real sz, const real zf,
        float* __restrict__ out_s, float* __restrict__ out_a, unsigned char* __restrict__ out_h)
{
    const int c = blockIdx.x * blockDim.x + threadIdx.x;
    const int r = blockIdx.y * blockDim.y + threadIdx.y;
    if (r >= H || c >= W) return;
    const long long ld = W + 2;
    const float* p = z + r * ld + c;
    const float a = p[0],      b = p[1],          cc = p[2];
    const float d = p[ld],     e = p[ld + 1],     f = p[ld + 2];
    const float g = p[2 * ld], h = p[2 * ld + 1], i = p[2 * ld + 2];
    const long long o = (long long)r * W + c;
    if (bad(a, nodata) || bad(b, nodata) || bad(cc, nodata) || bad(d, nodata) || bad(e, nodata) ||
        bad(f, nodata) || bad(g, nodata) || bad(h, nodata) || bad(i, nodata)) {
        if (do_s) out_s[o] = OUT_NODATA;
        if (do_a) out_a[o] = OUT_NODATA;
        if (do_h) out_h[o] = 0;
        return;
    }
    real dzdx, dzdy;
    if (horn) {
        dzdx = (((real)cc + (real)f + (real)f + (real)i) - ((real)a + (real)d + (real)d + (real)g)) / (8 * res);
        dzdy = (((real)a + (real)b + (real)b + (real)cc) - ((real)g + (real)h + (real)h + (real)i)) / (8 * res);
    } else {
        dzdx = ((real)f - (real)d) / (2 * res);
        dzdy = ((real)b - (real)h) / (2 * res);
    }
    if (do_s) out_s[o] = (float)(DEG * ATAN(SQRT(dzdx * dzdx + dzdy * dzdy)));
    if (do_a) {
        if (dzdx == 0 && dzdy == 0) {
            out_a[o] = OUT_NODATA;
        } else {
            real asp = DEG * ATAN2(-dzdx, -dzdy);
            out_a[o] = (float)(asp < 0 ? asp + 360 : asp);
        }
    }
    if (do_h) {
        const real gx = dzdx * zf, gy = dzdy * zf;
        const real cang = (-gx * sx - gy * sy + sz) / SQRT(1 + gx * gx + gy * gy);
        const real v = cang <= 0 ? (real)1 : 1 + 254 * cang;
        const int iv = (int)FLOOR(v + (real)0.5);
        out_h[o] = (unsigned char)(iv > 255 ? 255 : iv);
    }
}

// kind: 0 = TRI Riley, 1 = TRI Wilson, 2 = TPI, 3 = roughness
extern "C" __global__ void neighbourhood_op(
        const float* __restrict__ z, const int H, const int W, const float nodata, const int kind,
        float* __restrict__ out)
{
    const int c = blockIdx.x * blockDim.x + threadIdx.x;
    const int r = blockIdx.y * blockDim.y + threadIdx.y;
    if (r >= H || c >= W) return;
    const long long ld = W + 2;
    const float* p = z + r * ld + c;
    const real e = (real)p[ld + 1];
    bool isbad = false;
    // TPI from the sum of differences (v - e): exact in float, unlike e - (sum of 8 elevations) / 8
    real sd = 0, sabs = 0, ssq = 0, hi = -1e30, lo = 1e30;
    for (int dr = 0; dr < 3; ++dr) {
        for (int dc = 0; dc < 3; ++dc) {
            const float vf = p[dr * ld + dc];
            if (bad(vf, nodata)) isbad = true;
            const real v = (real)vf;
            hi = v > hi ? v : hi;
            lo = v < lo ? v : lo;
            if (!(dr == 1 && dc == 1)) {
                sd += v - e;
                sabs += FABS(v - e);
                ssq += (v - e) * (v - e);
            }
        }
    }
    const long long o = (long long)r * W + c;
    if (isbad)          out[o] = OUT_NODATA;
    else if (kind == 0) out[o] = (float)SQRT(ssq);
    else if (kind == 1) out[o] = (float)(sabs / 8);
    else if (kind == 2) out[o] = (float)(-sd / 8);
    else                out[o] = (float)(hi - lo);
}
"""

_MODULES = {}
KINDS = {("TRI", "Riley"): 0, ("TRI", ""): 0, ("TRI", "Wilson"): 1, ("TPI", ""): 2, ("roughness", ""): 3}
BLOCK = (32, 8)


def module(precision="fp32"):
    """Compiled kernels for one precision (NVRTC; CuPy caches the binary on disk after the first compile)."""
    if precision not in _MODULES:
        real, sfx = {"fp32": ("float", "f"), "fp64": ("double", "")}[precision]
        head = (f"typedef {real} real;\n#define SQRT sqrt{sfx}\n#define ATAN atan{sfx}\n#define ATAN2 atan2{sfx}\n"
                f"#define FLOOR floor{sfx}\n#define FABS fabs{sfx}\n")
        _MODULES[precision] = cp.RawModule(code=head + _SRC)
    return _MODULES[precision]


def compute_many(ops, zg, res, method="Horn", nodata=NODATA, precision="fp32", azimuth=315.0, altitude=45.0,
                 zfactor=1.0):
    """Launch the kernels for one window on the current CuPy stream. zg: float32 cupy array with a 1-cell halo.
    Returns {op: cupy array}; nothing is synchronised or copied back here."""
    if zg.dtype != cp.float32 or not zg.flags.c_contiguous:
        zg = cp.ascontiguousarray(zg, dtype=cp.float32)
    H, W = zg.shape[0] - 2, zg.shape[1] - 2
    real = np.float32 if precision == "fp32" else np.float64
    mod = module(precision)
    grid = ((W + BLOCK[0] - 1) // BLOCK[0], (H + BLOCK[1] - 1) // BLOCK[1])
    ops = list(ops)
    out = {}
    grad = [o for o in ops if o in ("slope", "aspect", "hillshade")]
    if grad:
        s = cp.empty((H, W) if "slope" in grad else (1,), cp.float32)
        a = cp.empty((H, W) if "aspect" in grad else (1,), cp.float32)
        h = cp.empty((H, W) if "hillshade" in grad else (1,), cp.uint8)
        az, alt = math.radians(azimuth), math.radians(altitude)
        sx, sy, sz = math.sin(az) * math.cos(alt), math.cos(az) * math.cos(alt), math.sin(alt)
        mod.get_function("gradient_ops")(
            grid, BLOCK,
            (zg, np.int32(H), np.int32(W), real(res), np.float32(nodata), np.int32(method != "ZevenbergenThorne"),
             np.int32("slope" in grad), np.int32("aspect" in grad), np.int32("hillshade" in grad),
             real(sx), real(sy), real(sz), real(zfactor), s, a, h))
        out.update({k: v for k, v in (("slope", s), ("aspect", a), ("hillshade", h)) if k in grad})
    for o in ops:
        if o in ("TRI", "TPI", "roughness"):
            key = (o, method if o == "TRI" and method in ("Riley", "Wilson") else "")
            r = cp.empty((H, W), cp.float32)
            mod.get_function("neighbourhood_op")(
                grid, BLOCK, (zg, np.int32(H), np.int32(W), np.float32(nodata), np.int32(KINDS[key]), r))
            out[o] = r
    return out
