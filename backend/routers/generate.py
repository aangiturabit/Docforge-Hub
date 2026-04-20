from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from backend.database.connection import get_db
from backend.database import crud
from backend.schemas.schemas import (
    GenerateQuestionsRequest,
    GenerateQuestionsResponse,
    GenerateDocumentRequest,
    GeneratedDocumentResponse,
    ValidateDocumentRequest,
    ValidateDocumentResponse,
    RegenerateDocumentRequest,
    PreviewDocumentRequest,
    PreviewDocumentResponse,
    RegenerateSectionRequest,
    RegenerateSectionResponse
)
from backend.services import question_service
from backend.services import prompt_service
from backend.services import llm_service
from backend.services import document_service
import json

router = APIRouter()


def _to_json_str(value) -> Optional[str]:
    """Always returns JSON string or None — never dict."""
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





def _doc_response(doc) -> GeneratedDocumentResponse:
    """Single serializer — structured_json always str."""
    return GeneratedDocumentResponse(
        document_id=doc.id,
        session_id=doc.session_id,
        title=doc.title or "",
        content=doc.content or "",
        structured_json=_to_json_str(doc.structured_json),
        version=doc.version or "1.0",
        validation_status=doc.validation_status or "pending",
        validation_notes=getattr(doc, "validation_notes", None),
        is_draft=doc.is_draft if doc.is_draft is not None else False,
        created_at=doc.created_at
    )


@router.post("/generate/questions", response_model=GenerateQuestionsResponse)
def generate_questions(request: GenerateQuestionsRequest, db: Session = Depends(get_db)):
    template = crud.get_template_by_id(db, request.document_type_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return question_service.get_form_structure(
        db=db,
        template_id=request.document_type_id,
        company=getattr(request, "company", None),
    )


@router.post("/generate/preview", response_model=PreviewDocumentResponse)
def preview_document(request: PreviewDocumentRequest, db: Session = Depends(get_db)):
    template = crud.get_template_by_id(db, request.template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    department = crud.get_department_by_id(db, request.department_id)
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")

    content = document_service.preview_document(
        db=db,
        department_name=department.name,
        template_name=template.name,
        template_description=template.description,
        template_id=request.template_id,
        answers=request.answers,
        company=getattr(request, "company", None)
    )
    return PreviewDocumentResponse(
        content=content,
        department=department.name,
        template=template.name
    )


@router.post("/generate/document", response_model=GeneratedDocumentResponse)
def generate_document(request: GenerateDocumentRequest, db: Session = Depends(get_db)):
    template = crud.get_template_by_id(db, request.template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    department = crud.get_department_by_id(db, request.department_id)
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")

    session = crud.create_session(
        db=db,
        department_id=request.department_id,
        template_id=request.template_id,
    )
    crud.update_session_status(db, session.id, "in_progress")

    try:
        structured = document_service.generate_structured_document(
            db=db,
            department_name=department.name,
            template_name=template.name,
            template_description=template.description,
            template_id=request.template_id,
            answers=request.answers,
            company=request.company,
        )
        content = document_service.structured_to_plain_text(structured)
        structured_sections = structured.get("sections", [])
    except Exception:
        prompt = prompt_service.build_prompt(
            department_name=department.name,
            template_name=template.name,
            template_description=template.description,
            template_id=request.template_id,
            answers=request.answers,
            company=request.company,
        )
        content = document_service._clean_text(
            llm_service.generate_with_llm(
                prompt, system_prompt=prompt_service.DOCUMENT_SYSTEM_PROMPT
            )
        )
        structured_sections = []
    doc = document_service.save_document(
        db=db,
        session_id=session.id,
        template_id=request.template_id,
        title=template.name,
        content=content,
        structured_sections=structured_sections,
    )
    crud.update_session_status(db, session.id, "completed")
    return _doc_response(doc)



@router.post("/generate/validate", response_model=ValidateDocumentResponse)
def validate_document(request: ValidateDocumentRequest, db: Session = Depends(get_db)):
    result = document_service.validate_document(db, request.document_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/generate/regenerate", response_model=GeneratedDocumentResponse)
def regenerate_document(request: RegenerateDocumentRequest, db: Session = Depends(get_db)):
    session = crud.get_session_by_id(db, request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    template = crud.get_template_by_id(db, session.template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    department = crud.get_department_by_id(db, session.department_id)
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")

    answers = request.answers or {}
    if not answers:
        previous = crud.get_answers_by_session(db, request.session_id)
        answers = {str(a.question_id): a.answer_text for a in previous}

    company = getattr(request, "company", None)

    try:
        structured = document_service.generate_structured_document(
            db=db,
            department_name=department.name,
            template_name=template.name,
            template_description=template.description,
            template_id=session.template_id,
            answers=answers,
            company=company
        )
        if request.feedback:
            regen_prompt = prompt_service.build_regenerate_prompt(
                db=db,
                department_name=department.name,
                template_name=template.name,
                template_description=template.description,
                template_id=session.template_id,
                answers=answers,
                feedback=request.feedback,
                company=company
            )
            content = document_service._clean_text(
                llm_service.generate_with_llm(
                    regen_prompt,
                    system_prompt=prompt_service.DOCUMENT_SYSTEM_PROMPT
                )
            )
        else:
            content = document_service.structured_to_plain_text(structured)
        structured_sections = structured.get("sections", [])

    except Exception:
        prompt = prompt_service.build_regenerate_prompt(
            department_name=department.name,
            template_name=template.name,
            template_description=template.description,
            template_id=session.template_id,
            answers=answers,
            feedback=request.feedback,
            company=company,
        )
        content = document_service._clean_text(
            llm_service.generate_with_llm(
                prompt, system_prompt=prompt_service.DOCUMENT_SYSTEM_PROMPT
            )
        )
        structured_sections = []

    doc = document_service.save_document(
        db=db,
        session_id=request.session_id,
        template_id=session.template_id,
        title=template.name,
        content=content,
        structured_sections=structured_sections
    )
    return _doc_response(doc)


@router.post("/generate/section", response_model=RegenerateSectionResponse)
def regenerate_section(request: RegenerateSectionRequest, db: Session = Depends(get_db)):
    if not crud.get_document_by_id(db, request.document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    result = document_service.regenerate_section(
        db=db,
        document_id=request.document_id,
        section_name=request.section_name,
        answers=request.answers,
        feedback=request.feedback,
        company=getattr(request, "company", None)
    )
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/generate/document/{document_id}", response_model=GeneratedDocumentResponse)
def get_document(document_id: int, db: Session = Depends(get_db)):
    doc = crud.get_document_by_id(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return _doc_response(doc)




