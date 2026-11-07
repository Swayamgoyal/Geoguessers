"""E6 (interactive viewing) analysis: tables (results/e6_tables.md) and charts (results/plots/e6_*.png).

Inputs, all written by bench/experiments/e6_view.py: results/runs.csv (experiment E6; metrics in `extra`),
e6_gestures.csv, e6_frames.csv, e6_memory.csv. Values are medians over the 5 measured runs, with the interquartile
range in brackets where it matters.

    python -m bench.analysis.e6_report [--results DIR]
"""
import argparse
import json

import numpy as np
import pandas as pd

import bench.analysis.phase2_report as p2
from bench.analysis.phase2_report import AXIS, INK2, MUTED, S, label_end, md_table, plt

RES, PLOTS = p2.RES, p2.PLOTS
PAN = ["pan-line-0.5", "pan-line-1", "pan-line-2", "pan-reverse-0.5", "pan-reverse-1", "pan-reverse-2", "pan-walk"]
BURSTS = ["zoom-burst-in-0.3", "zoom-burst-out-0.3", "zoom-burst-in-1", "zoom-burst-out-1", "zoom-burst-in-2",
          "zoom-burst-out-2"]
DEBOUNCE = [("debounce-off", "off"), ("debounce-100", "100"), ("debounce-150", "150"), ("base", "200"),
            ("debounce-250", "250"), ("maxwait-500", "200 + max 500")]


def load_runs():
    d = pd.read_csv(RES / "runs.csv", low_memory=False)
    d = d[(d.experiment == "E6") & (d.ok.astype(str) == "True") & (d.rep >= 1)].copy()
    ex = pd.json_normalize(d.extra.map(json.loads).tolist(), sep=".")
    ex.index = d.index
    d = pd.concat([d.drop(columns=["extra"]), ex], axis=1)
    d["server_fg_tiles"] = d["fg_completed"] + d["fg_cancelled_running"]
    d["server_bg_tiles"] = d["bg_completed"] + d["bg_cancelled_running"]
    tier_cols = [c for c in d.columns if c.startswith("tiers.")]
    tot = d[tier_cols].fillna(0).sum(axis=1).replace(0, np.nan)
    for c in tier_cols:
        d["share_" + c.split(".", 1)[1]] = d[c].fillna(0) / tot
    return d


def med(q, col):
    v = pd.to_numeric(q[col], errors="coerce").dropna() if col in q else pd.Series(dtype=float)
    return v.median() if len(v) else np.nan


def mi(q, col, fmt="{:.0f}"):
    """'median [q1-q3]' over runs."""
    v = pd.to_numeric(q[col], errors="coerce").dropna() if col in q else pd.Series(dtype=float)
    if v.empty:
        return ""
    a, b, c = v.quantile([0.25, 0.5, 0.75])
    return f"{fmt.format(b)} [{fmt.format(a)}-{fmt.format(c)}]"


def sel(d, config, traces=None):
    q = d[d.config == config]
    return q if traces is None else q[q.trace.isin(traces)]


# ---------------------------------------------------------------- tables
def base_table(d):
    rows = []
    for tr, q in sel(d, "base").groupby("trace", sort=False):
        rows.append({"trace": tr, "runs": len(q), "fg requests": mi(q, "fg_requests"),
                     "fg p50 ms": mi(q, "fg_p50_ms"), "fg p95 ms": mi(q, "fg_p95_ms"),
                     "server fg p95 ms": mi(q, "fg_server_p95_ms"), "prefetched tiles": mi(q, "bg_ok"),
                     "pan hit rate": mi(q, "pan_hit_rate", "{:.2f}"), "blank area-time": mi(q, "blank_area_time", "{:.2f}"),
                     "TTFF ms": mi(q, "ttff_ms_median"), "complete ms": mi(q, "complete_ms_median"),
                     "prefetch precision": mi(q, "prefetch_precision", "{:.2f}"),
                     "server fg tiles / zoom gesture": mi(q, "server_fg_tiles_per_wheel_gesture", "{:.1f}"),
                     "server peak RSS MiB": mi(q, "rss_peak_mb")})
    order = {t: i for i, t in enumerate(PAN + BURSTS + ["zoom-pan", "box"])}
    return pd.DataFrame(rows).sort_values("trace", key=lambda s: s.map(order)).reset_index(drop=True)


