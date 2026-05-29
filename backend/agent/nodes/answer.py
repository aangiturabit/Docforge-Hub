from backend.agent.state import AgentState
from backend.rag.retrieval.dense import get_parent
from backend.rag.generation.llm_client import generate_answer
from backend.rag.generation.citation_parser import parse_citations


def answer_node(state: AgentState) -> dict:
    """
    Generates grounded answer using retrieved chunks.
    Expands children to parents for full context.
    Sets: answer, citations, response
    """
    trace_id = state.get("trace_id", "")
    question = state["user_input"]
    chunks   = state.get("retrieved_chunks", [])

    print(f"[{trace_id}] answer_node → generating answer")

    try:
        # Parent expansion — same as RAG pipeline
        expanded = []
        for child in chunks:
            parent_id = child.get("parent_id", "")
            if parent_id:
                parent = get_parent(parent_id)
                if parent:
                    expanded.append({**child, "text": parent["text"]})
                else:
                    expanded.append(child)
            else:
                expanded.append(child)

        response = generate_answer(question, expanded)
        result   = parse_citations(response, chunks)

        print(f"[{trace_id}] answer_node → confidence={result.get('confidence')}")

        return {
            "answer"       : result["answer"],
            "citations"    : result["citations"],
            "response"     : result["answer"],
            "cannot_answer": False,
        }

    except Exception as e:
        print(f"[{trace_id}] answer_node → failed: {e}")
        return {
            "answer"       : "I encountered an error generating the answer.",
            "citations"    : [],
            "response"     : "I encountered an error. Please try again.",
            "cannot_answer": False,
        }