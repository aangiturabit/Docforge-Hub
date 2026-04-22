
import json
import os
import time

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage  
from langchain_core.output_parsers import JsonOutputParser
from langchain_openai import AzureChatOpenAI

from backend.utils.logger import get_logger

load_dotenv()

logger = get_logger("docforge.services.llm")

_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "8000"))

# ── Single LLM instance ───────────────────────────────────────────────────────
_llm = AzureChatOpenAI(
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


# ═══════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════

def _build_messages(system: str, prompt: str) -> list:
  
    return [
        SystemMessage(content=system),
        HumanMessage(content=prompt),
    ]


def _strip_markdown_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```json"):
        raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
    elif raw.startswith("```"):
        raw = raw.split("```", 1)[1].split("```", 1)[0].strip()
    return raw


# ═══════════════════════════════════════════════════════
# PLAIN TEXT GENERATION  (preview, section content, fallback)
# ═══════════════════════════════════════════════════════

_DEFAULT_TEXT_SYSTEM = (
    "You are a professional business document writer for a SaaS company. "
    "Generate complete, well-structured, professional document content. "
    "Return ONLY the document content — no commentary, no explanations, no markdown."
)


def generate_with_llm(
    prompt: str,
    system_prompt: str = None,
) -> str:
    """
    Generate plain text (documents, previews, section content).
    Returns the raw text string.
    Raises RuntimeError on failure.
    """
    system   = system_prompt or _DEFAULT_TEXT_SYSTEM
    messages = _build_messages(system, prompt)
    t0       = time.monotonic()

    logger.info("generate_with_llm | prompt_len=%d", len(prompt))
    logger.debug("generate_with_llm | system=%s…", system[:120])

    # ── Attempt 1 ─────────────────────────────────────────────────────────────
    try:
        response = _llm.invoke(messages)
        content  = (response.content or "").strip()

        if not content:
            raise RuntimeError("LLM returned empty response")

        logger.info(
            "generate_with_llm: success | chars=%d elapsed=%.1fs",
            len(content), time.monotonic() - t0,
        )
        return content

    except Exception as exc:
        logger.warning("generate_with_llm: attempt 1 failed (%s) — retrying", exc)

    # ── Attempt 2 ─────────────────────────────────────────────────────────────
    try:
        retry_messages = _build_messages(system, prompt + "\n\nGenerate the complete document content now.")
        response = _llm.invoke(retry_messages)
        content  = (response.content or "").strip()

        if not content:
            raise RuntimeError("LLM returned empty response on retry")

        logger.info(
            "generate_with_llm: retry success | chars=%d elapsed=%.1fs",
            len(content), time.monotonic() - t0,
        )
        return content

    except Exception as retry_exc:
        elapsed = time.monotonic() - t0
        logger.error("generate_with_llm: both attempts failed after %.1fs — %s", elapsed, retry_exc)
        raise RuntimeError(f"LLM text generation failed: {retry_exc}") from retry_exc


# ═══════════════════════════════════════════════════════
# JSON GENERATION  (question forms, custom JSON payloads)
# ═══════════════════════════════════════════════════════

def generate_with_llm_json(
    user_prompt: str,
    system_prompt: str,
) -> str:
    
    if not system_prompt:
        raise ValueError("system_prompt is required for JSON generation")

    parser   = JsonOutputParser()
    messages = _build_messages(system_prompt, user_prompt)
    t0       = time.monotonic()

    logger.info("generate_with_llm_json | prompt_len=%d", len(user_prompt))

    # ── Attempt 1 ─────────────────────────────────────────────────────────────
    try:
        response = _llm_json.invoke(messages)
        raw      = _strip_markdown_fences(response.content or "")

        if not raw:
            raise ValueError("LLM returned empty JSON response")

        content = json.dumps(parser.parse(raw))
        logger.info("generate_with_llm_json: success | elapsed=%.1fs", time.monotonic() - t0)
        return content

    except Exception as first_exc:
        logger.warning("generate_with_llm_json: attempt 1 failed (%s) — retrying", first_exc)

    # ── Attempt 2 ─────────────────────────────────────────────────────────────
    try:
        retry_messages = _build_messages(
            system_prompt,
            user_prompt + "\n\nReturn ONLY valid JSON — nothing else.",
        )
        response = _llm_json.invoke(retry_messages)
        raw      = _strip_markdown_fences(response.content or "")

        if not raw:
            raise ValueError("LLM returned empty JSON on retry")

        content = json.dumps(parser.parse(raw))
        logger.info(
            "generate_with_llm_json: retry success | elapsed=%.1fs", time.monotonic() - t0
        )
        return content

    except Exception as retry_exc:
        elapsed = time.monotonic() - t0
        logger.error(
            "generate_with_llm_json: both attempts failed after %.1fs — %s", elapsed, retry_exc
        )
        raise RuntimeError(f"JSON generation failed after retry: {retry_exc}") from retry_exc


# ═══════════════════════════════════════════════════════
# STRUCTURED DOCUMENT GENERATION  (
# ═══════════════════════════════════════════════════════

def generate_structured_document(
    system_prompt: str,
    user_prompt: str,
) -> dict:
    """
    Generate a structured document as a Python dict.
    Raises RuntimeError on failure.
    """
    parser   = JsonOutputParser()
    messages = _build_messages(system_prompt, user_prompt)
    t0       = time.monotonic()

    logger.info("generate_structured_document | prompt_len=%d", len(user_prompt))

    # ── Attempt 1 ─────────────────────────────────────────────────────────────
    try:
        response = _llm_json.invoke(messages)
        raw      = _strip_markdown_fences(response.content or "")

        if not raw:
            raise ValueError("LLM returned empty structured response")

        result = parser.parse(raw)
        if not isinstance(result, dict):
            raise TypeError(f"Expected dict, got {type(result).__name__}")

        logger.info(
            "generate_structured_document: success | sections=%d elapsed=%.1fs",
            len(result.get("sections", [])), time.monotonic() - t0,
        )
        return result

    except Exception as first_exc:
        logger.warning(
            "generate_structured_document: attempt 1 failed (%s) — retrying", first_exc
        )

    # ── Attempt 2 ─────────────────────────────────────────────────────────────
    try:
        retry_messages = _build_messages(
            system_prompt,
            user_prompt
            + "\n\nCRITICAL: Return ONLY the JSON object. "
            "No text before or after. No markdown. Pure JSON only.",
        )
        response = _llm_json.invoke(retry_messages)
        raw      = _strip_markdown_fences(response.content or "")

        if not raw:
            raise ValueError("LLM returned empty JSON on retry")

        result = parser.parse(raw)
        if not isinstance(result, dict):
            raise TypeError(f"Retry returned {type(result).__name__}, expected dict")

        logger.info(
            "generate_structured_document: retry success | sections=%d elapsed=%.1fs",
            len(result.get("sections", [])), time.monotonic() - t0,
        )
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