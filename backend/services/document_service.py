
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

# Role → minimum / maximum word targets
SECTION_DEPTH_WORDS = {
    "HEADER":     (30,  150),
    "OPENER":     (150, 400),
    "STRUCTURAL": (100, 300),
    "OBLIGATION": (250, 700),
    "EVIDENCE":   (200, 500),
    "BODY":       (250, 900),
    "CLOSURE":    (120, 400),
    "SIGN_OFF":   (30,  120),
}

TABLE_SECTION_SIGNALS = [
    "compensation", "breakdown", "ctc", "salary", "budget",
    "invoice", "pricing", "comparison", "metrics", "kpi",
    "test cases", "findings", "risk", "timeline", "schedule",
    "gross", "deductions", "earnings", "payment", "quotation",
    "bill", "purchase"
]

# Regeneration role instructions — match original generation depth exactly
ROLE_INSTRUCTIONS = {
    "HEADER": (
        "Write a concise, factual header block ONLY. "
        "Include exact values: document title, date ({today}), reference number, "
        "company name, candidate/employee name and designation. "
        "No explanatory sentences. No filler. 50-150 words maximum. "
        "Align left. No markdown."
    ),
    "OPENER": (
        "Write 3-4 full paragraphs (minimum 180 words). "
        "Cover: purpose of the document, background context, scope, "
        "and why this document matters to the recipient and organisation. "
        "Tone must match the document type — warm for HR letters, "
        "analytical for reports, authoritative for policies. "
        "No bullet points. No markdown. Justified paragraphs."
    ),
    "STRUCTURAL": (
        "Write precise, numbered definitions or classifications. "
        "Each item must be 2-3 sentences explaining the term, its scope, "
        "and how it applies in this document context. "
        "Minimum 4 items. 150-300 words total. "
        "Use numbered list format. No markdown symbols."
    ),
    "OBLIGATION": (
        "Write detailed, explicit obligations using formal language. "
        "Use 'must', 'shall', 'is responsible for', 'will ensure'. "
        "Minimum 250 words. Structure as numbered points — each point "
        "must be a complete, enforceable statement. "
        "Cover all parties mentioned in the answers. "
        "No vague language. No markdown."
    ),
    "EVIDENCE": (
        "Write a data-driven, analytical section. "
        "State specific findings, metrics, and observations drawn from "
        "the information provided. Minimum 200 words of analysis text. "
        "If numerical data is available from answers, present it in a "
        "structured table (columns: Item, Value, Status/Notes). "
        "Be factual and precise. No assumptions. No markdown."
    ),
    "BODY": (
        "Write comprehensive, detailed content — minimum 250 words. "
        "Expand every point with full explanation, context, and implications. "
        "Use all values from the provided answers. "
        "Structure as clear paragraphs — each paragraph covers one idea fully. "
        "No padding or repetition. No markdown. Justified alignment."
    ),
    "CLOSURE": (
        "Write clear, specific, actionable recommendations or conclusions. "
        "Minimum 120 words. For each recommendation: state the action, "
        "the responsible person/team, and a realistic timeline. "
        "Use numbered format. Tone should be forward-looking and constructive. "
        "No markdown."
    ),
    "SIGN_OFF": (
        "Write a formal sign-off block ONLY. 60-90 words maximum. "
        "Include: closing statement (one sentence), "
        "authorised signatory name and designation, "
        "company name, and a date line ({today}). "
        "If dual signatures are needed (e.g. contract), include both blocks. "
        "No markdown. No explanatory text."
    ),
}


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


def _replace_placeholders(text: str, answers: dict = None) -> str:
    """
    Replace ALL placeholders with real values from answers dict first,
    then fall back to today's date / 'Not Provided'.
    """
    today = date.today().strftime("%d %B %Y")

    # If answers provided, replace common field patterns with real values
    if answers:
        field_map = {
            r'\[COMPANY[_ ]NAME\]': answers.get("company_name", ""),
            r'\[CANDIDATE[_ ]NAME\]': answers.get("candidate_name", "")
                                      or answers.get("employee_name", ""),
            r'\[EMPLOYEE[_ ]NAME\]': answers.get("employee_name", "")
                                      or answers.get("candidate_name", ""),
            r'\[JOB[_ ]TITLE\]': answers.get("job_title", "")
                                  or answers.get("designation", ""),
            r'\[DESIGNATION\]': answers.get("designation", "")
                                or answers.get("job_title", ""),
            r'\[DEPARTMENT\]': answers.get("department", ""),
            r'\[JOINING[_ ]DATE\]': answers.get("joining_date", today),
            r'\[SALARY\]': answers.get("salary", "")
                           or answers.get("ctc", ""),
            r'\[CTC\]': answers.get("ctc", "")
                        or answers.get("salary", ""),
            r'\[LOCATION\]': answers.get("location", ""),
        }
        for pattern, value in field_map.items():
            if value and value.strip():
                text = re.sub(pattern, value.strip(), text, flags=re.IGNORECASE)

    # Date replacements
    text = re.sub(r'\[DATE\]|\[date\]|\[Date\]', today, text)
    text = re.sub(r'\[TODAY\]|\[today\]', today, text)
    text = re.sub(r'\[YEAR\]', str(date.today().year), text)
    text = re.sub(r'\[MONTH\]', date.today().strftime("%B"), text)
    text = re.sub(r'\[MISSING_INFORMATION\]', 'Not Provided', text)
    text = re.sub(r'\[TBD\]|\bTBD\b', 'To be confirmed', text)
    text = re.sub(r'\[INSERT[^\]]*\]', 'Not Provided', text)
    text = re.sub(r'\[ADD[^\]]*\]', '', text)
    text = re.sub(r'\[.*?\]', 'Not Provided', text)  
    return text


