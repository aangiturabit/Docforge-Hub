from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session
from typing import Optional, List
from uuid import UUID
from backend.database.connection import get_db
from backend.database import crud
from backend.schemas.schemas import GeneratedDocumentResponse, DraftResponse
import json

router = APIRouter()


def _to_json_str(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        if not value.strip():
            return None
        try:
            json.loads(value)
            return value
        except Exception:
            return None
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value)
        except Exception:
            return None
    return None


def _serialize_doc(d) -> GeneratedDocumentResponse:
    return GeneratedDocumentResponse(
        document_id=d.id,
        session_id=d.session_id,
        title=d.title or "",
        content=d.content or "",
        structured_json=_to_json_str(d.structured_json),
        version=d.version or "1.0",
        validation_status=d.validation_status or "pending",
        validation_notes=getattr(d, "validation_notes", None),
        is_draft=d.is_draft if d.is_draft is not None else False,
        created_at=d.created_at
    )


def _get_sections_from_doc(doc) -> list:
    raw = doc.structured_json
    if not raw:
        return []
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return parsed.get("sections", [])
    except Exception:
        pass
    return []


# ─────────────────────────────────────────
# 1. COLLECTION + NAMED ROUTES 
# ─────────────────────────────────────────

@router.get("", response_model=List[GeneratedDocumentResponse])
def get_all_documents(
    department_id: Optional[int] = None,
    template_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    docs = crud.get_all_documents(db, department_id, template_id)
    return [_serialize_doc(d) for d in docs]


@router.get("/drafts", response_model=List[DraftResponse])
def get_drafts(db: Session = Depends(get_db)):
    return crud.get_all_drafts(db)


@router.get("/drafts/{document_id}", response_model=DraftResponse)
def get_draft(document_id: int, db: Session = Depends(get_db)):
    draft = crud.get_draft_by_id(db, document_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


@router.delete("/drafts/{document_id}")
def delete_draft(document_id: int, db: Session = Depends(get_db)):
    if not crud.get_draft_by_id(db, document_id):
        raise HTTPException(status_code=404, detail="Draft not found")
    crud.delete_document(db, document_id)
    return {"message": "Draft deleted successfully"}


@router.get("/versions/{session_id}")
def get_versions(session_id: str, db: Session = Depends(get_db)):
    docs = crud.get_documents_by_session(db, UUID(session_id))
    return [
        {
            "document_id": d.id,
            "version": d.version,
            "title": d.title,
            "validation_status": d.validation_status,
            "is_draft": d.is_draft,
            "created_at": d.created_at
        }
        for d in docs
    ]


@router.post("/save", response_model=GeneratedDocumentResponse)
def save_document(document_id: int, db: Session = Depends(get_db)):
    doc = crud.get_document_by_id(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return _serialize_doc(crud.publish_draft(db, document_id))


@router.post("/draft", response_model=DraftResponse)
def save_draft(document_id: int, db: Session = Depends(get_db)):
    doc = crud.get_document_by_id(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return crud.save_document_as_draft(
        db=db, session_id=doc.session_id,
        template_id=doc.template_id,
        title=doc.title, content=doc.content
    )


# ─────────────────────────────────────────
# 2. SUB-RESOURCE ROUTES /{id}/pdf and /{id}/docx
#  
# ─────────────────────────────────────────

@router.get("/{document_id}/pdf")
def download_pdf(
    document_id: int,
    company_json: Optional[str] = None,
    db: Session = Depends(get_db)
):
    doc = crud.get_document_by_id(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    company = None
    if company_json:
        try:
            company = json.loads(company_json)
        except Exception:
            company = None

    sections = _get_sections_from_doc(doc)
    if not sections:
        raise HTTPException(status_code=404, detail="No structured content found for this document")

    try:
        from backend.renderers.pdf_renderer import render_pdf
        pdf_bytes = render_pdf(sections, doc.title or "", company, "")
        if not pdf_bytes:
            raise HTTPException(status_code=500, detail="PDF generation returned empty")
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{doc.title or "document"}.pdf"'
            }
        )
    except ImportError:
        raise HTTPException(status_code=501, detail="PDF renderer not installed")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF error: {str(e)}")


@router.get("/{document_id}/docx")
def download_docx(
    document_id: int,
    company_json: Optional[str] = None,
    db: Session = Depends(get_db)
):
    doc = crud.get_document_by_id(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    company = None
    if company_json:
        try:
            company = json.loads(company_json)
        except Exception:
            company = None

    sections = _get_sections_from_doc(doc)
    if not sections:
        raise HTTPException(status_code=404, detail="No structured content found for this document")

    try:
        from backend.renderers.docx_renderer import render_docx
        docx_bytes = render_docx(sections, doc.title or "", company, "")
        if not docx_bytes:
            raise HTTPException(status_code=500, detail="DOCX generation returned empty")
        return Response(
            content=docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f'attachment; filename="{doc.title or "document"}.docx"'
            }
        )
    except ImportError:
        raise HTTPException(status_code=501, detail="DOCX renderer not installed")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DOCX error: {str(e)}")


@router.post("/{document_id}/regenerate-section")
def regenerate_section(
    document_id: int,
    section_name: str,
    feedback: Optional[str] = None,
    db: Session = Depends(get_db)
):
    from backend.services import document_service
    if not crud.get_document_by_id(db, document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    result = document_service.regenerate_section(
        db=db, document_id=document_id,
        section_name=section_name, feedback=feedback
    )
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ─────────────────────────────────────────
# 3. WILDCARD /{document_id} ROUTES LAST

# ─────────────────────────────────────────

@router.get("/{document_id}", response_model=GeneratedDocumentResponse)
def get_document(document_id: int, db: Session = Depends(get_db)):
    doc = crud.get_document_by_id(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return _serialize_doc(doc)


@router.delete("/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db)):
    doc = crud.get_document_by_id(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    crud.delete_document(db, document_id)
    return {"message": "Document deleted successfully"}

# from fastapi import APIRouter, Depends, HTTPException
# from fastapi.responses import Response
# from sqlalchemy.orm import Session
# from typing import Optional, List
# from uuid import UUID
# from backend.database.connection import get_db
# from backend.database import crud
# from backend.schemas.schemas import GeneratedDocumentResponse, DraftResponse
# import json

# router = APIRouter()


# def _to_json_str(value) -> Optional[str]:
#     if value is None:
#         return None
#     if isinstance(value, str):
#         if not value.strip():
#             return None
#         try:
#             json.loads(value)
#             return value
#         except Exception:
#             return None
#     if isinstance(value, (dict, list)):
#         try:
#             return json.dumps(value)
#         except Exception:
#             return None
#     return None


# def _serialize_doc(d) -> GeneratedDocumentResponse:
#     return GeneratedDocumentResponse(
#         document_id=d.id,
#         session_id=d.session_id,
#         title=d.title or "",
#         content=d.content or "",
#         structured_json=_to_json_str(d.structured_json),
#         version=d.version or "1.0",
#         validation_status=d.validation_status or "pending",
#         validation_notes=getattr(d, "validation_notes", None),
#         is_draft=d.is_draft if d.is_draft is not None else False,
#         created_at=d.created_at
#     )


# def _get_sections_from_doc(doc) -> list:
#     """Extract sections list from a document ORM object."""
#     raw = doc.structured_json
#     if not raw:
#         return []
#     try:
#         parsed = json.loads(raw) if isinstance(raw, str) else raw
#         if isinstance(parsed, list):
#             return parsed
#         if isinstance(parsed, dict):
#             return parsed.get("sections", [])
#     except Exception:
#         pass
#     return []


# # ─────────────────────────────────────────
# # SPECIFIC PATHS FIRST — before /{document_id}
# # ─────────────────────────────────────────

# @router.get("", response_model=List[GeneratedDocumentResponse])
# def get_all_documents(
#     department_id: Optional[int] = None,
#     template_id: Optional[int] = None,
#     db: Session = Depends(get_db)
# ):
#     docs = crud.get_all_documents(db, department_id, template_id)
#     return [_serialize_doc(d) for d in docs]


# @router.get("/drafts", response_model=List[DraftResponse])
# def get_drafts(db: Session = Depends(get_db)):
#     return crud.get_all_drafts(db)


# @router.get("/drafts/{document_id}", response_model=DraftResponse)
# def get_draft(document_id: int, db: Session = Depends(get_db)):
#     draft = crud.get_draft_by_id(db, document_id)
#     if not draft:
#         raise HTTPException(status_code=404, detail="Draft not found")
#     return draft


# @router.delete("/drafts/{document_id}")
# def delete_draft(document_id: int, db: Session = Depends(get_db)):
#     if not crud.get_draft_by_id(db, document_id):
#         raise HTTPException(status_code=404, detail="Draft not found")
#     crud.delete_document(db, document_id)
#     return {"message": "Draft deleted successfully"}


# @router.get("/versions/{session_id}")
# def get_versions(session_id: str, db: Session = Depends(get_db)):
#     docs = crud.get_documents_by_session(db, UUID(session_id))
#     return [
#         {
#             "document_id": d.id,
#             "version": d.version,
#             "title": d.title,
#             "validation_status": d.validation_status,
#             "is_draft": d.is_draft,
#             "created_at": d.created_at
#         }
#         for d in docs
#     ]


# @router.post("/save", response_model=GeneratedDocumentResponse)
# def save_document(document_id: int, db: Session = Depends(get_db)):
#     doc = crud.get_document_by_id(db, document_id)
#     if not doc:
#         raise HTTPException(status_code=404, detail="Document not found")
#     return _serialize_doc(crud.publish_draft(db, document_id))


# @router.post("/draft", response_model=DraftResponse)
# def save_draft(document_id: int, db: Session = Depends(get_db)):
#     doc = crud.get_document_by_id(db, document_id)
#     if not doc:
#         raise HTTPException(status_code=404, detail="Document not found")
#     return crud.save_document_as_draft(
#         db=db, session_id=doc.session_id,
#         template_id=doc.template_id,
#         title=doc.title, content=doc.content
#     )


# # ─────────────────────────────────────────
# # WILDCARD ROUTES LAST — /{document_id}
# # ─────────────────────────────────────────

# @router.get("/{document_id}", response_model=GeneratedDocumentResponse)
# def get_document(document_id: int, db: Session = Depends(get_db)):
#     doc = crud.get_document_by_id(db, document_id)
#     if not doc:
#         raise HTTPException(status_code=404, detail="Document not found")
#     return _serialize_doc(doc)


# @router.delete("/{document_id}")
# def delete_document(document_id: int, db: Session = Depends(get_db)):
#     doc = crud.get_document_by_id(db, document_id)
#     if not doc:
#         raise HTTPException(status_code=404, detail="Document not found")
#     crud.delete_document(db, document_id)
#     return {"message": "Document deleted successfully"}


# @router.get("/{document_id}/pdf")
# def download_pdf(
#     document_id: int,
#     company_json: Optional[str] = None,
#     db: Session = Depends(get_db)
# ):
#     doc = crud.get_document_by_id(db, document_id)
#     if not doc:
#         raise HTTPException(status_code=404, detail="Document not found")

#     company = None
#     if company_json:
#         try:
#             company = json.loads(company_json)
#         except Exception:
#             company = None

#     sections = _get_sections_from_doc(doc)
#     if not sections:
#         raise HTTPException(status_code=404, detail="No structured content found")

#     try:
#         from backend.renderers.pdf_renderer import render_pdf
#         pdf_bytes = render_pdf(sections, doc.title or "", company, "")
#         if not pdf_bytes:
#             raise HTTPException(status_code=500, detail="PDF generation failed")
#         return Response(
#             content=pdf_bytes,
#             media_type="application/pdf",
#             headers={"Content-Disposition": f'attachment; filename="{doc.title or "document"}.pdf"'}
#         )
#     except ImportError:
#         raise HTTPException(status_code=501, detail="PDF renderer not available")
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"PDF error: {str(e)}")


# @router.get("/{document_id}/docx")
# def download_docx(
#     document_id: int,
#     company_json: Optional[str] = None,
#     db: Session = Depends(get_db)
# ):
#     doc = crud.get_document_by_id(db, document_id)
#     if not doc:
#         raise HTTPException(status_code=404, detail="Document not found")

#     company = None
#     if company_json:
#         try:
#             company = json.loads(company_json)
#         except Exception:
#             company = None

#     sections = _get_sections_from_doc(doc)
#     if not sections:
#         raise HTTPException(status_code=404, detail="No structured content found")

#     try:
#         from backend.renderers.docx_renderer import render_docx
#         docx_bytes = render_docx(sections, doc.title or "", company, "")
#         if not docx_bytes:
#             raise HTTPException(status_code=500, detail="DOCX generation failed")
#         return Response(
#             content=docx_bytes,
#             media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
#             headers={"Content-Disposition": f'attachment; filename="{doc.title or "document"}.docx"'}
#         )
#     except ImportError:
#         raise HTTPException(status_code=501, detail="DOCX renderer not available")
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"DOCX error: {str(e)}")


# @router.post("/{document_id}/regenerate-section")
# def regenerate_section(
#     document_id: int,
#     section_name: str,
#     feedback: Optional[str] = None,
#     db: Session = Depends(get_db)
# ):
#     from backend.services import document_service
#     if not crud.get_document_by_id(db, document_id):
#         raise HTTPException(status_code=404, detail="Document not found")
#     result = document_service.regenerate_section(
#         db=db, document_id=document_id,
#         section_name=section_name, feedback=feedback
#     )
#     if "error" in result:
#         raise HTTPException(status_code=404, detail=result["error"])
#     return result



