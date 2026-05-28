import json
import pickle
import bm25s
from pathlib import Path

CHUNKS_PATH   = Path("data/chunks.json")
BM25_INDEX_PATH = Path("data/bm25_index.pkl")


# ─────────────────────────────────────────────
# BUILD BM25 INDEX
# ─────────────────────────────────────────────
def build_bm25_index():
    """
    Loads children from chunks.json.
    Builds BM25 index on raw text (no prefix).
    Saves index + chunk list to disk.
    """
    try:
        with CHUNKS_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)

        children = data.get("children", [])
        if not children:
            print("No children found in chunks.json")
            return

        print(f"Building BM25 index for {len(children)} chunks...")

        # Raw text for BM25 — no prefix, exact term matching
        corpus     = [c["text"] for c in children]
        chunk_ids  = [c["chunk_id"] for c in children]

        # Tokenize
        tokenized  = bm25s.tokenize(corpus)

        # Build index
        retriever  = bm25s.BM25()
        retriever.index(tokenized)

        # Save index + metadata to disk
        with BM25_INDEX_PATH.open("wb") as f:
            pickle.dump({
                "retriever" : retriever,
                "chunk_ids" : chunk_ids,
                "children"  : children,
            }, f)

        print(f"BM25 index saved to {BM25_INDEX_PATH}")

    except Exception as e:
        print(f"Failed to build BM25 index: {e}")
        raise


# ─────────────────────────────────────────────
# LOAD INDEX
# ─────────────────────────────────────────────
def load_bm25_index():
    """
    Loads BM25 index from disk.
    Returns retriever + children list.
    """
    try:
        with BM25_INDEX_PATH.open("rb") as f:
            data = pickle.load(f)
        return data["retriever"], data["chunk_ids"], data["children"]
    except FileNotFoundError:
        print("BM25 index not found. Run build_bm25_index() first.")
        return None, [], []
    except Exception as e:
        print(f"Failed to load BM25 index: {e}")
        return None, [], []


# ─────────────────────────────────────────────
# SEARCH
# ─────────────────────────────────────────────
def sparse_search(
    question   : str,
    top_k      : int  = 10,
    doc_type   : str  = None,
    department : str  = None,
) -> list:
    """
    BM25 keyword search over children.
    Optionally filters by doc_type and department after retrieval.
    Returns list of chunks with bm25_score field.
    """
    try:
        retriever, chunk_ids, children = load_bm25_index()

        if retriever is None:
            return []

        # Tokenize query
        query_tokens = bm25s.tokenize([question])

        # Retrieve more than needed to account for post-filtering
        fetch_k = top_k * 3 if (doc_type or department) else top_k

        results, scores = retriever.retrieve(query_tokens, k=min(fetch_k, len(children)))

        # Build results list
        chunks = []
        for idx, score in zip(results[0], scores[0]):
            child = children[idx]

            # Post-filter by metadata
            if doc_type and child["metadata"].get("doc_type") != doc_type:
                continue
            if department and child["metadata"].get("department") != department:
                continue

            chunks.append({
                "chunk_id"  : child["chunk_id"],
                "parent_id" : child.get("parent_id", ""),
                "text"      : child["text"],
                "breadcrumb": child["breadcrumb"],
                "doc_type"  : child["metadata"].get("doc_type", ""),
                "department": child["metadata"].get("department", ""),
                "title"     : child["metadata"].get("title", ""),
                "url"       : child["metadata"].get("url", ""),
                "bm25_score": float(score),
            })

            if len(chunks) >= top_k:
                break

        return chunks

    except Exception as e:
        print(f"Sparse search failed: {e}")
        return []


# ─────────────────────────────────────────────
# MAIN — build index
# ─────────────────────────────────────────────
if __name__ == "__main__":
    build_bm25_index()

    print("\nTEST SEARCH:")
    results = sparse_search("notice period", top_k=3)
    for r in results:
        print(f"  bm25_score: {r['bm25_score']:.4f}")
        print(f"  breadcrumb: {r['breadcrumb']}")
        print(f"  preview   : {r['text'][:100]}")
        print()