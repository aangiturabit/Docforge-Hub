

# ── Section role signals ──────────────────────────────────────────────────────
SECTION_ROLE_MAP: dict[str, list[str]] = {
    "HEADER": [
        "letterhead", "date", "title", "reference", "id",
        "version", "parties", "candidate", "company letterhead", "heading",
    ],
    "OPENER": [
        "purpose", "scope", "overview", "background",
        "executive summary", "introduction", "objective",
    ],
    "STRUCTURAL": [
        "definitions", "methodology", "classification",
        "types", "categories", "framework",
    ],
    "OBLIGATION": [
        "responsibilities", "obligations", "requirements",
        "policy", "rules", "clause", "compliance", "standards",
    ],
    "EVIDENCE": [
        "findings", "results", "assessment", "analysis",
        "metrics", "test", "defects", "vulnerability", "risk",
    ],
    "BODY": [
        "compensation", "breakdown", "details", "description",
        "content", "information", "terms", "conditions",
    ],
    "CLOSURE": [
        "recommendations", "next steps", "action items",
        "conclusion", "improvement", "mitigation",
    ],
    "SIGN_OFF": [
        "approval", "signature", "sign off", "acknowledgement",
        "authorization", "sign-off", "closure",
    ],
}

# ── Word-count targets per role: (min, max) ───────────────────────────────────
SECTION_DEPTH_WORDS: dict[str, tuple[int, int]] = {
    "HEADER":     (30,  150),
    "OPENER":     (150, 400),
    "STRUCTURAL": (100, 300),
    "OBLIGATION": (250, 700),
    "EVIDENCE":   (200, 500),
    "BODY":       (250, 900),
    "CLOSURE":    (120, 400),
    "SIGN_OFF":   (30,  120),
}

# ── Human-readable depth description per role (used in prompts) ───────────────
SECTION_DEPTH_HINT: dict[str, str] = {
    "HEADER":     "concise — exact values only, 50-150 words",
    "OPENER":     "clear and purposeful — 180-350 words, 3-4 full paragraphs",
    "STRUCTURAL": "precise definitions — 100-200 words per item, minimum 4 items",
    "OBLIGATION": "detailed and explicit — 300-650 words, numbered sub-points with must/shall",
    "EVIDENCE":   "data-driven and specific — 250-500 words, use table if applicable",
    "BODY":       "detailed and substantial — 300-800 words, full paragraphs",
    "CLOSURE":    "actionable — 150-350 words with specific next steps, owner, timeline",
    "SIGN_OFF":   "formal block only — names, designations, date lines, 40-100 words",
}

# ── Section names that must render as tables ─────────────────────────────────
TABLE_SECTION_SIGNALS: list[str] = [
    "compensation", "breakdown", "ctc", "salary", "budget",
    "invoice", "pricing", "comparison", "metrics", "kpi",
    "test cases", "findings", "risk", "timeline", "schedule",
    "gross", "deductions", "earnings", "payment", "quotation",
    "bill", "purchase",
]


# ── Classifiers ───────────────────────────────────────────────────────────────

def classify_section_role(section_name: str) -> str:
    
    name = section_name.lower()
    for role, signals in SECTION_ROLE_MAP.items():
        if any(s in name for s in signals):
            return role
    return "BODY"


def section_needs_table(section_name: str) -> bool:
   
    name = section_name.lower()
    return any(s in name for s in TABLE_SECTION_SIGNALS)


def role_to_content_type(role: str, section_name: str = "") -> str:
    
    if section_needs_table(section_name):
        return "table"
    return {
        "HEADER":     "text",
        "OPENER":     "text",
        "STRUCTURAL": "list",
        "OBLIGATION": "text",
        "EVIDENCE":   "table",
        "BODY":       "text",
        "CLOSURE":    "list",
        "SIGN_OFF":   "text",
    }.get(role, "text")