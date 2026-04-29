
import os
import re
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

NOTION_API_KEY     = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
HEADERS = {
    "Authorization":  f"Bearer {NOTION_API_KEY}",
    "Content-Type":   "application/json",
    "Notion-Version": "2022-06-28",
}

NOTION_TEXT_CHUNK_LIMIT = 1900




_INLINE_TOKEN = re.compile(
    r"(\*\*\*.*?\*\*\*"      
    r"|\*\*.*?\*\*"           
    r"|\*[^*]+?\*"            
    r"|_[^_]+?_"              
    r"|~~.*?~~"               
    r"|`[^`]+`)",           
    re.DOTALL,
)

_SINGLE_WORD_HEADINGS = {
    "approval", "recommendations", "analysis", "summary", "overview",
    "findings", "conclusion", "conclusions", "scope", "purpose",
    "background", "objectives", "objective", "metrics", "timeline",
    "budget", "assumptions", "risks", "forecast",
}

_SIGNOFF_LABEL = re.compile(
    r"^(approved by|reviewed by|prepared by|authorized by|authorised by|"
    r"signatory|signature|name|designation|title|date)\b",
    re.IGNORECASE,
)

_ROLE_WORDS = {
    "officer", "director", "manager", "lead", "head", "chief", "president",
    "founder", "owner", "partner", "cfo", "ceo", "coo", "cto", "cio",
    "vp", "svp", "avp", "finance", "operations", "marketing", "sales",
    "legal", "compliance", "security", "engineering", "product", "hr",
    "human", "resources", "analyst", "specialist", "supervisor",
    "coordinator", "administrator", "signatory",
}


def _parse_inline(text: str) -> list:
    """Return a Notion rich_text array with bold/italic/code annotations."""
    runs = []
    last = 0

    for m in _INLINE_TOKEN.finditer(text):
        if m.start() > last:
            runs.extend(_plain_runs(text[last:m.start()]))

        raw = m.group()

        if raw.startswith("***"):
            runs.extend(_annotated_runs(raw[3:-3], bold=True, italic=True))
        elif raw.startswith("**"):
            runs.extend(_annotated_runs(raw[2:-2], bold=True))
        elif raw.startswith("*") or (raw.startswith("_") and raw.endswith("_")):
            runs.extend(_annotated_runs(raw[1:-1], italic=True))
        elif raw.startswith("~~"):
            runs.extend(_annotated_runs(raw[2:-2], strikethrough=True))
        elif raw.startswith("`"):
            runs.extend(_annotated_runs(raw[1:-1], code=True))

        last = m.end()

    if last < len(text):
        runs.extend(_plain_runs(text[last:]))

    return runs or _plain_runs(text)


def _chunk_text(text: str) -> list[str]:
    text = str(text or "")
    if not text:
        return [""]
    return [text[i:i + NOTION_TEXT_CHUNK_LIMIT] for i in range(0, len(text), NOTION_TEXT_CHUNK_LIMIT)]


def _plain_runs(text: str) -> list[dict]:
    return [{"type": "text", "text": {"content": chunk}} for chunk in _chunk_text(text)]


def _annotated_runs(
    text: str,
    bold: bool = False,
    italic: bool = False,
    strikethrough: bool = False,
    underline: bool = False,
    code: bool = False,
) -> list[dict]:
    return [
        _annotated(
            chunk,
            bold=bold,
            italic=italic,
            strikethrough=strikethrough,
            underline=underline,
            code=code,
        )
        for chunk in _chunk_text(text)
    ]


def _annotated(
    text: str,
    bold: bool = False,
    italic: bool = False,
    strikethrough: bool = False,
    underline: bool = False,
    code: bool = False,
) -> dict:
    return {
        "type": "text",
        "text": {"content": text},
        "annotations": {
            "bold": bold,
            "italic": italic,
            "strikethrough": strikethrough,
            "underline": underline,
            "code": code,
            "color": "default",
        },
    }


