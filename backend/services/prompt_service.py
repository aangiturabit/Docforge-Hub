
"""
backend/services/prompt_service.py
─────────────────────────────────────────────────────
Builds all LLM prompts.

Responsibilities
────────────────
• build_prompt            — plain-text generation prompt (used by preview_document)
• build_structured_prompt — JSON generation prompt (used by generate_structured_document)
• build_regenerate_prompt — plain-text regen prompt (with optional feedback)
• STRUCTURED_SYSTEM_PROMPT / DOCUMENT_SYSTEM_PROMPT — consumed by callers

Has NO generation, NO DB writes — pure prompt construction only.

Changes from previous version
──────────────────────────────
• build_structured_prompt and build_prompt now accept `sections` as a pre-fetched
  list instead of querying the DB themselves with `db` + `template_id`.
  The caller (document_service) fetches sections once and passes them in.
  This eliminates a redundant DB round-trip per generation / preview call.
• table_example_note replaced with _build_dynamic_table_example() which reads
  the actual first table section name and the actual answers keys to produce a
  context-specific example — prevents LLM from assuming every table is salary-based.
• generation_id removed from the prompt body. It was echoed back by the LLM
  but served no deduplication or idempotency purpose. document_service now
  injects it into document_metadata after generation so the LLM never sees it.
• answers_to_context imported from text_utils — single canonical implementation.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from backend.database import crud
from backend.services.section_utils import (
    SECTION_DEPTH_HINT,
    classify_section_role,
    role_to_content_type,
    section_needs_table,
)
from backend.services.text_utils import answers_to_context
from backend.utils.logger import get_logger

logger = get_logger("docforge.services.prompt")


# ═══════════════════════════════════════════════════════
# ARCHETYPE DETECTION
# ═══════════════════════════════════════════════════════

_ARCHETYPE_SIGNALS: dict[str, list[str]] = {
    "LETTER": [
        "offer letter", "appointment", "relieving", "termination",
        "warning letter", "promotion", "increment", "noc",
        "experience letter", "internship offer",
    ],
    "CONTRACT": [
        "agreement", "contract", "nda", "mou", "terms of service",
        "data processing", "terms and conditions", "partnership",
    ],
    "POLICY": [
        "policy", "code of conduct", "handbook", "guidelines",
        "access control", "data protection", "vulnerability management",
    ],
    "REPORT": [
        "report", "assessment", "audit", "analysis", "postmortem",
        "root cause", "data breach", "incident report",
    ],
    "PROCESS": [
        "sop", "checklist", "runbook", "guide", "procedure",
        "change management", "onboarding sop", "offboarding",
    ],
    "PLAN": [
        "plan", "strategy", "roadmap", "proposal", "framework",
        "specification", "requirements", "backlog", "sprint",
        "architecture", "design", "brief", "playbook",
    ],
}

_ARCHETYPE_TONE: dict[str, str] = {
    "LETTER":   "professional, warm and welcoming — direct address to recipient",
    "CONTRACT": "precise and formal — unambiguous legal language, every clause intentional",
    "POLICY":   "formal and structured — policy-driven, must/shall for obligations",
    "REPORT":   "analytical and evidence-based — findings-first, data-driven",
    "PROCESS":  "procedural and clear — step-based, action-oriented, role ownership",
    "PLAN":     "strategic and forward-looking — goal-oriented, milestone-driven",
}

_ARCHETYPE_FORMAT_HINT: dict[str, str] = {
    "LETTER":   "Letterhead at top. Direct address to named recipient. Compensation in table. Formal closing with signatory block.",
    "CONTRACT": "Numbered clauses (1., 1.1, 1.2). Definitions section. Obligations explicit. Dual signature blocks.",
    "POLICY":   "Numbered policy statements. Must/shall for mandatory. Should/may for recommended. Approval block.",
    "REPORT":   "Executive summary first. Findings structured. Risk matrix if applicable. Recommendations. Sign-off.",
    "PROCESS":  "Numbered sequential steps. Role per step. Decision points. Escalation path. Approval block.",
    "PLAN":     "Objective first. Milestones and owners. KPIs. Risk factors. Approval block.",
}

_DEPARTMENT_TONE: dict[str, str] = {
    "human resources":         "formal yet warm — clear, empathetic, professional",
    "legal":                   "precise and formal — strict, unambiguous, clause-based",
    "finance and accounting":  "accurate and structured — number-driven, factual",
    "engineering":             "technical and precise — structured, engineer audience",
    "it operations":           "procedural and clear — action-oriented, step-based",
    "security and compliance": "formal and risk-aware — authoritative, compliance-focused",
    "customer success":        "professional and client-friendly — solution-focused",
    "marketing":               "strategic and engaging — audience-aware, persuasive",
    "product management":      "strategic and cross-functional — business-technical balance",
    "quality assurance":       "methodical and precise — evidence-based, process-driven",
}


def _detect_archetype(template_name: str) -> str:
    name = template_name.lower()
    for archetype, signals in _ARCHETYPE_SIGNALS.items():
        if any(s in name for s in signals):
            return archetype
    return "PLAN"


def _is_long_document(template_name: str, section_count: int) -> bool:
    long_keywords = [
        "handbook", "strategy", "policy", "plan", "agreement",
        "contract", "architecture", "roadmap", "framework",
        "guide", "program", "playbook", "specification",
    ]
    return section_count >= 10 or any(k in template_name.lower() for k in long_keywords)


# ═══════════════════════════════════════════════════════
# SECTION INTELLIGENCE
# ═══════════════════════════════════════════════════════

def _build_section_intelligence(sections: list) -> str:
    lines = []
    for i, section in enumerate(sections, 1):
        role  = classify_section_role(section.section_name)
        depth = SECTION_DEPTH_HINT.get(role, "detailed and professional")
        table_hint = (
            " [MUST USE TABLE FORMAT WITH REAL DATA ROWS]"
            if section_needs_table(section.section_name) else ""
        )
        lines.append(
            f"{i}. {section.section_name}{table_hint}\n"
            f"   Role: {role} | Depth: {depth}"
        )
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════
# DYNAMIC TABLE EXAMPLE 
# ═══════════════════════════════════════════════════════

def _build_dynamic_table_example(
    table_sections: list,
    answers: dict,
) -> str:
    """
    Generate a context-specific table example based on the actual first table
    section in this document and the actual answer keys provided.

    This prevents the LLM from:
    - Assuming every table is a salary/compensation table
    - Copying the same structure on every generation
    - Ignoring non-HR table types (invoices, risk matrices, timelines, etc.)

    If no table sections exist, returns an empty string.
    """
    if not table_sections:
        return ""

    section = table_sections[0]
    name    = section.section_name
    lower   = name.lower()

    # Determine column structure from the section type
    if any(k in lower for k in ["compensation", "salary", "ctc", "earnings", "gross", "payroll"]):
        available = {
            k: v for k, v in (answers or {}).items()
            if any(kw in k.lower() for kw in ["salary", "ctc", "hra", "allowance", "basic"])
            and v
        }
        if available:
            rows = ["  {\"cells\": [\"Component\", \"Amount\", \"Frequency\"]}"]
            for k, v in list(available.items())[:3]:
                label = k.replace("_", " ").title()
                rows.append(f"  {{\"cells\": [\"{label}\", \"{v}\", \"Monthly\"]}}")
            data_block = ",\n".join(rows)
        else:
            data_block = (
                "  {\"cells\": [\"Component\", \"Amount\", \"Frequency\"]},\n"
                "  {\"cells\": [\"Basic Salary\", \"<value from answers>\", \"Monthly\"]},\n"
                "  {\"cells\": [\"Total CTC\", \"<value from answers>\", \"Annual\"]}"
            )

    elif any(k in lower for k in ["risk", "finding", "vulnerability", "issue", "defect"]):
        available_sev  = answers.get("severity", "<severity from answers>") if answers else "<severity>"
        available_stat = answers.get("status",   "<status from answers>")   if answers else "<status>"
        data_block = (
            "  {\"cells\": [\"Item\", \"Description\", \"Severity\", \"Status\"]},\n"
            f"  {{\"cells\": [\"Finding 1\", \"<finding from answers>\", \"{available_sev}\", \"{available_stat}\"]}}"
        )

    elif any(k in lower for k in ["invoice", "pricing", "quotation", "bill", "purchase", "cost"]):
        available_desc  = answers.get("item_description", "<item from answers>") if answers else "<item>"
        available_price = answers.get("unit_price",       "<price from answers>") if answers else "<price>"
        data_block = (
            "  {\"cells\": [\"Description\", \"Quantity\", \"Unit Price\", \"Total\"]},\n"
            f"  {{\"cells\": [\"{available_desc}\", \"1\", \"{available_price}\", \"{available_price}\"]}}"
        )

    elif any(k in lower for k in ["timeline", "schedule", "milestone", "plan", "roadmap"]):
        data_block = (
            "  {\"cells\": [\"Phase\", \"Activity\", \"Owner\", \"Due Date\"]},\n"
            "  {\"cells\": [\"Phase 1\", \"<activity from answers>\", \"<owner from answers>\", \"<date from answers>\"]}"
        )

    elif any(k in lower for k in ["metric", "kpi", "performance", "target", "result"]):
        data_block = (
            "  {\"cells\": [\"Metric\", \"Target\", \"Actual\", \"Status\"]},\n"
            "  {\"cells\": [\"<metric from answers>\", \"<target from answers>\", \"<actual from answers>\", \"On Track\"]}"
        )

    else:
        # Generic fallback — uses whatever keys are in answers
        available = list((answers or {}).keys())[:2]
        if len(available) >= 2:
            v1 = answers.get(available[0], "<value>")
            v2 = answers.get(available[1], "<value>")
            col1 = available[0].replace("_", " ").title()
            col2 = available[1].replace("_", " ").title()
            data_block = (
                f"  {{\"cells\": [\"{col1}\", \"{col2}\", \"Status\"]}},\n"
                f"  {{\"cells\": [\"{v1}\", \"{v2}\", \"Active\"]}}"
            )
        else:
            data_block = (
                "  {\"cells\": [\"Item\", \"Details\", \"Status\"]},\n"
                "  {\"cells\": [\"<item from answers>\", \"<detail from answers>\", \"Active\"]}"
            )

    return (
        f"\nTABLE CONSTRUCTION EXAMPLE for '{name}':\n"
        "Build your table using the actual values from variable data above.\n"
        "Example structure (column names and values must match your document):\n"
        "\"content\": [\n"
        f"{data_block}\n"
        "]\n"
        "IMPORTANT: Do not copy this example literally — "
        "use the actual values and column names relevant to THIS document.\n"
    )


# ═══════════════════════════════════════════════════════
# SYSTEM PROMPTS
# ═══════════════════════════════════════════════════════

DOCUMENT_SYSTEM_PROMPT = """You are DocForge, an advanced document generation engine for B2B SaaS businesses.
Generate premium-quality, comprehensive, polished business documents — executive-ready for PDF/DOCX conversion.
Today's date: {today}

