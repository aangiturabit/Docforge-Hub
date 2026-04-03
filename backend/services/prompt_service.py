from sqlalchemy.orm import Session
from backend.database import crud
from typing import Dict, Optional
from backend.services import llm_service
import json
import hashlib

# ─────────────────────────────────────────
# IN-MEMORY CACHE
# ─────────────────────────────────────────
_document_cache: dict = {}

def _make_document_cache_key(
    department_name: str,
    template_name: str,
    template_id: int,
    answers: Dict[str, str],
    feedback: Optional[str] = None,
    company: Optional[Dict] = None   
) -> str:
    """Create stable cache key for document generation"""
    sorted_answers = sorted(answers.items())

    company_part = json.dumps(company, sort_keys=True) if company else ""

    raw = f"{department_name}:{template_name}:{template_id}:{json.dumps(sorted_answers)}:{feedback or ''}:{company_part}"
    return hashlib.md5(raw.encode()).hexdigest()


# ─────────────────────────────────────────
# SYSTEM PROMPT
# ─────────────────────────────────────────
DOCUMENT_SYSTEM_PROMPT = """
You are an expert professional business document writer for  SaaS companies.
Create premium-quality, comprehensive, engaging, and polished business documents that are executive-ready and suitable for direct PDF conversion.
For the sections that require the numerical answer should be static in some questions according the document requirements. 


Core Requirements:
- Use ONLY the exact information provided in the User Provided Information. Never add, invent, assume, or hallucinate any extra details, dates, names, amounts, or clauses.
- If information is missing for any section, use "Not Provided" or a short professional placeholder. Do not fabricate content.
- Follow the exact section names and order given by the user. Never change, add, remove, or rename any section heading.
- Make every section heading clear and prominent using Markdown: ## Section Name
- Write each section in a highly professional, formal yet warm tone suitable for SaaS business documents.
- Expand every section with rich, detailed, and substantial content. Avoid short or generic text.

Word Limit Guidelines for Lengthy Documents:
- Short sections (header, date, parties): 80–200 words
- Standard sections (introduction, scope, terms): 300–500 words
- Detailed sections (CTC breakdown, responsibilities, confidentiality, conditions): 500–900+ words
- Overall document should feel comprehensive and professional don't make it too cluster for a user to read the content (typically 1000–3000+ words depending on the template).

Formatting Rules:
- Use clean Markdown.
- Use tables for breakdowns, amounts, lists, or comparisons.
- Do not repeat information unnecessarily across sections.
- Output ONLY the final document content. No explanations, no introductions, no meta text, and no code blocks.

Start directly with the document using the exact section headings provided.
"""

# ─────────────────────────────────────────
# FEW-SHOT EXAMPLE 
# ─────────────────────────────────────────
FEW_SHOT_EXAMPLES = """
Good output example style for an Offer Letter:

## Company Letterhead and Date
NexusCloud Solutions Pvt. Ltd.
Ahmedabad, Gujarat, India
Date: 30 March 2026

## Candidate Full Name and Address
Priya Sharma
[Full Address as provided]

## Offer of Employment
We are delighted to extend this formal offer of employment for the position of Senior Software Engineer...

## Gross CTC Breakdown
| Component                | Amount (₹)     |
|--------------------------|----------------|
| Basic Salary             | 18,00,000      |
| House Rent Allowance     | 7,20,000       |
[Full detailed table...]

## Terms and Conditions
[Long, detailed paragraph(s) covering all aspects using only provided data...]

Continue this style for all sections with rich, professional, and lengthy content.
"""

# ─────────────────────────────────────────
# PROMPT BUILDER
# ─────────────────────────────────────────
def build_prompt(
    db: Session,
    department_name: str,
    template_name: str,
    template_description: str,
    template_id: int,
    answers: Dict[str, str],
    company: Optional[Dict] = None
) -> str:

    
    if company:
        company_context_text = f"""
Company Context:
- Company Name: {company.get("name", "Not specified")}
- Industry: {company.get("industry", "Not specified")}
- Company Size: {company.get("size", "Not specified")}
- Location: {company.get("location", "Not specified")}
- Tone: {company.get("tone", "Professional")}
"""
    else:
        company_context_text = """
Company Context:
- Not specified. Use a neutral professional tone.
"""

    sections = crud.get_sections_by_template(db, template_id)
    sections_list = "\n".join([f"- {s.section_name}" for s in sections])

    answers_formatted = "\n".join([
        f"- {key}: {value}"
        for key, value in answers.items()
        if value and str(value).strip()
    ])

    user_prompt = f"""
{FEW_SHOT_EXAMPLES}

{company_context_text}

Department: {department_name}
Document Type: {template_name}
Description: {template_description}

Required Sections:
{sections_list}

User Provided Information:
{answers_formatted if answers_formatted else "No specific details provided."}

IMPORTANT:
- Use the company context to adjust tone, writing style, and level of formality
- Do not add information not provided & maintain the exact section headings and order. Don't hallicinate any details and dont repeat the content across sections.
- Make every section detailed, professional, and substantial while following the word limit guidelines. maintain a proper length content for each section based on its importance and type.

Generate a comprehensive, lengthy, and premium-quality {template_name} document.
Make every section detailed and substantial while strictly following the rules and word guidelines above.
"""


    return user_prompt


# ─────────────────────────────────────────
# REGENERATE PROMPT BUILDER
# ─────────────────────────────────────────
def build_regenerate_prompt(
    db: Session,
    department_name: str,
    template_name: str,
    template_description: str,
    template_id: int,
    answers: Dict[str, str],
    feedback: Optional[str] = None,
    company: Optional[Dict] = None   
) -> str:

    base_prompt = build_prompt(
        db=db,
        department_name=department_name,
        template_name=template_name,
        template_description=template_description,
        template_id=template_id,
        answers=answers,
        company=company   
    )

    if feedback:
        base_prompt += f"""

User Feedback:
{feedback}

Regenerate the document incorporating this feedback.
Keep tone consistent with company context.
"""

    return base_prompt


# ─────────────────────────────────────────
# MAIN DOCUMENT GENERATION
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

    cache_key = _make_document_cache_key(
        department_name,
        template_name,
        template_id,
        answers,
        feedback,
        company   
    )

    if cache_key in _document_cache:
        return _document_cache[cache_key]

    user_prompt = build_regenerate_prompt(
        db=db,
        department_name=department_name,
        template_name=template_name,
        template_description=template_description,
        template_id=template_id,
        answers=answers,
        feedback=feedback,
        company=company   
    )

    
    response = llm_service.generate_with_llm(user_prompt)

    cleaned_response = response.strip()

    if cleaned_response.startswith("```"):
        cleaned_response = cleaned_response.split("```", 1)[1].split("```", 1)[0].strip()

    _document_cache[cache_key] = cleaned_response
    return cleaned_response