def _normalize_structured(raw) -> dict:
    """Always return {"sections": [...]} regardless of what was stored."""
    if isinstance(raw, dict):
        if "sections" not in raw:
            raw["sections"] = []
        return raw
    if isinstance(raw, list):
        return {"sections": raw}
    return {"sections": []}


def _answers_to_context(answers: dict) -> str:
    """Format answers dict into a readable context string for prompts."""
    if not answers:
        return "No specific details provided."
    lines = []
    for k, v in answers.items():
        val = str(v).strip() if v and str(v).strip() else "Not Provided"
        lines.append(f"  {k}: {val}")
    return "\n".join(lines)


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

    cleaned = _clean_structured_json(raw, template_id, db, answers=answers)
    return cleaned


def _clean_structured_json(raw, template_id: int, db, answers: dict = None) -> dict:
  
    raw = _normalize_structured(raw)

    sections = crud.get_sections_by_template(db, template_id)
    required_names = [s.section_name for s in sections]

    cleaned_sections = []
    for section in raw.get("sections", []):
        heading      = _clean_text(section.get("heading", ""))
        content_type = section.get("content_type", "text")
        content      = section.get("content", "")
        styling      = section.get("styling", {
            "alignment": "justify",
            "font_weight": "normal",
            "page_break_after": False
        })

        if content_type == "text" and isinstance(content, str):
            content = _clean_text(_replace_placeholders(content, answers))

        elif content_type == "table" and isinstance(content, list):
            cleaned_rows = []
            for row in content:
                if isinstance(row, dict) and "cells" in row:
                    cells = [
                        _clean_text(_replace_placeholders(str(c), answers))
                        for c in row["cells"]
                    ]
                    cleaned_rows.append({"cells": cells})
            content = cleaned_rows

        elif content_type == "list" and isinstance(content, list):
            content = [
                _clean_text(_replace_placeholders(str(item), answers))
                for item in content
                if str(item).strip()
            ]

        word_count = len(content.split()) if isinstance(content, str) else 0

        cleaned_sections.append({
            "id":           section.get("id", f"section_{len(cleaned_sections)+1}"),
            "heading":      heading,
            "content_type": content_type,
            "content":      content,
            "styling":      styling,
            "word_count":   word_count
        })

    # Add placeholder for any truly missing required sections
    generated_headings = [s["heading"].lower() for s in cleaned_sections]
    for required in required_names:
        if not any(required.lower() in h for h in generated_headings):
            cleaned_sections.append({
                "id":           f"section_missing_{required[:10]}",
                "heading":      required,
                "content_type": "text",
                "content":      "This section requires additional information. Please regenerate.",
                "styling":      {"alignment": "justify", "font_weight": "normal", "page_break_after": False},
                "word_count":   0
            })

    raw["sections"] = cleaned_sections
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
        self.is_valid:           bool       = True
        self.issues:             List[dict] = []
        self.missing_sections:   List[str]  = []
        self.order_issues:       List[str]  = []
        self.table_issues:       List[str]  = []
        self.grounding_issues:   List[str]  = []
        self.placeholder_issues: List[str]  = []
        self.llm_judge_result:   dict       = {}

    def add_issue(self, issue_type: str, section: str, detail: str):
        self.is_valid = False
        self.issues.append({"type": issue_type, "section": section, "detail": detail})

    def to_dict(self) -> dict:
        return {
            "is_valid":            self.is_valid,
            "total_issues":        len(self.issues),
            "issues":              self.issues,
            "missing_sections":    self.missing_sections,
            "order_issues":        self.order_issues,
            "table_issues":        self.table_issues,
            "grounding_issues":    self.grounding_issues,
            "placeholder_issues":  self.placeholder_issues,
            "llm_judge_result":    self.llm_judge_result
        }


# Comprehensive placeholder patterns
PLACEHOLDER_PATTERNS = [
    r'\[DATE\]', r'\[date\]', r'\[Date\]',
    r'\[NAME\]', r'\[name\]',
    r'\[INSERT[^\]]*\]',
    r'\[ADD[^\]]*\]',
    r'\[MISSING_INFORMATION\]',
    r'\[TBD\]', r'\bTBD\b',
    r'\[.*?PLACEHOLDER.*?\]',
    r'\[COMPANY[^\]]*\]',
    r'\[CANDIDATE[^\]]*\]',
    r'\[EMPLOYEE[^\]]*\]',
    r'\[AMOUNT[^\]]*\]',
    r'\[SALARY[^\]]*\]',
    r'\[CTC[^\]]*\]',
    r'\[DESIGNATION[^\]]*\]',
    r'\[DEPARTMENT[^\]]*\]',
    r'\[LOCATION[^\]]*\]',
    r'\[.*?\]',   # catch-all
]

# Stub phrases that indicate incomplete generation
STUB_PHRASES = [
    "content to be provided",
    "to be filled",
    "to be completed",
    "insert here",
    "add details here",
    "as mentioned above",
    "lorem ipsum",
    "this section requires additional information",
]


