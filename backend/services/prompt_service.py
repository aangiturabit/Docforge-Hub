# from sqlalchemy.orm import Session
# from backend.database import crud
# from typing import Dict, Optional
# from backend.services import llm_service
# import json
# import hashlib

# # ─────────────────────────────────────────
# # IN-MEMORY CACHE
# # ─────────────────────────────────────────
# _document_cache: dict = {}

# def _make_document_cache_key(
#     department_name: str,
#     template_name: str,
#     template_id: int,
#     answers: Dict[str, str],
#     feedback: Optional[str] = None,
#     company: Optional[Dict] = None   
# ) -> str:
#     """Create stable cache key for document generation"""
#     sorted_answers = sorted(answers.items())

#     company_part = json.dumps(company, sort_keys=True) if company else ""

#     raw = f"{department_name}:{template_name}:{template_id}:{json.dumps(sorted_answers)}:{feedback or ''}:{company_part}"
#     return hashlib.md5(raw.encode()).hexdigest()


# # ─────────────────────────────────────────
# # SYSTEM PROMPT
# # ─────────────────────────────────────────
# DOCUMENT_SYSTEM_PROMPT = """
# You are an expert professional business document writer for  SaaS companies.
# Create premium-quality, comprehensive, engaging, and polished business documents that are executive-ready and suitable for direct PDF conversion.
# For the sections that require the numerical answer should be static in some questions according the document requirements. 


# Core Requirements:
# - Use ONLY the exact information provided in the User Provided Information. Never add, invent, assume, or hallucinate any extra details, dates, names, amounts, or clauses.
# - If information is missing for any section, use "Not Provided" or a short professional placeholder. Do not fabricate content.
# - Follow the exact section names and order given by the user. Never change, add, remove, or rename any section heading.
# - Make every section heading clear and prominent using Markdown: ## Section Name
# - Write each section in a highly professional, formal yet warm tone suitable for SaaS business documents.
# - Expand every section with rich, detailed, and substantial content. Avoid short or generic text.

# Word Limit Guidelines for Lengthy Documents:
# - Short sections (header, date, parties): 80–200 words
# - Standard sections (introduction, scope, terms): 300–500 words
# - Detailed sections (CTC breakdown, responsibilities, confidentiality, conditions): 500–900+ words
# - Overall document should feel comprehensive and professional don't make it too cluster for a user to read the content (typically 1000–3000+ words depending on the template).

# Formatting Rules:
# - Use clean Markdown.
# - Use tables for breakdowns, amounts, lists, or comparisons.
# - Do not repeat information unnecessarily across sections.
# - Output ONLY the final document content. No explanations, no introductions, no meta text, and no code blocks.

# Start directly with the document using the exact section headings provided.
# """

# # ─────────────────────────────────────────
# # FEW-SHOT EXAMPLE 
# # ─────────────────────────────────────────
# FEW_SHOT_EXAMPLES = """
# Good output example style for an Offer Letter:

# ## Company Letterhead and Date
# NexusCloud Solutions Pvt. Ltd.
# Ahmedabad, Gujarat, India
# Date: 30 March 2026

# ## Candidate Full Name and Address
# Priya Sharma
# [Full Address as provided]

# ## Offer of Employment
# We are delighted to extend this formal offer of employment for the position of Senior Software Engineer...

# ## Gross CTC Breakdown
# | Component                | Amount (₹)     |
# |--------------------------|----------------|
# | Basic Salary             | 18,00,000      |
# | House Rent Allowance     | 7,20,000       |
# [Full detailed table...]

# ## Terms and Conditions
# [Long, detailed paragraph(s) covering all aspects using only provided data...]

# Continue this style for all sections with rich, professional, and lengthy content.
# """

# # ─────────────────────────────────────────
# # PROMPT BUILDER
# # ─────────────────────────────────────────
# def build_prompt(
#     db: Session,
#     department_name: str,
#     template_name: str,
#     template_description: str,
#     template_id: int,
#     answers: Dict[str, str],
#     company: Optional[Dict] = None
# ) -> str:

    
#     if company:
#         company_context_text = f"""
# Company Context:
# - Company Name: {company.get("name", "Not specified")}
# - Industry: {company.get("industry", "Not specified")}
# - Company Size: {company.get("size", "Not specified")}
# - Location: {company.get("location", "Not specified")}
# - Tone: {company.get("tone", "Professional")}
# """
#     else:
#         company_context_text = """
# Company Context:
# - Not specified. Use a neutral professional tone.
# """

