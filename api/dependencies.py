"""
FastAPI dependency providers.

Singletons are initialised once at startup via lifespan and stored in
app.state. Dependencies pull from state so models are never reloaded
per-request.
"""

import os
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from pipeline.embedder import VectorStore
from rag.engine import RAGEngine

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

# Loaded once from environment at import time
_VALID_API_KEYS: set[str] = {
    k.strip()
    for k in os.getenv("API_KEYS", "dev-key-change-me").split(",")
    if k.strip()
}

DB_PATH = os.getenv("CHROMA_DB_PATH", "./chroma_db")


def verify_api_key(api_key: Annotated[str | None, Security(_API_KEY_HEADER)]) -> str:
    if not api_key or api_key not in _VALID_API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Supply X-API-Key header.",
        )
    return api_key


@lru_cache(maxsize=1)
def get_rag_engine() -> RAGEngine:
    return RAGEngine(db_path=DB_PATH)


@lru_cache(maxsize=1)
def get_vector_store() -> VectorStore:
    return VectorStore(db_path=DB_PATH)


# Typed aliases for use in route signatures
AuthDep = Annotated[str, Depends(verify_api_key)]
RAGDep  = Annotated[RAGEngine, Depends(get_rag_engine)]
StoreDep = Annotated[VectorStore, Depends(get_vector_store)]
