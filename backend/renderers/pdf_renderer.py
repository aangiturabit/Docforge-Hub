"""
backend/renderers/pdf_renderer.py
─────────────────────────────────────────────────────
High-quality A4 PDF renderer using ReportLab.

Called exclusively from backend/routers/download.py — never imported by app.py.

Features
────────
• Cover page  — company name, bold title, dept/industry/location, generated date
• Section headings — full-width dark-navy bar, white text
• Body text   — justified, 10pt Helvetica, 17pt leading
• Tables      — dark-navy header row, alternating row tints, tight grid
• Lists       — bullet-point indented items
• Footer      — title (left) / page number (right) on every content page
"""

import io
import re
from datetime import date as _date
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from backend.utils.logger import get_logger

logger = get_logger("docforge.renderers.pdf")

# ── Colour palette ────────────────────────────────────────────────────────────
_DARK     = colors.HexColor("#1e293b")
_ACCENT   = colors.HexColor("#334155")
_MUTED    = colors.HexColor("#64748b")
_ROW_EVEN = colors.white
_ROW_ODD  = colors.HexColor("#f8fafc")
_GRID     = colors.HexColor("#e2e8f0")
_RULE     = colors.HexColor("#1e293b")
_RULE_LT  = colors.HexColor("#e2e8f0")
_WHITE    = colors.white

# ── Page geometry ─────────────────────────────────────────────────────────────
_PAGE_W, _PAGE_H = A4
_MARGIN          = 2.5 * cm
_USABLE_W        = _PAGE_W - 2 * _MARGIN


# ── Text cleaner ─────────────────────────────────────────────────────────────
def _clean(text: str) -> str:
 
    if not text:
        return ""
    text = re.sub(r"#{1,6}\s*", "", str(text))
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*",     r"\1", text)
    text = re.sub(r"`(.*?)`",       r"\1", text)
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "--")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── Style definitions ─────────────────────────────────────────────────────────
_STYLES = {
    "cover_company": ParagraphStyle(
        "CoverCompany",
        fontName="Helvetica-Bold", fontSize=12,
        textColor=_ACCENT, alignment=TA_CENTER,
        spaceAfter=4, leading=16,
    ),
    "cover_title": ParagraphStyle(
        "CoverTitle",
        fontName="Helvetica-Bold", fontSize=28,
        textColor=_DARK, alignment=TA_CENTER,
        spaceBefore=8, spaceAfter=10, leading=36,
    ),
    "cover_dept": ParagraphStyle(
        "CoverDept",
        fontName="Helvetica-Bold", fontSize=12,
        textColor=_ACCENT, alignment=TA_CENTER,
        spaceAfter=6, leading=16,
    ),
    "cover_meta": ParagraphStyle(
        "CoverMeta",
        fontName="Helvetica", fontSize=10,
        textColor=_MUTED, alignment=TA_CENTER,
        spaceAfter=4, leading=14,
    ),
    "section_heading": ParagraphStyle(
        "SectionHeading",
        fontName="Helvetica-Bold", fontSize=11,
        textColor=_WHITE, alignment=TA_LEFT,
        spaceBefore=20, spaceAfter=8, leading=16,
        backColor=_DARK,
        borderPadding=(7, 10, 7, 10),
    ),
    "body": ParagraphStyle(
        "Body",
        fontName="Helvetica", fontSize=10,
        leading=17, spaceAfter=8, spaceBefore=2,
        alignment=TA_JUSTIFY,
    ),
    "list_item": ParagraphStyle(
        "ListItem",
        fontName="Helvetica", fontSize=10,
        leading=15, spaceAfter=4, spaceBefore=1,
        leftIndent=20, firstLineIndent=-12,
    ),
}


# ── Footer callback ───────────────────────────────────────────────────────────
def _draw_footer(canvas, doc):
    canvas.saveState()
    y = 1.6 * cm

    canvas.setStrokeColor(_RULE_LT)
    canvas.setLineWidth(0.5)
    canvas.line(_MARGIN, y + 0.35 * cm, _PAGE_W - _MARGIN, y + 0.35 * cm)

    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(_MUTED)

    title = getattr(doc, "_footer_title", "")
    if len(title) > 60:
        title = title[:57] + "…"
    canvas.drawString(_MARGIN, y, _clean(title))
    canvas.drawRightString(_PAGE_W - _MARGIN, y, f"Page {canvas.getPageNumber()}")
    canvas.restoreState()


