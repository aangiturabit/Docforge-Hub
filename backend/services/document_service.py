"""
backend/services/document_service.py
─────────────────────────────────────────────────────
Core document lifecycle service.

Responsibilities
────────────────
• generate_structured_document — generation + silent fix + bounded silent regen
• regenerate_section           — user-triggered single-section regen
• save_document                — persist to DB
• preview_document             — plain-text preview (not saved)
• get_all_versions             — list documents for a session

NOT in this file
────────────────
• Validation logic   → validation_service.py
• Section constants  → section_utils.py
• Text utilities     → text_utils.py
• PDF rendering      → renderers/pdf_renderer.py
• DOCX rendering     → renderers/docx_renderer.py
• Prompt building    → prompt_service.py

Fixes applied
─────────────
• Latin-1 encode/decode removed — now uses clean_text() from text_utils
• Two DB writes in regenerate_section collapsed into one atomic commit
• Silent regen is capped at MAX_SILENT_REGEN_SECTIONS (default 4)
  and tracks attempted sections to prevent re-queuing the same section
• Re-export via noqa removed — callers import renderers directly
"""

import json
import re
from datetime import date
from typing import Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from backend.database import crud
from backend.services import llm_service, prompt_service
from backend.services.section_utils import classify_section_role, section_needs_table
from backend.services.text_utils import (
    _build_fallback_table,
    auto_fix_structured,
    clean_text,
    format_answers,
    normalize_structured,
    replace_placeholders,
    sanitize_answers,
)
from backend.services.validation_service import run_validation_pipeline
from backend.utils.logger import get_logger

logger = get_logger("docforge.services.document")

# Maximum number of sections that may be silently regenerated per generation call.
# Prevents unbounded LLM calls when many sections fail.
MAX_SILENT_REGEN_SECTIONS = 2


# ═══════════════════════════════════════════════════════
# ROLE GENERATION INSTRUCTIONS
# ═══════════════════════════════════════════════════════

_ROLE_INSTRUCTIONS: dict[str, str] = {
    "HEADER": (
        "Write a concise, factual header block ONLY. "
        "Include exact values: document title, date ({today}), reference number, "
        "company name, candidate/employee name and designation. "
        "No explanatory sentences. 50-150 words maximum. No markdown."
    ),
    "OPENER": (
        "Write 3-4 full paragraphs (minimum 180 words). "
        "Cover: purpose of the document, background context, scope, and why this "
        "document matters. Tone must match document type. No bullet points. No markdown."
    ),
    "STRUCTURAL": (
        "Write precise, numbered definitions or classifications. "
        "Each item must be 2-3 sentences. Minimum 4 items. 150-300 words total. "
        "Numbered list format. No markdown."
    ),
    "OBLIGATION": (
        "Write detailed obligations using formal language (must, shall, is responsible for). "
        "Minimum 250 words. Numbered points — each is a complete, enforceable statement. "
        "Cover all parties. No vague language. No markdown."
    ),
    "EVIDENCE": (
        "Write a data-driven, analytical section (minimum 200 words). "
        "State specific findings and metrics from the answers. "
        "If numerical data is available, present in a structured table. "
        "Be factual. No assumptions. No markdown."
    ),
    "BODY": (
        "Write comprehensive, detailed content — minimum 250 words. "
        "Expand every point with full explanation, context, and implications. "
        "Use all values from the provided answers. "
        "Clear paragraphs — each covers one idea fully. No markdown."
    ),
    "CLOSURE": (
        "Write clear, specific, actionable recommendations or conclusions (minimum 120 words). "
        "For each: state the action, the responsible party, and a realistic timeline. "
        "Numbered format. No markdown."
    ),
    "SIGN_OFF": (
        "Write a formal sign-off block ONLY (60-90 words). "
        "Include: closing statement, authorised signatory name and designation, "
        "company name, date line ({today}). "
        "If dual signatures are needed, include both blocks. No markdown."
    ),
}


# ═══════════════════════════════════════════════════════
# TEXT HELPERS (thin wrappers for local convenience)
# ═══════════════════════════════════════════════════════

