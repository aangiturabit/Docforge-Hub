
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
    raw = (
        f"{department_name}:{template_name}:{template_id}:"
        f"{json.dumps(sorted_answers)}:{feedback or ''}:{company_part}"
    )
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
    "LETTER":   "professional, warm and welcoming — direct address to recipient",
    "CONTRACT": "precise and formal — unambiguous legal language, every clause intentional",
    "POLICY":   "formal and structured — policy-driven, must/shall for obligations",
    "REPORT":   "analytical and evidence-based — findings-first, data-driven",
    "PROCESS":  "procedural and clear — step-based, action-oriented, role ownership",
    "PLAN":     "strategic and forward-looking — goal-oriented, milestone-driven"
}

ARCHETYPE_FORMAT_HINT = {
    "LETTER":   "Letterhead at top. Direct address to named recipient. Compensation in table. Formal closing with signatory block.",
    "CONTRACT": "Numbered clauses (1., 1.1, 1.2). Definitions section. Obligations explicit. Dual signature blocks.",
    "POLICY":   "Numbered policy statements. Must/shall for mandatory. Should/may for recommended. Approval block.",
    "REPORT":   "Executive summary first. Findings structured. Risk matrix if applicable. Recommendations. Sign-off.",
    "PROCESS":  "Numbered sequential steps. Role per step. Decision points. Escalation path. Approval block.",
    "PLAN":     "Objective first. Milestones and owners. KPIs. Risk factors. Approval block."
}

