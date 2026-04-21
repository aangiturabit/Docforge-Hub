from pydantic import BaseModel, Field 
from typing import List, Literal, Union, Optional, Dict,Any 
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
    company: Optional[Dict[str, str]] = None



class GenerateQuestionsResponse(BaseModel):
    session_id: Optional[UUID] = None    
    department: str
    template: str
    sections: List[SectionWithFieldsResponse]

# ─────────────────────────────────────────
# GENERATE DOCUMENT SCHEMAS
# ─────────────────────────────────────────

class GenerateDocumentRequest(BaseModel):
    department_id: int
    template_id: int
    answers: Dict[str, str]
    company: Optional[Dict[str, str]] = None

class GeneratedDocumentResponse(BaseModel):
    document_id: int
    session_id: Optional[UUID] = None
    title: str = ""
    content: str = ""
    structured_json: Optional[str] = None  # always str — never dict
    version: str = "1.0"
    validation_status: Optional[str] = "pending"
    validation_notes: Optional[str] = None
    is_draft: bool = False
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
    is_valid: bool = False
    total_issues: int = 0
    issues: List[Dict[str, Any]] = []
    missing_sections: List[str] = []
    order_issues: List[str] = []
    table_issues: List[str] = []
    grounding_issues: List[str] = []
    placeholder_issues: List[str] = []
    llm_judge_result: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True
# ─────────────────────────────────────────
# VALIDATION RESPONSE
# ─────────────────────────────────────────

class ValidationIssue(BaseModel):
    type: str
    section: str
    detail: str


class ValidationResponse(BaseModel):
    document_id: int
    is_valid: bool
    total_issues: int
    issues: List[ValidationIssue]
    missing_sections: List[str]
    order_issues: List[str]
    table_issues: List[str]
    grounding_issues: List[str]
    placeholder_issues: List[str]
    llm_judge_result: Optional[dict] = None

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


# ─────────────────────────────────────────
# STRUCTURED DOCUMENT SCHEMAS
# ─────────────────────────────────────────

class SectionStyling(BaseModel):
    alignment: Literal["left", "center", "justify"] = "justify"
    font_weight: Literal["bold", "normal"] = "normal"
    page_break_after: bool = False


class TableRow(BaseModel):
    cells: List[str]


class DocumentSection(BaseModel):
    id: str
    heading: str
    content_type: Literal["text", "table", "list"]
    content: Union[str, List[TableRow], List[str]]
    styling: SectionStyling = Field(default_factory=SectionStyling)
    word_count: int = 0


class DocumentMetadata(BaseModel):
    department: str
    doc_type: str
    generated_date: str
    company: str = ""


class StructuredDocument(BaseModel):
    document_metadata: DocumentMetadata
    sections: List[DocumentSection]
    validation_status: Literal["verified", "partial", "failed"] = "verified"