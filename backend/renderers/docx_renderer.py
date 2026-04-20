"""
backend/renderers/docx_renderer.py
─────────────────────────────────────────────────────
High-quality .docx renderer using python-docx.

Called exclusively from backend/routers/download.py — never imported by app.py.

Features
────────
• Cover page   — company name, title, rules, dept/industry/location, date
• Section headings — dark-navy fill, white bold text via XML shading
• Body text    — justified, 10pt, 1.4× line spacing
• Tables       — dark-navy header row, alternating row tints
• Lists        — bullet-style paragraphs
• Footer       — page number field on every page
"""

import io
import re
from datetime import date as _date
from typing import Optional

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from backend.utils.logger import get_logger

logger = get_logger("docforge.renderers.docx")

# ── Colour palette (RGB tuples) ───────────────────────────────────────────────
_C_DARK   = (30, 41, 59)
_C_ACCENT = (51, 65, 85)
_C_MUTED  = (100, 116, 139)
_C_WHITE  = (255, 255, 255)

_HEX_DARK    = "1e293b"
_HEX_ROW_ODD = "f8fafc"


# ── XML helpers ───────────────────────────────────────────────────────────────

def _shade_cell(cell, fill_hex: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd   = OxmlElement("w:shd")
    shd.set(qn("w:val"),   "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"),  fill_hex)
    tc_pr.append(shd)


def _shade_para(paragraph, fill_hex: str) -> None:
    pPr = paragraph._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"),   "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"),  fill_hex)
    pPr.append(shd)


def _add_hr(doc: Document, color_hex: str = "1e293b", sz: str = "12") -> None:
    p    = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after  = Pt(8)
    pPr  = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bot  = OxmlElement("w:bottom")
    bot.set(qn("w:val"),   "single")
    bot.set(qn("w:sz"),    sz)
    bot.set(qn("w:space"), "1")
    bot.set(qn("w:color"), color_hex)
    pBdr.append(bot)
    pPr.append(pBdr)


def _add_page_number_footer(doc: Document, title: str) -> None:
    section = doc.sections[0]
    footer  = section.footer
    footer.is_linked_to_previous = False

    p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    p.clear()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.space_before = Pt(4)

    # Top border on footer paragraph
    pPr  = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    top  = OxmlElement("w:top")
    top.set(qn("w:val"),   "single")
    top.set(qn("w:sz"),    "4")
    top.set(qn("w:space"), "1")
    top.set(qn("w:color"), "e2e8f0")
    pBdr.append(top)
    pPr.append(pBdr)

    # Left: title text
    run_title = p.add_run(title[:60] + ("…" if len(title) > 60 else ""))
    run_title.font.size      = Pt(8)
    run_title.font.color.rgb = RGBColor(100, 116, 139)

    # Right-align tab stop
    tabs_el = OxmlElement("w:tabs")
    tab_el  = OxmlElement("w:tab")
    tab_el.set(qn("w:val"), "right")
    tab_el.set(qn("w:pos"), "9072")
    tabs_el.append(tab_el)
    pPr.append(tabs_el)

    run_tab = p.add_run()
    run_tab._r.append(OxmlElement("w:tab"))

    # Page number field
    run_pg = p.add_run()
    run_pg.font.size      = Pt(8)
    run_pg.font.color.rgb = RGBColor(100, 116, 139)

    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE \\* MERGEFORMAT "
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")

    run_pg._r.append(fld_begin)
    run_pg._r.append(instr)
    run_pg._r.append(fld_sep)
    run_pg._r.append(fld_end)


# ── Text cleaner ─────────────────────────────────────────────────────────────
def _clean(text: str) -> str:
    """
    Strip markdown artefacts and normalise typographic characters.
    Latin-1 encode/decode removed — it destroyed non-ASCII content.
    """
    if not text:
        return ""
    text = re.sub(r"#{1,6}\s*", "", str(text))
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*",     r"\1", text)
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "--")
    return text.strip()


def _add_para(
    doc: Document,
    text: str,
    bold: bool = False,
    size: int  = 10,
    align = WD_ALIGN_PARAGRAPH.LEFT,
    space_before: int = 0,
    space_after:  int = 6,
    color: tuple  = None,
    italic: bool  = False,
) -> None:
    p = doc.add_paragraph()
    p.alignment = align
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after  = Pt(space_after)
    run = p.add_run(_clean(text))
    run.bold      = bold
    run.italic    = italic
    run.font.size = Pt(size)
    if color:
        run.font.color.rgb = RGBColor(*color)


