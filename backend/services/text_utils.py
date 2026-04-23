import re
from datetime import date
from typing import Optional


_CONTEXTUAL_DEFAULTS: dict[str, str] = {
    # People
    "name":              "the relevant party",
    "full name":         "the relevant party",
    "candidate name":    "the Candidate",
    "employee name":     "the Employee",
    "authorized by":     "the Authorised Signatory",
    "signatory":         "the Authorised Signatory",
    "approver":          "the Authorised Approver",
    # Organisation
    "company name":      "the Company",
    "organisation":      "the Organisation",
    "department":        "the Department",
    # Role / designation
    "designation":       "the relevant designation",
    "job title":         "the relevant position",
    "role":              "the relevant role",
    # Financial
    "salary":            "as per agreement",
    "ctc":               "as per agreement",
    "amount":            "as per agreement",
    "price":             "as per agreement",
    "compensation":      "as per agreement",
    # Location
    "location":          "the registered office",
    "address":           "the registered address",
    # Document references
    "reference":         "as referenced",
    "ref":               "as referenced",
}


def _contextual_fill(bracket_content: str, doc_context: Optional[dict] = None) -> str:
    
    token = bracket_content.strip().lower()

    # Direct or substring match
    for key, default in _CONTEXTUAL_DEFAULTS.items():
        if key in token:
            return default

    # Nothing matched — convert UPPER_SNAKE_CASE to a readable phrase
    readable = token.replace("_", " ").title()
    return f"the {readable}"


# ── Text cleaner ─────────────────────────────────────────────────────────────

def clean_text(text: str) -> str:
  
    if not text:
        return ""
    # Remove markdown heading markers
    text = re.sub(r"#{1,6}\s*", "", text)
    # Unwrap bold / italic
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*",     r"\1", text)
    text = re.sub(r"`(.*?)`",       r"\1", text)
    # Remove HR lines
    text = re.sub(r"^-{3,}$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^={3,}$", "", text, flags=re.MULTILINE)
    # Smart quotes → straight quotes
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    # Dashes
    text = text.replace("\u2013", "-").replace("\u2014", "--")
    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── Placeholder replacement ──────────────────────────────────────────────────

def replace_placeholders(
    text: str,
    answers: Optional[dict] = None,
    doc_context: Optional[dict] = None,
) -> str:
    
    today = date.today().strftime("%d %B %Y")

    if answers:
        field_map = {
            r"\[COMPANY[_ ]NAME\]":   answers.get("company_name", ""),
            r"\[CANDIDATE[_ ]NAME\]": answers.get("candidate_name", "") or answers.get("employee_name", ""),
            r"\[EMPLOYEE[_ ]NAME\]":  answers.get("employee_name", "") or answers.get("candidate_name", ""),
            r"\[JOB[_ ]TITLE\]":      answers.get("job_title", "") or answers.get("designation", ""),
            r"\[DESIGNATION\]":       answers.get("designation", "") or answers.get("job_title", ""),
            r"\[DEPARTMENT\]":        answers.get("department", ""),
            r"\[JOINING[_ ]DATE\]":   answers.get("joining_date", today),
            r"\[SALARY\]":            answers.get("salary", "") or answers.get("ctc", ""),
            r"\[CTC\]":               answers.get("ctc", "") or answers.get("salary", ""),
            r"\[LOCATION\]":          answers.get("location", ""),
        }
        for pattern, value in field_map.items():
            if value and str(value).strip():
                text = re.sub(pattern, str(value).strip(), text, flags=re.IGNORECASE)

    # Date tokens
    text = re.sub(r"\[DATE\]|\[date\]|\[Date\]", today, text)
    text = re.sub(r"\[TODAY\]|\[today\]",         today, text)
    text = re.sub(r"\[YEAR\]",  str(date.today().year),       text)
    text = re.sub(r"\[MONTH\]", date.today().strftime("%B"),  text)

    # Common explicit patterns
    text = re.sub(r"\[TBD\]|\bTBD\b",   "to be confirmed",    text)
    text = re.sub(r"\[INSERT[^\]]*\]",   _contextual_fill("INSERT", doc_context), text)
    text = re.sub(r"\[ADD[^\]]*\]",      "",                   text)

   
    def _replace_caps_bracket(m: re.Match) -> str:
        inner = m.group(1)
        return _contextual_fill(inner, doc_context)

    text = re.sub(r"\[([A-Z][A-Z\s_]{2,})\]", _replace_caps_bracket, text)

    return text


# ── Answer sanitisation (prompt injection protection) ────────────────────────

_INJECTION_PATTERNS = re.compile(
    r"(ignore\s+(previous|all|above|prior)\s+instructions?|"
    r"you\s+are\s+now\s+|"
    r"system\s*:|"
    r"assistant\s*:|"
    r"<\|.+?\|>|"         
    r"\\n\\n###|"
    r"jailbreak)",
    re.IGNORECASE,
)

_MAX_ANSWER_LEN = 2000  


