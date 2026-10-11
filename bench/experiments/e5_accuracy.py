"""E5 accuracy: how wrong are slope and aspect computed on demand from a coarse pyramid level?

For every overview level k of a real DEM (Chamoli 2 m: levels 1-6 = 4-128 m; tile-571 8 m: levels 1-5 =
16-256 m):
  on demand      slope / aspect computed from the DEM overview (what the viewer reads), at that level's cell size
  truth          slope / aspect computed at full resolution, then averaged over the fine cells each coarse cell
                 covers (slope: mean; aspect: circular mean of the fine directions)
  error          on demand - truth
Also the share of cells at or above 30 and 45 deg (thresholds of slope-hazard maps) in truth vs on demand.
Only "fully valid" coarse cells are scored: the coarse cell and its 8 neighbours cover no nodata at full
resolution, so gaps in the data never enter the comparison. Errors are summarised overall and by truth-slope
class. Aspect is scored where the truth slope is >= 5 deg and the fine directions agree (mean resultant length
>= 0.5); elsewhere a block has no single meaningful direction.
Also per level:
  exact pyramid  the same with an exact power-of-two pyramid (blocks of 2^k x 2^k cells) instead of GDAL's
                 overviews, whose cells are slightly larger than 2^k fine cells when the grid size is not divisible
  precomputed    a slope pyramid made in advance (bench/experiments/e5_timing.py --precompute); should be ~exact
  DEM check      the overview DEM against the mean of the fine DEM over each footprint (how GDAL averaged)
Secondary (Chamoli footprint): independent DEMs at 8 / 30 / 90 m (HMA 8 m, Copernicus 30 / 90 m) against the same
truth, next to the Chamoli DEM simply averaged to that resolution: is pyramid error smaller or larger than the
difference between data sources?
Writes results/e5_accuracy.csv, e5_by_class.csv, e5_aspect.csv, e5_dem_check.csv, e5_sensors.csv and the map
figure results/plots/e5_maps.png.

    python -m bench.experiments.e5_accuracy
"""
import csv
import math
import time
from pathlib import Path

import numba
import numpy as np
import psutil
import rasterio
from scipy.ndimage import binary_erosion

from bench.harness import performance_cpus
from bench.sweep import DATA, OUT_DIR
from demlab.io import read_with_halo
from demlab.kernels import numba_k
from demlab.pyramid import block_area, block_sums, footprint_edges, level_dataset, level_res

NODATA = -9999.0
GRIDS = {"chamoli_2m": DATA / "prepared" / "chamoli_2m.tif", "tile571_8m": DATA / "prepared" / "tile571_8m.tif"}
SENSORS = {"tile571_8m": "HMA 8 m", "tile571_30m": "Copernicus 30 m", "tile571_90m": "Copernicus 90 m"}
CLASSES = [(0, 10), (10, 20), (20, 30), (30, 40), (40, 50), (50, 90)]
THRESHOLDS = (30, 45)
RES = Path(__file__).resolve().parents[2] / "results"
MAP_LEVEL = ("chamoli_2m", 4)  # the level shown in the map figure (32 m)


def precomputed_path(name):
    return OUT_DIR / f"e5_slope_{name}.tif"


def slope_aspect(z, res, nodata, ops=("slope", "aspect")):
    """Numba engine kernel on a whole array; z without halo (a nodata ring is added)."""
    zp = np.pad(z.astype(np.float64), 1, constant_values=nodata)
    return numba_k.compute_many(list(ops), zp, res, "Horn", nodata)


def stats(err, truth=None, coarse=None):
    e = err.astype(np.float64)
    a = np.abs(e)
    d = {"n": int(e.size), "bias": e.mean(), "mae": a.mean(), "rmse": math.sqrt(np.mean(e * e)),
         "p95_abs": float(np.percentile(a, 95)), "pct_gt5": 100 * np.mean(a > 5), "pct_gt10": 100 * np.mean(a > 10)}
    if truth is not None:
        d.update(mean_truth=float(truth.mean()), mean_coarse=float(coarse.mean()),
                 coarse_over_truth=float(coarse.mean() / truth.mean()))
        for th in THRESHOLDS:  # slope thresholds as used in hazard / suitability maps
            tt, cc = truth >= th, coarse >= th
            d[f"pct_truth_ge{th}"] = 100 * tt.mean()
            d[f"pct_coarse_ge{th}"] = 100 * cc.mean()
            d[f"agree_ge{th}"] = 100 * np.mean(tt == cc)
    return d


def circ_diff(a, b):
    d = np.abs(a - b) % 360
    return np.minimum(d, 360 - d)


def score_level(rows, cls_rows, label, name, level, res_m, coarse_slope, truth, full, extra_mask=None):
    """Score one coarse slope grid against the truth on fully valid cells (cell + 8 neighbours)."""
    ok = binary_erosion(full, np.ones((3, 3), bool), border_value=0) & (coarse_slope != NODATA)
    if extra_mask is not None:
        ok &= extra_mask
    c, t = coarse_slope[ok].astype(np.float64), truth[ok]
    rows.append({"dataset": name, "level": level, "res_m": res_m, "source": label, "coverage": ok.mean(),
                 **stats(c - t, t, c)})
    for lo, hi in CLASSES:
        m = (t >= lo) & (t < hi)
        if m.sum() >= 50:
            cls_rows.append({"dataset": name, "level": level, "res_m": res_m, "source": label,
                             "slope_class": f"{lo}-{hi}", "share": m.mean(), **stats(c[m] - t[m])})
    return ok


