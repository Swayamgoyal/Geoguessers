"""Write main.tex from content.py (same text as the .docx), for pdflatex.

    python build_latex.py && pdflatex main.tex && pdflatex main.tex
"""
import re
from pathlib import Path

from content import BLOCKS

HERE = Path(__file__).resolve().parent

EQS = {
    "horn_x": r"\frac{\partial z}{\partial x}=\frac{(c+2f+i)-(a+2d+g)}{8\,\Delta x}",
    "horn_y": r"\frac{\partial z}{\partial y}=\frac{(g+2h+i)-(a+2b+c)}{8\,\Delta y}",
    "slope": r"\theta=\arctan\sqrt{\left(\frac{\partial z}{\partial x}\right)^{2}+\left(\frac{\partial z}{\partial y}"
             r"\right)^{2}}",
    "amdahl": r"S_{\max}=\frac{1}{1-p}",
    "rmse": r"\mathrm{RMSE}_{k}=\sqrt{\frac{1}{n_{k}}\sum_{i=1}^{n_{k}}\left(s_{i}-\bar{s}_{i}\right)^{2}}",
    "level": r"k^{*}=\max\left\{\,k : r_{k}\le m\,\right\}",
}

# multi-character sequences first, then single characters
SEQ = [("s̄ᵢ", r"$\bar{s}_i$"), ("sᵢ", r"$s_i$"), ("2ᵏ", r"$2^{k}$"), ("rₖ", r"$r_k$"), ("level-k", "level-$k$"),
       ("level k", "level $k$")]
CHAR = {"–": "--", "°": r"\textdegree{}", "×": r"\texttimes{}", "−": r"\textminus{}", "²": r"\textsuperscript{2}",
        "¹": r"\textsuperscript{1}", "©": r"\textcopyright{}", "Δ": r"$\Delta$", "θ": r"$\theta$", "≥": r"$\geq$",
        "≤": r"$\leq$", "~": r"\textasciitilde{}", "&": r"\&", "%": r"\%", "#": r"\#", "_": r"\_", "$": r"\$"}


def esc(text):
    """Escape plain text for LaTeX, keeping URLs in \\url{} and **bold** / *italic* spans."""
    out = []
    for part in re.split(r"(https?://\S+?)(?=[\s)]|$)", text):
        if re.match(r"https?://", part):
            out.append(r"\url{" + part + "}")
            continue
        chunks = []
        for span in re.split(r"(\*\*[^*]+\*\*|\*[^*]+\*)", part):
            if not span:
                continue
            bold, ital = span.startswith("**"), span.startswith("*") and not span.startswith("**")
            body = span[2:-2] if bold else span[1:-1] if ital else span
            for a, b in SEQ:
                body = body.replace(a, "\x00" + str(SEQ.index((a, b))) + "\x01")
            body = "".join(CHAR.get(ch, ch) for ch in body)
            body = re.sub(r"\x00(\d+)\x01", lambda m: SEQ[int(m.group(1))][1], body)
            chunks.append(r"\textbf{" + body + "}" if bold else r"\textit{" + body + "}" if ital else body)
        out.append("".join(chunks))
    return "".join(out)


def table(caption, header, rows, note):
    n = len(header)
    lens = [max(len(str(x)) for x in [h] + [r[i] for r in rows]) for i, h in enumerate(header)]
    wide = [i for i, l in enumerate(lens) if l > 22]
    cols = []
    for i in range(n):
        if i in wide:
            cols.append(r">{\raggedright\arraybackslash}X" if i == 0 else r">{\centering\arraybackslash}X")
        else:
            cols.append("l" if i == 0 else "c")
    if wide:
        head = r"\begin{tabularx}{\linewidth}{" + "".join(cols) + "}"
        tail = r"\end{tabularx}"
    else:
        head = r"\begin{tabular*}{\linewidth}{@{\extracolsep{\fill}}" + "".join(cols) + "}"
        tail = r"\end{tabular*}"
    lines = [r"\begin{table}[H]", r"\centering\small", r"\caption*{" + esc(caption) + "}", head, r"\toprule",
             " & ".join(r"\textbf{" + esc(h) + "}" for h in header) + r" \\", r"\midrule"]
    lines += [" & ".join(esc(str(v)) for v in r) + r" \\" for r in rows]
    lines += [r"\bottomrule", tail]
    if note:
        lines.append(r"\par\smallskip{\footnotesize " + esc(note) + "}")
    lines.append(r"\end{table}")
    return "\n".join(lines)