#     sections = crud.get_sections_by_template(db, template_id)
#     sections_list = "\n".join([f"- {s.section_name}" for s in sections])

#     answers_formatted = "\n".join([
#         f"- {key}: {value}"
#         for key, value in answers.items()
#         if value and str(value).strip()
#     ])

#     user_prompt = f"""
# {FEW_SHOT_EXAMPLES}

# {company_context_text}

# Department: {department_name}
# Document Type: {template_name}
# Description: {template_description}

# Required Sections:
# {sections_list}

# User Provided Information:
# {answers_formatted if answers_formatted else "No specific details provided."}

# IMPORTANT:
# - Use the company context to adjust tone, writing style, and level of formality
# - Do not add information not provided & maintain the exact section headings and order. Don't hallicinate any details and dont repeat the content across sections.
# - Make every section detailed, professional, and substantial while following the word limit guidelines. maintain a proper length content for each section based on its importance and type.

# Generate a comprehensive, lengthy, and premium-quality {template_name} document.
# Make every section detailed and substantial while strictly following the rules and word guidelines above.
# """


#     return user_prompt


# # ─────────────────────────────────────────
# # REGENERATE PROMPT BUILDER
# # ─────────────────────────────────────────
# def build_regenerate_prompt(
#     db: Session,
#     department_name: str,
#     template_name: str,
#     template_description: str,
#     template_id: int,
#     answers: Dict[str, str],
#     feedback: Optional[str] = None,
#     company: Optional[Dict] = None   
# ) -> str:

#     base_prompt = build_prompt(
#         db=db,
#         department_name=department_name,
#         template_name=template_name,
#         template_description=template_description,
#         template_id=template_id,
#         answers=answers,
#         company=company   
#     )

#     if feedback:
#         base_prompt += f"""

# User Feedback:
# {feedback}

# Regenerate the document incorporating this feedback.
# Keep tone consistent with company context.
# """

#     return base_prompt


# # ─────────────────────────────────────────
# # MAIN DOCUMENT GENERATION
# # ─────────────────────────────────────────
# def generate_document(
#     db: Session,
#     department_name: str,
#     template_name: str,
#     template_description: str,
#     template_id: int,
#     answers: Dict[str, str],
#     feedback: Optional[str] = None,
#     company: Optional[Dict] = None  
# ) -> str:

#     cache_key = _make_document_cache_key(
#         department_name,
#         template_name,
#         template_id,
#         answers,
#         feedback,
#         company   
#     )

#     if cache_key in _document_cache:
#         return _document_cache[cache_key]

#     user_prompt = build_regenerate_prompt(
#         db=db,
#         department_name=department_name,
#         template_name=template_name,
#         template_description=template_description,
#         template_id=template_id,
#         answers=answers,
#         feedback=feedback,
#         company=company   
#     )

    
#     response = llm_service.generate_with_llm(user_prompt)

#     cleaned_response = response.strip()

#     if cleaned_response.startswith("```"):
#         cleaned_response = cleaned_response.split("```", 1)[1].split("```", 1)[0].strip()

#     _document_cache[cache_key] = cleaned_response
#     return cleaned_response

from sqlalchemy.orm import Session
from backend.database import crud
from typing import Dict, Optional
from backend.services import llm_service
import json
import hashlib
import re
from datetime import date

# ─────────────────────────────────────────
# CACHE
# ─────────────────────────────────────────
_document_cache: dict = {}


def _make_cache_key(
    department_name: str,
    template_name: str,
    template_id: int,
    answers: Dict[str, str],
    feedback: Optional[str] = None,
    company: Optional[Dict] = None
) -> str:
    sorted_answers = sorted(answers.items())
    company_part = json.dumps(company, sort_keys=True) if company else ""
    raw = f"{department_name}:{template_name}:{template_id}:{json.dumps(sorted_answers)}:{feedback or ''}:{company_part}"
    return hashlib.md5(raw.encode()).hexdigest()