ABSOLUTE RULES — NEVER VIOLATE:
1. NEVER use [brackets] as placeholders — no [DATE], [NAME], [Company Name], [Amount], [Insert anything]
2. Use exact values provided in the variable data
3. If a value is genuinely not provided, write a contextually appropriate phrase — NEVER write "Not Provided"
4. Use today's date {today} for any date field not explicitly provided
5. No ## no ** no -- no markdown symbols anywhere in content
6. No pipe | characters in text content (tables are handled separately)
7. UTF-8 safe characters only

TONE BY DOCUMENT TYPE:
- HR documents:      formal, warm, detailed — direct address to named recipient
- Legal/Contract:    strict, unambiguous, clause-based — numbered sub-clauses
- Finance:           accurate, number-driven, all values from provided data
- Reports:           analytical, evidence-based, findings-first
- Technical:         precise, structured, engineer audience
- Plans/Strategies:  strategic, milestone-driven, goal-oriented

SECTION WRITING RULES:
- HEADER:           exact values only — date, names, reference number, company, designation
- OPENER/INTRO:     3-4 full paragraphs — purpose, context, scope, importance
- BODY/OBLIGATION:  minimum 300 words — 3+ detailed paragraphs
- FINANCIAL/TABLE:  ALWAYS a table with real column headers and real data rows
- PROCESS:          numbered steps with role and action
- CLOSURE:          specific actions with owner and timeline
- SIGN_OFF:         formal block with actual names and designation — compact

