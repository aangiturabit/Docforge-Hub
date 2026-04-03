from sqlalchemy.orm import Session
from uuid import UUID
from typing import Dict, Optional
from backend.database import crud
from backend.services import prompt_service, llm_service


# ─────────────────────────────────────────
# SAVE DOCUMENT
# ─────────────────────────────────────────
def save_document(
    db: Session,
    session_id: UUID,
    template_id: int,
    title: str,
    content: str
):
    """
    Saves generated document into DB.
    """
    return crud.save_generated_document(
        db=db,
        session_id=session_id,
        template_id=template_id,
        title=title,
        content=content
    )


# ─────────────────────────────────────────
# VALIDATE DOCUMENT
# ─────────────────────────────────────────
def validate_document(db: Session, document_id: int) -> dict:
    """
    Validates:
    - Required sections exist
    - Content length is sufficient
    """
    doc = crud.get_document_by_id(db, document_id)
    if not doc:
        return {"error": "Document not found"}

    sections = crud.get_sections_by_template(db, doc.template_id)
    missing_sections = []

    def normalize(text):
        return text.lower().replace(" or founder", "").strip()

    content = normalize(doc.content)

    for section in sections:
        section_name = normalize(section.section_name)

        if section_name not in content:
            missing_sections.append(section.section_name)

    is_valid = len(doc.content) >= 500 and len(missing_sections) == 0
    status = "validated" if is_valid else "failed"

    notes = (
        f"Missing sections: {missing_sections}"
        if missing_sections
        else "All sections present"
    )

    crud.update_document_validation(db, document_id, status, notes)

    return {
        "document_id": document_id,
        "is_valid": is_valid,
        "missing_sections": missing_sections,
        "validation_notes": notes
    }


# ─────────────────────────────────────────
# GET ALL VERSIONS
# ─────────────────────────────────────────
def get_all_versions(db: Session, session_id: UUID):
    """
    Returns all versions of documents for a session.
    """
    return crud.get_documents_by_session(db, session_id)


# ─────────────────────────────────────────
# PREVIEW DOCUMENT (WITH COMPANY CONTEXT)
# ─────────────────────────────────────────
def preview_document(
    db: Session,
    department_name: str,
    template_name: str,
    template_description: str,
    template_id: int,
    answers: Dict[str, str],
    company: Optional[Dict] = None   
) -> str:
    """
    Generates preview document (NOT saved in DB).
    Uses TEXT output (correct).
    """

    prompt = prompt_service.build_prompt(
        db=db,
        department_name=department_name,
        template_name=template_name,
        template_description=template_description,
        template_id=template_id,
        answers=answers,
        company=company   
    )

    # ✅ Correct function (TEXT output)
    content = llm_service.generate_with_llm(prompt)

    return content


# ─────────────────────────────────────────
# GENERATE FULL DOCUMENT (MAIN FLOW)
# ─────────────────────────────────────────
def generate_document(
    db: Session,
    department_name: str,
    template_name: str,
    template_description: str,
    template_id: int,
    answers: Dict[str, str],
    feedback: Optional[str] = None,
    company: Optional[Dict] = None  
) -> str:
    """
    Generates full document using prompt_service.
    Supports feedback-based regeneration.
    """

    user_prompt = prompt_service.build_regenerate_prompt(
        db=db,
        department_name=department_name,
        template_name=template_name,
        template_description=template_description,
        template_id=template_id,
        answers=answers,
        feedback=feedback,
        company=company   
    )


    content = llm_service.generate_with_llm(user_prompt)

    return content


# ─────────────────────────────────────────
# REGENERATE SINGLE SECTION (WITH CONTEXT)
# ─────────────────────────────────────────
# def regenerate_section(
#     db: Session,
#     document_id: int,
#     section_name: str,
#     answers: Dict[str, str] = None,
#     feedback: str = None,
#     company: Optional[Dict] = None  
# ) -> dict:
#     """
#     Regenerates ONLY one section of the document or full document based on user feedback and provided answers, while maintaining the company context he LLM should focus solely on the specified section, using the provided answers and feedback to make necessary adjustments without hallucinating any information. The output should be in plain text format without any markdown syntax, and numerical data should be included in a table format where appropriate. The regenerated content should seamlessly integrate with the existing document, ensuring a cohesive and professional final output that aligns with the company's style and standards.
#     Maintains tone and responsiveness to feedback while ensuring consistency with the rest of the document.
#     Should be in a user way approach with clear instructions to the llm to focus only on the section that needs to be regenerated and use the company context to maintain the consistent with the rest of the document. The llm should not hallucinate any information and should use the provided answers and feedback to make necessary adjustments to the section content. The output should be in plain text format without any markdown syntax, and numerical data should be included in a table format where appropriate.
#     """

