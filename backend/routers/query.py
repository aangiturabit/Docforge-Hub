import hashlib
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional


from backend.rag.generation.llm_client import generate_answer
from backend.rag.retrieval.dense import get_parent
from backend.rag.retrieval.hybrid import hybrid_search
from backend.rag.generation.citation_parser import parse_citations
from backend.rag.cache.redis_client import get_session, append_to_session, get_redis

router = APIRouter(prefix="/rag", tags=["RAG Query"])
CHUNKS_PATH = Path("data/chunks.json")
COMPARE_CACHE_TTL = 3600


# ─────────────────────────────────────────────
# REQUEST MODELS
# ─────────────────────────────────────────────
class QueryRequest(BaseModel):
    question  : str
    doc_type  : Optional[str] = None
    department: Optional[str] = None
    top_k     : Optional[int] = 8
    session_id : Optional[str] = None   


class CompareRequest(BaseModel):
    question   : str
    doc_type_a : str
    doc_type_b : str
    top_k      : Optional[int] = 6


class SummarizeRequest(BaseModel):
    doc_type  : Optional[str] = None
    department: Optional[str] = None
    page_id   : Optional[str] = None


class EvaluateRequest(BaseModel):
    questions : list[str]
    doc_type  : Optional[str] = None
    department: Optional[str] = None
    top_k     : Optional[int] = 8
    run_name   : Optional[str] = "default" # for tracking in evaluation logs


def load_rag_metadata() -> dict:
    try:
        with CHUNKS_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"doc_types": [], "departments": []}

    items = []
    if isinstance(data, dict):
        items.extend(data.get("parents", []))
        items.extend(data.get("children", []))
    elif isinstance(data, list):
        items = data

    doc_types = set()
    departments = set()
    for item in items:
        meta = item.get("metadata", item)
        doc_type = meta.get("doc_type")
        department = meta.get("department")
        if doc_type and doc_type != "Unknown":
            doc_types.add(doc_type)
        if department and department != "Unknown":
            departments.add(department)

    return {
        "doc_types": sorted(doc_types),
        "departments": sorted(departments),
    }


def make_compare_cache_key(req: CompareRequest) -> str:
    raw = json.dumps(
        {
            "question": req.question.strip(),
            "doc_type_a": req.doc_type_a.strip(),
            "doc_type_b": req.doc_type_b.strip(),
            "top_k": req.top_k,
        },
        sort_keys=True,
    )
    return f"rag_compare:{hashlib.md5(raw.encode()).hexdigest()}"


def get_cached_compare(req: CompareRequest):
    try:
        r = get_redis()
        if not r:
            return None
        cached = r.get(make_compare_cache_key(req))
        return json.loads(cached) if cached else None
    except Exception as e:
        print(f"Compare cache get failed: {e}")
        return None


def set_cached_compare(req: CompareRequest, result: dict):
    try:
        r = get_redis()
        if not r:
            return
        r.setex(make_compare_cache_key(req), COMPARE_CACHE_TTL, json.dumps(result))
    except Exception as e:
        print(f"Compare cache set failed: {e}")


# ─────────────────────────────────────────────
# HELPER — Parent Expansion
# Retrieval finds children (focused, precise)
# LLM gets parent text (full section context)
# Citations always show child breadcrumb
# ─────────────────────────────────────────────
def expand_with_parents(chunks: list) -> list:
    """
    For each retrieved child chunk:
      - fetch its parent section from chunks.json
      - replace text with parent text for richer LLM context
      - keep all child metadata intact for citations
    """
    expanded = []
    for child in chunks:
        parent_id = child.get("parent_id", "")
        if parent_id:
            parent = get_parent(parent_id)
            if parent:
                expanded.append({
                    **child,
                    "text": parent["text"],
                })
            else:
                expanded.append(child)
        else:
            expanded.append(child)
    return expanded


# ─────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────
@router.get("/rag-metadata")
async def rag_metadata():
    return load_rag_metadata()


