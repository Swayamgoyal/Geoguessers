"""E4 (GPU) analysis: tables (results/e4_tables.md) and charts (results/plots/e4_*.png).

Compares the GPU engine (E4) with the CPU engine (E3) and gdaldem (E1) on the same grids, harness and machine,
and summarises the crossover test (results/e4_crossover.csv, bench/experiments/e4_crossover.py).

    python -m bench.analysis.e4_report
"""
import json

import numpy as np
import pandas as pd

from bench.analysis.phase2_report import AXIS, INK2, LABEL, ORDER, PLOTS, RES, S, label_end, md_table, plt
from bench.analysis.phase3_report import CONFIGS

GRIDS = [g for g in ORDER if g in ("tile571_8m", "chamoli_2m", "tile571_2m_cubic", "tile571_1m_cubic")]
LADDER = [("gpu_cupy_slope", "CuPy array port"), ("gpu_pageable_slope", "CUDA kernel, pageable copies"),
          ("gpu_pinned_slope", "+ pinned buffers"), ("gpu_slope", "+ 2 streams (default)"),
          ("gpu_slope_r8", "+ 8 reader threads"), ("gpu_slope_fp64", "default in float64"),
          ("gpu_slope_nowrite", "default, no output written")]
GPU_OP = {"engine_all_slope": "gpu_slope", "engine_all_aspect": "gpu_aspect", "engine_all_hillshade": "gpu_hillshade"}
KEYS = ("read", "compute", "write", "writer_busy", "t_imports", "gpu_init", "gpu_h2d", "gpu_kernel", "gpu_d2h",
        "gpu_host_copy", "peak_vram_mb", "gpu_temp_before", "gpu_temp_after")


def load():
    d = pd.read_csv(RES / "runs.csv")
    d["method"] = d.method.fillna("")
    d["variant"] = d.variant.fillna("")
    ex = d.extra.map(lambda x: json.loads(x) if isinstance(x, str) and x.startswith("{") else {})
    for k in KEYS:
        d[k] = pd.to_numeric(ex.map(lambda e, k=k: e.get(k)), errors="coerce")
    return d


def med(d, cache="warm", col="t_total", **kw):
    q = d[(d.rep >= 1) & d.ok]
    if cache:
        q = q[q.cache_state == cache]
    for k, v in kw.items():
        q = q[q[k] == v]
    return q[col].median() if len(q) else np.nan


def e1(d, ds, op, method, cache="warm", col="t_total"):
    return med(d, cache, col, experiment="E1", dataset=ds, op=op, method=method)


def e3(d, ds, v, cache="warm", col="t_total"):
    return med(d, cache, col, experiment="E3", dataset=ds, variant=v)


def e4(d, ds, v, cache="warm", col="t_total"):
    return med(d, cache, col, experiment="E4", dataset=ds, variant=v)


# ---------------------------------------------------------------- tables
def headline(d):
    rows = []
    for ds in GRIDS:
        g, c, w = e1(d, ds, "slope", "Horn"), e3(d, ds, "engine_perf_slope"), e4(d, ds, "gpu_slope")
        rows.append({"grid": LABEL[ds], "gdaldem s": g, "CPU engine (12 P-thr) s": c, "GPU engine s": w,
                     "GPU cold s": e4(d, ds, "gpu_slope", "cold"), "GPU, 8 readers s": e4(d, ds, "gpu_slope_r8"),
                     "GPU, no write s": e4(d, ds, "gpu_slope_nowrite"), "GPU vs CPU engine": c / w,
                     "GPU vs gdaldem": g / w, "GPU peak RAM MiB": e4(d, ds, "gpu_slope", None, "peak_rss_mb"),
                     "GPU peak VRAM MiB": e4(d, ds, "gpu_slope", None, "peak_vram_mb")})
    return pd.DataFrame(rows)


def ladder(d):
    rows = []
    for ds in GRIDS:
        for v, name in LADDER:
            t = e4(d, ds, v)
            if np.isnan(t):
                continue
            rows.append({"grid": LABEL[ds], "version": name, "total s": t,
                         "wait for read s": e4(d, ds, v, col="read"), "GPU part (main thread) s": e4(d, ds, v, col="compute"),
                         "copy to GPU s": e4(d, ds, v, col="gpu_h2d"), "kernel s": e4(d, ds, v, col="gpu_kernel"),
                         "copy back s": e4(d, ds, v, col="gpu_d2h"), "wait for writer s": e4(d, ds, v, col="write")})
    return pd.DataFrame(rows)