OUTPUT: Start directly with document content. No preamble. End with sign-off block."""


STRUCTURED_SYSTEM_PROMPT = """You are DocForge, a structured document generation engine for B2B SaaS companies.
Output ONLY valid JSON — never plain text or markdown outside JSON values.
Today's date: {today}

ABSOLUTE PLACEHOLDER RULE — CRITICAL:
- NEVER use [brackets] anywhere — no [DATE], [NAME], [Company Name], [Amount], [Insert X]
- Use exact values from the variable data provided
- For any date field: use {today} if no specific date was given
- For any missing value: write a contextually appropriate phrase — NEVER write "Not Provided"
- Table cells MUST have real content — never empty or bracket placeholders

SECTION TYPE RULES:
- HEADER:               content_type "text",  left alignment,    compact, exact values
- OPENER/INTRODUCTION:  content_type "text",  justify alignment, 180-350 words, 3-4 paragraphs
- BODY/OBLIGATION:      content_type "text",  justify alignment, 300-700 words
- FINANCIAL/TABLE sections: content_type "table", real header row + real data rows
- DEFINITIONS/STEPS:   content_type "list",  minimum 4 items
- SIGN_OFF/APPROVAL:   content_type "text",  center alignment,  40-100 words

TABLE FORMAT — REQUIRED STRUCTURE:
"content": [
  {{"cells": ["Column Header 1", "Column Header 2", "Column Header 3"]}},
  {{"cells": ["Actual Data Value", "Actual Data Value", "Actual Data Value"]}}
]
- Minimum 1 header row + 1 data row
- All cell values must be real, meaningful content from the variable data
- No pipe | characters in cell values