# ── Main renderer ─────────────────────────────────────────────────────────────
def render_pdf(
    structured_sections: list,
    title: str,
    company: Optional[dict] = None,
    department: str = "",
) -> bytes:
    logger.info(
        "render_pdf | title=%r dept=%r sections=%d",
        title, department, len(structured_sections),
    )

    buffer = io.BytesIO()
    doc    = BaseDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=_MARGIN, leftMargin=_MARGIN,
        topMargin=_MARGIN,   bottomMargin=_MARGIN,
        title=title,
    )
    doc._footer_title = title

    frame = Frame(_MARGIN, _MARGIN, _USABLE_W, _PAGE_H - 2 * _MARGIN, id="main")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=_draw_footer)])

    story = []

    # ── Cover page ────────────────────────────────────────────────────────────
    story.append(Spacer(1, 4.5 * cm))

    company_name = (company or {}).get("name", "")
    if company_name:
        story.append(Paragraph(_clean(company_name), _STYLES["cover_company"]))
        story.append(Spacer(1, 0.4 * cm))

    story.append(HRFlowable(width=_USABLE_W, thickness=3, color=_RULE, spaceAfter=20))
    story.append(Paragraph(_clean(title), _STYLES["cover_title"]))
    story.append(HRFlowable(width=_USABLE_W, thickness=1, color=_RULE_LT, spaceBefore=14, spaceAfter=22))

    if department:
        story.append(Paragraph(_clean(department), _STYLES["cover_dept"]))
        story.append(Spacer(1, 0.3 * cm))

    for key, label in [("industry", "Industry"), ("location", "Location"), ("size", "Size")]:
        val = (company or {}).get(key, "")
        if val:
            story.append(Paragraph(f"{label}: {_clean(val)}", _STYLES["cover_meta"]))

    story.append(Spacer(1, 0.6 * cm))
    story.append(Paragraph(f"Generated on {_date.today().strftime('%d %B %Y')}", _STYLES["cover_meta"]))
    story.append(Spacer(1, 5 * cm))
    story.append(PageBreak())

    _align_map = {
        "left":    TA_LEFT,
        "center":  TA_CENTER,
        "justify": TA_JUSTIFY,
        "right":   TA_RIGHT,
    }

    # ── Sections ──────────────────────────────────────────────────────────────
    for section in structured_sections:
        heading      = _clean(section.get("heading", ""))
        content_type = section.get("content_type", "text")
        content      = section.get("content", "")
        styling      = section.get("styling", {})
        align        = _align_map.get(styling.get("alignment", "justify"), TA_JUSTIFY)

        sec_story = []

        if heading:
            sec_story.append(Paragraph(heading, _STYLES["section_heading"]))
            sec_story.append(Spacer(1, 0.2 * cm))

        if content_type == "text" and isinstance(content, str):
            body_style = ParagraphStyle("_DynBody", parent=_STYLES["body"], alignment=align)
            normalized = re.sub(r"(?<!\n)\n(?!\n)", " ", content)
            for para in normalized.split("\n\n"):
                c = _clean(para.strip())
                if c and len(c) > 3:
                    sec_story.append(Paragraph(c, body_style))
                    sec_story.append(Spacer(1, 0.12 * cm))

        elif content_type == "table" and isinstance(content, list) and content:
            table_data = [
                [_clean(str(c)) for c in row.get("cells", [])]
                for row in content
                if row.get("cells")
            ]
            if table_data:
                col_count = max(len(r) for r in table_data)
                col_w     = _USABLE_W / col_count

                row_bg = [
                    ("BACKGROUND", (0, i), (-1, i), _ROW_ODD if i % 2 == 0 else _ROW_EVEN)
                    for i in range(1, len(table_data))
                ]

                t = Table(table_data, colWidths=[col_w] * col_count, repeatRows=1, hAlign="LEFT")
                t.setStyle(TableStyle([
                    ("BACKGROUND",    (0, 0), (-1, 0), _DARK),
                    ("TEXTCOLOR",     (0, 0), (-1, 0), _WHITE),
                    ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE",      (0, 0), (-1, 0), 9),
                    ("TOPPADDING",    (0, 0), (-1, 0), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                    ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
                    ("FONTSIZE",      (0, 1), (-1, -1), 9),
                    ("TOPPADDING",    (0, 1), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
                    ("LEFTPADDING",   (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
                    ("GRID",          (0, 0), (-1, -1), 0.5, _GRID),
                    ("ALIGN",         (0, 0), (-1, -1), "LEFT"),
                    ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                    ("WORDWRAP",      (0, 0), (-1, -1), True),
                    *row_bg,
                ]))
                sec_story.append(t)
                sec_story.append(Spacer(1, 0.4 * cm))

        elif content_type == "list" and isinstance(content, list):
            for item in content:
                c = _clean(str(item))
                if c:
                    sec_story.append(Paragraph(f"\u2022\u2002{c}", _STYLES["list_item"]))
            sec_story.append(Spacer(1, 0.2 * cm))

        if styling.get("page_break_after"):
            sec_story.append(PageBreak())
        else:
            sec_story.append(Spacer(1, 0.3 * cm))

        if sec_story:
            story.append(KeepTogether(sec_story[:4]))
            story.extend(sec_story[4:])

    doc.build(story)
    buffer.seek(0)
    size_kb = buffer.getbuffer().nbytes // 1024
    logger.info("render_pdf complete | size=%d KB", size_kb)
    return buffer.read()