def stages(d):
    rows = []
    for ds in GRIDS:
        for v in ("gpu_slope", "gpu_slope_nowrite", "gpu_3prod"):
            q = d[(d.experiment == "E4") & (d.dataset == ds) & (d.variant == v) & d.ok & (d.rep >= 1) &
                  (d.cache_state == "warm")]
            if q.empty:
                continue
            m = q[list(KEYS) + ["t_total", "proc_write_mb"]].median()
            rows.append({"grid": LABEL[ds], "variant": v, "total s": m.t_total, "python start-up s": m.t_imports,
                         "GPU init s": m.gpu_init, "wait for read s": m.read, "GPU part s": m.compute,
                         "of which: copy in / kernel / copy out s": f"{m.gpu_h2d:.2f} / {m.gpu_kernel:.3f} / {m.gpu_d2h:.2f}",
                         "wait for writer s": m.write, "writer busy s": m.writer_busy, "written GB": m.proc_write_mb * 2**20 / 1e9})
    return pd.DataFrame(rows)


def operators(d):
    rows = []
    for ds in GRIDS:
        for op, m, cv in CONFIGS:
            gv = GPU_OP.get(cv, cv.replace("engine_all_", "gpu_"))
            g, c, w = e1(d, ds, op, m), e3(d, ds, cv), e4(d, ds, gv)
            if np.isnan(w):
                continue
            rows.append({"grid": LABEL[ds], "operator": f"{op} {m}".strip(), "gdaldem s": g,
                         "CPU engine (22 thr) s": c, "GPU engine s": w, "GPU vs gdaldem": g / w,
                         "GPU vs CPU engine": c / w})
    return pd.DataFrame(rows)


def products(d):
    rows = []
    for ds in GRIDS:
        g = [e1(d, ds, op, "Horn") for op in ("slope", "aspect", "hillshade")]
        w = e4(d, ds, "gpu_3prod")
        if np.isnan(w):
            continue
        rows.append({"grid": LABEL[ds], "gdaldem 3 runs s": sum(g) if not any(np.isnan(g)) else np.nan,
                     "CPU engine fused s": e3(d, ds, "engine_all_3prod"), "GPU engine fused s": w,
                     "GPU writer busy s": e4(d, ds, "gpu_3prod", col="writer_busy"),
                     "written GB": e4(d, ds, "gpu_3prod", col="proc_write_mb") * 2**20 / 1e9})
    return pd.DataFrame(rows)


def windows_table(d):
    rows = []
    for ds in GRIDS:
        for n in (1024, 2048, 4096, 8192):
            v = "gpu_slope" if n == 2048 else f"gpu_window_{n}"
            t = e4(d, ds, v)
            if np.isnan(t):
                continue
            rows.append({"grid": LABEL[ds], "window": n, "warm s": t, "cold s": e4(d, ds, v, "cold"),
                         "wait for read s": e4(d, ds, v, col="read"), "peak RAM MiB": e4(d, ds, v, None, "peak_rss_mb"),
                         "peak VRAM MiB": e4(d, ds, v, None, "peak_vram_mb")})
    return pd.DataFrame(rows)


def crossover():
    p = RES / "e4_crossover.csv"
    if not p.exists():
        return pd.DataFrame()
    c = pd.read_csv(p)
    t = c.pivot_table(index=["ops", "window"], columns="version", values="median_s").reset_index()
    t.columns.name = None
    for col in ("cpu_numba", "gpu_kernel", "gpu_kernel_fp64", "gpu_e2e_pinned", "gpu_e2e_pageable"):
        t[col] = t[col] * 1e3
    t["GPU (with copies) vs CPU"] = t.cpu_numba / t.gpu_e2e_pinned
    t["copies share of GPU time"] = 1 - t.gpu_kernel / t.gpu_e2e_pinned
    return t.rename(columns={"cpu_numba": "CPU ms", "gpu_kernel": "GPU kernel ms", "gpu_kernel_fp64": "GPU kernel fp64 ms",
                             "gpu_e2e_pinned": "GPU incl. copies ms", "gpu_e2e_pageable": "GPU incl. pageable copies ms"})


def safety(d):
    q = d[d.experiment == "E4"]
    return pd.DataFrame([{"E4 runs": len(q), "failed": int((~q.ok).sum()),
                          "max GPU temp before a run C": q.gpu_temp_before.max(),
                          "max GPU temp after a run C": q.gpu_temp_after.max(),
                          "median GPU temp after a run C": q.gpu_temp_after.median(),
                          "max VRAM used by our pool MiB": q.peak_vram_mb.max()}])


