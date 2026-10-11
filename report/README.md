# Reports

| Folder | Report | Covers |
|---|---|---|
| `prof_report/` | Progress report, Phase 2: data preparation and baseline benchmarks (gdaldem, storage layouts, QGIS) | E1, E2, QGIS display |
| `phase3_report/` | Progress report, Phase 3: our own CPU and GPU terrain engine | E3, E4 |
| `phase4_report/` | Progress report, Phase 4: terrain derivatives on demand from the pyramid | E5 |
| `internal_report/` | Internal deep-dive written after Phase 2 (team use) | Phases 0â€“2 |

Figures come straight from `results/plots/` (and `figures/` for the study-area map), so a rebuild picks up regenerated
charts. Numbers match `docs/PHASE2_RESULTS.md`, `docs/PHASE3_RESULTS.md`, `docs/PHASE3_GPU_RESULTS.md` and
`docs/PHASE4_RESULTS.md`. Sizes use MB = 10^6 and GB = 10^9 bytes; GPU memory is in GiB.

Build (MiKTeX or TeX Live), twice for references:
```
cd report/phase3_report
pdflatex main.tex
pdflatex main.tex
```
