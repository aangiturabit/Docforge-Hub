
from sqlalchemy.orm import Session
from typing import Optional, Dict
from backend.database import crud
from backend.schemas.schemas import (
    SectionWithFieldsResponse,
    SectionFieldResponse,
    GenerateQuestionsResponse
)
from backend.services import llm_service
import json
import hashlib


# ─────────────────────────────────────────
# IN-MEMORY CACHE (Redis-ready)
# ─────────────────────────────────────────
_question_cache: dict = {}


def _make_cache_key(
    department_name: str,
    template_name: str,
    sections_with_fields: list,
    company: Optional[Dict] = None   
) -> str:
    """
    Create a stable cache key including company context
    """
    field_info = []

    for section in sections_with_fields:
        for field in section.get("fields", []):
            field_info.append({
                "field_name": field.field_name,
                "field_type": field.field_type,
                "is_required": field.is_required
            })

    company_part = json.dumps(company, sort_keys=True) if company else ""

    raw = f"{department_name}:{template_name}:{json.dumps(field_info, sort_keys=True)}:{company_part}"
    return hashlib.md5(raw.encode()).hexdigest()


# ─────────────────────────────────────────
# SYSTEM PROMPT (UNCHANGED — ALREADY STRONG)
# ─────────────────────────────────────────
QUESTION_SYSTEM_PROMPT = """
You are a professional SaaS business document consultant and expert question generator for {{template_name}} in the {{department_name}} department. Each section has fields with specific types (text, textarea, date, number). 
You specialize in creating clear, intelligent, and user-friendly forms for generating high-quality business documents.

Your task: For each field provided, generate exactly one clear, professional, and context-specific question.

STRICT RULES:
- Generate exactly ONE question per field_name.
- Use the exact field_name provided — never modify or invent field names.
- Questions must be specific to the Department and Document Type.
- Use formal, professional business tone.
- Avoid vague or generic questions (e.g., "Enter details", "Provide information").
- Do not create duplicate or highly similar questions.
- Never hallucinate or add any extra fields.
- Use company context ONLY to adjust tone and clarity, NOT field meaning.

OUTPUT FORMAT:
Return ONLY a valid JSON object:
{
  "questions": [
    {
      "field_name": "exact_field_name_from_input",
      "question": "Well-phrased professional question here?"
    }
  ]
}
"""


# ─────────────────────────────────────────
# FEW-SHOT EXAMPLES
# ─────────────────────────────────────────
FEW_SHOT_EXAMPLES = """
High-quality examples:

Department: HR | Document: Offer Letter
field_name: candidate_full_name → "What is the candidate's full legal name as it should appear on the offer letter?"


Department: Legal | Document: NDA
field_name: confidentiality_period → "For how many years should the confidentiality obligations continue after termination?"
"""


# ─────────────────────────────────────────
# PROMPT BUILDER (UPDATED WITH COMPANY)
# ─────────────────────────────────────────
def build_prompt(
    department_name: str,
    template_name: str,
    sections_with_fields: list,
    company: Optional[Dict] = None   
) -> str:

    # ✅ Dynamic company context
    if company:
        company_context_text = f"""
Company Context:
- Company Name: {company.get("name", "Not specified")}
- Industry: {company.get("industry", "Not specified")}
- Company Size: {company.get("size", "Not specified")}
- Location: {company.get("location", "Not specified")}
- Tone: {company.get("tone", "Professional")}
"""
    else:
        company_context_text = """
Company Context:
- Not specified. Use a neutral professional tone.
"""

    # Build fields list
    sections_text = ""
    for section in sections_with_fields:
        sections_text += f"\nSection: {section['section_name']}\n"
        for field in section.get("fields", []):
            required = "Required" if field.is_required else "Optional"
            sections_text += (
                f"  • {field.field_name} | Label: {field.field_label} | "
                f"Type: {field.field_type} | {required}\n"
            )

    return f"""
{FEW_SHOT_EXAMPLES}

{company_context_text}

Department: {department_name}
Document Type: {template_name}

Generate one professional question for each field listed below:

{sections_text}

IMPORTANT:
- Each field_name must appear exactly once
- Do not create duplicate questions
- Do not invent new fields
- Use company context only for tone

Return ONLY valid JSON as specified.
"""


# ─────────────────────────────────────────
# QUESTION GENERATION FUNCTION
# ─────────────────────────────────────────
def generate_smart_questions(
    department_name: str,
    template_name: str,
    sections_with_fields: list,
    company: Optional[Dict] = None   
) -> dict:

    cache_key = _make_cache_key(
        department_name,
        template_name,
        sections_with_fields,
        company   
    )

    # Cache hit
    if cache_key in _question_cache:
        return _question_cache[cache_key]

    user_prompt = build_prompt(
        department_name,
        template_name,
        sections_with_fields,
        company=company   
    )

    response = llm_service.generate_with_llm_json(
        user_prompt=user_prompt,
        system_prompt=QUESTION_SYSTEM_PROMPT
    )

    try:
        data = json.loads(response)
        result = {}

        for q in data.get("questions", []):
            field_name = q.get("field_name")
            question = q.get("question")

            if field_name and question:
                result[field_name] = question.strip()

        _question_cache[cache_key] = result
        return result

    except Exception as e:
        print(f"Error generating smart questions: {e}")
        return {}


# ─────────────────────────────────────────
# MAIN FUNCTION
# ─────────────────────────────────────────
def get_form_structure(
    db: Session,
    template_id: int,
    company: Optional[Dict] = None  
) -> GenerateQuestionsResponse:

    template = crud.get_template_by_id(db, template_id)
    if not template:
        raise ValueError(f"Template {template_id} not found")

    department = crud.get_department_by_id(db, template.department_id)
    if not department:
        raise ValueError("Department not found")

    # Create session
    session = crud.create_session(
        db=db,
        department_id=template.department_id,
        template_id=template.id
    )

    sections_with_fields = crud.get_fields_by_template(db, template.id)

    # Generate questions
    smart_questions = generate_smart_questions(
        department_name=department.name,
        template_name=template.name,
        sections_with_fields=sections_with_fields,
        company=company   
    )

    # Build response
    sections_response = []

    for section in sections_with_fields:
        fields_response = [
            SectionFieldResponse(
                id=f.id,
                field_name=f.field_name,
                field_label=smart_questions.get(f.field_name, f.field_label),
                field_type=f.field_type,
                is_required=f.is_required
            )
            for f in section.get("fields", [])
        ]

        sections_response.append(
            SectionWithFieldsResponse(
                section_id=section["section_id"],
                section_name=section["section_name"],
                section_order=section["section_order"],
                fields=fields_response
            )
        )

    return GenerateQuestionsResponse(
        session_id=session.id,
        department=department.name,
        template=template.name,
        sections=sections_response
    )