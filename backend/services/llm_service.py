
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

_LLM_KWARGS = dict(
    azure_deployment=os.getenv("AZURE_LLM_DEPLOYMENT_41_MINI"),
    azure_endpoint=os.getenv("AZURE_LLM_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_LLM_KEY"),
    api_version=os.getenv("AZURE_LLM_API_VERSION"),
    max_tokens=_MAX_TOKENS,
)

_llm = AzureChatOpenAI(**_LLM_KWARGS, temperature=0.2)
_llm_json = AzureChatOpenAI(
    **_LLM_KWARGS,
    temperature=0.0,
    model_kwargs={"response_format": {"type": "json_object"}},
)

_DEFAULT_SYSTEM = (
    "You are a professional business document writer for a SaaS company. "
    "Return ONLY the document content — no commentary."
)


# ── Helpers ─────────────────────────────────────────────────────────────

def _invoke_with_retry(llm, messages, retry_suffix: str, label: str) -> str:
    t0 = time.monotonic()

    for attempt in range(2):
        try:
            msgs = messages if attempt == 0 else messages[:-1] + [
                HumanMessage(content=messages[-1].content + retry_suffix)
            ]

            raw = (llm.invoke(msgs).content or "").strip()
            if not raw:
                raise ValueError("Empty response")

            logger.info(
                "%s: attempt %d ok | chars=%d elapsed=%.1fs",
                label, attempt + 1, len(raw), time.monotonic() - t0
            )
            return raw

        except Exception as exc:
            logger.warning("%s: attempt %d failed — %s", label, attempt + 1, exc)

    raise RuntimeError(f"{label} failed after retry")


def _clean_json(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) >= 2:
            raw = parts[1]
    if raw.startswith("json"):
        raw = raw[4:]
    return raw.strip()


def _generate_json(system_prompt: str, user_prompt: str, label: str) -> dict:
    parser = JsonOutputParser()

    raw = _invoke_with_retry(
        _llm_json,
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
        "\n\nReturn ONLY valid JSON.",
        label,
    )

    cleaned = _clean_json(raw)

    try:
        return parser.parse(cleaned)
    except Exception as e:
        logger.error("JSON parse failed | raw=%s", cleaned[:1000])
        raise ValueError(f"Invalid JSON from LLM: {e}")


# ── Public API ───────────────────────────────────────────────────────────

def generate_with_llm(prompt: str, system_prompt: str = None) -> str:
    return _invoke_with_retry(
        _llm,
        [SystemMessage(content=system_prompt or _DEFAULT_SYSTEM), HumanMessage(content=prompt)],
        "\n\nGenerate the complete document content now.",
        "generate_with_llm",
    )


def generate_with_llm_json(user_prompt: str, system_prompt: str) -> dict:
    if not system_prompt:
        raise ValueError("system_prompt is required for JSON generation")

    return _generate_json(system_prompt, user_prompt, "generate_with_llm_json")


def generate_structured_document(system_prompt: str, user_prompt: str) -> dict:
    result = _generate_json(system_prompt, user_prompt, "generate_structured_document")

    if not isinstance(result, dict):
        raise TypeError(f"Expected dict, got {type(result).__name__}")

    logger.info("sections=%d", len(result.get("sections", [])))
    return result