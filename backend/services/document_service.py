
# from sqlalchemy.orm import Session
# from uuid import UUID
# from typing import Dict, Optional, List
# from backend.database import crud
# from backend.services import prompt_service, llm_service
# import json
# import re
# import io
# from datetime import date

# # ═══════════════════════════════════════════════════════
# # SECTION INTELLIGENCE LAYER (Unchanged)
# # ═══════════════════════════════════════════════════════
# SECTION_ROLE_MAP = {
#     "HEADER": ["letterhead", "date", "title", "reference", "id", "version",
#                "parties", "candidate", "company letterhead", "heading"],
#     "OPENER": ["purpose", "scope", "overview", "background",
#                "executive summary", "introduction", "objective"],
#     "STRUCTURAL": ["definitions", "methodology", "classification",
#                    "types", "categories", "framework"],
#     "OBLIGATION": ["responsibilities", "obligations", "requirements",
#                    "policy", "rules", "clause", "compliance"],
#     "EVIDENCE": ["findings", "results", "assessment", "analysis",
#                  "metrics", "test", "defects", "vulnerability", "risk"],
#     "BODY": ["compensation", "breakdown", "details", "description",
#              "content", "information", "terms", "conditions"],
#     "CLOSURE": ["recommendations", "next steps", "action items",
#                 "conclusion", "improvement", "mitigation"],
#     "SIGN_OFF": ["approval", "signature", "sign off", "acknowledgement",
#                  "authorization", "sign-off", "closure"]
# }

# TABLE_SECTION_SIGNALS = [
#     "compensation", "breakdown", "ctc", "salary", "budget",
#     "invoice", "pricing", "comparison", "metrics", "kpi",
#     "test cases", "findings", "risk", "timeline", "schedule"
# ]

# def classify_section_role(section_name: str) -> str:
#     name = section_name.lower()
#     for role, signals in SECTION_ROLE_MAP.items():
#         if any(s in name for s in signals):
#             return role
#     return "BODY"

# def section_needs_table(section_name: str) -> bool:
#     name = section_name.lower()
#     return any(s in name for s in TABLE_SECTION_SIGNALS)


# # ═══════════════════════════════════════════════════════
# # VALIDATION PIPELINE
# # All validation in backend — never in prompt
# # ═══════════════════════════════════════════════════════

# class ValidationResult:
#     def __init__(self):
#         self.is_valid: bool = True
#         self.issues: List[dict] = []
#         self.missing_sections: List[str] = []
#         self.order_issues: List[str] = []
#         self.table_issues: List[str] = []
#         self.grounding_issues: List[str] = []
#         self.placeholder_issues: List[str] = []

#     def add_issue(self, issue_type: str, section: str, detail: str):
#         self.is_valid = False
#         self.issues.append({
#             "type": issue_type,
#             "section": section,
#             "detail": detail
#         })

#     def to_dict(self) -> dict:
#         return {
#             "is_valid": self.is_valid,
#             "total_issues": len(self.issues),
#             "issues": self.issues,
#             "missing_sections": self.missing_sections,
#             "order_issues": self.order_issues,
#             "table_issues": self.table_issues,
#             "grounding_issues": self.grounding_issues,
#             "placeholder_issues": self.placeholder_issues
#         }


# def _check_sections_present(
#     content: str,
#     sections: list,
#     result: ValidationResult
# ):
#     """Pass 1 — are all required sections present?"""
#     content_lower = content.lower()
#     for section in sections:
#         name_lower = section.section_name.lower()
#         # Flexible match — partial match allowed
#         if name_lower not in content_lower:
#             result.missing_sections.append(section.section_name)
#             result.add_issue(
#                 "MISSING_SECTION",
#                 section.section_name,
#                 f"Section '{section.section_name}' not found in document"
#             )


# def _check_section_order(
#     content: str,
#     sections: list,
#     result: ValidationResult
# ):
#     """Pass 2 — are sections in correct order?"""
#     positions = []
#     for section in sections:
#         name_lower = section.section_name.lower()
#         pos = content.lower().find(name_lower)
#         if pos != -1:
#             positions.append((section.section_name, pos))

#     for i in range(len(positions) - 1):
#         if positions[i][1] > positions[i + 1][1]:
#             issue = f"'{positions[i][0]}' appears after '{positions[i+1][0]}'"
#             result.order_issues.append(issue)
#             result.add_issue(
#                 "ORDER_VIOLATION",
#                 positions[i][0],
#                 issue
#             )


# def _check_table_sections(
#     content: str,
#     sections: list,
#     result: ValidationResult
# ):
#     """Pass 3 — sections that need tables, do they have them?"""
#     for section in sections:
#         if not section_needs_table(section.section_name):
#             continue

#         # Find section content
#         section_start = content.lower().find(section.section_name.lower())
#         if section_start == -1:
#             continue

#         # Get next 500 chars after section heading
#         section_chunk = content[section_start:section_start + 500]

#         # Check for table markers
#         has_table = "|" in section_chunk or "\t" in section_chunk

#         if not has_table:
#             result.table_issues.append(section.section_name)
#             result.add_issue(
#                 "MISSING_TABLE",
#                 section.section_name,
#                 f"Section '{section.section_name}' requires structured table format"
#             )


# def _check_answer_grounding(
#     content: str,
#     answers: dict,
#     result: ValidationResult
# ):
#     """Pass 4 — are key answer values present in document?"""
#     if not answers:
#         return

#     important_fields = [
#         "company_name", "candidate_name", "employee_name",
#         "job_title", "department", "joining_date"
#     ]

#     for field in important_fields:
#         value = answers.get(field, "").strip()
#         if value and len(value) > 2:
#             if value.lower() not in content.lower():
#                 result.grounding_issues.append(field)
#                 result.add_issue(
#                     "GROUNDING_FAILURE",
#                     field,
#                     f"Answer value '{value}' for field '{field}' not found in document"
#                 )


# def _check_placeholders(
#     content: str,
#     result: ValidationResult
# ):
#     """Pass 5 — are there unfilled placeholders?"""
#     patterns = [
#         r'\[MISSING_INFORMATION\]',
#         r'\[.*?\]',
#         r'\{.*?\}',
#         r'To be confirmed',
#         r'TBD',
#         r'\[INSERT',
#         r'\[ADD'
#     ]

#     for pattern in patterns:
#         found = re.findall(pattern, content, re.IGNORECASE)
#         if found:
#             for item in found:
#                 result.placeholder_issues.append(item)
#                 result.add_issue(
#                     "PLACEHOLDER_FOUND",
#                     "document",
#                     f"Unfilled placeholder found: {item}"
#                 )


# def _check_minimum_length(
#     content: str,
#     section_count: int,
#     result: ValidationResult
# ):
#     """Pass 6 — is document long enough?"""
#     word_count = len(content.split())
#     min_words = section_count * 80

#     if word_count < min_words:
#         result.add_issue(
#             "TOO_SHORT",
#             "document",
#             f"Document has {word_count} words. Minimum expected: {min_words}"
#         )


# def run_validation_pipeline(
#     content: str,
#     sections: list,
#     answers: dict = None
# ) -> ValidationResult:
#     """
#     Runs all 6 validation passes sequentially.
#     Returns ValidationResult with all issues found.
#     """
#     result = ValidationResult()

