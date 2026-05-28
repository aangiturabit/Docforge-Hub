import os
import json
import time
import requests
from dotenv import load_dotenv
from backend.rag.cache.redis_client import check_notion_rate_limit

load_dotenv(".env")

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

RATE_LIMIT_DELAY = 0.34  


# ─────────────────────────────────────────────
# 1. GET ALL PAGES (handles 100+ with pagination)
# ─────────────────────────────────────────────
def get_all_pages() -> list:
    """
    Fetch every page from the database.
    Handles Notion's 100-page pagination automatically.
    """
    pages = []
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    payload = {"page_size": 100}

    while True:
        response = requests.post(url, headers=HEADERS, json=payload)
        response.raise_for_status()
        data = response.json()

        pages.extend(data.get("results", []))
        print(f"  Fetched {len(pages)} pages so far...")

        if data.get("has_more"):
            payload["start_cursor"] = data["next_cursor"]
            time.sleep(RATE_LIMIT_DELAY)
        else:
            break

    return pages


# ─────────────────────────────────────────────
# 2. GET BLOCK CHILDREN (one level, paginated)
# ─────────────────────────────────────────────
def get_block_children(block_id: str) -> list:
    """
    Fetch direct children of any block or page.
    Handles pagination if children > 100.
    """
    blocks = []
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"

    while url:
         if not check_notion_rate_limit():
            print(f"  Rate limit hit — waiting...")
            time.sleep(1)

            response = requests.get(url, headers=HEADERS)
            response.raise_for_status()
            data = response.json()
            blocks.extend(data.get("results", []))

    if data.get("has_more"):
            cursor = data["next_cursor"]
            url = f"https://api.notion.com/v1/blocks/{block_id}/children?start_cursor={cursor}"
            time.sleep(RATE_LIMIT_DELAY)
    else:
            url = None

    return blocks


# ─────────────────────────────────────────────
# 3. RECURSIVE BLOCK FETCHER
# ─────────────────────────────────────────────
def get_page_blocks_recursive(block_id: str, depth: int = 0) -> list:
    try:
        blocks = get_block_children(block_id)
    except Exception as e:
        print(f"  Failed to fetch children of {block_id}: {e}")
        return []

    for block in blocks:
        block["_depth"] = depth
        block_type = block.get("type")

        try:
            if block_type == "child_page":
                print(f"    {'  ' * depth}↳ sub-page: {block['child_page']['title']}")
                block["_children"] = get_page_blocks_recursive(block["id"], depth + 1)
            elif block.get("has_children"):
                time.sleep(RATE_LIMIT_DELAY)
                block["_children"] = get_page_blocks_recursive(block["id"], depth + 1)
            else:
                block["_children"] = []
        except Exception as e:
            print(f"  Failed recursive fetch for block {block['id']}: {e}")
            block["_children"] = []

    return blocks

# ─────────────────────────────────────────────
# 4. FLATTEN TREE → FLAT LIST
# ─────────────────────────────────────────────
def flatten_blocks(blocks: list) -> list:
    """
    Convert nested block tree into a flat list.
    Preserves _depth on each block.
    Parent always appears before its children.
    """
    flat = []
    for block in blocks:
        children = block.pop("_children", [])
        flat.append(block)
        if children:
            flat.extend(flatten_blocks(children))
    return flat


# ─────────────────────────────────────────────
# 5. EXTRACT TITLE SAFELY
# ─────────────────────────────────────────────
def extract_title(page: dict) -> str:
    """Find the title property regardless of what it's named."""
    for prop in page["properties"].values():
        if prop.get("type") == "title":
            title_parts = prop.get("title", [])
            return title_parts[0]["plain_text"] if title_parts else "Untitled"
    return "Untitled"


# ─────────────────────────────────────────────
# 6. FETCH EVERYTHING — ALL PAGES, ALL BLOCKS
# ─────────────────────────────────────────────
def fetch_all_documents() -> list:
    """
    Master function.
    Returns a list of dicts:
    [
      {
        "page_id": "...",
        "title": "...",
        "url": "...",
        "blocks": [ ...flat list of all blocks... ]
      },
      ...
    ]
    """
    print("=" * 60)
    print("STEP 1: Fetching all pages from database...")
    print("=" * 60)
    pages = get_all_pages()
    print(f"\n Total pages found: {len(pages)}\n")

    all_documents = []
    failed_pages = []

    for i, page in enumerate(pages):
        page_id = page["id"]
        title = extract_title(page)
        url = page.get("url", "")

        print(f"[{i+1}/{len(pages)}] Fetching: {title}")
        print(f"         ID: {page_id}")

        try:
            blocks_tree = get_page_blocks_recursive(page_id)
            blocks_flat = flatten_blocks(blocks_tree)

            all_documents.append({
                "page_id": page_id,
                "title": title,
                "url": url,
                "blocks": blocks_flat
            })

            print(f"          {len(blocks_flat)} blocks fetched\n")

        except Exception as e:
            print(f"         FAILED: {e}\n")
            failed_pages.append({"page_id": page_id, "title": title, "error": str(e)})

        time.sleep(RATE_LIMIT_DELAY)

    print("=" * 60)
    print(f"Successfully fetched: {len(all_documents)} documents")
    print(f"Failed: {len(failed_pages)} documents")
    if failed_pages:
        for f in failed_pages:
            print(f"   - {f['title']} ({f['page_id']}): {f['error']}")
    print("=" * 60)

    return all_documents


# ─────────────────────────────────────────────
# 7. MAIN — RUN + SAVE RAW OUTPUT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    documents = fetch_all_documents()

    # ── Print summary of every document ──
    print("\n DOCUMENT SUMMARY:\n")
    for doc in documents:
        print(f"  {doc['title']}")
        print(f"    blocks : {len(doc['blocks'])}")
        print(f"    url    : {doc['url']}")

        # Show block type breakdown
        from collections import Counter
        type_counts = Counter(b["type"] for b in doc["blocks"])
        for btype, count in type_counts.most_common():
            print(f"    {btype:30s} {count}")
        print()

    # ── Save full raw data to JSON for Step 2 ──
    output_path = "docforge/data/raw_blocks.json"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(documents, f, indent=2, ensure_ascii=False)

    print(f"\n Raw blocks saved to: {output_path}")
  