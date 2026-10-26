"""
FastAPI application.

Endpoints:
  GET  /health          liveness + readiness probe
  GET  /metrics         Prometheus text exposition
  POST /ingest          document ingestion pipeline
  POST /query           raw vector search
  POST /ask             RBAC-enforced RAG Q&A
  POST /agent           autonomous ERP/CRM agent
"""

import os
import time
import tiktoken
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from api.models import (
    IngestRequest, IngestResponse, FileStats,
    AskRequest, AskResponse,
    AgentRequest, AgentResponse, AgentStepRecord,
    QueryRequest, QueryResponse, QueryResult,
    HealthResponse,
)
from api.dependencies import (
    AuthDep, RAGDep, StoreDep,
    get_rag_engine, get_vector_store, DB_PATH,
)
from api.metrics import (
    REQUEST_LATENCY, REQUEST_COUNT, ERROR_COUNT, ACTIVE_REQUESTS,
    RAG_TOKENS, RAG_CHUNKS, AGENT_STEPS, AGENT_TOOL_ERRORS, INGEST_CHUNKS,
)
from pipeline.ingest import run_pipeline
from agent.loop import run as agent_run

_VERSION = os.getenv("APP_VERSION", "1.0.0")
_ENCODER = tiktoken.get_encoding("cl100k_base")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm up singletons so first request isn't slow
    get_rag_engine()
    get_vector_store()
    yield


app = FastAPI(
    title="Datheon AI Platform",
    version=_VERSION,
    description="Vector ETL · RAG Engine · Enterprise Agent",
    lifespan=lifespan,
)


# ── Prometheus middleware ─────────────────────────────────────────────────────

@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    endpoint = request.url.path
    method   = request.method
    ACTIVE_REQUESTS.inc()
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
        status_code = str(response.status_code)
    except Exception:
        status_code = "500"
        raise
    finally:
        elapsed = time.perf_counter() - t0
        ACTIVE_REQUESTS.dec()
        REQUEST_LATENCY.labels(method, endpoint, status_code).observe(elapsed)
        REQUEST_COUNT.labels(method, endpoint, status_code).inc()
        if status_code.startswith(("4", "5")):
            ERROR_COUNT.labels(endpoint, status_code).inc()
    return response


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["ops"])
def health():
    chroma_ok, model_ok = True, True
    try:
        store = get_vector_store()
        store.collection.count()
    except Exception:
        chroma_ok = False
    try:
        engine = get_rag_engine()
        _ = engine.store.model
    except Exception:
        model_ok = False

    overall = "healthy" if chroma_ok and model_ok else "degraded"
    return HealthResponse(
        status=overall,
        version=_VERSION,
        chroma_ok=chroma_ok,
        model_ok=model_ok,
    )


# ── Metrics ───────────────────────────────────────────────────────────────────

@app.get("/metrics", tags=["ops"], include_in_schema=False)
def metrics():
    return PlainTextResponse(
        generate_latest().decode("utf-8"),
        media_type=CONTENT_TYPE_LATEST,
    )


# ── Ingest ────────────────────────────────────────────────────────────────────

@app.post("/ingest", response_model=IngestResponse, tags=["pipeline"])
def ingest(req: IngestRequest, _: AuthDep):
    try:
        result = run_pipeline(
            docs_dir=req.docs_dir,
            manifest=req.manifest,
            batch_size=req.batch_size,
            db_path=DB_PATH,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not result:
        raise HTTPException(status_code=422, detail="No supported documents found.")

    # Record per-format chunk counts from file stats
    for f in result.get("files", []):
        ext = f["file"].rsplit(".", 1)[-1].lower()
        fmt = {"md": "markdown", "markdown": "markdown", "pdf": "pdf", "csv": "csv"}.get(ext, ext)
        INGEST_CHUNKS.labels(fmt).inc(f["chunks"])

    files = [FileStats(**f) for f in result["files"]]
    return IngestResponse(
        files=files,
        total_chunks=result["total_chunks"],
        total_time_s=result["total_time_s"],
        overall_chunks_per_sec=result["overall_chunks_per_sec"],
    )


# ── Raw vector query ──────────────────────────────────────────────────────────

@app.post("/query", response_model=QueryResponse, tags=["search"])
def query(req: QueryRequest, _: AuthDep, store: StoreDep):
    where: dict = {}
    if req.department:
        where["department"] = req.department
    if req.access_tier:
        where["access_tier"] = req.access_tier

    try:
        results = store.query(req.query, n_results=req.top_k, where=where or None)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return QueryResponse(
        results=[QueryResult(**r) for r in results]
    )


# ── RAG ask ───────────────────────────────────────────────────────────────────

@app.post("/ask", response_model=AskResponse, tags=["rag"])
def ask(req: AskRequest, _: AuthDep, engine: RAGDep):
    try:
        response = engine.ask(
            query=req.query,
            user_id=req.user_id,
            top_k=req.top_k,
            n_rewrites=req.n_rewrites,
        )
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Instrument token volume (query + answer approximation)
    token_count = len(_ENCODER.encode(req.query)) + len(_ENCODER.encode(response.answer))
    RAG_TOKENS.labels(req.user_id).inc(token_count)
    RAG_CHUNKS.labels(req.user_id).inc(len(response.chunks_used))

    return AskResponse(
        answer=response.answer,
        citations=response.citations,
        flagged_sentences=response.flagged_sentences,
        grounded=response.grounded,
        sub_queries=response.sub_queries,
        chunks_used=len(response.chunks_used),
    )


# ── Agent ─────────────────────────────────────────────────────────────────────

@app.post("/agent", response_model=AgentResponse, tags=["agent"])
def agent(req: AgentRequest, _: AuthDep):
    try:
        trace = agent_run(req.task, auto_approve=req.auto_approve)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Instrument per-step outcomes
    for step in trace.steps:
        tool = step.get("tool", "unknown")
        if step.get("skipped"):
            AGENT_STEPS.labels(tool, "skipped").inc()
        elif step.get("hitl_rejected"):
            AGENT_STEPS.labels(tool, "hitl_rejected").inc()
        elif step.get("success"):
            AGENT_STEPS.labels(tool, "success").inc()
        else:
            AGENT_STEPS.labels(tool, "error").inc()
            AGENT_TOOL_ERRORS.labels(tool).inc()

    steps = [
        AgentStepRecord(
            tool=s.get("tool", ""),
            success=s.get("success", False),
            attempts=s.get("attempts", 0),
            hitl_rejected=s.get("hitl_rejected", False),
            output=s.get("output"),
            error=s.get("error", ""),
            skipped=s.get("skipped", False),
        )
        for s in trace.steps
    ]

    return AgentResponse(
        task=trace.task,
        success=trace.success,
        summary=trace.summary,
        steps=steps,
    )
