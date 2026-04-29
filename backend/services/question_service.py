


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