STRICT OUTPUT RULES:
1. Return ONLY valid JSON — nothing before or after the JSON object
2. No ##, no **, no markdown formatting in any content string
3. Every required section must be present in the sections array
4. Sections must be in the exact order specified in the prompt
5. Every content string must be substantially written — no stub content
6. word_count must be an integer"""


# ═══════════════════════════════════════════════════════
# PLAIN-TEXT PROMPT  (preview_document)
# ═══════════════════════════════════════════════════════

def build_prompt(
    sections: list,
    department_name: str,
    template_name: str,
    template_description: str,
    answers: Dict[str, str],
    company: Optional[Dict] = None,
) -> str:
    """
    Build the plain-text generation prompt.

    Parameters
    ----------
    sections : list
        Pre-fetched section ORM objects. Caller is responsible for fetching
        via crud.get_sections_by_template — no DB call made here.
    """
    section_count = len(sections)
    archetype     = _detect_archetype(template_name)
    is_long       = _is_long_document(template_name, section_count)
    today         = date.today().strftime("%d %B %Y")

    arch_tone  = _ARCHETYPE_TONE.get(archetype, "professional and formal")
    dept_tone  = _DEPARTMENT_TONE.get(department_name.lower(), "professional and formal")
    final_tone = (company or {}).get("tone", f"{arch_tone}; {dept_tone}")
    fmt_hint   = _ARCHETYPE_FORMAT_HINT.get(archetype, "")

    company_context = (
        f"Company: {company.get('name', 'Not specified')}\n"
        f"Industry: {company.get('industry', 'B2B SaaS')}\n"
        f"Size: {company.get('size', 'Not specified')}\n"
        f"Location: {company.get('location', 'India')}\n"
        f"Tone Preference: {final_tone}"
        if company else
        f"Company: India-based B2B SaaS\nTone: {final_tone}"
    )

    section_intelligence = _build_section_intelligence(sections)
    answers_formatted    = answers_to_context(answers)

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

    logger.debug(
        "build_prompt | template=%r archetype=%s sections=%d",
        template_name, archetype, section_count,
    )

    return f"""Today's date: {today}

{company_context}

Department: {department_name}
Document Type: {template_name}
Archetype: {archetype}
Purpose: {template_description}
Tone: {final_tone}
Format Guidelines: {fmt_hint}

Required Sections ({section_count} total — ALL mandatory, in this order):
{section_intelligence}

VARIABLE DATA — USE ALL OF THESE VALUES IN THE DOCUMENT:
{answers_formatted}