def _answers_context(answers: dict) -> str:
    return format_answers(answers)


def _parse_text_to_table_rows(text: str) -> list:
    rows  = []
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    for line in lines:
        if "|" in line:
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if len(cells) >= 2:
                rows.append({"cells": cells})
        elif "\t" in line:
            cells = [c.strip() for c in line.split("\t") if c.strip()]
            if len(cells) >= 2:
                rows.append({"cells": cells})
        elif re.search(r"\s{3,}", line):
            cells = [c.strip() for c in re.split(r"\s{3,}", line) if c.strip()]
            if len(cells) >= 2:
                rows.append({"cells": cells})
    return [r for r in rows if not all(re.match(r"^[-=]+$", c) for c in r["cells"])]


# ═══════════════════════════════════════════════════════
# STRUCTURED JSON GENERATION
# ═══════════════════════════════════════════════════════

def generate_structured_document(
    db,
    department_name: str,
    template_name: str,
    template_description: str,
    template_id: int,
    answers: dict,
    company: dict = None,
) -> dict:
   
    logger.info(
        "generate_structured_document | template=%r dept=%r",
        template_name, department_name,
    )

    safe_answers = sanitize_answers(answers or {})

    sections_db = crud.get_sections_by_template(db, template_id)

    user_prompt = prompt_service.build_structured_prompt(
        sections=sections_db,
        department_name=department_name,
        template_name=template_name,
        template_description=template_description,
        answers=safe_answers,
        company=company,
    )
    system = prompt_service.STRUCTURED_SYSTEM_PROMPT.format(
        today=date.today().strftime("%d %B %Y")
    )

    raw = llm_service.generate_structured_document(
        system_prompt=system,
        user_prompt=user_prompt,
    )
    logger.debug("LLM raw | sections=%d", len((raw or {}).get("sections", [])))

    cleaned = _clean_structured_json(raw, sections_db, answers=safe_answers)
    fixed   = auto_fix_structured(cleaned, safe_answers, sections_db)
    final   = _silent_regen_bad_sections(
        structured=fixed,
        sections_db=sections_db,
        answers=safe_answers,
        template_name=template_name,
        department_name=department_name,
        company=company,
    )

    logger.info(
        "generate_structured_document complete | sections=%d",
        len(final.get("sections", [])),
    )
    return final


def _clean_structured_json(
    raw,
    sections_db: list,
    answers: dict = None,
) -> dict:
    raw          = normalize_structured(raw)
    required     = [s.section_name for s in sections_db]
    cleaned_list = []

    for section in raw.get("sections", []):
        heading      = clean_text(section.get("heading", ""))
        content_type = section.get("content_type", "text")
        content      = section.get("content", "")
        styling      = section.get("styling", {
            "alignment": "justify",
            "font_weight": "normal",
            "page_break_after": False,
        })

        if content_type == "text" and isinstance(content, str):
            content = clean_text(replace_placeholders(content, answers))

        elif content_type == "table" and isinstance(content, list):
            content = [
                {"cells": [
                    clean_text(replace_placeholders(str(c), answers))
                    for c in row["cells"]
                ]}
                for row in content
                if isinstance(row, dict) and "cells" in row
            ]

        elif content_type == "list" and isinstance(content, list):
            content = [
                clean_text(replace_placeholders(str(item), answers))
                for item in content
                if str(item).strip()
            ]

        word_count = len(content.split()) if isinstance(content, str) else 0
        cleaned_list.append({
            "id":           section.get("id", f"section_{len(cleaned_list) + 1}"),
            "heading":      heading,
            "content_type": content_type,
            "content":      content,
            "styling":      styling,
            "word_count":   word_count,
        })

    # Insert placeholder for any missing required section
    generated_headings = [s["heading"].lower() for s in cleaned_list]
    for req in required:
        if not any(req.lower() in h for h in generated_headings):
            cleaned_list.append({
                "id":           f"section_missing_{req[:10]}",
                "heading":      req,
                "content_type": "text",
                "content":      "Pending generation.",
                "styling":      {"alignment": "justify", "font_weight": "normal", "page_break_after": False},
                "word_count":   0,
            })

    raw["sections"] = cleaned_list
    return raw


