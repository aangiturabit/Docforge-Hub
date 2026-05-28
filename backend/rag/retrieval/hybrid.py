from backend.rag.retrieval.dense import search as dense_search
from backend.rag.retrieval.sparse import sparse_search
from backend.rag.retrieval.reranker import rerank
from backend.rag.cache.redis_client import get_cached_retrieval, set_cached_retrieval

# Weight for combining dense + sparse scores
# 0.6 = slightly favour semantic (dense) for compliance docs
DENSE_WEIGHT  = 0.6
SPARSE_WEIGHT = 0.4


def hybrid_search(
    question   : str,
    top_k      : int  = 8,
    doc_type   : str  = None,
    department : str  = None,
) -> list:
    

    # ── Step 1: Retrieve from both systems ──
    cached = get_cached_retrieval(question, doc_type, department, top_k)
    if cached:
        print(f"  Cache hit for: {question[:50]}")
        return cached
    fetch_k       = top_k * 3  
    dense_results = dense_search(question, top_k=fetch_k, doc_type=doc_type, department=department)
    sparse_results = sparse_search(question, top_k=fetch_k, doc_type=doc_type, department=department)

    if not dense_results and not sparse_results:
        return []

    # ── Step 2: Normalize scores to 0-1 range ──
    def normalize(results, score_key):
        if not results:
            return {}
        scores = [r[score_key] for r in results]
        min_s  = min(scores)
        max_s  = max(scores)
        rng    = max_s - min_s if max_s != min_s else 1.0
        return {
            r["chunk_id"]: (r[score_key] - min_s) / rng
            for r in results
        }

    dense_norm  = normalize(dense_results,  "score")
    sparse_norm = normalize(sparse_results, "bm25_score")

    # ── Step 3: Weighted merge ──
    # Build unified chunk map by chunk_id
    chunk_map = {}

    for chunk in dense_results:
        cid = chunk["chunk_id"]
        chunk_map[cid] = {**chunk, "hybrid_score": 0.0}

    for chunk in sparse_results:
        cid = chunk["chunk_id"]
        if cid not in chunk_map:
            chunk_map[cid] = {
                "chunk_id"  : chunk["chunk_id"],
                "parent_id" : chunk.get("parent_id", ""),
                "text"      : chunk["text"],
                "breadcrumb": chunk["breadcrumb"],
                "doc_type"  : chunk["doc_type"],
                "department": chunk["department"],
                "title"     : chunk["title"],
                "url"       : chunk["url"],
                "score"     : 0.0,
                "hybrid_score": 0.0,
            }

    # Compute weighted hybrid score for each chunk
    for cid, chunk in chunk_map.items():
        d_score = dense_norm.get(cid, 0.0)
        s_score = sparse_norm.get(cid, 0.0)
        chunk["hybrid_score"] = (DENSE_WEIGHT * d_score) + (SPARSE_WEIGHT * s_score)
        chunk["score"]        = chunk["hybrid_score"]

    # Sort by hybrid score
    merged = sorted(chunk_map.values(), key=lambda x: x["hybrid_score"], reverse=True)

    # Take top candidates for reranker
    candidates = merged[:fetch_k]

    # ── Step 4: Rerank ──
    reranked = rerank(question, candidates, top_n=top_k)
    set_cached_retrieval(question, reranked, doc_type, department, top_k)

    return reranked


if __name__ == "__main__":
    print("TEST HYBRID SEARCH\n")
    results = hybrid_search("what is the notice period?", top_k=3)
    for r in results:
        print(f"  hybrid_score   : {r.get('hybrid_score', 0):.4f}")
        print(f"  reranker_score : {r.get('reranker_score', 0):.4f}")
        print(f"  breadcrumb     : {r['breadcrumb']}")
        print(f"  preview        : {r['text'][:100]}")
        print()
