# import json
# import re
# from typing import Optional
# from sqlalchemy.orm import Session
# from backend.database import crud
# from backend.schemas.schemas import (
#     GenerateQuestionsResponse,
#     SectionFieldResponse,
#     SectionWithFieldsResponse,
# )
# from backend.services import llm_service
# from backend.utils.logger import get_logger

# logger = get_logger("docforge.services.question")


# # ═══════════════════════════════════════════════════════
# # SYSTEM PROMPT
# # ═══════════════════════════════════════════════════════

# QUESTION_SYSTEM_PROMPT = """\
# You are a professional business document consultant.
# Your job is to generate clear, professional intake-form questions for a document template.

# OBJECTIVE
# ─────────
# For every section provided, generate a question for every field in that section.
# Never skip a section. Never skip a required field.
# Optional fields may be skipped only if they are completely self-explanatory.

# QUESTION QUALITY RULES
# ──────────────────────
# - Questions must be specific to the document type and department — not generic.
# - Formal, professional language. No vague or repetitive phrasing.
# - Never write "What is [field_name]?" — rephrase as a real business question.
# - Date fields: ask what the date represents and request DD/MM/YYYY format.
# - Number fields: specify the unit, currency, or scale expected.
# - Textarea fields: ask an open-ended question that invites rich, detailed input.
# - Required fields: always include without exception.

# OUTPUT FORMAT
# ─────────────
# Return ONLY valid JSON. No preamble. No markdown fences. No explanation.

# {
#   "questions_by_section": {
#     "Exact Section Name": [
#       { "field_name": "exact_field_name", "question": "Professional question text?" }
#     ]
#   }
# }

# Every section name must match exactly. Every field_name must match exactly.
# """

# _FEW_SHOT_EXAMPLES = """\
# EXAMPLES OF HIGH-QUALITY QUESTIONS:

# HR | Offer Letter
#   Section "Header"
#     candidate_full_name → "What is the candidate's full legal name as it should appear on the offer letter?"
#     joining_date        → "What is the proposed date of joining? (DD/MM/YYYY)"

#   Section "Compensation and Benefits"
#     basic_salary  → "What is the employee's monthly basic salary in INR?"
#     total_ctc     → "What is the total annual Cost to Company (CTC) being offered in INR?"
#     hra           → "What is the monthly House Rent Allowance (HRA) component in INR?"

# Legal | NDA
#   Section "Confidentiality Obligations"
#     confidentiality_period → "For how many years should confidentiality obligations remain enforceable after the agreement terminates?"
#     permitted_disclosures  → "Are there any parties or circumstances under which disclosure of confidential information is permitted?"

# IT | Security Audit Report
#   Section "Findings and Risk Assessment"
#     vulnerability_count → "How many vulnerabilities were identified in total during this audit?"
#     critical_issues     → "List all critical-severity issues found, including CVE references where applicable."
#     affected_systems    → "Which systems or services were found to be affected by the identified vulnerabilities?"
# """


# # ═══════════════════════════════════════════════════════
# # PROMPT BUILDER
# # ═══════════════════════════════════════════════════════

# def _build_prompt(
#     department_name: str,
#     template_name: str,
#     sections_with_fields: list,
#     company: Optional[dict] = None,
# ) -> str:
#     company_ctx = (
#         f"Company: {company.get('name', 'Not specified')}"
#         f" | Industry: {company.get('industry', 'Not specified')}"
#         f" | Size: {company.get('size', 'Not specified')}"
#         f" | Tone: {company.get('tone', 'Professional')}"
#         if company and any(company.values())
#         else "Company: Not specified. Use neutral professional tone."
#     )

#     sections_text = ""
#     for section in sections_with_fields:
#         sections_text += f'\nSection: "{section["section_name"]}"\n'
#         for field in section.get("fields", []):
#             req_tag = "REQUIRED" if field.is_required else "optional"
#             sections_text += (
#                 f"  - field_name: {field.field_name}"
#                 f" | label: {field.field_label}"
#                 f" | type: {field.field_type}"
#                 f" | {req_tag}\n"
#             )

