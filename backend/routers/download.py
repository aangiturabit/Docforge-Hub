

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.database.connection import get_db
from backend.database import crud
from backend.renderers.pdf_renderer import render_pdf
from backend.renderers.docx_renderer import render_docx
from backend.utils.logger import get_logger

logger   = get_logger("docforge.routers.download")
router   = APIRouter(prefix="/documents", tags=["download"])


def _load_structured(doc) -> list:
    """
    Parse structured_json from the document ORM object.
    Returns a list of section dicts.
    """
    if not doc.structured_json:
        return []
    try:
        raw = json.loads(doc.structured_json)
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            return raw.get("sections", [])
    except Exception:
        pass
    return []


def _parse_company(company_json: str | None) -> dict:
    """Safely parse the optional company query-param JSON string."""
    if not company_json:
        return {}
    try:
        return json.loads(company_json)
    except Exception:
        return {}


def _department_name(db: Session, doc) -> str:
    try:
        session    = crud.get_session_by_id(db, doc.session_id)
        department = crud.get_department_by_id(db, session.department_id)
        return department.name if department else ""
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# PDF endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{document_id}/pdf")
def download_pdf(
    document_id: int,
    company_json: str = Query(default=None, alias="company_json"),
    db: Session = Depends(get_db),
):
    """
    Generate and return a PDF for the given document.
    Returns application/pdf bytes with Content-Disposition: attachment.
    """
    logger.info("download_pdf | doc_id=%d", document_id)

    doc = crud.get_document_by_id(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    sections = _load_structured(doc)
    if not sections:
        raise HTTPException(status_code=404, detail="Document has no structured content")

    company = _parse_company(company_json)
    dept    = _department_name(db, doc)
    title   = doc.title or "Document"

    try:
        pdf_bytes = render_pdf(
            structured_sections=sections,
            title=title,
            company=company,
            department=dept,
        )
    except Exception as exc:
        logger.error("download_pdf: render failed | doc_id=%d | %s", document_id, exc)
        raise HTTPException(status_code=500, detail=f"PDF render failed: {exc}")

    safe_title = title.replace("/", "-").replace("\\", "-")[:80]
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_title}.pdf"'},
    )


# ─────────────────────────────────────────────────────────────────────────────
# DOCX endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{document_id}/docx")
def download_docx(
    document_id: int,
    company_json: str = Query(default=None, alias="company_json"),
    db: Session = Depends(get_db),
):
    """
    Generate and return a DOCX for the given document.
    Returns application/vnd.openxmlformats-officedocument.wordprocessingml.document bytes.
    """
    logger.info("download_docx | doc_id=%d", document_id)

    doc = crud.get_document_by_id(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    sections = _load_structured(doc)
    if not sections:
        raise HTTPException(status_code=404, detail="Document has no structured content")

    company = _parse_company(company_json)
    dept    = _department_name(db, doc)
    title   = doc.title or "Document"

    try:
        docx_bytes = render_docx(
            structured_sections=sections,
            title=title,
            company=company,
            department=dept,
        )
    except Exception as exc:
        logger.error("download_docx: render failed | doc_id=%d | %s", document_id, exc)
        raise HTTPException(status_code=500, detail=f"DOCX render failed: {exc}")

    safe_title = title.replace("/", "-").replace("\\", "-")[:80]
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{safe_title}.docx"'},
    )