"""Phase 2 analysis: tables (results/phase2_tables.md) and charts (results/plots/*.png) from results/runs.csv.

    python -m bench.analysis.phase2_report

Medians over measured repeats (rep >= 1; rep 0 is the warm-up). Large synthetic grids have
3 cold + 1 warm runs, so their 'warm' value is a single run.
"""
import json
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
RES = REPO / "results"
PLOTS = RES / "plots"
ORDER = ["tile571_90m", "tile571_30m", "tile571_8m", "chamoli_2m", "tile571_2m_cubic", "tile571_1m_cubic"]
LABEL = {"tile571_90m": "90 m", "tile571_30m": "30 m", "tile571_8m": "8 m", "chamoli_2m": "2 m real (Chamoli)",
         "tile571_2m_cubic": "2 m synthetic", "tile571_1m_cubic": "1 m synthetic"}
VARIANTS = ["strip_none", "tile256_none", "tile512_none", "tile512_lzw", "tile512_deflate", "tile512_zstd",
            "tile256_zstd"]

# reference palette (light): categorical slots in fixed order, chrome and ink
S = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
INK, INK2, MUTED, GRID, AXIS, SURF = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
plt.rcParams.update({
    "font.family": ["Segoe UI", "DejaVu Sans"], "font.size": 10, "figure.facecolor": SURF,
    "axes.facecolor": SURF, "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "axes.titlecolor": INK,
    "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.6, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.spines.top": False, "axes.spines.right": False, "lines.linewidth": 2, "lines.markersize": 6,
    "legend.frameon": False, "legend.labelcolor": INK2, "savefig.dpi": 160, "savefig.bbox": "tight",
})


def load():
    d = pd.read_csv(RES / "runs.csv")
    d = d[d.ok & (d.rep >= 1)].copy()
    d["method"] = d.method.fillna("")
    d["t_internal"] = pd.to_numeric(d.t_internal, errors="coerce")
    return d


def med(d, **kw):
    q = d
    for k, v in kw.items():
        q = q[q[k] == v]
    return q


