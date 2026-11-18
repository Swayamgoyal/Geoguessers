"""Build the final report as a Word document from report_source.txt.

Format (course instructions): Times New Roman 10 pt, 1.5 line spacing, line numbers, equations as Word equations,
tables with horizontal lines only, figures and tables placed where they are cited.

Needs python-docx, latex2mathml and lxml, and Microsoft Office's MML2OMML.XSL (MathML -> Word equation).
Run:  python build_docx.py   (writes GeoGuessers_final_report.docx next to this script)
"""
import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from latex2mathml.converter import convert as latex_to_mathml
from lxml import etree

HERE = Path(__file__).resolve().parent
SRC = HERE / "report_source.txt"
OUT = HERE / "GeoGuessers_final_report.docx"
FIGS = HERE / "figures"
XSL = Path(r"C:\Program Files\Microsoft Office\root\Office16\MML2OMML.XSL")
FONT = "Times New Roman"
BODY_PT = 10

_xslt = etree.XSLT(etree.parse(str(XSL)))


# ---------------------------------------------------------------- helpers
def set_font(run, size=BODY_PT, bold=None, italic=None):
    run.font.name = FONT
    run.font.size = Pt(size)
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    for k in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(k), FONT)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic


def para_format(p, align=WD_ALIGN_PARAGRAPH.JUSTIFY, spacing=1.5, before=0, after=6, keep_next=False):
    pf = p.paragraph_format
    p.alignment = align
    pf.line_spacing = spacing
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.keep_with_next = keep_next


TAG = re.compile(r"\{(/?)(sup|sub|i|b)\}")


def add_rich(p, text, size=BODY_PT, bold=False, italic=False):
    """Add text with inline {sup}{sub}{i}{b} tags."""
    state = {"sup": False, "sub": False, "i": italic, "b": bold}
    pos = 0
    for m in TAG.finditer(text):
        if m.start() > pos:
            _emit(p, text[pos:m.start()], state, size)
        tag, opening = m.group(2), m.group(1) != "/"
        base = {"sup": False, "sub": False, "i": italic, "b": bold}[tag]
        state[tag] = True if opening else base
        pos = m.end()
    if pos < len(text):
        _emit(p, text[pos:], state, size)


def _emit(p, s, state, size):
    r = p.add_run(s)
    set_font(r, size, bold=state["b"], italic=state["i"])
    if state["sup"]:
        r.font.superscript = True
    if state["sub"]:
        r.font.subscript = True


def omml(latex):
    mml = latex_to_mathml(latex)
    tree = etree.fromstring(mml.encode("utf-8"))
    return _xslt(tree).getroot()


TEXT_WIDTH_CM = 16.0


def no_borders(table):
    tblpr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "nil")
        borders.append(el)
    tblpr.append(borders)


def fixed_widths(table, widths_cm):
    tblpr = table._tbl.tblPr
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tblpr.append(layout)
    tw = OxmlElement("w:tblW")
    tw.set(qn("w:w"), str(int(sum(widths_cm) * 567)))
    tw.set(qn("w:type"), "dxa")
    for old in tblpr.findall(qn("w:tblW")):
        tblpr.remove(old)
    tblpr.append(tw)
    grid = table._tbl.tblGrid
    for gc, w in zip(grid.findall(qn("w:gridCol")), widths_cm):
        gc.set(qn("w:w"), str(int(w * 567)))
    for row in table.rows:
        for cell, w in zip(row.cells, widths_cm):
            cell.width = Cm(w)


def add_equation(doc, latex, number):
    """Display equation: a borderless 3-column row (blank | equation, centred | number, right)."""
    t = doc.add_table(rows=1, cols=3)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    no_borders(t)
    fixed_widths(t, [1.5, TEXT_WIDTH_CM - 3.0, 1.5])
    c0, c1, c2 = t.rows[0].cells
    for c in (c0, c1, c2):
        c.vertical_alignment = 1  # centre
    p = c1.paragraphs[0]
    para_format(p, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0, before=3, after=3)
    para = etree.SubElement(p._p, "{http://schemas.openxmlformats.org/officeDocument/2006/math}oMathPara")
    para.append(omml(latex))
    p2 = c2.paragraphs[0]
    para_format(p2, align=WD_ALIGN_PARAGRAPH.RIGHT, spacing=1.0, before=3, after=3)
    set_font(p2.add_run(number))


