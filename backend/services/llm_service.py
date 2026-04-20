

import hashlib
import json
import os
import time

from dotenv import load_dotenv
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import AzureChatOpenAI

from backend.utils.logger import get_logger

load_dotenv()

logger = get_logger("docforge.services.llm")

# ── Max tokens — configurable so large structured docs are never truncated ────
_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "8000"))

# ── LLM instances ─────────────────────────────────────────────────────────────
_llm_text = AzureChatOpenAI(
    azure_deployment=os.getenv("AZURE_LLM_DEPLOYMENT_41_MINI"),
    azure_endpoint=os.getenv("AZURE_LLM_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_LLM_KEY"),
    api_version=os.getenv("AZURE_LLM_API_VERSION"),
    temperature=0.2,
    max_tokens=_MAX_TOKENS,
)

_llm_json = AzureChatOpenAI(
    azure_deployment=os.getenv("AZURE_LLM_DEPLOYMENT_41_MINI"),
    azure_endpoint=os.getenv("AZURE_LLM_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_LLM_KEY"),
    api_version=os.getenv("AZURE_LLM_API_VERSION"),
    temperature=0.0,
    max_tokens=_MAX_TOKENS,
    model_kwargs={"response_format": {"type": "json_object"}},
)

# ── In-memory cache ───────────────────────────────────────────────────────────
_llm_cache: dict = {}


def _cache_key(mode: str, system: str, prompt: str) -> str:
    return hashlib.md5(f"{mode}:{system}:{prompt}".encode()).hexdigest()


def _build_messages(system: str, prompt: str) -> list:
    """Build LangChain message list from system + human strings."""
    template = ChatPromptTemplate.from_messages([
        ("system", "{system}"),
        ("human",  "{prompt}"),
    ])
    return template.format_messages(system=system, prompt=prompt)


def _strip_markdown_fences(raw: str) -> str:
    """Remove ```json ... ``` or ``` ... ``` wrappers if present."""
    raw = raw.strip()
    if raw.startswith("```json"):
        raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
    elif raw.startswith("```"):
        raw = raw.split("```", 1)[1].split("```", 1)[0].strip()
    return raw


# ═══════════════════════════════════════════════════════
# PLAIN TEXT GENERATION
# ═══════════════════════════════════════════════════════

def generate_with_llm(
    prompt: str,
    system_prompt: str = None,
) -> str:
    """
    Generate plain text (documents, previews, section content).
    Returns the raw text string.
    Raises RuntimeError on failure — caller decides how to handle.
    """
    system = system_prompt or (
        "You are a professional business document writer for a SaaS company. "
        "Generate complete, well-structured, professional documents. "
        "Return ONLY the document content — no commentary, no explanations."
    )

    key = _cache_key("text", system, prompt)
    if key in _llm_cache:
        logger.debug("generate_with_llm: cache hit | key=%s", key[:8])
        return _llm_cache[key]

    logger.info("generate_with_llm: calling LLM | prompt_len=%d", len(prompt))
    logger.debug("generate_with_llm: system=%s…", system[:120])
    logger.debug("generate_with_llm: prompt=%s…", prompt[:300])

    messages = _build_messages(system, prompt)
    t0       = time.monotonic()

    try:
        response = _llm_text.invoke(messages)
        content  = response.content

        if not content or not content.strip():
            raise RuntimeError("LLM returned empty response")

        content = content.strip()
        elapsed = time.monotonic() - t0

        logger.info(
            "generate_with_llm: success | chars=%d elapsed=%.1fs",
            len(content), elapsed,
        )

        _llm_cache[key] = content
        return content

    except Exception as exc:
        elapsed = time.monotonic() - t0
        logger.error("generate_with_llm: failed after %.1fs — %s", elapsed, exc)
        raise RuntimeError(f"LLM text generation failed: {exc}") from exc


# ═══════════════════════════════════════════════════════
# JSON GENERATION  
# ═══════════════════════════════════════════════════════

