import json
import re
from datetime import date
from typing import Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from backend.database import crud
from backend.services import llm_service, prompt_service
from backend.services.section_utils import classify_section_role, section_needs_table
from backend.services.text_utils import clean_text, replace_placeholders, sanitize_answers
from backend.utils.logger import get_logger

logger = get_logger("docforge.services.document")

_DEFAULT_STYLING = {"alignment": "justify", "font_weight": "normal", "page_break_after": False}

_ROLE_INSTRUCTIONS = {
    "HEADER":     "Concise factual header (50-150 words). Exact values: title, date ({today}), names, company. No sentences.",
    "OPENER":     "3-4 paragraphs (180+ words). Purpose, background, scope, importance. No bullet points.",
    "STRUCTURAL": "Numbered definitions, 4+ items (150-300 words).",
    "OBLIGATION": "Formal obligations (250+ words). Must/shall language. Complete enforceable statements.",
    "EVIDENCE":   "Data-driven analysis (200+ words). Specific findings. Table if numerical data present.",
    "BODY":       "Detailed content (250+ words). Full explanations. Use all answer values.",
    "CLOSURE":    "Actionable recommendations (120+ words). Action + owner + timeline per item.",
    "SIGN_OFF":   "Formal closing block (60-90 words). Signatory + designation + date ({today}).",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _today() -> str:
    return date.today().strftime("%d %B %Y")


def _normalize(raw) -> dict:
    if isinstance(raw, dict):
        raw.setdefault("sections", [])
        return raw
    if isinstance(raw, list):
        return {"sections": raw}
    return {"sections": []}


def _format_answers(answers: dict) -> str:
    if not answers:
        return "  No specific details provided — use professional defaults."
    return "\n".join(
        f"  {k}: {str(v).strip() if v and str(v).strip() else 'not specified'}"
        for k, v in answers.items()
    )


def _parse_table_rows(text: str) -> list:
    rows = []
    for line in [l.strip() for l in text.split("\n") if l.strip()]:
        if "|" in line:
            cells = [c.strip() for c in line.split("|") if c.strip()]
        elif "\t" in line:
            cells = [c.strip() for c in line.split("\t") if c.strip()]
        elif re.search(r"\s{3,}", line):
            cells = [c.strip() for c in re.split(r"\s{3,}", line) if c.strip()]
        else:
            continue
        if len(cells) >= 2 and not all(re.match(r"^[-=]+$", c) for c in cells):
            rows.append({"cells": cells})
    return rows


def _section_prompt(section_name, template_name, dept_name, answers, company, feedback=None, style_snippet=""):
    today       = _today()
    role        = classify_section_role(section_name)
    tone        = (company or {}).get("tone", "Professional")
    company_name = (company or {}).get("name") or dept_name or "the company"
    instruction = _ROLE_INSTRUCTIONS.get(role, _ROLE_INSTRUCTIONS["BODY"]).replace("{today}", today)

    system = f"Expert professional document writer for {company_name}. Tone: {tone}. No markdown. No bracket placeholders. Today: {today}."
    prompt = (
        f"Regenerate the '{section_name}' section for a {template_name} document.\n\n"
        f"DOCUMENT TYPE: {template_name}\nDEPARTMENT: {dept_name}\nTODAY: {today}\n\n"
        f"SECTION ROLE: {role}\nINSTRUCTION: {instruction}\n"
        + (f"\nTABLE FORMAT: rows separated by |, real values only\n" if section_needs_table(section_name) else "")
        + (f"\nFEEDBACK: {feedback}\n" if feedback else "")
        + (f"\nSTYLE REFERENCE:\n{style_snippet}\n" if style_snippet else "")
        + f"\nVARIABLE DATA:\n{_format_answers(answers or {})}\n\n"
        "Rules: content body only, no heading, no markdown, no placeholders."
    )
    return system, prompt


def _apply_section_content(structured: dict, section_name: str, new_content: str, answers: dict) -> dict:
    needs_tbl = section_needs_table(section_name)
    new_clean = clean_text(replace_placeholders(new_content, answers))

    if needs_tbl:
        rows = _parse_table_rows(new_clean)
        content, ctype, wc = (rows if len(rows) >= 2 else []), "table", 0
    else:
        content, ctype, wc = new_clean, "text", len(new_clean.split())

    for s in structured.get("sections", []):
        if section_name.lower() in s.get("heading", "").lower():
            s.update({"content_type": ctype, "content": content, "word_count": wc})
            return structured

    structured.setdefault("sections", []).append({
        "id": f"section_regen_{section_name[:10]}", "heading": section_name,
        "content_type": ctype, "content": content,
        "styling": _DEFAULT_STYLING.copy(), "word_count": wc,
    })
    return structured


# ── Document generation ───────────────────────────────────────────────────────

def generate_structured_document(db, department_name, template_name, template_description, template_id, answers, company=None) -> dict:
    logger.info("generate_structured_document | template=%r dept=%r", template_name, department_name)

    safe_answers = sanitize_answers(answers or {})
    sections_db  = crud.get_sections_by_template(db, template_id)

    system = prompt_service.STRUCTURED_SYSTEM_PROMPT.format(today=_today())
    user_prompt = prompt_service.build_structured_prompt(
        sections=sections_db, department_name=department_name, template_name=template_name,
        template_description=template_description, answers=safe_answers, company=company,
    )

    raw = _normalize(llm_service.generate_structured_document(system_prompt=system, user_prompt=user_prompt))
    cleaned, headings = [], []

    for sec in raw.get("sections", []):
        ct, c = sec.get("content_type", "text"), sec.get("content", "")
        if ct == "text" and isinstance(c, str):
            c = clean_text(replace_placeholders(c, safe_answers))
        elif ct == "table" and isinstance(c, list):
            c = [{"cells": [clean_text(replace_placeholders(str(x), safe_answers)) for x in r.get("cells", [])]}
                 for r in c if isinstance(r, dict) and "cells" in r]
        elif ct == "list" and isinstance(c, list):
            c = [clean_text(replace_placeholders(str(x), safe_answers)) for x in c if str(x).strip()]

        heading = clean_text(sec.get("heading", ""))
        cleaned.append({
            "id": sec.get("id", f"section_{len(cleaned)+1}"), "heading": heading,
            "content_type": ct, "content": c,
            "styling": sec.get("styling", _DEFAULT_STYLING.copy()),
            "word_count": len(c.split()) if isinstance(c, str) else 0,
        })
        headings.append(heading.lower())

    for req in [s.section_name for s in sections_db]:
        if not any(req.lower() in h for h in headings):
            cleaned.append({
                "id": f"section_missing_{req[:10]}", "heading": req,
                "content_type": "text", "content": "Pending generation.",
                "styling": _DEFAULT_STYLING.copy(), "word_count": 0,
            })

    raw["sections"] = cleaned
    logger.info("generate_structured_document complete | sections=%d", len(cleaned))
    return raw


def structured_to_plain_text(structured: dict) -> str:
    lines = []
    for sec in structured.get("sections", []):
        ct, c = sec.get("content_type", "text"), sec.get("content", "")
        if sec.get("heading"):
            lines.append(f"\n{sec['heading']}\n")
        if ct == "text" and isinstance(c, str):
            lines.append(f"{c}\n")
        elif ct == "table" and isinstance(c, list):
            for row in c:
                lines.append("  " + "   |   ".join(row.get("cells", [])))
            lines.append("")
        elif ct == "list" and isinstance(c, list):
            lines += [f"  - {item}" for item in c] + [""]
        lines.append("")
    return "\n".join(lines)


# ── Section regeneration ──────────────────────────────────────────────────────

def regenerate_section(db: Session, document_id: int, section_name: str, answers: dict = None, feedback: str = None, company: dict = None) -> dict:
    logger.info("regenerate_section | doc_id=%d section=%r", document_id, section_name)

    doc = crud.get_document_by_id(db, document_id)
    if not doc:
        return {"error": f"Document {document_id} not found"}

    template = crud.get_template_by_id(db, doc.template_id)
    if not template:
        return {"error": "Template not found"}

    session      = crud.get_session_by_id(db, doc.session_id) if doc.session_id else None
    dept         = crud.get_department_by_id(db, session.department_id) if session else None
    safe_answers = sanitize_answers(answers or {})

    style_snippet = ""
    if doc.structured_json:
        try:
            for s in _normalize(json.loads(doc.structured_json)).get("sections", []):
                if classify_section_role(s.get("heading", "")) in ("OPENER", "BODY") \
                        and isinstance(s.get("content"), str) and len(s["content"]) > 100:
                    style_snippet = s["content"][:1500]
                    break
        except Exception:
            pass
    style_snippet = style_snippet or (doc.content or "")[:1500]

    system, prompt = _section_prompt(
        section_name, template.name, dept.name if dept else "General",
        safe_answers, company, feedback, style_snippet,
    )
    new_content = llm_service.generate_with_llm(prompt, system)

    structured = _normalize(json.loads(doc.structured_json) if doc.structured_json else {})
    structured = _apply_section_content(structured, section_name, new_content, safe_answers)

    doc.structured_json = json.dumps(structured)
    doc.content         = structured_to_plain_text(structured)
    db.commit()

    section_content = next(
        (s["content"] for s in structured.get("sections", [])
         if section_name.lower() in s.get("heading", "").lower()),
        new_content,
    )
    return {
        "document_id":     document_id,
        "section_name":    section_name,
        "updated_content": json.dumps(section_content) if isinstance(section_content, list) else section_content,
    }


# ── Save / Preview / Versions ─────────────────────────────────────────────────

def save_document(db: Session, session_id: UUID, template_id: int, title: str, content: str, structured_sections=None) -> object:
    if isinstance(structured_sections, list):
        structured_json_str = json.dumps({"sections": structured_sections})
    elif isinstance(structured_sections, dict):
        structured_sections.setdefault("sections", [])
        structured_json_str = json.dumps(structured_sections)
    else:
        structured_json_str = None

    logger.info("save_document | session=%s template=%d", session_id, template_id)
    return crud.save_generated_document(
        db=db, session_id=session_id, template_id=template_id,
        title=title, content=content, structured_json=structured_json_str,
    )


def preview_document(db: Session, department_name: str, template_name: str, template_description: str, template_id: int, answers: Dict[str, str], company: Optional[Dict] = None) -> str:
    logger.info("preview_document | template=%r", template_name)
    safe_answers = sanitize_answers(answers or {})
    sections_db  = crud.get_sections_by_template(db, template_id)

    user_prompt = prompt_service.build_prompt(
        sections=sections_db, department_name=department_name, template_name=template_name,
        template_description=template_description, answers=safe_answers, company=company,
    )
    system = (
        f"Professional business document writer. "
        f"Tone: {(company or {}).get('tone', 'Professional')}. Today: {_today()}. "
        "Return clean plain text — no ## no ** no markdown."
    )
    return llm_service.generate_with_llm(user_prompt, system_prompt=system)


def get_all_versions(db: Session, session_id: UUID):
    return crud.get_documents_by_session(db, session_id)