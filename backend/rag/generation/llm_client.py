import os
from dotenv import load_dotenv
from pydantic import BaseModel
from langchain_openai import AzureChatOpenAI
from backend.rag.generation.prompt_builder import build_prompt

load_dotenv("docforge/.env")


# ─────────────────────────────────────────────
# STRUCTURED OUTPUT SCHEMA
# ─────────────────────────────────────────────
class CitationItem(BaseModel):
    source_number: int
    breadcrumb   : str
    doc_type     : str
    department   : str


class RAGResponse(BaseModel):
    answer     : str
    citations  : list[CitationItem]
    confidence : str  


# ─────────────────────────────────────────────
# LLM CLIENT
# ─────────────────────────────────────────────
def get_llm():
    return AzureChatOpenAI(
        api_key            = os.getenv("AZURE_OPENAI_LLM_KEY"),
        azure_endpoint     = os.getenv("AZURE_LLM_ENDPOINT"),
        api_version        = os.getenv("AZURE_LLM_API_VERSION"),
        azure_deployment   = os.getenv("AZURE_LLM_DEPLOYMENT_41_MINI"),
        temperature        = 0,
    )


# ─────────────────────────────────────────────
# GENERATE ANSWER
# ─────────────────────────────────────────────
def generate_answer(question: str, chunks: list) -> RAGResponse:
 
    try:
        llm      = get_llm()
        messages = build_prompt(question, chunks)

        
        structured_llm = llm.with_structured_output(RAGResponse)

        response = structured_llm.invoke(messages)
        return response

    except Exception as e:
        print(f"LLM generation failed: {e}")
       
        return RAGResponse(
            answer     = "I could not generate an answer. Please try again.",
            citations  = [],
            confidence = "low",
        )