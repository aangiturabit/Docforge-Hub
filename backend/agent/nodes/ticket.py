import hashlib
from backend.agent.state import AgentState
from backend.rag.cache.redis_client import get_redis


def _ticket_dedup_key(session_id: str, user_input: str) -> str:
    """Redis key for dedup check."""
    raw = f"{session_id}|{user_input[:100]}"
    return f"ticket_dedup:{hashlib.md5(raw.encode()).hexdigest()}"


def _ticket_question_from_state(state: AgentState) -> str:
    """
    Finds the question that should be used for a ticket.
    If the current message is just "create a ticket", use the previous user turn.
    """
    if state.get("ticket_question"):
        return state["ticket_question"]

    user_input = state.get("user_input", "")
    intent = state.get("intent")
    messages = state.get("messages", [])

    if intent == "create_ticket":
        for message in reversed(messages):
            if message.get("role") == "user":
                content = message.get("content", "").strip()
                if content:
                    return content

    return user_input


def check_ticket_node(state: AgentState) -> dict:
    """
    Checks Redis for duplicate ticket.
    If found → ticket_exists = True, ticket_id = existing ID
    If not   → ticket_exists = False
    """
    trace_id   = state.get("trace_id", "")
    session_id = state.get("session_id", "")
    question   = _ticket_question_from_state(state)

    print(f"[{trace_id}] check_ticket_node → checking dedup")

    try:
        r   = get_redis()
        key = _ticket_dedup_key(session_id, question)
        val = r.get(key) if r else None

        if val:
            if isinstance(val, bytes):
                val = val.decode("utf-8")
            print(f"[{trace_id}] check_ticket_node → ticket exists: {val}")
            return {
                "ticket_exists": True,
                "ticket_id"    : val,
                "ticket_question": question,
            }
        else:
            print(f"[{trace_id}] check_ticket_node → no duplicate found")
            return {
                "ticket_exists": False,
                "ticket_question": question,
            }

    except Exception as e:
        print(f"[{trace_id}] check_ticket_node → error: {e}")
        return {
            "ticket_exists": False,
            "ticket_question": question,
        }


def create_ticket_node(state: AgentState) -> dict:
    """
    Creates a ticket in Notion.
    Stores ticket_id in Redis for dedup.
    Sets: ticket_id, ticket_url
    """
    trace_id   = state.get("trace_id", "")
    session_id = state.get("session_id", "")
    question   = _ticket_question_from_state(state)
    chunks     = state.get("retrieved_chunks", [])
    messages   = state.get("messages", [])

    print(f"[{trace_id}] create_ticket_node → creating ticket")

    try:
        from backend.agent.notion_ticket import create_notion_ticket

        # Build sources tried list
        sources = [
            c.get("breadcrumb", "") for c in chunks if c.get("breadcrumb")
        ]

        # Build conversation summary (last 4 turns)
        recent   = messages[-4:] if messages else []
        conv_str = "\n".join(
            f"{m['role'].upper()}: {m['content'][:200]}"
            for m in recent
        )

        ticket = create_notion_ticket(
            question    = question,
            sources     = sources,
            conversation= conv_str,
            session_id  = session_id,
            trace_id    = trace_id,
        )

        ticket_id  = ticket.get("id", "")
        ticket_url = ticket.get("url", "")

        # Store in Redis for dedup (24 hour TTL)
        r   = get_redis()
        key = _ticket_dedup_key(session_id, question)
        if r and ticket_id:
            r.setex(key, 86400, ticket_id)

        print(f"[{trace_id}] create_ticket_node → created: {ticket_id}")

        return {
            "ticket_id"   : ticket_id,
            "ticket_url"  : ticket_url,
            "ticket_exists": False,
            "ticket_question": question,
        }

    except Exception as e:
        print(f"[{trace_id}] create_ticket_node → failed: {e}")
        return {
            "ticket_id"   : None,
            "ticket_url"  : None,
            "ticket_question": question,
            "response"    : "I could not create a support ticket right now. Please try again.",
        }


def fetch_ticket_node(state: AgentState) -> dict:
    """
    Fetches existing ticket status from Notion.
    Called when intent = ticket_status.
    """
    trace_id   = state.get("trace_id", "")
    session_id = state.get("session_id", "")

    print(f"[{trace_id}] fetch_ticket_node → fetching tickets for session")

    try:
        from backend.agent.notion_ticket import get_tickets_by_session

        tickets = get_tickets_by_session(session_id)

        if not tickets:
            return {
                "response": "I could not find any tickets for your session.",
            }

        # Format tickets for display
        lines = ["Here are your tickets:\n"]
        for t in tickets:
            props  = t.get("properties", {})
            title  = props.get("Question", {}).get("title", [{}])[0].get("plain_text", "Unknown")
            status = props.get("Status", {}).get("select", {}).get("name", "Unknown")
            url    = t.get("url", "")
            lines.append(f"• {title[:80]} — **{status}** [View]({url})")

        return {"response": "\n".join(lines)}

    except Exception as e:
        print(f"[{trace_id}] fetch_ticket_node → failed: {e}")
        return {"response": "Could not fetch ticket status. Please try again."}
