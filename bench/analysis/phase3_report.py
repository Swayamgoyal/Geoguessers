"""Phase 3 (E3, CPU) analysis: tables (results/phase3_tables.md) and charts (results/plots/e3_*.png).

Compares our engine (demlab) with the gdaldem baseline from E1 on the same grids, harness and machine.

    python -m bench.analysis.phase3_report
"""
import json

import numpy as np
import pandas as pd

from bench.analysis.phase2_report import (INK2, LABEL, ORDER, PLOTS, RES, S, AXIS, label_end, md_table, plt)

GRIDS = [g for g in ORDER if g in ("tile571_8m", "chamoli_2m", "tile571_2m_cubic", "tile571_1m_cubic")]
THREE = "slope+aspect+hillshade"


def load_all():
    d = pd.read_csv(RES / "runs.csv")
    d["method"] = d.method.fillna("")
    d["variant"] = d.variant.fillna("")
    d["t_internal"] = pd.to_numeric(d.t_internal, errors="coerce")
    for k in ("read", "compute", "write", "writer_busy", "t_imports"):
        d[k] = d.extra.map(lambda x, k=k: json.loads(x).get(k) if isinstance(x, str) and x.startswith("{") else np.nan)
    return d


def med(d, cache="warm", col="t_total", **kw):
    q = d[(d.rep >= 1) & d.ok]
    if cache:
        q = q[q.cache_state == cache]
    for k, v in kw.items():
        q = q[q[k] == v]
    return q[col].median() if len(q) else np.nan


def gdal(d, ds, op, cache="warm", col="t_total"):
    return med(d, cache, col, experiment="E1", dataset=ds, op=op, method="Horn" if op != "TPI" else "")


def eng(d, ds, variant, cache="warm", col="t_total"):
    return med(d, cache, col, experiment="E3", dataset=ds, variant=variant)


# ---------------------------------------------------------------- tables
def headline(d):
    rows = []
    for ds in GRIDS:
        g_c, g_w = gdal(d, ds, "slope", "cold"), gdal(d, ds, "slope")
        e_c, e_w = eng(d, ds, "engine_all_slope", "cold"), eng(d, ds, "engine_all_slope")
        p_w = eng(d, ds, "engine_perf_slope")
        rows.append({"grid": LABEL[ds], "gdaldem cold s": g_c, "gdaldem warm s": g_w,
                     "engine (22 thr) cold s": e_c, "engine (22 thr) warm s": e_w,
                     "engine (12 P-thr) warm s": p_w, "speed-up warm": g_w / e_w,
                     "engine peak MB": eng(d, ds, "engine_all_slope", None, "peak_rss_mb"),
                     "engine cores": eng(d, ds, "engine_all_slope", None, "avg_cores")})
    return pd.DataFrame(rows)


def products(d):
    rows = []
    for ds in GRIDS:
        g = [gdal(d, ds, op) for op in ("slope", "aspect", "hillshade")]
        sep = [eng(d, ds, f"engine_all_{op}") for op in ("slope", "aspect", "hillshade")]
        fused = eng(d, ds, "engine_all_3prod")
        rows.append({"grid": LABEL[ds], "gdaldem 3 runs s": sum(g) if not any(np.isnan(g)) else np.nan,
                     "engine 3 separate runs s": sum(sep) if not any(np.isnan(sep)) else np.nan,
                     "engine fused 1 pass s": fused,
                     "fused vs gdaldem": (sum(g) / fused) if not any(np.isnan(g)) else np.nan})
    return pd.DataFrame(rows)


def stages(d):
    rows = []
    for ds in GRIDS:
        for v in ("engine_all_slope", "engine_all_slope_nowrite", "engine_all_slope_zstd1", "engine_all_3prod"):
            q = d[(d.experiment == "E3") & (d.dataset == ds) & (d.variant == v) & d.ok & (d.rep >= 1)]
            if q.empty:
                continue
            rows.append({"grid": LABEL[ds], "variant": v, "total s": q.t_total.median(),
                         "python start-up s": q.t_imports.median(), "wait for read s": q.read.median(),
                         "compute s": q.compute.median(), "wait for writer s": q.write.median(),
                         "writer busy s": q.writer_busy.median(), "written MB": q.proc_write_mb.median()})
    return pd.DataFrame(rows)


def threads(d):
    rows = []
    for ds in GRIDS:
        base = None
        for n, v in [(1, "threads_1"), (2, "threads_2"), (4, "threads_4"), (8, "threads_8"),
                     (12, "engine_perf_slope"), (22, "engine_all_slope")]:
            t = eng(d, ds, v)
            c = eng(d, ds, v, col="compute")
            if np.isnan(t):
                continue
            base = base or (t, c)
            rows.append({"grid": LABEL[ds], "threads": n, "cores": "all 22" if n == 22 else "performance",
                         "total s": t, "speed-up total": base[0] / t, "kernel s": c, "speed-up kernel": base[1] / c})
    return pd.DataFrame(rows)