# ═══════════════════════════════════════════════════════
# LAYER 1 — ARCHETYPE DETECTION
# ═══════════════════════════════════════════════════════
ARCHETYPE_SIGNALS = {
    "LETTER": [
        "offer letter", "appointment", "relieving", "termination",
        "warning letter", "promotion", "increment", "noc",
        "experience letter", "internship offer"
    ],
    "CONTRACT": [
        "agreement", "contract", "nda", "mou", "terms of service",
        "data processing", "terms and conditions", "partnership"
    ],
    "POLICY": [
        "policy", "code of conduct", "handbook", "guidelines",
        "access control", "data protection", "vulnerability management"
    ],
    "REPORT": [
        "report", "assessment", "audit", "analysis", "postmortem",
        "root cause", "data breach", "incident report"
    ],
    "PROCESS": [
        "sop", "checklist", "runbook", "guide", "procedure",
        "change management", "onboarding sop", "offboarding"
    ],
    "PLAN": [
        "plan", "strategy", "roadmap", "proposal", "framework",
        "specification", "requirements", "backlog", "sprint",
        "architecture", "design", "brief", "playbook"
    ]
}

ARCHETYPE_TONE = {
    "LETTER": "professional, warm and welcoming — direct address to recipient",
    "CONTRACT": "precise and formal — unambiguous legal language, every clause intentional",
    "POLICY": "formal and structured — policy-driven, must/shall for obligations",
    "REPORT": "analytical and evidence-based — findings-first, data-driven",
    "PROCESS": "procedural and clear — step-based, action-oriented, role ownership",
    "PLAN": "strategic and forward-looking — goal-oriented, milestone-driven"
}

ARCHETYPE_FORMAT_HINT = {
    "LETTER": "Letterhead at top. Direct address. Compensation in table. Formal closing with signatory block.",
    "CONTRACT": "Numbered clauses (1., 1.1, 1.2). Definitions section. Obligations clear. Dual signature blocks.",
    "POLICY": "Numbered policy statements. Must/shall for mandatory. Should/may for recommended. Approval block.",
    "REPORT": "Executive summary first. Findings structured. Risk matrix if applicable. Recommendations. Sign-off.",
    "PROCESS": "Numbered sequential steps. Role per step. Decision points. Escalation path. Approval block.",
    "PLAN": "Objective first. Milestones and owners. KPIs. Risk factors. Approval block."
}

DEPARTMENT_TONE = {
    "human resources": "formal yet warm — clear, empathetic, professional",
    "legal": "precise and formal — strict, unambiguous, clause-based",
    "finance and accounting": "accurate and structured — number-driven, factual",
    "engineering": "technical and precise — structured, engineer audience",
    "it operations": "procedural and clear — action-oriented, step-based",
    "security and compliance": "formal and risk-aware — authoritative, compliance-focused",
    "customer success": "professional and client-friendly — solution-focused",
    "marketing": "strategic and engaging — audience-aware, persuasive",
    "product management": "strategic and cross-functional — business-technical balance",
    "quality assurance": "methodical and precise — evidence-based, process-driven"
}


def _detect_archetype(template_name: str) -> str:
    name = template_name.lower()
    for archetype, signals in ARCHETYPE_SIGNALS.items():
        if any(s in name for s in signals):
            return archetype
    return "PLAN"


def _is_long_document(template_name: str, section_count: int) -> bool:
    long_keywords = [
        "handbook", "strategy", "policy", "plan", "agreement",
        "contract", "architecture", "roadmap", "framework",
        "guide", "program", "playbook", "specification"
    ]
    return section_count >= 10 or any(k in template_name.lower() for k in long_keywords)


# ═══════════════════════════════════════════════════════
# LAYER 2 — SECTION INTELLIGENCE
# ═══════════════════════════════════════════════════════
SECTION_ROLE_MAP = {
    "HEADER": [
        "letterhead", "date", "title", "reference", "id",
        "version", "parties", "candidate", "company letterhead", "heading"
    ],
    "OPENER": [
        "purpose", "scope", "overview", "background",
        "executive summary", "introduction", "objective"
    ],
    "STRUCTURAL": [
        "definitions", "methodology", "classification",
        "types", "categories", "framework"
    ],
    "OBLIGATION": [
        "responsibilities", "obligations", "requirements",
        "policy", "rules", "clause", "compliance", "standards"
    ],
    "EVIDENCE": [
        "findings", "results", "assessment", "analysis",
        "metrics", "test", "defects", "vulnerability", "risk"
    ],
    "BODY": [
        "compensation", "breakdown", "details", "description",
        "content", "information", "terms", "conditions"
    ],
    "CLOSURE": [
        "recommendations", "next steps", "action items",
        "conclusion", "improvement", "mitigation"
    ],
    "SIGN_OFF": [
        "approval", "signature", "sign off", "acknowledgement",
        "authorization", "sign-off", "closure"
    ]
}

