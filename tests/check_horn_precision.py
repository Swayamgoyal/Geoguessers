"""Is the Horn difference vs gdaldem just float32 rounding inside gdaldem? Recompute Horn slope/aspect with
the neighbour sums done in float32 (as in GDAL's C code, where the window is a float array) and compare."""
import sys

import numpy as np

sys.path.insert(0, ".")
from demlab.kernels import numpy_k  # noqa: E402
from tests.fixtures import gdaldem_ref, load  # noqa: E402

for name in ["8m_gaps", "chamoli_2m"]:
    z, res, nodata = load(name)
    zp = np.pad(z, 1, constant_values=nodata).astype(np.float32)
    a, b, c, d, e, f, g, h, i = numpy_k._window(zp)
    gx = ((c + d.dtype.type(0) + f + f + i) - (a + d + d + g)).astype(np.float64)  # float32 sums
    gy = ((a + b + b + c) - (g + h + h + i)).astype(np.float64)
    bad = numpy_k.invalid_mask(zp, nodata)
    s = np.degrees(np.arctan(np.hypot(gx, gy) / (8 * res)))
    asp = np.degrees(np.arctan2(-gx, -gy)) % 360
    for op, ours in (("slope", s), ("aspect", asp)):
        ref, nd = gdaldem_ref(name, op, "Horn")
        m = ~bad & (ref != nd) & ~((gx == 0) & (gy == 0))
        dd = np.abs(ours[m] - ref[m])
        if op == "aspect":
            dd = np.minimum(dd, 360 - dd)
        print(f"{name:11s} {op:6s} Horn with float32 sums: max |diff| {dd.max():.6f}  mean {dd.mean():.2e}")
