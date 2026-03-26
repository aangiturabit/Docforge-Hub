from sqlalchemy.orm import Session
from uuid import UUID
from backend.database import crud


def save_document(
    db: Session,
    session_id: UUID,
    template_id: int,
    title: str,
    content: str
):
    doc = crud.save_generated_document(
        db=db,
        session_id=session_id,
        template_id=template_id,
        title=title,
        content=content
    )
    return doc


def validate_document(db: Session, document_id: int) -> dict:
    doc = crud.get_document_by_id(db, document_id)
    if not doc:
        return {"error": "Document not found"}

    sections = crud.get_sections_by_template(db, doc.template_id)
    missing_sections = []

    # ✅ ADD THIS
    def normalize(text):
        return text.lower().replace(" or founder", "").strip()

    content = normalize(doc.content)

    # ✅ REPLACE LOOP
    for section in sections:
        section_name = normalize(section.section_name)

        if section_name not in content:
            missing_sections.append(section.section_name)

    is_valid = len(doc.content) >= 500 and len(missing_sections) == 0
    status = "validated" if is_valid else "failed"
    notes = (
        f"Missing sections: {missing_sections}"
        if missing_sections
        else "All sections present"
    )

    crud.update_document_validation(db, document_id, status, notes)

    return {
        "document_id": document_id,
        "is_valid": is_valid,
        "missing_sections": missing_sections,
        "validation_notes": notes
    }


def get_all_versions(db: Session, session_id: UUID):
    return crud.get_documents_by_session(db, session_id)

def preview_document(
    db: Session,
    department_name: str,
    template_name: str,
    template_description: str,
    template_id: int,
    answers: dict
) -> str:
    from backend.services import prompt_service, llm_service
    prompt = prompt_service.build_prompt(
        db=db,
        department_name=department_name,
        template_name=template_name,
        template_description=template_description,
        template_id=template_id,
        answers=answers
    )
    content = llm_service.generate_with_llm(prompt)
    return content


def regenerate_section(
    db: Session,
    document_id: int,
    section_name: str,
    answers: dict = None,
    feedback: str = None
) -> dict:
    doc = crud.get_document_by_id(db, document_id)
    if not doc:
        return {"error": "Document not found"}

    template = crud.get_template_by_id(db, doc.template_id)
    department = crud.get_department_by_id(
        db,
        crud.get_session_by_id(
            db, doc.session_id
        ).department_id
    )

    feedback_text = f"\nFocus only on this section: {section_name}"
    if feedback:
        feedback_text += f"\nAdditional instructions: {feedback}"

    prompt = f"""You are a professional business document writer.

Department: {department.name}
Document Type: {template.name}

Regenerate ONLY this section: {section_name}

User provided information:
{answers if answers else "Use context from the document"}
{feedback_text}

Return only the content for this section.
Start with the section heading.
"""
    from backend.services import llm_service
    new_section_content = llm_service.generate_with_llm(prompt)

    updated_doc = crud.update_document_section(
        db, document_id, section_name, new_section_content
    )

    return {
        "document_id": document_id,
        "section_name": section_name,
        "updated_content": updated_doc.content if updated_doc else ""
    }