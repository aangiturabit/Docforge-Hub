import os
import uuid
from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from backend.agent.state import AgentState

load_dotenv(".env")


def get_llm():
    return AzureChatOpenAI(
        api_key          = os.getenv("AZURE_OPENAI_LLM_KEY"),
        azure_endpoint   = os.getenv("AZURE_LLM_ENDPOINT"),
        api_version      = os.getenv("AZURE_LLM_API_VERSION"),
        azure_deployment = os.getenv("AZURE_LLM_DEPLOYMENT_41_MINI"),
        temperature      = 0,
    )


INTENT_SYSTEM = """You are an intent classifier for a document assistant.

Classify the user message into exactly one of these intents:
- "question"       : user wants information from documents
- "unclear"        : message is too vague to answer without clarification
- "create_ticket"  : user wants to create or raise a support ticket
- "ticket_status"  : user is asking about an existing support ticket

Respond ONLY with a JSON object in this exact format:
{
  "intent": "question" | "unclear" | "create_ticket" | "ticket_status",
  "clarification": "string if unclear, else null"
}

Rules:
- If intent is "unclear", clarification must contain the question to ask the user.
- If intent is "question", "create_ticket", or "ticket_status", clarification must be null.
- If the user says "create a ticket", "raise a ticket", "generate ticket", or asks to create a support request, use "create_ticket".
- Only use "ticket_status" when the user asks to view, fetch, check, or track existing tickets.
- Never add any text outside the JSON object.
"""


def intent_node(state: AgentState) -> dict:
    """
    Classifies user intent from the current message.
    Sets: intent, clarification, trace_id (if not set)
    """
    import json

    # Generate trace_id on first turn
    trace_id = state.get("trace_id") or str(uuid.uuid4())[:8]

    user_input = state["user_input"]
    messages   = state.get("messages", [])

    # Build context from last 3 turns for better intent classification
    context = ""
    if messages:
        recent = messages[-3:]
        context = "\n".join(
            f"{m['role'].upper()}: {m['content']}"
            for m in recent
        )

    prompt = f"{context}\nUSER: {user_input}" if context else user_input

    llm      = get_llm()
    response = llm.invoke([
        SystemMessage(content=INTENT_SYSTEM),
        HumanMessage(content=prompt),
    ])

    try:
        raw    = response.content.strip()
        parsed = json.loads(raw)
        intent        = parsed.get("intent", "question")
        clarification = parsed.get("clarification")
        if intent not in {"question", "unclear", "create_ticket", "ticket_status"}:
            intent = "question"
    except Exception:
        # fallback if LLM returns unexpected format
        intent        = "question"
        clarification = None

    print(f"[{trace_id}] intent_node → intent={intent}")

    return {
        "intent"       : intent,
        "clarification": clarification,
        "trace_id"     : trace_id,
    }