@router.post("/rag-query")
async def rag_query(req: QueryRequest):
    """
    Main Q&A endpoint.
    1. Search children (semantic + precise retrieval)
    2. Expand to parents (full context for LLM)
    3. Generate grounded answer with citations
    """
    try:
        chunks = hybrid_search(
            question   = req.question,
            top_k      = req.top_k,
            doc_type   = req.doc_type,
            department = req.department,
        )

        if not chunks:
            return {
                "answer"          : "I could not find relevant documents.",
                "citations"       : [],
                "retrieved_chunks": [],
                "confidence"      : "low",
            }

        expanded = expand_with_parents(chunks)
        response = generate_answer(req.question, expanded)
        result   = parse_citations(response, chunks)
        if req.session_id:
            append_to_session(req.session_id, "user", req.question)
            append_to_session(req.session_id, "assistant", result["answer"])

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rag-compare")
async def rag_compare(req: CompareRequest):
    """
    Compares two document types on a specific question.
    Retrieves children from both separately then expands to parents.
    """
    try:
        cached = get_cached_compare(req)
        if cached:
            cached["cache_hit"] = True
            return cached

        chunks_a = hybrid_search(
            question = req.question,
            top_k    = req.top_k,
            doc_type = req.doc_type_a,
        )
        chunks_b = hybrid_search(
            question = req.question,
            top_k    = req.top_k,
            doc_type = req.doc_type_b,
        )

        if not chunks_a and not chunks_b:
            return {
                "answer"    : "No relevant documents found for comparison.",
                "citations" : [],
                "confidence": "low",
            }

        for chunk in chunks_a:
            chunk["compare_side"] = "A"
        for chunk in chunks_b:
            chunk["compare_side"] = "B"

        all_chunks = chunks_a + chunks_b
        expanded   = expand_with_parents(all_chunks)
        for idx, chunk in enumerate(expanded):
            if idx < len(all_chunks):
                chunk["compare_side"] = all_chunks[idx].get("compare_side", "")

        compare_question = (
            f"Compare Document A ({req.doc_type_a}) and Document B ({req.doc_type_b}) "
            f"regarding: {req.question}.\n\n"
            "Return the answer in this exact structure:\n"
            "1. Start with a brief executive summary.\n"
            "2. Add a markdown table with columns: Aspect | Document A | Document B | Difference / Risk.\n"
            "3. Add bullets for Similarities, Differences, Conflicts / Gaps, Policy Implications, and Recommendation.\n"
            "4. Cite both documents inline using [Source N]. If evidence exists for only one side, say so clearly.\n"
            "5. Do not blend facts between the two documents."
        )

        response = generate_answer(compare_question, expanded)
        result   = parse_citations(response, all_chunks)
        result["doc_type_a"] = req.doc_type_a
        result["doc_type_b"] = req.doc_type_b
        result["cache_hit"] = False
        set_cached_compare(req, result)
        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rag-summarize")
async def rag_summarize(req: SummarizeRequest):
    """
    Summarizes a document type or department.
    Fetches top chunks then expands to parents for full context.
    """
    try:
        if not req.doc_type and not req.page_id and not req.department:
            raise HTTPException(
                status_code=400,
                detail="Provide at least one of: doc_type, department, page_id."
            )

        chunks = hybrid_search(
            question   = "summarize this document",
            top_k      = 8,
            doc_type   = req.doc_type,
            department = req.department,
        )

        if not chunks:
            return {
                "answer"    : "No relevant documents found.",
                "citations" : [],
                "confidence": "low",
            }

        expanded = expand_with_parents(chunks)

        question = (
            f"Provide a comprehensive summary of the {req.doc_type} document."
            if req.doc_type
            else "Provide a comprehensive summary of this document."
        )

        response = generate_answer(question, expanded)
        result   = parse_citations(response, chunks)
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rag-evaluate")
async def rag_evaluate(req: EvaluateRequest):
    """
    Runs batch questions through hybrid RAG pipeline.
    Computes RAGAS metrics using Azure OpenAI.
    Saves results to data/evaluations/{run_name}.json.
    """
    if not req.questions:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one question."
        )

    results = []

    for question in req.questions:
        try:
            chunks   = hybrid_search(
                question   = question,
                top_k      = req.top_k,
                doc_type   = req.doc_type,
                department = req.department,
            )
            expanded = expand_with_parents(chunks)
            response = generate_answer(question, expanded)
            result   = parse_citations(response, chunks)

            results.append({
                "question" : question,
                "answer"   : result["answer"],
                "contexts" : [c["text"] for c in expanded],
                "citations": result["citations"],
                "status"   : "success",
            })

        except Exception as e:
            results.append({
                "question" : question,
                "answer"   : "",
                "contexts" : [],
                "citations": [],
                "status"   : f"failed: {str(e)}",
            })

    successful = [r for r in results if r["status"] == "success"]

    if not successful:
        return {
            "total"  : len(req.questions),
            "results": results,
            "message": "No successful results to evaluate.",
        }

    try:
        from backend.rag.evaluation.ragas_runner import run_ragas_evaluation
        from functools import partial
        import asyncio

        config = {
            "top_k"     : req.top_k,
            "doc_type"  : req.doc_type,
            "department": req.department,
        }

        loop   = asyncio.get_event_loop()
        report = await loop.run_in_executor(
            None,
            partial(
                run_ragas_evaluation,
                results  = successful,
                run_name = req.run_name,
                config   = config,
            )
        )
        return report

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