def structured_to_plain_text(structured: dict) -> str:
    lines = []
    for section in structured.get("sections", []):
        heading      = section.get("heading", "")
        content_type = section.get("content_type", "text")
        content      = section.get("content", "")

        if heading:
            lines.append(f"\n{heading}\n")
        if content_type == "text" and isinstance(content, str):
            lines.append(f"{content}\n")
        elif content_type == "table" and isinstance(content, list):
            for row in content:
                lines.append("  " + "   |   ".join(row.get("cells", [])))
            lines.append("")
        elif content_type == "list" and isinstance(content, list):
            for item in content:
                lines.append(f"  - {item}")
            lines.append("")
        lines.append("")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════
# SILENT REGEN — bounded, tracked
# ═══════════════════════════════════════════════════════

def _silent_regen_bad_sections(
    structured: dict,
    sections_db: list,
    answers: dict,
    template_name: str,
    department_name: str,
    company: dict = None,
) -> dict:

    result = run_validation_pipeline(
        structured=structured,
        sections=sections_db,
        answers=answers,
    )

    if result.is_valid:
        logger.info("silent_regen: document passed all checks")
        return structured

    # Collect unique failing sections, skip document-level markers
    bad_sections = [
        issue["section"]
        for issue in result.issues
        if issue.get("fatal", True)
        and issue.get("section")
        and issue["section"] not in ("document", "")
    ]
    # Deduplicate while preserving order
    seen: set = set()
    unique_bad: list = []
    for s in bad_sections:
        if s not in seen:
            seen.add(s)
            unique_bad.append(s)

    # Apply cap
    to_regen = unique_bad[:MAX_SILENT_REGEN_SECTIONS]
    if len(unique_bad) > MAX_SILENT_REGEN_SECTIONS:
        logger.warning(
            "silent_regen: %d sections need regen but cap is %d — skipping: %s",
            len(unique_bad), MAX_SILENT_REGEN_SECTIONS,
            unique_bad[MAX_SILENT_REGEN_SECTIONS:],
        )

    logger.info("silent_regen: regenerating %d section(s): %s", len(to_regen), to_regen)

    for section_name in to_regen:
        try:
            structured = _regenerate_section_inline(
                structured=structured,
                section_name=section_name,
                answers=answers,
                template_name=template_name,
                department_name=department_name,
                company=company,
            )
            logger.info("silent_regen: done — %s", section_name)
        except Exception as exc:
            logger.error("silent_regen: failed for '%s': %s", section_name, exc)
            # Do not retry — leave section as-is

    return structured


def _regenerate_section_inline(
    structured: dict,
    section_name: str,
    answers: dict,
    template_name: str,
    department_name: str,
    company: dict = None,
) -> dict:
    """
    Pure function (no DB ops). Regenerates one section, slots it back.
    Used only by _silent_regen_bad_sections.
    """
    today        = date.today().strftime("%d %B %Y")
    role         = classify_section_role(section_name)
    needs_tbl    = section_needs_table(section_name)
    tone         = (company or {}).get("tone", "Professional")
    company_name = (company or {}).get("name", "")

    instruction = _ROLE_INSTRUCTIONS.get(role, _ROLE_INSTRUCTIONS["BODY"]).replace("{today}", today)
    answers_ctx = format_answers(answers or {})
    table_note  = (
        "\n\nTABLE FORMAT: Output rows separated by |. Use real values. No markdown.\n"
        if needs_tbl else ""
    )

    system = (
        f"Professional document writer for {company_name or department_name}. "
        f"Tone: {tone}. No markdown. No bracket placeholders. Today: {today}."
    )
    prompt = (
        f"Regenerate the '{section_name}' section for a {template_name} document.\n\n"
        f"ROLE: {role}\nINSTRUCTION:\n{instruction}{table_note}\n\n"
        f"VARIABLE DATA:\n{answers_ctx}\n\n"
        "Rules: content body only, no heading, no brackets, real values only."
    )

    new_content = llm_service.generate_with_llm(prompt, system)
    new_clean   = clean_text(replace_placeholders(new_content, answers))

    if needs_tbl:
        rows = _parse_text_to_table_rows(new_clean)
        if not rows or len(rows) < 2:
            rows = _build_fallback_table(section_name, answers or {})

    updated = False
    for s in structured.get("sections", []):
        if section_name.lower() in s.get("heading", "").lower():
            if needs_tbl:
                s["content_type"] = "table"
                s["content"]      = rows
                s["word_count"]   = 0
            else:
                s["content_type"] = "text"
                s["content"]      = new_clean
                s["word_count"]   = len(new_clean.split())
            updated = True
            break

    if not updated:
        structured["sections"].append({
            "id":           f"section_regen_{section_name[:10]}",
            "heading":      section_name,
            "content_type": "table" if needs_tbl else "text",
            "content":      rows if needs_tbl else new_clean,
            "styling":      {"alignment": "justify", "font_weight": "normal", "page_break_after": False},
            "word_count":   0 if needs_tbl else len(new_clean.split()),
        })

    return structured