def interference(d):
    """Gate 1: foreground latency with prefetch on (base) vs off, per trace (median of 5 runs)."""
    rows = []
    for tr in PAN + ["zoom-pan"]:
        on, off = sel(d, "base", [tr]), sel(d, "prefetch-off", [tr])
        if on.empty or off.empty:
            continue
        r = {"trace": tr}
        for name, q in (("on", on), ("off", off)):
            r[f"fg p95 ms, prefetch {name}"] = med(q, "fg_p95_ms")
            r[f"server fg p95 ms, prefetch {name}"] = med(q, "fg_server_p95_ms")
            r[f"fg requests, prefetch {name}"] = med(q, "fg_requests")
        r["server p95 on / off"] = r["server fg p95 ms, prefetch on"] / r["server fg p95 ms, prefetch off"]
        rows.append(r)
    t = pd.DataFrame(rows)
    if not t.empty:
        allon = sel(d, "base", PAN + ["zoom-pan"])
        alloff = sel(d, "prefetch-off", PAN + ["zoom-pan"])
        t.loc[len(t)] = {"trace": "all pan traces + zoom-pan (pooled runs)",
                         "fg p95 ms, prefetch on": med(allon, "fg_p95_ms"),
                         "fg p95 ms, prefetch off": med(alloff, "fg_p95_ms"),
                         "server fg p95 ms, prefetch on": med(allon, "fg_server_p95_ms"),
                         "server fg p95 ms, prefetch off": med(alloff, "fg_server_p95_ms"),
                         "fg requests, prefetch on": med(allon, "fg_requests"),
                         "fg requests, prefetch off": med(alloff, "fg_requests"),
                         "server p95 on / off": med(allon, "fg_server_p95_ms") / med(alloff, "fg_server_p95_ms")}
    return t


def debounce(d, traces):
    """Gate 2: server tiles and time to first frame per zoom gesture against the debounce."""
    rows = []
    for cfg, label in DEBOUNCE:
        q = sel(d, cfg, traces)
        if q.empty:
            continue
        deb = {"off": 0, "200 + max 500": 200}.get(label, None)
        deb = int(label) if deb is None else deb
        rows.append({"debounce ms": label, "runs": len(q), "commits per run": mi(q, "commits"),
                     "server fg tiles / gesture": med(q, "server_fg_tiles_per_wheel_gesture"),
                     "client fg requests / gesture": med(q, "fg_per_wheel_gesture"),
                     "fg cancelled on server / run": med(q, "fg_cancelled_running") + med(q, "fg_cancelled_queued"),
                     "TTFF ms": med(q, "ttff_ms_median"), "TTFF - debounce ms": med(q, "ttff_ms_median") - deb,
                     "complete ms": med(q, "complete_ms_median"), "blank area-time": med(q, "blank_area_time")})
    return pd.DataFrame(rows)


def compare(d, configs, traces, cols):
    rows = []
    for cfg in configs:
        q = sel(d, cfg, traces)
        if q.empty:
            continue
        r = {"configuration": cfg, "runs": len(q)}
        for label, col, fmt in cols:
            r[label] = mi(q, col, fmt)
        rows.append(r)
    return pd.DataFrame(rows)


PREFETCH_COLS = [("fg requests", "fg_requests", "{:.0f}"), ("pan hit rate", "pan_hit_rate", "{:.2f}"),
                 ("blank area-time", "blank_area_time", "{:.3f}"), ("prefetched", "bg_ok", "{:.0f}"),
                 ("precision", "prefetch_precision", "{:.2f}"), ("recall of misses", "prefetch_recall", "{:.2f}"),
                 ("fg p95 ms", "fg_p95_ms", "{:.0f}"), ("server fg p95 ms", "fg_server_p95_ms", "{:.0f}"),
                 ("back-offs", "prefetch_backoffs", "{:.0f}")]
SERVER_COLS = [("fg p95 ms", "fg_p95_ms", "{:.0f}"), ("server fg p95 ms", "fg_server_p95_ms", "{:.0f}"),
               ("complete ms", "complete_ms_median", "{:.0f}"), ("pan hit rate", "pan_hit_rate", "{:.2f}"),
               ("prefetched", "bg_ok", "{:.0f}"), ("fg CPU s", "cpu_s.fg", "{:.2f}"),
               ("bg CPU s", "cpu_s.bg", "{:.2f}"), ("blocks decoded", "blocks_decoded", "{:.0f}"),
               ("peak RSS MiB", "rss_peak_mb", "{:.0f}")]
