
import hashlib
import json
import re
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

# ── In-memory question cache ─────────────────────────────────────────────────
_question_cache: dict = {}


# ═══════════════════════════════════════════════════════
# SYSTEM PROMPT — role-aware, dynamic count
# ═══════════════════════════════════════════════════════

QUESTION_SYSTEM_PROMPT = """\
You are a professional business document consultant generating intake-form questions \
for {template_name} documents in the {department_name} department.

CORE OBJECTIVE
Let section role and field count decide how many questions are needed.
Do not force a fixed count per section.

SECTION-ROLE COUNT GUIDANCE
────────────────────────────────────────────────────────────────────
HEADER   (letterhead, title, reference)      → 2-4 questions total
OPENER   (introduction, purpose, background) → 3-5 questions
STRUCTURAL (definitions, classification)     → 2-4 questions
OBLIGATION (responsibilities, compliance)    → 4-7 questions
EVIDENCE   (findings, risk, metrics)         → 4-8 questions
BODY       (compensation, terms, conditions) → 4-8 questions
CLOSURE    (recommendations, next steps)     → 3-5 questions
SIGN_OFF   (approval, signature)             → 1-3 questions max

FIELD-LEVEL RULES
────────────────────────────────────────────────────────────────────
• Exactly 1 question per field.
• Skip a field ONLY if it is BOTH optional AND completely self-explanatory.
• Never write "What is [field_name]?" — rephrase as a business question.
• Date fields    → ask what this date represents + request format (DD/MM/YYYY).
• Number fields  → specify unit, currency, or scale in the question.
• Textarea fields → open-ended question inviting rich detail.
• Required fields → always include, even if obvious.

QUALITY RULES
────────────────────────────────────────────────────────────────────
• Questions specific to department and document type.
• Formal, professional language. No vague phrasing.
• No duplicates. No invented field names. Use exact field_name from input.
• Company context adjusts tone only.

OUTPUT FORMAT — return ONLY valid JSON, no preamble, no markdown fences:
{
  "questions": [
    { "field_name": "exact_field_name", "question": "Professional question?" }
  ]
}
"""

_FEW_SHOT_EXAMPLES = """\
Examples of high-quality questions:

HR | Offer Letter | HEADER
  candidate_full_name → "What is the candidate's full legal name as it should appear on the offer letter?"

HR | Offer Letter | BODY (Compensation)
  basic_salary   → "What is the employee's monthly basic salary in INR?"
  total_ctc      → "What is the total annual CTC offered to the employee (INR)?"

Legal | NDA | OBLIGATION
  confidentiality_period → "For how many years should confidentiality obligations remain in effect after termination?"

IT | Security Audit | EVIDENCE
  vulnerability_count → "How many vulnerabilities were identified in total?"
  critical_issues     → "List the critical-severity issues found, including CVE references if applicable."
"""


# ═══════════════════════════════════════════════════════
# CACHE KEY
# ═══════════════════════════════════════════════════════

def _make_cache_key(
    department_name: str,
    template_name: str,
    sections_with_fields: list,
    company: Optional[dict] = None,
) -> str:
    field_info = [
        {"field_name": f.field_name, "field_type": f.field_type, "is_required": f.is_required}
        for section in sections_with_fields
        for f in section.get("fields", [])
    ]
    company_part = json.dumps(company, sort_keys=True) if company else ""
    raw = f"{department_name}:{template_name}:{json.dumps(field_info, sort_keys=True)}:{company_part}"
    return hashlib.md5(raw.encode()).hexdigest()


# ═══════════════════════════════════════════════════════
# FALLBACK 1 — safe JSON extraction
# ═══════════════════════════════════════════════════════

