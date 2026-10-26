"""
Semantic chunker for PDF, CSV, and Markdown documents.
Preserves metadata: department, access_tier, date, source, chunk_index.
"""

import re
import csv
from pathlib import Path
from dataclasses import dataclass, field
from typing import Generator

import tiktoken
from pypdf import PdfReader

ENCODER = tiktoken.get_encoding("cl100k_base")
MAX_TOKENS = 512
OVERLAP_TOKENS = 64


@dataclass
class Chunk:
    text: str
    metadata: dict = field(default_factory=dict)


def _token_split(text: str, max_tokens: int, overlap: int) -> list[str]:
    """Split text into token-bounded chunks with overlap."""
    tokens = ENCODER.encode(text)
    chunks, start = [], 0
    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))
        chunks.append(ENCODER.decode(tokens[start:end]))
        start += max_tokens - overlap
    return chunks


def _base_meta(path: Path, extra: dict) -> dict:
    return {
        "source": path.name,
        "department": extra.get("department", "unknown"),
        "access_tier": extra.get("access_tier", "public"),
        "date": extra.get("date", ""),
    }


def chunk_pdf(path: Path, meta: dict) -> Generator[Chunk, None, None]:
    reader = PdfReader(str(path))
    base = _base_meta(path, meta)
    chunk_idx = 0
    for page_num, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        for text in _token_split(page_text, MAX_TOKENS, OVERLAP_TOKENS):
            if text.strip():
                yield Chunk(
                    text=text.strip(),
                    metadata={**base, "chunk_index": chunk_idx, "page": page_num, "format": "pdf"},
                )
                chunk_idx += 1


def chunk_csv(path: Path, meta: dict) -> Generator[Chunk, None, None]:
    base = _base_meta(path, meta)
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            text = " | ".join(f"{k}: {v}" for k, v in row.items() if v)
            if text.strip():
                yield Chunk(text=text.strip(), metadata={**base, "chunk_index": i, "format": "csv"})


def chunk_markdown(path: Path, meta: dict) -> Generator[Chunk, None, None]:
    base = _base_meta(path, meta)
    content = path.read_text(encoding="utf-8")
    # Split on markdown headers to preserve semantic sections
    sections = re.split(r"(?=^#{1,3} )", content, flags=re.MULTILINE)
    chunk_idx = 0
    for section in sections:
        for text in _token_split(section, MAX_TOKENS, OVERLAP_TOKENS):
            if text.strip():
                yield Chunk(text=text.strip(), metadata={**base, "chunk_index": chunk_idx, "format": "markdown"})
                chunk_idx += 1


HANDLERS = {
    ".pdf": chunk_pdf,
    ".csv": chunk_csv,
    ".md": chunk_markdown,
    ".markdown": chunk_markdown,
}


def chunk_document(path: Path, meta: dict) -> list[Chunk]:
    handler = HANDLERS.get(path.suffix.lower())
    if not handler:
        raise ValueError(f"Unsupported file type: {path.suffix}")
    return list(handler(path, meta))
