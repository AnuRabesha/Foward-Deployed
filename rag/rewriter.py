"""
Query rewriter: expands the original query into N semantically distinct
sub-queries to improve retrieval recall via query decomposition.

Uses a lightweight local approach (no external LLM required) — generates
variations by prepending intent-shifting prefixes. For production, swap
`_rewrite_local` with an LLM call.
"""

import re

# Intent-shifting prefixes that produce meaningfully different embedding vectors
_PREFIXES = [
    "",                          # original
    "What is the definition of",
    "Summarize information about",
    "List key facts regarding",
]


def rewrite(query: str, n: int = 3) -> list[str]:
    """
    Return `n` query variants including the original.
    Deduplicates and strips empty strings.
    """
    query = query.strip()
    variants: list[str] = []
    for prefix in _PREFIXES:
        candidate = f"{prefix} {query}".strip() if prefix else query
        # Normalise whitespace and avoid exact duplicates
        candidate = re.sub(r"\s+", " ", candidate)
        if candidate not in variants:
            variants.append(candidate)
        if len(variants) == n:
            break
    return variants
