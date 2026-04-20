
import json
import re
from datetime import date
from typing import List

from sqlalchemy.orm import Session

from backend.database import crud
from backend.services.section_utils import (
    SECTION_DEPTH_WORDS,
    classify_section_role,
    section_needs_table,
)
from backend.services.text_utils import auto_fix_structured, normalize_structured
from backend.utils.logger import get_logger

logger = get_logger("docforge.services.validation")



class ValidationResult:
    def __init__(self):
        self.is_valid:           bool       = True
        self.issues:             List[dict] = []
        self.missing_sections:   List[str]  = []
        self.order_issues:       List[str]  = []
        self.table_issues:       List[str]  = []
        self.grounding_issues:   List[str]  = []
        self.placeholder_issues: List[str]  = []

    def add_issue(self, issue_type: str, section: str, detail: str, fatal: bool = True) -> None:
        if fatal:
            self.is_valid = False
        self.issues.append({
            "type":    issue_type,
            "section": section,
            "detail":  detail,
            "fatal":   fatal,
        })

    def to_dict(self) -> dict:
        return {
            "is_valid":           self.is_valid,
            "total_issues":       len(self.issues),
            "issues":             self.issues,
            "missing_sections":   self.missing_sections,
            "order_issues":       self.order_issues,
            "table_issues":       self.table_issues,
            "grounding_issues":   self.grounding_issues,
            "placeholder_issues": self.placeholder_issues,
        }


# ═══════════════════════════════════════════════════════
# PLACEHOLDER PATTERNS


# ═══════════════════════════════════════════════════════

_PLACEHOLDER_PATTERNS: list[str] = [
    # Explicit date / time
    r"\[DATE\]", r"\[date\]", r"\[Date\]",
    r"\[TODAY\]", r"\[today\]",
    # Explicit name placeholders
    r"\[NAME\]", r"\[name\]",
    r"\[INSERT[^\]]*\]",
    r"\[ADD[^\]]*\]",
    # Explicit content stubs
    r"\[MISSING_INFORMATION\]",
    r"\[TBD\]", r"\bTBD\b",
    r"\[.*?PLACEHOLDER.*?\]",
    # Specific field caps patterns
    r"\[COMPANY[^\]]*\]",
    r"\[CANDIDATE[^\]]*\]",
    r"\[EMPLOYEE[^\]]*\]",
    r"\[AMOUNT[^\]]*\]",
    r"\[SALARY[^\]]*\]",
    r"\[CTC[^\]]*\]",
    r"\[DESIGNATION[^\]]*\]",
    r"\[DEPARTMENT[^\]]*\]",
    r"\[LOCATION[^\]]*\]",
    # Safe catch-all — ALL-CAPS bracket content only (3+ chars)
    # MATCHES:  [FULL NAME], [COMPANY NAME], [REFERENCE NUMBER]
    # SKIPS:    [Schedule A], [Section 1.2], [Annexure B], [Exhibit C]
    r"\[[A-Z][A-Z\s_]{2,}\]",
]

_STUB_PHRASES: list[str] = [
    "content to be provided",
    "to be filled",
    "to be completed",
    "insert here",
    "add details here",
    "lorem ipsum",
    "this section requires additional information",
]

_GROUNDING_FIELDS: list[str] = [
    "company_name", "candidate_name", "employee_name",
    "job_title", "department", "joining_date",
    "designation", "salary", "ctc",
]


# ═══════════════════════════════════════════════════════
# PASS 1 — Required sections present
# ═══════════════════════════════════════════════════════

def _check_sections_present(
    structured: dict,
    sections: list,
    result: ValidationResult,
) -> None:
    generated = [s.get("heading", "").lower() for s in structured.get("sections", [])]
    for section in sections:
        name_lower = section.section_name.lower()
        if not any(name_lower in g for g in generated):
            result.missing_sections.append(section.section_name)
            result.add_issue(
                "MISSING_SECTION", section.section_name,
                f"Required section '{section.section_name}' not found in document",
            )


# ═══════════════════════════════════════════════════════
# PASS 2 — Sections follow template order
# ═══════════════════════════════════════════════════════