def _check_sections_present(structured: dict, sections, result: ValidationResult):
    """Pass 1 — all required sections must exist."""
    generated = [s.get("heading", "").lower() for s in structured.get("sections", [])]
    for section in sections:
        name_lower = section.section_name.lower()
        if not any(name_lower in g for g in generated):
            result.missing_sections.append(section.section_name)
            result.add_issue(
                "MISSING_SECTION", section.section_name,
                f"Section '{section.section_name}' not found in document"
            )


def _check_section_order(structured: dict, sections, result: ValidationResult):
    """Pass 2 — sections must follow template order."""
    generated_headings = [s.get("heading", "").lower() for s in structured.get("sections", [])]
    template_order     = [s.section_name.lower() for s in sections]

    found_positions = []
    for name in template_order:
        for i, heading in enumerate(generated_headings):
            if name in heading:
                found_positions.append((name, i))
                break

    for i in range(len(found_positions) - 1):
        if found_positions[i][1] > found_positions[i + 1][1]:
            issue = f"'{found_positions[i][0]}' appears after '{found_positions[i+1][0]}'"
            result.order_issues.append(issue)
            result.add_issue("ORDER_VIOLATION", found_positions[i][0], issue)


def _check_table_sections(structured: dict, sections, result: ValidationResult):
    """Pass 3 — financial/metric sections must have table content_type with rows."""
    section_map = {
        s.get("heading", "").lower(): s
        for s in structured.get("sections", [])
    }

    for section in sections:
        if not section_needs_table(section.section_name):
            continue

        name_lower = section.section_name.lower()
        matched    = next((v for k, v in section_map.items() if name_lower in k), None)
        if not matched:
            continue

        if matched.get("content_type") != "table":
            result.table_issues.append(section.section_name)
            result.add_issue(
                "MISSING_TABLE", section.section_name,
                f"'{section.section_name}' must be table type — got '{matched.get('content_type')}'"
            )
        elif not matched.get("content", []):
            result.table_issues.append(section.section_name)
            result.add_issue(
                "EMPTY_TABLE", section.section_name,
                f"Table in '{section.section_name}' has no rows"
            )
        else:
            # Check table has more than just a header row
            rows = matched.get("content", [])
            if len(rows) < 2:
                result.table_issues.append(section.section_name)
                result.add_issue(
                    "TABLE_NO_DATA", section.section_name,
                    f"Table in '{section.section_name}' has header but no data rows"
                )


def _check_placeholders(structured: dict, result: ValidationResult):
    """Pass 4 — scan all content for unfilled placeholders."""
    for section in structured.get("sections", []):
        content = section.get("content", "")
        heading = section.get("heading", "")

        if isinstance(content, str):
            for pattern in PLACEHOLDER_PATTERNS:
                for item in re.findall(pattern, content, re.IGNORECASE):
                    result.placeholder_issues.append(item)
                    result.add_issue(
                        "PLACEHOLDER_FOUND", heading,
                        f"Unfilled placeholder '{item}' in '{heading}'"
                    )
            # Also check for stub phrases
            content_lower = content.lower()
            for stub in STUB_PHRASES:
                if stub in content_lower:
                    result.add_issue(
                        "STUB_CONTENT", heading,
                        f"Stub phrase detected in '{heading}': '{stub}'"
                    )

        elif isinstance(content, list):
            for row in content:
                if isinstance(row, dict):
                    for cell in row.get("cells", []):
                        cell_str = str(cell)
                        for pattern in PLACEHOLDER_PATTERNS:
                            for item in re.findall(pattern, cell_str, re.IGNORECASE):
                                result.placeholder_issues.append(item)
                                result.add_issue(
                                    "PLACEHOLDER_FOUND", heading,
                                    f"Unfilled placeholder '{item}' in table of '{heading}'"
                                )


def _check_answer_grounding(structured: dict, answers: dict, result: ValidationResult):
    """Pass 5 — key answer values must appear in document text."""
    if not answers:
        return

    all_text = " ".join([
        section.get("content", "")
        if isinstance(section.get("content", ""), str) else
        " ".join(
            " ".join(row.get("cells", []))
            for row in section.get("content", [])
            if isinstance(row, dict)
        )
        for section in structured.get("sections", [])
    ]).lower()

    important_fields = [
        "company_name", "candidate_name", "employee_name",
        "job_title", "department", "joining_date",
        "designation", "salary", "ctc",
    ]

    for field in important_fields:
        value = str(answers.get(field, "")).strip()
        if value and len(value) > 2 and value.lower() not in ("not provided", "", "none"):
            if value.lower() not in all_text:
                result.grounding_issues.append(field)
                result.add_issue(
                    "GROUNDING_FAILURE", field,
                    f"Value '{value}' for '{field}' not found in document"
                )


def _check_minimum_content(structured: dict, sections, result: ValidationResult):
    """Pass 6 — check minimum word count per section role."""
    for section in structured.get("sections", []):
        content = section.get("content", "")
        heading = section.get("heading", "")

        if isinstance(content, str):
            word_count = len(content.split())
            role       = classify_section_role(heading)
            min_words, _ = SECTION_DEPTH_WORDS.get(role, (20, 9999))

            if role not in ("HEADER", "SIGN_OFF") and word_count < min_words:
                result.add_issue(
                    "TOO_SHORT", heading,
                    f"'{heading}' has {word_count} words — minimum {min_words} for {role} role"
                )


