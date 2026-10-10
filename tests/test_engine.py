"""The tiled engine must give the same result as one big window, whatever the window size (halo correctness),
and match gdaldem on whole files.

    python -m pytest tests/test_engine.py -q
"""
import numpy as np
import pytest
import rasterio

from demlab.engine import run
from demlab.kernels import numpy_k
from tests.fixtures import crop, gdaldem_ref, load


def _read(p):
    with rasterio.open(p) as ds:
        return ds.read(1)


@pytest.mark.parametrize("backend", ["numpy", "numba", "cupy"])
@pytest.mark.parametrize("window", [300, 1024])  # 300: windows not aligned to the crop or to the 512 tiles
def test_tiled_equals_whole(tmp_path, backend, window):
    if backend == "cupy":
        pytest.importorskip("cupy")
    src = crop("8m_gaps")
    z, res, nodata = load("8m_gaps")
    whole = numpy_k.compute("slope", np.pad(z, 1, constant_values=nodata), res, "Horn", nodata)
    outs = {op: tmp_path / f"{op}.tif" for op in ("slope", "aspect", "hillshade")}
    run(src, outs, backend=backend, method="Horn", window=window)
    tiled = _read(outs["slope"])
    assert np.array_equal(tiled == numpy_k.NODATA, whole == numpy_k.NODATA)
    m = tiled != numpy_k.NODATA
    assert np.abs(tiled[m] - whole[m]).max() <= 1e-4


@pytest.mark.parametrize("op,method", [("slope", "ZevenbergenThorne"), ("TRI", "Riley"), ("roughness", "")])
def test_engine_matches_gdaldem(tmp_path, op, method):
    out = tmp_path / "o.tif"
    run(crop("chamoli_2m"), {op: out}, backend="numba", method=method or "Horn", window=400)
    ours = _read(out)
    ref, nd = gdaldem_ref("chamoli_2m", op, method)
    assert np.array_equal(ours == numpy_k.NODATA, ref == nd)
    m = ref != nd
    assert np.abs(ours[m].astype(np.float64) - ref[m]).max() <= 1e-3
