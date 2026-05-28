# ─────────────────────────────────────────────
# CITATION PARSER
# ─────────────────────────────────────────────
def parse_citations(response, chunks: list) -> dict:
    """
    Merges LLM structured response with retrieved chunk metadata.

    response → RAGResponse from llm_client.py
    chunks   → list of chunks from dense.search()

    Returns final dict ready for API response:
    {
      answer           → answer text with inline [Source N]
      citations        → list with full metadata per cited source
      retrieved_chunks → all chunks that were retrieved (for inspector panel)
      confidence       → high / medium / low
    }
    """
    # Build lookup: source_number → chunk metadata
    # chunks list is 1-indexed to match [Source N] labels
    chunk_lookup = {i + 1: chunk for i, chunk in enumerate(chunks)}

    # Build citations list
    citations = []
    for citation in response.citations:
        n     = citation.source_number
        chunk = chunk_lookup.get(n, {})

        citations.append({
            "source_number": n,
            "breadcrumb"   : citation.breadcrumb,
            "doc_type"     : citation.doc_type,
            "department"   : citation.department,
            "title"        : chunk.get("title", ""),
            "url"          : chunk.get("url", ""),
            "score"        : chunk.get("score", 0.0),
            "compare_side" : chunk.get("compare_side", ""),
        })

    # Build retrieved chunks list for Streamlit inspector panel
    retrieved = []
    for i, chunk in enumerate(chunks, start=1):
        retrieved.append({
            "source_number": i,
            "breadcrumb"   : chunk.get("breadcrumb", ""),
            "doc_type"     : chunk.get("doc_type", ""),
            "department"   : chunk.get("department", ""),
            "score"        : chunk.get("score", 0.0),
            "preview"      : chunk.get("text", ""),
            "compare_side" : chunk.get("compare_side", ""),
        })

    return {
        "answer"           : response.answer,
        "citations"        : citations,
        "retrieved_chunks" : retrieved,
        "confidence"       : response.confidence,
    }