# ── Main renderer ─────────────────────────────────────────────────────────────
def render_docx(
    structured_sections: list,
    title: str,
    company: Optional[dict] = None,
    department: str = "",
) -> bytes:
    logger.info(
        "render_docx | title=%r dept=%r sections=%d",
        title, department, len(structured_sections),
    )

    doc = Document()

    for sec in doc.sections:
        sec.top_margin    = Cm(2.5)
        sec.bottom_margin = Cm(2.5)
        sec.left_margin   = Cm(2.5)
        sec.right_margin  = Cm(2.5)

    _add_page_number_footer(doc, title)

    # ── Cover page ────────────────────────────────────────────────────────────
    doc.add_paragraph()
    doc.add_paragraph()

    company_name = (company or {}).get("name", "")
    if company_name:
        _add_para(doc, company_name, bold=True, size=13,
                  align=WD_ALIGN_PARAGRAPH.CENTER, space_after=6, color=_C_ACCENT)

    _add_hr(doc, color_hex="1e293b", sz="18")
    _add_para(doc, title, bold=True, size=24,
              align=WD_ALIGN_PARAGRAPH.CENTER, space_before=10, space_after=10, color=_C_DARK)
    _add_hr(doc, color_hex="e2e8f0", sz="6")

    if department:
        _add_para(doc, department, bold=True, size=12,
                  align=WD_ALIGN_PARAGRAPH.CENTER, space_after=4, color=_C_ACCENT)

    for key, label in [("industry", "Industry"), ("location", "Location"), ("size", "Size")]:
        val = (company or {}).get(key, "")
        if val:
            _add_para(doc, f"{label}: {val}", size=10,
                      align=WD_ALIGN_PARAGRAPH.CENTER, space_after=3, color=_C_MUTED)

    _add_para(doc, f"Generated on {_date.today().strftime('%d %B %Y')}",
              size=10, align=WD_ALIGN_PARAGRAPH.CENTER, space_before=6, space_after=4, color=_C_MUTED)

    doc.add_page_break()

    _align_map = {
        "left":    WD_ALIGN_PARAGRAPH.LEFT,
        "center":  WD_ALIGN_PARAGRAPH.CENTER,
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
        "right":   WD_ALIGN_PARAGRAPH.RIGHT,
    }

    # ── Sections ──────────────────────────────────────────────────────────────
    for section_data in structured_sections:
        heading      = _clean(section_data.get("heading", ""))
        content_type = section_data.get("content_type", "text")
        content      = section_data.get("content", "")
        styling      = section_data.get("styling", {})
        para_align   = _align_map.get(styling.get("alignment", "justify"), WD_ALIGN_PARAGRAPH.JUSTIFY)

        if heading:
            h = doc.add_paragraph()
            h.paragraph_format.space_before = Pt(18)
            h.paragraph_format.space_after  = Pt(6)
            _shade_para(h, _HEX_DARK)
            run = h.add_run(heading)
            run.bold           = True
            run.font.size      = Pt(11)
            run.font.color.rgb = RGBColor(*_C_WHITE)

        if content_type == "text" and isinstance(content, str):
            normalized = re.sub(r"(?<!\n)\n(?!\n)", " ", content)
            for para_text in normalized.split("\n\n"):
                c = _clean(para_text.strip())
                if not c:
                    continue
                p = doc.add_paragraph()
                p.alignment                     = para_align
                p.paragraph_format.space_before = Pt(2)
                p.paragraph_format.space_after  = Pt(6)
                p.paragraph_format.line_spacing = Pt(16)
                run = p.add_run(c)
                run.font.size = Pt(10)

        elif content_type == "table" and isinstance(content, list) and content:
            rows = len(content)
            cols = max((len(r.get("cells", [])) for r in content), default=0)

            if rows > 0 and cols > 0:
                tbl = doc.add_table(rows=rows, cols=cols)
                tbl.style = "Table Grid"

                for i, row_data in enumerate(content):
                    cells = row_data.get("cells", [])
                    for j in range(cols):
                        cell_text = cells[j] if j < len(cells) else ""
                        cell      = tbl.cell(i, j)
                        cell.text = _clean(str(cell_text))

                        p = cell.paragraphs[0]
                        p.paragraph_format.space_before = Pt(3)
                        p.paragraph_format.space_after  = Pt(3)

                        if p.runs:
                            p.runs[0].font.size = Pt(9)

                        if i == 0:
                            _shade_cell(cell, _HEX_DARK)
                            if p.runs:
                                p.runs[0].bold           = True
                                p.runs[0].font.color.rgb = RGBColor(*_C_WHITE)
                        elif i % 2 == 0:
                            _shade_cell(cell, _HEX_ROW_ODD)

                spacer = doc.add_paragraph()
                spacer.paragraph_format.space_after = Pt(8)

        elif content_type == "list" and isinstance(content, list):
            for item in content:
                c = _clean(str(item))
                if c:
                    p = doc.add_paragraph(style="List Bullet")
                    p.paragraph_format.space_before = Pt(1)
                    p.paragraph_format.space_after  = Pt(3)
                    run = p.add_run(c)
                    run.font.size = Pt(10)

        spacer = doc.add_paragraph()
        spacer.paragraph_format.space_after = Pt(4)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    size_kb = buffer.getbuffer().nbytes // 1024
    logger.info("render_docx complete | size=%d KB", size_kb)
    return buffer.read()

