from sqlalchemy.orm import Session
from backend.database import crud
from backend.schemas.schemas import (
    SectionWithFieldsResponse,
    SectionFieldResponse,
    GenerateQuestionsResponse
)


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

    sections_response = []
    for section in sections_with_fields:
        fields_response = [
            SectionFieldResponse(
                id=f.id,
                field_name=f.field_name,
                field_label=f.field_label,
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