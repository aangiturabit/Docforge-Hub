import json
from pathlib import Path
from fastapi import APIRouter, HTTPException

from backend.rag.ingestion.notion_client import fetch_all_documents
from backend.rag.ingestion.chunker import chunk_all_documents
from backend.rag.retrieval.dense import store_chunks
from backend.rag.retrieval.sparse import build_bm25_index

router = APIRouter(prefix="/rag", tags=["RAG Ingestion"])


@router.post("/rag-ingest")
async def rag_ingest():
    """
    Triggers full ingestion pipeline:
    1. Fetch all pages + blocks from Notion
    2. Structural + semantic chunking
    3. Embed children + store in ChromaDB
    """
    try:
        # Step 1 — fetch from Notion
        documents = fetch_all_documents()
        if not documents:
            raise HTTPException(
                status_code=404,
                detail="No documents found in Notion database."
            )

        # Step 2 — structural + semantic chunking
        chunks = chunk_all_documents(documents)

        if not chunks["children"]:
            raise HTTPException(
                status_code=500,
                detail="Chunking produced no output."
            )

        # Save to disk
        chunks_path = Path("data/chunks.json")
        chunks_path.parent.mkdir(parents=True, exist_ok=True)
        with chunks_path.open("w", encoding="utf-8") as f:
            json.dump(chunks, f, indent=2, ensure_ascii=False)

        # Step 3 — embed children + store in ChromaDB
        store_chunks(chunks["children"])
        build_bm25_index()

        return {
            "status"   : "success",
            "documents": len(documents),
            "parents"  : len(chunks["parents"]),
            "children" : len(chunks["children"]),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))