from langchain_core.prompts import ChatPromptTemplate

# ─────────────────────────────────────────────
# SYSTEM PROMPT
# ─────────────────────────────────────────────
SYSTEM_PROMPT = """You are a precise and reliable Document Assistant.
You answer questions strictly using the context provided below.

RULES:
1. Only use information from the provided context.
2. Cite sources using [Source N] notation inline in your answer.
3. If the answer is not in the context, say exactly:
   "I could not find this information in the provided documents."
4. Never make up information.Do not hallucinate or use external knowledge.
5. Keep answers clear and professional .
6. Assign confidence realistically based on how well the context supports the answer.

CONTEXT:
{context}
"""

# ─────────────────────────────────────────────
# PROMPT TEMPLATE
# ─────────────────────────────────────────────
rag_prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "{question}"),
])


# ─────────────────────────────────────────────
# BUILD CONTEXT STRING FROM CHUNKS
# ─────────────────────────────────────────────
def build_context(chunks: list) -> str:
    """
    Takes retrieved chunks and formats them as labeled sources.

    Each chunk becomes:
      [Source 1 | Breadcrumb]
      chunk text...

    The LLM sees these labels and uses [Source N] in its answer.
    citation_parser.py then maps [Source N] back to real metadata.
    """
    if not chunks:
        return "No relevant documents found."

    lines = []
    for i, chunk in enumerate(chunks, start=1):
        label = f"[Source {i} | {chunk['breadcrumb']}]"
        lines.append(f"{label}\n{chunk['text']}")

    return "\n\n".join(lines)


# ─────────────────────────────────────────────
# BUILD FINAL PROMPT
# ─────────────────────────────────────────────
def build_prompt(question: str, chunks: list) -> list:
    """
    Returns formatted messages ready to send to the LLM.
    """
    context = build_context(chunks)
    return rag_prompt.format_messages(
        context  = context,
        question = question,
    )