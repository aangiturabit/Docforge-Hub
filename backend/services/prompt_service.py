from __future__ import annotations

from datetime import date
from typing import Dict, Optional

from backend.services.section_utils import (
    SECTION_DEPTH_HINT,
    classify_section_role,
    section_needs_table,
)
from backend.utils.logger import get_logger

logger = get_logger("docforge.services.prompt")


# ── Inline helper (removed from text_utils) ──────────────────────────────────

def _answers_to_context(answers: dict) -> str:
    if not answers:
        return "  No specific details provided — use professional defaults."
    return "\n".join(
        f"  {k}: {str(v).strip() if v and str(v).strip() else 'not specified'}"
        for k, v in answers.items()
    )


# ── Archetype detection ───────────────────────────────────────────────────────

_ARCHETYPE_SIGNALS: dict[str, list[str]] = {
    "LETTER":   ["offer letter", "appointment", "relieving", "termination",
                 "warning letter", "promotion", "increment", "noc",
                 "experience letter", "internship offer"],
    "CONTRACT": ["agreement", "contract", "nda", "mou", "terms of service",
                 "data processing", "terms and conditions", "partnership"],
    "POLICY":   ["policy", "code of conduct", "handbook", "guidelines",
                 "access control", "data protection", "vulnerability management"],
    "REPORT":   ["report", "assessment", "audit", "analysis", "postmortem",
                 "root cause", "data breach", "incident report"],
    "PROCESS":  ["sop", "checklist", "runbook", "guide", "procedure",
                 "change management", "onboarding sop", "offboarding"],
    "PLAN":     ["plan", "strategy", "roadmap", "proposal", "framework",
                 "specification", "requirements", "backlog", "sprint",
                 "architecture", "design", "brief", "playbook"],
}


def _detect_archetype(template_name: str) -> str:
    name = template_name.lower()
    for archetype, signals in _ARCHETYPE_SIGNALS.items():
        if any(s in name for s in signals):
            return archetype
    return "PLAN"


# ── Lookup tables ─────────────────────────────────────────────────────────────

_ARCHETYPE: dict[str, tuple[str, str]] = {
    "LETTER":   ("professional, warm — direct address to recipient",
                 "Letterhead → named recipient → compensation table → signatory block."),
    "CONTRACT": ("precise and formal — unambiguous legal language",
                 "Numbered clauses (1., 1.1). Definitions. Dual signature blocks."),
    "POLICY":   ("formal — must/shall for obligations, should/may for recommended",
                 "Numbered policy statements. Approval block."),
    "REPORT":   ("analytical, evidence-based — findings-first",
                 "Executive summary → findings → risk matrix → recommendations → sign-off."),
    "PROCESS":  ("procedural and clear — step-based, role ownership",
                 "Numbered steps. Role per step. Decision points. Escalation path."),
    "PLAN":     ("strategic, forward-looking — goal and milestone driven",
                 "Objective → milestones/owners → KPIs → risk factors → approval."),
}

_DEPT_TONE: dict[str, str] = {
    "human resources":         "formal yet warm — empathetic, professional",
    "legal":                   "precise and formal — unambiguous, clause-based",
    "finance and accounting":  "accurate and structured — number-driven",
    "engineering":             "technical and precise — engineer audience",
    "it operations":           "procedural and clear — action-oriented",
    "security and compliance": "formal and risk-aware — compliance-focused",
    "customer success":        "professional and client-friendly — solution-focused",
    "marketing":               "strategic and engaging — persuasive",
    "product management":      "strategic and cross-functional",
    "quality assurance":       "methodical and precise — evidence-based",
}


# ── Section intelligence ──────────────────────────────────────────────────────

def _build_section_intelligence(sections: list) -> str:
    lines = []
    for i, section in enumerate(sections, 1):
        role       = classify_section_role(section.section_name)
        depth      = SECTION_DEPTH_HINT.get(role, "detailed and professional")
        table_hint = " [TABLE REQUIRED — real rows from variable data]" if section_needs_table(section.section_name) else ""
        lines.append(f"{i}. {section.section_name}{table_hint}\n   Role: {role} | Depth: {depth}")
    return "\n".join(lines)