# import io
# import re
# from datetime import date as _date
# from typing import Optional

# from docx import Document
# from docx.enum.text import WD_ALIGN_PARAGRAPH
# from docx.oxml import OxmlElement
# from docx.oxml.ns import qn
# from docx.shared import Cm, Pt, RGBColor

# from backend.utils.logger import get_logger

# logger = get_logger("docforge.renderers.docx")

# # ── Colour palette (RGB tuples) ───────────────────────────────────────────────
# _C_DARK    = (30, 41, 59)     
# _C_ACCENT  = (51, 65, 85)     
# _C_MUTED   = (100, 116, 139)  
# _C_WHITE   = (255, 255, 255)  

# # Hex strings for XML (no #)
# _HEX_DARK    = "1e293b"
# _HEX_ROW_ODD = "f8fafc"
# _HEX_HDR_BG  = "1e293b"


# # ── Small XML helpers ─────────────────────────────────────────────────────────
# def _shade_cell(cell, fill_hex: str):

#     tc_pr = cell._tc.get_or_add_tcPr()
#     shd   = OxmlElement("w:shd")
#     shd.set(qn("w:val"),   "clear")
#     shd.set(qn("w:color"), "auto")
#     shd.set(qn("w:fill"),  fill_hex)
#     tc_pr.append(shd)


# def _shade_para(paragraph, fill_hex: str):
  
#     pPr = paragraph._p.get_or_add_pPr()
#     shd = OxmlElement("w:shd")
#     shd.set(qn("w:val"),   "clear")
#     shd.set(qn("w:color"), "auto")
#     shd.set(qn("w:fill"),  fill_hex)
#     pPr.append(shd)


# def _add_hr(doc: Document, color_hex: str = "1e293b", sz: str = "12"):

#     p    = doc.add_paragraph()
#     p.paragraph_format.space_before = Pt(0)
#     p.paragraph_format.space_after  = Pt(8)
#     pPr  = p._p.get_or_add_pPr()
#     pBdr = OxmlElement("w:pBdr")
#     bot  = OxmlElement("w:bottom")
#     bot.set(qn("w:val"),   "single")
#     bot.set(qn("w:sz"),    sz)
#     bot.set(qn("w:space"), "1")
#     bot.set(qn("w:color"), color_hex)
#     pBdr.append(bot)
#     pPr.append(pBdr)


# def _add_page_number_footer(doc: Document, title: str):
#     section  = doc.sections[0]
#     footer   = section.footer
#     footer.is_linked_to_previous = False

#     p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
#     p.clear()
#     p.alignment = WD_ALIGN_PARAGRAPH.LEFT
#     p.paragraph_format.space_before = Pt(4)

#     # Add top border to footer paragraph
#     pPr  = p._p.get_or_add_pPr()
#     pBdr = OxmlElement("w:pBdr")
#     top  = OxmlElement("w:top")
#     top.set(qn("w:val"),   "single")
#     top.set(qn("w:sz"),    "4")
#     top.set(qn("w:space"), "1")
#     top.set(qn("w:color"), "e2e8f0")
#     pBdr.append(top)
#     pPr.append(pBdr)

#     # Left: title text
#     run_title = p.add_run(title[:60] + ("…" if len(title) > 60 else ""))
#     run_title.font.size  = Pt(8)
#     run_title.font.color.rgb = RGBColor(100, 116, 139)

#     # Tab to right-align page number
#     tab_stop = OxmlElement("w:tab")
#     pPr2 = p._p.get_or_add_pPr()

#     tabs_el = OxmlElement("w:tabs")
#     tab_el  = OxmlElement("w:tab")
#     tab_el.set(qn("w:val"), "right")
#     tab_el.set(qn("w:pos"), "9072")  
#     tabs_el.append(tab_el)
#     pPr2.append(tabs_el)

