"""
Re-ranker: uses a cross-encoder to score (query, passage) pairs and
re-order bi-encoder candidates by true relevance.

Model: cross-encoder/ms-marco-MiniLM-L-6-v2  (~80 MB, CPU-friendly)
"""

from functools import lru_cache

from sentence_transformers import CrossEncoder

_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"


@lru_cache(maxsize=1)
def _get_model() -> CrossEncoder:
    return CrossEncoder(_MODEL_NAME)


def rerank(query: str, candidates: list[dict], top_k: int = 5) -> list[dict]:
    """
    Score each candidate against the query and return top_k sorted by score.

    Each candidate dict must have a "text" key.
    Adds a "rerank_score" key to each returned item.
    """
    if not candidates:
        return []

    model = _get_model()
    pairs = [(query, c["text"]) for c in candidates]
    scores = model.predict(pairs).tolist()

    for candidate, score in zip(candidates, scores):
        candidate["rerank_score"] = round(float(score), 4)

    ranked = sorted(candidates, key=lambda c: c["rerank_score"], reverse=True)
    return ranked[:top_k]