# Plain _rich() used only for DB properties (no inline parsing needed there)
def _rich(text: str, bold: bool = False) -> list:
    if not bold:
        return _plain_runs(text)
    return _annotated_runs(text, bold=True)


# ── Block primitives ──────────────────────────────────────────────────────────

def _block(kind: str, text: str) -> dict:
    """Generic block using inline-parsed rich_text."""
    return {"object": "block", "type": kind, kind: {"rich_text": _parse_inline(text)}}

def _spacer() -> dict:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": []}}

def _divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}

def _callout(title: str, department: str = "", template_name: str = "") -> dict:
    """
    Clean single-line callout:  📄  Title   ·   Department   ·   Template
    Only non-empty parts are joined so there are no stray separators.
    """
    parts  = [p for p in [title, department, template_name] if p and p.strip()]
    label  = "   ·   ".join(parts)
    # Title part is bold; the rest are plain
    runs: list = []
    if parts:
        runs.append(_annotated(parts[0], bold=True))
        for part in parts[1:]:
            runs.append({"type": "text", "text": {"content": f"   ·   {part}"}})

    return {
        "object": "block", "type": "callout",
        "callout": {
            "rich_text": runs or [{"type": "text", "text": {"content": label}}],
            "icon": {"type": "emoji", "emoji": "📄"},
            "color": "gray_background",
        },
    }




def _table_block(rows: list) -> dict:
    """Build a Notion table from a list-of-lists. First row = bold header."""
    if not rows:
        return _spacer()

    header_width = len(rows[0]) if rows and len(rows[0]) >= 2 else 0
    widths       = [len(r) for r in rows if len(r) >= 2]
    col_count    = header_width or max(set(widths), key=widths.count) if widths else 0
    col_count    = col_count or max(len(r) for r in rows)
    notion_rows = []

    for idx, row in enumerate(rows):
        if len(row) > col_count:
            padded = row[:col_count - 1] + [" | ".join(row[col_count - 1:])]
        else:
            padded = row + [""] * (col_count - len(row))
        is_header = idx == 0
        cells     = []

        for cell in padded:
            parsed = _parse_inline(str(cell))
            if is_header:
                for run in parsed:
                    run.setdefault("annotations", {})["bold"] = True
            cells.append(parsed)

        notion_rows.append({"type": "table_row", "table_row": {"cells": cells}})

    return {
        "object": "block", "type": "table",
        "table": {
            "table_width": col_count,
            "has_column_header": True,
            "has_row_header": False,
            "children": notion_rows,
        },
    }


def _split_table_cells(line: str) -> tuple[list[str], Optional[str]]:
    """
    Split one potential table row into cells.
    Supports markdown-style pipes with or without edge pipes, tabs, and wide spacing.
    """
    raw = line.strip()
    if not raw:
        return [], None

    if "\t" in raw:
        cells = [c.strip() for c in raw.split("\t")]
        return cells, "tab"

    if "|" in raw:
        parts = [c.strip() for c in raw.split("|")]
        while parts and not parts[0]:
            parts.pop(0)
        while parts and not parts[-1]:
            parts.pop()
        return parts, "pipe"

    if re.search(r"\s{3,}", raw):
        cells = [c.strip() for c in re.split(r"\s{3,}", raw)]
        return cells, "space"

    return [raw], None


def _is_table_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?[-=]{3,}:?", cell or "") for cell in cells)


def _looks_like_table_row(line: str, expected_delimiter: Optional[str] = None) -> bool:
    cells, delimiter = _split_table_cells(line)
    if delimiter is None or len(cells) < 2:
        return False
    if expected_delimiter and delimiter != expected_delimiter:
        return False
    return any(cell for cell in cells) and not _is_table_separator_row(cells)


def _parse_table(lines: list[str], start: int) -> tuple[list[list[str]], int]:
    """
    Collect consecutive delimited lines starting at `start`.
    Supports pipe, tab, and wide-space tables even when rows do not start with `|`.
    """
    rows: list[list[str]] = []
    i                     = start
    expected_delimiter    = None

    while i < len(lines):
        stripped = lines[i].strip()
        cells, delimiter = _split_table_cells(stripped)

        if delimiter is None or len(cells) < 2:
            break

        if expected_delimiter and delimiter != expected_delimiter:
            break

        expected_delimiter = expected_delimiter or delimiter
        if not _is_table_separator_row(cells) and any(cells):
            rows.append(cells)
        i += 1

    return rows, i