#     _check_sections_present(content, sections, result)
#     _check_section_order(content, sections, result)
#     _check_table_sections(content, sections, result)
#     _check_answer_grounding(content, answers or {}, result)
#     _check_placeholders(content, result)
#     _check_minimum_length(content, len(sections), result)

#     return result


# # ═══════════════════════════════════════════════════════
# # PDF RENDERER — uses reportlab, no special chars
# # ═══════════════════════════════════════════════════════

# def render_pdf(structured_sections: list, title: str) -> bytes:
#     """
#     Renders PDF from structured sections.
#     No ##, no **, no special chars — clean professional output.
#     Uses reportlab for full control.
#     """
#     from reportlab.lib.pagesizes import A4
#     from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
#     from reportlab.lib.units import cm
#     from reportlab.lib import colors
#     from reportlab.platypus import (
#         SimpleDocTemplate, Paragraph, Spacer,
#         Table, TableStyle, PageBreak
#     )
#     from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
#     import io

#     buffer = io.BytesIO()

#     doc = SimpleDocTemplate(
#         buffer,
#         pagesize=A4,
#         rightMargin=2.5 * cm,
#         leftMargin=2.5 * cm,
#         topMargin=2.5 * cm,
#         bottomMargin=2.5 * cm
#     )

#     styles = getSampleStyleSheet()

#     # Custom styles — no special chars
#     title_style = ParagraphStyle(
#         "DocTitle",
#         parent=styles["Title"],
#         fontSize=18,
#         spaceAfter=20,
#         alignment=TA_CENTER,
#         textColor=colors.HexColor("#1a1a1a"),
#         fontName="Helvetica-Bold"
#     )

#     heading_style = ParagraphStyle(
#         "SectionHeading",
#         parent=styles["Heading2"],
#         fontSize=13,
#         spaceBefore=16,
#         spaceAfter=8,
#         textColor=colors.HexColor("#1a1a1a"),
#         fontName="Helvetica-Bold",
#         borderPad=4,
#         backColor=colors.HexColor("#f5f5f5"),
#         leading=18
#     )

#     body_style = ParagraphStyle(
#         "BodyText",
#         parent=styles["Normal"],
#         fontSize=10,
#         leading=16,
#         spaceAfter=8,
#         alignment=TA_JUSTIFY,
#         fontName="Helvetica"
#     )

#     list_style = ParagraphStyle(
#         "ListItem",
#         parent=styles["Normal"],
#         fontSize=10,
#         leading=14,
#         spaceAfter=4,
#         leftIndent=20,
#         fontName="Helvetica"
#     )

#     story = []

#     # Document title
#     clean_title = _clean_text(title)
#     story.append(Paragraph(clean_title, title_style))
#     story.append(Spacer(1, 0.5 * cm))

#     for section in structured_sections:
#         heading = _clean_text(section.get("heading", ""))
#         content_type = section.get("content_type", "text")
#         content = section.get("content", "")
#         styling = section.get("styling", {})

#         # Section heading — bold, no ##
#         story.append(Paragraph(heading, heading_style))

#         if content_type == "text" and isinstance(content, str):
#             paragraphs = content.split("\n\n")
#             for para in paragraphs:
#                 clean = _clean_text(para.strip())
#                 if clean:
#                     story.append(Paragraph(clean, body_style))
#                     story.append(Spacer(1, 0.2 * cm))

#         elif content_type == "table" and isinstance(content, list):
#             if content:
#                 table_data = []
#                 for row in content:
#                     cells = row.get("cells", [])
#                     table_data.append([_clean_text(str(c)) for c in cells])

#                 if table_data:
#                     col_count = len(table_data[0])
#                     col_width = (A4[0] - 5 * cm) / col_count

#                     t = Table(
#                         table_data,
#                         colWidths=[col_width] * col_count,
#                         repeatRows=1
#                     )
#                     t.setStyle(TableStyle([
#                         ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a1a")),
#                         ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
#                         ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
#                         ("FONTSIZE", (0, 0), (-1, 0), 10),
#                         ("ALIGN", (0, 0), (-1, -1), "LEFT"),
#                         ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
#                         ("FONTSIZE", (0, 1), (-1, -1), 9),
#                         ("ROWBACKGROUNDS", (0, 1), (-1, -1),
#                          [colors.white, colors.HexColor("#f9f9f9")]),
#                         ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
#                         ("TOPPADDING", (0, 0), (-1, -1), 6),
#                         ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
#                         ("LEFTPADDING", (0, 0), (-1, -1), 8),
#                     ]))
#                     story.append(t)
#                     story.append(Spacer(1, 0.3 * cm))

#         elif content_type == "list" and isinstance(content, list):
#             for item in content:
#                 clean = _clean_text(str(item))
#                 story.append(Paragraph(f"- {clean}", list_style))
#             story.append(Spacer(1, 0.2 * cm))

#         if styling.get("page_break_after"):
#             story.append(PageBreak())

#     doc.build(story)
#     buffer.seek(0)
#     return buffer.read()


# def _clean_text(text: str) -> str:
#     """Remove markdown and special chars for PDF/DOCX rendering."""
#     if not text:
#         return ""
#     # Remove markdown
#     text = re.sub(r"#{1,6}\s*", "", text)
#     text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
#     text = re.sub(r"\*(.*?)\*", r"\1", text)
#     text = re.sub(r"`(.*?)`", r"\1", text)
#     # Remove special chars that break PDF
#     text = text.replace("\u2019", "'").replace("\u2018", "'")
#     text = text.replace("\u201c", '"').replace("\u201d", '"')
#     text = text.replace("\u2013", "-").replace("\u2014", "--")
#     # Encode safe
#     text = text.encode("latin-1", "replace").decode("latin-1")
#     return text.strip()


# # ═══════════════════════════════════════════════════════
# # DOCX RENDERER — python-docx, no special chars
# # ═══════════════════════════════════════════════════════

# def render_docx(structured_sections: list, title: str) -> bytes:
#     """
#     Renders DOCX from structured sections.
#     Section headings bold. No ##, no **, no special chars.
#     """
#     from docx import Document
#     from docx.shared import Pt, RGBColor, Cm
#     from docx.enum.text import WD_ALIGN_PARAGRAPH
#     import io

#     doc = Document()

#     # Page margins
#     for section in doc.sections:
#         section.top_margin = Cm(2.5)
#         section.bottom_margin = Cm(2.5)
#         section.left_margin = Cm(2.5)
#         section.right_margin = Cm(2.5)

#     # Document title
#     title_para = doc.add_heading(_clean_text(title), level=0)
#     title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
#     title_run = title_para.runs[0]
#     title_run.font.size = Pt(18)
#     title_run.font.color.rgb = RGBColor(0x1a, 0x1a, 0x1a)

#     for section_data in structured_sections:
#         heading = _clean_text(section_data.get("heading", ""))
#         content_type = section_data.get("content_type", "text")
#         content = section_data.get("content", "")

#         # Section heading — bold, no ##
#         heading_para = doc.add_paragraph()
#         heading_run = heading_para.add_run(heading)
#         heading_run.bold = True
#         heading_run.font.size = Pt(12)
#         heading_run.font.color.rgb = RGBColor(0x1a, 0x1a, 0x1a)
#         heading_para.space_before = Pt(16)
#         heading_para.space_after = Pt(6)

#         if content_type == "text" and isinstance(content, str):
#             for para_text in content.split("\n\n"):
#                 clean = _clean_text(para_text.strip())
#                 if clean:
#                     para = doc.add_paragraph(clean)
#                     para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
#                     para.style.font.size = Pt(10)

