# import json
# import re
# from datetime import date
# from typing import List

# from sqlalchemy.orm import Session

# from backend.database import crud
# from backend.services.section_utils import SECTION_DEPTH_WORDS, classify_section_role
# from backend.services.text_utils import normalize_structured
# from backend.utils.logger import get_logger

# logger = get_logger("docforge.services.validation")


# class ValidationResult:
#     def __init__(self):
#         self.is_valid:           bool       = True
#         self.issues:             List[dict] = []
#         self.missing_sections:   List[str]  = []
#         self.placeholder_issues: List[str]  = []

#     def add_issue(self, issue_type: str, section: str, detail: str, fatal: bool = True) -> None:
#         if fatal:
#             self.is_valid = False
#         self.issues.append({
#             "type":    issue_type,
#             "section": section,
#             "detail":  detail,
#             "fatal":   fatal,
#         })

#     def to_dict(self) -> dict:
#         return {
#             "is_valid":           self.is_valid,
#             "total_issues":       len(self.issues),
#             "issues":             self.issues,
#             "missing_sections":   self.missing_sections,
#             "placeholder_issues": self.placeholder_issues,
#         }


# # ── Single compiled pattern for all placeholder forms ─────────────────────────
# _PLACEHOLDER_RE = re.compile(
#     r"\[[A-Z][A-Z\s_]{2,}\]"       # [CAPS PLACEHOLDER]
#     r"|\[(?:INSERT|ADD|TBD)[^\]]*\]"  # [INSERT X], [ADD X], [TBD]
#     r"|\bTBD\b",
#     re.IGNORECASE,
# )

# _STUB_PHRASES = (
#     "content to be provided",
#     "to be filled",
#     "to be completed",
#     "insert here",
#     "add details here",
#     "lorem ipsum",
# )


# # ═══════════════════════════════════════════════════════
# # PASS 1 — Required sections present
# # ═══════════════════════════════════════════════════════

# def _check_sections_present(
#     structured: dict,
#     sections: list,
#     result: ValidationResult,
# ) -> None:
#     generated = [s.get("heading", "").lower() for s in structured.get("sections", [])]
#     for section in sections:
#         name_lower = section.section_name.lower()
#         if not any(name_lower in g for g in generated):
#             result.missing_sections.append(section.section_name)
#             result.add_issue(
#                 "MISSING_SECTION", section.section_name,
#                 f"Required section '{section.section_name}' not found in document",
#             )


# # ═══════════════════════════════════════════════════════
# # PASS 2 — No unfilled placeholders or stub phrases
# # ═══════════════════════════════════════════════════════

# def _check_placeholders(
#     structured: dict,
#     result: ValidationResult,
# ) -> None:
#     for section in structured.get("sections", []):
#         heading = section.get("heading", "")
#         content = section.get("content", "")

#         # Flatten content to a single string regardless of type
#         if isinstance(content, list):
#             text = " ".join(
#                 " ".join(str(c) for c in row.get("cells", []))
#                 for row in content if isinstance(row, dict)
#             )
#         else:
#             text = content or ""

#         for match in _PLACEHOLDER_RE.findall(text):
#             result.placeholder_issues.append(match)
#             result.add_issue(
#                 "PLACEHOLDER_FOUND", heading,
#                 f"Unfilled placeholder '{match}' in '{heading}'",
#             )

#         text_lower = text.lower()
#         for stub in _STUB_PHRASES:
#             if stub in text_lower:
#                 result.add_issue(
#                     "STUB_CONTENT", heading,
#                     f"Stub phrase '{stub}' found in '{heading}'",
#                 )


# # ═══════════════════════════════════════════════════════
# # PASS 3 — Minimum word count per section role
# # ═══════════════════════════════════════════════════════

# def _check_word_counts(
#     structured: dict,
#     result: ValidationResult,
# ) -> None:
#     for section in structured.get("sections", []):
#         content = section.get("content", "")
#         heading = section.get("heading", "")

#         if not isinstance(content, str):
#             continue

#         role    = classify_section_role(heading)
#         if role in ("HEADER", "SIGN_OFF"):
#             continue

#         word_count = len(content.split())
#         min_w, _   = SECTION_DEPTH_WORDS.get(role, (20, 9999))

#         if word_count < min_w:
#             result.add_issue(
#                 "TOO_SHORT", heading,
#                 f"'{heading}' has {word_count} words — minimum {min_w} for {role}",
#                 fatal=True,
#             )


# # ═══════════════════════════════════════════════════════
# # PIPELINE
# # ═══════════════════════════════════════════════════════

# def run_validation_pipeline(
#     structured: dict,
#     sections: list,
#     answers: dict = None,
# ) -> ValidationResult:
#     result = ValidationResult()
#     _check_sections_present(structured, sections, result)
#     _check_placeholders(structured, result)
#     _check_word_counts(structured, result)
#     logger.debug(
#         "validation_pipeline | valid=%s fatal_issues=%d",
#         result.is_valid,
#         sum(1 for i in result.issues if i.get("fatal", True)),
#     )
#     return result


# # ═══════════════════════════════════════════════════════
# # DB VALIDATION SERVICE
# # ═══════════════════════════════════════════════════════

# def validate_document(
#     db: Session,
#     document_id: int,
#     answers: dict = None,
# ) -> dict:
#     logger.info("validate_document | doc_id=%d", document_id)

#     doc = crud.get_document_by_id(db, document_id)
#     if not doc:
#         return {"error": "Document not found"}

#     sections   = crud.get_sections_by_template(db, doc.template_id)
#     template   = crud.get_template_by_id(db, doc.template_id)
#     session    = crud.get_session_by_id(db, doc.session_id) if doc.session_id else None
#     department = crud.get_department_by_id(db, session.department_id) if session else None

#     structured: dict = {"sections": []}
#     if doc.structured_json:
#         try:
#             structured = normalize_structured(json.loads(doc.structured_json))
#         except Exception as exc:
#             logger.warning("validate_document: cannot parse structured_json: %s", exc)

#     result = run_validation_pipeline(structured=structured, sections=sections, answers=answers)

#     payload = {
#         **result.to_dict(),
#         "checked_at":    date.today().isoformat(),
#         "template_name": template.name if template else "",
#         "department":    department.name if department else "",
#     }

#     status = "validated" if result.is_valid else "needs_review"
#     crud.update_document_validation(db, document_id, status, json.dumps(payload))

#     logger.info(
#         "validate_document | doc_id=%d status=%s issues=%d",
#         document_id, status, len(result.issues),
#     )
#     return {"document_id": document_id, **result.to_dict()}