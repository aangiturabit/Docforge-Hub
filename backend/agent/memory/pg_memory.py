import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(".env")


def get_db_connection():
    import psycopg2
    return psycopg2.connect(os.getenv("DATABASE_URL"))


def ensure_table():
    """
    Creates agent_conversations table if not exists.
    Safe to call on every startup.
    """
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_conversations (
                id          SERIAL PRIMARY KEY,
                session_id  TEXT        NOT NULL,
                role        TEXT        NOT NULL,
                content     TEXT        NOT NULL,
                intent      TEXT,
                trace_id    TEXT,
                created_at  TIMESTAMP   DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_agent_session
                ON agent_conversations(session_id);
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"ensure_table failed: {e}")


def save_message(
    session_id : str,
    role       : str,
    content    : str,
    intent     : str = None,
    trace_id   : str = None,
):
    """Persist one conversation turn to PostgreSQL."""
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute(
            """
            INSERT INTO agent_conversations
                (session_id, role, content, intent, trace_id)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (session_id, role, content, intent, trace_id)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"save_message failed: {e}")


def load_history(session_id: str, limit: int = 20) -> list:
    """
    Load last N turns for a session from PostgreSQL.
    Used when Redis cache has expired.
    """
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute(
            """
            SELECT role, content FROM agent_conversations
            WHERE session_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (session_id, limit)
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        # Reverse to get chronological order
        return [{"role": r[0], "content": r[1]} for r in reversed(rows)]
    except Exception as e:
        print(f"load_history failed: {e}")
        return []


def get_all_sessions() -> list:
    """Returns list of unique session IDs with last activity."""
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute(
            """
            SELECT session_id, MAX(created_at) as last_active
            FROM agent_conversations
            GROUP BY session_id
            ORDER BY last_active DESC
            LIMIT 50
            """
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [{"session_id": r[0], "last_active": str(r[1])} for r in rows]
    except Exception as e:
        print(f"get_all_sessions failed: {e}")
        return []