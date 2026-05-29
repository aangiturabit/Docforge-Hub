import json
from backend.rag.cache.redis_client import get_redis

SESSION_TTL = 1800 


def load_session(session_id: str) -> list:
    """Load conversation history from Redis."""
    try:
        r   = get_redis()
        if not r:
            return []
        val = r.get(f"agent_session:{session_id}")
        return json.loads(val) if val else []
    except Exception as e:
        print(f"Redis load_session failed: {e}")
        return []


def save_session(session_id: str, messages: list):
    """Save conversation history to Redis with TTL."""
    try:
        r = get_redis()
        if not r:
            return
        # Keep last 20 turns only
        trimmed = messages[-20:] if len(messages) > 20 else messages
        r.setex(
            f"agent_session:{session_id}",
            SESSION_TTL,
            json.dumps(trimmed)
        )
    except Exception as e:
        print(f"Redis save_session failed: {e}")


def append_message(session_id: str, role: str, content: str):
    """Append one message turn to session."""
    messages = load_session(session_id)
    messages.append({"role": role, "content": content})
    save_session(session_id, messages)


def clear_session(session_id: str):
    """Clear session from Redis."""
    try:
        r = get_redis()
        if r:
            r.delete(f"agent_session:{session_id}")
    except Exception as e:
        print(f"Redis clear_session failed: {e}")