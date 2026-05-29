import os
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
from backend.agent.state import AgentState
from backend.agent.nodes.intent   import intent_node
from backend.agent.nodes.clarify  import clarify_node
from backend.agent.nodes.retrieve import retrieve_node
from backend.agent.nodes.evaluate import evaluate_node
from backend.agent.nodes.answer   import answer_node
from backend.agent.nodes.ticket   import (
    check_ticket_node,
    create_ticket_node,
    fetch_ticket_node,
)
from backend.agent.nodes.notify import notify_node

load_dotenv(".env")


# ─────────────────────────────────────────────
# ROUTING FUNCTIONS
# ─────────────────────────────────────────────
def route_intent(state: AgentState) -> str:
    intent = state.get("intent", "question")
    if intent == "unclear":
        return "clarify_node"
    elif intent == "create_ticket":
        return "check_ticket_node"
    elif intent == "ticket_status":
        return "fetch_ticket_node"
    else:
        return "retrieve_node"


def route_confidence(state: AgentState) -> str:
    confidence = state.get("confidence", "low")
    if confidence == "high":
        return "answer_node"
    elif confidence == "out_of_kb":
        return "notify_node"
    else:
        return "notify_node"


def route_ticket_exists(state: AgentState) -> str:
    if state.get("ticket_exists"):
        return "notify_node"
    return "create_ticket_node"


# ─────────────────────────────────────────────
# BUILD GRAPH
# ─────────────────────────────────────────────
def build_graph():
    graph = StateGraph(AgentState)

    # Add all nodes
    graph.add_node("intent_node",        intent_node)
    graph.add_node("clarify_node",       clarify_node)
    graph.add_node("retrieve_node",      retrieve_node)
    graph.add_node("evaluate_node",      evaluate_node)
    graph.add_node("answer_node",        answer_node)
    graph.add_node("check_ticket_node",  check_ticket_node)
    graph.add_node("create_ticket_node", create_ticket_node)
    graph.add_node("fetch_ticket_node",  fetch_ticket_node)
    graph.add_node("notify_node",        notify_node)

    # Entry point
    graph.set_entry_point("intent_node")

    # Intent routing
    graph.add_conditional_edges(
        "intent_node",
        route_intent,
        {
            "clarify_node"     : "clarify_node",
            "retrieve_node"    : "retrieve_node",
            "check_ticket_node" : "check_ticket_node",
            "fetch_ticket_node": "fetch_ticket_node",
        }
    )

    # Clarify → END (waits for next user message)
    graph.add_edge("clarify_node", END)

    # Retrieve → Evaluate
    graph.add_edge("retrieve_node", "evaluate_node")

    # Evaluate routing
    graph.add_conditional_edges(
        "evaluate_node",
        route_confidence,
        {
            "answer_node" : "answer_node",
            "notify_node" : "notify_node",
        }
    )

    # Answer → Notify → END
    graph.add_edge("answer_node",    "notify_node")
    graph.add_edge("notify_node",    END)

    # Fetch ticket → END
    graph.add_edge("fetch_ticket_node", END)

    # Create ticket flow
    graph.add_conditional_edges(
        "check_ticket_node",
        route_ticket_exists,
        {
            "notify_node"       : "notify_node",
            "create_ticket_node": "create_ticket_node",
        }
    )
    graph.add_edge("create_ticket_node", "notify_node")

    return graph.compile()


# Compiled graph instance
agent_graph = build_graph()
