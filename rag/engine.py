"""
RAG Engine: orchestrates the full retrieval-augmented generation pipeline.

Flow:
  1. RBAC  — resolve user, build access filter
  2. Rewrite — expand query into N sub-queries
  3. Retrieve — multi-query retrieval from ChromaDB (RBAC-filtered)
  4. Deduplicate — merge candidates by text identity
  5. Re-rank — cross-encoder scores, keep top_k
  6. Synthesise — assemble answer from ranked chunks
  7. Guardrails — strip ungrounded sentences, attach citations
"""

from dataclasses import dataclass, field

from pipeline.embedder import VectorStore
from rag.rbac import get_user, build_chroma_filter, assert_result_access
from rag.rewriter import rewrite
from rag.reranker import rerank
from rag.guardrails import apply_guardrails

# How many candidates to fetch per sub-query before re-ranking
_RETRIEVAL_CANDIDATES = 20
# Final answers are synthesised from this many re-ranked chunks
_TOP_K_RERANK = 5


@dataclass
class RAGResponse:
    answer: str
    citations: list[str]
    flagged_sentences: list[str]
    grounded: bool
    chunks_used: list[dict] = field(default_factory=list)
    sub_queries: list[str] = field(default_factory=list)


def _synthesise(query: str, chunks: list[dict]) -> str:
    """
    Lightweight extractive synthesis: concatenate the most relevant
    chunk texts into a coherent answer paragraph.

    In production, replace this with an LLM call (e.g. Bedrock Claude)
    passing `chunks` as the context window.
    """
    parts = []
    for chunk in chunks:
        text = chunk["text"].strip()
        if text and text not in parts:
            parts.append(text)
    return " ".join(parts)


class RAGEngine:
    def __init__(self, db_path: str = "./chroma_db"):
        self.store = VectorStore(db_path=db_path)

    def ask(
        self,
        query: str,
        user_id: str,
        top_k: int = _TOP_K_RERANK,
        n_rewrites: int = 3,
    ) -> RAGResponse:
        # ── 1. RBAC ──────────────────────────────────────────────────────────
        user = get_user(user_id)
        access_filter = build_chroma_filter(user)

        # ── 2. Query rewriting ───────────────────────────────────────────────
        sub_queries = rewrite(query, n=n_rewrites)

        # ── 3. Multi-query retrieval ─────────────────────────────────────────
        seen_texts: set[str] = set()
        candidates: list[dict] = []

        for sub_q in sub_queries:
            results = self.store.query(
                sub_q,
                n_results=_RETRIEVAL_CANDIDATES,
                where=access_filter,
            )
            for r in results:
                # Secondary RBAC assertion — defence in depth
                assert_result_access(user, r["metadata"])
                if r["text"] not in seen_texts:
                    seen_texts.add(r["text"])
                    candidates.append(r)

        if not candidates:
            return RAGResponse(
                answer="No accessible documents matched your query.",
                citations=[],
                flagged_sentences=[],
                grounded=False,
                sub_queries=sub_queries,
            )

        # ── 4. Re-rank ───────────────────────────────────────────────────────
        ranked = rerank(query, candidates, top_k=top_k)

        # ── 5. Synthesise ────────────────────────────────────────────────────
        raw_answer = _synthesise(query, ranked)

        # ── 6. Guardrails ────────────────────────────────────────────────────
        result = apply_guardrails(raw_answer, ranked)

        return RAGResponse(
            answer=result["answer"],
            citations=result["citations"],
            flagged_sentences=result["flagged"],
            grounded=result["grounded"],
            chunks_used=ranked,
            sub_queries=sub_queries,
        )
