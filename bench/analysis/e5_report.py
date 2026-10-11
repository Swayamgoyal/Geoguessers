"""E5 (pyramid on demand) analysis: tables (results/e5_tables.md) and charts (results/plots/e5_*.png).

Inputs: results/e5_accuracy.csv, e5_by_class.csv, e5_aspect.csv, e5_dem_check.csv, e5_sensors.csv
(bench/experiments/e5_accuracy.py) and results/e5_timing.csv, e5_precompute.csv (bench/experiments/e5_timing.py).
The map figure results/plots/e5_maps.png is written by e5_accuracy.py.

    python -m bench.analysis.e5_report
"""
import matplotlib.colors as mcolors
import numpy as np
import pandas as pd

from bench.analysis.phase2_report import AXIS, INK2, PLOTS, RES, S, label_end, md_table, plt

NAMES = {"chamoli_2m": "Chamoli 2 m", "tile571_8m": "tile-571 8 m"}
COG, EXACT, PRE = "on demand (COG overview)", "on demand (exact 2^k pyramid)", "precomputed slope pyramid"
ROUTES = {"on_demand": "on demand from DEM pyramid", "full_res": "full resolution, then averaged",
          "precomputed": "precomputed slope pyramid"}


def load(name):
    p = RES / name
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


# ---------------------------------------------------------------- tables
def accuracy(acc):
    rows = []
    for (ds, lvl), q in acc.groupby(["dataset", "level"], sort=False):
        c = q[q.source == COG].iloc[0]
        ex = q[q.source == EXACT]
        pre = q[q.source == PRE]
        rows.append({"grid": NAMES[ds], "level": lvl, "cell size m": c.res_m, "cells scored": c.n,
                     "share scored": c.coverage, "RMSE deg": c.rmse, "bias deg": c.bias, "MAE deg": c.mae,
                     "P95 abs deg": c.p95_abs, "% > 5 deg": c.pct_gt5, "% > 10 deg": c.pct_gt10,
                     "mean truth deg": c.mean_truth, "mean on-demand deg": c.mean_coarse,
                     "on-demand / truth": c.coarse_over_truth,
                     "RMSE exact pyramid": ex.rmse.iloc[0] if len(ex) else np.nan,
                     "RMSE precomputed": pre.rmse.iloc[0] if len(pre) else np.nan})
    return pd.DataFrame(rows)


def thresholds(acc):
    q = acc[acc.source == COG]
    if "pct_truth_ge30" not in q:
        return pd.DataFrame()
    return pd.DataFrame({"grid": q.dataset.map(NAMES), "level": q.level, "cell size m": q.res_m,
                         "% >= 30 deg, truth": q.pct_truth_ge30, "% >= 30 deg, on demand": q.pct_coarse_ge30,
                         "same side of 30 deg %": q.agree_ge30,
                         "% >= 45 deg, truth": q.pct_truth_ge45, "% >= 45 deg, on demand": q.pct_coarse_ge45,
                         "same side of 45 deg %": q.agree_ge45})


def by_class(cls, col):
    q = cls[cls.source == COG].copy()
    q["grid"] = q.dataset.map(NAMES)
    q["cell size m"] = q.res_m.round(0).astype(int)
    t = q.pivot_table(index=["grid", "cell size m"], columns="slope_class", values=col, sort=False)
    order = [c for c in ["0-10", "10-20", "20-30", "30-40", "40-50", "50-90"] if c in t.columns]
    t = t[order].reset_index()
    t.columns.name = None
    return t.rename(columns={c: f"{c} deg" for c in order})


def aspect(asp):
    return pd.DataFrame({"grid": asp.dataset.map(NAMES), "level": asp.level, "cell size m": asp.res_m,
                         "cells scored": asp.n, "share of slope cells scored": asp.share_scored,
                         "mean abs error deg": asp.mae, "median deg": asp["median"], "P95 deg": asp.p95,
                         "% > 22.5 deg (one of 16 directions)": asp.pct_gt22_5, "% > 45 deg": asp.pct_gt45})


def timing_table(tm, view):
    q = tm[tm.view == view]
    if q.empty:
        return pd.DataFrame()
    m = q.groupby(["dataset", "level", "route", "cache"]).seconds.median().unstack(["route", "cache"])
    res = q.groupby(["dataset", "level"]).res_m.first()
    rows = []
    for (ds, lvl), r in m.iterrows():
        g = lambda route, cache: r.get((route, cache), np.nan)  # noqa: E731
        rows.append({"grid": NAMES[ds], "level": lvl, "cell size m": res[(ds, lvl)],
                     "on demand warm s": g("on_demand", "warm"), "on demand cold s": g("on_demand", "cold"),
                     "full res + average warm s": g("full_res", "warm"), "full res + average cold s": g("full_res", "cold"),
                     "precomputed warm s": g("precomputed", "warm"), "precomputed cold s": g("precomputed", "cold"),
                     "time saved by on demand (warm)": g("full_res", "warm") / g("on_demand", "warm"),
                     "time saved (cold)": g("full_res", "cold") / g("on_demand", "cold")})
    return pd.DataFrame(rows)


