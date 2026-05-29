from backend.agent.state import AgentState


def clarify_node(state: AgentState) -> dict:
    """
    Formats the clarification question from intent_node
    into a response that gets shown to the user.
    Graph ends here — waits for user to reply.
    Next user message re-enters the graph from intent_node.
    """
    clarification = state.get("clarification") or "Could you please clarify your question?"
    trace_id      = state.get("trace_id", "")

    print(f"[{trace_id}] clarify_node → asking: {clarification[:60]}")

    return {
        "response"      : clarification,
        "cannot_answer" : False,
    }