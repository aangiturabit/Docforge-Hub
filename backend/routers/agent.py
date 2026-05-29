import uuid
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from backend.agent.graph import agent_graph
from backend.agent.memory.redis_memory import load_session, save_session, append_message
from backend.agent.memory.pg_memory import save_message, load_history, ensure_table
from backend.agent.notion_ticket import get_all_tickets, update_ticket_status

router = APIRouter(prefix="/agent", tags=["Agent"])

ensure_table()


# ─────────────────────────────────────────────
# REQUEST MODELS
# ─────────────────────────────────────────────
class ChatRequest(BaseModel):
    message   : str
    session_id: Optional[str] = None


class TicketRequest(BaseModel):
    session_id: str
    question  : str
    sources   : Optional[list] = []
    priority  : Optional[str]  = "Medium"


class UpdateTicketRequest(BaseModel):
    status: str


# ─────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────
@router.post("/chat")
async def chat(req: ChatRequest):
    """
    Main agent chat endpoint.
    Runs full LangGraph pipeline.
    Returns response + metadata.
    """
    try:
        # Generate session_id if not provided
        session_id = req.session_id or str(uuid.uuid4())[:8]

        # Load conversation history
        # Try Redis first, fall back to PostgreSQL
        messages = load_session(session_id)
        if not messages:
            messages = load_history(session_id)

        # Build initial state
        state = {
            "session_id"      : session_id,
            "user_input"      : req.message,
            "messages"        : messages,
            "trace_id"        : None,
            "retrieved_chunks": [],
            "citations"       : [],
            "cannot_answer"   : False,
            "ticket_exists"   : None,
            "ticket_id"       : None,
            "ticket_url"      : None,
            "ticket_question" : None,
            "intent"          : None,
            "clarification"   : None,
            "confidence"      : None,
            "answer"          : None,
            "response"        : None,
        }

        # Run graph
        result = agent_graph.invoke(state)

        # Save to memory
        append_message(session_id, "user",      req.message)
        append_message(session_id, "assistant", result.get("response", ""))

        # Persist to PostgreSQL
        save_message(
            session_id = session_id,
            role       = "user",
            content    = req.message,
            intent     = result.get("intent"),
            trace_id   = result.get("trace_id"),
        )
        save_message(
            session_id = session_id,
            role       = "assistant",
            content    = result.get("response", ""),
            intent     = result.get("intent"),
            trace_id   = result.get("trace_id"),
        )

        return {
            "session_id"   : session_id,
            "response"     : result.get("response", ""),
            "intent"       : result.get("intent"),
            "confidence"   : result.get("confidence"),
            "citations"    : result.get("citations", []),
            "cannot_answer": result.get("cannot_answer", False),
            "ticket_id"    : result.get("ticket_id"),
            "ticket_url"   : result.get("ticket_url"),
            "trace_id"     : result.get("trace_id"),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create-ticket")
async def create_ticket(req: TicketRequest):
    """
    User explicitly creates a ticket.
    Called when user clicks Create Ticket button in Streamlit.
    """
    try:
        from backend.agent.nodes.ticket import (
            check_ticket_node,
            create_ticket_node,
        )

        # Build minimal state for ticket nodes
        state = {
            "session_id"      : req.session_id,
            "user_input"      : req.question,
            "retrieved_chunks": [{"breadcrumb": s} for s in req.sources],
            "messages"        : load_session(req.session_id),
            "trace_id"        : str(uuid.uuid4())[:8],
            "ticket_exists"   : None,
            "ticket_id"       : None,
            "ticket_url"      : None,
            "ticket_question" : req.question,
            "intent"          : "question",
            "clarification"   : None,
            "confidence"      : "low",
            "answer"          : None,
            "citations"       : [],
            "cannot_answer"   : True,
            "response"        : None,
        }

        # Check duplicate first
        check_result = check_ticket_node(state)
        state.update(check_result)

        if state.get("ticket_exists"):
            return {
                "status"    : "exists",
                "message"   : "A ticket for this question already exists.",
                "ticket_id" : state.get("ticket_id"),
            }

        # Create ticket
        create_result = create_ticket_node(state)
        state.update(create_result)

        return {
            "status"    : "created",
            "message"   : "Ticket created successfully.",
            "ticket_id" : state.get("ticket_id"),
            "ticket_url": state.get("ticket_url"),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tickets")
async def get_tickets():
    """Returns all tickets from Notion ticket database."""
    try:
        tickets = get_all_tickets()
        result  = []
        for t in tickets:
            props = t.get("properties", {})

            title_list = props.get("Question", {}).get("title", [])
            title      = title_list[0].get("plain_text", "Unknown") if title_list else "Unknown"

            status     = props.get("Status", {}).get("select", {})
            status_name = status.get("name", "Unknown") if status else "Unknown"

            priority    = props.get("Priority", {}).get("select", {})
            priority_name = priority.get("name", "Unknown") if priority else "Unknown"

            session_list = props.get("Session ID", {}).get("rich_text", [])
            session_id   = session_list[0].get("plain_text", "") if session_list else ""

            result.append({
                "ticket_id" : t.get("id"),
                "title"     : title,
                "status"    : status_name,
                "priority"  : priority_name,
                "session_id": session_id,
                "url"       : t.get("url"),
                "created_at": props.get("Created At", {}).get("date", {}).get("start", ""),
            })

        return {"tickets": result, "total": len(result)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/tickets/{ticket_id}")
async def patch_ticket(ticket_id: str, req: UpdateTicketRequest):
    """Update ticket status in Notion."""
    try:
        update_ticket_status(ticket_id, req.status)
        return {"status": "updated", "ticket_id": ticket_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{session_id}")
async def get_history(session_id: str):
    """Returns conversation history for a session."""
    try:
        messages = load_session(session_id)
        if not messages:
            messages = load_history(session_id)
        return {"session_id": session_id, "messages": messages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