def window_sizes(d):
    rows = []
    for ds in GRIDS:
        for n in (512, 1024, 2048, 4096, 8192):
            v = "engine_perf_slope" if n == 2048 else f"window_{n}"
            w = eng(d, ds, v)
            if np.isnan(w):
                continue
            q = d[(d.experiment == "E3") & (d.dataset == ds) & (d.variant == v) & d.ok]
            rows.append({"grid": LABEL[ds], "window": n, "cold s": eng(d, ds, v, "cold"), "warm s": w,
                         "peak MB": q.peak_rss_mb.median(), "wait for read s": eng(d, ds, v, col="read"),
                         "compute s": eng(d, ds, v, col="compute"), "wait for writer s": eng(d, ds, v, col="write")})
    return pd.DataFrame(rows)


def whole_array(d):
    rows = []
    for ds in GRIDS:
        q = d[(d.experiment == "E3") & (d.dataset == ds) & (d.variant == "naive_slope") & (d.rep >= 1)]
        if q.empty:
            continue
        ok = q[q.ok]
        rows.append({"grid": LABEL[ds], "cells (M)": q.cells.iloc[0] / 1e6, "runs": len(q), "succeeded": len(ok),
                     "time s": ok.t_total.median() if len(ok) else q.t_total.median(),
                     "peak MB": q.peak_rss_mb.max(),
                     "outcome": "ok" if len(ok) == len(q) else "out of memory: " + (
                         q[~q.ok].error.str.extract(r"(Unable to allocate [\d.]+ GiB)")[0].iloc[0] or "see error")})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- charts
def chart_scaling(d):
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    series = [("gdaldem slope", lambda ds: gdal(d, ds, "slope"), "o", "-", 0),
              ("engine slope, 22 threads", lambda ds: eng(d, ds, "engine_all_slope"), "s", "-", 1),
              ("engine, no output written", lambda ds: eng(d, ds, "engine_all_slope_nowrite"), "^", "--", 2),
              ("NumPy tiled, 1 thread", lambda ds: eng(d, ds, "numpy_tiled_slope", None), "D", ":", 3)]
    cells = {ds: d[d.dataset == ds].cells.iloc[0] for ds in GRIDS if (d.dataset == ds).any()}
    for name, f, mk, ls, i in series:
        xs = [(cells[ds], f(ds)) for ds in GRIDS if ds in cells and not np.isnan(f(ds))]
        if xs:
            x, y = zip(*xs)
            ax.plot(x, y, marker=mk, ls=ls, color=S[i], label=name)
            label_end(ax, x[-1], y[-1], f"{y[-1]:.1f} s", dy={0: 7, 1: 5, 2: -7}.get(i, 0))
    ax.set_xscale("log"), ax.set_yscale("log")
    ax.set_xlabel("grid cells"), ax.set_ylabel("time, warm cache (s)")
    ax.set_title("E3: our engine vs gdaldem (slope, Horn)")
    ax.legend(loc="upper left")
    fig.savefig(PLOTS / "e3_scaling.png"), plt.close(fig)


def chart_threads(t):
    if t.empty:
        return
    fig, ax = plt.subplots(figsize=(6.6, 4.2))
    for i, (g, q) in enumerate(t.groupby("grid", sort=False)):
        if q.threads.iloc[0] != 1:  # no single-thread baseline on this grid
            continue
        ax.plot(q.threads, q["speed-up kernel"], marker="o", color=S[i], label=g)
        label_end(ax, q.threads.iloc[-1], q["speed-up kernel"].iloc[-1], f"{q['speed-up kernel'].iloc[-1]:.1f}x")
    ax.axvline(12, color=AXIS, lw=1, ls=":")
    ax.annotate("12 performance-core threads", (12, ax.get_ylim()[1]), xytext=(-4, -10), textcoords="offset points",
                ha="right", color=INK2, fontsize=8)
    ax.set_xlabel("threads"), ax.set_ylabel("kernel speed-up vs 1 thread")
    ax.set_title("E3: kernel speed-up with threads, inside the full pipeline")
    ax.legend(loc="upper left")
    fig.savefig(PLOTS / "e3_threads.png"), plt.close(fig)