#         elif content_type == "table" and isinstance(content, list):
#             if content:
#                 rows = len(content)
#                 cols = len(content[0].get("cells", []))
#                 if rows > 0 and cols > 0:
#                     table = doc.add_table(rows=rows, cols=cols)
#                     table.style = "Table Grid"

#                     for i, row_data in enumerate(content):
#                         cells = row_data.get("cells", [])
#                         for j, cell_text in enumerate(cells):
#                             cell = table.cell(i, j)
#                             cell.text = _clean_text(str(cell_text))
#                             if i == 0:
#                                 run = cell.paragraphs[0].runs[0]
#                                 run.bold = True
#                                 run.font.size = Pt(9)
#                             else:
#                                 cell.paragraphs[0].runs[0].font.size = Pt(9)

#         elif content_type == "list" and isinstance(content, list):
#             for item in content:
#                 clean = _clean_text(str(item))
#                 doc.add_paragraph(clean, style="List Bullet")

#     buffer = io.BytesIO()
#     doc.save(buffer)
#     buffer.seek(0)
#     return buffer.read()




# # ═══════════════════════════════════════════════════════
# # MARKDOWN TO STRUCTURED SECTIONS
# # Converts LLM markdown output to section list
# # ═══════════════════════════════════════════════════════

# def markdown_to_structured(content: str, sections: list) -> list:
#     """
#     Converts markdown document to structured section list.
#     Used when LLM returns markdown instead of JSON.
#     """
#     structured = []
#     lines = content.split("\n")
#     current_section = None
#     current_lines = []

#     def flush_section():
#         if current_section:
#             body = "\n".join(current_lines).strip()
#             role = classify_section_role(current_section)
#             content_type = "table" if section_needs_table(current_section) and "|" in body else "text"

#             if content_type == "table":
#                 structured.append({
#                     "heading": current_section,
#                     "content_type": "table",
#                     "content": _parse_markdown_table(body),
#                     "styling": {"alignment": "left", "font_weight": "normal", "page_break_after": False}
#                 })
#             else:
#                 structured.append({
#                     "heading": current_section,
#                     "content_type": "text",
#                     "content": _clean_text(body),
#                     "styling": {
#                         "alignment": "center" if role == "SIGN_OFF" else "justify",
#                         "font_weight": "normal",
#                         "page_break_after": False
#                     }
#                 })

#     for line in lines:
#         if line.startswith("## "):
#             flush_section()
#             current_section = line[3:].strip()
#             current_lines = []
#         elif line.startswith("# "):
#             flush_section()
#             current_section = line[2:].strip()
#             current_lines = []
#         else:
#             current_lines.append(line)

#     flush_section()
#     return structured


# def _parse_markdown_table(text: str) -> list:
#     """Parse markdown table into structured rows."""
#     rows = []
#     for line in text.split("\n"):
#         if line.startswith("|") and "---" not in line:
#             cells = [c.strip() for c in line.split("|") if c.strip()]
#             if cells:
#                 rows.append({"cells": cells})
#     return rows



# # ═══════════════════════════════════════════════════════
# # ENHANCED PROMPT SERVICE (Updated)
# # ═══════════════════════════════════════════════════════
# def build_prompt(
#     db: Session,
#     department_name: str,
#     template_name: str,
#     template_description: str,
#     template_id: int,
#     answers: Dict[str, str],
#     company: Optional[Dict] = None
# ) -> str:
    
#     if company:
#         company_name = company.get("name", "")
#         tone = company.get("tone", "Professional")
#         industry = company.get("industry", "")
#         values = company.get("values", "")
#     else:
#         company_name = ""
#         tone = "Professional"
#         industry = ""
#         values = ""

#     company_context = f"""
# Company Context:
# - Name: {company_name or 'Our Company'}
# - Tone: {tone}
# - Industry: {industry}
# - Core Values: {values}
# """.strip()

#     sections = crud.get_sections_by_template(db, template_id)
#     sections_list = "\n".join([f"- {s.section_name}" for s in sections])

#     answers_formatted = "\n".join([
#         f"{key}: {value}" for key, value in answers.items() if value and str(value).strip()
#     ])

#     prompt = f"""You are an expert senior business document writer with 15+ years of experience in crafting high-quality corporate documents.

# Create a **premium, detailed, and professional** {template_name} for {company_name or department_name}.

# {company_context}

# Document Requirements:
# - Department: {department_name}
# - Template Type: {template_name}
# - Description: {template_description}

# Required Sections (in exact order):
# {sections_list}

# Provided Information:
# {answers_formatted or "No additional details provided."}

# CRITICAL INSTRUCTIONS:
# - Make every section substantial and detailed — do not write short or generic content.
# - Use formal yet engaging language suitable for SaaS / corporate environment.
# - Expand each section with proper explanations, context, and value.
# - For any financial or breakdown sections, use well-formatted markdown tables.
# - Never hallucinate information. If data is missing, write professionally without fabricating.
# - Maintain consistent {tone.lower()} tone throughout the document.
# - don't use Markdown formatting also for tables where applicable dont use | markdown format .

# Write a high-quality, comprehensive, and client-ready document now."""

#     return prompt


# # ═══════════════════════════════════════════════════════
# # UPDATED PREVIEW DOCUMENT (Strong Company Context)
# # ═══════════════════════════════════════════════════════
# def save_document(
#     db: Session,
#     session_id: UUID,
#     template_id: int,
#     title: str,
#     content: str,
#     structured_sections: list = None
# ):
#     """Save generated document to database"""
#     doc = crud.save_generated_document(
#         db=db,
#         session_id=session_id,
#         template_id=template_id,
#         title=title,
#         content=content
#     )

#     if structured_sections:
#         doc.structured_json = json.dumps(structured_sections)
#         db.commit()

#     return doc


# def preview_document(
#     db: Session,
#     department_name: str,
#     template_name: str,
#     template_description: str,
#     template_id: int,
#     answers: Dict[str, str],
#     company: Optional[Dict] = None
# ) -> str:
#     """Generate full document with strong company context"""
#     prompt = prompt_service.build_prompt(
#         db=db,
#         department_name=department_name,
#         template_name=template_name,
#         template_description=template_description,
#         template_id=template_id,
#         answers=answers,
#         company=company
#     )

#     system_prompt = (
#         f"You are a professional business document writer generate a good quality document that dont provide any repeat content after & before  regeneration. "
#         f"Maintain consistent {company.get('tone', 'Professional') if company else 'Professional'} tone. "
#         f"Return clean proper section headings all sections should have proper bold heading with no markdown."
#     )

#     return llm_service.generate_with_llm(prompt=prompt, system_prompt=system_prompt)


# def regenerate_section(
#     db: Session,
#     document_id: int,
#     section_name: str,
#     answers: dict = None,
#     feedback: str = None,
#     company: dict = None
# ) -> dict:
#     """Regenerate ONLY one specific section with strong context """
    
#     doc = crud.get_document_by_id(db, document_id)
#     if not doc:
#         return {"error": "Document not found"}

#     template = crud.get_template_by_id(db, doc.template_id)
#     session = crud.get_session_by_id(db, doc.session_id)
#     department = crud.get_department_by_id(db, session.department_id)

#     # Strong Company Context
#     if company:
#         company_name = company.get("name", "")
#         tone = company.get("tone", "Professional")
#         industry = company.get("industry", "")
#         values = company.get("values", "")
#         location = company.get("location", "")
#     else:
#         company_name = ""
#         tone = "Professional"
#         industry = ""
#         values = ""
#         location = ""

