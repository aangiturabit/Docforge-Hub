from sqlalchemy.orm import Session
from backend.database.models import (
    Department,
    DocumentTemplate,
    TemplateSection,
    SectionField,
    UserSession,
    SessionQuestion,
    SessionAnswer,
    GeneratedDocument
)
from uuid import UUID
import uuid


# ─────────────────────────────────────────
# DEPARTMENT
# ─────────────────────────────────────────

def get_all_departments(db: Session):
    return db.query(Department).all()


def get_department_by_id(db: Session, department_id: int):
    return db.query(Department).filter(Department.id == department_id).first()


# ─────────────────────────────────────────
# DOCUMENT TEMPLATES
# ─────────────────────────────────────────

def get_templates_by_department(db: Session, department_id: int):
    return db.query(DocumentTemplate).filter(
        DocumentTemplate.department_id == department_id
    ).all()


def get_template_by_id(db: Session, template_id: int):
    return db.query(DocumentTemplate).filter(
        DocumentTemplate.id == template_id
    ).first()


# ─────────────────────────────────────────
# TEMPLATE SECTIONS
# ─────────────────────────────────────────

def get_sections_by_template(db: Session, template_id: int):
    return db.query(TemplateSection).filter(
        TemplateSection.template_id == template_id
    ).order_by(TemplateSection.section_order).all()


# ─────────────────────────────────────────
# SECTION FIELDS
# ─────────────────────────────────────────

def get_fields_by_section(db: Session, section_id: int):
    return db.query(SectionField).filter(
        SectionField.section_id == section_id
    ).all()


def get_fields_by_template(db: Session, template_id: int):
    sections = get_sections_by_template(db, template_id)
    result = []
    for section in sections:
        fields = get_fields_by_section(db, section.id)
        result.append({
            "section_id": section.id,
            "section_name": section.section_name,
            "section_order": section.section_order,
            "fields": fields
        })
    return result


# ─────────────────────────────────────────
# USER SESSIONS
# ─────────────────────────────────────────

def create_session(db: Session, department_id: int, template_id: int):
    session = UserSession(
        id=uuid.uuid4(),
        department_id=department_id,
        template_id=template_id,
        status="pending"
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session_by_id(db: Session, session_id: UUID):
    return db.query(UserSession).filter(
        UserSession.id == session_id
    ).first()


def update_session_status(db: Session, session_id: UUID, status: str):
    session = get_session_by_id(db, session_id)
    if session:
        session.status = status
        db.commit()
        db.refresh(session)
    return session


# ─────────────────────────────────────────
# SESSION QUESTIONS
# ─────────────────────────────────────────

def save_questions(db: Session, session_id: UUID, questions: list):
    saved = []
    for q in questions:
        question = SessionQuestion(
            session_id=session_id,
            question_text=q["question_text"],
            field_key=q["field_key"],
            order_index=q["order_index"]
        )
        db.add(question)
        saved.append(question)
    db.commit()
    return saved


def get_questions_by_session(db: Session, session_id: UUID):
    return db.query(SessionQuestion).filter(
        SessionQuestion.session_id == session_id
    ).order_by(SessionQuestion.order_index).all()


# ─────────────────────────────────────────
# SESSION ANSWERS
# ─────────────────────────────────────────

def save_answers(db: Session, session_id: UUID, answers: list):
    saved = []
    for a in answers:
        answer = SessionAnswer(
            session_id=session_id,
            question_id=a["question_id"],
            answer_text=a["answer_text"]
        )
        db.add(answer)
        saved.append(answer)
    db.commit()
    return saved


def get_answers_by_session(db: Session, session_id: UUID):
    return db.query(SessionAnswer).filter(
        SessionAnswer.session_id == session_id
    ).all()


# ─────────────────────────────────────────
# GENERATED DOCUMENTS
# ─────────────────────────────────────────

def save_generated_document(
    db: Session,
    session_id: UUID,
    template_id: int,
    title: str,
    content: str
):
    doc = GeneratedDocument(
        session_id=session_id,
        template_id=template_id,
        title=title,
        content=content,
        validation_status="pending"
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def get_document_by_session(db: Session, session_id: UUID):
    return db.query(GeneratedDocument).filter(
        GeneratedDocument.session_id == session_id
    ).first()


def get_document_by_id(db: Session, document_id: int):
    return db.query(GeneratedDocument).filter(
        GeneratedDocument.id == document_id
    ).first()


def get_all_documents(db: Session, department_id: int = None, template_id: int = None):
    query = db.query(GeneratedDocument)
    if department_id:
        query = query.join(UserSession).filter(
            UserSession.department_id == department_id
        )
    if template_id:
        query = query.filter(
            GeneratedDocument.template_id == template_id
        )
    return query.order_by(GeneratedDocument.created_at.desc()).all()


def update_document_validation(
    db: Session,
    document_id: int,
    status: str,
    notes: str = None
):
    doc = get_document_by_id(db, document_id)
    if doc:
        doc.validation_status = status
        doc.validation_notes = notes
        db.commit()
        db.refresh(doc)
    return doc