def sanitize_answer_value(value: str) -> str:
   
    if not value:
        return ""
    value = value[:_MAX_ANSWER_LEN]

    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
  
    value = _INJECTION_PATTERNS.sub("[redacted]", value)
    return value.strip()


def sanitize_answers(answers: dict) -> dict:
    """Return a new dict with all string values sanitised."""
    return {
        k: sanitize_answer_value(str(v)) if v is not None else ""
        for k, v in answers.items()
    }


# ── Answer → prompt context string ──────────────────────────────────────────

def format_answers(answers: dict) -> str:
   
    if not answers:
        return "  No specific details provided — use professional defaults."
    return "\n".join(
        f"  {k}: {str(v).strip() if v and str(v).strip() else 'not specified'}"
        for k, v in answers.items()
    )


# ── Structured JSON normalisation ────────────────────────────────────────────

def normalize_structured(raw) -> dict:
    """Always return {sections: [...]} regardless of input shape."""
    if isinstance(raw, dict):
        raw.setdefault("sections", [])
        return raw
    if isinstance(raw, list):
        return {"sections": raw}
    return {"sections": []}


# ── Auto-fix — placeholder replacement + table repair ────────────────────────

def auto_fix_structured(
    structured: dict,
    answers: Optional[dict],
    sections_db: list,
) -> dict:
  
    from backend.services.section_utils import section_needs_table

    structured = normalize_structured(structured)

    for section in structured.get("sections", []):
        heading      = section.get("heading", "")
        content_type = section.get("content_type", "text")
        content      = section.get("content", "")

        if content_type == "text" and isinstance(content, str):
            fixed = replace_placeholders(content, answers)
            section["content"]    = clean_text(fixed)
            section["word_count"] = len(section["content"].split())

        elif content_type == "table" and isinstance(content, list):
            fixed_rows = [
                {"cells": [
                    clean_text(replace_placeholders(str(c), answers))
                    for c in row["cells"]
                ]}
                for row in content
                if isinstance(row, dict) and "cells" in row
            ]
            if not fixed_rows and section_needs_table(heading):
                fixed_rows = _build_fallback_table(heading, answers or {})
            section["content"] = fixed_rows

        elif content_type == "list" and isinstance(content, list):
            section["content"] = [
                clean_text(replace_placeholders(str(item), answers))
                for item in content
                if str(item).strip()
            ]

    return structured


# ── Fallback table builder ────────────────────────────────────────────────────


def _build_fallback_table(section_heading: str, answers: dict) -> list:
    today = date.today().strftime("%d %B %Y")
    lower = section_heading.lower()

    if any(k in lower for k in ["compensation", "salary", "ctc", "earnings", "gross"]):
        rows = [{"cells": ["Component", "Amount (INR)", "Frequency"]}]
        if answers.get("basic_salary") or answers.get("salary"):
            rows.append({"cells": [
                "Basic Salary",
                str(answers.get("basic_salary") or answers.get("salary", "As per agreement")),
                "Monthly",
            ]})
        if answers.get("hra"):
            rows.append({"cells": ["House Rent Allowance (HRA)", str(answers["hra"]), "Monthly"]})
        if answers.get("ctc"):
            rows.append({"cells": ["Total CTC", str(answers["ctc"]), "Annual"]})
        if len(rows) == 1:
            rows.append({"cells": ["Total CTC", answers.get("ctc", "As per agreement"), "Annual"]})
        return rows

    if any(k in lower for k in ["invoice", "pricing", "quotation", "bill", "purchase"]):
        return [
            {"cells": ["Description", "Quantity", "Unit Price (INR)", "Total (INR)"]},
            {"cells": [
                answers.get("item_description", "Professional Services"),
                str(answers.get("quantity", "1")),
                str(answers.get("unit_price", answers.get("amount", "As per agreement"))),
                str(answers.get("total_amount", answers.get("amount", "As per agreement"))),
            ]},
        ]

    if any(k in lower for k in ["risk", "finding", "vulnerability"]):
        return [
            {"cells": ["Item", "Description", "Severity", "Status"]},
            {"cells": [
                "Finding 1",
                answers.get("finding_description", "As per assessment"),
                answers.get("severity", "Medium"),
                answers.get("status", "Open"),
            ]},
        ]

    if any(k in lower for k in ["timeline", "schedule", "milestone"]):
        return [
            {"cells": ["Milestone", "Owner", "Due Date", "Status"]},
            {"cells": [
                "Phase 1",
                answers.get("owner", "Project Lead"),
                answers.get("start_date", today),
                "Planned",
            ]},
        ]

    if any(k in lower for k in ["kpi", "metrics", "comparison"]):
        return [
            {"cells": ["Metric", "Target", "Actual", "Status"]},
            {"cells": [
                "Primary KPI",
                answers.get("target", "As defined"),
                answers.get("actual", "Pending"),
                "In Progress",
            ]},
        ]

    return [
        {"cells": ["Item", "Details", "Status"]},
        {"cells": ["Reference", answers.get("reference", today), "Active"]},
    ]

answers_to_context = format_answers