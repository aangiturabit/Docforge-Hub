from sqlalchemy.orm import Session
from backend.database import crud
from typing import Dict, Optional


def build_prompt(
    db: Session,
    department_name: str,
    template_name: str,
    template_description: str,
    template_id: int,
    answers: Dict[str, str]
) -> str:

    sections = crud.get_sections_by_template(db, template_id)

    sections_list = "\n".join(
        [f"{i+1}. {s.section_name}" for i, s in enumerate(sections)]
    )

    answers_formatted = "\n".join(
        [f"- {key}: {value}" for key, value in answers.items()]
    )

    prompt = f"""You are a professional business document writer for a SaaS company.

Department: {department_name}
Document Type: {template_name}
Description: {template_description}

This document must contain ALL of these sections:
{sections_list}

User has provided the following information:
{answers_formatted}

Generate a complete, professional {template_name} document.
Cover every section listed above.
Use formal professional tone appropriate for {department_name}.
Format each section clearly with the EXACT section name as a heading.
DO NOT change, shorten, or modify section names.
Make the document ready to use without any placeholders.
Do not include any instructions or meta text in the output.
Only return the final document content.
"""
    return prompt


def build_regenerate_prompt(
    db: Session,
    department_name: str,
    template_name: str,
    template_description: str,
    template_id: int,
    answers: Dict[str, str],
    feedback: Optional[str] = None
) -> str:

    prompt = build_prompt(
        db=db,
        department_name=department_name,
        template_name=template_name,
        template_description=template_description,
        template_id=template_id,
        answers=answers
    )

    if feedback:
        prompt += f"""
Additional Instructions from user:
{feedback}

Please improve and regenerate the document based on the above instructions.
Make sure all sections are still covered completely.
"""
    return prompt