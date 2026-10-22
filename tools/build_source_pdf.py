"""One-off: convert the official lab handout (.docx, provided by the department)
into data/LY_AgenticAI_Lab_Handout.pdf so the Researcher can cite page numbers.
Text is copied verbatim; only layout changes. Run:
    python tools/build_source_pdf.py path/to/Agentic_AI_Lab_Evaluation_AgentReel_Challenge.docx
"""
import sys
from pathlib import Path

import docx
from docx.oxml.ns import qn
from fpdf import FPDF

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"


def blocks(path):
    body = docx.Document(path).element.body
    for el in body.iterchildren():
        if el.tag == qn("w:p"):
            t = "".join(x.text or "" for x in el.iter(qn("w:t"))).strip()
            if t:
                yield "p", t
        elif el.tag == qn("w:tbl"):
            rows = []
            for tr in el.iter(qn("w:tr")):
                cells = []
                for tc in tr.iter(qn("w:tc")):
                    cells.append(" ".join("".join(x.text or "" for x in p.iter(qn("w:t")))
                                          for p in tc.iter(qn("w:p"))).strip())
                rows.append(cells)
            yield "t", rows


def main(src):
    pdf = FPDF(format="A4")
    pdf.set_margins(18, 16, 18)
    pdf.set_auto_page_break(True, 16)
    pdf.add_font("plex", "", str(FONTS / "IBMPlexSans-Regular.ttf"))
    pdf.add_font("plex", "B", str(FONTS / "IBMPlexSans-Bold.ttf"))
    pdf.add_page()
    for kind, content in blocks(src):
        if kind == "p":
            heading = content[:3].strip(". ").replace(".", "").isdigit() and len(content) < 70
            pdf.set_font("plex", "B" if heading else "", 12 if heading else 10)
            pdf.multi_cell(0, 5.4, content, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1.5)
        else:
            pdf.set_font("plex", "", 9)
            for row in content:
                line = " | ".join(c for c in row if c)
                if line:
                    pdf.multi_cell(0, 4.8, line, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
    out = ROOT / "data" / "LY_AgenticAI_Lab_Handout.pdf"
    pdf.output(str(out))
    print("wrote", out, pdf.page, "pages")


if __name__ == "__main__":
    main(sys.argv[1])
