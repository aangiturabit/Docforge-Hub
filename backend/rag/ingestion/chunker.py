import os
import json
import time
import tiktoken
from pathlib import Path
from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv(".env")

RAW_BLOCKS_PATH    = Path("data/raw_blocks.json")
CHUNKS_OUTPUT_PATH = Path("data/chunks.json")

# ─────────────────────────────────────────────
# TOKEN CONFIG
# ─────────────────────────────────────────────
MAX_PARENT_TOKENS = 1200   # structural section max
MAX_CHILD_TOKENS  = 512    # hard limit per child
CHUNK_OVERLAP_TOKENS = 100 # token overlap between child chunks
MIN_CHILD_TOKENS  = 30     # lowered — don't discard short but valid clauses
SIM_THRESHOLD     = 0.65   # lowered — catches more semantic shifts

ENCODER = tiktoken.get_encoding("cl100k_base")


# ─────────────────────────────────────────────
# EMBEDDING CLIENT
# ─────────────────────────────────────────────
def get_emb_client():
    return AzureOpenAI(
        api_key        = os.getenv("AZURE_OPENAI_EMB_KEY"),
        azure_endpoint = os.getenv("AZURE_EMB_ENDPOINT"),
        api_version    = os.getenv("AZURE_EMB_API_VERSION"),
    )


def embed_sentences(client, sentences):
    try:
        response = client.embeddings.create(
            model = os.getenv("AZURE_EMB_DEPLOYMENT"),
            input = sentences,
        )
        return [item.embedding for item in response.data]
    except Exception as e:
        print(f"  Embedding failed: {e}")
        return []


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def count_tokens(text):
    return len(ENCODER.encode(text))


def cosine_sim(a, b):
    dot   = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x ** 2 for x in a) ** 0.5
    mag_b = sum(x ** 2 for x in b) ** 0.5
    if mag_a == 0 or mag_b == 0:
        return 1.0
    return dot / (mag_a * mag_b)


def extract_rich_text(rich_text):
    return "".join(item.get("plain_text", "") for item in rich_text).strip()


def split_sentences(text):
    import re
    parts = re.split(r'(?<=[.!?])\s+|\n+', text)
    return [p.strip() for p in parts if p.strip()]


def serialize_table(blocks, table_id):
    try:
        rows = [
            b for b in blocks
            if b.get("type") == "table_row"
            and b.get("parent", {}).get("block_id") == table_id
        ]
        if not rows:
            return ""

        parsed = []
        for row in rows:
            cells = row.get("table_row", {}).get("cells", [])
            parsed.append([extract_rich_text(cell) for cell in cells])

        if not parsed:
            return ""

        header    = parsed[0]
        data_rows = parsed[1:]

        md = ["| " + " | ".join(header) + " |"]
        md.append("| " + " | ".join(["---"] * len(header)) + " |")
        for row in data_rows:
            padded = row + [""] * (len(header) - len(row))
            md.append("| " + " | ".join(padded) + " |")

        sentences = []
        for row in data_rows:
            parts = [
                f"{header[i]} is {cell}"
                for i, cell in enumerate(row)
                if cell.strip() and i < len(header) and header[i].strip()
            ]
            if parts:
                sentences.append(". ".join(parts) + ".")

        return "\n".join(md) + "\n\n" + "\n".join(sentences)

    except Exception as e:
        print(f"  Table failed {table_id}: {e}")
        return ""