def _llm_as_judge(structured: dict, template_name: str, department: str) -> dict:
    """Pass 7 — LLM quality score. Samples first 4 sections for speed."""
    sample_sections = structured.get("sections", [])[:4]
    sample_text = "\n\n".join([
        f"{s.get('heading', '')}: {str(s.get('content', ''))[:400]}"
        for s in sample_sections
    ])

    judge_prompt = f"""You are a strict document quality evaluator.

Evaluate this {template_name} document excerpt for the {department} department.

Document excerpt:
{sample_text}

Score each criterion from 0 to 10:
1. Professional tone — language appropriate for business document
2. Content completeness — all sections have real, substantive content
3. No placeholders — no [brackets], TBD, or stub phrases anywhere
4. Factual consistency — values are real, not invented or contradictory
5. Format appropriateness — structure matches document type

IMPORTANT SCORING RULES:
- Score 10 only if the section is truly exceptional
- Score 7-9 for solid, professional content with minor gaps
- Score 4-6 for content with noticeable issues
- Score 0-3 for content with placeholders, stubs, or major problems
- overall_score = average of all five scores (rounded)
- passed = true if overall_score >= 7, else false

Return ONLY this JSON (no text before or after):
{{
  "overall_score": 0,
  "tone_score": 0,
  "completeness_score": 0,
  "placeholder_score": 0,
  "consistency_score": 0,
  "format_score": 0,
  "passed": false,
  "main_issue": "one line summary or empty string",
  "recommendation": "one line improvement suggestion or empty string"
}}"""

    try:
        result_str = llm_service.generate_with_llm_json(
            user_prompt=judge_prompt,
            system_prompt=(
                "You are a document quality judge. Score strictly and honestly. "
                "Return ONLY valid JSON — no markdown, no text outside braces."
            )
        )
        result = json.loads(result_str)
        # Recalculate overall from subscores for safety
        subscores = [
            result.get("tone_score", 0),
            result.get("completeness_score", 0),
            result.get("placeholder_score", 0),
            result.get("consistency_score", 0),
            result.get("format_score", 0),
        ]
        calculated = round(sum(subscores) / len(subscores), 1)
        result["overall_score"] = calculated
        result["passed"] = calculated >= 7
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
    # Always normalise before any pass touches it
    structured = _normalize_structured(structured)

    result = ValidationResult()
    _check_sections_present(structured, sections, result)
    _check_section_order(structured, sections, result)
    _check_table_sections(structured, sections, result)
    _check_placeholders(structured, result)
    _check_answer_grounding(structured, answers or {}, result)
    _check_minimum_content(structured, sections, result)

    if run_llm_judge and template_name:
        result.llm_judge_result = _llm_as_judge(structured, template_name, department)
        if not result.llm_judge_result.get("passed", True):
            result.is_valid = False
            result.add_issue(
                "LLM_JUDGE_FAILED", "document",
                result.llm_judge_result.get("main_issue", "Quality check failed")
            )

    return result


# ═══════════════════════════════════════════════════════
# AUTO-FIX: post-generation patch for common failures
# ═══════════════════════════════════════════════════════
def _auto_fix_structured(structured: dict, answers: dict, sections_db: list, db) -> dict:
    """
    After generation, run quick fixes:
    - Replace any remaining placeholders using answer values
    - Ensure every table section has at least a header +  data rows
    - Remove stub-content sections
    """
    structured = _normalize_structured(structured)
    today = date.today().strftime("%d %B %Y")

    for section in structured.get("sections", []):
        heading      = section.get("heading", "")
        content_type = section.get("content_type", "text")
        content      = section.get("content", "")

        # Fix text content
        if content_type == "text" and isinstance(content, str):
            content = _replace_placeholders(content, answers)
            section["content"] = _clean_text(content)
            section["word_count"] = len(section["content"].split())

        # Fix table content
        elif content_type == "table" and isinstance(content, list):
            fixed_rows = []
            for row in content:
                if isinstance(row, dict) and "cells" in row:
                    fixed_cells = [
                        _clean_text(_replace_placeholders(str(c), answers))
                        for c in row["cells"]
                    ]
                    fixed_rows.append({"cells": fixed_cells})
            # If table ended up empty, build a minimal table from answers
            if not fixed_rows and section_needs_table(heading):
                fixed_rows = _build_fallback_table(heading, answers)
            section["content"] = fixed_rows

        # Fix list content
        elif content_type == "list" and isinstance(content, list):
            fixed_items = [
                _clean_text(_replace_placeholders(str(item), answers))
                for item in content
                if str(item).strip()
            ]
            section["content"] = fixed_items

    return structured