#     total_sections = len(sections_with_fields)
#     total_fields   = sum(len(s.get("fields", [])) for s in sections_with_fields)

#     return (
#         f"{_FEW_SHOT_EXAMPLES}\n"
#         f"───────────────────────────────────────\n"
#         f"NOW GENERATE QUESTIONS FOR:\n\n"
#         f"{company_ctx}\n"
#         f"Department: {department_name}\n"
#         f"Document Type: {template_name}\n"
#         f"Total sections: {total_sections} | Total fields: {total_fields}\n"
#         f"\nSECTIONS AND FIELDS:\n"
#         f"{sections_text}\n"
#         f"───────────────────────────────────────\n"
#         f"RULES:\n"
#         f"- Include ALL {total_sections} sections in questions_by_section.\n"
#         f"- Use exact section names and exact field_names.\n"
#         f"- Never skip a REQUIRED field.\n"
#         f"- Return ONLY valid JSON. No markdown. No extra text.\n"
#     )


# # ═══════════════════════════════════════════════════════
# # JSON PARSER
# # ═══════════════════════════════════════════════════════

# def _parse_response(response: str) -> Optional[dict]:
#     if not response:
#         return None
#     cleaned = re.sub(r"```(?:json)?|```", "", response).strip()
#     try:
#         return json.loads(cleaned)
#     except json.JSONDecodeError:
#         pass
#     # One fallback: find outermost {...} block
#     match = re.search(r"\{.*\}", cleaned, re.DOTALL)
#     if match:
#         try:
#             return json.loads(match.group())
#         except json.JSONDecodeError:
#             pass
#     logger.warning("_parse_response: could not parse LLM output")
#     return None


# # ═══════════════════════════════════════════════════════
# # FALLBACK — type-aware label-based questions
# # ═══════════════════════════════════════════════════════

# def _fallback_questions(sections_with_fields: list) -> dict:
#     result = {}
#     for section in sections_with_fields:
#         for field in section.get("fields", []):
#             fn    = field.field_name
#             label = field.field_label or fn.replace("_", " ").title()
#             ftype = field.field_type

#             if ftype == "date":
#                 result[fn] = f"What is the {label.lower()}? (DD/MM/YYYY)"
#             elif ftype == "number":
#                 result[fn] = f"What is the {label.lower()}? (numeric value)"
#             elif ftype == "textarea":
#                 result[fn] = f"Please provide details for: {label}"
#             else:
#                 result[fn] = f"What is the {label}?"

#     # logger AFTER loop — not inside it
#     logger.info("_fallback_questions: generated %d fallback questions", len(result))
#     return result


# # ═══════════════════════════════════════════════════════
# # MAIN GENERATION
# # ═══════════════════════════════════════════════════════

# def generate_smart_questions(
#     department_name: str,
#     template_name: str,
#     sections_with_fields: list,
#     company: Optional[dict] = None,
# ) -> dict:
#     """
#     Returns flat {field_name: question} dict for all fields.
#     Uses section-driven LLM output then flattens to field-level.
#     Falls back to label-based questions on any failure.
#     """
#     logger.info(
#         "generate_smart_questions | dept=%r template=%r sections=%d",
#         department_name, template_name, len(sections_with_fields),
#     )

#     system      = QUESTION_SYSTEM_PROMPT
#     user_prompt = _build_prompt(
#         department_name, template_name, sections_with_fields, company
#     )

#     try:
#         response = llm_service.generate_with_llm_json(
#             user_prompt=user_prompt,
#             system_prompt=system,
#         )
#         parsed = _parse_response(response)

#         if not parsed or "questions_by_section" not in parsed:
#             logger.warning(
#                 "generate_smart_questions: missing questions_by_section — using fallback"
#             )
#             return _fallback_questions(sections_with_fields)

#         # Flatten section-driven output → {field_name: question}
#         flat: dict = {}
#         for section_name, items in parsed["questions_by_section"].items():
#             if not isinstance(items, list):
#                 continue
#             for item in items:
#                 fn       = item.get("field_name")
#                 question = item.get("question")
#                 if fn and question and isinstance(question, str):
#                     flat[fn] = question.strip()

