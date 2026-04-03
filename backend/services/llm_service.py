
from openai import AzureOpenAI
from dotenv import load_dotenv
import os
import hashlib
import json

load_dotenv()

client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_LLM_KEY"),
    api_version=os.getenv("AZURE_LLM_API_VERSION"),
    azure_endpoint=os.getenv("AZURE_LLM_ENDPOINT")
)

deployment = os.getenv("AZURE_LLM_DEPLOYMENT_41_MINI")

# ─────────────────────────────────────────
# RESPONSE CACHE
# ─────────────────────────────────────────
_llm_cache: dict = {}

# ✅ DEBUG FLAG (for prompt visibility in logs)
DEBUG = False


def _cache_key(prompt: str, system: str, temperature: float) -> str:
    """Generate stable cache key (includes temperature for correctness)"""
    return hashlib.md5(f"{system}:{prompt}:{temperature}".encode()).hexdigest()


# ─────────────────────────────────────────
# DOCUMENT GENERATION (Free-form Markdown/Text)
# ─────────────────────────────────────────
def generate_with_llm(
    prompt: str,
    system_prompt: str = None
) -> str:
    """
    Used for generating full documents (Markdown output).
    """
    system = system_prompt or (
        "You are a professional business document writer for a SaaS company. "
        "Generate complete, well-structured, professional, and lengthy documents. "
        "Return ONLY the document content with no extra commentary or explanations."
    )

    temperature = 0.3
    cache_key = _cache_key(prompt, system, temperature)

    # ✅ Cache check
    if cache_key in _llm_cache:
        return _llm_cache[cache_key]

    # ✅ Debug logging 
    if DEBUG:
        print("\n===== SYSTEM PROMPT =====")
        print(system)
        print("\n===== USER PROMPT =====")
        print(prompt[:1000]) 

    try:
        response = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            max_tokens=4000,
            temperature=temperature,
        )

        content = response.choices[0].message.content

        # ✅ Safety check
        if not content:
            raise RuntimeError("LLM returned empty response")

        content = content.strip()

        _llm_cache[cache_key] = content
        return content

    except Exception as e:
        raise RuntimeError(
            f"LLM document generation failed: {str(e)} | Prompt snippet: {prompt[:200]}"
        )


# ─────────────────────────────────────────
# JSON GENERATION (for smart questions)
# ─────────────────────────────────────────
def generate_with_llm_json(
    user_prompt: str,
    system_prompt: str
) -> str:
    """
    Used in question_service.py for generating structured questions.
    Uses JSON mode for better reliability.
    """
    if not system_prompt:
        raise ValueError("system_prompt is required for generate_with_llm_json")

    temperature = 0.0
    cache_key = _cache_key(user_prompt, system_prompt, temperature)

    # ✅ Cache check
    if cache_key in _llm_cache:
        return _llm_cache[cache_key]

    # ✅ Debug logging 
    if DEBUG:
        print("\n===== SYSTEM PROMPT (JSON) =====")
        print(system_prompt)
        print("\n===== USER PROMPT (JSON) =====")
        print(user_prompt[:1000])

    try:
        response = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=2000,
            temperature=temperature,
            response_format={"type": "json_object"}
        )

        content = response.choices[0].message.content

        # ✅ Safety check
        if not content:
            raise RuntimeError("LLM returned empty JSON response")

        content = content.strip()

        # ✅ Clean markdown wrappers if present
        if content.startswith("```json"):
            content = content.split("```json", 1)[1].split("```", 1)[0].strip()
        elif content.startswith("```"):
            content = content.split("```", 1)[1].split("```", 1)[0].strip()

        # ✅ Validate JSON
        json.loads(content)

        _llm_cache[cache_key] = content
        return content

    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"LLM returned invalid JSON: {str(e)} | Response snippet: {content[:300]}"
        )
    except Exception as e:
        raise RuntimeError(
            f"LLM JSON generation failed: {str(e)} | Prompt snippet: {user_prompt[:200]}"
        )