def generate_with_llm_json(
    user_prompt: str,
    system_prompt: str,
) -> str:
   
    if not system_prompt:
        raise ValueError("system_prompt is required for JSON generation")

    key = _cache_key("json", system_prompt, user_prompt)
    if key in _llm_cache:
        logger.debug("generate_with_llm_json: cache hit | key=%s", key[:8])
        return _llm_cache[key]

    logger.info("generate_with_llm_json: calling LLM | prompt_len=%d", len(user_prompt))

    parser   = JsonOutputParser()
    messages = _build_messages(system_prompt, user_prompt)
    t0       = time.monotonic()

    # ── Attempt 1 ─────────────────────────────────────────────────────────────
    try:
        response = _llm_json.invoke(messages)
        raw      = _strip_markdown_fences(response.content or "")

        if not raw:
            raise ValueError("LLM returned empty JSON response")

        parsed  = parser.parse(raw)
        content = json.dumps(parsed)
        elapsed = time.monotonic() - t0

        logger.info("generate_with_llm_json: success | elapsed=%.1fs", elapsed)
        _llm_cache[key] = content
        return content

    except Exception as first_exc:
        logger.warning(
            "generate_with_llm_json: attempt 1 failed (%s) — retrying", first_exc
        )

    # ── Attempt 2 — explicit JSON reminder ────────────────────────────────────
    retry_prompt    = user_prompt + "\n\nReturn ONLY valid JSON — nothing else."
    retry_messages  = _build_messages(system_prompt, retry_prompt)

    try:
        response = _llm_json.invoke(retry_messages)
        raw      = _strip_markdown_fences(response.content or "")

        if not raw:
            raise ValueError("LLM returned empty JSON on retry")

        parsed  = parser.parse(raw)
        content = json.dumps(parsed)
        elapsed = time.monotonic() - t0

        logger.info("generate_with_llm_json: retry succeeded | elapsed=%.1fs", elapsed)
        _llm_cache[key] = content
        return content

    except Exception as retry_exc:
        elapsed = time.monotonic() - t0
        logger.error(
            "generate_with_llm_json: both attempts failed after %.1fs — %s",
            elapsed, retry_exc,
        )
        raise RuntimeError(f"JSON generation failed after retry: {retry_exc}") from retry_exc


# ═══════════════════════════════════════════════════════
# STRUCTURED DOCUMENT GENERATION  
# ═══════════════════════════════════════════════════════

def generate_structured_document(
    system_prompt: str,
    user_prompt: str,
) -> dict:
  
    key = _cache_key("structured", system_prompt, user_prompt)
    if key in _llm_cache:
        logger.debug("generate_structured_document: cache hit | key=%s", key[:8])
        return _llm_cache[key]

    logger.info(
        "generate_structured_document: calling LLM | prompt_len=%d", len(user_prompt)
    )

    parser   = JsonOutputParser()
    messages = _build_messages(system_prompt, user_prompt)
    t0       = time.monotonic()

    # ── Attempt 1 ─────────────────────────────────────────────────────────────
    try:
        response = _llm_json.invoke(messages)
        raw      = _strip_markdown_fences(response.content or "")

        if not raw:
            raise ValueError("LLM returned empty structured response")

        result = parser.parse(raw)

        if not isinstance(result, dict):
            raise TypeError(f"Expected dict, got {type(result).__name__}")

        elapsed = time.monotonic() - t0
        sections = len(result.get("sections", []))
        logger.info(
            "generate_structured_document: success | sections=%d elapsed=%.1fs",
            sections, elapsed,
        )

        _llm_cache[key] = result
        return result

    except Exception as first_exc:
        logger.warning(
            "generate_structured_document: attempt 1 failed (%s) — retrying", first_exc
        )

    # ── Attempt 2 — explicit JSON reminder ────────────────────────────────────
    retry_prompt = (
        user_prompt
        + "\n\nCRITICAL: Return ONLY the JSON object. "
        "No text before or after. No markdown. Pure JSON only."
    )
    retry_messages = _build_messages(system_prompt, retry_prompt)

    try:
        response = _llm_json.invoke(retry_messages)
        raw      = _strip_markdown_fences(response.content or "")

        if not raw:
            raise ValueError("LLM returned empty JSON on retry")

        result = parser.parse(raw)

        if not isinstance(result, dict):
            raise TypeError(f"Retry returned {type(result).__name__}, expected dict")

        elapsed  = time.monotonic() - t0
        sections = len(result.get("sections", []))
        logger.info(
            "generate_structured_document: retry succeeded | sections=%d elapsed=%.1fs",
            sections, elapsed,
        )

        _llm_cache[key] = result
        return result

    except Exception as retry_exc:
        elapsed = time.monotonic() - t0
        logger.error(
            "generate_structured_document: both attempts failed after %.1fs — %s",
            elapsed, retry_exc,
        )
        raise RuntimeError(
            f"Structured document generation failed after retry: {retry_exc}"
        ) from retry_exc