def _build_fallback_table(section_heading: str, answers: dict) -> list:
    """
    Build a minimal meaningful table from available answer values
    when the LLM failed to produce one.
    """
    today = date.today().strftime("%d %B %Y")
    heading_lower = section_heading.lower()

    # Compensation / salary / CTC table
    if any(k in heading_lower for k in ["compensation", "salary", "ctc", "earnings", "gross"]):
        rows = [{"cells": ["Component", "Amount (INR)", "Frequency"]}]
        if answers.get("basic_salary") or answers.get("salary"):
            rows.append({"cells": [
                "Basic Salary",
                str(answers.get("basic_salary") or answers.get("salary", "As agreed")),
                "Monthly"
            ]})
        if answers.get("hra"):
            rows.append({"cells": ["House Rent Allowance (HRA)", str(answers["hra"]), "Monthly"]})
        if answers.get("ctc"):
            rows.append({"cells": ["Total CTC", str(answers["ctc"]), "Annual"]})
        if len(rows) == 1:
            rows.append({"cells": ["Total CTC", answers.get("ctc", "As per offer letter"), "Annual"]})
        return rows

    # Invoice / pricing table
    if any(k in heading_lower for k in ["invoice", "pricing", "quotation", "bill", "purchase"]):
        rows = [{"cells": ["Description", "Quantity", "Unit Price", "Total"]}]
        rows.append({"cells": [
            answers.get("item_description", "Service/Product"),
            str(answers.get("quantity", "1")),
            str(answers.get("unit_price", answers.get("amount", "As agreed"))),
            str(answers.get("total_amount", answers.get("amount", "As agreed")))
        ]})
        return rows

    # Risk / findings table
    if any(k in heading_lower for k in ["risk", "finding", "vulnerability"]):
        rows = [{"cells": ["Item", "Description", "Severity", "Status"]}]
        rows.append({"cells": [
            "Item 1",
            answers.get("finding_description", "As per assessment"),
            answers.get("severity", "Medium"),
            answers.get("status", "Open")
        ]})
        return rows

    # Generic fallback table
    rows = [{"cells": ["Item", "Details", "Status"]}]
    rows.append({"cells": ["Reference", answers.get("reference", today), "Active"]})
    return rows