def set_cell_border(cell, **edges):
    tcpr = cell._tc.get_or_add_tcPr()
    borders = tcpr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tcpr.append(borders)
    for edge, val in edges.items():
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), val.get("val", "single"))
        el.set(qn("w:sz"), str(val.get("sz", 6)))
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), "000000")
        borders.append(el)


def add_table(doc, caption, rows):
    cap = doc.add_paragraph()
    para_format(cap, align=WD_ALIGN_PARAGRAPH.LEFT, spacing=1.15, before=6, after=3, keep_next=True)
    head, rest = caption.split(".", 1) if caption.startswith(("Table", "Appendix Table")) else (caption, "")
    r = cap.add_run(head + ".")
    set_font(r, 9, bold=True)
    add_rich(cap, rest, size=9)
    ncol = len(rows[0])
    t = doc.add_table(rows=len(rows), cols=ncol)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = True
    # no borders by default
    tblpr = t._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        if edge in ("top", "bottom"):
            el.set(qn("w:val"), "single")
            el.set(qn("w:sz"), "8")
        else:
            el.set(qn("w:val"), "nil")
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), "000000")
        borders.append(el)
    tblpr.append(borders)
    # column widths from content length, filling the text width
    plain = [[TAG.sub("", c).strip() for c in r] for r in rows]
    weights = []
    for j in range(ncol):
        body = max((len(r[j]) for r in plain[1:]), default=0)
        head_word = max(len(w) for w in (plain[0][j].split() or [""]))
        weights.append(min(max(body, head_word, 4) + 3, 40))
    widths = [TEXT_WIDTH_CM * w / sum(weights) for w in weights]
    fixed_widths(t, widths)
    textual = [sum(len(r[j]) for r in plain[1:]) / max(len(plain) - 1, 1) > 14 for j in range(ncol)]
    for i, row in enumerate(rows):
        for j, txt in enumerate(row):
            cell = t.cell(i, j)
            cp = cell.paragraphs[0]
            left = j == 0 or textual[j]
            para_format(cp, align=WD_ALIGN_PARAGRAPH.LEFT if left else WD_ALIGN_PARAGRAPH.CENTER,
                        spacing=1.0, after=1, before=1, keep_next=(i < len(rows) - 1))
            add_rich(cp, txt.strip(), size=9, bold=(i == 0))
            if i == 0:
                set_cell_border(cell, bottom={"sz": 6})
        # keep rows together on one page where possible
        trpr = t.rows[i]._tr.get_or_add_trPr()
        cs = OxmlElement("w:cantSplit")
        trpr.append(cs)
    if len(rows) > 1:
        hdr = t.rows[0]._tr.get_or_add_trPr()
        th = OxmlElement("w:tblHeader")
        hdr.append(th)
    sp = doc.add_paragraph()
    para_format(sp, spacing=1.0, after=4)


def add_figure(doc, fname, width_cm, caption):
    p = doc.add_paragraph()
    para_format(p, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0, before=6, after=2, keep_next=True)
    p.add_run().add_picture(str(FIGS / fname), width=Cm(width_cm))
    cap = doc.add_paragraph()
    para_format(cap, align=WD_ALIGN_PARAGRAPH.JUSTIFY, spacing=1.15, after=8)
    head, rest = caption.split(".", 1)
    r = cap.add_run(head + ".")
    set_font(r, 9, bold=True)
    add_rich(cap, rest, size=9)


def add_line_numbers(section):
    sectpr = section._sectPr
    ln = OxmlElement("w:lnNumType")
    ln.set(qn("w:countBy"), "1")
    ln.set(qn("w:restart"), "continuous")
    ln.set(qn("w:distance"), "283")
    sectpr.append(ln)


def add_page_number(section):
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for kind, text in (("begin", None), (None, "PAGE"), ("end", None)):
        r = p.add_run()
        set_font(r, 9)
        if kind:
            fc = OxmlElement("w:fldChar")
            fc.set(qn("w:fldCharType"), kind)
            r._r.append(fc)
        else:
            it = OxmlElement("w:instrText")
            it.set(qn("xml:space"), "preserve")
            it.text = text
            r._r.append(it)


def suppress_line_numbers(p):
    ppr = p._p.get_or_add_pPr()
    el = OxmlElement("w:suppressLineNumbers")
    ppr.append(el)