def _check_section_order(
    structured: dict,
    sections: list,
    result: ValidationResult,
) -> None:
    generated = [s.get("heading", "").lower() for s in structured.get("sections", [])]
    template  = [s.section_name.lower() for s in sections]

    positions = []
    for name in template:
        for i, heading in enumerate(generated):
            if name in heading:
                positions.append((name, i))
                break

    for i in range(len(positions) - 1):
        if positions[i][1] > positions[i + 1][1]:
            detail = f"'{positions[i][0]}' appears after '{positions[i + 1][0]}'"
            result.order_issues.append(detail)
            result.add_issue("ORDER_VIOLATION", positions[i][0], detail)


# ═══════════════════════════════════════════════════════
# PASS 3 — Table sections have real rows
# ═══════════════════════════════════════════════════════

def _check_table_sections(
    structured: dict,
    sections: list,
    result: ValidationResult,
) -> None:
    section_map = {s.get("heading", "").lower(): s for s in structured.get("sections", [])}

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
                f"'{section.section_name}' must be table — got '{matched.get('content_type')}'",
            )
        elif not matched.get("content"):
            result.table_issues.append(section.section_name)
            result.add_issue(
                "EMPTY_TABLE", section.section_name,
                f"Table in '{section.section_name}' has no rows",
            )
        elif len(matched.get("content", [])) < 2:
            result.table_issues.append(section.section_name)
            result.add_issue(
                "TABLE_NO_DATA", section.section_name,
                f"Table in '{section.section_name}' has a header row but no data rows",
            )


# ═══════════════════════════════════════════════════════
# PASS 4 — No unfilled placeholders or stub phrases
# ═══════════════════════════════════════════════════════

def _check_placeholders(
    structured: dict,
    result: ValidationResult,
) -> None:
    for section in structured.get("sections", []):
        content = section.get("content", "")
        heading = section.get("heading", "")

        if isinstance(content, str):
            for pattern in _PLACEHOLDER_PATTERNS:
                for item in re.findall(pattern, content, re.IGNORECASE):
                    result.placeholder_issues.append(item)
                    result.add_issue(
                        "PLACEHOLDER_FOUND", heading,
                        f"Unfilled placeholder '{item}' in section '{heading}'",
                    )
            content_lower = content.lower()
            for stub in _STUB_PHRASES:
                if stub in content_lower:
                    result.add_issue(
                        "STUB_CONTENT", heading,
                        f"Stub phrase found in '{heading}': '{stub}'",
                    )

        elif isinstance(content, list):
            for row in content:
                if isinstance(row, dict):
                    for cell in row.get("cells", []):
                        for pattern in _PLACEHOLDER_PATTERNS:
                            for item in re.findall(pattern, str(cell), re.IGNORECASE):
                                result.placeholder_issues.append(item)
                                result.add_issue(
                                    "PLACEHOLDER_FOUND", heading,
                                    f"Unfilled placeholder '{item}' in table of '{heading}'",
                                )


# ═══════════════════════════════════════════════════════
# PASS 5 — Key answer values appear in document

# ═══════════════════════════════════════════════════════

def _significant_tokens(value: str) -> list[str]:
  
    stop_words = {"the", "a", "an", "of", "in", "at", "on", "and", "or", "to", "for"}
    tokens = re.findall(r"[a-zA-Z0-9]+", value.lower())
    return [t for t in tokens if len(t) >= 2 and t not in stop_words]


def _check_answer_grounding(
    structured: dict,
    answers: dict,
    result: ValidationResult,
) -> None:
    if not answers:
        return

    all_text = " ".join(
        section.get("content", "")
        if isinstance(section.get("content", ""), str)
        else " ".join(
            " ".join(row.get("cells", []))
            for row in section.get("content", [])
            if isinstance(row, dict)
        )
        for section in structured.get("sections", [])
    ).lower()

    for field in _GROUNDING_FIELDS:
        value = str(answers.get(field, "")).strip()
        if not value or len(value) < 2 or value.lower() in ("", "none"):
            continue

        tokens = _significant_tokens(value)
        if not tokens:
            continue

        # All significant tokens must appear somewhere in the document text
        missing_tokens = [t for t in tokens if t not in all_text]
        if missing_tokens:
            result.grounding_issues.append(field)
            result.add_issue(
                "GROUNDING_FAILURE", field,
                f"'{field}' value ({value!r}) — tokens {missing_tokens} not found in document",
            )


