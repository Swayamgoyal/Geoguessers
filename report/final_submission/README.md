# Final report for submission (Word)

`GeoGuessers_final_report.docx` is the report to submit. `GeoGuessers_final_report.pdf` is the same document
exported from Word, for checking.

It follows the course instructions (`final_report/Report_Instructions_sample (1).pdf` in the repository root):
- Times New Roman 10 pt, 1.5 line spacing, line numbers.
- Title, authors with e-mail addresses, affiliation.
- Abstract of 196 words, keywords.
- Introduction of about 1,150 words.
- Main text (Introduction to Conclusions) of about 7,600 words.
- Sections: Study Area, Data and Methods, Results, Discussion (separate from Results), Limitations and Future
  Scope, Conclusions, Acknowledgements, Declarations, References (author–year), Appendix.
- 7 figures and 6 tables in the text; 3 tables and 2 figures in the appendix.
- Equations are Word equations. Tables have horizontal rules only.
- The study-area map shows the whole of India.

It is built on the team's 16-page draft (`final_report/final_report.pdf`). Changes:
- system-architecture figure (Figure 2);
- figure of the system in use (Figure 7);
- validation section and table that cover the default (pyramid) mode;
- recommendations paragraph in the Discussion;
- more measured details in Methods and Results;
- DOIs for the references, with the uncertain ones checked online;
- appendix with storage layouts, window sizes, viewer settings, the prefetch gate chart and the slope-error map.

## Files

| File | What |
|---|---|
| `AI_USAGE.md` | Statement of where an AI assistant was used in the project and in this report (kept out of the report itself) |
| `report_source.txt` | The report text, with simple markup (headings, tables, figures, equations, references) |
| `build_docx.py` | Builds the Word file from `report_source.txt` |
| `figures/` | The figures used in the report. `fig2_architecture.tex` is the TikZ source of Figure 2. |

## Rebuild

1. Install the build packages in any Python environment: `pip install python-docx latex2mathml lxml`.
2. Run `python build_docx.py`.
3. It needs Microsoft Office's `MML2OMML.XSL` (installed with Word) to turn the equations into Word equations.

Edits can also be made directly in the Word file. Rebuilding overwrites them.
