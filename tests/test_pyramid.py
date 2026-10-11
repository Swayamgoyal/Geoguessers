"""Footprints and block sums used by E5 (demlab/pyramid.py).

    python -m pytest tests/test_pyramid.py -q
"""
import numpy as np
import pytest

from demlab.pyramid import block_area, block_sums, footprint_edges


@pytest.mark.parametrize("n_fine,n_coarse", [(16, 8), (16, 4), (17460, 2182), (12825, 6412), (15, 1), (45, 3)])
def test_footprints_cover_every_fine_cell_once(n_fine, n_coarse):
    e = footprint_edges(n_fine, n_coarse)
    assert e[0] == 0 and e[-1] == n_fine and np.all(np.diff(e) > 0)
    ratio = n_fine / n_coarse
    assert np.diff(e).min() >= np.floor(ratio) and np.diff(e).max() <= np.ceil(ratio)


def test_exact_blocks_when_divisible():
    assert footprint_edges(16, 4).tolist() == [0, 4, 8, 12, 16]


def test_partial_range_matches_full():
    full = footprint_edges(17460, 2182)
    assert np.array_equal(footprint_edges(17460, 2182, 100, 612), full[100:613])


def test_block_sums_match_brute_force():
    rng = np.random.default_rng(1)
    a = rng.random((37, 29))
    valid = rng.random((37, 29)) > 0.2
    re, ce = footprint_edges(37, 9), footprint_edges(29, 7)
    s, c = block_sums(a, valid, re, ce)
    for i in range(9):
        for j in range(7):
            blk = (slice(re[i], re[i + 1]), slice(ce[j], ce[j + 1]))
            assert s[i, j] == pytest.approx(a[blk][valid[blk]].sum())
            assert c[i, j] == valid[blk].sum()
    assert block_area(re, ce).sum() == 37 * 29


def test_chunking_does_not_change_the_result():
    rng = np.random.default_rng(3)
    a = rng.random((101, 53))
    valid = rng.random((101, 53)) > 0.1
    re, ce = footprint_edges(101, 12), footprint_edges(53, 6)
    s1, c1 = block_sums(a, valid, re, ce, chunk_rows=10_000)
    s2, c2 = block_sums(a, valid, re, ce, chunk_rows=9)
    assert np.allclose(s1, s2) and np.array_equal(c1, c2)


def test_block_sums_on_a_sub_window():
    rng = np.random.default_rng(2)
    a = rng.random((40, 40))
    valid = np.ones_like(a, bool)
    full_s, _ = block_sums(a, valid, footprint_edges(40, 10), footprint_edges(40, 10))
    re, ce = footprint_edges(40, 10, 3, 7), footprint_edges(40, 10, 2, 9)
    sub = a[re[0]:re[-1], ce[0]:ce[-1]]
    s, _ = block_sums(sub, np.ones_like(sub, bool), re - re[0], ce - ce[0])
    assert np.allclose(s, full_s[3:7, 2:9])