def tradeoff(acc_t, tiles):
    if tiles.empty:
        return pd.DataFrame()
    t = tiles.merge(acc_t[["grid", "level", "RMSE deg", "bias deg", "% > 5 deg"]], on=["grid", "level"], how="left")
    return t[["grid", "level", "cell size m", "on demand warm s", "full res + average warm s",
              "time saved by on demand (warm)", "time saved (cold)", "RMSE deg", "bias deg", "% > 5 deg"]]


# ---------------------------------------------------------------- charts
def chart_error(acc):
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    for i, (ds, q) in enumerate(acc[acc.source == COG].groupby("dataset", sort=False)):
        ax.plot(q.res_m, q.rmse, marker="o", color=S[i], label=f"{NAMES[ds]}: RMSE")
        ax.plot(q.res_m, -q.bias, marker="o", ls="--", color=S[i], label=f"{NAMES[ds]}: underestimate (-bias)")
        label_end(ax, q.res_m.iloc[-1], q.rmse.iloc[-1], f"{q.rmse.iloc[-1]:.1f}°")
    ax.set_xscale("log", base=2)
    xs = sorted(acc.res_m.round().unique())
    ax.set_xticks(xs, [f"{x:.0f}" for x in xs])
    ax.set_xlabel("pyramid level cell size (m)"), ax.set_ylabel("slope error (degrees)")
    ax.set_title("E5: slope computed from a coarser pyramid level vs the full-resolution truth")
    ax.legend(loc="upper left", fontsize=8)
    fig.savefig(PLOTS / "e5_error_by_level.png"), plt.close(fig)


def chart_by_class(cls):
    q = cls[(cls.source == COG) & (cls.dataset == "chamoli_2m")]
    lv = sorted(q.level.unique())
    ramp = mcolors.LinearSegmentedColormap.from_list("lv", ["#a9c8ee", S[0], "#0e2f57"])
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    order = ["0-10", "10-20", "20-30", "30-40", "40-50", "50-90"]
    for i, l in enumerate(lv):
        r = q[q.level == l].set_index("slope_class").reindex(order)
        ax.plot(range(len(order)), r.pct_gt5, marker="o", color=ramp(i / max(len(lv) - 1, 1)),
                label=f"{r.res_m.dropna().iloc[0]:.0f} m")
    ax.set_xticks(range(len(order)), [f"{o}°" for o in order])
    ax.set_xlabel("true slope class"), ax.set_ylabel("cells with error > 5° (%)")
    ax.set_title("E5: steeper terrain loses more slope at coarse levels (Chamoli)")
    ax.legend(title="pyramid level", loc="upper left", fontsize=8, title_fontsize=8)
    fig.savefig(PLOTS / "e5_by_class.png"), plt.close(fig)


def chart_tradeoff(tr):
    if tr.empty:
        return
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    for i, (g, q) in enumerate(tr[tr.level > 0].groupby("grid", sort=False)):
        ax.plot(q["time saved by on demand (warm)"], q["RMSE deg"], marker="o", color=S[i], label=g)
        for _, r in q.iterrows():
            ax.annotate(f"{r['cell size m']:.0f} m", (r["time saved by on demand (warm)"], r["RMSE deg"]),
                        xytext=(6, -3), textcoords="offset points", fontsize=8, color=INK2)
    ax.set_xscale("log")
    ax.set_xlabel("time saved per 512² display tile (full-res route / on demand, warm)")
    ax.set_ylabel("slope RMSE vs truth (degrees)")
    ax.set_title("E5: error against time saved, one display tile per pyramid level")
    ax.legend(loc="upper left")
    fig.savefig(PLOTS / "e5_tradeoff.png"), plt.close(fig)