#     run_tab = p.add_run()
#     run_tab._r.append(OxmlElement("w:tab"))

#     # Page number field
#     run_pg = p.add_run()
#     run_pg.font.size = Pt(8)
#     run_pg.font.color.rgb = RGBColor(100, 116, 139)

#     fld_begin = OxmlElement("w:fldChar")
#     fld_begin.set(qn("w:fldCharType"), "begin")
#     instr = OxmlElement("w:instrText")
#     instr.set(qn("xml:space"), "preserve")
#     instr.text = ' PAGE \\* MERGEFORMAT '
#     fld_sep = OxmlElement("w:fldChar")
#     fld_sep.set(qn("w:fldCharType"), "separate")
#     fld_end = OxmlElement("w:fldChar")
#     fld_end.set(qn("w:fldCharType"), "end")

#     run_pg._r.append(fld_begin)
#     run_pg._r.append(instr)
#     run_pg._r.append(fld_sep)
#     run_pg._r.append(fld_end)


# # ── Text cleaner ─────────────────────────────────────────────────────────────
# def _clean(text: str) -> str:
#     if not text:
#         return ""
#     text = re.sub(r"#{1,6}\s*", "", str(text))
#     text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
#     text = re.sub(r"\*(.*?)\*",     r"\1", text)
#     text = text.replace("\u2019", "'").replace("\u2018", "'")
#     text = text.replace("\u201c", '"').replace("\u201d", '"')
#     text = text.replace("\u2013", "-").replace("\u2014", "--")
#     return text.strip()


# # ── Cover-page paragraph helper ───────────────────────────────────────────────
# def _add_para(
#     doc: Document,
#     text: str,
#     bold: bool = False,
#     size: int  = 10,
#     align = WD_ALIGN_PARAGRAPH.LEFT,
#     space_before: int = 0,
#     space_after:  int = 6,
#     color: tuple  = None,
#     italic: bool  = False,
# ) -> None:
#     p = doc.add_paragraph()
#     p.alignment = align
#     p.paragraph_format.space_before = Pt(space_before)
#     p.paragraph_format.space_after  = Pt(space_after)
#     run = p.add_run(_clean(text))
#     run.bold   = bold
#     run.italic = italic
#     run.font.size = Pt(size)
#     if color:
#         run.font.color.rgb = RGBColor(*color)


# # ── Main renderer ─────────────────────────────────────────────────────────────
# def render_docx(
#     structured_sections: list,
#     title: str,
#     company: Optional[dict] = None,
#     department: str = "",
# ) -> bytes:

#     logger.info(
#         "render_docx start | title=%r dept=%r sections=%d",
#         title, department, len(structured_sections),
#     )

#     doc = Document()

#     # ── Page margins ──────────────────────────────────────────────────────────
#     for sec in doc.sections:
#         sec.top_margin    = Cm(2.5)
#         sec.bottom_margin = Cm(2.5)
#         sec.left_margin   = Cm(2.5)
#         sec.right_margin  = Cm(2.5)

#     # ── Footer ────────────────────────────────────────────────────────────────
#     _add_page_number_footer(doc, title)

#     # ── Cover page ────────────────────────────────────────────────────────────
#     doc.add_paragraph()
#     doc.add_paragraph()

#     company_name = (company or {}).get("name", "")
#     if company_name:
#         _add_para(
#             doc, company_name,
#             bold=True, size=13,
#             align=WD_ALIGN_PARAGRAPH.CENTER,
#             space_after=6, color=_C_ACCENT,
#         )

#     _add_hr(doc, color_hex="1e293b", sz="18")

#     _add_para(
#         doc, title,
#         bold=True, size=24,
#         align=WD_ALIGN_PARAGRAPH.CENTER,
#         space_before=10, space_after=10,
#         color=_C_DARK,
#     )

#     _add_hr(doc, color_hex="e2e8f0", sz="6")

#     if department:
#         _add_para(
#             doc, department,
#             bold=True, size=12,
#             align=WD_ALIGN_PARAGRAPH.CENTER,
#             space_after=4, color=_C_ACCENT,
#         )

#     for key, label in [("industry", "Industry"), ("location", "Location"), ("size", "Size")]:
#         val = (company or {}).get(key, "")
#         if val:
#             _add_para(
#                 doc, f"{label}: {val}",
#                 size=10,
#                 align=WD_ALIGN_PARAGRAPH.CENTER,
#                 space_after=3, color=_C_MUTED,
#             )

