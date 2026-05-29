import sys
sys.path.insert(0, '.')
from backend.agent.state import AgentState
from backend.rag.retrieval.hybrid import hybrid_search


def retrieve_node(state: AgentState) -> dict:
    """
    Calls hybrid RAG search using the user's question.
    Stores retrieved chunks in state for evaluate_node.
    """
    trace_id   = state.get("trace_id", "")
    user_input = state["user_input"]

    print(f"[{trace_id}] retrieve_node → searching: {user_input[:60]}")

    try:
        chunks = hybrid_search(
            question   = user_input,
            top_k      = 5,
        )
        print(f"[{trace_id}] retrieve_node → found {len(chunks)} chunks")
        return {"retrieved_chunks": chunks}

    except Exception as e:
        print(f"[{trace_id}] retrieve_node → failed: {e}")
        return {"retrieved_chunks": []}