DEPARTMENT_TONE = {
    "human resources":          "formal yet warm — clear, empathetic, professional",
    "legal":                    "precise and formal — strict, unambiguous, clause-based",
    "finance and accounting":   "accurate and structured — number-driven, factual",
    "engineering":              "technical and precise — structured, engineer audience",
    "it operations":            "procedural and clear — action-oriented, step-based",
    "security and compliance":  "formal and risk-aware — authoritative, compliance-focused",
    "customer success":         "professional and client-friendly — solution-focused",
    "marketing":                "strategic and engaging — audience-aware, persuasive",
    "product management":       "strategic and cross-functional — business-technical balance",
    "quality assurance":        "methodical and precise — evidence-based, process-driven"
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
    "HEADER":     "concise — exact values only, 50-150 words",
    "OPENER":     "clear and purposeful — 180-350 words, 3-4 full paragraphs",
    "STRUCTURAL": "precise definitions — 100-200 words per item, minimum 4 items",
    "OBLIGATION": "detailed and explicit — 300-650 words, numbered sub-points with must/shall",
    "EVIDENCE":   "data-driven and specific — 250-500 words, use table if applicable",
    "BODY":       "detailed and substantial — 300-800 words, full paragraphs",
    "CLOSURE":    "actionable — 150-350 words with specific next steps, owner, timeline",
    "SIGN_OFF":   "formal block only — names, designations, date lines, 40-100 words"
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


def _role_to_content_type(role: str, section_name: str = "") -> str:
    if _section_needs_table(section_name):
        return "table"
    return {
        "HEADER":     "text",
        "OPENER":     "text",
        "STRUCTURAL": "list",
        "OBLIGATION": "text",
        "EVIDENCE":   "table",
        "BODY":       "text",
        "CLOSURE":    "list",
        "SIGN_OFF":   "text"
    }.get(role, "text")


def _build_section_intelligence(sections: list) -> str:
    lines = []
    for i, section in enumerate(sections, 1):
        role = _classify_section_role(section.section_name)
        depth = SECTION_DEPTH.get(role, "detailed and professional")
        table_hint = " [MUST USE TABLE FORMAT WITH REAL DATA ROWS]" if _section_needs_table(section.section_name) else ""
        lines.append(
            f"{i}. {section.section_name}{table_hint}\n"
            f"   Role: {role} | Depth: {depth}"
        )
    return "\n".join(lines)


def _format_answers_for_prompt(answers: dict) -> str:
    """
    Format answers for injection into prompts.
    Shows ALL keys, marks blanks as 'Not Provided' explicitly.
    """
    if not answers:
        return "  No specific details provided — use professional defaults."
    lines = []
    for k, v in answers.items():
        val = str(v).strip() if v and str(v).strip() else "Not Provided"
        lines.append(f"  {k}: {val}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════
# SYSTEM PROMPTS
# ═══════════════════════════════════════════════════════
DOCUMENT_SYSTEM_PROMPT = """You are DocForge, an advanced document generation engine for B2B SaaS businesses.
Generate premium-quality, comprehensive, polished business documents — executive-ready for PDF/DOCX conversion.
Today's date: {today}

ABSOLUTE RULES — NEVER VIOLATE:
1. NEVER use [brackets] as placeholders — no [DATE], [NAME], [Company Name], [Amount], [Insert anything]
2. Use exact values provided in the variable data
3. If a value is genuinely not provided, write "Not Provided" — never a bracket
4. Use today's date {today} for any date field that is not explicitly provided
5. No ## no ** no -- no markdown symbols anywhere in content
6. No pipe | characters in text content (tables are handled separately)
7. UTF-8 safe characters only

TONE BY DOCUMENT TYPE:
- HR documents: formal, warm, detailed — direct address to named recipient
- Legal/Contract: strict, unambiguous, clause-based — numbered sub-clauses
- Finance: accurate, number-driven, all values from provided data
- Reports: analytical, evidence-based, findings-first
- Technical: precise, structured, engineer audience
- Plans/Strategies: strategic, milestone-driven, goal-oriented

SECTION WRITING RULES:
- HEADER: exact values only — date, names, reference number, company, designation
- OPENER/INTRODUCTION: 3-4 full paragraphs — purpose, context, scope, importance
- BODY/OBLIGATION sections: minimum 300 words — 3+ detailed paragraphs
- FINANCIAL sections (compensation, salary, invoice, pricing): ALWAYS a table with real column headers and real data rows
- PROCESS sections: numbered steps with role and action
- CLOSURE/RECOMMENDATIONS: specific actions with owner and timeline
- SIGN_OFF: formal block with actual names and designation — compact

CONTENT QUALITY RULES:
- Use ALL provided variable data — do not ignore any supplied value
- Every section must feel complete and professionally written
- No filler phrases: "as mentioned above", "as previously stated", "it is important to note"
- No redundancy across sections
- Financial tables must have real monetary values, not "As agreed" unless value is genuinely absent

OUTPUT: Start directly with document content. No preamble. End with sign-off block."""


STRUCTURED_SYSTEM_PROMPT = """You are DocForge, a structured document generation engine for B2B SaaS companies.
Output ONLY valid JSON — never plain text or markdown outside JSON values.
Today's date: {today}

ABSOLUTE PLACEHOLDER RULE — THIS IS CRITICAL:
- NEVER use [brackets] anywhere — no [DATE], [NAME], [Company Name], [Amount], [Insert X], [Add X]
- Use the exact values from the variable data provided
- For any date field: use {today} if no specific date was given
- For any missing name: write "Not Provided"
- For any missing amount: write "As per agreement" — NEVER [Amount] or [Price]
- Table cells MUST have real content — never empty or bracket placeholders

SECTION TYPE RULES:
- HEADER sections: content_type "text", left alignment, compact, exact values
- OPENER/INTRODUCTION/BACKGROUND: content_type "text", justify alignment, 180-350 words, 3-4 paragraphs
- BODY/OBLIGATION/RESPONSIBILITIES: content_type "text", justify alignment, 300-700 words
- FINANCIAL/COMPENSATION/SALARY/INVOICE/PAYMENT/PRICING: content_type "table", real header row + real data rows
- DEFINITIONS/STEPS/RECOMMENDATIONS: content_type "list", minimum 4 items
- SIGN_OFF/APPROVAL/SIGNATURE: content_type "text", center alignment, 40-100 words

TABLE FORMAT — REQUIRED STRUCTURE:
"content": [
  {{"cells": ["Column Header 1", "Column Header 2", "Column Header 3"]}},
  {{"cells": ["Actual Data Value", "Actual Data Value", "Actual Data Value"]}},
  {{"cells": ["Actual Data Value", "Actual Data Value", "Actual Data Value"]}}
]
- Minimum 1 header row + 1 data row (2 rows total)
- All cell values must be real, meaningful content
- No pipe | characters in cell values

STRICT OUTPUT RULES:
1. Return ONLY valid JSON — nothing before or after the JSON object
2. No ##, no **, no markdown formatting in any content string
3. Every required section must be present in the sections array
4. Sections must be in the exact order specified in the prompt
5. Every content string must be substantially written — no stub content
6. word_count field must be an integer (approximate is fine)"""


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
# PROMPT BUILDER — plain text generation
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
    effective_tone = f"{archetype_tone}; {dept_tone}"
    format_hint = ARCHETYPE_FORMAT_HINT.get(archetype, "")
    section_intelligence = _build_section_intelligence(sections)

    if company:
        company_context = (
            f"Company: {company.get('name', 'Not specified')}\n"
            f"Industry: {company.get('industry', 'B2B SaaS')}\n"
            f"Size: {company.get('size', 'Not specified')}\n"
            f"Location: {company.get('location', 'India')}\n"
            f"Tone Preference: {company.get('tone', effective_tone)}"
        )
        final_tone = company.get("tone", effective_tone)
    else:
        company_context = f"Company: India-based B2B SaaS\nTone: {effective_tone}"
        final_tone = effective_tone

    answers_formatted = _format_answers_for_prompt(answers)

    length_note = (
        "COMPREHENSIVE DOCUMENT: Every section must be fully written.\n"
        "- Critical sections (BODY, OBLIGATION, EVIDENCE): minimum 400 words each\n"
        "- Supporting sections (OPENER, CLOSURE): minimum 200 words each\n"
        "- HEADER and SIGN_OFF: compact and factual"
        if is_long else
        "PRECISE DOCUMENT: Every section must be complete and professional.\n"
        "- Content sections: minimum 250 words each\n"
        "- HEADER and SIGN_OFF: compact and factual"
    )

    prompt = f"""Today's date: {today}

{company_context}

Department: {department_name}
Document Type: {template_name}
Archetype: {archetype}
Purpose: {template_description}
Tone: {final_tone}
Format Guidelines: {format_hint}

Required Sections ({section_count} total — ALL mandatory, in this order):
{section_intelligence}

VARIABLE DATA — USE ALL OF THESE VALUES IN THE DOCUMENT:
{answers_formatted}

CRITICAL RULES:
1. Use every provided value above — do not ignore any supplied data
2. NEVER use [brackets] as placeholders — use real values or write "Not Provided"
3. Today's date is {today} — use this wherever date is needed
4. For table sections: build proper table using actual values from variable data
5. No ##, no **, no markdown — clean plain text only . 
no Approval section should be unfilled or with placeholder text like "Approver Name", "Date", "Signature" etc. if the relevant data is not provided, fill according to document context  dont write "Not Provided" strictly.
6. Every section must be substantively written — no stub content

{length_note}

Generate all {section_count} sections. Start immediately with document content. End with sign-off block."""

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
        base += (
            f"\n\nUSER FEEDBACK TO APPLY:\n{feedback}\n\n"
            "Apply the feedback above. Keep all sections. Maintain professional tone."
        )
    return base


# ═══════════════════════════════════════════════════════
# STRUCTURED PROMPT — for JSON generation
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
    dept_tone = DEPARTMENT_TONE.get(department_name.lower(), "professional and formal")
    arch_tone = ARCHETYPE_TONE.get(archetype, "professional and formal")

    company_name = company.get("name", "Not specified") if company else "Not specified"
    final_tone   = (company.get("tone", f"{arch_tone}; {dept_tone}") if company
                    else f"{arch_tone}; {dept_tone}")

    # Build per-section schema with depth hints
    sections_schema = []
    for i, section in enumerate(sections, 1):
        role = _classify_section_role(section.section_name)
        content_type = _role_to_content_type(role, section.section_name)
        depth = SECTION_DEPTH.get(role, "detailed and professional")

        if _section_needs_table(section.section_name):
            extra = (
                " [TABLE REQUIRED — build real rows from variable data above. "
                "Minimum: 1 header row + data rows] give addition to the table if document content needs more data to fill the table."
            )
        else:
            extra = ""

        sections_schema.append(
            f'{i}. "{section.section_name}"\n'
            f'   role: {role} | content_type: {content_type} | depth: {depth}{extra}'
        )
    sections_list = "\n".join(sections_schema)

    answers_formatted = _format_answers_for_prompt(answers)
    generation_id = str(uuid.uuid4())

    # Build a concrete example table if any table sections exist
    table_sections = [s for s in sections if _section_needs_table(s.section_name)]
    table_example_note = ""
    if table_sections:
        table_example_note = f"""
TABLE CONSTRUCTION EXAMPLE for '{table_sections[0].section_name}':
this might be vary according to the variable data.
If variable data contains: salary = 50000, hra = 20000, ctc = 840000
Then build:
"content": [
  {{"cells": ["Component", "Monthly (INR)", "Annual (INR)"]}},
  {{"cells": ["Basic Salary", "50,000", "6,00,000"]}},
  {{"cells": ["House Rent Allowance", "20,000", "2,40,000"]}},
  {{"cells": ["Total CTC", "--", "8,40,000"]}}
]
Apply the same principle using the actual values from the variable data for your documents according to different scenarios.
"""

    return f"""Generate a complete {template_name} document for {company_name}.

DOCUMENT CONTEXT:
- Today's Date: {today}
- Company: {company_name}
- Department: {department_name}
- Document Type: {template_name}
- Archetype: {archetype}
- Tone: {final_tone}
- Purpose: {template_description}

REQUIRED SECTIONS — ALL {len(sections)} MUST BE PRESENT, IN THIS EXACT ORDER:
{sections_list}

VARIABLE DATA — EMBED ALL APPLICABLE VALUES IN THE DOCUMENT:
{answers_formatted}

PLACEHOLDER RULE (CRITICAL — READ CAREFULLY):
- NEVER write [brackets] anywhere in the JSON output
- Use the exact values from variable data above
- If today's date is needed: use {today}
- If a name is missing: write "Not Provided" (not [Name])
- If an amount is missing: write "As per agreement" (not [Amount])
- Table cells must ALWAYS have real text — never empty or brackets
{table_example_note}

CONTENT DEPTH REQUIREMENTS:
- OPENER / INTRODUCTION / BACKGROUND: minimum 180 words, 3-4 full paragraphs
- BODY / OBLIGATION / RESPONSIBILITIES: minimum 300 words, detailed
- EVIDENCE / ASSESSMENT: table with real data + minimum 150 words of text
- HEADER: compact, 50-150 words, exact values only
- SIGN_OFF: formal block, 40-100 words max

Return ONLY this JSON structure (no text before or after, no markdown):
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
      "heading": "Exact Section Name",
      "content_type": "text",
      "content": "Fully written content string here — no placeholders, no brackets",
      "styling": {{
        "alignment": "justify",
        "font_weight": "normal",
        "page_break_after": false
      }},
      "word_count": 0
    }}
  ],
  "validation_status": "verified"
}}

For list sections, content is an array of strings:
"content": ["Item one fully written", "Item two fully written", "Item three fully written"]

For table sections, content is an array of row objects:
"content": [
  {{"cells": ["Header 1", "Header 2", "Header 3"]}},
  {{"cells": ["Real
    Value 1", "Real Value 2", "Real Value 3"]}}
]

FINAL CHECK BEFORE OUTPUTTING:
- Are all {len(sections)} sections present? 
- Do all table sections have header row + at least 1 data row with real values?
- Are there zero [bracket] placeholders anywhere?
- Is the content substantive and professionally written?
If any answer is no, fix it before outputting."""


# ═══════════════════════════════════════════════════════
# MAIN GENERATE (plain text — for preview)
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

    today = date.today().strftime("%d %B %Y")

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

    system = DOCUMENT_SYSTEM_PROMPT.replace("{today}", today)

    response = llm_service.generate_with_llm(
        prompt,
        system_prompt=system
    )

    cleaned = clean_output(response)
    _document_cache[cache_key] = cleaned
    return cleaned