# ── Table rules ───────────────────────────────────────────────────────────────

_TABLE_PROMPT = """
TABLE CONSTRUCTION RULES (apply to every section marked TABLE REQUIRED):
1. Always generate a table — never skip it
2. First row = column headers relevant to THIS section type
3. Every subsequent row = real values from the variable data above
4. Minimum: 1 header row + 1 data row with actual content
5. No empty cells, no [bracket] placeholders, no pipe | characters inside cell text
6. Choose column headers that match the section purpose:
   - Compensation/Salary   → Component | Amount | Frequency
   - Risk/Findings         → Item | Description | Severity | Status
   - Invoice/Pricing       → Description | Quantity | Unit Price | Total
   - Timeline/Milestones   → Phase | Activity | Owner | Due Date
   - Metrics/KPIs          → Metric | Target | Actual | Status
   - Asset/Inventory       → Asset | Description | Quantity | Status
   - Any other table       → derive logical headers from the section name and variable data
7. Use values already present in the variable data — do not invent numbers or names. if not given fill that cell with details according to the context of the document. never leave blank or use "not provided".
"""


# ── Unified prompt builder ────────────────────────────────────────────────────

def build_unified_prompt(
    sections: list,
    department_name: str,
    template_name: str,
    template_description: str,
    answers: Dict[str, str],
    company: Optional[Dict] = None,
    structured: bool = False,
) -> str:
    today        = date.today().strftime("%d %B %Y")
    archetype    = _detect_archetype(template_name)
    arch_tone, fmt_hint = _ARCHETYPE.get(archetype, ("professional and formal", ""))
    dept_tone    = _DEPT_TONE.get(department_name.lower(), "professional and formal")
    company_name = (company or {}).get("name", "Not specified")
    final_tone   = (company or {}).get("tone", f"{arch_tone}; {dept_tone}")

    company_ctx = (
        f"Company: {company.get('name', 'Not specified')} | "
        f"Industry: {company.get('industry', 'B2B SaaS')} | "
        f"Size: {company.get('size', 'Not specified')} | "
        f"Location: {company.get('location', 'India')}"
        if company else "Company: India-based B2B SaaS"
    )

    section_count = len(sections)
    section_info  = _build_section_intelligence(sections)
    answers_ctx   = _answers_to_context(answers)
    has_tables    = any(section_needs_table(s.section_name) for s in sections)

    logger.debug(
        "build_unified_prompt | template=%r archetype=%s sections=%d structured=%s",
        template_name, archetype, section_count, structured,
    )

    prompt = f"""You are DocForge, a professional document generation engine for B2B SaaS businesses.
Today's date: {today}

ABSOLUTE RULES — NEVER VIOLATE:
1. NEVER use [brackets] — no [DATE], [NAME], [Amount], [Insert anything]
2. Use exact values from the variable data provided or fill with contextually appropriate content — do not invent details. dont leave placeholders or gaps.or empty blanks in any section .
3. NEVER write "Not Provided" specially in any approval section — write a contextually appropriate phrase instead
4. Use {today} for any date field not explicitly provided
5. No ##, no **, no --, no markdown symbols in content, no table | cell text, no markdown lists — only clean plain text or structured JSON as specified below
6. UTF-8 safe characters only


DOCUMENT CONTEXT:
- {company_ctx}
- Department: {department_name}
- Document Type: {template_name}
- Archetype: {archetype}
- Tone: {final_tone}
- Format: {fmt_hint}
- Purpose: {template_description}

REQUIRED SECTIONS — ALL {section_count} MUST BE PRESENT IN THIS EXACT ORDER:
{section_info}

VARIABLE DATA — EMBED ALL VALUES IN THE DOCUMENT:
{answers_ctx}
"""

    if has_tables:
        prompt += _TABLE_PROMPT

    if structured:
        prompt += f"""
SECTION TYPE → content_type:
- HEADER, OPENER, BODY, OBLIGATION, CLOSURE, SIGN_OFF → "text"
- FINANCIAL, COMPENSATION, TABLE sections              → "table"
- DEFINITIONS, STEPS, LIST sections                    → "list"

CONTENT DEPTH:
- OPENER / INTRODUCTION: minimum 200-250 words, 3-4 paragraphs
- BODY / OBLIGATION:     minimum 300-500 words, detailed
- HEADER:                compact, 100-150 words, exact values only
- SIGN_OFF:              formal block, 40-100 words max
- Approval sections:     must include a clear call to action for approver, no placeholders or "Not Provided"

Return ONLY this JSON — no text before or after, no markdown:
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
      "content": "Fully written — no placeholders, no brackets",
      "styling": {{"alignment": "justify", "font_weight": "normal", "page_break_after": false}},
      "word_count": 0
    }}
  ],
  "validation_status": "verified"
}}

list sections  → "content": ["Item one", "Item two"]
table sections → "content": [{{"cells": ["H1","H2"]}}, {{"cells": ["V1","V2"]}}]

FINAL CHECK — fix before outputting if any answer is no:
- All {section_count} sections present and in order?
- All table sections have header + data rows with real values?
- Zero [bracket] placeholders anywhere?
- No "Not Provided" text anywhere?
- Content substantive and professionally written?
- Add details from variable data where possible, do not leave gaps or hallucinations.
"""
    else:
        prompt += f"""
SECTION DEPTH:
- HEADER / SIGN_OFF:  compact, exact values only — 100-150 words
- OPENER / CLOSURE:   minimum 200-250 words, 3-4 full paragraphs
- BODY / OBLIGATION:  minimum 300-500 words, detailed and formal
- Approval sections:  must include a clear call to action for approver
- TABLE sections:     real column headers + real data rows from provided values, never leave blank.

OUTPUT RULES:
- Start directly with document content — no preamble
- Generate all {section_count} sections in order
- End with a formal sign-off block
- Clean plain text only — no ##, no **, no markdown

"""

    return prompt