#         if not flat:
#             logger.warning("generate_smart_questions: empty after flatten — using fallback")
#             return _fallback_questions(sections_with_fields)

#         # Fill any fields the LLM missed
#         for section in sections_with_fields:
#             for field in section.get("fields", []):
#                 fn = field.field_name
#                 if fn not in flat:
#                     label = field.field_label or fn.replace("_", " ").title()
#                     ftype = field.field_type
#                     if ftype == "date":
#                         flat[fn] = f"What is the {label.lower()}? (DD/MM/YYYY)"
#                     elif ftype == "number":
#                         flat[fn] = f"What is the {label.lower()}? (numeric value)"
#                     elif ftype == "textarea":
#                         flat[fn] = f"Please provide details for: {label}"
#                     else:
#                         flat[fn] = f"What is the {label}?"
#                     logger.debug("generate_smart_questions: filled missing field %r", fn)

#         logger.info("generate_smart_questions: returning %d questions", len(flat))
#         return flat

#     except Exception as exc:
#         logger.error("generate_smart_questions: LLM failed (%s) — using fallback", exc)
#         return _fallback_questions(sections_with_fields)


# # ═══════════════════════════════════════════════════════
# # FORM STRUCTURE BUILDER
# # ═══════════════════════════════════════════════════════

# def get_form_structure(
#     db: Session,
#     template_id: int,
#     company: Optional[dict] = None,
# ) -> GenerateQuestionsResponse:
#     """
#     Builds full form structure for a template.
#     Injects smart questions as field labels.
#     session_id always None — session created server-side on /generate/document.
#     """
#     logger.info("get_form_structure | template_id=%d", template_id)

#     template = crud.get_template_by_id(db, template_id)
#     if not template:
#         raise ValueError(f"Template {template_id} not found")

#     department = crud.get_department_by_id(db, template.department_id)
#     if not department:
#         raise ValueError("Department not found for template")

#     sections_with_fields = crud.get_fields_by_template(db, template.id)
#     if not sections_with_fields:
#         raise ValueError("No sections found for template")

#     try:
#         smart_questions = generate_smart_questions(
#             department_name=department.name,
#             template_name=template.name,
#             sections_with_fields=sections_with_fields,
#             company=company,
#         )
#     except Exception as e:
#         logger.error("get_form_structure: question generation failed: %s", e)
#         smart_questions = {}

#     sections_response = []
#     for section in sections_with_fields:
#         fields = []
#         for f in section.get("fields", []):
#             label = smart_questions.get(f.field_name, "").strip()
#             if not label or len(label) < 5:
#                 label = f.field_label
#             fields.append(
#                 SectionFieldResponse(
#                     id=f.id,
#                     field_name=f.field_name,
#                     field_label=label,
#                     field_type=f.field_type,
#                     is_required=f.is_required,
#                 )
#             )
#         sections_response.append(
#             SectionWithFieldsResponse(
#                 section_id=section["section_id"],
#                 section_name=section["section_name"],
#                 section_order=section["section_order"],
#                 fields=fields,
#             )
#         )

#     logger.info(
#         "get_form_structure | template=%s dept=%s sections=%d",
#         template.name, department.name, len(sections_response),
#     )

#     return GenerateQuestionsResponse(
#         session_id=None,
#         department=department.name,
#         template=template.name,
#         sections=sections_response,
#     )


import json
from typing import Optional

from sqlalchemy.orm import Session

from backend.database import crud
from backend.schemas.schemas import (
    GenerateQuestionsResponse,
    SectionFieldResponse,
    SectionWithFieldsResponse,
)
from backend.services import llm_service
from backend.utils.logger import get_logger

logger = get_logger("docforge.services.question")


# ═══════════════════════════════════════════════════════
# SYSTEM PROMPT
# ═══════════════════════════════════════════════════════