# ─────────────────────────────────────────────
# HARD TOKEN ENFORCEMENT
# Splits text that exceeds MAX_CHILD_TOKENS
# at sentence boundaries — no mid-sentence cuts
# ─────────────────────────────────────────────
def enforce_token_limit(text, max_tokens=MAX_CHILD_TOKENS):
    """
    If text exceeds max_tokens, split at sentence boundaries.
    Never cuts mid-sentence.
    Returns list of text chunks each within max_tokens.
    """
    if count_tokens(text) <= max_tokens:
        return [text]

    sentences = split_sentences(text)
    chunks    = []
    current   = []
    current_t = 0

    for sentence in sentences:
        s_tokens = count_tokens(sentence)

        # Single sentence already exceeds limit — keep as is
        # Better to have a slightly large chunk than lose data
        if s_tokens > max_tokens:
            if current:
                chunks.append(" ".join(current))
                current   = []
                current_t = 0
            chunks.append(sentence)
            continue

        if current_t + s_tokens > max_tokens:
            if current:
                chunks.append(" ".join(current))
            current   = [sentence]
            current_t = s_tokens
        else:
            current.append(sentence)
            current_t += s_tokens

    if current:
        chunks.append(" ".join(current))

    return chunks if chunks else [text]


def add_token_overlap(chunks, overlap_tokens=CHUNK_OVERLAP_TOKENS):
    """
    Adds token overlap from the previous chunk to the next chunk.
    This keeps boundary context available during retrieval.
    """
    if overlap_tokens <= 0 or len(chunks) <= 1:
        return chunks

    overlapped = []
    previous_tokens = []

    for chunk in chunks:
        current_tokens = ENCODER.encode(chunk)
        if previous_tokens:
            overlap = previous_tokens[-overlap_tokens:]
            chunk = (ENCODER.decode(overlap) + " " + chunk).strip()
        overlapped.append(chunk)
        previous_tokens = current_tokens

    return overlapped


# ─────────────────────────────────────────────
# PASS 1 — STRUCTURAL
# heading_1/2 → parent boundaries
# Returns parent sections 300–1200 tokens
# ─────────────────────────────────────────────
def structural_pass(doc):
    page_id = doc["page_id"]
    title   = doc["title"]
    url     = doc["url"]
    blocks  = doc["blocks"]

    parents      = []
    parent_index = 0
    doc_type     = "Unknown"
    department   = "Unknown"

    current_lines      = []
    current_breadcrumb = title
    current_h2         = None

    def flush():
        nonlocal parent_index, current_lines
        text = "\n".join(l for l in current_lines if l.strip()).strip()
        if not text:
            current_lines.clear()
            return

        tokens = count_tokens(text)

        # If parent itself exceeds MAX_PARENT_TOKENS
        # split at paragraph level to keep parents manageable
        if tokens > MAX_PARENT_TOKENS:
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            group      = []
            group_t    = 0
            for para in paragraphs:
                p_tokens = count_tokens(para)
                if group_t + p_tokens > MAX_PARENT_TOKENS and group:
                    parents.append({
                        "parent_id"  : f"{page_id}_p{parent_index}",
                        "page_id"    : page_id,
                        "title"      : title,
                        "url"        : url,
                        "breadcrumb" : current_breadcrumb,
                        "text"       : "\n\n".join(group),
                        "doc_type"   : doc_type,
                        "department" : department,
                        "token_count": group_t,
                    })
                    parent_index += 1
                    group   = [para]
                    group_t = p_tokens
                else:
                    group.append(para)
                    group_t += p_tokens
            if group:
                parents.append({
                    "parent_id"  : f"{page_id}_p{parent_index}",
                    "page_id"    : page_id,
                    "title"      : title,
                    "url"        : url,
                    "breadcrumb" : current_breadcrumb,
                    "text"       : "\n\n".join(group),
                    "doc_type"   : doc_type,
                    "department" : department,
                    "token_count": group_t,
                })
                parent_index += 1
        else:
            parents.append({
                "parent_id"  : f"{page_id}_p{parent_index}",
                "page_id"    : page_id,
                "title"      : title,
                "url"        : url,
                "breadcrumb" : current_breadcrumb,
                "text"       : text,
                "doc_type"   : doc_type,
                "department" : department,
                "token_count": tokens,
            })
            parent_index += 1

        current_lines.clear()

    for block in blocks:
        block_type = block.get("type", "")

        if block_type in ("divider", "table_row"):
            continue

        if block_type == "callout":
            text = extract_rich_text(block.get("callout", {}).get("rich_text", []))
            if text and doc_type == "Unknown":
                parts      = [p.strip() for p in text.split("·")]
                doc_type   = parts[0] if parts else "Unknown"
                department = parts[1] if len(parts) > 1 else "Unknown"
            continue

        if block_type in ("heading_1", "heading_2"):
            flush()
            h_text             = extract_rich_text(block.get(block_type, {}).get("rich_text", []))
            current_h2         = h_text
            current_breadcrumb = f"{title} > {h_text}"
            prefix             = "# " if block_type == "heading_1" else "## "
            current_lines.append(f"{prefix}{h_text}")
            continue

        if block_type == "heading_3":
            h3_text = extract_rich_text(block.get("heading_3", {}).get("rich_text", []))
            current_breadcrumb = (
                f"{title} > {current_h2} > {h3_text}"
                if current_h2 else f"{title} > {h3_text}"
            )
            current_lines.append(f"### {h3_text}")
            continue

        if block_type == "table":
            table_text = serialize_table(blocks, block["id"])
            if table_text:
                current_lines.append(table_text)
            continue

        if block_type in (
            "paragraph", "bulleted_list_item", "numbered_list_item",
            "quote", "code", "toggle", "to_do"
        ):
            text = extract_rich_text(block.get(block_type, {}).get("rich_text", []))
            if text:
                current_lines.append(text)

    flush()
    return parents