#     company_context_text = f"""
# Company: {company_name}
# Tone: {tone}
# Industry: {industry}
# Location: {location}
# Key Values: {values}
# """.strip()

#     role = classify_section_role(section_name)
#     needs_table = section_needs_table(section_name)

#     role_instructions = {
#     "HEADER": "Keep it concise, formal, and factual. Include only exact values like dates, names, reference numbers, version, and document title. No explanations needed.",
#     "OPENER": "Write 2-3 detailed paragraphs 80- 120 words explaining purpose, context, and importance.",
#     "OBLIGATION": "Use numbered or bulleted points. Use formal language with 'must', 'shall', 'will be responsible for'.",
#     "EVIDENCE": "Be data-driven and analytical. Include specific findings, metrics, and tables where possible. Write in detail.",
#     "BODY": "Write comprehensive and detailed content. Expand ideas properly with explanations and examples . Aim for 70-100+ words per major point.",
#     "CLOSURE": "Provide clear, actionable recommendations with responsible persons and timelines.",
#     "SIGN_OFF": "Formal sign-off block only. Include names, designations, and date lines. Keep it clean and professional 60 - 90 words.",
#     "STRUCTURAL": "Provide precise, clear definitions. Use numbered or bulleted lists for better readability ."
# }
#     role_instruction = role_instructions.get(role, "Write clearly and professionally in very detailed format .")

#     # Original document for consistency
#     original_content = doc.content[:3500] if doc.content else ""

#     table_note = "Use table format for structured data." if needs_table else ""
#     feedback_note = f"\nUser instruction: {feedback}" if feedback else ""

#     answers_formatted = "\n".join(
#         [f" {k}: {v}" for k, v in (answers or {}).items() if v]
#     ) or " Use professional defaults."

#     system_prompt = (
#         f"You are a professional business document writer for {company_name or department.name}. "
#         f"Maintain {tone} tone. "
#         f"Company context: {company_context_text}\n"
#         f"Return clean text only — no markdown."
#     )

#     section_prompt = f"""Document Name: {template.name}
# Department: {department.name}
# Company Context:
# {company_context_text}

# Original Document (for style consistency):
# {original_content}

# Section to Regenerate: {section_name}
# Role: {role} — {role_instruction}
# {table_note}
# {feedback_note}

# Relevant Information:
# {answers_formatted}

# === STRICT INSTRUCTIONS ===
# - Write ONLY content for section "{section_name}".
# - Do NOT output any other sections.
# - Do NOT repeat the full document.
# - Match the style, tone and formality of the original document.
# - Return clean professional text only.

# Generate now:"""

#     new_content = llm_service.generate_with_llm(section_prompt, system_prompt)
#     new_content_clean = _clean_text(new_content)

#     updated = crud.update_document_section(
#         db, document_id, section_name, new_content_clean
#     )

#     return {
#         "document_id": document_id,
#         "section_name": section_name,
#         "updated_content": updated.content if updated else new_content_clean,
#         "status": "regenerated"
#     }


# def validate_document(
#     db: Session,
#     document_id: int,
#     answers: dict = None
# ) -> dict:
#     """Run full validation pipeline"""
#     doc = crud.get_document_by_id(db, document_id)
#     if not doc:
#         return {"error": "Document not found"}

#     sections = crud.get_sections_by_template(db, doc.template_id)
#     result = run_validation_pipeline(doc.content, sections, answers)

#     status = "validated" if result.is_valid else "needs_review"
#     notes = json.dumps(result.to_dict())

#     crud.update_document_validation(db, document_id, status, notes)

#     return {
#         "document_id": document_id,
#         **result.to_dict()
#     }


# def get_all_versions(db: Session, session_id: UUID):
#     return crud.get_documents_by_session(db, session_id)

from pydoc import doc

from sqlalchemy.orm import Session
from uuid import UUID
from typing import Dict, Optional, List
from backend.database import crud
from backend.services import prompt_service, llm_service
import json
import re
import io
from datetime import date

# ═══════════════════════════════════════════════════════
# SECTION INTELLIGENCE LAYER
# ═══════════════════════════════════════════════════════
SECTION_ROLE_MAP = {
    "HEADER": ["letterhead", "date", "title", "reference", "id", "version",
               "parties", "candidate", "company letterhead", "heading"],
    "OPENER": ["purpose", "scope", "overview", "background",
               "executive summary", "introduction", "objective"],
    "STRUCTURAL": ["definitions", "methodology", "classification",
                   "types", "categories", "framework"],
    "OBLIGATION": ["responsibilities", "obligations", "requirements",
                   "policy", "rules", "clause", "compliance"],
    "EVIDENCE": ["findings", "results", "assessment", "analysis",
                 "metrics", "test", "defects", "vulnerability", "risk"],
    "BODY": ["compensation", "breakdown", "details", "description",
             "content", "information", "terms", "conditions"],
    "CLOSURE": ["recommendations", "next steps", "action items",
                "conclusion", "improvement", "mitigation"],
    "SIGN_OFF": ["approval", "signature", "sign off", "acknowledgement",
                 "authorization", "sign-off", "closure"]
}

TABLE_SECTION_SIGNALS = [
    "compensation", "breakdown", "ctc", "salary", "budget",
    "invoice", "pricing", "comparison", "metrics", "kpi",
    "test cases", "findings", "risk", "timeline", "schedule",
    "gross", "deductions", "earnings"
]


def classify_section_role(section_name: str) -> str:
    name = section_name.lower()
    for role, signals in SECTION_ROLE_MAP.items():
        if any(s in name for s in signals):
            return role
    return "BODY"


def section_needs_table(section_name: str) -> bool:
    name = section_name.lower()
    return any(s in name for s in TABLE_SECTION_SIGNALS)


# ═══════════════════════════════════════════════════════
# TEXT CLEANER
# ═══════════════════════════════════════════════════════
def _clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"#{1,6}\s*", "", text)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"`(.*?)`", r"\1", text)
    text = re.sub(r"^-{3,}$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^={3,}$", "", text, flags=re.MULTILINE)
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "--")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.encode("latin-1", "replace").decode("latin-1")
    return text.strip()


def _replace_placeholders(text: str) -> str:
    """Replace any remaining placeholders with today's date or empty."""
    today = date.today().strftime("%d %B %Y")
    text = re.sub(r'\[DATE\]|\[date\]|\[Date\]', today, text)
    text = re.sub(r'\[TODAY\]|\[today\]', today, text)
    text = re.sub(r'\[YEAR\]', str(date.today().year), text)
    text = re.sub(r'\[MONTH\]', date.today().strftime("%B"), text)
    text = re.sub(r'\[MISSING_INFORMATION\]', 'Not Provided', text)
    text = re.sub(r'\[TBD\]|\bTBD\b', 'To be confirmed', text)
    text = re.sub(r'\[INSERT.*?\]', '', text)
    text = re.sub(r'\[ADD.*?\]', '', text)
    return text