def _safe_parse_questions(response: str) -> Optional[dict]:
   
    if not response:
        return None

    # Strategy 1 — direct parse
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        pass

    # Strategy 2 — strip markdown fences
    cleaned = re.sub(r"```(?:json)?", "", response).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Strategy 3 — extract first {...} block
    match = re.search(r"\{.*\}", response, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Strategy 4 — repair truncated JSON
    for suffix in ("]}", "]}\n"):
        try:
            return json.loads(response.rstrip() + suffix)
        except json.JSONDecodeError:
            pass

    logger.warning("_safe_parse_questions: all 4 parse strategies failed")
    return None


# ═══════════════════════════════════════════════════════
# FALLBACK 2 — default question builder 
# ═══════════════════════════════════════════════════════

def _default_question_generator(sections_with_fields: list) -> dict:
  
    result = {}
    for section in sections_with_fields:
        for field in section.get("fields", []):
            fn    = field.field_name
            label = field.field_label or fn.replace("_", " ").title()
            ftype = field.field_type

            if ftype == "date":
                result[fn] = f"What is the {label.lower()}? (DD/MM/YYYY)"
            elif ftype == "number":
                result[fn] = f"What is the {label.lower()}? (provide the numeric value)"
            elif ftype == "textarea":
                result[fn] = f"Please provide detailed information for: {label}"
            else:
                result[fn] = f"What is the {label}?"

    logger.info("_default_question_generator: built %d questions", len(result))
    return result


# ═══════════════════════════════════════════════════════
# FALLBACK 3 — ensure complete coverage
# ═══════════════════════════════════════════════════════

def _ensure_all_fields_covered(
    questions: dict,
    sections_with_fields: list,
) -> dict:
   
    missing = 0
    for section in sections_with_fields:
        for field in section.get("fields", []):
            fn = field.field_name
            if fn in questions:
                continue

            label = field.field_label or fn.replace("_", " ").title()
            ftype = field.field_type

            if ftype == "date":
                questions[fn] = f"What is the {label.lower()}? (DD/MM/YYYY)"
            elif ftype == "number":
                questions[fn] = f"What is the {label.lower()}? (numeric value)"
            elif ftype == "textarea":
                questions[fn] = f"Please describe: {label}"
            else:
                questions[fn] = f"{label}?"

            missing += 1

    if missing:
        logger.info("_ensure_all_fields_covered: filled %d missed fields", missing)

    return questions


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
        f"\nCompany: {company.get('name', 'Not specified')}"
        f" | Industry: {company.get('industry', 'Not specified')}"
        f" | Size: {company.get('size', 'Not specified')}"
        f" | Tone: {company.get('tone', 'Professional')}\n"
        if company else
        "\nCompany: Not specified. Use neutral professional tone.\n"
    )

    sections_text = ""
    for section in sections_with_fields:
        sections_text += f"\nSection: {section['section_name']}\n"
        for field in section.get("fields", []):
            req_tag = "Required" if field.is_required else "Optional"
            sections_text += (
                f"  • {field.field_name} | label: {field.field_label} "
                f"| type: {field.field_type} | {req_tag}\n"
            )

    return (
        f"{_FEW_SHOT_EXAMPLES}\n"
        f"{company_ctx}\n"
        f"Department: {department_name}\n"
        f"Document Type: {template_name}\n\n"
        f"Generate professional questions for each field below.\n"
        f"Count must match the section role and field complexity.\n"
        f"{sections_text}\n"
        "Rules: exact field_names only, no duplicates, no invented fields.\n"
        "Return ONLY valid JSON."
    )


# ═══════════════════════════════════════════════════════
# MAIN GENERATION FUNCTION
# ═══════════════════════════════════════════════════════

def generate_smart_questions(
    department_name: str,
    template_name: str,
    sections_with_fields: list,
    company: Optional[dict] = None,
) -> dict:
   
    cache_key = _make_cache_key(department_name, template_name, sections_with_fields, company)

    if cache_key in _question_cache:
        logger.debug("generate_smart_questions: cache hit | key=%s", cache_key[:8])
        return _question_cache[cache_key]

    logger.info("generate_smart_questions | dept=%r template=%r", department_name, template_name)

    system      = QUESTION_SYSTEM_PROMPT.format(template_name=template_name, department_name=department_name)
    user_prompt = _build_prompt(department_name, template_name, sections_with_fields, company)

    result: dict = {}

    try:
        response = llm_service.generate_with_llm_json(
            user_prompt=user_prompt,
            system_prompt=system,
        )
        parsed = _safe_parse_questions(response)

        if parsed and "questions" in parsed:
            for q in parsed["questions"]:
                fn       = q.get("field_name")
                question = q.get("question")
                if fn and question:
                    result[fn] = question.strip()
            logger.info(
                "generate_smart_questions: LLM returned %d questions", len(result)
            )
        else:
            logger.warning("generate_smart_questions: unparseable LLM response — using default generator")
            result = _default_question_generator(sections_with_fields)

    except Exception as exc:
        logger.error("generate_smart_questions: LLM failed (%s) — using default generator", exc)
        result = _default_question_generator(sections_with_fields)

    
    result = _ensure_all_fields_covered(result, sections_with_fields)
    _question_cache[cache_key] = result
    return result



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

   
    try:
        smart_questions = generate_smart_questions(
            department_name=department.name,
            template_name=template.name,
            sections_with_fields=sections_with_fields,
            company=company,
        )
    except Exception as e:
        logger.error("Smart question generation failed: %s", e)
        smart_questions = {}

    sections_response = []

    for section in sections_with_fields:
        fields = []
        for f in section.get("fields", []):
            label = smart_questions.get(f.field_name)

            if not label or len(label.strip()) < 5:
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
        "form_structure | template=%s dept=%s sections=%d",
        template.name,
        department.name,
        len(sections_response),
    )

    return GenerateQuestionsResponse(
        session_id=None,  
        department=department.name,
        template=template.name,
        sections=sections_response,
    )



