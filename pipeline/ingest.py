"""
Ingest orchestrator: discovers documents, chunks them, upserts to ChromaDB,
and reports batch ingestion benchmarks.
"""

import json
import time
from pathlib import Path

from tqdm import tqdm

from pipeline.chunker import chunk_document, HANDLERS
from pipeline.embedder import VectorStore


def load_manifest(manifest_path: Path) -> dict:
    """
    Optional JSON manifest mapping filenames to metadata.
    Example: {"report.pdf": {"department": "finance", "access_tier": "internal", "date": "2024-01-15"}}
    """
    if manifest_path.exists():
        return json.loads(manifest_path.read_text())
    return {}


def run_pipeline(
    docs_dir: str = "./sample_docs",
    manifest: str = "./manifest.json",
    batch_size: int = 64,
    db_path: str = "./chroma_db",
) -> dict:
    docs_path = Path(docs_dir)
    manifest_data = load_manifest(Path(manifest))
    store = VectorStore(db_path=db_path)

    files = [f for f in docs_path.iterdir() if f.suffix.lower() in HANDLERS]
    if not files:
        print(f"No supported documents found in {docs_dir}")
        return {}

    benchmark = {"files": [], "total_chunks": 0, "total_time_s": 0.0}
    pipeline_start = time.perf_counter()

    for file in tqdm(files, desc="Ingesting documents"):
        meta = manifest_data.get(file.name, {})
        t0 = time.perf_counter()
        chunks = chunk_document(file, meta)
        upserted = store.upsert_batch(chunks, batch_size=batch_size)
        elapsed = time.perf_counter() - t0

        file_stat = {
            "file": file.name,
            "chunks": upserted,
            "time_s": round(elapsed, 3),
            "chunks_per_sec": round(upserted / elapsed, 1) if elapsed > 0 else 0,
        }
        benchmark["files"].append(file_stat)
        benchmark["total_chunks"] += upserted
        print(f"  {file.name}: {upserted} chunks in {elapsed:.2f}s ({file_stat['chunks_per_sec']} chunks/s)")

    benchmark["total_time_s"] = round(time.perf_counter() - pipeline_start, 3)
    benchmark["overall_chunks_per_sec"] = round(
        benchmark["total_chunks"] / benchmark["total_time_s"], 1
    ) if benchmark["total_time_s"] > 0 else 0

    return benchmark