# ═══════════════════════════════════════════════════════
# STRUCTURED JSON GENERATION PIPELINE
# ═══════════════════════════════════════════════════════
def generate_structured_document(
    db,
    department_name: str,
    template_name: str,
    template_description: str,
    template_id: int,
    answers: dict,
    company: dict = None
) -> dict:
    """
    Main pipeline:
    1. Build structured prompt
    2. Call LLM → get JSON
    3. Validate JSON structure
    4. Replace any placeholders
    5. Return clean structured dict
    """
    user_prompt = prompt_service.build_structured_prompt(
        db=db,
        department_name=department_name,
        template_name=template_name,
        template_description=template_description,
        template_id=template_id,
        answers=answers,
        company=company
    )

    system = prompt_service.STRUCTURED_SYSTEM_PROMPT.format(
        today=date.today().strftime("%d %B %Y")
    )

    raw = llm_service.generate_structured_document(
        system_prompt=system,
        user_prompt=user_prompt
    )

    # Validate and clean
    cleaned = _clean_structured_json(raw, template_id, db)
    return cleaned


def _clean_structured_json(raw: dict, template_id: int, db) -> dict:
    """
    Post-process structured JSON:
    1. Clean all text values — no markdown
    2. Replace all placeholders
    3. Ensure all required sections present
    4. Fix empty table cells
    """
    sections = crud.get_sections_by_template(db, template_id)
    required_names = [s.section_name for s in sections]

    cleaned_sections = []
    for section in raw.get("sections", []):
        heading = _clean_text(section.get("heading", ""))
        content_type = section.get("content_type", "text")
        content = section.get("content", "")
        styling = section.get("styling", {
            "alignment": "justify",
            "font_weight": "normal",
            "page_break_after": False
        })

        # Clean content based on type
        if content_type == "text" and isinstance(content, str):
            content = _clean_text(_replace_placeholders(content))

        elif content_type == "table" and isinstance(content, list):
            cleaned_rows = []
            for row in content:
                if isinstance(row, dict) and "cells" in row:
                    cells = [
                        _clean_text(_replace_placeholders(str(c)))
                        for c in row["cells"]
                    ]
                    cleaned_rows.append({"cells": cells})
            content = cleaned_rows

        elif content_type == "list" and isinstance(content, list):
            content = [
                _clean_text(_replace_placeholders(str(item)))
                for item in content
                if str(item).strip()
            ]

        # Count words
        if isinstance(content, str):
            word_count = len(content.split())
        else:
            word_count = 0

        cleaned_sections.append({
            "id": section.get("id", f"section_{len(cleaned_sections)+1}"),
            "heading": heading,
            "content_type": content_type,
            "content": content,
            "styling": styling,
            "word_count": word_count
        })

    # Check missing sections — add empty placeholder
    generated_headings = [s["heading"].lower() for s in cleaned_sections]
    for required in required_names:
        if not any(required.lower() in h for h in generated_headings):
            cleaned_sections.append({
                "id": f"section_missing_{required[:10]}",
                "heading": required,
                "content_type": "text",
                "content": "Content to be provided.",
                "styling": {"alignment": "justify", "font_weight": "normal", "page_break_after": False},
                "word_count": 0
            })

    raw["sections"] = cleaned_sections
    return raw


def structured_to_plain_text(structured: dict) -> str:
    """
    Converts structured JSON to clean plain text.
    No markdown. Section headings are plain text.
    Used for DB storage and Streamlit display.
    """
    lines = []
    for section in structured.get("sections", []):
        heading = section.get("heading", "")
        content_type = section.get("content_type", "text")
        content = section.get("content", "")

        if heading:
            lines.append(f"\n{heading}\n")

        if content_type == "text" and isinstance(content, str):
            lines.append(f"{content}\n")

        elif content_type == "table" and isinstance(content, list):
            if content:
                for row in content:
                    cells = row.get("cells", [])
                    lines.append("  " + "   |   ".join(cells))
                lines.append("")

        elif content_type == "list" and isinstance(content, list):
            for item in content:
                lines.append(f"  - {item}")
            lines.append("")

        lines.append("")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════
# VALIDATION PIPELINE — 6 passes + LLM Judge
# ═══════════════════════════════════════════════════════
class ValidationResult:
    def __init__(self):
        self.is_valid: bool = True
        self.issues: List[dict] = []
        self.missing_sections: List[str] = []
        self.order_issues: List[str] = []
        self.table_issues: List[str] = []
        self.grounding_issues: List[str] = []
        self.placeholder_issues: List[str] = []
        self.llm_judge_result: dict = {}

    def add_issue(self, issue_type: str, section: str, detail: str):
        self.is_valid = False
        self.issues.append({
            "type": issue_type,
            "section": section,
            "detail": detail
        })

    def to_dict(self) -> dict:
        return {
            "is_valid": self.is_valid,
            "total_issues": len(self.issues),
            "issues": self.issues,
            "missing_sections": self.missing_sections,
            "order_issues": self.order_issues,
            "table_issues": self.table_issues,
            "grounding_issues": self.grounding_issues,
            "placeholder_issues": self.placeholder_issues,
            "llm_judge_result": self.llm_judge_result
        }


PLACEHOLDER_PATTERNS = [
    r'\[DATE\]', r'\[date\]', r'\[Date\]',
    r'\[NAME\]', r'\[name\]',
    r'\[INSERT.*?\]', r'\[ADD.*?\]',
    r'\[MISSING_INFORMATION\]',
    r'\[TBD\]', r'\bTBD\b',
    r'\[.*?PLACEHOLDER.*?\]'
]


def _check_sections_present(structured, sections, result):
    """Pass 1 — check all required sections in structured JSON."""
    generated = [
        s.get("heading", "").lower()
        for s in structured.get("sections", [])
    ]
    for section in sections:
        name_lower = section.section_name.lower()
        if not any(name_lower in g for g in generated):
            result.missing_sections.append(section.section_name)
            result.add_issue(
                "MISSING_SECTION", section.section_name,
                f"Section '{section.section_name}' not in structured output"
            )


def _check_section_order(structured, sections, result):
    """Pass 2 — check section order matches template."""
    generated_headings = [
        s.get("heading", "").lower()
        for s in structured.get("sections", [])
    ]
    template_order = [s.section_name.lower() for s in sections]

    found_positions = []
    for name in template_order:
        for i, heading in enumerate(generated_headings):
            if name in heading:
                found_positions.append((name, i))
                break

    for i in range(len(found_positions) - 1):
        if found_positions[i][1] > found_positions[i+1][1]:
            issue = f"'{found_positions[i][0]}' appears after '{found_positions[i+1][0]}'"
            result.order_issues.append(issue)
            result.add_issue("ORDER_VIOLATION", found_positions[i][0], issue)


def _check_table_sections(structured, sections, result):
    """Pass 3 — sections that need tables must have table content_type."""
    section_map = {
        s.get("heading", "").lower(): s
        for s in structured.get("sections", [])
    }

    for section in sections:
        if not section_needs_table(section.section_name):
            continue

        name_lower = section.section_name.lower()
        matched = next(
            (v for k, v in section_map.items() if name_lower in k),
            None
        )

        if not matched:
            continue

        if matched.get("content_type") != "table":
            result.table_issues.append(section.section_name)
            result.add_issue(
                "MISSING_TABLE", section.section_name,
                f"'{section.section_name}' must be table type but got '{matched.get('content_type')}'"
            )
        elif not matched.get("content", []):
            result.table_issues.append(section.section_name)
            result.add_issue(
                "EMPTY_TABLE", section.section_name,
                f"Table in '{section.section_name}' has no rows"
            )


