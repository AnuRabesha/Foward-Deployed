"""
Prometheus metrics registry.

Metrics exposed at GET /metrics (text/plain; version=0.0.4):

  http_request_duration_seconds  histogram  latency per endpoint
  http_requests_total             counter    request count by status
  http_errors_total               counter    4xx/5xx by endpoint + code
  active_requests                 gauge      in-flight requests
  rag_tokens_processed_total      counter    approximate token volume
  rag_chunks_retrieved_total      counter    chunks returned per query
  agent_steps_total               counter    agent tool-call steps
  agent_tool_errors_total         counter    per-tool failure count
  ingest_chunks_total             counter    chunks written to ChromaDB
"""

from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry, REGISTRY

# ── HTTP layer ────────────────────────────────────────────────────────────────

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "End-to-end HTTP request latency",
    ["method", "endpoint", "status_code"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)

ERROR_COUNT = Counter(
    "http_errors_total",
    "HTTP 4xx/5xx responses",
    ["endpoint", "status_code"],
)

ACTIVE_REQUESTS = Gauge(
    "active_requests",
    "Number of requests currently being processed",
)

# ── RAG layer ─────────────────────────────────────────────────────────────────

RAG_TOKENS = Counter(
    "rag_tokens_processed_total",
    "Approximate tokens processed by the RAG engine (query + context)",
    ["user_id"],
)

RAG_CHUNKS = Counter(
    "rag_chunks_retrieved_total",
    "Chunks retrieved and re-ranked per RAG query",
    ["user_id"],
)

# ── Agent layer ───────────────────────────────────────────────────────────────

AGENT_STEPS = Counter(
    "agent_steps_total",
    "Total agent tool-call steps executed",
    ["tool", "status"],   # status: success | error | skipped | hitl_rejected
)

AGENT_TOOL_ERRORS = Counter(
    "agent_tool_errors_total",
    "Agent tool call failures by tool name",
    ["tool"],
)

# ── Ingest layer ──────────────────────────────────────────────────────────────

INGEST_CHUNKS = Counter(
    "ingest_chunks_total",
    "Total document chunks written to ChromaDB",
    ["format"],           # pdf | csv | markdown
)