CRITICAL RULES:
1. Use every provided value — do not ignore any supplied data
2. NEVER use [brackets] — use real values or a contextually appropriate phrase
3. NEVER write 'Not Provided' — infer from document context if a value is absent
4. Today's date is {today} — use this wherever a date is needed
5. Table sections: build proper table using actual values from variable data
6. No ##, no **, no markdown — clean plain text only

{length_note}

Generate all {section_count} sections. Start immediately with document content. End with sign-off block."""


# ═══════════════════════════════════════════════════════
# REGENERATE PROMPT
# ═══════════════════════════════════════════════════════

def build_regenerate_prompt(
    sections: list,
    department_name: str,
    template_name: str,
    template_description: str,
    answers: Dict[str, str],
    feedback: Optional[str] = None,
    company: Optional[Dict] = None,
) -> str:
    base = build_prompt(
        sections=sections,
        department_name=department_name,
        template_name=template_name,
        template_description=template_description,
        answers=answers,
        company=company,
    )
    if feedback:
        base += (
            f"\n\nUSER FEEDBACK TO APPLY:\n{feedback}\n\n"
            "Apply the feedback above. Keep all sections. Maintain professional tone."
        )
    return base


# ═══════════════════════════════════════════════════════
# STRUCTURED JSON PROMPT  (generate_structured_document)
# ═══════════════════════════════════════════════════════

def build_structured_prompt(
    sections: list,
    department_name: str,
    template_name: str,
    template_description: str,
    answers: dict,
    company: dict = None,
) -> str:
    """
    Build the structured JSON generation prompt.

    Parameters
    ----------
    sections : list
        Pre-fetched section ORM objects. Caller (document_service) fetches once
        and passes in — no DB call made here.
    """
    today         = date.today().strftime("%d %B %Y")
    archetype     = _detect_archetype(template_name)
    dept_tone     = _DEPARTMENT_TONE.get(department_name.lower(), "professional and formal")
    arch_tone     = _ARCHETYPE_TONE.get(archetype, "professional and formal")
    company_name  = (company or {}).get("name", "Not specified")
    final_tone    = (company or {}).get("tone", f"{arch_tone}; {dept_tone}")

    
    sections_schema = []
    for i, section in enumerate(sections, 1):
        role         = classify_section_role(section.section_name)
        content_type = role_to_content_type(role, section.section_name)
        depth        = SECTION_DEPTH_HINT.get(role, "detailed and professional")
        table_hint   = (
            " [TABLE REQUIRED — build real rows from variable data. Minimum: 1 header row + data rows]"
            if section_needs_table(section.section_name) else ""
        )
        sections_schema.append(
            f'{i}. "{section.section_name}"\n'
            f'   role: {role} | content_type: {content_type} | depth: {depth}{table_hint}'
        )
    sections_list = "\n".join(sections_schema)

    answers_formatted = answers_to_context(answers)

    # Dynamic, context-aware table example — not static, not salary-biased
    table_sections    = [s for s in sections if section_needs_table(s.section_name)]
    table_example_note = _build_dynamic_table_example(table_sections, answers)

    logger.debug(
        "build_structured_prompt | template=%r archetype=%s sections=%d",
        template_name, archetype, len(sections),
    )

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

PLACEHOLDER RULE (CRITICAL):
- NEVER write [brackets] anywhere in the JSON output
- Use exact values from variable data
- Date fields: use {today} if not explicitly provided
- Missing value: write a contextually appropriate phrase — NEVER write "Not Provided"
- Table cells must always have real text — never empty or brackets
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
    "company": "{company_name}"
  }},
  "sections": [
    {{
      "id": "section_1",
      "heading": "Exact Section Name",
      "content_type": "text",
      "content": "Fully written content — no placeholders, no brackets",
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

For list sections: "content": ["Item one fully written", "Item two fully written"]

For table sections:
"content": [
  {{"cells": ["Header 1", "Header 2", "Header 3"]}},
  {{"cells": ["Real Value 1", "Real Value 2", "Real Value 3"]}}
]

FINAL CHECK BEFORE OUTPUTTING:
- Are all {len(sections)} sections present?
- Do all table sections have header row + at least 1 data row with real values?
- Are there zero [bracket] placeholders anywhere?
- Is there any 'Not Provided' text anywhere? (If yes, replace with a contextual phrase)
- Is the content substantive and professionally written?
If any answer is no, fix it before outputting."""
