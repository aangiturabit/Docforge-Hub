from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
from backend.database.connection import Base


class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class DocumentTemplate(Base):
    __tablename__ = "document_templates"

    id = Column(Integer, primary_key=True, index=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    name = Column(String(150), nullable=False)
    description = Column(Text)
    version = Column(String(20), default="1.0")
    created_at = Column(DateTime, server_default=func.now())


class TemplateSection(Base):
    __tablename__ = "template_sections"

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("document_templates.id"), nullable=False)
    section_name = Column(String(200), nullable=False)
    section_order = Column(Integer, nullable=False)


class SectionField(Base):
    __tablename__ = "section_fields"

    id = Column(Integer, primary_key=True, index=True)
    section_id = Column(Integer, ForeignKey("template_sections.id"), nullable=False)
    field_name = Column(String(100), nullable=False)
    field_label = Column(String(150), nullable=False)
    field_type = Column(String(50), nullable=False, default="text")
    is_required = Column(Boolean, default=True)


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    template_id = Column(Integer, ForeignKey("document_templates.id"), nullable=False)
    status = Column(String(50), default="pending")
    created_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime, nullable=True)

class SessionQuestion(Base):
    __tablename__ = "session_questions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey("user_sessions.id"), nullable=False)
    question_text = Column(Text, nullable=False)
    field_key = Column(String(100), nullable=False)
    field_name = Column(String(100), nullable=True)  
    order_index = Column(Integer, nullable=False)


class SessionAnswer(Base):
    __tablename__ = "session_answers"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey("user_sessions.id"), nullable=False)
    question_id = Column(Integer, ForeignKey("session_questions.id"), nullable=False)
    answer_text = Column(Text, nullable=False)


class GeneratedDocument(Base):
    __tablename__ = "generated_documents"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey("user_sessions.id"), nullable=False)
    template_id = Column(Integer, ForeignKey("document_templates.id"), nullable=False)
    title = Column(String(255))
    content = Column(Text, nullable=False)
    version = Column(String(20), default="1.0")
    validation_status = Column(String(50), default="pending")
    validation_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())