def md_table(df, floatfmt=2):
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_float_dtype(df[c]):
            df[c] = df[c].map(lambda v: "" if pd.isna(v) else f"{v:,.{floatfmt}f}")
    head = "| " + " | ".join(str(c) for c in df.columns) + " |"
    sep = "|" + "|".join("---" for _ in df.columns) + "|"
    rows = ["| " + " | ".join(str(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join([head, sep] + rows)


def label_end(ax, x, y, text, color=INK2, dy=0):
    """Direct label at a line's last point; dy (points) nudges labels whose lines end close together."""
    ax.annotate(text, (x, y), xytext=(6, dy), textcoords="offset points", va="center", color=color, fontsize=9)


# ---------------------------------------------------------------- E1
def e1_tables(d):
    e = d[(d.experiment == "E1")]
    rows = []
    for ds in ORDER:
        g = e[e.dataset == ds]
        if g.empty:
            continue
        cells = g.cells.iloc[0]

        def m(op, method, cache, col="t_total"):
            s = g[(g.op == op) & (g.method == method) & (g.cache_state == cache)][col]
            return s.median() if len(s) else float("nan")
        slope_w = m("slope", "Horn", "warm")
        rows.append({
            "grid": LABEL[ds], "cells (M)": cells / 1e6,
            "slope cold s": m("slope", "Horn", "cold"), "slope warm s": slope_w,
            "hillshade warm s": m("hillshade", "Horn", "warm"),
            "read warm s": m("read", "blocks", "warm", "t_internal"), "copy warm s": m("copy", "gtiff", "warm"),
            "slope ns/cell": slope_w / cells * 1e9,
            "peak MiB (gdaldem)": g[g.impl == "gdaldem"].peak_rss_mb.max(),
            "CPU cores": g[(g.op == "slope") & (g.method == "Horn")].avg_cores.median(),
            "slope disk read MiB (warm)": m("slope", "Horn", "warm", "disk_read_mb"),
        })
    return pd.DataFrame(rows)


def e1_stage_split(d):
    t = e1_tables(d)
    out = pd.DataFrame({"grid": t.grid, "read": t["read warm s"],
                        "write + tool overhead": t["copy warm s"] - t["read warm s"],
                        "compute": t["slope warm s"] - t["copy warm s"], "slope total": t["slope warm s"]})
    for c in ["read", "write + tool overhead", "compute"]:
        out[c + " %"] = 100 * out[c] / out["slope total"]
    return out


def e1_ops(d):
    e = d[(d.experiment == "E1") & (d.cache_state == "warm") & (d.impl == "gdaldem")]
    rows = []
    for ds in ["tile571_8m", "chamoli_2m"]:
        g = e[e.dataset == ds]
        cells = g.cells.iloc[0]
        for (op, method), s in g.groupby(["op", "method"]):
            rows.append({"grid": LABEL[ds], "config": f"{op} {method}".strip(), "ns/cell": s.t_total.median() / cells * 1e9})
    t = pd.DataFrame(rows).pivot(index="config", columns="grid", values="ns/cell").reset_index()
    return t.sort_values(t.columns[-1])


def pinning_table(d):
    first = RES / "e1_first_pass_unpinned.csv"
    if not first.exists():
        return pd.DataFrame()
    f = pd.read_csv(first)
    f = f[f.ok & (f.rep >= 1)]
    rows = []
    for ds in ["tile571_8m", "chamoli_2m", "tile571_2m_cubic", "tile571_1m_cubic"]:
        for name, src in (("unpinned (first pass)", f), ("pinned to performance cores", d[d.experiment == "E1"])):
            s = src[(src.dataset == ds) & (src.op == "slope") & (src.method == "Horn") & (src.cache_state == "cold")].t_total
            if len(s):
                rows.append({"grid": LABEL[ds], "run": name, "n": len(s), "median s": s.median(),
                             "min s": s.min(), "max s": s.max(), "spread %": 100 * (s.max() - s.min()) / s.median()})
    return pd.DataFrame(rows)


def plot_e1_scaling(d):
    e = d[d.experiment == "E1"]
    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    series = [("slope", "Horn", "t_total", "gdaldem slope", "o", "-", 7),
              ("hillshade", "Horn", "t_total", "gdaldem hillshade", "s", "-", -7),
              ("copy", "gtiff", "t_total", "copy (read + write)", "^", "--", 0),
              ("read", "blocks", "t_internal", "read + decompress only", "D", ":", 0)]
    for i, (op, method, col, name, mk, ls, dy) in enumerate(series):
        g = e[(e.op == op) & (e.method == method) & (e.cache_state == "warm")]
        g = g.groupby("cells")[col].median().sort_index()
        ax.plot(g.index, g.values, marker=mk, ls=ls, color=S[i], label=name)
        label_end(ax, g.index[-1], g.values[-1], f"{name} {g.values[-1]:.0f} s", dy=dy)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("grid cells")
    ax.set_ylabel("time, warm cache (s)")
    ax.set_title("E1: gdaldem time grows linearly with grid size")
    ax.legend(loc="upper left")
    ax.set_xlim(right=ax.get_xlim()[1] * 8)
    fig.savefig(PLOTS / "e1_scaling.png")
    plt.close(fig)


def plot_e1_memory(d):
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    e = d[(d.experiment == "E1") & (d.impl == "gdaldem")].groupby("cells").peak_rss_mb.max().sort_index()
    ax.plot(e.index, e.values, marker="o", color=S[0], label="gdaldem (any operator)")
    label_end(ax, e.index[-1], e.values[-1], f"{e.values[-1]:.0f} MiB", dy=-7)
    q = d[(d.experiment == "E1q") & (d.method == "full-none")]
    if len(q):
        q = q.groupby("cells").peak_rss_mb.max().sort_index()
        ax.plot(q.index, q.values, marker="s", ls="--", color=S[1], label="QGIS draw, no pyramid")
        label_end(ax, q.index[-1], q.values[-1], f"{q.values[-1]:.0f} MiB", dy=7)
    ram = 16 * 1024
    ax.axhline(ram, color=AXIS, lw=1)
    ax.annotate("laptop RAM, 16 GB", (e.index[-1] * 6, ram), xytext=(0, 4), textcoords="offset points",
                color=INK2, fontsize=9, ha="right")
    raw = pd.Series(e.index.values * 4 / 2**20, index=e.index)
    ax.plot(raw.index, raw.values, ls=":", color=MUTED, lw=1.5, label="size of the grid itself (float32)")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("grid cells")
    ax.set_ylabel("peak memory (MiB)")
    ax.set_title("E1: gdaldem memory levels off at ~830 MiB (0.87 GB), whatever the grid size")
    ax.legend(loc="lower right")
    ax.set_xlim(right=ax.get_xlim()[1] * 6)
    fig.savefig(PLOTS / "e1_memory.png")
    plt.close(fig)


def plot_e1_stages(d):
    s = e1_stage_split(d)
    s = s[s.grid.isin([LABEL[x] for x in ["tile571_8m", "chamoli_2m", "tile571_2m_cubic", "tile571_1m_cubic"]])]
    fig, ax = plt.subplots(figsize=(7.5, 3.2))
    left = pd.Series(0.0, index=s.index)
    for i, c in enumerate(["read %", "write + tool overhead %", "compute %"]):
        v = s[c].clip(lower=0)
        ax.barh(s.grid, v, left=left, color=S[i], edgecolor=SURF, linewidth=2, label=c.replace(" %", ""))
        for y, (l, w) in enumerate(zip(left, v)):
            if w >= 8:
                ax.text(l + w / 2, y, f"{w:.0f}%", ha="center", va="center", color="white", fontsize=9)
        left += v
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("share of gdaldem slope time, warm cache (%)")
    ax.set_title("E1: most of the time is computation, not disk")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=3)
    fig.savefig(PLOTS / "e1_stages.png")
    plt.close(fig)


def plot_e1_ops(d):
    t = e1_ops(d)
    col = LABEL["chamoli_2m"]
    t = t.sort_values(col)
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    ax.barh(t.config, t[col], color=S[0], height=0.6)
    for y, v in enumerate(t[col]):
        ax.text(v, y, f" {v:.1f}", va="center", color=INK2, fontsize=9)
    ax.set_xlabel("time per cell, warm cache (ns), 2 m real grid")
    ax.set_title("E1: operators and methods cost about the same")
    ax.grid(axis="y", visible=False)
    fig.savefig(PLOTS / "e1_operators.png")
    plt.close(fig)


# ---------------------------------------------------------------- E2
def e2_table(d):
    e = d[d.experiment == "E2"]
    sizes = {}
    if (RES / "e2_files.csv").exists():
        s = pd.read_csv(RES / "e2_files.csv")
        sizes = {(r.dataset, r.variant): r.bytes for r in s.itertuples()}
    rows = []
    for ds in ["tile571_8m", "tile571_2m_cubic"]:
        for v in VARIANTS:
            g = e[(e.dataset == ds) & (e.variant == v)]
            if g.empty:
                continue
            size = sizes.get((ds, v), float("nan"))

            def m(op, cache, col="t_total"):
                s = g[(g.op == op) & (g.cache_state == cache)][col]
                return s.median() if len(s) else float("nan")
            rows.append({"grid": LABEL[ds], "layout": v, "file MiB": size / 2**20,
                         "create s": m("create", "warm"), "read cold s": m("read", "cold", "t_internal"),
                         "read warm s": m("read", "warm", "t_internal"), "slope cold s": m("slope", "cold"),
                         "slope warm s": m("slope", "warm")})
    return pd.DataFrame(rows)


def plot_e2(d):
    t = e2_table(d)
    if t.empty:
        return
    t = t[t.grid == LABEL["tile571_2m_cubic"]]
    if t.empty:
        return
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.6), sharey=True)
    for ax, (col, title, color) in zip(axes, [("file MiB", "file size (MiB)", S[0]), ("read cold s", "read, cold (s)", S[1]),
                                               ("slope cold s", "gdaldem slope, cold (s)", S[2])]):
        ax.barh(t.layout, t[col], color=color, height=0.6)
        for y, v in enumerate(t[col]):
            ax.text(v, y, f" {v:,.0f}", va="center", color=INK2, fontsize=8)
        ax.set_title(title, fontsize=10)
        ax.grid(axis="y", visible=False)
        ax.set_xlim(0, t[col].max() * 1.3)
    axes[0].invert_yaxis()
    fig.suptitle("E2: storage layout, 2 m synthetic grid (2.7 B cells)", x=0.01, ha="left", fontweight="bold", color=INK)
    fig.savefig(PLOTS / "e2_storage.png")
    plt.close(fig)


