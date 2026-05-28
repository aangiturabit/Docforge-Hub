import json
import hashlib
import redis
import os
from dotenv import load_dotenv

load_dotenv(".env")

REDIS_URL             = os.getenv("REDIS_URL", "redis://localhost:6379")
RETRIEVAL_CACHE_TTL   = 3600   
SESSION_TTL           = 1800   
NOTION_RATE_LIMIT     = 3     
NOTION_RATE_WINDOW    = 60     


# ─────────────────────────────────────────────
# CONNECTION
# ─────────────────────────────────────────────
def get_redis():
    try:
        client = redis.from_url(REDIS_URL, decode_responses=True)
        client.ping()
        return client
    except Exception as e:
        print(f"Redis connection failed: {e}")
        return None


# ─────────────────────────────────────────────
# JOB 1 — RETRIEVAL CACHE
# Key   : hash(question + filters)
# Value : retrieved chunks JSON
# ─────────────────────────────────────────────
def make_cache_key(question: str, doc_type: str = None, department: str = None, top_k: int = None) -> str:
    raw = f"{question}|{doc_type or ''}|{department or ''}|{top_k or ''}"
    return f"retrieval:{hashlib.md5(raw.encode()).hexdigest()}"


def get_cached_retrieval(question: str, doc_type: str = None, department: str = None, top_k: int = None):

    try:
        r   = get_redis()
        if not r:
            return None
        key = make_cache_key(question, doc_type, department, top_k)
        val = r.get(key)
        return json.loads(val) if val else None
    except Exception as e:
        print(f"Cache get failed: {e}")
        return None


def set_cached_retrieval(question: str, chunks: list, doc_type: str = None, department: str = None, top_k: int = None):

    try:
        r   = get_redis()
        if not r:
            return
        key = make_cache_key(question, doc_type, department, top_k)
        r.setex(key, RETRIEVAL_CACHE_TTL, json.dumps(chunks))
    except Exception as e:
        print(f"Cache set failed: {e}")


# ─────────────────────────────────────────────
# JOB 2 — SESSION CONTEXT
# Key   : session:{session_id}
# Value : list of conversation turns
# ─────────────────────────────────────────────
def get_session(session_id: str) -> list:
    
    try:
        r   = get_redis()
        if not r:
            return []
        val = r.get(f"session:{session_id}")
        return json.loads(val) if val else []
    except Exception as e:
        print(f"Session get failed: {e}")
        return []


def set_session(session_id: str, history: list):
  
    try:
        r = get_redis()
        if not r:
            return
        r.setex(f"session:{session_id}", SESSION_TTL, json.dumps(history))
    except Exception as e:
        print(f"Session set failed: {e}")


def append_to_session(session_id: str, role: str, content: str):
  
    history = get_session(session_id)
    history.append({"role": role, "content": content})
    # Keep last 10 turns only
    if len(history) > 10:
        history = history[-10:]
    set_session(session_id, history)


# ─────────────────────────────────────────────
# JOB 3 — NOTION RATE LIMITING
# Key   : notion_rate:{minute_timestamp}
# Value : count of API calls this minute
# ─────────────────────────────────────────────
def check_notion_rate_limit() -> bool:
  
    try:
        import time
        r = get_redis()
        if not r:
            return True  

        minute_key = f"notion_rate:{int(time.time() // NOTION_RATE_WINDOW)}"
        count      = r.get(minute_key)
        count      = int(count) if count else 0

        if count >= NOTION_RATE_LIMIT:
            return False

        pipe = r.pipeline()
        pipe.incr(minute_key)
        pipe.expire(minute_key, NOTION_RATE_WINDOW)
        pipe.execute()
        return True

    except Exception as e:
        print(f"Rate limit check failed: {e}")
        return True  
