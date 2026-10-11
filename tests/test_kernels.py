"""Correctness of our kernels against gdaldem and against each other.

Our kernels compute in float64. gdaldem adds the Horn neighbour values in float32, which moves Horn slope by up to
~0.015 deg and, in gentle or flat cells, aspect by up to a few degrees (error / gradient). So:
  - parity: with gdal_rounding=True (float32 sums, like GDAL's C code) every cell must match gdaldem;
  - accuracy: our default float64 slope must stay within 0.02 deg of gdaldem.
Nodata masks must match exactly.

    python -m pytest tests/test_kernels.py -q
"""
import numpy as np
import pytest

from demlab.kernels import numba_k, numpy_k
from tests.fixtures import OPS, gdaldem_ref, load

CROPS = ["8m_gaps", "chamoli_2m"]
TOL = {"slope": 0.02, "aspect": 0.1, "hillshade": 1, "TRI": 1e-3, "TPI": 2e-3, "roughness": 1e-3}


def _nodata_of(op):
    return 0 if op == "hillshade" else numpy_k.NODATA


def _padded(name):
    z, res, nodata = load(name)
    return np.pad(z, 1, constant_values=nodata), res, nodata


def _assert_close(op, ours, ref, ref_nd, extra_mask=None, tol=None):
    ref_bad, our_bad = ref == ref_nd, ours == _nodata_of(op)
    assert np.array_equal(ref_bad, our_bad), f"{op}: nodata mask differs in {np.sum(ref_bad != our_bad)} cells"
    m = ~ref_bad if extra_mask is None else ~ref_bad & extra_mask
    d = np.abs(ours[m].astype(np.float64) - ref[m].astype(np.float64))
    if op == "aspect":
        d = np.minimum(d, 360 - d)
    assert d.max() <= (tol if tol is not None else TOL[op]), f"{op}: max diff {d.max()}"


@pytest.mark.parametrize("name", CROPS)
@pytest.mark.parametrize("op,method", OPS)
def test_numpy_matches_gdaldem(name, op, method):
    """Same formulas as gdaldem: with gdaldem's float32 rounding reproduced, every cell agrees."""
    zp, res, nodata = _padded(name)
    ref, ref_nd = gdaldem_ref(name, op, method)
    ours = numpy_k.compute(op, zp, res, method, nodata, gdal_rounding=True)
    tol = {"slope": 1e-4, "aspect": 1e-3}.get(op)
    _assert_close(op, ours, ref, ref_nd, tol=tol)


@pytest.mark.parametrize("name", CROPS)
@pytest.mark.parametrize("method", ["Horn", "ZevenbergenThorne"])
def test_float64_slope_close_to_gdaldem(name, method):
    """Our default (float64) slope differs from gdaldem's only by its float32 rounding."""
    zp, res, nodata = _padded(name)
    ref, ref_nd = gdaldem_ref(name, "slope", method)
    _assert_close("slope", numpy_k.compute("slope", zp, res, method, nodata), ref, ref_nd)


@pytest.mark.parametrize("name", CROPS)
@pytest.mark.parametrize("op,method", OPS)
def test_numba_matches_numpy(name, op, method):
    zp, res, nodata = _padded(name)
    ref = numpy_k.compute(op, zp, res, method, nodata)
    ours = numba_k.compute_many([op], zp, res, method, nodata)[op]
    _assert_close(op, ours, ref, _nodata_of(op), tol=1e-4 if op != "hillshade" else 0)


def test_numba_fused_equals_separate():
    zp, res, nodata = _padded("chamoli_2m")
    fused = numba_k.compute_many(["slope", "aspect", "hillshade"], zp, res, "Horn", nodata)
    for op in ("slope", "aspect", "hillshade"):
        alone = numba_k.compute_many([op], zp, res, "Horn", nodata)[op]
        assert np.array_equal(fused[op], alone)


@pytest.mark.parametrize("op,method", [("slope", "Horn"), ("aspect", "ZevenbergenThorne"), ("hillshade", "Horn"),
                                       ("TRI", "Riley"), ("TPI", ""), ("roughness", "")])
def test_cupy_matches_numpy(op, method):
    cp = pytest.importorskip("cupy")
    zp, res, nodata = _padded("chamoli_2m")
    ref = numpy_k.compute(op, zp, res, method, nodata)
    ours = cp.asnumpy(numpy_k.compute(op, cp.asarray(zp), res, method, nodata, xp=cp))
    _assert_close(op, ours, ref, _nodata_of(op), tol=1e-4 if op != "hillshade" else 1)


def _cuda(op, zp, res, method, nodata, precision):
    cp = pytest.importorskip("cupy")
    from demlab.kernels import cuda_k
    zg = cp.asarray(zp, dtype=cp.float32)  # the grids are float32, so this is exact
    return cp.asnumpy(cuda_k.compute_many([op], zg, res, method or "Horn", nodata, precision)[op])


@pytest.mark.parametrize("name", CROPS)
@pytest.mark.parametrize("op,method", OPS)
def test_cuda_fp32_matches_gdaldem(name, op, method):
    """The float32 GPU kernel adds the Horn neighbours in float32 like gdaldem: as close as the parity version."""
    zp, res, nodata = _padded(name)
    ref, ref_nd = gdaldem_ref(name, op, method)
    tol = {"slope": 1e-4, "aspect": 1e-3}.get(op)
    _assert_close(op, _cuda(op, zp, res, method, nodata, "fp32"), ref, ref_nd, tol=tol)


@pytest.mark.parametrize("name", CROPS)
@pytest.mark.parametrize("op,method", OPS)
def test_cuda_fp64_matches_numba(name, op, method):
    """The float64 GPU kernel computes like the CPU engine."""
    zp, res, nodata = _padded(name)
    ref = numba_k.compute_many([op], zp, res, method, nodata)[op]
    _assert_close(op, _cuda(op, zp, res, method, nodata, "fp64"), ref, _nodata_of(op),
                  tol=1e-4 if op != "hillshade" else 0)