# ---------------------------------------------------------------- E1-QGIS
def e1q_table(d):
    e = d[d.experiment == "E1q"].copy()
    if e.empty:
        return pd.DataFrame()
    ex = e.extra.fillna("{}").map(json.loads)
    e["t_open"] = ex.map(lambda x: x.get("t_open"))
    e["filled"] = ex.map(lambda x: x.get("filled"))
    rows = []
    for (ds, method), g in e.groupby(["dataset", "method"]):
        rows.append({"grid": LABEL[ds], "view-pyramid": method,
                     "open cold s": g[g.cache_state == "cold"].t_open.median(),
                     "draw cold s": g[g.cache_state == "cold"].t_internal.median(),
                     "draw warm s": g[g.cache_state == "warm"].t_internal.median(),
                     "peak MiB": g.peak_rss_mb.max(), "filled": g.filled.median(), "_o": ORDER.index(ds)})
    return pd.DataFrame(rows).sort_values(["_o", "view-pyramid"]).drop(columns="_o")


def plot_e1q(d):
    e = d[d.experiment == "E1q"]
    if e.empty:
        return
    fig, ax = plt.subplots(figsize=(7.5, 4.4))
    for i, (method, name, mk, ls) in enumerate([("full-use", "whole area, with pyramid", "o", "-"),
                                                ("full-none", "whole area, no pyramid", "s", "--"),
                                                ("zoom-use", "zoomed in, with pyramid", "^", "-"),
                                                ("zoom-none", "zoomed in, no pyramid", "D", "--")]):
        g = e[(e.method == method) & (e.cache_state == "cold")].groupby("cells").t_internal.median().sort_index()
        if len(g):
            ax.plot(g.index, g.values, marker=mk, ls=ls, color=S[i], label=name)
            if method == "zoom-none":
                label_end(ax, g.index[-1], g.values[-1], f"zoomed in (both) {g.values[-1]:.2f} s", dy=8)
            elif method != "zoom-use":  # the two zoomed lines overlap; one shared label
                label_end(ax, g.index[-1], g.values[-1], f"{g.values[-1]:.2f} s", dy=-6 if method == "full-use" else 0)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("grid cells")
    ax.set_ylabel("QGIS draw time, cold cache (s)")
    ax.set_title("QGIS: without a pyramid, drawing the whole area scales with grid size")
    ax.legend(loc="upper left")
    ax.set_xlim(right=ax.get_xlim()[1] * 5)
    fig.savefig(PLOTS / "e1q_render.png")
    plt.close(fig)


