# Final presentation

`main.pdf` is a Beamer deck: 16:9, 21 slides, using the team draft's navy and orange style. It is built from the
team's draft, with these additions:
- a chart or picture on every result slide;
- the web viewer (E6) results;
- live-demo slides;
- the Swiss Alps validation;
- numbers checked against the reports and logs.

Build (MiKTeX or TeX Live), twice:
```
cd report/presentation
pdflatex main.tex
pdflatex main.tex
```
Figures come from `results/plots/`, `report/figures/`, `report/demo/`, `logs/qgis_session/charts/` and `figures/`
(three viewer stills taken from the demo video, and a CPU and memory chart of Swiss run 4 drawn from
`logs/qgis_session/`: tile server and browser CPU only, because an unrelated background application inflated the
whole-machine CPU during that run).

## Slide order

| # | Slides | Part |
|---|---|---|
| 1–2 | Title; the problem and the three questions | Motivation |
| 3 | What we changed, and why (baseline finding → change) | Method |
| 4 | Baseline: gdaldem slows down, one thread computing | E1 |
| 5 | Baseline: for display the pyramid is everything; ZSTD storage | E1 display, E2 |
| 6 | CPU engine: parallel, flat memory, exact; three products in one pass | E3 |
| 7 | GPU engine: fast kernel, small overall gain | E4 |
| 8 | The bottleneck moves, so compute only what is seen | E3, E4 |
| 9–10 | On demand from the pyramid, accuracy vs speed | E5 |
| 11–13 | End-to-end system, debounce, prefetch | Viewer (E6) |
| 14–15 | **Live demo**: web viewer, then QGIS plugin (orange "LIVE" boxes give the commands) | Demo |
| 16–17 | Swiss Alps validation (2.85 B cells), where Exact mode breaks | Validation |
| 18–21 | Summary table, conclusion, limitations and future work, thank you | Wrap-up |

The introduction, baseline and engine part takes 8 slides, because it was covered in the mid presentation. Each slide
has one chart, its key numbers and a one-line takeaway; charts that repeat a message shown elsewhere (E1 stages,
E2 storage, E3 scaling, E3 threads) are left out.

**Before the talk:**
1. Start `python -m server`.
2. Open `http://127.0.0.1:8765/viewer/` once, so the first tiles are cached.
3. Open QGIS with the plugin connected.

The demo video `report/demo/geoguessers_demo.mp4` stays as a fallback if the live run fails.

## Corrections to the team draft

| Draft said | Measured | Source |
|---|---|---|
| Scheduler: 12 P-threads foreground, 8 E-threads prefetch | 8 foreground workers on the P-core threads, 3 prefetch workers on the E-cores | `docs/PHASE5_RESULTS.md`, server defaults |
| Stale jobs abort in < 37 ms | Aborted requests dropped in a **median** 37 ms | `docs/PHASE5_RESULTS.md` |
| Block cache: 5.7× fewer disk decodes | Without the block cache: 6× more decodes and p95 +40% | final report, E6 |
| Aspect median error < 6° | 2–8° (1.8° at 4 m … 8.5° at 128 m) | final report, E5 |
| 0.6 B cells where load-all fails | 0.5–0.7 B cells | final report, E3 |
| Summary: full viewport redraw 7 ms; interactive ROI box "minutes / ~15 s / ~11 s" | No source. Replaced by the full view 76–158 ms after a zoom (E6) and a QGIS box in 10–225 ms (Swiss runs) | final report; `logs/qgis_session/experiment_report.md` |
| Summary: speed-up "up to 447×" next to gdaldem | 447× is on demand vs **exact tile** at 32 m (8–450× over all levels), not vs gdaldem | final report, E5 |
| Summary: GPU engine uses 4 threads, 1.4 GB | GPU memory ≤ 2.0 GiB is the measured figure; host threads are not reported | final report, E4 |

Unchanged numbers that were checked: 43 GB, 16 GB, 10.8 B; 1.2–1.6% spread; 2.7× core pinning; 208 s, 0.87 GB,
19–25 ns/cell; 73%, 0.99/22, 2–4%; 31.9 s; 2.9×, 2.6×, 39%; 3.5×, 1.4 GB; 1.3–2.6×, 3.4–4.2×, 134.8 s, > 367 s;
2.2–2.8×, 33 s / 65 s; 50×, 1.4×, 95%, 4.75×, 43.8 s; 14.5 → 2.0 s; 5–8 ms, 447×; 2.3°, 6.4°, 29% → 22%; 10–225 ms,
43/44, 0 diff (1.22 M cells), 400 M-cell box refused in 1 ms; 6.9–14 ms, 0.02 cores, 0% GPU, 1.9–2.3 GB, 47–129 s.

Data attribution: swissALTI3D © swisstopo; Copernicus DEM, see `datasets/README.md`.