# from sqlalchemy.orm import Session
# from typing import Optional, Dict
# from backend.database import crud
# from backend.schemas.schemas import (
#     SectionWithFieldsResponse,
#     SectionFieldResponse,
#     GenerateQuestionsResponse
# )
# from backend.services import llm_service
# import json
# import hashlib


# # ─────────────────────────────────────────
# # IN-MEMORY CACHE (Redis-ready)
# # ─────────────────────────────────────────
# _question_cache: dict = {}


# def _make_cache_key(
#     department_name: str,
#     template_name: str,
#     sections_with_fields: list,
#     company: Optional[Dict] = None   
# ) -> str:
#     """
#     Create a stable cache key including company context
#     """
#     field_info = []

#     for section in sections_with_fields:
#         for field in section.get("fields", []):
#             field_info.append({
#                 "field_name": field.field_name,
#                 "field_type": field.field_type,
#                 "is_required": field.is_required
#             })

#     company_part = json.dumps(company, sort_keys=True) if company else ""

#     raw = f"{department_name}:{template_name}:{json.dumps(field_info, sort_keys=True)}:{company_part}"
#     return hashlib.md5(raw.encode()).hexdigest()


# # ─────────────────────────────────────────
# # SYSTEM PROMPT
# # ─────────────────────────────────────────
# QUESTION_SYSTEM_PROMPT = """
# You are a professional SaaS business document consultant and expert question generator for {{template_name}} in the {{department_name}} department. Each section has fields with specific types (text, textarea, date, number). 
# You specialize in creating clear, intelligent, and user-friendly forms for generating high-quality business documents.

# Your task: For each field provided, generate questions according to the section relevance and field type. Focus on clarity, relevance, and professionalism. Use the company context to adjust tone and clarity, but do not change the meaning of the fields.
# the questions should be very rigid for each section giving 5 questions for each section. it should detch the section & documet context and generate question accordingly.

# STRICT RULES:
# - Generate questions according to the section relevance and field type.plus dont genrate question for each like 5-6 for each section. 
# - Use the exact field_name provided — never modify or invent field names.
# - Questions must be specific to the Department and Document Type.
# - Use formal, professional business tone.
# - Avoid vague or generic questions (e.g., "Enter details", "Provide information").
# - Do not create duplicate or highly similar questions.
# - Never hallucinate or add any extra fields.
# - Use company context ONLY to adjust tone and clarity, NOT field meaning.

# OUTPUT FORMAT:
# Return ONLY a valid JSON object:
# {
#   "questions": [
#     {
#       "field_name": "exact_field_name_from_input",
#       "question": "Well-phrased professional question here?"
#     }
#   ]
# }
# """


# # ─────────────────────────────────────────
# # FEW-SHOT EXAMPLES
# # ─────────────────────────────────────────
# FEW_SHOT_EXAMPLES = """
# High-quality examples:

# Department: HR | Document: Offer Letter
# field_name: candidate_full_name → "What is the candidate's full legal name as it should appear on the offer letter?"


# Department: Legal | Document: NDA
# field_name: confidentiality_period → "For how many years should the confidentiality obligations continue after termination?"
# """