def chart_tile_time(tm):
    q = tm[(tm.view == "tile") & (tm.dataset == "chamoli_2m")]
    if q.empty:
        return
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    for i, (route, name) in enumerate(ROUTES.items()):
        for cache, ls in (("warm", "-"), ("cold", ":")):
            m = q[(q.route == route) & (q.cache == cache)].groupby("res_m").seconds.median() * 1e3
            if len(m):
                ax.plot(m.index, m.values, marker="o", ls=ls, color=S[i], label=f"{name}, {cache}")
    ax.set_xscale("log", base=2), ax.set_yscale("log")
    xs = sorted(q.res_m.unique())
    ax.set_xticks(xs, [f"{x:.0f}" for x in xs])
    ax.axhline(100, color=AXIS, lw=1)
    ax.annotate("100 ms", (xs[0], 100), xytext=(2, 3), textcoords="offset points", fontsize=8, color=INK2)
    ax.set_xlabel("pyramid level cell size (m)"), ax.set_ylabel("time for one 512² slope tile (ms)")
    ax.set_title("E5: one display tile, Chamoli")
    ax.legend(loc="upper left", fontsize=8)
    fig.savefig(PLOTS / "e5_tile_time.png"), plt.close(fig)


def chart_sensors(sens):
    if sens.empty:
        return
    q = sens[sens.comparison.str.endswith("vs truth")].copy()
    q["kind"] = np.where(q.comparison.str.startswith("Chamoli"), "Chamoli 2 m averaged to this size (pyramid)",
                         "independent DEM at this size")
    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    res = sorted(q.resolution_m.unique())
    x = np.arange(len(res))
    for i, kind in enumerate(["Chamoli 2 m averaged to this size (pyramid)", "independent DEM at this size"]):
        v = q[q.kind == kind].set_index("resolution_m").reindex(res)
        ax.bar(x + (i - 0.5) * 0.38, v.rmse, width=0.36, color=S[i], label=kind)
        for xi, val in zip(x, v.rmse):
            ax.annotate(f"{val:.1f}°", (xi + (i - 0.5) * 0.38, val), xytext=(0, 3), textcoords="offset points",
                        ha="center", fontsize=8, color=INK2)
    names = {8.0: "8 m\n(HMA 8 m)", 30.0: "30 m\n(Copernicus 30)", 90.0: "90 m\n(Copernicus 90)"}
    ax.set_xticks(x, [names.get(r, f"{r:.0f} m") for r in res])
    ax.set_ylabel("slope RMSE vs 2 m truth (degrees)")
    ax.set_title("E5: a pyramid level of good data beats a coarse DEM from another source")
    ax.legend(loc="upper left", fontsize=8)
    fig.savefig(PLOTS / "e5_sensors.png"), plt.close(fig)


def main():
    acc, cls, asp, dem, sens = (load(f"e5_{n}.csv") for n in ("accuracy", "by_class", "aspect", "dem_check", "sensors"))
    tm, pre = load("e5_timing.csv"), load("e5_precompute.csv")
    acc_t = accuracy(acc)
    tiles, whole = timing_table(tm, "tile"), timing_table(tm, "whole")
    tr = tradeoff(acc_t, tiles)
    PLOTS.mkdir(parents=True, exist_ok=True)
    chart_error(acc), chart_by_class(cls), chart_tradeoff(tr), chart_tile_time(tm), chart_sensors(sens)
    out = ["# E5 (pyramid on demand) result tables", "",
           "Generated by `python -m bench.analysis.e5_report`. Accuracy: `bench/experiments/e5_accuracy.py`; "
           "timing: `bench/experiments/e5_timing.py` (medians).", "",
           "## Slope from each pyramid level vs the full-resolution truth", "", md_table(acc_t), "",
           "## Bias by true slope class (degrees, on demand from the COG overview)", "", md_table(by_class(cls, "bias")), "",
           "## RMSE by true slope class (degrees)", "", md_table(by_class(cls, "rmse")), "",
           "## Cells off by more than 5 degrees, by true slope class (%)", "", md_table(by_class(cls, "pct_gt5")), "",
           "## Slope thresholds (share of cells at or above 30 / 45 degrees)", "", md_table(thresholds(acc)), "",
           "## Aspect", "", md_table(aspect(asp)), "",
           "## Independent DEMs over the Chamoli footprint", "", md_table(sens), "",
           "## GDAL overview DEM vs mean fine elevation over each footprint", "", md_table(dem), "",
           "## Time for one 512 x 512 display tile", "", md_table(tiles, 4) if not tiles.empty else "(not run)", "",
           "## Time for the whole grid at each level", "", md_table(whole, 3) if not whole.empty else "(not run)", "",
           "## Error against time saved (one display tile, warm)", "", md_table(tr, 3) if not tr.empty else "(not run)",
           "", "## Cost of a precomputed slope pyramid (once per derivative)", "",
           md_table(pre) if not pre.empty else "(not run)", ""]
    (RES / "e5_tables.md").write_text("\n".join(out), encoding="utf-8")
    print("wrote", RES / "e5_tables.md", sorted(p.name for p in PLOTS.glob("e5_*.png")))


if __name__ == "__main__":
    main()