# ═══════════════════════════════════════════════════════
# USER-TRIGGERED SECTION REGENERATION
# ═══════════════════════════════════════════════════════

def regenerate_section(
    db: Session,
    document_id: int,
    section_name: str,
    answers: dict = None,
    feedback: str = None,
    company: dict = None,
) -> dict:
    
    logger.info(
        "regenerate_section | doc_id=%d section=%r feedback=%s",
        document_id, section_name, bool(feedback),
    )

    doc = crud.get_document_by_id(db, document_id)
    if not doc:
        raise ValueError(f"Document {document_id} not found")

    template   = crud.get_template_by_id(db, doc.template_id)
    session    = crud.get_session_by_id(db, doc.session_id)
    department = crud.get_department_by_id(db, session.department_id)

    if not template:
        raise ValueError(f"Template for document {document_id} not found")

    safe_answers = sanitize_answers(answers or {})

    today        = date.today().strftime("%d %B %Y")
    role         = classify_section_role(section_name)
    needs_tbl    = section_needs_table(section_name)
    tone         = (company or {}).get("tone", "Professional")
    company_name = (company or {}).get("name", "")

    instruction  = _ROLE_INSTRUCTIONS.get(role, _ROLE_INSTRUCTIONS["BODY"]).replace("{today}", today)
    answers_ctx  = format_answers(safe_answers)
    table_note   = (
        "\n\nTABLE FORMAT: Output rows separated by |. Use real values. No markdown.\n"
        if needs_tbl else ""
    )
    feedback_note = f"\n\nUSER INSTRUCTION (apply exactly): {feedback}\n" if feedback else ""

    # Style reference from an existing OPENER or BODY section
    original_snippet = ""
    if doc.structured_json:
        try:
            structured_existing = normalize_structured(json.loads(doc.structured_json))
            for s in structured_existing.get("sections", []):
                if classify_section_role(s.get("heading", "")) in ("OPENER", "BODY") \
                        and isinstance(s.get("content"), str):
                    original_snippet = s["content"][:1500]
                    break
        except Exception:
            pass
    if not original_snippet and doc.content:
        original_snippet = doc.content[:1500]

    system = (
        f"Expert professional document writer for "
        f"{company_name or (department.name if department else 'the organisation')}. "
        f"Tone: {tone}. No markdown. No bracket placeholders. Today: {today}."
    )
    prompt = (
        f"Regenerate '{section_name}' section for a {template.name} document.\n\n"
        f"DOCUMENT TYPE: {template.name}\n"
        f"DEPARTMENT: {department.name if department else 'N/A'}\n"
        f"TODAY: {today}\n\n"
        f"SECTION ROLE: {role}\n"
        f"DEPTH INSTRUCTION:\n{instruction}"
        f"{table_note}{feedback_note}\n\n"
        f"STYLE REFERENCE:\n{original_snippet}\n\n"
        f"VARIABLE DATA:\n{answers_ctx}\n\n"
        "Rules:\n"
        "1. Content body only — do NOT include the section heading\n"
        "2. No markdown\n"
        "3. No bracket placeholders — real values only\n"
        f"4. Meet minimum word count for {role} role"
    )

    # — LLM call — exceptions propagate to router (no silent fallback)
    new_content = llm_service.generate_with_llm(prompt, system)
    new_clean   = clean_text(replace_placeholders(new_content, safe_answers))

    table_rows = None
    if needs_tbl:
        table_rows = _parse_text_to_table_rows(new_clean)
        if not table_rows or len(table_rows) < 2:
            table_rows = _build_fallback_table(section_name, safe_answers)

    # Load current structured JSON
    raw        = json.loads(doc.structured_json) if doc.structured_json else {}
    structured = normalize_structured(raw)
    updated    = False

    for s in structured.get("sections", []):
        if section_name.lower() in s.get("heading", "").lower():
            if needs_tbl and table_rows:
                s["content_type"] = "table"
                s["content"]      = table_rows
                s["word_count"]   = 0
            else:
                s["content_type"] = "text"
                s["content"]      = new_clean
                s["word_count"]   = len(new_clean.split())
            updated = True
            break

    if not updated:
        structured["sections"].append({
            "id":           f"section_regen_{section_name[:10]}",
            "heading":      section_name,
            "content_type": "table" if needs_tbl and table_rows else "text",
            "content":      table_rows if needs_tbl and table_rows else new_clean,
            "styling":      {"alignment": "justify", "font_weight": "normal", "page_break_after": False},
            "word_count":   0 if needs_tbl else len(new_clean.split()),
        })

    # ── Single atomic commit — structured_json and plain content updated together
    doc.structured_json = json.dumps(structured)
    doc.content         = structured_to_plain_text(structured)
    db.commit()
    # ─────────────────────────────────────────────────────────────────────────

    logger.info(
        "regenerate_section complete | doc_id=%d section=%r",
        document_id, section_name,
    )

    return {
        "document_id":     document_id,
        "section_name":    section_name,
        "updated_content": json.dumps(table_rows) if needs_tbl and table_rows else new_clean,
        "status":          "regenerated",
    }


