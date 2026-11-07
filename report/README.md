# Reports

| Folder | Report | Covers |
|---|---|---|
| `prof_report/` | Progress report, Phase 2: data preparation and baseline benchmarks (gdaldem, storage layouts, QGIS) | E1, E2, QGIS display |
| `phase3_report/` | Progress report, Phase 3: our own CPU and GPU terrain engine | E3, E4 |
| `phase4_report/` | Progress report, Phase 4: terrain derivatives on demand from the pyramid | E5 |
| `phase5_report/` | Progress report, Phase 5: interactive viewing with debounced pan/zoom and prefetch (tile engine, scheduler, server, web viewer, QGIS plugin) | E6 |
| `internal_report/` | Internal team report: everything we did and why, all results (Phases 0–5 incl. the viewer and E6), problems faced, glossary, presentation preparation (numbers to remember, slide order, likely questions with answers) | Phases 0–5 |
| `final_report/` | **Final report**: introduction, related work, data, method, E1–E6, discussion (the bottleneck story, G1, G2), recommendations, limitations, reproducibility, problems met | E1–E6 |
| `slides/` | Final presentation (Beamer, 16:9, 23 slides) | E1–E6, demo |
| `demo/` | Demo video (58 s, silent with captions) of the web viewer and the QGIS plugin; see its README | Phase 5 |

Figures come straight from `results/plots/` (and `figures/` for the study-area map), so a rebuild picks up regenerated
charts. Numbers match `docs/PHASE2_RESULTS.md`, `docs/PHASE3_RESULTS.md`, `docs/PHASE3_GPU_RESULTS.md` and
`docs/PHASE4_RESULTS.md` and `docs/PHASE5_RESULTS.md`. Sizes use MB = 10^6 and GB = 10^9 bytes; GPU memory is in GiB.

Build (MiKTeX or TeX Live), twice for references:
```
cd report/phase3_report
pdflatex main.tex
pdflatex main.tex
```