def _is_signoff_line(line: str) -> bool:
    raw = line.strip()
    if not raw:
        return False
    if _SIGNOFF_LABEL.match(raw):
        return True
    if raw.endswith(":"):
        return _SIGNOFF_LABEL.match(raw[:-1].strip()) is not None

    words = [w.strip(",:") for w in raw.split()]
    if not (1 <= len(words) <= 6):
        return False
    if re.search(r"[.!?]", raw):
        return False

    cap_ratio = sum(1 for w in words if w and w[0].isupper()) / len(words)
    if cap_ratio < 0.8:
        return False

    return any(w.lower() in _ROLE_WORDS for w in words)


def _heading_level(line: str) -> Optional[int]:
    if not line or len(line) > 120:
        return None
    if _is_signoff_line(line) or line.endswith(":"):
        return None

    # H1: all-caps
    if line.isupper() and 2 <= len(line.split()) <= 8:
        return 1

    # H2: majority title-case
    words = line.split()
    if len(words) == 1:
        return 2 if words[0].lower() in _SINGLE_WORD_HEADINGS else None

    if 2 <= len(words) <= 12:
        cap_ratio = sum(1 for w in words if w and w[0].isupper()) / len(words)
        if (
            cap_ratio >= 0.65
            and not line.endswith(",")
            and not re.search(r"\.\s", line)
            and not line.endswith(".")
        ):
            return 2

    return None



# ── Main converter ────────────────────────────────────────────────────────────

def _text_to_blocks(content: str) -> list:
    blocks: list = []
    lines = [l.rstrip() for l in content.split("\n")]
    i     = 0

    def _dedup_spacer():
        if blocks and not (
            blocks[-1]["type"] == "paragraph"
            and not blocks[-1]["paragraph"]["rich_text"]
        ):
            blocks.append(_spacer())

    def _section_break():
        _dedup_spacer()
        blocks.append(_divider())
        _dedup_spacer()

    while i < len(lines):
        line = lines[i].strip()

        # ── Blank line ────────────────────────────────────────────────────────
        if not line:
            _dedup_spacer()
            i += 1
            continue

        # ── Delimited table (pipes, tabs, or wide spaces) ────────────────────
        if _looks_like_table_row(line):
            rows, new_i = _parse_table(lines, i)
            if len(rows) >= 2:  # header + at least one data row
                _dedup_spacer()
                blocks.append(_table_block(rows))
                _dedup_spacer()
                i = new_i
                continue

        # ── Bullet list ───────────────────────────────────────────────────────
        if re.match(r"^[-*•]\s+", line):
            blocks.append(_block("bulleted_list_item", re.sub(r"^[-*•]\s+", "", line)))
            i += 1
            continue

        # ── Numbered list ─────────────────────────────────────────────────────
        if re.match(r"^\d+[.)]\s", line):
            blocks.append(_block("numbered_list_item", re.sub(r"^\d+[.)]\s+", "", line)))
            i += 1
            continue

        # ── Approval/sign-off lines: preserve as plain paragraphs ─────────────
        if _is_signoff_line(line):
            blocks.append(_block("paragraph", line))
            i += 1
            continue

        # ── Heading (plain-text shape detection only) ─────────────────────────
        level = _heading_level(line)
        if level:
            _section_break()
            display = line.title() if line.isupper() else line
            kind    = f"heading_{level}"
            blocks.append(_block(kind, display))
            _dedup_spacer()
            i += 1
            continue
       
  
        # ── Paragraph (multi-line merge) ──────────────────────────────────────
        para_lines = [line]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if not nxt:
                break
            if _heading_level(nxt) or re.match(r"^[-*•]|\d+[.)]", nxt):
                break
            if _is_signoff_line(nxt):
                break
            if _looks_like_table_row(nxt):       # next line is a table
                break
            para_lines.append(nxt)
            i += 1

        full = " ".join(para_lines)
        for start in range(0, len(full), 1900):
            blocks.append(_block("paragraph", full[start:start + 1900]))
        _dedup_spacer()

    # Remove consecutive empty paragraphs
    cleaned, prev_empty = [], False
    for b in blocks:
        empty = b["type"] == "paragraph" and not b["paragraph"]["rich_text"]
        if empty and prev_empty:
            continue
        cleaned.append(b)
        prev_empty = empty

    return cleaned


