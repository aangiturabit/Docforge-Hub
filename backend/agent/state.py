from typing import TypedDict, Optional


class AgentState(TypedDict):
    # ── Conversation ──────────────────────────────
    session_id      : str           
    user_input      : str            
    messages        : list           
                                   

    # ── Intent ────────────────────────────────────
    intent          : Optional[str]  
    clarification   : Optional[str] 

    # ── Retrieval ─────────────────────────────────
    retrieved_chunks: list           
    confidence      : Optional[str]
    
    # ── Answer ────────────────────────────────────
    answer          : Optional[str]  
    citations       : list           

    # ── Ticket ────────────────────────────────────
    ticket_exists   : Optional[bool] 
    ticket_id       : Optional[str] 
    ticket_url      : Optional[str] 
    ticket_question : Optional[str]
    cannot_answer   : bool


    response        : Optional[str]  
    trace_id        : Optional[str] 