WORK_COLS = [("fg p95 ms", "fg_p95_ms", "{:.0f}"), ("server fg p95 ms", "fg_server_p95_ms", "{:.0f}"),
             ("TTFF ms", "ttff_ms_median", "{:.0f}"), ("complete ms", "complete_ms_median", "{:.0f}"),
             ("blank area-time", "blank_area_time", "{:.3f}"), ("fg CPU s", "cpu_s.fg", "{:.2f}"),
             ("blocks decoded", "blocks_decoded", "{:.0f}"), ("cold-tier share", "share_cold", "{:.2f}"),
             ("result-tier share", "share_result", "{:.2f}"), ("peak RSS MiB", "rss_peak_mb", "{:.0f}")]


def hit_by_speed(d, configs):
    rows = []
    for cfg in configs:
        for fam in ("pan-line", "pan-reverse"):
            for sp in ("0.5", "1", "2"):
                q = sel(d, cfg, [f"{fam}-{sp}"])
                if q.empty:
                    continue
                rows.append({"configuration": cfg, "trace family": fam, "speed (views/s)": float(sp),
                             "pan hit rate": med(q, "pan_hit_rate"), "blank area-time": med(q, "blank_area_time"),
                             "fg requests": med(q, "fg_requests"), "precision": med(q, "prefetch_precision")})
    return pd.DataFrame(rows)


def pinning(d):
    """Where jobs ran (logical CPU class at the end of each job), summed over all E6 runs per placement."""
    rows = []
    for shared, q in d.groupby(d.config == "bg-shared-pcores"):
        r = {"background placement": "performance cores (shared, yielding)" if shared else "efficiency cores"}
        for pool in ("fg", "bg"):
            for cls in ("P", "E", "LP", "other"):
                col = f"ran_on_class.{pool}.{cls}"
                r[f"{pool} jobs on {cls}"] = int(q[col].fillna(0).sum()) if col in q else 0
        r["bg CPU s (all runs)"] = q["cpu_s.bg"].sum()
        r["fg CPU s (all runs)"] = q["cpu_s.fg"].sum()
        rows.append(r)
    return pd.DataFrame(rows)


def gestures_table(g):
    if g.empty:
        return pd.DataFrame()
    q = g[g.config.isin([c for c, _ in DEBOUNCE]) & g.trace.isin(BURSTS)]
    t = q.groupby(["config", "trace"]).agg(ttff_ms=("ttff_ms", "median"), complete_ms=("complete_ms", "median"),
                                           fg_requested=("fg_requested", "median")).reset_index()
    return t.pivot_table(index="trace", columns="config", values="fg_requested").reset_index()


# ---------------------------------------------------------------- charts
def chart_hit_speed(hs):
    if hs.empty:
        return
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    labels = {"prefetch-off": "prefetch off", "base": "prefetch on (defaults)",
              "prefetch-no-backoff": "prefetch on, no back-off", "ring-fixed-order": "ring in fixed order"}
    q = hs[hs["trace family"] == "pan-line"]
    for i, (cfg, lab) in enumerate(labels.items()):
        r = q[q.configuration == cfg].sort_values("speed (views/s)")
        if r.empty:
            continue
        ax.plot(r["speed (views/s)"], r["pan hit rate"], marker="o", color=S[i], label=lab)
        label_end(ax, r["speed (views/s)"].iloc[-1], r["pan hit rate"].iloc[-1], lab, dy=[-6, 6, 0, -12][i])
    ax.set_xlabel("pan speed (view widths per second)")
    ax.set_ylabel("tiles already in the browser cache when they enter the view")
    ax.set_ylim(0, 1.05)
    ax.set_xticks([0.5, 1, 2])
    ax.set_xlim(0.4, 2.9)
    ax.set_title("Pan hit rate against pan speed (pan-line, median of 5 runs)")
    ax.legend(loc="lower left")
    fig.savefig(PLOTS / "e6_hit_vs_speed.png"), plt.close(fig)


