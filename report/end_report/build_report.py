"""Build the end report (.docx) from content.py.

    python build_report.py  ->  GeoGuessers_end_report.docx

Formatting follows the course instructions: Times New Roman 10 pt, 1.5 line spacing, line numbers, equations as Word
equations (OMML), tables with horizontal rules only (caption above), figures inline (caption below), author-year
references without numbers.
"""
import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from content import BLOCKS

HERE = Path(__file__).resolve().parent
OUT = HERE / "GeoGuessers_end_report.docx"
FONT, SIZE, SMALL = "Times New Roman", Pt(10), Pt(9)
TEXT_W = Cm(16.0)

M = 'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


# ----------------------------------------------------------------------------- equations (OMML)
def r(t, upright=False):
    sty = '<m:rPr><m:sty m:val="p"/></m:rPr>' if upright else ""
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (f'<m:r>{sty}<w:rPr><w:rFonts w:ascii="Cambria Math" w:hAnsi="Cambria Math"/></w:rPr>'
            f'<m:t xml:space="preserve">{t}</m:t></m:r>')


def f(num, den):
    return f"<m:f><m:num>{num}</m:num><m:den>{den}</m:den></m:f>"


def sub(base, s):
    return f"<m:sSub><m:e>{base}</m:e><m:sub>{s}</m:sub></m:sSub>"


def sup(base, s):
    return f"<m:sSup><m:e>{base}</m:e><m:sup>{s}</m:sup></m:sSup>"


def rad(e):
    return f'<m:rad><m:radPr><m:degHide m:val="1"/></m:radPr><m:deg/><m:e>{e}</m:e></m:rad>'


def d(e, beg="(", end=")"):
    return f'<m:d><m:dPr><m:begChr m:val="{beg}"/><m:endChr m:val="{end}"/></m:dPr><m:e>{e}</m:e></m:d>'


def func(name, e):
    return f"<m:func><m:fName>{r(name, True)}</m:fName><m:e>{e}</m:e></m:func>"


def bar(e):
    return f'<m:bar><m:barPr><m:pos m:val="top"/></m:barPr><m:e>{e}</m:e></m:bar>'


def nsum(lo, hi, e):
    return (f'<m:nary><m:naryPr><m:chr m:val="&#8721;"/></m:naryPr><m:sub>{lo}</m:sub><m:sup>{hi}</m:sup>'
            f"<m:e>{e}</m:e></m:nary>")


dzdx, dzdy = f(r("∂z"), r("∂x")), f(r("∂z"), r("∂y"))
EQS = {
    "horn_x": dzdx + r("=") + f(d(d(r("c+2f+i")) + r("−") + d(r("a+2d+g")), "[", "]"), r("8Δx")),
    "horn_y": dzdy + r("=") + f(d(d(r("g+2h+i")) + r("−") + d(r("a+2b+c")), "[", "]"), r("8Δy")),
    "slope": r("θ=") + func("arctan", rad(sup(d(dzdx), r("2", True)) + r("+") + sup(d(dzdy), r("2", True)))),
    "amdahl": sub(r("S"), r("max", True)) + r("=") + f(r("1", True), r("1−p")),
    "rmse": sub(r("RMSE", True), r("k")) + r("=") + rad(
        f(r("1", True), sub(r("n"), r("k"))) + nsum(r("i=1"), sub(r("n"), r("k")),
                                                   sup(d(sub(r("s"), r("i")) + r("−") + sub(bar(r("s")), r("i"))),
                                                       r("2", True)))),
    "level": sup(r("k"), r("*")) + r("=") + func("max", d(r("k : ") + sub(r("r"), r("k")) + r("≤m"), "{", "}")),
}


def omath(key):
    return parse_xml(f"<m:oMath {M} {W}>{EQS[key]}</m:oMath>")


# ----------------------------------------------------------------------------- helpers
def set_font(run, size=SIZE, bold=None, italic=None, sup=False):
    run.font.name = FONT
    run._element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    run.font.size = size
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic
    if sup:
        run.font.superscript = True


def fmt(p, align=WD_ALIGN_PARAGRAPH.JUSTIFY, before=0, after=6, spacing=1.5, keep_next=False):
    pf = p.paragraph_format
    pf.alignment = align
    pf.space_before, pf.space_after = Pt(before), Pt(after)
    pf.line_spacing = spacing
    pf.keep_with_next = keep_next
    return p


