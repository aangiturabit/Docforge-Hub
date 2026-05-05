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


# ── Inline helper  ──────────────────────────────────

def _answers_to_context(answers: dict) -> str:
    if not answers:
        return "  No specific details provided — use professional defaults."

    answered = []
    unanswered = []
    for key, value in answers.items():
        if value is not None and str(value).strip():
            answered.append(f"  {key}: {str(value).strip()}")
        else:
            unanswered.append(f"  {key}")

    parts = []
    if answered:
        parts.append(
            "ANSWERED FIELDS - mandatory source content; preserve the user's exact meaning and rephrase only for grammar, clarity, tone, and formatting:\n"
            + "\n".join(answered)
        )
    if unanswered:
        parts.append(
            "UNANSWERED FIELDS - add only neutral, context-safe professional wording where needed; do not invent factual, financial, legal, HR policy, or employment-term specifics:\n"
            + "\n".join(unanswered)
        )
    return "\n\n".join(parts) if parts else "  No specific details provided — use professional defaults."


def _answer_coverage_prompt(answers: dict) -> str:
    if not any(value is not None and str(value).strip() for value in (answers or {}).values()):
        return ""

    return """
USER ANSWER COVERAGE RULES:
1. Treat answered fields as mandatory content, not optional inspiration.
2. Every answered field must be visibly represented in the most relevant section of the final document.
3. If an answered field is short, informal, or grammatically rough, polish it into professional language without changing its meaning.
4. Do not replace user-provided answers with a generic template paragraph.
5. Do not add new conditions, exceptions, promises, penalties, benefits, dates, amounts, or obligations around an answered field unless the user answer already contains them.
6. If a user answer conflicts with a usual default or common policy style, follow the user answer.
7. Use generic handbook or letter wording only as connective tissue around the user's actual answers.
"""


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
7. For answered values, rewrite the user's meaning professionally without changing facts or intent. If a factual, financial, legal, HR policy, or employment-term value is not answered, do not invent a specific value. Use neutral professional wording only where needed. Never leave blank or use "not provided".
"""


# ── Document-specific rules ───────────────────────────────────────────────────

def _document_specific_prompt(template_name: str) -> str:
    name = (template_name or "").lower()

    offer_signals = ("offer letter", "employment offer", "job offer", "internship offer")
    handbook_signals = ("employee handbook", "staff handbook", "hr handbook", "handbook")

    if any(signal in name for signal in offer_signals):
        return """
DOCUMENT-SPECIFIC RULES — OFFER LETTER:
1. Draft a real-world HR offer letter, not a structured document, policy, report, agreement, or handbook.
2. The output must read like a natural, formal corporate letter in continuous paragraphs.
3. Do not use section headings such as Job Details, Compensation, Benefits, Terms, Acceptance, or Next Steps.
4. Do not use bullet points, numbered sections, markdown, labels, or table-style formatting.
5. Preserve the user's exact meaning for candidate details, role, designation, department, reporting manager, work location, joining date, employment type, compensation, benefits, probation, notice period, acceptance deadline, contact details, and conditions.
6. Improve only grammar, clarity, tone, presentation, and letter formatting. Do not change, expand, reduce, replace, contradict, or reinterpret the user's intended offer terms.
7. Build the letter around the user's answered fields first. Every answered offer detail must appear visibly and naturally in the most relevant sentence or paragraph.
8. Use generic letter language only as connective tissue around the user's actual answers. Do not replace user-provided answers with a generic offer-letter template.
9. Start with the company name if available, then date, then candidate name and address if available, then the exact subject line: Offer of Employment.
10. After the subject line, write the letter in paragraph flow: opening offer confirmation with role and company; body paragraphs naturally covering role, department, reporting manager, location, compensation and benefits if provided, joining date, work expectations, probation, policies, confidentiality, and other user-provided terms; closing paragraph with acceptance or next steps and contact details if provided.
11. End exactly in letter style with Sincerely, followed by the authorized signatory name if provided, then the company name if available.
12. If a factual employment detail is unanswered, skip it gracefully or use neutral wording only when needed for flow. Do not create placeholders or call out that the detail is missing.
13. Do not invent salary figures, joining dates, benefits, probation duration, notice period, working hours, reporting lines, employment type, location, acceptance deadline, documents required, background-check conditions, contact details, authorized signatory, or legal conditions.
14. If the LETTER archetype guidance, section headings, or section depth rules conflict with these offer-letter rules, follow these offer-letter rules.
15. Return only the final offer letter text, with no explanation before or after.
"""

    if any(signal in name for signal in handbook_signals):
        return """