# ---------------------------------------------------------------- build
def build():
    doc = Document()
    sec = doc.sections[0]
    sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
    for m in ("left_margin", "right_margin"):
        setattr(sec, m, Cm(2.5))
    sec.top_margin = sec.bottom_margin = Cm(2.3)
    add_line_numbers(sec)
    add_page_number(sec)
    st = doc.styles["Normal"]
    st.font.name = FONT
    st.font.size = Pt(BODY_PT)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    # line numbers in Times as well
    if "Line Number" in [s.name for s in doc.styles]:
        doc.styles["Line Number"].font.name = FONT

    lines = SRC.read_text(encoding="utf-8").splitlines()
    i = 0
    words_main, counting = 0, False
    abstract_words, in_abstract = 0, False
    while i < len(lines):
        line = lines[i].rstrip()
        if not line:
            i += 1
            continue
        key, _, val = line.partition("| ")
        if line.startswith("TITLE| "):
            p = doc.add_paragraph()
            para_format(p, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.15, before=12, after=12)
            add_rich(p, val, size=14, bold=True)
        elif line.startswith(("CENTER| ", "CENTERSMALL| ")):
            p = doc.add_paragraph()
            para_format(p, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.15, after=4)
            add_rich(p, val, size=9 if key == "CENTERSMALL" else BODY_PT)
        elif line.startswith("H0| "):
            p = doc.add_paragraph()
            centered = val in ("Abstract",)
            para_format(p, align=WD_ALIGN_PARAGRAPH.CENTER if centered else WD_ALIGN_PARAGRAPH.LEFT,
                        before=12, after=4, keep_next=True)
            add_rich(p, val, size=11, bold=True)
            in_abstract = val == "Abstract"
            if val in ("Acknowledgements",):
                counting = False
        elif line.startswith("KEYWORDS| "):
            in_abstract = False
            p = doc.add_paragraph()
            para_format(p, after=8)
            r = p.add_run("Keywords: ")
            set_font(r, bold=True)
            add_rich(p, val)
        elif line.startswith("# "):
            counting = True
            p = doc.add_paragraph()
            para_format(p, align=WD_ALIGN_PARAGRAPH.LEFT, before=10, after=4, keep_next=True)
            add_rich(p, line[2:], size=11, bold=True)
            words_main += len(line[2:].split())
        elif line.startswith("## "):
            p = doc.add_paragraph()
            para_format(p, align=WD_ALIGN_PARAGRAPH.LEFT, before=8, after=3, keep_next=True)
            add_rich(p, line[3:], size=BODY_PT, bold=True)
            words_main += len(line[3:].split())
        elif line.startswith("### "):
            p = doc.add_paragraph()
            para_format(p, align=WD_ALIGN_PARAGRAPH.LEFT, before=6, after=2, keep_next=True)
            add_rich(p, line[4:], size=BODY_PT, italic=True)
        elif line.startswith("SUBHEAD| "):
            body = lines[i + 1].strip()
            p = doc.add_paragraph()
            para_format(p, after=4)
            r = p.add_run(val + ". ")
            set_font(r, bold=True)
            add_rich(p, body)
            i += 1
        elif line.startswith("EQ| "):
            latex, num = [x.strip() for x in val.rsplit("|", 1)]
            add_equation(doc, latex, num)
        elif line.startswith("FIG| "):
            fname, width, cap = [x.strip() for x in val.split("|", 2)]
            add_figure(doc, fname, float(width), cap)
        elif line.startswith("TAB| "):
            rows = []
            i += 1
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c for c in lines[i].strip().strip("|").split("|")])
                i += 1
            add_table(doc, val, rows)
            continue
        elif line.startswith("REF| "):
            p = doc.add_paragraph()
            para_format(p, align=WD_ALIGN_PARAGRAPH.LEFT, spacing=1.15, after=3)
            p.paragraph_format.left_indent = Cm(0.6)
            p.paragraph_format.first_line_indent = Cm(-0.6)
            add_rich(p, val, size=9)
        elif line == "PAGEBREAK":
            doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        else:  # body paragraph (NOINDENT| is the same here: no first-line indents are used)
            text = val if line.startswith("NOINDENT| ") else line
            p = doc.add_paragraph()
            para_format(p)
            add_rich(p, text)
            n = len(TAG.sub("", text).split())
            if counting:
                words_main += n
            if in_abstract:
                abstract_words += n
        i += 1
    doc.save(OUT)
    print(f"wrote {OUT}")
    print(f"abstract words: {abstract_words}; main text words (Introduction to Conclusions, without tables, "
          f"captions and equations): {words_main}")


if __name__ == "__main__":
    sys.exit(build())