#     doc = crud.get_document_by_id(db, document_id)
#     if not doc:
#         return {"error": "Document not found"}

#     template = crud.get_template_by_id(db, doc.template_id)

#     session = crud.get_session_by_id(db, doc.session_id)
#     department = crud.get_department_by_id(db, session.department_id)

#     # ✅ Build company context block
#     company_text = ""
#     if company:
#         company_text = f"""
# Company Context:
# - Company Name: {company.get("name", "Not specified")}
# - Industry: {company.get("industry", "Not specified")}
# - Company Size: {company.get("size", "Not specified")}
# - Location: {company.get("location", "Not specified")}
# - Tone: {company.get("tone", "Professional")} 
# """

#     feedback_text = f"\nFocus only on this section: {section_name}"
#     if feedback:
#         feedback_text += f"\nAdditional instructions: {feedback}"

#     # ✅ Improved prompt (aligned with main system)
#     prompt = f"""
# You are a professional business document writer with expertise in {department.name} documents. You are updating a document based on user feedback and provided answers and mainting the  {company.get('tone', 'Professional')} style consistent with the company context.

# {company_text}

# Department: {department.name}
# Document Type: {template.name}

# Regenerate ONLY this section: {section_name}

# User provided information:
# {answers if answers else "Use context from the document"}

# IMPORTANT:
# - Use company context to adjust tone and style. no **,/, ## or any other markdown syntax in the output.should be bold and clear.with all sections .
# - Do not invent any information. use section conext and validation to ensure the accuracy of the content. 
# - Numerical answers should be included in the section if relevant and should not hallicunate numbers. If the user provided a number, use according to the section context. use table format in document iwhere appropriate to reports ,financials or any other numerical data. don't give generic statements or numbers llm should not hallicnate & give validations answer according to the document context. 
# - Maintain consistency with the rest of the document. when the comapny context is needed write the comapny name instead of using the [company name] token or placeholder. 

# {feedback_text}

# Return only the content for this section.
# Start with the section heading make it bold .
# """

#     new_section_content = llm_service.generate_with_llm(prompt)

#     updated_doc = crud.update_document_section(
#         db, document_id, section_name, new_section_content
#     )

#     return {
#         "document_id": document_id,
#         "section_name": section_name,
#         "updated_content": updated_doc.content if updated_doc else ""
#     }

def regenerate_section(
    db: Session,
    document_id: int,
    section_name: str,
    answers: dict = None,
    feedback: str = None,
    company: dict = None
) -> dict:
    doc = crud.get_document_by_id(db, document_id)
    if not doc:
        return {"error": "Document not found"}

    template = crud.get_template_by_id(db, doc.template_id)
    session = crud.get_session_by_id(db, doc.session_id)
    department = crud.get_department_by_id(db, session.department_id)

   
    tone = company.get('tone', 'Professional') if company else 'Professional'

    from backend.services import prompt_service
    from backend.services import llm_service

    role = prompt_service._classify_section_role(section_name)
    role_instruction = prompt_service.ROLE_INSTRUCTIONS.get(role, "Write clearly and professionally.")

    feedback_note = f"\nUser instruction: {feedback}" if feedback else ""
    answers_formatted = "\n".join([f"  {k}: {v}" for k, v in (answers or {}).items() if v])

    system_prompt = (
        f"You are a professional business document writer with expertise in "
        f"{department.name} documents. You are updating a specific section "
        f"based on user feedback. Maintain {tone} tone throughout."
    )

    section_prompt = f"""Document: {template.name}
Department: {department.name}
Section to regenerate: {section_name}
Role: {role} → {role_instruction}
{feedback_note}

Relevant information:
{answers_formatted if answers_formatted else "Use professional defaults."}

Write ONLY the content for this section.
Start with ## {section_name}
Return section content only."""

    new_content = llm_service.generate_with_llm(section_prompt, system_prompt)

    updated = crud.update_document_section(
        db, document_id, section_name, new_content
    )

    return {
        "document_id": document_id,
        "section_name": section_name,
        "updated_content": updated.content if updated else new_content
    }