
# from openai import AzureOpenAI
# from dotenv import load_dotenv
# import os
# import hashlib
# import json

# load_dotenv()

# client = AzureOpenAI(
#     api_key=os.getenv("AZURE_OPENAI_LLM_KEY"),
#     api_version=os.getenv("AZURE_LLM_API_VERSION"),
#     azure_endpoint=os.getenv("AZURE_LLM_ENDPOINT")
# )

# deployment = os.getenv("AZURE_LLM_DEPLOYMENT_41_MINI")

# # ─────────────────────────────────────────
# # RESPONSE CACHE
# # ─────────────────────────────────────────
# _llm_cache: dict = {}

# # ✅ DEBUG FLAG (for prompt visibility in logs)
# DEBUG = False


# def _cache_key(prompt: str, system: str, temperature: float) -> str:
#     """Generate stable cache key (includes temperature for correctness)"""
#     return hashlib.md5(f"{system}:{prompt}:{temperature}".encode()).hexdigest()


# # ─────────────────────────────────────────
# # DOCUMENT GENERATION (Free-form Markdown/Text)
# # ─────────────────────────────────────────
# def generate_with_llm(
#     prompt: str,
#     system_prompt: str = None
# ) -> str:
#     """
#     Used for generating full documents (Markdown output).
#     """
#     system = system_prompt or (
#         "You are a professional business document writer for a SaaS company. "
#         "Generate complete, well-structured, professional, and lengthy documents with proper formatting and in-depth explanations. "
#         "Return ONLY the document content with no extra commentary or explanations."
#     )

#     temperature = 0.3
#     cache_key = _cache_key(prompt, system, temperature)

#     # ✅ Cache check
#     if cache_key in _llm_cache:
#         return _llm_cache[cache_key]

#     # ✅ Debug logging 
#     if DEBUG:
#         print("\n===== SYSTEM PROMPT =====")
#         print(system)
#         print("\n===== USER PROMPT =====")
#         print(prompt[:1000]) 

#     try:
#         response = client.chat.completions.create(
#             model=deployment,
#             messages=[
#                 {"role": "system", "content": system},
#                 {"role": "user", "content": prompt}
#             ],
#             max_tokens=4000,
#             temperature=temperature,
#         )

#         content = response.choices[0].message.content

#         # ✅ Safety check
#         if not content:
#             raise RuntimeError("LLM returned empty response")

#         content = content.strip()

#         _llm_cache[cache_key] = content
#         return content

#     except Exception as e:
#         raise RuntimeError(
#             f"LLM document generation failed: {str(e)} | Prompt snippet: {prompt[:200]}"
#         )


# # ─────────────────────────────────────────
# # JSON GENERATION (for smart questions)
# # ─────────────────────────────────────────
# def generate_with_llm_json(
#     user_prompt: str,
#     system_prompt: str
# ) -> str:
#     """
#     Used in question_service.py for generating structured questions.
#     Uses JSON mode for better reliability.
#     """
#     if not system_prompt:
#         raise ValueError("system_prompt is required for generate_with_llm_json")

#     temperature = 0.0
#     cache_key = _cache_key(user_prompt, system_prompt, temperature)

#     # ✅ Cache check
#     if cache_key in _llm_cache:
#         return _llm_cache[cache_key]

#     # ✅ Debug logging 
#     if DEBUG:
#         print("\n===== SYSTEM PROMPT (JSON) =====")
#         print(system_prompt)
#         print("\n===== USER PROMPT (JSON) =====")
#         print(user_prompt[:1000])

#     try:
#         response = client.chat.completions.create(
#             model=deployment,
#             messages=[
#                 {"role": "system", "content": system_prompt},
#                 {"role": "user", "content": user_prompt}
#             ],
#             max_tokens=2000,
#             temperature=temperature,
#             response_format={"type": "json_object"}
#         )

#         content = response.choices[0].message.content

#         # ✅ Safety check
#         if not content:
#             raise RuntimeError("LLM returned empty JSON response")