# ═══════════════════════════════════════════════════════
# PDF RENDERER
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
        Table, TableStyle, PageBreak, HRFlowable, KeepTogether
    )
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY, TA_RIGHT

    buffer = io.BytesIO()
    PAGE_W = A4[0] - 5 * cm

    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=2.5*cm, leftMargin=2.5*cm,
        topMargin=2.5*cm,   bottomMargin=2.5*cm,
        title=title
    )

    cover_title = ParagraphStyle(
        "CoverTitle", fontSize=22, fontName="Helvetica-Bold",
        textColor=colors.HexColor("#1a1a1a"),
        alignment=TA_CENTER, spaceAfter=14, leading=30
    )
    cover_sub = ParagraphStyle(
        "CoverSub", fontSize=13, fontName="Helvetica",
        textColor=colors.HexColor("#444444"),
        alignment=TA_CENTER, spaceAfter=8
    )
    cover_meta = ParagraphStyle(
        "CoverMeta", fontSize=10, fontName="Helvetica",
        textColor=colors.HexColor("#888888"),
        alignment=TA_CENTER, spaceAfter=5
    )
    heading_style = ParagraphStyle(
        "SectionHeading", fontSize=11, fontName="Helvetica-Bold",
        textColor=colors.HexColor("#1a1a1a"),
        spaceBefore=18, spaceAfter=6, leading=15,
        backColor=colors.HexColor("#f2f2f2"),
        borderPadding=(5, 8, 5, 8),
        leftIndent=0, rightIndent=0
    )
    body_style = ParagraphStyle(
        "Body", fontSize=10, fontName="Helvetica",
        leading=16, spaceAfter=7, spaceBefore=2,
        alignment=TA_JUSTIFY, firstLineIndent=0
    )
    list_item_style = ParagraphStyle(
        "ListItem", fontSize=10, fontName="Helvetica",
        leading=15, spaceAfter=4, leftIndent=18, firstLineIndent=-10
    )

    story = []

    # Cover page
    story.append(Spacer(1, 3 * cm))
    company_name = company.get("name", "") if company else ""
    if company_name:
        story.append(Paragraph(_clean_text(company_name), cover_sub))
        story.append(Spacer(1, 0.4 * cm))

    story.append(HRFlowable(width=PAGE_W, thickness=2,
                             color=colors.HexColor("#1a1a1a"), spaceAfter=14))
    story.append(Paragraph(_clean_text(title), cover_title))
    story.append(HRFlowable(width=PAGE_W, thickness=1,
                             color=colors.HexColor("#cccccc"), spaceBefore=14, spaceAfter=18))

    if department:
        story.append(Paragraph(f"Department: {_clean_text(department)}", cover_meta))
    if company:
        if company.get("industry"):
            story.append(Paragraph(f"Industry: {_clean_text(company.get('industry', ''))}", cover_meta))
        if company.get("location"):
            story.append(Paragraph(f"Location: {_clean_text(company.get('location', ''))}", cover_meta))

    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph(f"Generated: {date.today().strftime('%d %B %Y')}", cover_meta))
    story.append(Spacer(1, 4 * cm))
    story.append(PageBreak())

    align_map = {
        "left":    TA_LEFT,
        "center":  TA_CENTER,
        "justify": TA_JUSTIFY,
        "right":   TA_RIGHT,
    }

    for section in structured_sections:
        heading      = _clean_text(section.get("heading", ""))
        content_type = section.get("content_type", "text")
        content      = section.get("content", "")
        styling      = section.get("styling", {})
        align        = align_map.get(styling.get("alignment", "justify"), TA_JUSTIFY)

        section_story = []

        if heading:
            section_story.append(Paragraph(heading, heading_style))
            section_story.append(Spacer(1, 0.15 * cm))

        if content_type == "text" and isinstance(content, str):
            para_style = ParagraphStyle("DynBody", parent=body_style, alignment=align)
            normalized = re.sub(r'(?<!\n)\n(?!\n)', ' ', content)
            paragraphs = [p.strip() for p in normalized.split("\n\n") if p.strip()]
            for para in paragraphs:
                clean = _clean_text(para)
                if clean and len(clean) > 3:
                    section_story.append(Paragraph(clean, para_style))
                    section_story.append(Spacer(1, 0.18 * cm))

        elif content_type == "table" and isinstance(content, list) and content:
            table_data = [
                [_clean_text(str(c)) for c in row.get("cells", [])]
                for row in content
            ]
            if table_data and table_data[0]:
                col_count = len(table_data[0])
                col_width = PAGE_W / col_count
                t = Table(
                    table_data,
                    colWidths=[col_width] * col_count,
                    repeatRows=1
                )
                t.setStyle(TableStyle([
                    ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#2c2c2c")),
                    ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
                    ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
                    ("FONTSIZE",      (0, 0), (-1, 0),  9),
                    ("TOPPADDING",    (0, 0), (-1, 0),  7),
                    ("BOTTOMPADDING", (0, 0), (-1, 0),  7),
                    ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
                    ("FONTSIZE",      (0, 1), (-1, -1), 9),
                    ("TOPPADDING",    (0, 1), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
                    ("LEFTPADDING",   (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                     [colors.white, colors.HexColor("#f7f7f7")]),
                    ("GRID",          (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
                    ("ALIGN",         (0, 0), (-1, -1), "LEFT"),
                    ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                    ("WORDWRAP",      (0, 0), (-1, -1), True),
                ]))
                section_story.append(t)
                section_story.append(Spacer(1, 0.4 * cm))

        elif content_type == "list" and isinstance(content, list):
            for item in content:
                clean = _clean_text(str(item))
                if clean:
                    section_story.append(
                        Paragraph(f"\u2022  {clean}", list_item_style)
                    )
            section_story.append(Spacer(1, 0.25 * cm))

        if styling.get("page_break_after"):
            section_story.append(PageBreak())
        else:
            section_story.append(Spacer(1, 0.25 * cm))

        if section_story:
            story.append(KeepTogether(section_story[:3]))
            story.extend(section_story[3:])

    doc.build(story)
    buffer.seek(0)
    return buffer.read()


# ═══════════════════════════════════════════════════════
# DOCX RENDERER
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
        sec.top_margin    = Cm(2.5)
        sec.bottom_margin = Cm(2.5)
        sec.left_margin   = Cm(2.5)
        sec.right_margin  = Cm(2.5)

    def add_para(text, bold=False, size=10,
                 align=WD_ALIGN_PARAGRAPH.LEFT,
                 sb=0, sa=6, color=None, italic=False):
        p = doc.add_paragraph()
        p.alignment = align
        p.paragraph_format.space_before = Pt(sb)
        p.paragraph_format.space_after  = Pt(sa)
        run = p.add_run(_clean_text(text))
        run.bold   = bold
        run.italic = italic
        run.font.size = Pt(size)
        if color:
            run.font.color.rgb = RGBColor(*color)
        return p

    def add_hr(doc_obj):
        p   = doc_obj.add_paragraph()
        p.paragraph_format.space_after = Pt(10)
        pPr = p._p.get_or_add_pPr()
        pBdr = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"),   "single")
        bottom.set(qn("w:sz"),    "12")
        bottom.set(qn("w:space"), "1")
        bottom.set(qn("w:color"), "1a1a1a")
        pBdr.append(bottom)
        pPr.append(pBdr)
        return p

    # Cover page
    doc.add_paragraph()
    doc.add_paragraph()

    company_name = company.get("name", "") if company else ""
    if company_name:
        add_para(company_name, size=13, align=WD_ALIGN_PARAGRAPH.CENTER,
                 sa=8, color=(68, 68, 68))

    add_hr(doc)
    add_para(title, bold=True, size=20,
             align=WD_ALIGN_PARAGRAPH.CENTER,
             sb=10, sa=10, color=(26, 26, 26))
    add_hr(doc)

    if department:
        add_para(f"Department: {department}", size=10,
                 align=WD_ALIGN_PARAGRAPH.CENTER, sa=4, color=(100, 100, 100))
    if company:
        if company.get("industry"):
            add_para(f"Industry: {company.get('industry', '')}",
                     size=10, align=WD_ALIGN_PARAGRAPH.CENTER,
                     sa=4, color=(100, 100, 100))
        if company.get("location"):
            add_para(f"Location: {company.get('location', '')}",
                     size=10, align=WD_ALIGN_PARAGRAPH.CENTER,
                     sa=4, color=(100, 100, 100))

    add_para(f"Generated: {date.today().strftime('%d %B %Y')}",
             size=10, align=WD_ALIGN_PARAGRAPH.CENTER,
             sa=4, color=(136, 136, 136))

    doc.add_page_break()

    align_map = {
        "left":    WD_ALIGN_PARAGRAPH.LEFT,
        "center":  WD_ALIGN_PARAGRAPH.CENTER,
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
    }

    for section_data in structured_sections:
        heading      = _clean_text(section_data.get("heading", ""))
        content_type = section_data.get("content_type", "text")
        content      = section_data.get("content", "")
        styling      = section_data.get("styling", {})
        para_align   = align_map.get(
            styling.get("alignment", "justify"),
            WD_ALIGN_PARAGRAPH.JUSTIFY
        )

        # Section heading with shaded background
        if heading:
            h = doc.add_paragraph()
            h.paragraph_format.space_before = Pt(16)
            h.paragraph_format.space_after  = Pt(6)
            pPr   = h._p.get_or_add_pPr()
            shd   = OxmlElement("w:shd")
            shd.set(qn("w:val"),   "clear")
            shd.set(qn("w:color"), "auto")
            shd.set(qn("w:fill"),  "F2F2F2")
            pPr.append(shd)
            run = h.add_run(heading)
            run.bold           = True
            run.font.size      = Pt(11)
            run.font.color.rgb = RGBColor(26, 26, 26)

        if content_type == "text" and isinstance(content, str):
            normalized = re.sub(r'(?<!\n)\n(?!\n)', ' ', content)
            for para_text in normalized.split("\n\n"):
                clean = _clean_text(para_text.strip())
                if not clean:
                    continue
                p = doc.add_paragraph()
                p.alignment                     = para_align
                p.paragraph_format.space_before = Pt(2)
                p.paragraph_format.space_after  = Pt(6)
                p.paragraph_format.line_spacing = Pt(15)
                run = p.add_run(clean)
                run.font.size = Pt(10)

        elif content_type == "table" and isinstance(content, list) and content:
            rows = len(content)
            cols = max((len(r.get("cells", [])) for r in content), default=0)
            if rows > 0 and cols > 0:
                table = doc.add_table(rows=rows, cols=cols)
                table.style = "Table Grid"
                for i, row_data in enumerate(content):
                    cells = row_data.get("cells", [])
                    for j in range(cols):
                        cell_text = cells[j] if j < len(cells) else ""
                        cell      = table.cell(i, j)
                        cell.text = _clean_text(str(cell_text))
                        p         = cell.paragraphs[0]
                        p.paragraph_format.space_before = Pt(3)
                        p.paragraph_format.space_after  = Pt(3)
                        if p.runs:
                            p.runs[0].font.size = Pt(9)
                            if i == 0:
                                p.runs[0].bold = True
                                tc_pr = cell._tc.get_or_add_tcPr()
                                shd   = OxmlElement("w:shd")
                                shd.set(qn("w:val"),   "clear")
                                shd.set(qn("w:color"), "auto")
                                shd.set(qn("w:fill"),  "2C2C2C")
                                tc_pr.append(shd)
                                p.runs[0].font.color.rgb = RGBColor(255, 255, 255)
                p_space = doc.add_paragraph()
                p_space.paragraph_format.space_after = Pt(8)

        elif content_type == "list" and isinstance(content, list):
            for item in content:
                clean = _clean_text(str(item))
                if clean:
                    p = doc.add_paragraph(style="List Bullet")
                    p.paragraph_format.space_before = Pt(1)
                    p.paragraph_format.space_after  = Pt(3)
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
def save_document(
    db: Session,
    session_id: UUID,
    template_id: int,
    title: str,
    content: str,
    structured_sections=None
):
    """Always stores structured JSON as {"sections": [...]} dict — never bare list."""
    if structured_sections is not None:
        if isinstance(structured_sections, list):
            structured_json_str = json.dumps({"sections": structured_sections})
        elif isinstance(structured_sections, dict):
            if "sections" not in structured_sections:
                structured_sections["sections"] = []
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

    sections   = crud.get_sections_by_template(db, doc.template_id)
    template   = crud.get_template_by_id(db, doc.template_id)
    session    = crud.get_session_by_id(db, doc.session_id)
    department = crud.get_department_by_id(db, session.department_id)

    if doc.structured_json:
        try:
            raw        = json.loads(doc.structured_json)
            structured = _normalize_structured(raw)
        except Exception:
            structured = {"sections": []}
    else:
        structured = {"sections": []}

    # Apply auto-fixes first — replace any residual placeholders using stored answers
    if answers:
        structured = _auto_fix_structured(structured, answers, sections, db)
        # Persist the fixed version back
        try:
            doc.structured_json = json.dumps(structured)
            db.commit()
        except Exception:
            pass

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
    """
    Regenerate a single section.
    - Uses full answers context so no placeholders appear
    - Role-aware depth instructions
    - Cleans and validates output before saving
    - Handles table sections with fallback builder
    """
    doc = crud.get_document_by_id(db, document_id)
    if not doc:
        return {"error": "Document not found"}

    template   = crud.get_template_by_id(db, doc.template_id)
    session    = crud.get_session_by_id(db, doc.session_id)
    department = crud.get_department_by_id(db, session.department_id)

    tone         = company.get("tone", "Professional") if company else "Professional"
    company_name = company.get("name", "") if company else ""

    role      = classify_section_role(section_name)
    needs_tbl = section_needs_table(section_name)
    today     = date.today().strftime("%d %B %Y")

    role_instruction = ROLE_INSTRUCTIONS.get(role, ROLE_INSTRUCTIONS["BODY"])
    role_instruction = role_instruction.replace("{today}", today)

    # Build answers context — include all keys, mark blanks explicitly
    answers_fmt = _answers_to_context(answers or {})

    table_instruction = ""
    if needs_tbl:
        table_instruction = (
            "\n\nTABLE REQUIREMENT: This section MUST be formatted as a structured table. "
            "Build real rows using the exact values from the variable data above. "
            "Format: plain text rows, no pipe | characters, no markdown.\n"
            "Example row structure: Component | Value | Notes\n"
        )

    feedback_note = f"\n\nUSER INSTRUCTION (apply exactly): {feedback}\n" if feedback else ""

    # Get current document content for style reference
    original_snippet = ""
    if doc.structured_json:
        try:
            structured = _normalize_structured(json.loads(doc.structured_json))
            # Find an OPENER or BODY section for style reference
            for s in structured.get("sections", []):
                role_ref = classify_section_role(s.get("heading", ""))
                if role_ref in ("OPENER", "BODY") and isinstance(s.get("content"), str):
                    original_snippet = s["content"][:1500]
                    break
        except Exception:
            pass

    if not original_snippet and doc.content:
        original_snippet = doc.content[:1500]

    system_prompt = (
        f"You are an expert professional document writer for "
        f"{company_name or (department.name if department else 'the organisation')}. "
        f"Tone: {tone}. "
        f"Rules: No markdown (no ##, no **, no --). Clean plain text only. "
        f"Today is {today}. "
        f"CRITICAL: Never use [DATE], [NAME], [AMOUNT] or any bracket placeholder. "
        f"Use the exact values from the variable data. "
        f"If a value is genuinely missing, write 'Not Provided' — do not invent values."
    )

    section_prompt = f"""TASK: Regenerate the '{section_name}' section for a {template.name} document.

DOCUMENT CONTEXT:
- Document Type: {template.name}
- Department: {department.name if department else 'N/A'}
- Template Purpose: {template.description if hasattr(template, 'description') and template.description else 'Professional business document'}
- Today's Date: {today}

SECTION ROLE: {role}
DEPTH AND FORMAT INSTRUCTION:
{role_instruction}
{table_instruction}{feedback_note}

STYLE REFERENCE (match this document's tone and formatting):
{original_snippet}

VARIABLE DATA — USE ALL APPLICABLE VALUES (do not ignore any):
{answers_fmt}

OUTPUT RULES:
1. Write ONLY the content body for '{section_name}' — do NOT include the section heading
2. No markdown symbols anywhere
3. No [bracket] placeholders — use real values from variable data above
4. Use 'Not Provided' only if the value is genuinely absent from variable data
5. Meet the minimum word count for {role} role
6. Every sentence must add value — no padding or filler phrases"""

    new_content       = llm_service.generate_with_llm(section_prompt, system_prompt)
    new_content_clean = _clean_text(_replace_placeholders(new_content, answers))

    # Determine final content type
    final_content_type = "table" if needs_tbl else "text"

    # For table sections: parse the LLM text output into table rows
    # or use fallback builder if parsing fails
    table_rows = None
    if needs_tbl:
        table_rows = _parse_text_to_table_rows(new_content_clean)
        if not table_rows or len(table_rows) < 2:
            table_rows = _build_fallback_table(section_name, answers or {})

    # Update structured JSON
    if doc.structured_json:
        try:
            raw        = json.loads(doc.structured_json)
            structured = _normalize_structured(raw)
            updated    = False

            for s in structured.get("sections", []):
                if section_name.lower() in s.get("heading", "").lower():
                    if needs_tbl and table_rows:
                        s["content_type"] = "table"
                        s["content"]      = table_rows
                        s["word_count"]   = 0
                    else:
                        s["content_type"] = "text"
                        s["content"]      = new_content_clean
                        s["word_count"]   = len(new_content_clean.split())
                    updated = True
                    break

            if not updated:
                new_section = {
                    "id":           f"section_regen_{section_name[:10]}",
                    "heading":      section_name,
                    "content_type": final_content_type,
                    "content":      table_rows if needs_tbl and table_rows else new_content_clean,
                    "styling":      {
                        "alignment": "justify",
                        "font_weight": "normal",
                        "page_break_after": False
                    },
                    "word_count": 0 if needs_tbl else len(new_content_clean.split())
                }
                structured["sections"].append(new_section)

            doc.structured_json = json.dumps(structured)
            db.commit()
        except Exception:
            pass

    updated_doc = crud.update_document_section(
        db, document_id, section_name, new_content_clean
    )

    return_content = new_content_clean
    if needs_tbl and table_rows:
        return_content = json.dumps(table_rows)

    return {
        "document_id":     document_id,
        "section_name":    section_name,
        "updated_content": return_content,
        "status":          "regenerated"
    }


def _parse_text_to_table_rows(text: str) -> list:
    """
    Attempt to parse LLM plain-text output into table row dicts.
    Handles lines separated by |, tab, or multi-space.
    Returns list of {"cells": [...]} or empty list on failure.
    """
    rows = []
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    for line in lines:
        # Try pipe-separated
        if "|" in line:
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if len(cells) >= 2:
                rows.append({"cells": cells})
        # Try tab-separated
        elif "\t" in line:
            cells = [c.strip() for c in line.split("\t") if c.strip()]
            if len(cells) >= 2:
                rows.append({"cells": cells})
        # Try multiple-space separated (e.g. aligned columns)
        elif re.search(r'\s{3,}', line):
            cells = [c.strip() for c in re.split(r'\s{3,}', line) if c.strip()]
            if len(cells) >= 2:
                rows.append({"cells": cells})

    # Remove separator rows (rows whose cells are all dashes)
    rows = [r for r in rows if not all(re.match(r'^[-=]+$', c) for c in r["cells"])]

    return rows


def get_all_versions(db: Session, session_id: UUID):
    return crud.get_documents_by_session(db, session_id)