def analyse_grid(name, path, out):
    t0 = time.perf_counter()
    with rasterio.open(path) as src:
        z = src.read(1)
        res0, nodata = src.res[0], src.nodata
        overviews = src.overviews(1)
    H, W = z.shape
    dem_valid = z != nodata
    fine = slope_aspect(z, res0, nodata)
    s, asp = fine["slope"], fine["aspect"]
    del fine
    s_valid = s != NODATA
    a_valid = asp != NODATA
    rad = np.radians(np.where(a_valid, asp, 0)).astype(np.float32)
    sin_a, cos_a = np.sin(rad), np.cos(rad)
    del rad
    print(f"{name}: {H} x {W}, {dem_valid.mean():.1%} valid, fine slope/aspect in {time.perf_counter() - t0:.0f} s",
          flush=True)
    pre = precomputed_path(name)
    for k in range(1, len(overviews) + 1):
        with level_dataset(path, k) as ds:
            zk = ds.read(1)
            rk = level_res(ds)
        Hk, Wk = zk.shape
        re, ce = footprint_edges(H, Hk), footprint_edges(W, Wk)
        area = block_area(re, ce)
        # DEM check: GDAL's overview vs the mean fine elevation over each footprint
        zs, zc = block_sums(z, dem_valid, re, ce)
        zfull = (zc == area) & (zk != nodata)
        dz = zk[zfull] - zs[zfull] / area[zfull]
        out["dem"].append({"dataset": name, "level": k, "res_m": rk, "cells": int(zfull.sum()),
                           "rmse_m": math.sqrt(np.mean(dz.astype(np.float64) ** 2)), "max_abs_m": float(np.abs(dz).max()),
                           "rows_per_cell": H / Hk, "cols_per_cell": W / Wk})
        # truth
        ss, sc = block_sums(s, s_valid, re, ce)
        full = sc == area
        truth = np.where(full, ss / np.maximum(area, 1), np.nan)
        coarse = slope_aspect(zk, rk, nodata)
        ok = score_level(out["acc"], out["cls"], "on demand (COG overview)", name, k, rk, coarse["slope"], truth, full)
        # aspect: circular mean of fine directions, scored where it is well defined
        sn, an = block_sums(sin_a, a_valid, re, ce)
        cs, _ = block_sums(cos_a, a_valid, re, ce)
        R = np.hypot(sn, cs) / np.maximum(an, 1)
        ta = np.degrees(np.arctan2(sn, cs)) % 360
        ca = coarse["aspect"]
        am = ok & (truth >= 5) & (R >= 0.5) & (ca != NODATA)
        d = circ_diff(ca[am].astype(np.float64), ta[am])
        out["asp"].append({"dataset": name, "level": k, "res_m": rk, "n": int(d.size), "share_scored": am.sum() / ok.sum(),
                           "mae": d.mean(), "median": float(np.median(d)), "p95": float(np.percentile(d, 95)),
                           "pct_gt22_5": 100 * np.mean(d > 22.5), "pct_gt45": 100 * np.mean(d > 45)})
        if (name, k) == MAP_LEVEL:
            out["map"] = (name, k, rk, truth, coarse["slope"], ok)
        # exact power-of-two pyramid on the largest divisible part of the grid
        f = 2 ** k
        er, ec = np.arange(0, H // f + 1) * f, np.arange(0, W // f + 1) * f
        ea = block_area(er, ec)
        xs, xc = block_sums(z, dem_valid, er, ec)
        zx = np.where(xc == ea, xs / ea, nodata).astype(np.float32)
        xs, xc = block_sums(s, s_valid, er, ec)
        score_level(out["acc"], out["cls"], "on demand (exact 2^k pyramid)", name, k, res0 * f,
                    slope_aspect(zx, res0 * f, nodata, ("slope",))["slope"], np.where(xc == ea, xs / ea, np.nan),
                    xc == ea)
        # slope pyramid made in advance
        if pre.exists():
            with level_dataset(pre, k) as ds:
                score_level(out["acc"], out["cls"], "precomputed slope pyramid", name, k, rk, ds.read(1), truth, full)
        last = [r for r in out["acc"] if r["dataset"] == name and r["level"] == k]
        print("  " + " | ".join(f"L{k} {r['res_m']:.0f} m {r['source'][:22]:22s} rmse {r['rmse']:.2f} bias "
                                f"{r['bias']:+.2f} >5deg {r['pct_gt5']:.1f}%" for r in last), flush=True)
    return z, s, s_valid, res0, nodata


def sensors(z, s, s_valid, res0, nodata, out):
    """Chamoli footprint: independent coarser DEMs vs the averaged 2 m truth."""
    with rasterio.open(GRIDS["chamoli_2m"]) as ch:
        left, top = ch.bounds.left, ch.bounds.top
    H, W = z.shape
    dem_valid = z != nodata
    for key, label in SENSORS.items():
        with rasterio.open(DATA / "prepared" / f"{key}.tif") as src:
            R = src.res[0]
            f = int(round(R / res0))
            j0, i0 = (left - src.bounds.left) / R, (src.bounds.top - top) / R
            assert abs(j0 - round(j0)) < 1e-6 and abs(i0 - round(i0)) < 1e-6 and abs(f * res0 - R) < 1e-6
            hn, wn = H // f, W // f
            tnd = src.nodata
            zt = read_with_halo(src, (int(round(i0)), int(round(j0)), hn, wn), tnd)
        st = numba_k.compute_many(["slope"], zt, R, "Horn", tnd)["slope"]
        er, ec = np.arange(hn + 1) * f, np.arange(wn + 1) * f
        ea = block_area(er, ec)
        ss, sc = block_sums(s, s_valid, er, ec)
        full = sc == ea
        truth = np.where(full, ss / ea, np.nan)
        zs, zc = block_sums(z, dem_valid, er, ec)
        zavg = np.where(zc == ea, zs / ea, nodata).astype(np.float32)
        savg = slope_aspect(zavg, R, nodata, ("slope",))["slope"]
        ok = binary_erosion(full, np.ones((3, 3), bool), border_value=0) & (st != NODATA) & (savg != NODATA)
        dz = zt[1:-1, 1:-1][ok] - zavg[ok]
        for comp, a, b in ((f"{label} vs truth", st, truth), ("Chamoli 2 m averaged vs truth", savg, truth),
                           (f"{label} vs Chamoli 2 m averaged", st, savg)):
            out["sens"].append({"resolution_m": R, "comparison": comp, **stats(a[ok].astype(np.float64) - b[ok])})
        out["sens"][-1].update(dem_median_diff_m=float(np.median(dz)),
                               dem_nmad_m=float(1.4826 * np.median(np.abs(dz - np.median(dz)))))
        print(f"  {label}: " + " | ".join(f"{r['comparison']}: rmse {r['rmse']:.2f} bias {r['bias']:+.2f}"
                                          for r in out["sens"][-3:]), flush=True)


def map_figure(name, k, rk, truth, coarse, ok):
    import matplotlib.colors as mcolors

    from bench.analysis.phase2_report import GRID, INK2, PLOTS, S, SURF, plt
    seq = mcolors.LinearSegmentedColormap.from_list("seq", ["#eef3fb", S[0], "#0e2f57"])
    div = mcolors.LinearSegmentedColormap.from_list("div", [S[0], GRID, S[1]])
    for cm in (seq, div):
        cm.set_bad(SURF)
    t = np.where(ok, truth, np.nan)
    c = np.where(ok, coarse.astype(np.float64), np.nan)
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 5.2))
    panels = [(t, seq, 0, 60, "Truth: 2 m slope averaged to 32 m cells"),
              (c, seq, 0, 60, "On demand: slope of the 32 m pyramid level"),
              (c - t, div, -15, 15, "Error (on demand - truth)")]
    labels = ["slope (degrees)", "slope (degrees)", "on demand lower  ←  degrees  →  higher"]
    for ax, (img, cm, lo, hi, title), lab in zip(axes, panels, labels):
        im = ax.imshow(img, cmap=cm, vmin=lo, vmax=hi, interpolation="nearest")
        ax.set_title(title, fontsize=10)
        ax.set_xticks([]), ax.set_yticks([]), ax.grid(False)
        for sp in ax.spines.values():
            sp.set_visible(False)
        cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02)
        cb.set_label(lab, color=INK2)
        cb.outline.set_visible(False)
    fig.suptitle(f"E5: Chamoli, slope from pyramid level {k} ({rk:.0f} m) vs the 2 m truth "
                 f"(blank = nodata within one cell)", x=0.01, ha="left", fontsize=12, fontweight="bold")
    fig.savefig(PLOTS / "e5_maps.png"), plt.close(fig)


def write(rows, fname):
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with open(RES / fname, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main():
    psutil.Process().cpu_affinity(performance_cpus())
    numba.set_num_threads(len(performance_cpus()))
    out = {"acc": [], "cls": [], "asp": [], "dem": [], "sens": [], "map": None}
    for name, path in GRIDS.items():
        z, s, s_valid, res0, nodata = analyse_grid(name, path, out)
        if name == "chamoli_2m":
            print("independent sensors over the Chamoli footprint:", flush=True)
            sensors(z, s, s_valid, res0, nodata, out)
        del z, s, s_valid
    write(out["acc"], "e5_accuracy.csv")
    write(out["cls"], "e5_by_class.csv")
    write(out["asp"], "e5_aspect.csv")
    write(out["dem"], "e5_dem_check.csv")
    write(out["sens"], "e5_sensors.csv")
    if out["map"]:
        map_figure(*out["map"])
    print("wrote results/e5_*.csv and results/plots/e5_maps.png")


if __name__ == "__main__":
    main()
