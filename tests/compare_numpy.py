"""Quick diagnostic: NumPy reference kernels vs gdaldem on the test crops (prints max differences)."""
import sys

import numpy as np

sys.path.insert(0, ".")
from demlab.kernels import numpy_k  # noqa: E402
from tests.fixtures import OPS, gdaldem_ref, load  # noqa: E402

for name in ["8m_gaps", "chamoli_2m"]:
    z, res, nodata = load(name)
    zp = np.pad(z, 1, constant_values=nodata)  # halo outside the crop = nodata, like gdaldem's edges
    print(f"== {name}: res {res} m, nodata {nodata}, {np.mean(z == nodata) * 100:.1f}% nodata")
    for op, method in OPS:
        ref, ref_nd = gdaldem_ref(name, op, method)
        ours = numpy_k.compute(op, zp, res, method, nodata)
        ref_bad, our_bad = ref == ref_nd, ours == (0 if op == "hillshade" else numpy_k.NODATA)
        both = ~ref_bad & ~our_bad
        d = np.abs(ours[both].astype(np.float64) - ref[both].astype(np.float64))
        if op == "aspect":
            d = np.minimum(d, 360 - d)
        print(f"  {op:9s} {method:17s} nodata mismatch {np.sum(ref_bad != our_bad):6d}  "
              f"max |diff| {d.max():.6f}  mean {d.mean():.2e}")