def _check_placeholders(structured, result):
    """Pass 4 — scan all text content for unfilled placeholders."""
    for section in structured.get("sections", []):
        content = section.get("content", "")
        heading = section.get("heading", "")

        if isinstance(content, str):
            for pattern in PLACEHOLDER_PATTERNS:
                found = re.findall(pattern, content, re.IGNORECASE)
                for item in found:
                    result.placeholder_issues.append(item)
                    result.add_issue(
                        "PLACEHOLDER_FOUND", heading,
                        f"Unfilled placeholder '{item}' in section '{heading}'"
                    )

        elif isinstance(content, list):
            for row in content:
                if isinstance(row, dict):
                    for cell in row.get("cells", []):
                        for pattern in PLACEHOLDER_PATTERNS:
                            found = re.findall(pattern, str(cell), re.IGNORECASE)
                            for item in found:
                                result.placeholder_issues.append(item)
                                result.add_issue(
                                    "PLACEHOLDER_FOUND", heading,
                                    f"Unfilled placeholder '{item}' in table"
                                )


def _check_answer_grounding(structured, answers, result):
    """Pass 5 — verify key answer values appear in document."""
    if not answers:
        return

    all_text = " ".join([
        section.get("content", "") if isinstance(section.get("content", ""), str) else ""
        for section in structured.get("sections", [])
    ]).lower()

    important_fields = [
        "company_name", "candidate_name", "employee_name",
        "job_title", "department", "joining_date"
    ]

    for field in important_fields:
        value = answers.get(field, "").strip()
        if value and len(value) > 2 and value.lower() != "not provided":
            if value.lower() not in all_text:
                result.grounding_issues.append(field)
                result.add_issue(
                    "GROUNDING_FAILURE", field,
                    f"Value '{value}' for '{field}' not found in document"
                )


def _check_minimum_content(structured, sections, result):
    """Pass 6 — check minimum content per section."""
    for section in structured.get("sections", []):
        content = section.get("content", "")
        heading = section.get("heading", "")

        if isinstance(content, str) and len(content.split()) < 20:
            role = classify_section_role(heading)
            if role not in ("HEADER", "SIGN_OFF"):
                result.add_issue(
                    "TOO_SHORT", heading,
                    f"Section '{heading}' has only {len(content.split())} words"
                )


def _llm_as_judge(structured: dict, template_name: str, department: str) -> dict:
    """
    LLM Judge — evaluates document quality.
    Returns score + specific feedback.
    Fast check — uses JSON mode.
    """
    # Sample first 3 sections for efficiency
    sample_sections = structured.get("sections", [])[:4]
    sample_text = "\n\n".join([
        f"{s.get('heading', '')}: {str(s.get('content', ''))[:300]}"
        for s in sample_sections
    ])

    judge_prompt = f"""You are a strict document quality evaluator.

Evaluate this {template_name} document excerpt for {department} department.

Document excerpt:
{sample_text}

Evaluate on these criteria:
1. Professional tone (0-10)
2. Content completeness (0-10)
3. No placeholder text (0-10)
4. Factual consistency (0-10)
5. Format appropriateness (0-10)

Return ONLY this JSON:
{{
  "overall_score": 0-10,
  "tone_score": 0-10,
  "completeness_score": 0-10,
  "placeholder_score": 0-10,
  "consistency_score": 0-10,
  "format_score": 0-10,
  "passed": true or false,
  "main_issue": "one line summary of biggest issue or empty string",
  "recommendation": "one line improvement suggestion or empty string"
}}"""

    judge_system = """You are a document quality judge. 
Score documents strictly. 
Return ONLY valid JSON — no text before or after."""

    try:
        result_str = llm_service.generate_with_llm_json(
            user_prompt=judge_prompt,
            system_prompt=judge_system
        )
        result = json.loads(result_str)
        result["passed"] = result.get("overall_score", 0) >= 7
        return result
    except Exception:
        return {
            "overall_score": 0,
            "passed": False,
            "main_issue": "LLM judge failed to evaluate",
            "recommendation": "Manual review required"
        }


def run_validation_pipeline(
    structured: dict,
    sections: list,
    answers: dict = None,
    template_name: str = "",
    department: str = "",
    run_llm_judge: bool = True
) -> ValidationResult:
    """
    Runs all validation passes on structured JSON.
    Pass 1: sections present
    Pass 2: section order
    Pass 3: table sections
    Pass 4: placeholders
    Pass 5: answer grounding
    Pass 6: minimum content
    Pass 7: LLM judge (optional)
    """
    result = ValidationResult()

    _check_sections_present(structured, sections, result)
    _check_section_order(structured, sections, result)
    _check_table_sections(structured, sections, result)
    _check_placeholders(structured, result)
    _check_answer_grounding(structured, answers or {}, result)
    _check_minimum_content(structured, sections, result)

    if run_llm_judge and template_name:
        result.llm_judge_result = _llm_as_judge(
            structured, template_name, department
        )
        if not result.llm_judge_result.get("passed", True):
            result.is_valid = False
            result.add_issue(
                "LLM_JUDGE_FAILED",
                "document",
                result.llm_judge_result.get("main_issue", "Quality check failed")
            )

    return result


