


# import json
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
# Never skip a section. Never skip a required field. dont repeat questions across fields. 


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

# def _parse_response(response: str) -> dict:
#     if not response:
#         raise ValueError("Empty LLM response")
#     try:
#         parsed = json.loads(response)
#     except json.JSONDecodeError as e:
#         raise ValueError(f"Invalid JSON from LLM: {response}") from e
#     if "questions_by_section" not in parsed:
#         raise ValueError("Missing 'questions_by_section'")
#     return parsed


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
#     Raises RuntimeError if LLM fails or response is unusable.
#     """
#     logger.info(
#         "generate_smart_questions | dept=%r template=%r sections=%d",
#         department_name, template_name, len(sections_with_fields),
#     )

#     response = llm_service.generate_with_llm_json(
#         user_prompt=_build_prompt(department_name, template_name, sections_with_fields, company),
#         system_prompt=QUESTION_SYSTEM_PROMPT,
#     )

#     parsed = _parse_response(response)

#     # Flatten section-driven output → {field_name: question}
#     flat: dict = {}
#     for section_name, items in parsed["questions_by_section"].items():
#         if not isinstance(items, list):
#             continue
#         for item in items:
#             fn       = item.get("field_name")
#             question = item.get("question")
#             if fn and question and isinstance(question, str) and question.strip():
#                 flat[fn] = question.strip()

#     if not flat:
#         raise RuntimeError("LLM returned questions_by_section but all items were invalid")

#     # Fill any fields the LLM silently missed (not a fallback — uses the LLM label directly)
#     missing = []
#     for section in sections_with_fields:
#         for field in section.get("fields", []):
#             if field.field_name not in flat:
#                 missing.append(field.field_name)
#                 flat[field.field_name] = field.field_label  # use DB label as-is

#     if missing:
#         logger.warning(
#             "generate_smart_questions: LLM missed %d field(s), using DB labels: %s",
#             len(missing), missing,
#         )

#     logger.info("generate_smart_questions: returning %d questions", len(flat))
#     return flat


# # ═══════════════════════════════════════════════════════
# # FORM STRUCTURE BUILDER
# # ═══════════════════════════════════════════════════════

# def get_form_structure(
#     db: Session,
#     template_id: int,
#     company: Optional[dict] = None,
# ) -> GenerateQuestionsResponse:
   
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


#     smart_questions = generate_smart_questions(
#         department_name=department.name,
#         template_name=template.name,
#         sections_with_fields=sections_with_fields,
#         company=company,
#     )

#     sections_response = []
#     for section in sections_with_fields:
#         fields = []
#         for f in section.get("fields", []):
#             label = smart_questions.get(f.field_name, "").strip()
#             if not label:
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
#         "get_form_structure complete | template=%s dept=%s sections=%d",
#         template.name, department.name, len(sections_response),
#     )

#     return GenerateQuestionsResponse(
#         session_id=None,
#         department=department.name,
#         template=template.name,
#         sections=sections_response,
#     )



from typing import Optional

from sqlalchemy.orm import Session

from backend.database import crud
from backend.schemas.schemas import GenerateQuestionsResponse, SectionFieldResponse, SectionWithFieldsResponse
from backend.services import llm_service
from backend.utils.logger import get_logger

logger = get_logger("docforge.services.question")

_SYSTEM_PROMPT = """\
You are a senior business document consultant who designs intake forms for professional documents.

QUESTION QUALITY RULES:
- Questions must be specific to the document type, department, and field purpose — never generic.
- Never write "What is [field_label]?" or "Please provide [field_label]." — always rephrase into a real business question.
- Textarea fields → open-ended questions that invite detailed, specific input.
- Date fields → ask what the date represents + request DD/MM/YYYY format.
- Number/salary fields → specify the currency, unit, or scale expected.
- Required fields → always include, no exceptions.
- One question per field. No repeated or similar questions across fields.

BAD (never do this):
  welcome_message → "What is the welcome message from the CEO or Founder?"
  company_overview → "Please provide an overview of the company, including its history and culture."

GOOD (always do this):
  welcome_message → "What key message should the CEO or Founder communicate to new employees — include the company's founding story, culture, and what success looks like here?"
  company_overview → "Describe how the company was founded, its growth journey, and the cultural values that define how teams work and make decisions today."
  joining_date → "What is the employee's confirmed date of joining? (DD/MM/YYYY)"
  basic_salary → "What is the employee's monthly basic salary component in INR?"

Keep questions short and concise, but specific and professional. Avoid vague language or generic prompts.

Return ONLY valid JSON — no preamble, no markdown fences:
{
  "questions_by_section": {
    "Exact Section Name": [
      { "field_name": "exact_field_name", "question": "Specific, professional question text?" }
    ]
  }
}
"""