# ═══════════════════════════════════════════════════════
# PASS 6 — Min AND max word count per section role
# ═══════════════════════════════════════════════════════

def _check_word_counts(
    structured: dict,
    sections: list,
    result: ValidationResult,
) -> None:
    for section in structured.get("sections", []):
        content = section.get("content", "")
        heading = section.get("heading", "")

        if not isinstance(content, str):
            continue

        word_count = len(content.split())
        role = classify_section_role(heading)
        min_w, max_w = SECTION_DEPTH_WORDS.get(role, (20, 9999))

        if role not in ("HEADER", "SIGN_OFF"):
            if word_count < min_w:
                result.add_issue(
                    "TOO_SHORT", heading,
                    f"'{heading}' has {word_count} words — minimum {min_w} for {role}",
                    fatal=True,
                )
            elif word_count > max_w * 2:
                # Non-fatal warning for severely over-length sections
                result.add_issue(
                    "TOO_LONG", heading,
                    f"'{heading}' has {word_count} words — exceeds 2× max ({max_w}) for {role}",
                    fatal=False,
                )


# ═══════════════════════════════════════════════════════
# PIPELINE
# ═══════════════════════════════════════════════════════

def run_validation_pipeline(
    structured: dict,
    sections: list,
    answers: dict = None,
) -> ValidationResult:
   
    result = ValidationResult()

    _check_sections_present(structured, sections, result)
    _check_section_order(structured, sections, result)
    _check_table_sections(structured, sections, result)
    _check_placeholders(structured, result)
    _check_answer_grounding(structured, answers or {}, result)
    _check_word_counts(structured, sections, result)

    logger.debug(
        "validation_pipeline | valid=%s fatal_issues=%d",
        result.is_valid,
        sum(1 for i in result.issues if i.get("fatal", True)),
    )
    return result


# ═══════════════════════════════════════════════════════
# DB VALIDATION SERVICE
# ═══════════════════════════════════════════════════════

def validate_document(
    db: Session,
    document_id: int,
    answers: dict = None,
) -> dict:
   
    logger.info("validate_document | doc_id=%d", document_id)

    doc = crud.get_document_by_id(db, document_id)
    if not doc:
        logger.warning("validate_document: document %d not found", document_id)
        return {"error": "Document not found"}

    sections   = crud.get_sections_by_template(db, doc.template_id)
    template   = crud.get_template_by_id(db, doc.template_id)
    session    = crud.get_session_by_id(db, doc.session_id)
    department = crud.get_department_by_id(db, session.department_id)

    # Load structured JSON
    structured: dict = {"sections": []}
    if doc.structured_json:
        try:
            raw = json.loads(doc.structured_json)
            structured = normalize_structured(raw)
        except Exception as exc:
            logger.warning("validate_document: cannot parse structured_json: %s", exc)

    # Auto-fix placeholders using answers — imports from text_utils only (no circular dep)
    if answers:
        structured = auto_fix_structured(structured, answers, sections)
        try:
            doc.structured_json = json.dumps(structured)
            db.commit()
        except Exception as exc:
            logger.warning("validate_document: cannot persist auto-fix: %s", exc)

    result = run_validation_pipeline(
        structured=structured,
        sections=sections,
        answers=answers,
    )

    payload = {
        **result.to_dict(),
        "checked_at":    date.today().isoformat(),
        "template_name": template.name if template else "",
        "department":    department.name if department else "",
    }

    status = "validated" if result.is_valid else "needs_review"
    crud.update_document_validation(db, document_id, status, json.dumps(payload))

    logger.info(
        "validate_document: doc_id=%d status=%s issues=%d",
        document_id, status, len(result.issues),
    )
    return {"document_id": document_id, **result.to_dict()}