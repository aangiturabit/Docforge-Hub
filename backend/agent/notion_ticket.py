import os
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(".env")

NOTION_API_KEY        = os.getenv("NOTION_API_KEY")
NOTION_TICKET_DB_ID   = os.getenv("NOTION_TICKET_DATABASE_ID")

HEADERS = {
    "Authorization" : f"Bearer {NOTION_API_KEY}",
    "Content-Type"  : "application/json",
    "Notion-Version": "2022-06-28",
}


def create_notion_ticket(
    question    : str,
    sources     : list,
    conversation: str,
    session_id  : str,
    trace_id    : str,
    priority    : str = "Medium",
) -> dict:
    """
    Creates a ticket page in the Notion tickets database.
    Returns the created page dict with id and url.
    """
    sources_text = "\n".join(f"• {s}" for s in sources) if sources else "None"

    payload = {
        "parent": {"database_id": NOTION_TICKET_DB_ID},
        "properties": {
            "Question": {
                "title": [{"text": {"content": question[:200]}}]
            },
            "Status": {
                "select": {"name": "Open"}
            },
            "Priority": {
                "select": {"name": priority}
            },
            "Session ID": {
                "rich_text": [{"text": {"content": session_id}}]
            },
            "Trace ID": {
                "rich_text": [{"text": {"content": trace_id}}]
            },
            "Created At": {
                "date": {"start": datetime.utcnow().isoformat()}
            },
        },
        "children": [
            {
                "object": "block",
                "type"  : "heading_2",
                "heading_2": {
                    "rich_text": [{"text": {"content": "Question"}}]
                }
            },
            {
                "object"   : "block",
                "type"     : "paragraph",
                "paragraph": {
                    "rich_text": [{"text": {"content": question}}]
                }
            },
            {
                "object": "block",
                "type"  : "heading_2",
                "heading_2": {
                    "rich_text": [{"text": {"content": "Sources Tried"}}]
                }
            },
            {
                "object"   : "block",
                "type"     : "paragraph",
                "paragraph": {
                    "rich_text": [{"text": {"content": sources_text}}]
                }
            },
            {
                "object": "block",
                "type"  : "heading_2",
                "heading_2": {
                    "rich_text": [{"text": {"content": "Conversation Context"}}]
                }
            },
            {
                "object"   : "block",
                "type"     : "paragraph",
                "paragraph": {
                    "rich_text": [{"text": {"content": conversation[:2000] if conversation else "No context"}}]
                }
            },
        ]
    }

    response = requests.post(
        "https://api.notion.com/v1/pages",
        headers=HEADERS,
        json=payload,
    )
    response.raise_for_status()
    return response.json()


def get_tickets_by_session(session_id: str) -> list:
    """
    Fetches all tickets from Notion that match a session_id.
    """
    payload = {
        "filter": {
        "property": "Session ID",
        "rich_text": {"contains": session_id}
        
        },
        "sorts": [
            {"property": "Created At", "direction": "descending"}
        ]
    }

    response = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_TICKET_DB_ID}/query",
        headers=HEADERS,
        json=payload,
    )
    response.raise_for_status()
    return response.json().get("results", [])


def get_all_tickets() -> list:
    """
    Fetches all tickets from Notion ticket database.
    Used by GET /agent/tickets endpoint.
    """
    response = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_TICKET_DB_ID}/query",
        headers=HEADERS,
        json={
            "sorts": [
                {"property": "Created At", "direction": "descending"}
            ]
        }
    )
    response.raise_for_status()
    return response.json().get("results", [])


def update_ticket_status(ticket_id: str, status: str) -> dict:
    """
    Updates the status of an existing ticket.
    status: "Open" | "In Progress" | "Resolved"
    """
    payload = {
        "properties": {
            "Status": {
                "select": {"name": status}
            }
        }
    }
    response = requests.patch(
        f"https://api.notion.com/v1/pages/{ticket_id}",
        headers=HEADERS,
        json=payload,
    )
    response.raise_for_status()
    return response.json()
