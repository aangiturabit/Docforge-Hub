from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
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

router = APIRouter()


# ─────────────────────────────────────────
# 1. GENERATE QUESTIONS
# ─────────────────────────────────────────

@router.post("/generate/questions", response_model=GenerateQuestionsResponse)
def generate_questions(
    request: GenerateQuestionsRequest,
    db: Session = Depends(get_db)
):
    template = crud.get_template_by_id(db, request.document_type_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return question_service.get_form_structure(db, request.document_type_id)


# ─────────────────────────────────────────
# 2. PREVIEW DOCUMENT (no save)
# ─────────────────────────────────────────

@router.post("/generate/preview", response_model=PreviewDocumentResponse)
def preview_document(
    request: PreviewDocumentRequest,
    db: Session = Depends(get_db)
):
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
        answers=request.answers
    )

    return PreviewDocumentResponse(
        content=content,
        department=department.name,
        template=template.name
    )


# ─────────────────────────────────────────
# 3. GENERATE DOCUMENT (save to DB)
# ─────────────────────────────────────────

@router.post("/generate/document", response_model=GeneratedDocumentResponse)
def generate_document(
    request: GenerateDocumentRequest,
    db: Session = Depends(get_db)
):
    session = crud.get_session_by_id(db, request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    template = crud.get_template_by_id(db, request.template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    department = crud.get_department_by_id(db, request.department_id)
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")

    crud.update_session_status(db, request.session_id, "in_progress")

    prompt = prompt_service.build_prompt(
        db=db,
        department_name=department.name,
        template_name=template.name,
        template_description=template.description,
        template_id=request.template_id,
        answers=request.answers
    )

    content = llm_service.generate_with_llm(prompt)

    doc = document_service.save_document(
        db=db,
        session_id=request.session_id,
        template_id=request.template_id,
        title=template.name,
        content=content
    )

    crud.update_session_status(db, request.session_id, "completed")

    return GeneratedDocumentResponse(
        document_id=doc.id,
        session_id=doc.session_id,
        title=doc.title,
        content=doc.content,
        validation_status=doc.validation_status,
        created_at=doc.created_at
    )


# ─────────────────────────────────────────
# 4. VALIDATE DOCUMENT
# ─────────────────────────────────────────

@router.post("/generate/validate", response_model=ValidateDocumentResponse)
def validate_document(
    request: ValidateDocumentRequest,
    db: Session = Depends(get_db)
):
    result = document_service.validate_document(db, request.document_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ─────────────────────────────────────────
# 5. REGENERATE DOCUMENT
# ─────────────────────────────────────────

@router.post("/generate/regenerate", response_model=GeneratedDocumentResponse)
def regenerate_document(
    request: RegenerateDocumentRequest,
    db: Session = Depends(get_db)
):
    session = crud.get_session_by_id(db, request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    template = crud.get_template_by_id(db, session.template_id)
    department = crud.get_department_by_id(db, session.department_id)

    if not request.answers:
        previous_answers = crud.get_answers_by_session(db, request.session_id)
        answers = {str(a.question_id): a.answer_text for a in previous_answers}
    else:
        answers = request.answers

    prompt = prompt_service.build_regenerate_prompt(
        db=db,
        department_name=department.name,
        template_name=template.name,
        template_description=template.description,
        template_id=session.template_id,
        answers=answers,
        feedback=request.feedback
    )

    content = llm_service.generate_with_llm(prompt)

    doc = document_service.save_document(
        db=db,
        session_id=request.session_id,
        template_id=session.template_id,
        title=template.name,
        content=content
    )

    return GeneratedDocumentResponse(
        document_id=doc.id,
        session_id=doc.session_id,
        title=doc.title,
        content=doc.content,
        validation_status=doc.validation_status,
        created_at=doc.created_at
    )


# ─────────────────────────────────────────
# 6. REGENERATE SECTION
# ─────────────────────────────────────────

@router.post("/generate/section", response_model=RegenerateSectionResponse)
def regenerate_section(
    request: RegenerateSectionRequest,
    db: Session = Depends(get_db)
):
    doc = crud.get_document_by_id(db, request.document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    result = document_service.regenerate_section(
        db=db,
        document_id=request.document_id,
        section_name=request.section_name,
        answers=request.answers,
        feedback=request.feedback
    )

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return result


# ─────────────────────────────────────────
# 7. GET DOCUMENT BY ID
# ─────────────────────────────────────────

@router.get("/generate/document/{document_id}", response_model=GeneratedDocumentResponse)
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