def rich(p, text, size=SIZE, base_bold=False):
    """Add text with **bold** and *italic* spans."""
    for part in re.split(r"(\*\*[^*]+\*\*|\*[^*]+\*)", text):
        if not part:
            continue
        if part.startswith("**"):
            set_font(p.add_run(part[2:-2]), size, bold=True)
        elif part.startswith("*"):
            set_font(p.add_run(part[1:-1]), size, bold=base_bold, italic=True)
        else:
            set_font(p.add_run(part), size, bold=base_bold)


def cell_borders(cell, top=None, bottom=None):
    tcPr = cell._tc.get_or_add_tcPr()
    b = OxmlElement("w:tcBorders")
    for side, sz in (("top", top), ("bottom", bottom)):
        e = OxmlElement(f"w:{side}")
        if sz:
            e.set(qn("w:val"), "single"), e.set(qn("w:sz"), str(sz)), e.set(qn("w:color"), "000000")
        else:
            e.set(qn("w:val"), "nil")
        b.append(e)
    for side in ("left", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{side}")
        e.set(qn("w:val"), "nil")
        b.append(e)
    tcPr.append(b)


def add_table(doc, caption, header, rows, note):
    cp = fmt(doc.add_paragraph(), WD_ALIGN_PARAGRAPH.LEFT, before=6, after=3, spacing=1.15, keep_next=True)
    rich(cp, caption, SMALL)
    t = doc.add_table(rows=len(rows) + 1, cols=len(header))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    # column widths proportional to content length
    lens = [max(len(str(x)) for x in [h] + [row[i] for row in rows]) for i, h in enumerate(header)]
    lens = [max(10, min(l, 46)) for l in lens]
    widths = [int(TEXT_W * l / sum(lens)) for l in lens]
    # fixed layout with an explicit table width and grid, so Word and LibreOffice both honour the widths
    tblPr = t._tbl.tblPr
    tblW = tblPr.find(qn("w:tblW"))
    if tblW is None:
        tblW = OxmlElement("w:tblW")
        tblPr.append(tblW)
    tblW.set(qn("w:w"), str(int(TEXT_W / 635)))   # EMU -> twentieths of a point
    tblW.set(qn("w:type"), "dxa")
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tblPr.append(layout)
    for gc, w in zip(t._tbl.tblGrid.findall(qn("w:gridCol")), widths):
        gc.set(qn("w:w"), str(int(w / 635)))
    for col, w in zip(t.columns, widths):
        col.width = w
    for ri, values in enumerate([header] + rows):
        for ci, v in enumerate(values):
            c = t.cell(ri, ci)
            c.width = widths[ci]
            c.text = ""
            p = fmt(c.paragraphs[0], WD_ALIGN_PARAGRAPH.LEFT if ci == 0 else WD_ALIGN_PARAGRAPH.CENTER,
                    after=0, spacing=1.0, keep_next=(ri < len(rows)))   # keep the whole table on one page
            if ci == 0:
                trPr = t.rows[ri]._tr.get_or_add_trPr()
                cant = OxmlElement("w:cantSplit")
                trPr.append(cant)
            run = p.add_run(str(v))
            set_font(run, SMALL, bold=(ri == 0))
            top = 12 if ri == 0 else None
            bottom = 6 if ri == 0 else (12 if ri == len(rows) else None)
            cell_borders(c, top, bottom)
    if note:
        np_ = fmt(doc.add_paragraph(), WD_ALIGN_PARAGRAPH.LEFT, before=2, after=8, spacing=1.15)
        rich(np_, note, Pt(8.5))
    else:
        fmt(doc.add_paragraph(), after=4, spacing=1.0)


def add_figure(doc, path, caption):
    p = fmt(doc.add_paragraph(), WD_ALIGN_PARAGRAPH.CENTER, before=6, after=2, spacing=1.0, keep_next=True)
    p.add_run().add_picture(str(HERE / path), width=TEXT_W)
    cp = fmt(doc.add_paragraph(), WD_ALIGN_PARAGRAPH.JUSTIFY, before=2, after=10, spacing=1.15)
    rich(cp, caption, SMALL)


def add_equation(doc, key, n):
    p = fmt(doc.add_paragraph(), WD_ALIGN_PARAGRAPH.LEFT, before=3, after=3, spacing=1.15)
    ts = p.paragraph_format.tab_stops
    ts.add_tab_stop(Cm(8.0), WD_TAB_ALIGNMENT.CENTER)
    ts.add_tab_stop(TEXT_W, WD_TAB_ALIGNMENT.RIGHT)
    set_font(p.add_run("\t"))
    p._p.append(omath(key))
    set_font(p.add_run(f"\t({n})"))


def add_page_number(section):
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    for kind, text in (("begin", None), (None, "PAGE"), ("end", None)):
        if kind:
            e = OxmlElement("w:fldChar")
            e.set(qn("w:fldCharType"), kind)
        else:
            e = OxmlElement("w:instrText")
            e.set(qn("xml:space"), "preserve")
            e.text = text
        run._r.append(e)
    set_font(run, SMALL)


def line_numbers(section):
    sp = section._sectPr
    ln = OxmlElement("w:lnNumType")
    ln.set(qn("w:countBy"), "1")
    ln.set(qn("w:restart"), "continuous")
    ln.set(qn("w:distance"), "283")
    pgMar = sp.find(qn("w:pgMar"))
    pgMar.addnext(ln)


# ----------------------------------------------------------------------------- build
def build():
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name, st.font.size = FONT, SIZE
    st.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    sec = doc.sections[0]
    sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
    sec.left_margin = sec.right_margin = Cm(2.5)
    sec.top_margin = sec.bottom_margin = Cm(2.5)
    line_numbers(sec)
    add_page_number(sec)

    for b in BLOCKS:
        kind = b[0]
        if kind == "title":
            p = fmt(doc.add_paragraph(), WD_ALIGN_PARAGRAPH.CENTER, after=10, spacing=1.15)
            set_font(p.add_run(b[1]), Pt(14), bold=True)
        elif kind == "authors":
            p = fmt(doc.add_paragraph(), WD_ALIGN_PARAGRAPH.CENTER, after=2, spacing=1.15)
            for i, (name, s) in enumerate(b[1]):
                set_font(p.add_run(name + ("" if i == len(b[1]) - 1 else "")), SIZE)
                set_font(p.add_run(s), SIZE, sup=True)
                if i < len(b[1]) - 1:
                    set_font(p.add_run(", " if i < len(b[1]) - 2 else " and "), SIZE)
        elif kind in ("emails", "affil"):
            p = fmt(doc.add_paragraph(), WD_ALIGN_PARAGRAPH.CENTER, after=2 if kind == "emails" else 14,
                    spacing=1.15)
            set_font(p.add_run(b[1]), SMALL)
        elif kind in ("h1", "h1u"):
            p = fmt(doc.add_paragraph(), WD_ALIGN_PARAGRAPH.LEFT if kind == "h1" else WD_ALIGN_PARAGRAPH.CENTER,
                    before=12, after=4, spacing=1.15, keep_next=True)
            set_font(p.add_run(b[1]), Pt(11), bold=True)
        elif kind == "h2":
            p = fmt(doc.add_paragraph(), WD_ALIGN_PARAGRAPH.LEFT, before=8, after=3, spacing=1.15, keep_next=True)
            set_font(p.add_run(b[1]), SIZE, bold=True, italic=True)
        elif kind in ("p", "abstract"):
            p = fmt(doc.add_paragraph())
            rich(p, b[1])
        elif kind == "keywords":
            p = fmt(doc.add_paragraph(), after=10)
            set_font(p.add_run("Keywords: "), SIZE, bold=True)
            set_font(p.add_run(b[1]), SIZE)
        elif kind == "eq":
            add_equation(doc, b[1], b[2])
        elif kind == "fig":
            add_figure(doc, b[1], b[2])
        elif kind == "table":
            add_table(doc, *b[1:])
        elif kind == "ref":
            p = fmt(doc.add_paragraph(), WD_ALIGN_PARAGRAPH.LEFT, after=4, spacing=1.15)
            p.paragraph_format.left_indent = Cm(0.75)
            p.paragraph_format.first_line_indent = Cm(-0.75)
            set_font(p.add_run(b[1]), SIZE)
        else:
            raise ValueError(kind)
    doc.save(OUT)
    print("written", OUT)


if __name__ == "__main__":
    build()