# ═══════════════════════════════════════════════════════
# PDF RENDERER — reportlab, cover page, structured JSON
# ═══════════════════════════════════════════════════════
def render_pdf(
    structured_sections: list,
    title: str,
    company: dict = None,
    department: str = ""
) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer,
        Table, TableStyle, PageBreak, HRFlowable
    )
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY

    buffer = io.BytesIO()
    W = A4[0] - 5 * cm

    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=2.5*cm, leftMargin=2.5*cm,
        topMargin=2.5*cm, bottomMargin=2.5*cm,
        title=title
    )

    styles = getSampleStyleSheet()

    cover_title = ParagraphStyle("CoverTitle", fontSize=24, fontName="Helvetica-Bold",
        textColor=colors.HexColor("#1a1a1a"), alignment=TA_CENTER, spaceAfter=12, leading=32)
    cover_sub = ParagraphStyle("CoverSub", fontSize=13, fontName="Helvetica",
        textColor=colors.HexColor("#555555"), alignment=TA_CENTER, spaceAfter=8)
    cover_meta = ParagraphStyle("CoverMeta", fontSize=10, fontName="Helvetica",
        textColor=colors.HexColor("#888888"), alignment=TA_CENTER, spaceAfter=6)
   
    heading_style = ParagraphStyle(
    "SectionHeading", fontSize=11, fontName="Helvetica-Bold",
    textColor=colors.HexColor("#1a1a1a"),
    spaceBefore=20, spaceAfter=8, leading=16,
    leftIndent=0,
    borderPadding=(6, 8, 6, 8),
    backColor=colors.HexColor("#f0f0f0"),
    borderColor=colors.HexColor("#cccccc"),
    borderWidth=0
)
    body_style = ParagraphStyle(
    "Body", fontSize=10, fontName="Helvetica",
    leading=17, spaceAfter=8, spaceBefore=4,
    alignment=TA_JUSTIFY,
    firstLineIndent=0
)
    list_style = ParagraphStyle(
    "List", fontSize=10, fontName="Helvetica",
    leading=15, spaceAfter=4, leftIndent=20,
    bulletIndent=8
)
    story = []

    # Cover page
    story.append(Spacer(1, 3*cm))
    company_name = company.get("name", "") if company else ""
    if company_name:
        story.append(Paragraph(_clean_text(company_name), cover_sub))
        story.append(Spacer(1, 0.5*cm))

    story.append(HRFlowable(width=W, thickness=2,
        color=colors.HexColor("#1a1a1a"), spaceAfter=16))
    story.append(Paragraph(_clean_text(title), cover_title))
    story.append(HRFlowable(width=W, thickness=1,
        color=colors.HexColor("#cccccc"), spaceBefore=16, spaceAfter=20))

    if department:
        story.append(Paragraph(f"Department: {_clean_text(department)}", cover_meta))
    if company:
        if company.get("industry"):
            story.append(Paragraph(f"Industry: {_clean_text(company.get('industry',''))}", cover_meta))
        if company.get("location"):
            story.append(Paragraph(f"Location: {_clean_text(company.get('location',''))}", cover_meta))
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph(f"Generated: {date.today().strftime('%d %B %Y')}", cover_meta))
    story.append(Spacer(1, 4*cm))
    story.append(PageBreak())

    # Document sections
    for section in structured_sections:
        heading = _clean_text(section.get("heading", ""))
        content_type = section.get("content_type", "text")
        content = section.get("content", "")
        styling = section.get("styling", {})
        align_map = {"left": TA_LEFT, "center": TA_CENTER, "justify": TA_JUSTIFY}
        align = align_map.get(styling.get("alignment", "justify"), TA_JUSTIFY)

        if heading:
            story.append(Paragraph(heading, heading_style))
            story.append(Spacer(1, 0.2*cm))

        if content_type == "text" and isinstance(content, str):
            para_style = ParagraphStyle("DynBody", parent=body_style, alignment=align)
    # Normalize: collapse single newlines within a paragraph
    normalized = re.sub(r'(?<!\n)\n(?!\n)', ' ', content)
    paragraphs = [p.strip() for p in normalized.split("\n\n") if p.strip()]
    for para in paragraphs:
        clean = _clean_text(para)
        if clean and len(clean) > 3:
            story.append(Paragraph(clean, para_style))
            story.append(Spacer(1, 0.2*cm))
        elif content_type == "table" and isinstance(content, list):
            if content:
                table_data = [
                    [_clean_text(str(c)) for c in row.get("cells", [])]
                    for row in content
                ]
                if table_data and table_data[0]:
                    col_count = len(table_data[0])
                    col_width = W / col_count
                    t = Table(table_data, colWidths=[col_width]*col_count, repeatRows=1)
                    t.setStyle(TableStyle([
                        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#2c2c2c")),
                        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
                        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
                        ("FONTSIZE", (0,0), (-1,0), 9),
                        ("TOPPADDING", (0,0), (-1,0), 7),
                        ("BOTTOMPADDING", (0,0), (-1,0), 7),
                        ("FONTNAME", (0,1), (-1,-1), "Helvetica"),
                        ("FONTSIZE", (0,1), (-1,-1), 9),
                        ("TOPPADDING", (0,1), (-1,-1), 5),
                        ("BOTTOMPADDING", (0,1), (-1,-1), 5),
                        ("LEFTPADDING", (0,0), (-1,-1), 8),
                        ("RIGHTPADDING", (0,0), (-1,-1), 8),
                        ("ROWBACKGROUNDS", (0,1), (-1,-1),
                         [colors.white, colors.HexColor("#f9f9f9")]),
                        ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#dddddd")),
                        ("ALIGN", (0,0), (-1,-1), "LEFT"),
                        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
                    ]))
                    story.append(t)
                    story.append(Spacer(1, 0.4*cm))

        elif content_type == "list" and isinstance(content, list):
            for item in content:
                clean = _clean_text(str(item))
                if clean:
                    story.append(Paragraph(f"- {clean}", list_style))
            story.append(Spacer(1, 0.3*cm))

        if styling.get("page_break_after"):
            story.append(PageBreak())
        story.append(Spacer(1, 0.3*cm))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()


# ═══════════════════════════════════════════════════════
# DOCX RENDERER — python-docx, cover page, proper spacing
# ═══════════════════════════════════════════════════════
def render_docx(
    structured_sections: list,
    title: str,
    company: dict = None,
    department: str = ""
) -> bytes:
    from docx import Document
    from docx.shared import Pt, RGBColor, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    doc = Document()

    for sec in doc.sections:
        sec.top_margin = Cm(2.5)
        sec.bottom_margin = Cm(2.5)
        sec.left_margin = Cm(2.5)
        sec.right_margin = Cm(2.5)

    def add_para(text, bold=False, size=10,
                 align=WD_ALIGN_PARAGRAPH.LEFT,
                 sb=0, sa=6, color=None):
        p = doc.add_paragraph()
        p.alignment = align
        p.paragraph_format.space_before = Pt(sb)
        p.paragraph_format.space_after = Pt(sa)
        run = p.add_run(_clean_text(text))
        run.bold = bold
        run.font.size = Pt(size)
        if color:
            run.font.color.rgb = RGBColor(*color)
        return p

    # Cover page
    doc.add_paragraph()
    doc.add_paragraph()
    doc.add_paragraph()

    company_name = company.get("name", "") if company else ""
    if company_name:
        add_para(company_name, size=13, align=WD_ALIGN_PARAGRAPH.CENTER,
                 sa=8, color=(85, 85, 85))

    # HR line
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(12)
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "12")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "1a1a1a")
    pBdr.append(bottom)
    pPr.append(pBdr)

    add_para(title, bold=True, size=22,
             align=WD_ALIGN_PARAGRAPH.CENTER,
             sb=12, sa=12, color=(26, 26, 26))

    if department:
        add_para(f"Department: {department}", size=10,
                 align=WD_ALIGN_PARAGRAPH.CENTER,
                 sa=4, color=(100, 100, 100))
    if company:
        if company.get("industry"):
            add_para(f"Industry: {company.get('industry','')}",
                     size=10, align=WD_ALIGN_PARAGRAPH.CENTER,
                     sa=4, color=(100, 100, 100))
    add_para(f"Generated: {date.today().strftime('%d %B %Y')}",
             size=10, align=WD_ALIGN_PARAGRAPH.CENTER,
             sa=4, color=(100, 100, 100))

    doc.add_page_break()

    # Document sections
    align_map = {
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY
    }

    for section_data in structured_sections:
        heading = _clean_text(section_data.get("heading", ""))
        content_type = section_data.get("content_type", "text")
        content = section_data.get("content", "")
        styling = section_data.get("styling", {})
        para_align = align_map.get(styling.get("alignment", "justify"),
                                   WD_ALIGN_PARAGRAPH.JUSTIFY)

        if heading:
            h = doc.add_paragraph()
            h.paragraph_format.space_before = Pt(16)
            h.paragraph_format.space_after = Pt(6)
            run = h.add_run(heading)
            run.bold = True
            run.font.size = Pt(12)
            run.font.color.rgb = RGBColor(26, 26, 26)

        if content_type == "text" and isinstance(content, str):
            for para_text in content.split("\n\n"):
                clean = _clean_text(para_text.strip())
                if not clean:
                    continue
                p = doc.add_paragraph()
                p.alignment = para_align
                p.paragraph_format.space_before = Pt(2)
                p.paragraph_format.space_after = Pt(6)
                run = p.add_run(clean)
                run.font.size = Pt(10)

        elif content_type == "table" and isinstance(content, list):
            if content:
                rows = len(content)
                cols = max((len(r.get("cells", [])) for r in content), default=0)
                if rows > 0 and cols > 0:
                    table = doc.add_table(rows=rows, cols=cols)
                    table.style = "Table Grid"
                    for i, row_data in enumerate(content):
                        cells = row_data.get("cells", [])
                        for j in range(cols):
                            cell_text = cells[j] if j < len(cells) else ""
                            cell = table.cell(i, j)
                            cell.text = _clean_text(str(cell_text))
                            p = cell.paragraphs[0]
                            p.paragraph_format.space_before = Pt(3)
                            p.paragraph_format.space_after = Pt(3)
                            if p.runs:
                                p.runs[0].font.size = Pt(9)
                                p.runs[0].bold = (i == 0)
                    doc.add_paragraph().paragraph_format.space_after = Pt(8)

        elif content_type == "list" and isinstance(content, list):
            for item in content:
                clean = _clean_text(str(item))
                if clean:
                    p = doc.add_paragraph(style="List Bullet")
                    p.paragraph_format.space_before = Pt(1)
                    p.paragraph_format.space_after = Pt(3)
                    run = p.add_run(clean)
                    run.font.size = Pt(10)

        doc.add_paragraph().paragraph_format.space_after = Pt(4)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.read()