#         content = content.strip()

#         # ✅ Clean markdown wrappers if present
#         if content.startswith("```json"):
#             content = content.split("```json", 1)[1].split("```", 1)[0].strip()
#         elif content.startswith("```"):
#             content = content.split("```", 1)[1].split("```", 1)[0].strip()

#         # ✅ Validate JSON
#         json.loads(content)

#         _llm_cache[cache_key] = content
#         return content

#     except json.JSONDecodeError as e:
#         raise RuntimeError(
#             f"LLM returned invalid JSON: {str(e)} | Response snippet: {content[:300]}"
#         )
#     except Exception as e:
#         raise RuntimeError(
#             f"LLM JSON generation failed: {str(e)} | Prompt snippet: {user_prompt[:200]}"
#         )

from langchain_openai import AzureChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.messages import SystemMessage, HumanMessage
from dotenv import load_dotenv
import os
import hashlib
import json

load_dotenv()

# ─────────────────────────────────────────
# LLM INSTANCES
# Two separate — text vs JSON structured
# ─────────────────────────────────────────
_llm_text = AzureChatOpenAI(
    azure_deployment=os.getenv("AZURE_LLM_DEPLOYMENT_41_MINI"),
    azure_endpoint=os.getenv("AZURE_LLM_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_LLM_KEY"),
    api_version=os.getenv("AZURE_LLM_API_VERSION"),
    temperature=0.3,
    max_tokens=4000
)

_llm_json = AzureChatOpenAI(
    azure_deployment=os.getenv("AZURE_LLM_DEPLOYMENT_41_MINI"),
    azure_endpoint=os.getenv("AZURE_LLM_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_LLM_KEY"),
    api_version=os.getenv("AZURE_LLM_API_VERSION"),
    temperature=0.0,
    max_tokens=4000,
    model_kwargs={"response_format": {"type": "json_object"}}
)

DEBUG = False

# ─────────────────────────────────────────
# CACHE
# ─────────────────────────────────────────
_llm_cache: dict = {}


def _cache_key(system: str, prompt: str, mode: str) -> str:
    return hashlib.md5(f"{mode}:{system}:{prompt}".encode()).hexdigest()


def _build_messages(system: str, prompt: str) -> list:
    """
    Uses LangChain ChatPromptTemplate to build messages.
    No chain — just formats and returns message list.
    """
    template = ChatPromptTemplate.from_messages([
        ("system", "{system}"),
        ("human", "{prompt}")
    ])
    return template.format_messages(system=system, prompt=prompt)


# ─────────────────────────────────────────
# TEXT GENERATION
# LangChain prompting — no chain
# ─────────────────────────────────────────
def generate_with_llm(
    prompt: str,
    system_prompt: str = None
) -> str:
    system = system_prompt or (
        "You are a professional business document writer for a SaaS company. "
        "Generate complete, well-structured, professional documents. "
        "Return ONLY the document content — no commentary, no explanations."
    )

    key = _cache_key(system, prompt, "text")
    if key in _llm_cache:
        return _llm_cache[key]

    if DEBUG:
        print("\n[LLM TEXT] SYSTEM:", system[:300])
        print("[LLM TEXT] PROMPT:", prompt[:500])

    # Build messages using LangChain PromptTemplate
    messages = _build_messages(system, prompt)

    try:
        # Direct LLM invoke — no chain
        response = _llm_text.invoke(messages)

        # LangChain returns AIMessage — extract content
        content = response.content

        if not content or not content.strip():
            raise RuntimeError("LLM returned empty response")

        content = content.strip()
        _llm_cache[key] = content
        return content

    except Exception as e:
        raise RuntimeError(f"LLM text generation failed: {str(e)}")