def main():
    PLOTS.mkdir(parents=True, exist_ok=True)
    d = load()
    parts = ["# Phase 2 result tables", "", "Generated by `python -m bench.analysis.phase2_report` from `results/runs.csv`. "
             "Medians over measured repeats; all tools pinned to the performance cores.", ""]
    for title, df in [("E1: gdaldem baseline by grid size (Horn)", e1_tables(d)),
                      ("E1: where the slope time goes (warm cache)", e1_stage_split(d)),
                      ("E1: operators and methods, ns per cell (warm)", e1_ops(d)),
                      ("E1: effect of pinning to performance cores (slope Horn, cold)", pinning_table(d)),
                      ("E2: storage layout", e2_table(d)),
                      ("E1-QGIS: open and draw one 1920x1080 view", e1q_table(d))]:
        if len(df):
            parts += [f"## {title}", "", md_table(df), ""]
    (RES / "phase2_tables.md").write_text("\n".join(parts), encoding="utf-8")
    for f in (plot_e1_scaling, plot_e1_memory, plot_e1_stages, plot_e1_ops, plot_e2, plot_e1q):
        f(d)
    print("wrote", RES / "phase2_tables.md", "and", sorted(p.name for p in PLOTS.glob("*.png")))


if __name__ == "__main__":
    main()
