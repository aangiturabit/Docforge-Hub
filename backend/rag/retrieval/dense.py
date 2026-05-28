import os
import json
import time
from pathlib import Path
from openai import AzureOpenAI
from dotenv import load_dotenv
import chromadb
from chromadb.config import Settings

load_dotenv(".env")

CHUNKS_PATH  = Path("data/chunks.json")
CHROMA_PATH  = Path("backend/rag/storage/chroma")
COLLECTION   = "rag_chunks"
BATCH_SIZE   = 10  


# ─────────────────────────────────────────────
# CLIENTS
# ─────────────────────────────────────────────
def get_embedding_client():
    return AzureOpenAI(
        api_key      = os.getenv("AZURE_OPENAI_EMB_KEY"),
        azure_endpoint = os.getenv("AZURE_EMB_ENDPOINT"),
        api_version  = os.getenv("AZURE_EMB_API_VERSION"),
    )


def get_chroma_collection():
    client = chromadb.PersistentClient(
        path     = str(CHROMA_PATH),
    )
    collection = client.get_or_create_collection(
        name     = COLLECTION,
        metadata = {"hnsw:space": "cosine"},
    )
    return collection


# ─────────────────────────────────────────────
# EMBED
# ─────────────────────────────────────────────
def embed_texts(client: AzureOpenAI, texts: list) -> list:
    try:
        response = client.embeddings.create(
            model = os.getenv("AZURE_EMB_DEPLOYMENT"),
            input = texts,
        )
        return [item.embedding for item in response.data]
    except Exception as e:
        print(f"Embedding failed: {e}")
        raise
# ─────────────────────────────────────────────
# STORE
# ─────────────────────────────────────────────
def store_chunks(chunks) -> None:
    if isinstance(chunks, dict):
        chunks = chunks["children"]
    emb_client = get_embedding_client()
    collection = get_chroma_collection()
    total    = len(chunks)
    stored   = 0
    failed   = 0

    print(f"Storing {total} chunks into ChromaDB...\n")

    for i in range(0, total, BATCH_SIZE):
        batch = chunks[i : i + BATCH_SIZE]

        try:
            # Embed using prefixed embed_text
            texts_to_embed = [c["embed_text"] for c in batch]
            embeddings     = embed_texts(emb_client, texts_to_embed)

            # Prepare ChromaDB inputs
            ids        = [c["chunk_id"]   for c in batch]
            documents  = [c["text"]       for c in batch]
            metadatas  = []

            for c in batch:
                # ChromaDB metadata must be flat + only str/int/float/bool
               metadatas.append({
                    "doc_type"  : c["metadata"]["doc_type"],
                    "department": c["metadata"]["department"],
                    "breadcrumb": c["metadata"]["breadcrumb"],
                    "parent_id" : c.get("parent_id", ""),
                    "page_id"   : c["page_id"],
                    "title"     : c["title"],
                    "url"       : c["url"],
                    "source"    : "notion",
})

            # Upsert — safe to re-run, existing chunks get updated
            collection.upsert(
                ids        = ids,
                embeddings = embeddings,
                documents  = documents,
                metadatas  = metadatas,
            )

            stored += len(batch)
            print(f"  [{stored}/{total}] stored batch {i//BATCH_SIZE + 1}")

        except Exception as e:
            failed += len(batch)
            print(f"  FAILED batch {i//BATCH_SIZE + 1}: {e}")

        # Small delay to respect Azure rate limits
        time.sleep(0.5)

    print(f"\nDone.")
    print(f"  Stored : {stored}")
    print(f"  Failed : {failed}")
    print(f"  Total  : {total}")


# ─────────────────────────────────────────────
# SEARCH
# ─────────────────────────────────────────────
def search(
    question   : str,
    top_k      : int = 8,
    doc_type   : str = None,
    department : str = None,
) -> list:
    try:
        emb_client   = get_embedding_client()
        collection   = get_chroma_collection()
        query_vector = embed_texts(emb_client, [question])[0]

        where = {}
        if doc_type and department:
            where = {
                "$and": [
                    {"doc_type"  : {"$eq": doc_type}},
                    {"department": {"$eq": department}},
                ]
            }
        elif doc_type:
            where = {"doc_type": {"$eq": doc_type}}
        elif department:
            where = {"department": {"$eq": department}}

        results = collection.query(
            query_embeddings = [query_vector],
            n_results        = top_k,
            where            = where if where else None,
            include          = ["documents", "metadatas", "distances"],
        )

        chunks = []
        for i in range(len(results["ids"][0])):
            meta = results["metadatas"][0][i]
            chunks.append({
                "chunk_id"  : results["ids"][0][i],
                "text"      : results["documents"][0][i],
                "breadcrumb": meta.get("breadcrumb", ""),
                "doc_type"  : meta.get("doc_type", ""),
                "department": meta.get("department", ""),
                "title"     : meta.get("title", ""),
                "url"       : meta.get("url", ""),
                "parent_id" : meta.get("parent_id", ""),
                "score"     : round(1 - results["distances"][0][i], 4),
            })

        return chunks

    except Exception as e:
        print(f"Search failed: {e}")
        return []
    
def get_parent(parent_id: str) -> dict:
    """
    Fetch parent chunk by parent_id from chunks.json.
    Called after retrieval to get full section context for LLM.
    """
    try:
        with Path("data/chunks.json").open("r", encoding="utf-8") as f:
            data = json.load(f)
        for p in data.get("parents", []):
            if p["parent_id"] == parent_id:
                return p
        return {}
    except Exception as e:
        print(f"get_parent failed: {e}")
        return {}

# ─────────────────────────────────────────────
# MAIN — run this once to embed + store
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Loading {CHUNKS_PATH}\n")
    with CHUNKS_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        children = data["children"]
        print(f"Loaded {len(data['parents'])} parents, {len(children)} children\n")
    else:
        children = data
        print(f"Loaded {len(children)} chunks\n")

    store_chunks(children)

    print("\nTEST SEARCH:")
    results = search("what is the notice period?", top_k=3)
    for r in results:
        print(f"  score     : {r['score']}")
        print(f"  breadcrumb: {r['breadcrumb']}")
        print(f"  parent_id : {r.get('parent_id', 'N/A')}")
        print(f"  preview   : {r['text'][:100]}")
        print()
