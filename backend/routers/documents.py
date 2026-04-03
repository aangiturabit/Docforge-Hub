from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional, List
from backend.database.connection import get_db
from backend.database import crud
from backend.schemas.schemas import (
    GeneratedDocumentResponse,
    DraftResponse
)
import io

router = APIRouter()


# ─────────────────────────────────────────
# GET ALL DOCUMENTS (library)
# ─────────────────────────────────────────

@router.get("", response_model=List[GeneratedDocumentResponse])
def get_all_documents(
    department_id: Optional[int] = None,
    template_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    docs = crud.get_all_documents(db, department_id, template_id)

    return [
        GeneratedDocumentResponse(
            document_id=d.id,
            session_id=d.session_id,
            title=d.title,
            content=d.content,
            validation_status=d.validation_status,
            created_at=d.created_at
        )
        for d in docs
    ]

# ─────────────────────────────────────────
# GET DOCUMENT BY ID
# ─────────────────────────────────────────

@router.get("/documents/{document_id}", response_model=GeneratedDocumentResponse)
def get_document(
    document_id: int,
    db: Session = Depends(get_db)
):
    doc = crud.get_document_by_id(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return GeneratedDocumentResponse(
        document_id=doc.id,
        session_id=doc.session_id,
        title=doc.title,
        content=doc.content,
        validation_status=doc.validation_status,
        created_at=doc.created_at
    )


# ─────────────────────────────────────────
# SAVE DOCUMENT
# ─────────────────────────────────────────

@router.post("/documents/save", response_model=GeneratedDocumentResponse)
def save_document(
    document_id: int,
    db: Session = Depends(get_db)
):
    doc = crud.get_document_by_id(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    published = crud.publish_draft(db, document_id)
    return GeneratedDocumentResponse(
        document_id=published.id,
        session_id=published.session_id,
        title=published.title,
        content=published.content,
        validation_status=published.validation_status,
        created_at=published.created_at
    )


# ─────────────────────────────────────────
# SAVE AS DRAFT
# ─────────────────────────────────────────

@router.post("/documents/draft", response_model=DraftResponse)
def save_draft(
    document_id: int,
    db: Session = Depends(get_db)
):
    doc = crud.get_document_by_id(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    draft = crud.save_document_as_draft(
        db=db,
        session_id=doc.session_id,
        template_id=doc.template_id,
        title=doc.title,
        content=doc.content
    )
    return draft


# ─────────────────────────────────────────
# GET ALL DRAFTS
# ─────────────────────────────────────────

@router.get("/documents/drafts", response_model=List[DraftResponse])
def get_drafts(db: Session = Depends(get_db)):
    return crud.get_all_drafts(db)


# ─────────────────────────────────────────
# GET DRAFT BY ID
# ─────────────────────────────────────────

@router.get("/documents/drafts/{document_id}", response_model=DraftResponse)
def get_draft(
    document_id: int,
    db: Session = Depends(get_db)
):
    draft = crud.get_draft_by_id(db, document_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


# ─────────────────────────────────────────
# DELETE DRAFT
# ─────────────────────────────────────────

@router.delete("/documents/drafts/{document_id}")
def delete_draft(
    document_id: int,
    db: Session = Depends(get_db)
):
    draft = crud.get_draft_by_id(db, document_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    crud.delete_document(db, document_id)
    return {"message": "Draft deleted successfully"}


# ─────────────────────────────────────────
# DELETE DOCUMENT
# ─────────────────────────────────────────

@router.delete("/documents/{document_id}")
def delete_document(
    document_id: int,
    db: Session = Depends(get_db)
):
    doc = crud.get_document_by_id(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    crud.delete_document(db, document_id)
    return {"message": "Document deleted successfully"}


# ─────────────────────────────────────────
# GET ALL VERSIONS
# ─────────────────────────────────────────

@router.get("/documents/versions/{session_id}")
def get_versions(
    session_id: str,
    db: Session = Depends(get_db)
):
    from uuid import UUID
    docs = crud.get_documents_by_session(db, UUID(session_id))
    return [
        {
            "document_id": d.id,
            "version": d.version,
            "title": d.title,
            "validation_status": d.validation_status,
            "is_draft": d.is_draft,
            "created_at": d.created_at
        } for d in docs
    ]


# ─────────────────────────────────────────
# REGENERATE SECTION
# ─────────────────────────────────────────

@router.post("/documents/{document_id}/regenerate-section")
def regenerate_section(
    document_id: int,
    section_name: str,
    feedback: Optional[str] = None,
    db: Session = Depends(get_db)
):
    from backend.services import document_service
    doc = crud.get_document_by_id(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    result = document_service.regenerate_section(
        db=db,
        document_id=document_id,
        section_name=section_name,
        feedback=feedback
    )

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return result