DOCUMENT-SPECIFIC RULES — EMPLOYEE HANDBOOK:
1. Write this document as a clear employee-facing handbook with organized sections and practical HR language.
2. Preserve the user's exact meaning for all company policies, expectations, benefits, leave rules, working arrangements, conduct rules, disciplinary steps, confidentiality requirements, compliance obligations, and acknowledgement terms.
3. Improve only grammar, clarity, tone, presentation, and handbook formatting. Do not change, expand, reduce, replace, contradict, or reinterpret the user's intended policy meaning.
4. Build each section around the user's answers first. Generic handbook language may support the section, but it must never drown out, replace, or contradict the provided answer.
5. Keep the handbook practical, readable, and easy for employees to follow. Use concise paragraphs and plain numbered points where the section naturally needs policy steps or expectations.
6. Do not turn the handbook into a contract, legal agreement, audit report, or strict compliance policy unless the user's answers explicitly ask for that style.
7. If a factual HR policy detail is unanswered, do not invent a specific company commitment. Use neutral general guidance only when needed.
8. Do not invent leave counts, salary policies, benefits, working hours, remote work rules, disciplinary penalties, notice periods, legal obligations, escalation paths, or compliance requirements.
9. If the POLICY archetype guidance conflicts with these employee-handbook rules, follow these employee-handbook rules.
10. The final output must feel like a polished internal employee handbook while keeping the user's provided meaning intact.
"""

    return ""


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
    answer_coverage_rules = _answer_coverage_prompt(answers)
    document_specific_rules = _document_specific_prompt(template_name)
    is_offer_letter = any(
        signal in (template_name or "").lower()
        for signal in ("offer letter", "employment offer", "job offer", "internship offer")
    )
    section_instruction = (
        f"OFFER LETTER SOURCE INPUT AREAS — DO NOT OUTPUT THESE AS SEPARATE SECTIONS:\n{section_info}\n\n"
        "For Offer Letter only, use these source input areas only to make sure all user answers are covered. "
        "Merge everything into one continuous letter."
        if is_offer_letter else
        f"REQUIRED SECTIONS — ALL {section_count} MUST BE PRESENT IN THIS EXACT ORDER:\n{section_info}"
    )

    logger.debug(
        "build_unified_prompt | template=%r archetype=%s sections=%d structured=%s",
        template_name, archetype, section_count, structured,
    )

    prompt = f"""You are DocForge, a professional document generation engine for B2B SaaS businesses.
Today's date: {today}

ABSOLUTE RULES — NEVER VIOLATE:
1. NEVER use [brackets] — no [DATE], [NAME], [Amount], [Insert anything]
2. For answered fields, use the user's answer as the source of truth. Preserve the exact meaning, facts, intent, conditions, names, dates, amounts, roles, policies, benefits, working terms, and requirements. Rephrase only for grammar, clarity, tone, and formatting.
3. NEVER write "Not Provided" specially in any approval section — write a contextually appropriate phrase instead
4. Use {today} for any date field not explicitly provided
5. No ##, no **, no --, no markdown symbols in content, no table | cell text, no markdown lists — only clean plain text or structured JSON as specified below
6. UTF-8 safe characters only
7. For unanswered factual, financial, legal, HR policy, or employment-term fields, do not invent specifics. Use neutral professional wording only where needed.


DOCUMENT CONTEXT:
- {company_ctx}
- Department: {department_name}
- Document Type: {template_name}
- Archetype: {archetype}
- Tone: {final_tone}
- Format: {fmt_hint}
- Purpose: {template_description}

{section_instruction}

VARIABLE DATA — ANSWERED FIELDS ARE USER MEANING TO PRESERVE, UNANSWERED FIELDS NEED NEUTRAL CONTEXT-SAFE WORDING:
{answers_ctx}
{answer_coverage_rules}
{document_specific_rules}
"""

    if has_tables:
        prompt += _TABLE_PROMPT

    if structured and is_offer_letter:
        prompt += f"""
OFFER LETTER STRUCTURED OUTPUT OVERRIDE:
- Ignore the normal multi-section JSON document pattern.
- Return exactly one section only.
- Do not create separate sections for company letterhead, candidate details, job title, compensation, benefits, terms, acceptance, or signature.
- Put the complete offer letter in the single section content as continuous paragraph text.
- The content must start with company name if available, date, candidate name/address if available, and Subject: Offer of Employment.
- The content must end with Sincerely, then authorized signatory name if provided, then company name if available.
- content_type must be "text".
- heading must be "Offer of Employment".
- No bullets, numbered sections, tables, labels, or markdown inside content.

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
      "id": "offer_letter",
      "heading": "Offer of Employment",
      "content_type": "text",
      "content": "Full continuous offer letter text only — no placeholders, no brackets, no section headings",
      "styling": {{"alignment": "justify", "font_weight": "normal", "page_break_after": false}},
      "word_count": 0
    }}
  ],
  "validation_status": "verified"
}}

FINAL CHECK — fix before outputting if any answer is no:
- Exactly one section only?
- The one section content reads like a real HR offer letter, not a section-wise document?
- Every answered offer-letter field from VARIABLE DATA is visibly represented without changing its meaning?
- No section headings such as Job Details, Compensation, Benefits, Terms, Acceptance, or Next Steps inside content?
- No bullets, numbered sections, tables, labels, markdown, placeholders, or "Not Provided" text?
"""
    elif structured:
        prompt += f"""
SECTION TYPE → content_type:
- HEADER, OPENER, BODY, OBLIGATION, CLOSURE, SIGN_OFF → "text"
- FINANCIAL, COMPENSATION, TABLE sections              → "table"
- DEFINITIONS, STEPS, LIST sections                    → "list"

CONTENT DEPTH:
- OPENER / INTRODUCTION: minimum 100-150 words
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
- Every answered field from VARIABLE DATA is visibly represented without changing its meaning?
- All table sections have header + data rows with real values?
- Zero [bracket] placeholders anywhere?
- No "Not Provided" text anywhere?
- Content substantive and professionally written?
- User-provided answers are the backbone of the content, with no generic template text replacing them?
- Add details from variable data where possible, do not leave gaps or hallucinations.
"""
    else:
        prompt += f"""
SECTION DEPTH:
- HEADER / SIGN_OFF:  compact, exact values only — 100-150 words
- OPENER / CLOSURE:   minimum 100-150 words
- BODY / OBLIGATION:  minimum 300-500 words, detailed and formal
- Approval sections:  must include a clear call to action for approver
- TABLE sections:     real column headers + real data rows from provided values, never leave blank.

OUTPUT RULES:
- Start directly with document content — no preamble
- {'For Offer Letter, merge all source input areas into one continuous letter; do not output section headings or a section-wise document' if is_offer_letter else f'Generate all {section_count} sections in order'}
- End with a formal sign-off block
- Every answered field from VARIABLE DATA must be visibly represented without changing its meaning
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