#     _add_para(
#         doc, f"Generated on {_date.today().strftime('%d %B %Y')}",
#         size=10,
#         align=WD_ALIGN_PARAGRAPH.CENTER,
#         space_before=6, space_after=4,
#         color=_C_MUTED,
#     )

#     doc.add_page_break()

#     # ── Alignment map ─────────────────────────────────────────────────────────
#     _align = {
#         "left":    WD_ALIGN_PARAGRAPH.LEFT,
#         "center":  WD_ALIGN_PARAGRAPH.CENTER,
#         "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
#         "right":   WD_ALIGN_PARAGRAPH.RIGHT,
#     }

#     # ── Sections ──────────────────────────────────────────────────────────────
#     for section_data in structured_sections:
#         heading      = _clean(section_data.get("heading", ""))
#         content_type = section_data.get("content_type", "text")
#         content      = section_data.get("content", "")
#         styling      = section_data.get("styling", {})
#         para_align   = _align.get(styling.get("alignment", "justify"), WD_ALIGN_PARAGRAPH.JUSTIFY)

#         # ── Section heading — dark-navy bg, white text ─────────────────────
#         if heading:
#             h = doc.add_paragraph()
#             h.paragraph_format.space_before = Pt(18)
#             h.paragraph_format.space_after  = Pt(6)
#             _shade_para(h, _HEX_DARK)

#             run = h.add_run(heading)
#             run.bold           = True
#             run.font.size      = Pt(11)
#             run.font.color.rgb = RGBColor(*_C_WHITE)

#         # ── Text ──────────────────────────────────────────────────────────
#         if content_type == "text" and isinstance(content, str):
#             normalized = re.sub(r"(?<!\n)\n(?!\n)", " ", content)
#             for para_text in normalized.split("\n\n"):
#                 c = _clean(para_text.strip())
#                 if not c:
#                     continue
#                 p = doc.add_paragraph()
#                 p.alignment                     = para_align
#                 p.paragraph_format.space_before = Pt(2)
#                 p.paragraph_format.space_after  = Pt(6)
#                 p.paragraph_format.line_spacing = Pt(16)
#                 run = p.add_run(c)
#                 run.font.size = Pt(10)

#         # ── Table ─────────────────────────────────────────────────────────
#         elif content_type == "table" and isinstance(content, list) and content:
#             rows = len(content)
#             cols = max((len(r.get("cells", [])) for r in content), default=0)

#             if rows > 0 and cols > 0:
#                 tbl = doc.add_table(rows=rows, cols=cols)
#                 tbl.style = "Table Grid"

#                 for i, row_data in enumerate(content):
#                     cells = row_data.get("cells", [])
#                     for j in range(cols):
#                         cell_text = cells[j] if j < len(cells) else ""
#                         cell      = tbl.cell(i, j)
#                         cell.text = _clean(str(cell_text))

#                         p = cell.paragraphs[0]
#                         p.paragraph_format.space_before = Pt(3)
#                         p.paragraph_format.space_after  = Pt(3)

#                         if p.runs:
#                             p.runs[0].font.size = Pt(9)

#                         if i == 0:
#                             # Header row — dark navy bg, white bold text
#                             _shade_cell(cell, _HEX_HDR_BG)
#                             if p.runs:
#                                 p.runs[0].bold = True
#                                 p.runs[0].font.color.rgb = RGBColor(*_C_WHITE)
#                         elif i % 2 == 0:
#                             # Even data rows — light tint
#                             _shade_cell(cell, _HEX_ROW_ODD)

#                 # Spacing after table
#                 spacer = doc.add_paragraph()
#                 spacer.paragraph_format.space_after = Pt(8)

#         # ── List ──────────────────────────────────────────────────────────
#         elif content_type == "list" and isinstance(content, list):
#             for item in content:
#                 c = _clean(str(item))
#                 if c:
#                     p = doc.add_paragraph(style="List Bullet")
#                     p.paragraph_format.space_before = Pt(1)
#                     p.paragraph_format.space_after  = Pt(3)
#                     run = p.add_run(c)
#                     run.font.size = Pt(10)

#         # Section spacing
#         spacer = doc.add_paragraph()
#         spacer.paragraph_format.space_after = Pt(4)

#     buffer = io.BytesIO()
#     doc.save(buffer)
#     buffer.seek(0)
#     size_kb = buffer.getbuffer().nbytes // 1024
#     logger.info("render_docx complete | size=%d KB", size_kb)
#     return buffer.read()