def chart_debounce(t2):
    if t2.empty:
        return
    t2 = t2[t2["debounce ms"] != "200 + max 500"]
    x = np.arange(len(t2))
    fig, axes = plt.subplots(1, 2, figsize=(9.6, 3.9))
    axes[0].bar(x, t2["server fg tiles / gesture"], color=S[0], width=0.6)
    axes[0].set_title("Foreground tiles the server renders per gesture")
    axes[0].set_ylabel("tiles per zoom gesture")
    axes[1].bar(x, t2["TTFF ms"], color=S[0], width=0.6)
    axes[1].set_title("Last wheel tick to first exact tile")
    axes[1].set_ylabel("ms")
    for ax in axes:
        ax.set_xticks(x, t2["debounce ms"])
        ax.set_xlabel("debounce (ms)")
        ax.grid(axis="x", visible=False)
    for i, v in enumerate(t2["server fg tiles / gesture"]):
        axes[0].annotate(f"{v:.0f}", (i, v), xytext=(0, 3), textcoords="offset points", ha="center", color=INK2,
                         fontsize=9)
    for i, v in enumerate(t2["TTFF ms"]):
        axes[1].annotate(f"{v:.0f}", (i, v), xytext=(0, 3), textcoords="offset points", ha="center", color=INK2,
                         fontsize=9)
    fig.suptitle("Zoom bursts (0.3 / 1 / 2 s, in and out), median of 5 runs", x=0.01, ha="left", color=MUTED,
                 fontsize=9, y=0.02)
    fig.tight_layout()
    fig.savefig(PLOTS / "e6_debounce.png"), plt.close(fig)


def chart_fg_p95(d):
    cfgs = [("prefetch-off", "prefetch off"), ("base", "defaults (E-cores, yield)"),
            ("prefetch-no-backoff", "no client back-off"), ("bg-no-yield", "E-cores, no yield"),
            ("bg-shared-pcores", "P-cores, yield")]
    rows = [(lab, med(sel(d, c, PAN + ["zoom-pan"]), "fg_server_p95_ms"),
             med(sel(d, c, PAN + ["zoom-pan"]), "fg_p95_ms")) for c, lab in cfgs if not sel(d, c).empty]
    if not rows:
        return
    labs, srv, cli = zip(*rows)
    y = np.arange(len(labs))
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    ax.barh(y - 0.19, srv, height=0.36, color=S[0], label="on the server (queue + render)")
    ax.barh(y + 0.19, cli, height=0.36, color=S[1], label="at the client (adds waiting for 1 of 6 connections)")
    for yy, a, b in zip(y, srv, cli):
        ax.annotate(f"{a:.0f}", (a, yy - 0.19), xytext=(3, 0), textcoords="offset points", va="center",
                    color=INK2, fontsize=9)
        ax.annotate(f"{b:.0f}", (b, yy + 0.19), xytext=(3, 0), textcoords="offset points", va="center",
                    color=INK2, fontsize=9)
    ax.set_yticks(y, labs)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("foreground tile latency p95 (ms), pan traces + zoom-pan, median of runs")
    ax.set_title("Foreground latency by prefetch configuration")
    ax.legend(loc="lower right", fontsize=8)
    fig.savefig(PLOTS / "e6_fg_p95.png"), plt.close(fig)


def chart_memory(mem):
    if mem.empty:
        return
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    shown = [("base", "defaults (1024 MiB block cache)"), ("block-cache-256", "256 MiB block cache"),
             ("block-cache-0", "no block cache")]
    for i, (cfg, lab) in enumerate(shown):
        q = mem[(mem.config == cfg) & (mem.trace == "zoom-pan")]
        if q.empty:
            continue
        ax.plot(q.t, q.rss_mb, color=S[i], lw=1.5, label=lab)
    ax.set_xlabel("seconds into the zoom-pan trace")
    ax.set_ylabel("server resident memory (MiB)")
    ax.set_ylim(bottom=0)
    ax.set_title("Server memory during zoom-pan (rep 1)")
    ax.legend(loc="lower right")
    fig.savefig(PLOTS / "e6_memory.png"), plt.close(fig)