# ─────────────────────────────────────────
# JSON GENERATION
# LangChain prompting + JsonOutputParser — no chain
# Used for question_service
# ─────────────────────────────────────────
def generate_with_llm_json(
    user_prompt: str,
    system_prompt: str
) -> str:
    if not system_prompt:
        raise ValueError("system_prompt required for JSON generation")

    key = _cache_key(system_prompt, user_prompt, "json")
    if key in _llm_cache:
        return _llm_cache[key]

    if DEBUG:
        print("\n[LLM JSON] SYSTEM:", system_prompt[:300])
        print("[LLM JSON] PROMPT:", user_prompt[:500])

    messages = _build_messages(system_prompt, user_prompt)
    parser = JsonOutputParser()

    try:
        # Direct LLM invoke — no chain
        response = _llm_json.invoke(messages)
        raw = response.content

        if not raw or not raw.strip():
            raise RuntimeError("LLM returned empty JSON response")

        # Clean markdown wrappers if present
        clean = raw.strip()
        if clean.startswith("```json"):
            clean = clean.split("```json", 1)[1].split("```", 1)[0].strip()
        elif clean.startswith("```"):
            clean = clean.split("```", 1)[1].split("```", 1)[0].strip()

        # Parse using LangChain JsonOutputParser
        parsed = parser.parse(clean)
        content = json.dumps(parsed)
        _llm_cache[key] = content
        return content

    except Exception:
        # Retry once with explicit reminder
        retry_prompt = user_prompt + "\n\nReturn ONLY valid JSON — nothing else."
        retry_messages = _build_messages(system_prompt, retry_prompt)

        try:
            response = _llm_json.invoke(retry_messages)
            raw = response.content.strip()

            if raw.startswith("```json"):
                raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
            elif raw.startswith("```"):
                raw = raw.split("```", 1)[1].split("```", 1)[0].strip()

            parsed = parser.parse(raw)
            content = json.dumps(parsed)
            _llm_cache[key] = content
            return content

        except Exception as e:
            raise RuntimeError(f"JSON generation failed after retry: {str(e)}")


# ─────────────────────────────────────────
# STRUCTURED DOCUMENT GENERATION
# LangChain prompting + JsonOutputParser — no chain
# Used for PDF/DOCX structured pipeline
# ─────────────────────────────────────────
def generate_structured_document(
    system_prompt: str,
    user_prompt: str
) -> dict:
    key = _cache_key(system_prompt, user_prompt, "structured")
    if key in _llm_cache:
        return _llm_cache[key]

    if DEBUG:
        print("\n[LLM STRUCTURED] SYSTEM:", system_prompt[:300])
        print("[LLM STRUCTURED] PROMPT:", user_prompt[:500])

    messages = _build_messages(system_prompt, user_prompt)
    parser = JsonOutputParser()

    try:
        # Direct LLM invoke — no chain
        response = _llm_json.invoke(messages)
        raw = response.content

        if not raw or not raw.strip():
            raise RuntimeError("LLM returned empty structured response")

        clean = raw.strip()
        if clean.startswith("```json"):
            clean = clean.split("```json", 1)[1].split("```", 1)[0].strip()
        elif clean.startswith("```"):
            clean = clean.split("```", 1)[1].split("```", 1)[0].strip()

        # Parse using LangChain JsonOutputParser
        result = parser.parse(clean)

        if not isinstance(result, dict):
            raise RuntimeError(f"Expected dict, got {type(result)}")

        _llm_cache[key] = result
        return result

    except Exception:
        # Retry once
        retry_prompt = (
            user_prompt +
            "\n\nCRITICAL: Return ONLY the JSON object. "
            "No text before or after. No markdown. Pure JSON only."
        )
        retry_messages = _build_messages(system_prompt, retry_prompt)

        try:
            response = _llm_json.invoke(retry_messages)
            raw = response.content.strip()

            if raw.startswith("```json"):
                raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
            elif raw.startswith("```"):
                raw = raw.split("```", 1)[1].split("```", 1)[0].strip()

            result = parser.parse(raw)

            if not isinstance(result, dict):
                raise RuntimeError("Retry also returned non-dict")

            _llm_cache[key] = result
            return result

        except Exception as e:
            raise RuntimeError(f"Structured generation failed after retry: {str(e)}")