QUESTION_SYSTEM_PROMPT = """\
You are a professional business document consultant.
Your job is to generate clear, professional intake-form questions for a document template.

OBJECTIVE
─────────
For every section provided, generate a question for every field in that section.
Never skip a section. Never skip a required field. dont repeat questions across fields. 


QUESTION QUALITY RULES
──────────────────────
- Questions must be specific to the document type and department — not generic.
- Formal, professional language. No vague or repetitive phrasing.
- Never write "What is [field_name]?" — rephrase as a real business question.
- Date fields: ask what the date represents and request DD/MM/YYYY format.
- Number fields: specify the unit, currency, or scale expected.
- Textarea fields: ask an open-ended question that invites rich, detailed input.
- Required fields: always include without exception.

OUTPUT FORMAT
─────────────
Return ONLY valid JSON. No preamble. No markdown fences. No explanation.

{
  "questions_by_section": {
    "Exact Section Name": [
      { "field_name": "exact_field_name", "question": "Professional question text?" }
    ]
  }
}

Every section name must match exactly. Every field_name must match exactly.
"""

_FEW_SHOT_EXAMPLES = """\
EXAMPLES OF HIGH-QUALITY QUESTIONS:

HR | Offer Letter
  Section "Header"
    candidate_full_name → "What is the candidate's full legal name as it should appear on the offer letter?"
    joining_date        → "What is the proposed date of joining? (DD/MM/YYYY)"

  Section "Compensation and Benefits"
    basic_salary  → "What is the employee's monthly basic salary in INR?"
    total_ctc     → "What is the total annual Cost to Company (CTC) being offered in INR?"
    hra           → "What is the monthly House Rent Allowance (HRA) component in INR?"

Legal | NDA
  Section "Confidentiality Obligations"
    confidentiality_period → "For how many years should confidentiality obligations remain enforceable after the agreement terminates?"
    permitted_disclosures  → "Are there any parties or circumstances under which disclosure of confidential information is permitted?"

IT | Security Audit Report
  Section "Findings and Risk Assessment"
    vulnerability_count → "How many vulnerabilities were identified in total during this audit?"
    critical_issues     → "List all critical-severity issues found, including CVE references where applicable."
    affected_systems    → "Which systems or services were found to be affected by the identified vulnerabilities?"
"""


# ═══════════════════════════════════════════════════════
# PROMPT BUILDER
# ═══════════════════════════════════════════════════════

def _build_prompt(
    department_name: str,
    template_name: str,
    sections_with_fields: list,
    company: Optional[dict] = None,
) -> str:
    company_ctx = (
        f"Company: {company.get('name', 'Not specified')}"
        f" | Industry: {company.get('industry', 'Not specified')}"
        f" | Size: {company.get('size', 'Not specified')}"
        f" | Tone: {company.get('tone', 'Professional')}"
        if company and any(company.values())
        else "Company: Not specified. Use neutral professional tone."
    )

    sections_text = ""
    for section in sections_with_fields:
        sections_text += f'\nSection: "{section["section_name"]}"\n'
        for field in section.get("fields", []):
            req_tag = "REQUIRED" if field.is_required else "optional"
            sections_text += (
                f"  - field_name: {field.field_name}"
                f" | label: {field.field_label}"
                f" | type: {field.field_type}"
                f" | {req_tag}\n"
            )

    total_sections = len(sections_with_fields)
    total_fields   = sum(len(s.get("fields", [])) for s in sections_with_fields)

    return (
        f"{_FEW_SHOT_EXAMPLES}\n"
        f"───────────────────────────────────────\n"
        f"NOW GENERATE QUESTIONS FOR:\n\n"
        f"{company_ctx}\n"
        f"Department: {department_name}\n"
        f"Document Type: {template_name}\n"
        f"Total sections: {total_sections} | Total fields: {total_fields}\n"
        f"\nSECTIONS AND FIELDS:\n"
        f"{sections_text}\n"
        f"───────────────────────────────────────\n"
        f"RULES:\n"
        f"- Include ALL {total_sections} sections in questions_by_section.\n"
        f"- Use exact section names and exact field_names.\n"
        f"- Never skip a REQUIRED field.\n"
        f"- Return ONLY valid JSON. No markdown. No extra text.\n"
    )