SECTION_DEPTH = {
    "HEADER": "concise — exact values only, 50-150 words",
    "OPENER": "clear and purposeful — 150-300 words",
    "STRUCTURAL": "precise definitions — 100-200 words per item",
    "OBLIGATION": "detailed and explicit — 300-600 words, numbered sub-points",
    "EVIDENCE": "data-driven and specific — 300-500 words, use table if applicable",
    "BODY": "detailed and substantial — 400-800 words",
    "CLOSURE": "actionable — 150-300 words with specific next steps",
    "SIGN_OFF": "formal block only — names, designations, date lines, 30-80 words"
}

TABLE_SECTION_SIGNALS = [
    "compensation", "breakdown", "ctc", "salary", "budget",
    "invoice", "pricing", "comparison", "metrics", "kpi",
    "test cases", "findings", "risk", "timeline", "schedule",
    "gross", "deductions", "earnings", "payment", "quotation",
    "bill", "purchase"
]


def _classify_section_role(section_name: str) -> str:
    name = section_name.lower()
    for role, signals in SECTION_ROLE_MAP.items():
        if any(s in name for s in signals):
            return role
    return "BODY"


def _section_needs_table(section_name: str) -> bool:
    name = section_name.lower()
    return any(s in name for s in TABLE_SECTION_SIGNALS)


def _role_to_content_type(role: str) -> str:
    return {
        "HEADER": "text",
        "OPENER": "text",
        "STRUCTURAL": "list",
        "OBLIGATION": "text",
        "EVIDENCE": "table",
        "BODY": "text",
        "CLOSURE": "list",
        "SIGN_OFF": "text"
    }.get(role, "text")


def _build_section_intelligence(sections: list) -> str:
    lines = []
    for i, section in enumerate(sections, 1):
        role = _classify_section_role(section.section_name)
        depth = SECTION_DEPTH.get(role, "detailed and professional")
        table_hint = " [USE TABLE FORMAT]" if _section_needs_table(section.section_name) else ""
        lines.append(
            f"{i}. {section.section_name}{table_hint}\n"
            f"   Role: {role} | Depth: {depth}"
        )
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════
# SYSTEM PROMPTS
# ═══════════════════════════════════════════════════════
DOCUMENT_SYSTEM_PROMPT = """You are DocForge, an advanced document generation engine for B2B SaaS businesses.
Generate premium-quality, comprehensive, polished business documents executive-ready for PDF/DOCX conversion.

CORE BEHAVIOR:
- Adapt tone, depth and structure based on document type and department
- HR documents: formal, warm, detailed
- Legal documents: strict, unambiguous, clause-based
- Finance documents: accurate, number-driven, structured tables
- Reports: analytical, evidence-based, findings-first
- Technical: precise, structured, engineer audience
- Plans/strategies: strategic, milestone-driven, goal-oriented

SECTION INTELLIGENCE:
- HEADER: concise, exact values, no elaboration
- BODY/OBLIGATION: detailed paragraphs, minimum 2-3 per section
- FINANCIAL sections: proper table with columns and data rows — NEVER use | pipe characters
- PROCESS sections: numbered steps with role ownership
- SIGN_OFF: formal block, names and designations only
- Never repeat content across sections

CONTENT RULES:
- Use ALL information provided in answers — never ignore provided values
- For table sections: generate actual data using provided values — never leave cells empty
- If a value is not provided: write "Not Provided" — never use [brackets] as placeholders
- Dates: use actual date format like "14 April 2026" — never write [DATE]
- Names: use exact names provided — never write [Name] or [Insert Name]
- Financial values: use exact figures provided — never write [Amount] or [Price]

FORMAT RULES — STRICTLY ENFORCED:
- DO NOT use ##, **, --, ***, or any markdown symbols anywhere
- Section headings are plain text only
- No pipe | characters for tables — use proper structured format
- No special characters, no smart quotes, no decorative formatting
- Content must be readable for both PDF and DOCX

OUTPUT: Start directly with document content. End with sign-off block."""