def chart_memory(d):
    fig, ax = plt.subplots(figsize=(7.0, 4.2))
    cells = {ds: d[d.dataset == ds].cells.iloc[0] for ds in GRIDS if (d.dataset == ds).any()}
    for i, (name, pick) in enumerate([("gdaldem", lambda ds: gdal(d, ds, "slope", None, "peak_rss_mb")),
                                      ("our engine", lambda ds: eng(d, ds, "engine_all_slope", None, "peak_rss_mb"))]):
        xs = [(cells[ds], pick(ds)) for ds in GRIDS if ds in cells and not np.isnan(pick(ds))]
        if xs:
            x, y = zip(*xs)
            ax.plot(x, y, marker="os"[i], color=S[i], label=name)
    q = d[(d.experiment == "E3") & (d.variant == "naive_slope") & (d.rep >= 1)]
    for ok, mk, lab in ((True, "D", "whole grid in memory"), (False, "X", "whole grid: memory asked for (failed)")):
        p = q[q.ok == ok].groupby("cells").peak_rss_mb.max()
        if not ok:  # a failed run never reached its peak: add the allocation that was refused
            asked = q[~q.ok].groupby("cells").error.first().str.extract(r"allocate ([\d.]+) GiB")[0].astype(float)
            p = p + asked.reindex(p.index).fillna(0) * 1024
        if len(p):
            ax.plot(p.index, p.values, marker=mk, ls="--" if ok else "none", color=S[3], ms=9 if not ok else 6,
                    label=lab)
    ax.axhline(16 * 1024, color=AXIS, lw=1)
    ax.annotate("laptop RAM, 16 GB", (max(cells.values()), 16 * 1024), xytext=(0, 4), textcoords="offset points",
                ha="right", color=INK2, fontsize=9)
    ax.set_xscale("log"), ax.set_yscale("log")
    ax.set_xlabel("grid cells"), ax.set_ylabel("peak memory (MB)")
    ax.set_title("E3: streaming stays flat; the whole-grid approach hits the RAM limit")
    ax.legend(loc="center right")
    fig.savefig(PLOTS / "e3_memory.png"), plt.close(fig)


def chart_products(p):
    if p.empty:
        return
    fig, ax = plt.subplots(figsize=(7.0, 3.8))
    cols = ["gdaldem 3 runs s", "engine 3 separate runs s", "engine fused 1 pass s"]
    x = np.arange(len(p))
    w = 0.26
    for i, c in enumerate(cols):
        ax.bar(x + (i - 1) * w, p[c], width=w - 0.02, color=S[i], label=c.removesuffix(" s"))
    ax.set_xticks(x, p.grid)
    ax.set_yscale("log")
    ax.set_ylabel("time for slope + aspect + hillshade (s)")
    ax.set_title("E3: three products, separately or in one pass")
    ax.legend(loc="upper left")
    fig.savefig(PLOTS / "e3_products.png"), plt.close(fig)


def chart_window(ws):
    if ws.empty:
        return
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.0, 3.8))
    for i, (g, q) in enumerate(ws.groupby("grid", sort=False)):
        if len(q) < 2:  # 1 m: only the default window was run
            continue
        base = q.set_index("window")["warm s"].get(2048, np.nan)
        a1.plot(q.window, q["warm s"] / base, marker="o", color=S[i], label=g)
        a2.plot(q.window, q["peak MB"], marker="o", color=S[i], label=g)
    for a in (a1, a2):
        a.set_xscale("log", base=2)
        a.set_xticks([512, 1024, 2048, 4096, 8192], ["512", "1024", "2048", "4096", "8192"])
        a.set_xlabel("window size (cells per side)")
    a1.axhline(1, color=AXIS, lw=1)
    a1.set_ylabel("time vs 2048 window (warm)")
    a1.set_title("E3: time")
    a2.set_ylabel("peak memory (MB)")
    a2.set_title("E3: memory")
    a1.legend(loc="upper center")
    fig.savefig(PLOTS / "e3_window.png"), plt.close(fig)


def main():
    d = load_all()
    h, p, s, t, w = headline(d), products(d), stages(d), threads(d), whole_array(d)
    ws = window_sizes(d)
    PLOTS.mkdir(parents=True, exist_ok=True)
    chart_scaling(d), chart_threads(t), chart_memory(d), chart_products(p), chart_window(ws)
    out = ["# Phase 3 (CPU) result tables", "",
           "Generated by `python -m bench.analysis.phase3_report` from `results/runs.csv`. Medians over measured "
           "repeats. gdaldem numbers are E1 (pinned to the 12 performance-core threads); engine runs are separate "
           "processes, so their times include Python start-up (~0.5 s).", "",
           "## Slope: engine vs gdaldem", "", md_table(h), "",
           "## Slope + aspect + hillshade", "", md_table(p), "",
           "## Where the engine's time goes (warm)", "", md_table(s), "",
           "## Thread scaling (slope, warm)", "", md_table(t), "",
           "## Window (tile) size (slope, 12 performance-core threads)", "", md_table(ws), "",
           "## Whole grid in memory (naive NumPy)", "", md_table(w), ""]
    (RES / "phase3_tables.md").write_text("\n".join(out), encoding="utf-8")
    print("wrote", RES / "phase3_tables.md", sorted(p.name for p in PLOTS.glob("e3_*.png")))


if __name__ == "__main__":
    main()
