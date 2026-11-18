# Reports

| Folder | What | Covers |
|---|---|---|
| `final_submission/` | **Final report** (Word, course format): `GeoGuessers_final_report.docx` (+ PDF export), built from `report_source.txt` by `build_docx.py`; see its README | E1–E6, Swiss validation |
| `presentation/` | **Final presentation** (Beamer, 16:9): plots, live-demo slides, the Swiss Alps validation; see its README | E1–E6, demo |
| `demo/` | Demo video (58 s) of the web viewer and the QGIS plugin, a fallback for the live demo; see its README | Phase 5 |
| `end_report/` | The team's draft of the end report (LaTeX/Word builder) that the final report was developed from | E1–E6 |
| `figures/` | Study-area map used by the presentation | – |

The progress reports of Phases 2–5, the earlier LaTeX final report, the internal report and the earlier slides were
moved out of the repository at the final clean-up; their content is in the final report.

Figures come straight from `results/plots/` (and `figures/` for the study-area map), so a rebuild picks up regenerated
charts. Numbers match `docs/PHASE2_RESULTS.md`, `docs/PHASE3_RESULTS.md`, `docs/PHASE3_GPU_RESULTS.md` and
`docs/PHASE4_RESULTS.md` and `docs/PHASE5_RESULTS.md`. Sizes use MB = 10^6 and GB = 10^9 bytes; GPU memory is in GiB.

Build the presentation (MiKTeX or TeX Live), twice for references:
```
cd report/presentation
pdflatex main.tex
pdflatex main.tex
```