STRUCTURED_SYSTEM_PROMPT = """You are Doc-Forge, a document generation engine for B2B SaaS companies.
Output ONLY structured JSON — never plain text or markdown.
Today's date: {today}

SECTION RULES:
- HEADER: content_type "text", concise exact values, left alignment
- BODY/OBLIGATION: content_type "text", 2-3 substantial paragraphs, justify alignment
- FINANCIAL/COMPENSATION/INVOICE/PAYMENT: content_type "table", structured rows with actual data
- STEPS/LIST sections: content_type "list", numbered items
- SIGN_OFF: content_type "text", center alignment, formal block

CRITICAL — PLACEHOLDER RULE:
- NEVER use [brackets] for anything — no [DATE], [NAME], [Amount], [Insert anything]
- Use actual values from provided data
- If date missing: use today {today}
- If name missing: write "Not Provided"
- If amount missing: write "As agreed"
- Table cells must have actual content — never empty brackets

STRICT OUTPUT RULES:
1. Use ONLY information provided — no invention
2. No ##, no **, no markdown in any content value
3. No pipe | characters anywhere in content
4. UTF-8 safe characters only — no smart quotes
5. Every required section must appear in output
6. Return valid JSON only — nothing else
7. Tables must have real header row + real data rows"""


# ═══════════════════════════════════════════════════════
# CLEAN OUTPUT
# ═══════════════════════════════════════════════════════
def clean_output(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"#{1,6}\s*", "", text)
    text = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", text)
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`(.*?)`", r"\1", text)
    text = re.sub(r"^-{3,}$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^={3,}$", "", text, flags=re.MULTILINE)
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "--")
    text = re.sub(r"^\s*[-*]\s+", "- ", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ═══════════════════════════════════════════════════════
# PROMPT BUILDER
# ═══════════════════════════════════════════════════════
def build_prompt(
    db: Session,
    department_name: str,
    template_name: str,
    template_description: str,
    template_id: int,
    answers: Dict[str, str],
    company: Optional[Dict] = None
) -> str:

    sections = crud.get_sections_by_template(db, template_id)
    section_count = len(sections)
    archetype = _detect_archetype(template_name)
    is_long = _is_long_document(template_name, section_count)
    today = date.today().strftime("%d %B %Y")

    archetype_tone = ARCHETYPE_TONE.get(archetype, "professional and formal")
    dept_tone = DEPARTMENT_TONE.get(department_name.lower(), "professional and formal")
    tone = f"{archetype_tone}; {dept_tone}"
    format_hint = ARCHETYPE_FORMAT_HINT.get(archetype, "")
    section_intelligence = _build_section_intelligence(sections)

    if company:
        company_context = (
            f"Company: {company.get('name', 'Not specified')}\n"
            f"Industry: {company.get('industry', 'B2B SaaS')}\n"
            f"Size: {company.get('size', 'Not specified')}\n"
            f"Location: {company.get('location', 'India')}\n"
            f"Tone Preference: {company.get('tone', tone)}"
        )
    else:
        company_context = f"Company: India-based B2B SaaS\nTone: {tone}"

    answers_formatted = "\n".join([
        f"  {k}: {v}"
        for k, v in answers.items()
        if v and str(v).strip()
    ]) or "  No specific details provided — use professional defaults."

    length_note = (
        "Comprehensive document — full detailed content per section. "
        "Critical sections minimum 400 words. Supporting sections 150-300 words."
        if is_long else
        "Precise document — complete and professional per section."
    )

    prompt = f"""Today's date: {today}

{company_context}

Department: {department_name}
Document Type: {template_name}
Archetype: {archetype}
Purpose: {template_description}
Tone: {tone}
Format: {format_hint}

Required Sections ({section_count} total — ALL mandatory):
{section_intelligence}

ANSWERS PROVIDED — USE ALL OF THESE VALUES:
{answers_formatted}

CRITICAL RULES:
- Use every answer value provided above — do not ignore any
- Never use [brackets] as placeholders — use actual values or "Not Provided"
- Today's date is {today} — use this wherever date is needed
- For table sections: build proper table with actual data from answers above
- No ##, no **, no markdown — clean text only

{length_note}
Cover all {section_count} sections. Start with document title. End with sign-off block."""

    return prompt


# ═══════════════════════════════════════════════════════
# REGENERATE PROMPT
# ═══════════════════════════════════════════════════════
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
    base = build_prompt(
        db=db,
        department_name=department_name,
        template_name=template_name,
        template_description=template_description,
        template_id=template_id,
        answers=answers,
        company=company
    )
    if feedback:
        base += f"\n\nUser Feedback:\n{feedback}\n\nApply this. Keep all sections. Maintain tone."
    return base


# ═══════════════════════════════════════════════════════
# STRUCTURED PROMPT — fixed, no stray ] at end
# ═══════════════════════════════════════════════════════
def build_structured_prompt(
    db,
    department_name: str,
    template_name: str,
    template_description: str,
    template_id: int,
    answers: dict,
    company: dict = None
) -> str:
    import uuid

    today = date.today().strftime("%d %B %Y")
    sections = crud.get_sections_by_template(db, template_id)
    archetype = _detect_archetype(template_name)
    tone = DEPARTMENT_TONE.get(department_name.lower(), "professional and formal")
    company_name = company.get("name", "India-based B2B SaaS") if company else "India-based B2B SaaS"

    sections_schema = []
    for i, section in enumerate(sections, 1):
        role = _classify_section_role(section.section_name)
        content_type = _role_to_content_type(role)
        table_flag = " [MUST_BE_TABLE — use actual data from answers]" if _section_needs_table(section.section_name) else ""
        sections_schema.append(
            f'{i}. "{section.section_name}" | role:{role} | type:{content_type}{table_flag}'
        )
    sections_list = "\n".join(sections_schema)

    # Format answers strictly — show all values
    answers_lines = []
    for k, v in answers.items():
        val = v if v and str(v).strip() else "Not Provided"
        answers_lines.append(f"  {k}: {val}")
    answers_formatted = "\n".join(answers_lines) if answers_lines else "  No details provided."

    generation_id = str(uuid.uuid4())

    return f"""Generate {template_name} for {company_name}.

Today's date: {today}
Company: {company_name}
Department: {department_name}
Archetype: {archetype}
Tone: {tone}
Purpose: {template_description}

Required sections ({len(sections)} total — ALL mandatory in order):
{sections_list}

Variable data — USE ALL THESE VALUES (critical — do not ignore):
{answers_formatted}

CRITICAL RULES:
1. NEVER use [brackets] as placeholders — use actual values above or "Not Provided"
2. For table sections: build real table using actual data from answers — no empty bracket cells
3. Today's date is {today} — use this for any date field
4. Every section must have substantial content — no "Content to be provided"
5. Financial/invoice tables must have real rows with actual values from answers

Return ONLY this JSON (no text before or after, no markdown):
{{
  "document_metadata": {{
    "department": "{department_name}",
    "doc_type": "{template_name}",
    "generated_date": "{today}",
    "company": "{company_name}",
    "generation_id": "{generation_id}"
  }},
  "sections": [
    {{
      "id": "section_1",
      "heading": "exact section name — no symbols",
      "content_type": "text or table or list",
      "content": "string for text, array of cell objects for table, array of strings for list",
      "styling": {{
        "alignment": "left or center or justify",
        "font_weight": "normal",
        "page_break_after": false
      }},
      "word_count": 0
    }}
  ],
  "validation_status": "verified"
}}

Table format (use for financial/invoice/pricing sections):
"content": [
  {{"cells": ["Description", "Quantity", "Unit Price", "Total"]}},
  {{"cells": ["[actual item from answers]", "[actual qty]", "[actual price]", "[actual total]"]}}
]
CRITICAL CONTENT DEPTH RULES:
- OPENER/BACKGROUND sections: minimum 150 words — full paragraphs
- BODY/OBLIGATION sections: minimum 250-900 words — detailed content
- EVIDENCE sections: use table with real data rows from answers
- HEADER: compact, exact values only (name, date, ref no)
- SIGN_OFF: formal block, 60-80 words max
- Every section must feel complete — no filler phrases like "as mentioned above"""


# ═══════════════════════════════════════════════════════
# MAIN GENERATE
# ═══════════════════════════════════════════════════════
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

    cache_key = _make_cache_key(
        department_name, template_name,
        template_id, answers, feedback, company
    )

    if cache_key in _document_cache:
        return _document_cache[cache_key]

    prompt = build_regenerate_prompt(
        db=db,
        department_name=department_name,
        template_name=template_name,
        template_description=template_description,
        template_id=template_id,
        answers=answers,
        feedback=feedback,
        company=company
    )

    response = llm_service.generate_with_llm(
        prompt,
        system_prompt=DOCUMENT_SYSTEM_PROMPT
    )

    cleaned = clean_output(response)
    _document_cache[cache_key] = cleaned
    return cleaned