# # ─────────────────────────────────────────
# # PROMPT BUILDER 
# # ─────────────────────────────────────────
# def build_prompt(
#     department_name: str,
#     template_name: str,
#     sections_with_fields: list,
#     company: Optional[Dict] = None   
# ) -> str:

#     # Build company context
#     if company:
#         company_context_text = f"""
# Company Context:
# - Company Name: {company.get("name", "Not specified")}
# - Industry: {company.get("industry", "Not specified")}
# - Company Size: {company.get("size", "Not specified")}
# - Location: {company.get("location", "Not specified")}
# - Tone: {company.get("tone", "Professional")}
# """
#     else:
#         company_context_text = """
# Company Context:
# - Not specified. Use a neutral professional tone.
# """

#     # Build fields list
#     sections_text = ""
#     for section in sections_with_fields:
#         sections_text += f"\nSection: {section['section_name']}\n"
#         for field in section.get("fields", []):
#             required = "Required" if field.is_required else "Optional"
#             sections_text += (
#                 f"  • {field.field_name} | Label: {field.field_label} | "
#                 f"Type: {field.field_type} | {required}\n"
#             )

#     return f"""
# {FEW_SHOT_EXAMPLES}

# {company_context_text}

# Department: {department_name}
# Document Type: {template_name}

# Generate professional question for each field listed below:

# {sections_text}

# IMPORTANT:
# - Each field_name must appear exactly once
# - Do not create duplicate questions
# - Do not invent new fields
# - Use company context only for tone

# Return ONLY valid JSON as specified.
# """


# # ─────────────────────────────────────────
# # QUESTION GENERATION FUNCTION
# # ─────────────────────────────────────────
# def generate_smart_questions(
#     department_name: str,
#     template_name: str,
#     sections_with_fields: list,
#     company: Optional[Dict] = None   
# ) -> dict:

#     cache_key = _make_cache_key(
#         department_name,
#         template_name,
#         sections_with_fields,
#         company   
#     )

#     # Cache hit
#     if cache_key in _question_cache:
#         return _question_cache[cache_key]

#     user_prompt = build_prompt(
#         department_name,
#         template_name,
#         sections_with_fields,
#         company=company   
#     )

#     response = llm_service.generate_with_llm_json(
#         user_prompt=user_prompt,
#         system_prompt=QUESTION_SYSTEM_PROMPT
#     )

#     try:
#         data = json.loads(response)
#         result = {}

#         for q in data.get("questions", []):
#             field_name = q.get("field_name")
#             question = q.get("question")

#             if field_name and question:
#                 result[field_name] = question.strip()

#         _question_cache[cache_key] = result
#         return result

#     except Exception as e:
#         print(f"Error generating smart questions: {e}")
#         return {}


# # ─────────────────────────────────────────
# # MAIN FUNCTION
# # ─────────────────────────────────────────
# def get_form_structure(
#     db: Session,
#     template_id: int,
#     company: Optional[Dict] = None  
# ) -> GenerateQuestionsResponse:

#     template = crud.get_template_by_id(db, template_id)
#     if not template:
#         raise ValueError(f"Template {template_id} not found")

#     department = crud.get_department_by_id(db, template.department_id)
#     if not department:
#         raise ValueError("Department not found")

#     # Create session
#     session = crud.create_session(
#         db=db,
#         department_id=template.department_id,
#         template_id=template.id
#     )

#     sections_with_fields = crud.get_fields_by_template(db, template.id)

#     # Generate questions
#     smart_questions = generate_smart_questions(
#         department_name=department.name,
#         template_name=template.name,
#         sections_with_fields=sections_with_fields,
#         company=company   
#     )

#     # Build response
#     sections_response = []

#     for section in sections_with_fields:
#         fields_response = [
#             SectionFieldResponse(
#                 id=f.id,
#                 field_name=f.field_name,
#                 field_label=smart_questions.get(f.field_name, f.field_label),
#                 field_type=f.field_type,
#                 is_required=f.is_required
#             )
#             for f in section.get("fields", [])
#         ]

#         sections_response.append(
#             SectionWithFieldsResponse(
#                 section_id=section["section_id"],
#                 section_name=section["section_name"],
#                 section_order=section["section_order"],
#                 fields=fields_response
#             )
#         )

#     return GenerateQuestionsResponse(
#         session_id=session.id,
#         department=department.name,
#         template=template.name,
#         sections=sections_response
#     )