# ═══════════════════════════════════════════════════════
# PERSISTENCE HELPERS
# ═══════════════════════════════════════════════════════

def save_document(
    db: Session,
    session_id: UUID,
    template_id: int,
    title: str,
    content: str,
    structured_sections=None,
) -> object:
    if structured_sections is not None:
        if isinstance(structured_sections, list):
            structured_json_str = json.dumps({"sections": structured_sections})
        elif isinstance(structured_sections, dict):
            structured_sections.setdefault("sections", [])
            structured_json_str = json.dumps(structured_sections)
        else:
            structured_json_str = None
    else:
        structured_json_str = None

    logger.info("save_document | session=%s template=%d", session_id, template_id)
    return crud.save_generated_document(
        db=db,
        session_id=session_id,
        template_id=template_id,
        title=title,
        content=content,
        structured_json=structured_json_str,
    )


def preview_document(
    db: Session,
    department_name: str,
    template_name: str,
    template_description: str,
    template_id: int,
    answers: Dict[str, str],
    company: Optional[Dict] = None,
) -> str:
    logger.info("preview_document | template=%r", template_name)
    safe_answers = sanitize_answers(answers or {})
    sections_db  = crud.get_sections_by_template(db, template_id)

    user_prompt = prompt_service.build_prompt(
        sections=sections_db,
        department_name=department_name,
        template_name=template_name,
        template_description=template_description,
        answers=safe_answers,
        company=company,
    )
    system = (
        f"Professional business document writer. "
        f"Tone: {(company or {}).get('tone', 'Professional')}. "
        "Return clean text — no ## no ** no markdown."
    )
    return llm_service.generate_with_llm(user_prompt, system_prompt=system)


def get_all_versions(db: Session, session_id: UUID):
    return crud.get_documents_by_session(db, session_id)


