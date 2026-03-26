from sqlalchemy.orm import Session
from backend.database import crud
from backend.schemas.schemas import (
    SectionWithFieldsResponse,
    SectionFieldResponse,
    GenerateQuestionsResponse
)
from backend.services import llm_service


def generate_smart_questions(
    department_name: str,
    template_name: str,
    sections_with_fields: list
) -> dict:
    sections_text = ""
    for section in sections_with_fields:
        sections_text += f"\nSection: {section['section_name']}\n"
        for field in section["fields"]:
            required = "required" if field.is_required else "optional"
            sections_text += f"  - {field.field_label} ({field.field_type}, {required})\n"

    prompt = f"""You are helping collect information to generate a professional {template_name} document for the {department_name} department.

The document has these sections and fields:
{sections_text}

For each field listed above, generate a clear, professional question to ask the user.
Return the questions in this exact JSON format:
{{
  "questions": [
    {{
      "field_name": "exact_field_name",
      "question": "What is the...?"
    }}
  ]
}}

Rules:
- Keep questions clear and professional
- Match field_name exactly as given
- Make questions specific to {template_name}
- Return only valid JSON, no extra text
"""

    import json
    response = llm_service.generate_with_llm(prompt)

    try:
        data = json.loads(response)
        return {q["field_name"]: q["question"] for q in data["questions"]}
    except Exception:
        return {}


def get_form_structure(db: Session, template_id: int) -> GenerateQuestionsResponse:
    template = crud.get_template_by_id(db, template_id)
    if not template:
        raise ValueError(f"Template {template_id} not found")

    department = crud.get_department_by_id(db, template.department_id)
    if not department:
        raise ValueError(f"Department not found")

    session = crud.create_session(
        db=db,
        department_id=template.department_id,
        template_id=template.id
    )

    sections_with_fields = crud.get_fields_by_template(db, template.id)

    # Generate smart questions via LLM
    smart_questions = generate_smart_questions(
        department_name=department.name,
        template_name=template.name,
        sections_with_fields=sections_with_fields
    )

    sections_response = []
    for section in sections_with_fields:
        fields_response = [
            SectionFieldResponse(
                id=f.id,
                field_name=f.field_name,
                # Use LLM question if available, else use field_label
                field_label=smart_questions.get(f.field_name, f.field_label),
                field_type=f.field_type,
                is_required=f.is_required
            )
            for f in section["fields"]
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