# ─────────────────────────────────────────────
# PASS 2 — SEMANTIC + HARD TOKEN ENFORCEMENT
# Splits parents into children using:
#   1. Embedding similarity (semantic boundaries)
#   2. Hard token enforcement (base max 512 per child)
#   3. Token overlap between child chunks
# ─────────────────────────────────────────────
def semantic_pass(parent, emb_client):
    parent_id  = parent["parent_id"]
    page_id    = parent["page_id"]
    title      = parent["title"]
    url        = parent["url"]
    breadcrumb = parent["breadcrumb"]
    doc_type   = parent["doc_type"]
    department = parent["department"]
    text       = parent["text"]
    tokens     = parent["token_count"]

    def make_child(chunk_text, part, total, semantic):
        prefix = f"[Document: {title} | Section: {breadcrumb}]\n"
        return {
            "chunk_id"      : f"{parent_id}_c{part}",
            "parent_id"     : parent_id,
            "page_id"       : page_id,
            "title"         : title,
            "url"           : url,
            "breadcrumb"    : breadcrumb,
            "text"          : chunk_text,
            "embed_text"    : prefix + chunk_text,
            "part"          : part,
            "total_parts"   : total,
            "semantic_split": semantic,
            "token_count"   : count_tokens(chunk_text),
            "metadata"      : {
                "doc_type"  : doc_type,
                "department": department,
                "breadcrumb": breadcrumb,
                "parent_id" : parent_id,
                "page_id"   : page_id,
                "title"     : title,
                "url"       : url,
                "source"    : "notion",
            }
        }

    # ── Already within child limit → single child ──
    if tokens <= MAX_CHILD_TOKENS:
        return [make_child(text, 0, 1, False)]

    # ── Semantic split ──
    sentences = split_sentences(text)

    if len(sentences) <= 1:
        # Only one sentence — apply hard token enforcement
        enforced = add_token_overlap(enforce_token_limit(text))
        total    = len(enforced)
        return [make_child(t, i, total, False) for i, t in enumerate(enforced)]

    # Embed sentences — cost control:
    # only embed if parent > MAX_CHILD_TOKENS (already checked above)
    time.sleep(0.2)
    vectors = embed_sentences(emb_client, sentences)

    if not vectors or len(vectors) != len(sentences):
        # Embedding failed → fall back to hard token enforcement
        enforced = add_token_overlap(enforce_token_limit(text))
        total    = len(enforced)
        return [make_child(t, i, total, False) for i, t in enumerate(enforced)]

    # Find semantic boundaries
    split_points = [0]
    for i in range(len(vectors) - 1):
        sim = cosine_sim(vectors[i], vectors[i + 1])
        if sim < SIM_THRESHOLD:
            split_points.append(i + 1)
    split_points.append(len(sentences))

    # Build text groups from split points
    raw_groups = []
    for i in range(len(split_points) - 1):
        group = " ".join(sentences[split_points[i]:split_points[i + 1]])
        if group.strip():
            raw_groups.append(group)

    if not raw_groups:
        enforced = add_token_overlap(enforce_token_limit(text))
        total    = len(enforced)
        return [make_child(t, i, total, False) for i, t in enumerate(enforced)]

    # Apply hard token enforcement to each semantic group before overlap.
    final_texts = []
    for group in raw_groups:
        enforced = enforce_token_limit(group)
        final_texts.extend(enforced)

    # Merge groups that are too small (below MIN_CHILD_TOKENS)
    # Instead of discarding — merge with next group
    merged = []
    buffer = ""
    for ft in final_texts:
        if count_tokens(buffer + " " + ft) < MIN_CHILD_TOKENS:
            buffer = (buffer + " " + ft).strip()
        else:
            if buffer:
                merged.append(buffer)
            buffer = ft
    if buffer:
        merged.append(buffer)

    if not merged:
        return [make_child(text, 0, 1, False)]

    merged = add_token_overlap(merged)

    total    = len(merged)
    children = [make_child(t, i, total, True) for i, t in enumerate(merged)]
    return children


