from pydantic import BaseModel
from typing import List, Optional, Dict
from uuid import UUID
from datetime import datetime


# ─────────────────────────────────────────
# DEPARTMENT SCHEMAS
# ─────────────────────────────────────────

class DepartmentResponse(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


# ─────────────────────────────────────────
# DOCUMENT TEMPLATE SCHEMAS
# ─────────────────────────────────────────

class TemplateResponse(BaseModel):
    id: int
    department_id: int
    name: str
    description: Optional[str] = None
    version: Optional[str] = None

    class Config:
        from_attributes = True


# ─────────────────────────────────────────
# SECTION FIELD SCHEMAS
# ─────────────────────────────────────────

class SectionFieldResponse(BaseModel):
    id: int
    field_name: str
    field_label: str
    field_type: str
    is_required: bool

    class Config:
        from_attributes = True


# ─────────────────────────────────────────
# TEMPLATE SECTION SCHEMAS
# ─────────────────────────────────────────

class SectionWithFieldsResponse(BaseModel):
    section_id: int
    section_name: str
    section_order: int
    fields: List[SectionFieldResponse]

    class Config:
        from_attributes = True


# ─────────────────────────────────────────
# GENERATE QUESTIONS SCHEMAS
# ─────────────────────────────────────────

class GenerateQuestionsRequest(BaseModel):
    document_type_id: int


class GenerateQuestionsResponse(BaseModel):
    session_id: UUID
    department: str
    template: str
    sections: List[SectionWithFieldsResponse]


# ─────────────────────────────────────────
# GENERATE DOCUMENT SCHEMAS
# ─────────────────────────────────────────

class GenerateDocumentRequest(BaseModel):
    session_id: UUID
    department_id: int
    template_id: int
    answers: Dict[str, str]


class GeneratedDocumentResponse(BaseModel):
    document_id: int
    session_id: UUID
    title: str
    content: str
    validation_status: str
    created_at: datetime

    class Config:
        from_attributes = True


# ─────────────────────────────────────────
# SESSION SCHEMAS
# ─────────────────────────────────────────

class SessionResponse(BaseModel):
    id: UUID
    department_id: int
    template_id: int
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


# ─────────────────────────────────────────
# ANSWER SCHEMAS
# ─────────────────────────────────────────

class AnswerItem(BaseModel):
    question_id: int
    answer_text: str


class SaveAnswersRequest(BaseModel):
    session_id: UUID
    answers: List[AnswerItem]


# ─────────────────────────────────────────
# DOCUMENT LIBRARY SCHEMAS
# ─────────────────────────────────────────

class DocumentLibraryItem(BaseModel):
    id: int
    title: str
    template_id: int
    validation_status: str
    created_at: datetime

    class Config:
        from_attributes = True


# ─────────────────────────────────────────
# NOTION SCHEMAS
# ─────────────────────────────────────────

class NotionPublishRequest(BaseModel):
    document_id: int


class NotionPublishResponse(BaseModel):
    status: str
    notion_page_id: Optional[str] = None
    message: Optional[str] = None


# ─────────────────────────────────────────
# VALIDATE DOCUMENT SCHEMAS
# ─────────────────────────────────────────

class ValidateDocumentRequest(BaseModel):
    document_id: int


class ValidateDocumentResponse(BaseModel):
    document_id: int
    is_valid: bool
    missing_sections: List[str]
    validation_notes: str


# ─────────────────────────────────────────
# REGENERATE DOCUMENT SCHEMAS
# ─────────────────────────────────────────

class RegenerateDocumentRequest(BaseModel):
    session_id: UUID
    answers: Optional[Dict[str, str]] = None
    feedback: Optional[str] = None


# ─────────────────────────────────────────
# PREVIEW SCHEMA
# ─────────────────────────────────────────

class PreviewDocumentRequest(BaseModel):
    department_id: int
    template_id: int
    answers: Dict[str, str]


class PreviewDocumentResponse(BaseModel):
    content: str
    department: str
    template: str


# ─────────────────────────────────────────
# DRAFT SCHEMAS
# ─────────────────────────────────────────

class DraftResponse(BaseModel):
    id: int
    session_id: UUID
    title: str
    content: str
    version: str
    is_draft: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ─────────────────────────────────────────
# SECTION REGENERATE SCHEMA
# ─────────────────────────────────────────

class RegenerateSectionRequest(BaseModel):
    document_id: int
    section_name: str
    answers: Optional[Dict[str, str]] = None
    feedback: Optional[str] = None


class RegenerateSectionResponse(BaseModel):
    document_id: int
    section_name: str
    updated_content: str


# ─────────────────────────────────────────
# DOCUMENT LIBRARY FILTER SCHEMA
# ─────────────────────────────────────────

class DocumentFilterRequest(BaseModel):
    department_id: Optional[int] = None
    template_id: Optional[int] = None
    is_draft: Optional[bool] = None