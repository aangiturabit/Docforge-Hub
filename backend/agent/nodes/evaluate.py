from backend.agent.state import AgentState

# Minimum score threshold for high confidence
HIGH_CONFIDENCE_THRESHOLD = 0.5

# Minimum number of chunks needed
MIN_CHUNKS = 2


def evaluate_node(state: AgentState) -> dict:
    """
    Evaluates quality of retrieved chunks.

    Three outcomes:
      high       → enough evidence, proceed to answer
      low        → some evidence but weak, offer ticket to user
      out_of_kb  → no relevant docs at all, hard stop

    Sets: confidence
    """
    trace_id = state.get("trace_id", "")
    chunks   = state.get("retrieved_chunks", [])

    # No chunks at all → out of knowledge base
    if not chunks:
        print(f"[{trace_id}] evaluate_node → out_of_kb (no chunks)")
        return {"confidence": "out_of_kb"}

    # Score based on top chunk score + chunk count
    top_score   = max(c.get("score", 0) for c in chunks)
    chunk_count = len(chunks)

    print(f"[{trace_id}] evaluate_node → top_score={top_score:.3f} chunks={chunk_count}")

    if top_score >= HIGH_CONFIDENCE_THRESHOLD and chunk_count >= MIN_CHUNKS:
    # Extra check — reranker score if available
        top_reranker = max(
            (c.get("reranker_score", 0) for c in chunks),
            default=0
        )
        if top_reranker > 0:
            print(f"[{trace_id}] evaluate_node → high confidence (reranker={top_reranker:.3f})")
            return {"confidence": "high"}
        else:
            print(f"[{trace_id}] evaluate_node → low confidence (reranker scores zero)")
            return {"confidence": "low"}
    elif top_score > 0.2:
        print(f"[{trace_id}] evaluate_node → low confidence")
        return {"confidence": "low"}

    else:
        print(f"[{trace_id}] evaluate_node → out_of_kb (scores too low)")
        return {"confidence": "out_of_kb"}