# ---------------------------------------------------------------- charts
def chart_scaling(d):
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    cells = {ds: d[d.dataset == ds].cells.iloc[0] for ds in GRIDS if (d.dataset == ds).any()}
    series = [("gdaldem", lambda ds: e1(d, ds, "slope", "Horn"), "o", "-"),
              ("CPU engine, 12 threads", lambda ds: e3(d, ds, "engine_perf_slope"), "s", "-"),
              ("GPU engine", lambda ds: e4(d, ds, "gpu_slope"), "D", "-"),
              ("GPU engine, no output written", lambda ds: e4(d, ds, "gpu_slope_nowrite"), "^", "--")]
    for i, (name, f, mk, ls) in enumerate(series):
        xs = [(cells[ds], f(ds)) for ds in GRIDS if ds in cells and not np.isnan(f(ds))]
        if xs:
            x, y = zip(*xs)
            ax.plot(x, y, marker=mk, ls=ls, color=S[i], label=name)
            label_end(ax, x[-1], y[-1], f"{y[-1]:.0f} s", dy={0: 6, 1: 6, 2: -2, 3: -9}[i])
    ax.set_xscale("log"), ax.set_yscale("log")
    ax.set_xlabel("grid cells"), ax.set_ylabel("time, warm cache (s)")
    ax.set_title("E4: slope on the GPU vs the CPU engine and gdaldem")
    ax.legend(loc="upper left")
    fig.savefig(PLOTS / "e4_scaling.png"), plt.close(fig)


def chart_ladder(lad, d):
    ds = "tile571_2m_cubic"
    q = lad[lad.grid == LABEL[ds]]
    if q.empty:
        return
    fig, ax = plt.subplots(figsize=(7.6, 4.0))
    names = ["CPU engine (E3), 12 threads"] + list(q.version)
    vals = [e3(d, ds, "engine_perf_slope")] + list(q["total s"])
    y = np.arange(len(names))[::-1]
    ax.barh(y, vals, color=[S[1]] + [S[2]] * len(q), height=0.6)
    for yi, v in zip(y, vals):
        ax.annotate(f"{v:.1f} s", (v, yi), xytext=(4, 0), textcoords="offset points", va="center", fontsize=8,
                    color=INK2)
    ax.set_yticks(y, names)
    ax.set_xlabel("slope, whole grid, warm (s)")
    ax.set_title(f"E4: GPU versions, {LABEL[ds]} (2.7 B cells)")
    fig.savefig(PLOTS / "e4_ladder.png"), plt.close(fig)


def chart_crossover():
    p = RES / "e4_crossover.csv"
    if not p.exists():
        return
    c = pd.read_csv(p)
    c = c[c.ops == "slope"]
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    for i, (v, name, ls) in enumerate([("cpu_numba", "CPU kernel, 12 threads", "-"),
                                       ("gpu_e2e_pageable", "GPU incl. copies (pageable)", ":"),
                                       ("gpu_e2e_pinned", "GPU incl. copies (pinned)", "-"),
                                       ("gpu_kernel_fp64", "GPU kernel only, float64", "--"),
                                       ("gpu_kernel", "GPU kernel only", "--")]):
        q = c[c.version == v].sort_values("window")
        ax.plot(q.cells, q.median_s * 1e3, marker="o", ls=ls, color=S[i], label=name)
    ax.set_xscale("log"), ax.set_yscale("log")
    ws = sorted(c.window.unique())
    ax.set_xticks([w * w for w in ws], [f"{w}²" for w in ws])
    ax.axhline(16.7, color=AXIS, lw=1)
    ax.annotate("one frame at 60 fps", (ws[-1] ** 2, 16.7), xytext=(0, 3), textcoords="offset points", color=INK2,
                fontsize=8, ha="right")
    ax.set_xlabel("window (cells)"), ax.set_ylabel("time per window (ms)")
    ax.set_title("E4: when is the GPU worth it? (slope, data in RAM)")
    ax.legend(loc="lower right", fontsize=8)
    fig.savefig(PLOTS / "e4_crossover.png"), plt.close(fig)


STAGE_COLORS = {"start-up": "#c3c2b7", "read + decompress / wait for input": S[0], "compute (CPU)": S[1],
                "GPU copies": S[3], "GPU kernel": S[2], "write / wait for output": S[4],
                "other (process start, library imports, closing files)": "#e1e0d9"}