# ── Notion DB helpers ─────────────────────────────────────────────────────────

def _get_db_schema(database_id: str) -> dict:
    try:
        r = requests.get(
            f"https://api.notion.com/v1/databases/{database_id}",
            headers=HEADERS,
            timeout=15,
        )
        if r.status_code == 200:
            return {k: v["type"] for k, v in r.json().get("properties", {}).items()}
    except Exception:
        pass
    return {}


def _build_properties(schema: dict, title: str, department: str, template_name: str) -> dict:
    now   = datetime.now(timezone.utc).isoformat()
    props = {}

    for name, ptype in schema.items():
        low = name.lower()

        if ptype == "title":
            props[name] = {"title": _rich(title)}

        elif ptype == "select" and "department" in low and department:
            props[name] = {"select": {"name": department}}

        elif ptype == "select" and any(k in low for k in ("document_type", "document type", "doc_type")) and template_name:
            props[name] = {"select": {"name": template_name}}

        elif ptype == "rich_text" and any(k in low for k in ("document_type", "document type", "doc_type")):
            props[name] = {"rich_text": _rich(template_name or "")}

        elif ptype == "rich_text" and "version" in low:
            props[name] = {"rich_text": _rich("v1.0")}

        elif ptype == "date" and "created" in low:
            props[name] = {"date": {"start": now}}

        elif ptype == "date" and ("last_updated" in low or "updated" in low):
            props[name] = {"date": {"start": now}}

    return {k: v for k, v in props.items() if v}


# ── Public API ────────────────────────────────────────────────────────────────

def publish_document(
    document_id: int,
    title: str,
    content: str,
    department: str = "",
    template_name: str = "",
) -> dict:
    if not NOTION_API_KEY:
        return {"error": "NOTION_API_KEY not configured in .env"}
    if not NOTION_DATABASE_ID:
        return {"error": "NOTION_DATABASE_ID not configured in .env"}

    schema     = _get_db_schema(NOTION_DATABASE_ID)
    properties = _build_properties(schema, title, department, template_name)

    blocks = (
        [_callout(title, department, template_name), _spacer()]
        + _text_to_blocks(content)
    )

    try:
        response = requests.post(
            "https://api.notion.com/v1/pages",
            headers=HEADERS,
            json={
                "parent": {"database_id": NOTION_DATABASE_ID},
                "properties": properties,
                "children": blocks[:100],
            },
            timeout=30,
        )
        if response.status_code not in (200, 201):
            return {"error": f"Notion API error: {response.status_code} — {response.text[:300]}"}

        page_data = response.json()
        page_id   = page_data["id"]
        page_url  = page_data.get("url", f"https://notion.so/{page_id.replace('-', '')}")

        for start in range(100, len(blocks), 100):
            append_response = requests.patch(
                f"https://api.notion.com/v1/blocks/{page_id}/children",
                headers=HEADERS,
                json={"children": blocks[start:start + 100]},
                timeout=30,
            )
            if append_response.status_code not in (200, 201):
                return {
                    "error": (
                        f"Notion append error: {append_response.status_code} — "
                        f"{append_response.text[:500]}"
                    )
                }

        return {"page_id": page_id, "url": page_url, "status": "published"}

    except Exception as e:
        return {"error": f"Notion publish failed: {str(e)}"}


def get_page(page_id: str) -> Optional[dict]:
    try:
        r = requests.get(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=HEADERS,
            timeout=15,
        )
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None
