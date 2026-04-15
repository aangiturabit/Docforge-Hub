import os
import requests
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
NOTION_VERSION = "2022-06-28"

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": NOTION_VERSION
}


def _text_to_blocks(content: str) -> list:
    """
    Convert plain text content to Notion blocks.
    Handles headings, paragraphs, tables, lists.
    """
    blocks = []
    lines = content.split("\n")

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if not line:
            i += 1
            continue

        # Heading detection (clean text headings)
        if len(line) < 80 and line.isupper():
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": line}}]
                }
            })
            i += 1
            continue

        # Table detection (| format)
        if line.startswith("|"):
            table_rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                row_line = lines[i].strip()
                if "---" in row_line:
                    i += 1
                    continue
                cells = [
                    c.strip() for c in row_line.strip("|").split("|")
                ]
                if cells:
                    table_rows.append(cells)
                i += 1

            if table_rows:
                col_count = max(len(r) for r in table_rows)
                notion_rows = []
                for row in table_rows:
                    padded = row + [""] * (col_count - len(row))
                    notion_rows.append({
                        "type": "table_row",
                        "table_row": {
                            "cells": [
                                [{"type": "text", "text": {"content": c}}]
                                for c in padded
                            ]
                        }
                    })
                if notion_rows:
                    blocks.append({
                        "object": "block",
                        "type": "table",
                        "table": {
                            "table_width": col_count,
                            "has_column_header": True,
                            "has_row_header": False,
                            "children": notion_rows
                        }
                    })
            continue

        # List detection
        if line.startswith("- ") or line.startswith("* "):
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": line[2:]}}]
                }
            })
            i += 1
            continue

        # Numbered list
        import re
        if re.match(r"^\d+\.\s", line):
            text = re.sub(r"^\d+\.\s", "", line)
            blocks.append({
                "object": "block",
                "type": "numbered_list_item",
                "numbered_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": text}}]
                }
            })
            i += 1
            continue

        # Regular paragraph
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": line}}]
            }
        })
        i += 1

    return blocks


def publish_document(
    document_id: int,
    title: str,
    content: str,
    department: str = "",
    template_name: str = ""
) -> dict:
    """
    Publishes document to Notion database.
    Returns page_id and url on success.
    Returns error on failure.
    """
    if not NOTION_API_KEY:
        return {"error": "NOTION_API_KEY not configured in .env"}

    if not NOTION_DATABASE_ID:
        return {"error": "NOTION_DATABASE_ID not configured in .env"}

    blocks = _text_to_blocks(content)

    # Notion API limits 100 blocks per request
    # Send first 100 blocks on create
    first_batch = blocks[:100]
    remaining = blocks[100:]

    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Name": {
                "title": [{"type": "text", "text": {"content": title}}]
            }
        },
        "children": first_batch
    }

    try:
        response = requests.post(
            "https://api.notion.com/v1/pages",
            headers=HEADERS,
            json=payload,
            timeout=30
        )

        if response.status_code not in (200, 201):
            return {
                "error": f"Notion API error: {response.status_code} — {response.text[:200]}"
            }

        page_data = response.json()
        page_id = page_data["id"]
        page_url = page_data.get("url", f"https://notion.so/{page_id.replace('-', '')}")

        # Append remaining blocks if any
        if remaining:
            for batch_start in range(0, len(remaining), 100):
                batch = remaining[batch_start:batch_start + 100]
                requests.patch(
                    f"https://api.notion.com/v1/blocks/{page_id}/children",
                    headers=HEADERS,
                    json={"children": batch},
                    timeout=30
                )

        return {
            "page_id": page_id,
            "url": page_url,
            "status": "published"
        }

    except Exception as e:
        return {"error": f"Notion publish failed: {str(e)}"}


def get_page(page_id: str) -> Optional[dict]:
    try:
        r = requests.get(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=HEADERS,
            timeout=15
        )
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None