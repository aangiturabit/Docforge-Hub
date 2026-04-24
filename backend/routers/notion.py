from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.database.connection import get_db
from backend.database import crud
from backend.services import notion_service
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


class NotionPublishRequest(BaseModel):
    document_id: int
    page_title: Optional[str] = None


class NotionPublishResponse(BaseModel):
    document_id: int
    notion_page_id: str
    notion_url: str
    status: str


@router.post("/notion/publish", response_model=NotionPublishResponse)
def publish_to_notion(request: NotionPublishRequest, db: Session = Depends(get_db)):
    doc = crud.get_document_by_id(db, request.document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Resolve department + template name for property filling
    template   = crud.get_template_by_id(db, doc.template_id) if doc.template_id else None
    session    = crud.get_session_by_id(db, doc.session_id) if doc.session_id else None
    department = crud.get_department_by_id(db, session.department_id) if session else None

    result = notion_service.publish_document(
        document_id=request.document_id,
        title=request.page_title or doc.title,
        content=doc.content,
        department=department.name if department else "",
        template_name=template.name if template else "",
    )

    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])

    return NotionPublishResponse(
        document_id=request.document_id,
        notion_page_id=result["page_id"],
        notion_url=result["url"],
        status="published",
    )