def chart_timeline(fr, g):
    q = fr[(fr.config == "base") & (fr.trace == "zoom-pan")]
    if q.empty:
        return
    run = q.run_id.iloc[0]
    q = q[q.run_id == run]
    fig, ax = plt.subplots(figsize=(8.4, 3.4))
    ax.fill_between(q.t, 0, q.exact_share, color=S[0], lw=0, step="post", label="exact tile of the needed level")
    ax.fill_between(q.t, q.exact_share, q.exact_share + q.fallback_share, color="#a9c8ee", lw=0, step="post",
                    label="preview from another cached level")
    gq = g[(g.run_id == run)] if not g.empty else g
    for _, r in gq.iterrows():
        ax.axvspan(r.t_first, r.t_last, color=AXIS, alpha=0.35, lw=0)
    ax.set_ylim(0, 1.02)
    ax.set_xlim(q.t.min(), q.t.max())
    ax.set_xlabel("seconds (grey bands: wheel bursts; the rest is panning)")
    ax.set_ylabel("share of the view")
    ax.set_title("What the viewer draws during zoom-pan (defaults, rep 1, 60 Hz frames)")
    ax.legend(loc="lower left", fontsize=8)
    fig.savefig(PLOTS / "e6_timeline.png"), plt.close(fig)


def main():
    global RES, PLOTS
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=None)
    a = ap.parse_args()
    if a.results:
        from pathlib import Path
        RES = Path(a.results)
        PLOTS = RES / "plots"
        p2.RES, p2.PLOTS = RES, PLOTS
    PLOTS.mkdir(parents=True, exist_ok=True)
    d = load_runs()
    rd = lambda n: pd.read_csv(RES / n) if (RES / n).exists() else pd.DataFrame()  # noqa: E731
    g, fr, mem = rd("e6_gestures.csv"), rd("e6_frames.csv"), rd("e6_memory.csv")
    t_base, t_int = base_table(d), interference(d)
    t_deb = debounce(d, BURSTS)
    t_deb_zp = debounce(d, ["zoom-pan"])
    hs = hit_by_speed(d, ["prefetch-off", "base", "prefetch-no-backoff", "backoff-100", "ring-fixed-order"])
    chart_hit_speed(hs), chart_debounce(t_deb), chart_fg_p95(d), chart_memory(mem), chart_timeline(fr, g)
    pf = ["prefetch-off", "base", "backoff-100", "prefetch-no-backoff", "ring-fixed-order"]
    place = ["base", "bg-no-yield", "bg-shared-pcores", "bg-workers-2", "bg-workers-4"]
    work = ["base", "fg-workers-4", "fg-workers-6", "block-cache-0", "block-cache-256", "result-cache-off",
            "op-slope", "op-aspect", "mode-precomputed", "tile571-8m", "cold"]
    mix = ["pan-walk", "zoom-pan", "zoom-burst-in-1", "zoom-burst-out-1", "box"]
    out = ["# E6 (interactive viewing) result tables", "",
           "Generated by `python -m bench.analysis.e6_report` from `bench/experiments/e6_view.py` runs: virtual client "
           "(the viewer's policy in Python) replaying seeded traces against a fresh tile server per run, 1 warm-up + 5 "
           "measured runs per configuration and trace. Cells show median [interquartile range] over runs unless "
           "a single number. fg = foreground (visible tiles), bg = prefetch. Client latency includes waiting for one "
           "of the browser's 6 connections; server latency is queue + render from `Server-Timing`.", "",
           "## Defaults, every trace", "", md_table(t_base), "",
           "## Gate 1: prefetch must not raise foreground p95 by more than 10%", "", md_table(t_int, 1), "",
           "## Gate 2: debounce, zoom bursts (all six)", "", md_table(t_deb, 1), "",
           "## Debounce, zoom-pan", "", md_table(t_deb_zp, 1), "",
           "## Client foreground requests per burst trace, by debounce", "", md_table(gestures_table(g), 1), "",
           "## Prefetch policy, pan traces + zoom-pan", "", md_table(compare(d, pf, PAN + ["zoom-pan"], PREFETCH_COLS)), "",
           "## Hit rate against pan speed", "", md_table(hs, 2), "",
           "## Background placement and pool sizes, pan traces + zoom-pan", "",
           md_table(compare(d, place, PAN + ["zoom-pan"], SERVER_COLS)), "",
           "## Workers, caches, product, mode, dataset, OS cache (mixed traces)", "",
           md_table(compare(d, work, mix, WORK_COLS)), "",
           "## Where jobs ran (core class at the end of each job, all runs)", "", md_table(pinning(d), 1), ""]
    (RES / "e6_tables.md").write_text("\n".join(out), encoding="utf-8")
    print("wrote", RES / "e6_tables.md", sorted(p.name for p in PLOTS.glob("e6_*.png")))


if __name__ == "__main__":
    main()