# ─────────────────────────────────────────────
# CHUNK ALL DOCUMENTS
# ─────────────────────────────────────────────
def chunk_all_documents(documents):
    emb_client   = get_emb_client()
    all_parents  = []
    all_children = []
    total        = len(documents)

    print("=" * 60)
    print("CHUNKING ALL DOCUMENTS")
    print("=" * 60)

    for i, doc in enumerate(documents):
        try:
            title = doc.get("title", "Untitled")
            print(f"\n[{i+1}/{total}] {title}")

            parents = structural_pass(doc)
            all_parents.extend(parents)

            doc_children = []
            for parent in parents:
                children = semantic_pass(parent, emb_client)
                doc_children.extend(children)

            all_children.extend(doc_children)
            print(f"  parents={len(parents)} children={len(doc_children)}")

        except Exception as e:
            print(f"  FAILED: {e}")

    print("\n" + "=" * 60)
    print(f"Total parents  : {len(all_parents)}")
    print(f"Total children : {len(all_children)}")
    print("=" * 60)

    return {"parents": all_parents, "children": all_children}


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    try:
        print(f"Loading {RAW_BLOCKS_PATH}\n")
        with RAW_BLOCKS_PATH.open("r", encoding="utf-8") as f:
            documents = json.load(f)
        print(f"Loaded {len(documents)} documents\n")
    except FileNotFoundError:
        print("raw_blocks.json not found. Run notion_client.py first.")
        return
    except json.JSONDecodeError as e:
        print(f"Failed to parse raw_blocks.json: {e}")
        return

    chunks = chunk_all_documents(documents)

    try:
        CHUNKS_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CHUNKS_OUTPUT_PATH.open("w", encoding="utf-8") as f:
            json.dump(chunks, f, indent=2, ensure_ascii=False)
        print(f"\nSaved to {CHUNKS_OUTPUT_PATH}")
        print(f"Parents  : {len(chunks['parents'])}")
        print(f"Children : {len(chunks['children'])}")
        print("Ready for dense.py")
    except Exception as e:
        print(f"Failed to save: {e}")


if __name__ == "__main__":
    main()
