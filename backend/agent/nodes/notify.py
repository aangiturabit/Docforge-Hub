from backend.agent.state import AgentState


def notify_node(state: AgentState) -> dict:
    """
    Builds the final response shown to user.
    Handles four cases:
      1. Normal answer with citations
      2. Cannot answer — offer ticket button
      3. Out of knowledge base — offer ticket
      4. Ticket created / already exists
    """
    trace_id      = state.get("trace_id", "")
    confidence    = state.get("confidence")
    ticket_exists = state.get("ticket_exists")
    ticket_url    = state.get("ticket_url")
    answer        = state.get("answer")


    # Already has a response set (clarify / fetch_ticket)
    if state.get("response") and not answer:
        return {}

    answer = state.get("answer", "")

    # Ticket already exists
    if ticket_exists is True:
        return {
            "response": "A ticket for this question has already been raised. Our team will get back to you shortly.",
        }

    # Ticket just created
    if ticket_url:
        return {
            "response": f"A support ticket has been created for your question. You can track it here: {ticket_url}",
        }

    # Cannot answer — offer ticket to user
    if confidence in {"low", "out_of_kb"}:
        print(f"[{trace_id}] notify_node → {confidence} confidence, offering ticket")
        response = "I found some related documents but couldn't find a confident answer to your question."
        if confidence == "out_of_kb":
            response = "I could not find this information in the knowledge base."
        return {
            "response"     : f"{response} Would you like to raise a support ticket?",
            "cannot_answer": True,
        }

    # Normal answer
    return {"response": answer or "I could not generate a response."}
