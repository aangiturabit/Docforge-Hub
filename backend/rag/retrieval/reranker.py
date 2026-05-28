from sentence_transformers import CrossEncoder
from functools import lru_cache

MODEL_NAME        = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RERANKER_THRESHOLD = 1.0  


@lru_cache(maxsize=1)
def get_reranker():
    return CrossEncoder(MODEL_NAME)


def rerank(question: str, chunks: list, top_n: int = 5) -> list:
  
    try:
        if not chunks:
            return []

        reranker = get_reranker()
        pairs    = [[question, c["text"]] for c in chunks]
        scores   = reranker.predict(pairs)

        # Attach score + filter below threshold
        scored = []
        for i, chunk in enumerate(chunks):
            score = float(scores[i])
            if score >= RERANKER_THRESHOLD:
                chunk["reranker_score"] = score
                scored.append(chunk)

        if not scored:
            # All filtered — return top_n unfiltered as fallback
            for i, chunk in enumerate(chunks):
                chunk["reranker_score"] = float(scores[i])
            return sorted(chunks, key=lambda x: x["reranker_score"], reverse=True)[:top_n]

        return sorted(scored, key=lambda x: x["reranker_score"], reverse=True)[:top_n]

    except Exception as e:
        print(f"Reranker failed: {e}")
        return chunks[:top_n]