def main():
    out = [r"""\documentclass[10pt,a4paper]{article}
\usepackage[a4paper,margin=2.5cm]{geometry}
\usepackage[T1]{fontenc}
\usepackage{mathptmx}
\usepackage{textcomp,amsmath,graphicx,booktabs,tabularx,array,float}
\usepackage[font=small,labelformat=empty]{caption}
\usepackage{setspace}
\usepackage[mathlines]{lineno}
\usepackage{microtype}
\usepackage[hidelinks]{hyperref}
\usepackage{xurl}
\usepackage{titlesec}
\titleformat{\section}{\normalfont\fontsize{11}{13}\bfseries}{}{0pt}{}
\titleformat{\subsection}{\normalfont\normalsize\bfseries\itshape}{}{0pt}{}
\titlespacing*{\section}{0pt}{12pt}{4pt}
\titlespacing*{\subsection}{0pt}{8pt}{3pt}
\setlength{\parindent}{0pt}
\setlength{\parskip}{4pt}
\onehalfspacing
\renewcommand{\linenumberfont}{\normalfont\footnotesize}
\begin{document}
\linenumbers"""]
    for b in BLOCKS:
        kind = b[0]
        if kind == "title":
            out.append(r"\begin{center}{\fontsize{14}{17}\selectfont\bfseries " + esc(b[1]) + r"}\end{center}")
        elif kind == "authors":
            names = [esc(n) + r"\textsuperscript{" + s + "}" for n, s in b[1]]
            out.append(r"\begin{center}" + ", ".join(names[:-1]) + " and " + names[-1] + r"\\[2pt]")
        elif kind == "emails":
            out.append(r"{\small " + esc(b[1]) + r"}\\[2pt]")
        elif kind == "affil":
            out.append(r"{\small " + esc(b[1]) + r"}\end{center}")
        elif kind == "h1u":
            if b[1] == "References":
                out.append(r"\section*{\centering " + esc(b[1]) + "}")
                out.append(r"\begingroup\setlength{\parskip}{3pt}\singlespacing")
            else:
                out.append(r"\section*{\centering " + esc(b[1]) + "}")
        elif kind == "h1":
            out.append(r"\section*{" + esc(b[1]) + "}")
        elif kind == "h2":
            out.append(r"\subsection*{" + esc(b[1]) + "}")
        elif kind in ("p", "abstract"):
            out.append(esc(b[1]) + "\n")
        elif kind == "keywords":
            out.append(r"\textbf{Keywords:} " + esc(b[1]) + "\n")
        elif kind == "eq":
            out.append(r"\begin{equation}" + EQS[b[1]] + r"\end{equation}")
        elif kind == "fig":
            out.append(r"\begin{figure}[H]\centering\includegraphics[width=\linewidth]{" + b[1] + r"}"
                       r"\caption*{" + esc(b[2]) + r"}\end{figure}")
        elif kind == "table":
            out.append(table(*b[1:]))
        elif kind == "ref":
            out.append(r"\noindent\hangindent=1.5em\hangafter=1 " + esc(b[1]) + r"\par")
        else:
            raise ValueError(kind)
    out.append(r"\endgroup")
    out.append(r"\end{document}")
    (HERE / "main.tex").write_text("\n".join(out) + "\n")
    print("written", HERE / "main.tex")


if __name__ == "__main__":
    main()
