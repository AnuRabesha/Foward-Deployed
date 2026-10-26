"""
Embedder: wraps SentenceTransformer + ChromaDB collection with cosine similarity.
"""

import uuid
from typing import Optional

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

from pipeline.chunker import Chunk

MODEL_NAME = "all-MiniLM-L6-v2"
COLLECTION_NAME = "client_documents"
DB_PATH = "./chroma_db"


class VectorStore:
    def __init__(self, db_path: str = DB_PATH, collection: str = COLLECTION_NAME):
        self.model = SentenceTransformer(MODEL_NAME)
        self.client = chromadb.PersistentClient(
            path=db_path,
            settings=Settings(anonymized_telemetry=False),
        )
        # ChromaDB uses cosine similarity when space="cosine"
        self.collection = self.client.get_or_create_collection(
            name=collection,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert_batch(self, chunks: list[Chunk], batch_size: int = 64) -> int:
        """Embed and upsert chunks in batches. Returns total upserted count."""
        total = 0
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            texts = [c.text for c in batch]
            embeddings = self.model.encode(texts, show_progress_bar=False).tolist()
            self.collection.upsert(
                ids=[str(uuid.uuid4()) for _ in batch],
                embeddings=embeddings,
                documents=texts,
                metadatas=[c.metadata for c in batch],
            )
            total += len(batch)
        return total

    def query(
        self,
        query_text: str,
        n_results: int = 5,
        where: Optional[dict] = None,
    ) -> list[dict]:
        """Semantic search with optional metadata filter."""
        embedding = self.model.encode([query_text]).tolist()
        kwargs = {"query_embeddings": embedding, "n_results": n_results}
        if where:
            kwargs["where"] = where
        results = self.collection.query(**kwargs)
        return [
            {"text": doc, "metadata": meta, "distance": dist}
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            )
        ]