def _build_prompt(department_name: str, template_name: str, sections_with_fields: list, company: Optional[dict] = None) -> str:
    company_ctx = (
        f"Company: {company.get('name','N/A')} | Industry: {company.get('industry','N/A')} | Tone: {company.get('tone','Professional')}"
        if company and any(company.values()) else "Company: Not specified."
    )

    sections_text = "\n".join(
        f'Section: "{s["section_name"]}"\n' +
        "\n".join(
            f"  - {f.field_name} | {f.field_label} | {f.field_type} | {'REQUIRED' if f.is_required else 'optional'}"
            for f in s.get("fields", [])
        )
        for s in sections_with_fields
    )

    total_sections = len(sections_with_fields)

    return (
        f"{company_ctx}\n"
        f"Department: {department_name} | Document Type: {template_name}\n\n"
        f"SECTIONS AND FIELDS:\n{sections_text}\n\n"
        f"Generate specific, professional questions for ALL {total_sections} sections.\n"
        f"Use exact section names and field_names. Return ONLY valid JSON."
    )


def generate_smart_questions(department_name: str, template_name: str, sections_with_fields: list, company: Optional[dict] = None) -> dict:
    logger.info("generate_smart_questions | dept=%r template=%r sections=%d", department_name, template_name, len(sections_with_fields))

    try:
        parsed = llm_service.generate_with_llm_json(
            user_prompt=_build_prompt(department_name, template_name, sections_with_fields, company),
            system_prompt=_SYSTEM_PROMPT,
        )
    except Exception as e:
        logger.exception("LLM generation failed")
        raise RuntimeError("Failed to generate questions") from e

    if not isinstance(parsed, dict) or "questions_by_section" not in parsed:
        raise ValueError("Invalid LLM response structure")

    flat = {
        item["field_name"]: item["question"].strip()
        for items in parsed["questions_by_section"].values()
        if isinstance(items, list)
        for item in items
        if item.get("field_name") and item.get("question")
    }

    if not flat:
        raise RuntimeError("LLM returned no valid questions")

    missing = []
    for s in sections_with_fields:
        for f in s.get("fields", []):
            if f.field_name not in flat:
                missing.append(f.field_name)
                flat[f.field_name] = f.field_label

    if missing:
        logger.warning("LLM missed %d field(s): %s", len(missing), missing)

    logger.info("returning %d questions", len(flat))
    return flat


def get_form_structure(db: Session, template_id: int, company: Optional[dict] = None) -> GenerateQuestionsResponse:
    logger.info("get_form_structure | template_id=%d", template_id)

    template             = crud.get_template_by_id(db, template_id)
    department           = crud.get_department_by_id(db, template.department_id)
    sections_with_fields = crud.get_fields_by_template(db, template.id)

    if not template:             raise ValueError(f"Template {template_id} not found")
    if not department:           raise ValueError("Department not found")
    if not sections_with_fields: raise ValueError("No sections found")

    smart_questions = generate_smart_questions(department.name, template.name, sections_with_fields, company)

    sections_response = [
        SectionWithFieldsResponse(
            section_id=s["section_id"],
            section_name=s["section_name"],
            section_order=s["section_order"],
            fields=[
                SectionFieldResponse(
                    id=f.id,
                    field_name=f.field_name,
                    field_label=smart_questions.get(f.field_name, f.field_label).strip(),
                    field_type=f.field_type,
                    is_required=f.is_required,
                )
                for f in s.get("fields", [])
            ],
        )
        for s in sections_with_fields
    ]

    logger.info("complete | template=%s sections=%d", template.name, len(sections_response))
    return GenerateQuestionsResponse(session_id=None, department=department.name, template=template.name, sections=sections_response)