def stage_rows(d):
    """Seconds per stage (warm, slope Horn) for gdaldem, the CPU engine (12 threads) and the GPU engine.
    gdaldem: E1 stage split (read / write / compute from the read and copy references). Engines: how the main
    thread spends the run (start-up, waiting for input, computing or driving the GPU, waiting for the writer);
    the GPU part is split into copies and kernel in proportion to their CUDA-event times."""
    from bench.analysis import phase2_report
    e1 = phase2_report.e1_stage_split(phase2_report.load()).set_index("grid")
    rows = []
    for ds in GRIDS:
        g = LABEL[ds]
        if g in e1.index:
            r = e1.loc[g]
            rows.append({"grid": g, "tool": "gdaldem", "read + decompress / wait for input": r["read"],
                         "compute (CPU)": r["compute"], "write / wait for output": r["write + tool overhead"]})
        for tool, exp, v in (("CPU engine", "E3", "engine_perf_slope"), ("GPU engine", "E4", "gpu_slope")):
            q = d[(d.experiment == exp) & (d.dataset == ds) & (d.variant == v) & d.ok & (d.rep >= 1) &
                  (d.cache_state == "warm")]
            if q.empty:
                continue
            m = q[["t_total", "t_imports", "gpu_init", "read", "compute", "write", "gpu_h2d", "gpu_kernel",
                   "gpu_d2h"]].median()
            row = {"grid": g, "tool": tool, "start-up": m.t_imports + (m.gpu_init if exp == "E4" else 0),
                   "read + decompress / wait for input": m.read, "write / wait for output": m.write}
            if exp == "E4":
                ev = m.gpu_h2d + m.gpu_kernel + m.gpu_d2h
                row["GPU copies"] = m.compute * (m.gpu_h2d + m.gpu_d2h) / ev
                row["GPU kernel"] = m.compute * m.gpu_kernel / ev
            else:
                row["compute (CPU)"] = m.compute
            row["other (process start, library imports, closing files)"] = max(m.t_total - sum(v for k, v in row.items() if k not in ("grid", "tool")), 0)
            rows.append(row)
    return pd.DataFrame(rows).fillna(0)


def chart_stages(st):
    if st.empty:
        return
    grids = list(dict.fromkeys(st.grid))
    fig, axes = plt.subplots(len(grids), 1, figsize=(8.4, 1.45 * len(grids) + 1.0), squeeze=False)
    for ax, g in zip(axes[:, 0], grids):
        q = st[st.grid == g].iloc[::-1]
        y = np.arange(len(q))
        left = np.zeros(len(q))
        for stage, color in STAGE_COLORS.items():
            if stage in q:
                vals = q[stage].to_numpy()
                ax.barh(y, vals, left=left, color=color, height=0.62, edgecolor="#fcfcfb", linewidth=1,
                        label=stage if g == grids[0] else None)
                left += vals
        for yi, tot in zip(y, left):
            ax.annotate(f"{tot:.1f} s", (tot, yi), xytext=(4, 0), textcoords="offset points", va="center",
                        fontsize=8, color=INK2)
        ax.set_yticks(y, q.tool)
        ax.set_xlim(0, left.max() * 1.12)
        ax.set_title(g, fontsize=10)
        ax.grid(axis="y", visible=False)
    axes[-1, 0].set_xlabel("seconds (slope, warm cache); each panel has its own scale")
    fig.legend(loc="lower center", ncol=4, fontsize=8, frameon=False, bbox_to_anchor=(0.5, -0.01))
    fig.suptitle("Where the time goes: gdaldem vs our CPU and GPU engines", x=0.01, ha="left", fontsize=12,
                 fontweight="bold")
    fig.tight_layout(rect=(0, 0.06, 1, 0.97))
    fig.savefig(PLOTS / "e4_stages.png"), plt.close(fig)


def main():
    d = load()
    h, lad, st, o, p, w, c, s = (headline(d), ladder(d), stages(d), operators(d), products(d), windows_table(d),
                                 crossover(), safety(d))
    PLOTS.mkdir(parents=True, exist_ok=True)
    sr = stage_rows(d)
    chart_scaling(d), chart_ladder(lad, d), chart_crossover(), chart_stages(sr)
    out = ["# E4 (GPU) result tables", "",
           "Generated by `python -m bench.analysis.e4_report` from `results/runs.csv` and `results/e4_crossover.csv`. "
           "Medians over measured repeats, warm cache unless stated. GPU runs pinned to the 12 performance-core "
           "threads; times include Python start-up and GPU initialisation.", "",
           "## Slope: GPU vs CPU engine vs gdaldem", "", md_table(h), "",
           "## GPU versions (optimisation ladder, slope)", "", md_table(lad), "",
           "## Where the GPU engine's time goes", "", md_table(st), "",
           "## Stage split: gdaldem vs CPU engine vs GPU engine (slope, warm, seconds)", "", md_table(sr), "",
           "## Every gdaldem configuration", "", md_table(o), "",
           "## Slope + aspect + hillshade in one pass", "", md_table(p), "",
           "## Window size (GPU, slope)", "", md_table(w), "",
           "## Crossover: one window, data in RAM (ms per window)", "", md_table(c) if not c.empty else "(not run)", "",
           "## GPU safety record", "", md_table(s), ""]
    (RES / "e4_tables.md").write_text("\n".join(out), encoding="utf-8")
    print("wrote", RES / "e4_tables.md", sorted(q.name for q in PLOTS.glob("e4_*.png")))


if __name__ == "__main__":
    main()