# ═══════════════════════════════════════════════════════
# JSON PARSER
# ═══════════════════════════════════════════════════════

def _parse_response(response: str) -> dict:
    if not response:
        raise ValueError("Empty LLM response")
    try:
        parsed = json.loads(response)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON from LLM: {response}") from e
    if "questions_by_section" not in parsed:
        raise ValueError("Missing 'questions_by_section'")
    return parsed


# ═══════════════════════════════════════════════════════
# MAIN GENERATION
# ═══════════════════════════════════════════════════════

def generate_smart_questions(
    department_name: str,
    template_name: str,
    sections_with_fields: list,
    company: Optional[dict] = None,
) -> dict:
    """
    Returns flat {field_name: question} dict for all fields.
    Raises RuntimeError if LLM fails or response is unusable.
    """
    logger.info(
        "generate_smart_questions | dept=%r template=%r sections=%d",
        department_name, template_name, len(sections_with_fields),
    )

    response = llm_service.generate_with_llm_json(
        user_prompt=_build_prompt(department_name, template_name, sections_with_fields, company),
        system_prompt=QUESTION_SYSTEM_PROMPT,
    )

    parsed = _parse_response(response)

    # Flatten section-driven output → {field_name: question}
    flat: dict = {}
    for section_name, items in parsed["questions_by_section"].items():
        if not isinstance(items, list):
            continue
        for item in items:
            fn       = item.get("field_name")
            question = item.get("question")
            if fn and question and isinstance(question, str) and question.strip():
                flat[fn] = question.strip()

    if not flat:
        raise RuntimeError("LLM returned questions_by_section but all items were invalid")

    # Fill any fields the LLM silently missed (not a fallback — uses the LLM label directly)
    missing = []
    for section in sections_with_fields:
        for field in section.get("fields", []):
            if field.field_name not in flat:
                missing.append(field.field_name)
                flat[field.field_name] = field.field_label  # use DB label as-is

    if missing:
        logger.warning(
            "generate_smart_questions: LLM missed %d field(s), using DB labels: %s",
            len(missing), missing,
        )

    logger.info("generate_smart_questions: returning %d questions", len(flat))
    return flat


# ═══════════════════════════════════════════════════════
# FORM STRUCTURE BUILDER
# ═══════════════════════════════════════════════════════

def get_form_structure(
    db: Session,
    template_id: int,
    company: Optional[dict] = None,
) -> GenerateQuestionsResponse:
   
    logger.info("get_form_structure | template_id=%d", template_id)

    template = crud.get_template_by_id(db, template_id)
    if not template:
        raise ValueError(f"Template {template_id} not found")

    department = crud.get_department_by_id(db, template.department_id)
    if not department:
        raise ValueError("Department not found for template")

    sections_with_fields = crud.get_fields_by_template(db, template.id)
    if not sections_with_fields:
        raise ValueError("No sections found for template")


    smart_questions = generate_smart_questions(
        department_name=department.name,
        template_name=template.name,
        sections_with_fields=sections_with_fields,
        company=company,
    )

    sections_response = []
    for section in sections_with_fields:
        fields = []
        for f in section.get("fields", []):
            label = smart_questions.get(f.field_name, "").strip()
            if not label:
                label = f.field_label 
            fields.append(
                SectionFieldResponse(
                    id=f.id,
                    field_name=f.field_name,
                    field_label=label,
                    field_type=f.field_type,
                    is_required=f.is_required,
                )
            )
        sections_response.append(
            SectionWithFieldsResponse(
                section_id=section["section_id"],
                section_name=section["section_name"],
                section_order=section["section_order"],
                fields=fields,
            )
        )

    logger.info(
        "get_form_structure complete | template=%s dept=%s sections=%d",
        template.name, department.name, len(sections_response),
    )

    return GenerateQuestionsResponse(
        session_id=None,
        department=department.name,
        template=template.name,
        sections=sections_response,
    )