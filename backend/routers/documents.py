
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional, List
from uuid import UUID
from backend.database.connection import get_db
from backend.database import crud
from backend.schemas.schemas import GeneratedDocumentResponse, DraftResponse
import json

router = APIRouter()


def _to_json_str(value) -> Optional[str]:
    """
    Convert any structured_json value to str safely.
    DB stores Text — but old JSONB rows may return dict.
    Always returns str or None.
    """
    if value is None:
        return None
    if isinstance(value, str):
        if not value.strip():
            return None
        try:
            json.loads(value)  # validate it's valid JSON
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


# ─────────────────────────────────────────
# documents routes 
# ─────────────────────────────────────────

@router.get("/documents", response_model=List[GeneratedDocumentResponse])
def get_all_documents(
    department_id: Optional[int] = None,
    template_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    docs = crud.get_all_documents(db, department_id, template_id)
    return [_serialize_doc(d) for d in docs]

@router.get("/{document_id:int}", response_model=GeneratedDocumentResponse)
def get_document(document_id: int, db: Session = Depends(get_db)):
    doc = crud.get_document_by_id(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return _serialize_doc(doc)

@router.delete("/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db)):
    if not crud.get_document_by_id(db, document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    crud.delete_document(db, document_id)
    return {"message": "Document deleted successfully"}

@router.get("/drafts", response_model=List[DraftResponse])
def get_drafts(db: Session = Depends(get_db)):
    return crud.get_all_drafts(db)


@router.get("/drafts/{document_id}", response_model=DraftResponse)
def get_draft(document_id: int, db: Session = Depends(get_db)):
    draft = crud.get_draft_by_id(db, document_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


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


@router.delete("/drafts/{document_id}")
def delete_draft(document_id: int, db: Session = Depends(get_db)):
    if not crud.get_draft_by_id(db, document_id):
        raise HTTPException(status_code=404, detail="Draft not found")
    crud.delete_document(db, document_id)
    return {"message": "Draft deleted successfully"}







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





# rough code - to be deleted, kept for reference 

# from fastapi import APIRouter, Depends, HTTPException
# from fastapi.responses import StreamingResponse
# from sqlalchemy.orm import Session
# from typing import Optional, List
# from backend.database.connection import get_db
# from backend.database import crud
# from backend.schemas.schemas import (
#     GeneratedDocumentResponse,
#     DraftResponse
# )
# import io
# import json

# router = APIRouter()

# from typing import Any

# @router.get("", response_model=List[GeneratedDocumentResponse])
# def get_all_documents(
#     department_id: Optional[int] = None,
#     template_id: Optional[int] = None,
#     db: Session = Depends(get_db)
# ):
#     docs = crud.get_all_documents(db, department_id, template_id)
    
#     result = []
#     for d in docs:
#         # structured_json is often stored as a raw string in DB — parse it back
#         structured = d.structured_json
#         if isinstance(structured, str):
#             try:
#                 structured = json.loads(structured)
#             except (json.JSONDecodeError, TypeError):
#                 structured = {}

#         result.append(
#             GeneratedDocumentResponse(
#                 document_id=d.id,
#                 session_id=d.session_id,
#                 title=d.title or "",
#                 content=d.content or "",
#                 structured_json=structured,
#                 version=d.version or "1.0",
#                 validation_status=d.validation_status or "pending",
#                 is_draft=d.is_draft if d.is_draft is not None else False,
#                 created_at=d.created_at,
#             )
#         )
#     return result


# # ─────────────────────────────────────────
# # GET DOCUMENT BY ID
# # ─────────────────────────────────────────
# @router.get("/{document_id}", response_model=GeneratedDocumentResponse)
# def get_document(
#     document_id: int,
#     db: Session = Depends(get_db)
# ):
#     doc = crud.get_document_by_id(db, document_id)
#     if not doc:
#         raise HTTPException(status_code=404, detail="Document not found")
#     return GeneratedDocumentResponse(
#         document_id=doc.id,
#         session_id=doc.session_id,
#         title=doc.title,
#         content=doc.content,
#         structured_json=doc.structured_json,
#         version=doc.version or "1.0",
#         validation_status=doc.validation_status,
#         is_draft=doc.is_draft or False,
#         created_at=doc.created_at
#     )

# # ─────────────────────────────────────────
# # SAVE DOCUMENT
# # ─────────────────────────────────────────
# @router.post("/save", response_model=GeneratedDocumentResponse)
# def save_document(
#     document_id: int,
#     db: Session = Depends(get_db)
# ):
#     doc = crud.get_document_by_id(db, document_id)
#     if not doc:
#         raise HTTPException(status_code=404, detail="Document not found")
#     published = crud.publish_draft(db, document_id)
#     return GeneratedDocumentResponse(
#         document_id=published.id,
#         session_id=published.session_id,
#         title=published.title,
#         content=published.content,
#         structured_json=published.structured_json,
#         version=published.version or "1.0",
#         validation_status=published.validation_status,
#         is_draft=False,
#         created_at=published.created_at
#     )


# # ─────────────────────────────────────────
# # SAVE AS DRAFT
# # ─────────────────────────────────────────
# @router.post("/draft", response_model=DraftResponse)
# def save_draft(
#     document_id: int,
#     db: Session = Depends(get_db)
# ):
#     doc = crud.get_document_by_id(db, document_id)
#     if not doc:
#         raise HTTPException(status_code=404, detail="Document not found")
#     draft = crud.save_document_as_draft(
#         db=db,
#         session_id=doc.session_id,
#         template_id=doc.template_id,
#         title=doc.title,
#         content=doc.content
#     )
#     return draft


# # ─────────────────────────────────────────
# # GET ALL DRAFTS
# # ─────────────────────────────────────────
# @router.get("/drafts", response_model=List[DraftResponse])
# def get_drafts(db: Session = Depends(get_db)):
#     return crud.get_all_drafts(db)


# # ─────────────────────────────────────────
# # GET DRAFT BY ID
# # ─────────────────────────────────────────
# @router.get("/drafts/{document_id}", response_model=DraftResponse)
# def get_draft(
#     document_id: int,
#     db: Session = Depends(get_db)
# ):
#     draft = crud.get_draft_by_id(db, document_id)
#     if not draft:
#         raise HTTPException(status_code=404, detail="Draft not found")
#     return draft


# # ─────────────────────────────────────────
# # DELETE DRAFT
# # ─────────────────────────────────────────
# @router.delete("/drafts/{document_id}")
# def delete_draft(
#     document_id: int,
#     db: Session = Depends(get_db)
# ):
#     draft = crud.get_draft_by_id(db, document_id)
#     if not draft:
#         raise HTTPException(status_code=404, detail="Draft not found")
#     crud.delete_document(db, document_id)
#     return {"message": "Draft deleted successfully"}


# # ─────────────────────────────────────────
# # DELETE DOCUMENT
# # ─────────────────────────────────────────
# @router.delete("/{document_id}")
# def delete_document(
#     document_id: int,
#     db: Session = Depends(get_db)
# ):
#     doc = crud.get_document_by_id(db, document_id)
#     if not doc:
#         raise HTTPException(status_code=404, detail="Document not found")
#     crud.delete_document(db, document_id)
#     return {"message": "Document deleted successfully"}


# # ─────────────────────────────────────────
# # GET ALL VERSIONS
# # ─────────────────────────────────────────
# @router.get("/versions/{session_id}")
# def get_versions(
#     session_id: str,
#     db: Session = Depends(get_db)
# ):
#     from uuid import UUID
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


# # ─────────────────────────────────────────
# # REGENERATE SECTION
# # ─────────────────────────────────────────
# @router.post("/{document_id}/regenerate-section")
# def regenerate_section(
#     document_id: int,
#     section_name: str,
#     feedback: Optional[str] = None,
#     db: Session = Depends(get_db)
# ):
#     from backend.services import document_service
#     doc = crud.get_document_by_id(db, document_id)
#     if not doc:
#         raise HTTPException(status_code=404, detail="Document not found")

#     result = document_service.regenerate_section(
#         db=db,
#         document_id=document_id,
#         section_name=section_name,
#         feedback=feedback
#     )

#     if "error" in result:
#         raise HTTPException(status_code=404, detail=result["error"])

#     return result

# 2 ----------------------------------------------------

# from fastapi import APIRouter, Depends, HTTPException
# from sqlalchemy.orm import Session
# from typing import Optional, List
# from uuid import UUID
# from backend.database.connection import get_db
# from backend.database import crud
# from backend.schemas.schemas import GeneratedDocumentResponse, DraftResponse
# import json

# router = APIRouter()


# def _serialize_doc(d) -> GeneratedDocumentResponse:
#     """
#     Safely serialize DB object to response.
#     structured_json in DB is JSONB (returns dict) — must convert to str for schema.
#     """
#     structured = d.structured_json

#     if structured is None:
#         structured_str = None
#     elif isinstance(structured, dict):
#         # JSONB column returns dict — serialize to string for schema
#         structured_str = json.dumps(structured)
#     elif isinstance(structured, list):
#         # Sometimes stored as list of sections directly
#         structured_str = json.dumps(structured)
#     elif isinstance(structured, str):
#         # Already a string — validate it's valid JSON
#         try:
#             json.loads(structured)
#             structured_str = structured
#         except Exception:
#             structured_str = None
#     else:
#         structured_str = None

#     return GeneratedDocumentResponse(
#         document_id=d.id,
#         session_id=d.session_id,
#         title=d.title or "",
#         content=d.content or "",
#         structured_json=structured_str,
#         version=d.version or "1.0",
#         validation_status=d.validation_status or "pending",
#         validation_notes=getattr(d, "validation_notes", None),
#         is_draft=d.is_draft if d.is_draft is not None else False,
#         created_at=d.created_at
#     )

# # ─────────────────────────────────────────
# # STATIC ROUTES FIRST — critical for FastAPI routing
# # ─────────────────────────────────────────


# @router.get("/documents", response_model=List[GeneratedDocumentResponse])
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
#     published = crud.publish_draft(db, document_id)
#     return _serialize_doc(published)


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

# @router.delete("/drafts/{document_id}")
# def delete_draft(document_id: int, db: Session = Depends(get_db)):
#     if not crud.get_draft_by_id(db, document_id):
#         raise HTTPException(status_code=404, detail="Draft not found")
#     crud.delete_document(db, document_id)
#     return {"message": "Draft deleted successfully"}


# # # ─────────────────────────────────────────
# # # DYNAMIC /{document_id} ROUTES LAST
# # # ─────────────────────────────────────────

# # # GET DOCUMENT BY ID
# @router.get("/{document_id:int}", response_model=GeneratedDocumentResponse)
# def get_document(document_id: int, db: Session = Depends(get_db)):
#     doc = crud.get_document_by_id(db, document_id)
#     if not doc:
#         raise HTTPException(status_code=404, detail="Document not found")
#     return _serialize_doc(doc)



# @router.delete("/{document_id:int}")
# def delete_document(document_id: int, db: Session = Depends(get_db)):
#     if not crud.get_document_by_id(db, document_id):
#         raise HTTPException(status_code=404, detail="Document not found")
#     crud.delete_document(db, document_id)
#     return {"message": "Document deleted successfully"}


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


