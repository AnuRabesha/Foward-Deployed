from typing import Any
from pydantic import BaseModel, Field


# ── Ingest ────────────────────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    docs_dir: str = Field("./sample_docs", description="Path to documents directory")
    manifest: str = Field("./manifest.json", description="Path to manifest JSON")
    batch_size: int = Field(64, ge=1, le=512)


class FileStats(BaseModel):
    file: str
    chunks: int
    time_s: float
    chunks_per_sec: float


class IngestResponse(BaseModel):
    files: list[FileStats]
    total_chunks: int
    total_time_s: float
    overall_chunks_per_sec: float


# ── RAG / Ask ─────────────────────────────────────────────────────────────────

class AskRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    user_id: str = Field(..., min_length=1)
    top_k: int = Field(5, ge=1, le=20)
    n_rewrites: int = Field(3, ge=1, le=5)


class AskResponse(BaseModel):
    answer: str
    citations: list[str]
    flagged_sentences: list[str]
    grounded: bool
    sub_queries: list[str]
    chunks_used: int


# ── Agent ─────────────────────────────────────────────────────────────────────

class AgentRequest(BaseModel):
    task: str = Field(..., min_length=1, max_length=2000)
    auto_approve: bool = Field(False)


class AgentStepRecord(BaseModel):
    tool: str
    success: bool
    attempts: int
    hitl_rejected: bool
    output: Any = None
    error: str = ""
    skipped: bool = False


class AgentResponse(BaseModel):
    task: str
    success: bool
    summary: str
    steps: list[AgentStepRecord]


# ── Health ────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    version: str
    chroma_ok: bool
    model_ok: bool


# ── Query (raw vector search) ─────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(5, ge=1, le=50)
    department: str | None = None
    access_tier: str | None = None


class QueryResult(BaseModel):
    text: str
    metadata: dict
    distance: float


class QueryResponse(BaseModel):
    results: list[QueryResult]