# ── Backward-compat wrappers ──────────────────────────────────────────────────

def build_prompt(sections, department_name, template_name, template_description, answers, company=None) -> str:
    return build_unified_prompt(sections=sections, department_name=department_name, template_name=template_name,
                                template_description=template_description, answers=answers, company=company, structured=False)


def build_structured_prompt(sections, department_name, template_name, template_description, answers, company=None) -> str:
    return build_unified_prompt(sections=sections, department_name=department_name, template_name=template_name,
                                template_description=template_description, answers=answers, company=company, structured=True)


def build_regenerate_prompt(sections, department_name, template_name, template_description, answers, feedback=None, company=None) -> str:
    base = build_prompt(sections=sections, department_name=department_name, template_name=template_name,
                        template_description=template_description, answers=answers, company=company)
    if feedback:
        base += f"\n\nUSER FEEDBACK TO APPLY:\n{feedback}\n\nApply the feedback above. Keep all sections. Maintain professional tone."
    return base


# ── System prompt constants ───────────────────────────────────────────────────

DOCUMENT_SYSTEM_PROMPT = (
    "You are DocForge, a professional document generation engine for B2B SaaS businesses. "
    "Generate premium-quality, detailed, comprehensive, executive-ready plain-text documents. "
    "Today's date: {today}. Never use [brackets]. Never write 'Not Provided'. No markdown."
)

STRUCTURED_SYSTEM_PROMPT = (
    "You are DocForge, a structured document generation engine for B2B SaaS companies. "
    "Output ONLY valid JSON — no plain text or markdown outside JSON string values. "
    "Today's date: {today}. Never use [brackets]. Never write 'Not Provided'. word_count must be an integer."
)