# ═══════════════════════════════════════════════════════
# CORE OPERATIONS
# ═══════════════════════════════════════════════════════
# def save_document(
#     db: Session,
#     session_id: UUID,
#     template_id: int,
#     title: str,
#     content: str,
#     structured_sections: list = None
# ):
#     structured_json_str = json.dumps(structured_sections) if structured_sections else None

def save_document(db, session_id, template_id, title, content, structured_sections=None):
    if structured_sections is not None:
        if isinstance(structured_sections, list):
            structured_json_str = json.dumps({"sections": structured_sections})
        elif isinstance(structured_sections, dict):
            structured_json_str = json.dumps(structured_sections)
        else:
            structured_json_str = None
    else:
        structured_json_str = None
    return crud.save_generated_document(
        db=db,
        session_id=session_id,
        template_id=template_id,
        title=title,
        content=content,
        structured_json=structured_json_str
    )


def validate_document(
    db: Session,
    document_id: int,
    answers: dict = None,
    run_llm_judge: bool = True
) -> dict:
    doc = crud.get_document_by_id(db, document_id)
    if not doc:
        return {"error": "Document not found"}

    sections = crud.get_sections_by_template(db, doc.template_id)
    template = crud.get_template_by_id(db, doc.template_id)
    session = crud.get_session_by_id(db, doc.session_id)
    department = crud.get_department_by_id(db, session.department_id)

    # Use structured JSON if available
    if doc.structured_json:
        try:
            structured = json.loads(doc.structured_json)
        except Exception:
            structured = {"sections": []}
    else:
        structured = {"sections": []}



    result = run_validation_pipeline(
        structured=structured,
        sections=sections,
        answers=answers,
        template_name=template.name if template else "",
        department=department.name if department else "",
        run_llm_judge=run_llm_judge
    )

    status = "validated" if result.is_valid else "needs_review"
    crud.update_document_validation(
        db, document_id, status, json.dumps(result.to_dict())
    )

    return {"document_id": document_id, **result.to_dict()}


def preview_document(
    db: Session,
    department_name: str,
    template_name: str,
    template_description: str,
    template_id: int,
    answers: Dict[str, str],
    company: Optional[Dict] = None
) -> str:
    prompt = prompt_service.build_prompt(
        db=db,
        department_name=department_name,
        template_name=template_name,
        template_description=template_description,
        template_id=template_id,
        answers=answers,
        company=company
    )
    system = (
        f"You are a professional business document writer. "
        f"Maintain {company.get('tone', 'Professional') if company else 'Professional'} tone. "
        f"Return clean text — no ## no ** no markdown."
    )
    return llm_service.generate_with_llm(prompt=prompt, system_prompt=system)


def regenerate_section(
    db: Session,
    document_id: int,
    section_name: str,
    answers: dict = None,
    feedback: str = None,
    company: dict = None
) -> dict:
    doc = crud.get_document_by_id(db, document_id)
    if not doc:
        return {"error": "Document not found"}

    template = crud.get_template_by_id(db, doc.template_id)
    session = crud.get_session_by_id(db, doc.session_id)
    department = crud.get_department_by_id(db, session.department_id)

    tone = company.get("tone", "Professional") if company else "Professional"
    company_name = company.get("name", "") if company else ""

    role = classify_section_role(section_name)
    needs_tbl = section_needs_table(section_name)

    role_instructions = {
   "HEADER": "Keep it concise, formal, and factual. Include only exact values like dates, names, reference numbers, version, and document title. No explanations needed.",
    "OPENER": "Write 2-3 detailed paragraphs 80- 120 words explaining purpose, context, and importance.",
    "OBLIGATION": "Use numbered or bulleted points. Use formal language with 'must', 'shall', 'will be responsible for'.",
    "EVIDENCE": "Be data-driven and analytical. Include specific findings, metrics, and tables where possible. Write in detail.",
    "BODY": "Write comprehensive and detailed content. Expand ideas properly with explanations and examples . Aim for 70-100+ words per major point.",
    "CLOSURE": "Provide clear, actionable recommendations with responsible persons and timelines.",
    "SIGN_OFF": "Formal sign-off block only. Include names, designations, and date lines. Keep it clean and professional 60 - 90 words.",
    "STRUCTURAL": "Provide precise, clear definitions. Use numbered or bulleted lists for better readability ."
}

    role_instruction = role_instructions.get(role, "Write clearly and professionally.")
    table_note = "Use table format for this section." if needs_tbl else ""
    feedback_note = f"\nUser instruction: {feedback}" if feedback else ""
    today = date.today().strftime("%d %B %Y")

    answers_fmt = "\n".join(
        [f"  {k}: {v}" for k, v in (answers or {}).items() if v]
    ) or "  Use professional defaults."

    original_snippet = doc.content[:2000] if doc.content else ""

    system_prompt = (
        f"You are a professional document writer for {company_name or department.name}. "
        f"Maintain {tone} tone. No ##, no **, no markdown. Clean text only. "
        f"Today's date: {today}. Never use [DATE] or [NAME] placeholders."
    )

    section_prompt = f"""Document: {template.name}
Department: {department.name}
Today: {today}
Section: {section_name}
Role: {role} — {role_instruction}
{table_note}{feedback_note}

Original document style reference:
{original_snippet}

Information:
{answers_fmt}

Write ONLY content for "{section_name}".
No markdown. No placeholders. Clean professional text only."""

    new_content = llm_service.generate_with_llm(section_prompt, system_prompt)
    new_content_clean = _clean_text(_replace_placeholders(new_content))


    # Update structured JSON if available
    if doc.structured_json:
        try:
            structured = json.loads(doc.structured_json)
            for s in structured.get("sections", []):
                if section_name.lower() in s.get("heading", "").lower():
                    s["content"] = new_content_clean
                    s["word_count"] = len(new_content_clean.split())
                    break
            doc.structured_json = json.dumps(structured)
            db.commit()
        except Exception:
            pass

    

    updated = crud.update_document_section(
        db, document_id, section_name, new_content_clean
    )

    return {
        "document_id": document_id,
        "section_name": section_name,
        "updated_content": updated.content if updated else new_content_clean,
        "status": "regenerated"
    }


def get_all_versions(db: Session, session_id: UUID):
    return crud.get_documents_by_session(db, session_id)