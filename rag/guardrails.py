"""
Hallucination guardrails.

Strategy:
  1. Split the answer into sentences.
  2. For each sentence, check if any retrieved chunk contains enough
     overlapping n-grams to consider it "grounded".
  3. Sentences that fail the grounding check are flagged and removed
     from the final answer.
  4. Every grounded sentence is annotated with its source citation.

This is a deterministic, zero-latency approach that requires no extra
model calls. For production, replace `_is_grounded` with a NLI model.
"""

import re
from collections import Counter


def _ngrams(text: str, n: int = 4) -> Counter:
    words = re.findall(r"\w+", text.lower())
    return Counter(zip(*[words[i:] for i in range(n)]))


def _overlap_ratio(sentence: str, passage: str, n: int = 4) -> float:
    """Jaccard-like overlap of n-grams between sentence and passage."""
    s_grams = _ngrams(sentence, n)
    p_grams = _ngrams(passage, n)
    if not s_grams:
        return 0.0
    intersection = sum((s_grams & p_grams).values())
    return intersection / sum(s_grams.values())


def _is_grounded(sentence: str, chunks: list[dict], threshold: float = 0.25) -> tuple[bool, dict | None]:
    """Return (grounded, best_chunk) for a sentence."""
    best_score, best_chunk = 0.0, None
    for chunk in chunks:
        score = _overlap_ratio(sentence, chunk["text"])
        if score > best_score:
            best_score, best_chunk = score, chunk
    if best_score >= threshold:
        return True, best_chunk
    # Fallback: check if any 3-gram from the sentence appears verbatim
    s3 = _ngrams(sentence, 3)
    for chunk in chunks:
        p3 = _ngrams(chunk["text"], 3)
        if sum((s3 & p3).values()) >= 2:
            return True, chunk
    return False, None


def _citation(chunk: dict) -> str:
    meta = chunk.get("metadata", {})
    source = meta.get("source", "unknown")
    page = meta.get("page", None)
    chunk_idx = meta.get("chunk_index", "")
    if page is not None:
        return f"[{source}, p.{page}]"
    return f"[{source}, chunk {chunk_idx}]"


def apply_guardrails(answer: str, chunks: list[dict]) -> dict:
    """
    Verify answer against retrieved chunks.

    Returns:
        {
          "answer": str,           # grounded sentences only, with inline citations
          "flagged": list[str],    # sentences removed as ungrounded
          "citations": list[str],  # unique citations used
          "grounded": bool,        # True if at least one sentence survived
        }
    """
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", answer) if s.strip()]
    grounded_parts: list[str] = []
    flagged: list[str] = []
    citations: list[str] = []

    for sentence in sentences:
        ok, best = _is_grounded(sentence, chunks)
        if ok and best is not None:
            cite = _citation(best)
            grounded_parts.append(f"{sentence} {cite}")
            if cite not in citations:
                citations.append(cite)
        else:
            flagged.append(sentence)

    return {
        "answer": " ".join(grounded_parts),
        "flagged": flagged,
        "citations": citations,
        "grounded": len(grounded_parts) > 0,
    }
