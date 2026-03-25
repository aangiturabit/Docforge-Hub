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