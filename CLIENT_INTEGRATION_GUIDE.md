# Datheon AI Platform — Client Integration Guide

**Version:** 1.0.0
**Base URL (production):** `https://api.your-domain.com`
**Base URL (local dev):** `http://localhost:8000`

---

## Table of Contents

1. [Authentication](#1-authentication)
2. [Quick Start](#2-quick-start)
3. [Endpoints Reference](#3-endpoints-reference)
   - [Health Check](#31-get-health)
   - [Document Ingestion](#32-post-ingest)
   - [Vector Search](#33-post-query)
   - [RAG Q&A](#34-post-ask)
   - [Enterprise Agent](#35-post-agent)
4. [Error Codes](#4-error-codes)
5. [Prometheus Metrics Reference](#5-prometheus-metrics-reference)
6. [Deployment](#6-deployment)
7. [Security Checklist](#7-security-checklist)

---

## 1. Authentication

All endpoints (except `/health` and `/metrics`) require an API key passed in the request header:

```
X-API-Key: <your-api-key>
```

API keys are provisioned by your Datheon administrator and stored in the server's `.env` file under `API_KEYS` (comma-separated). Keys are never embedded in responses or logs.

**Rotate keys** by updating `API_KEYS` in `.env` and restarting the service — no code changes required.

---

## 2. Quick Start

### 2.1 Start the stack

```bash
# Copy and configure secrets
cp .env.example .env
# Edit .env — set API_KEYS to a strong random value

# Build and start all services
docker compose up --build -d

# Confirm healthy
curl http://localhost:8000/health
```

### 2.2 Ingest documents, then query

```bash
API_KEY="dev-key-change-me"

# 1. Ingest sample documents
curl -s -X POST http://localhost:8000/ingest \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"docs_dir": "./sample_docs", "manifest": "./manifest.json", "batch_size": 64}' \
  | python -m json.tool

# 2. Ask a question (RBAC-enforced)
curl -s -X POST http://localhost:8000/ask \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the remote work policy?", "user_id": "alice"}' \
  | python -m json.tool
```

---

## 3. Endpoints Reference

### 3.1 `GET /health`

Liveness and readiness probe. Used by Docker, load balancers, and Kubernetes.

**Auth required:** No

**Response `200 OK`:**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "chroma_ok": true,
  "model_ok": true
}
```

`status` is `"degraded"` if either `chroma_ok` or `model_ok` is `false`. Route traffic away from degraded instances.

---

### 3.2 `POST /ingest`

Ingests documents from a directory into ChromaDB. Supports PDF, CSV, and Markdown.

**Auth required:** Yes

**Request body:**
```json
{
  "docs_dir": "./sample_docs",
  "manifest": "./manifest.json",
  "batch_size": 64
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `docs_dir` | string | `./sample_docs` | Path to documents directory (inside container) |
| `manifest` | string | `./manifest.json` | Path to metadata manifest |
| `batch_size` | int [1–512] | `64` | Embedding batch size |

**Response `200 OK`:**
```json
{
  "files": [
    {"file": "finance_report_q1.md", "chunks": 4, "time_s": 1.2, "chunks_per_sec": 3.3}
  ],
  "total_chunks": 12,
  "total_time_s": 3.8,
  "overall_chunks_per_sec": 3.2
}
```

**Manifest format** (`manifest.json`):
```json
{
  "finance_report_q1.md": {
    "department": "finance",
    "access_tier": "internal",
    "date": "2024-03-31"
  }
}
```

Valid `access_tier` values: `public`, `internal`, `confidential`

---

### 3.3 `POST /query`

Raw vector similarity search with optional metadata filters. Returns chunks ranked by cosine distance. No RBAC — use `/ask` for access-controlled retrieval.

**Auth required:** Yes

**Request body:**
```json
{
  "query": "revenue forecast Q2",
  "top_k": 5,
  "department": "finance",
  "access_tier": "internal"
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | string | required | Search query |
| `top_k` | int [1–50] | `5` | Number of results |
| `department` | string \| null | `null` | Filter by department |
| `access_tier` | string \| null | `null` | Filter by access tier |

**Response `200 OK`:**
```json
{
  "results": [
    {
      "text": "Q2 projections estimate $4.6M in revenue...",
      "metadata": {
        "source": "finance_report_q1.md",
        "department": "finance",
        "access_tier": "internal",
        "date": "2024-03-31",
        "chunk_index": 2,
        "format": "markdown"
      },
      "distance": 0.1243
    }
  ]
}
```

Lower `distance` = more similar (cosine distance, range 0–2).

---

### 3.4 `POST /ask`

RBAC-enforced RAG Q&A with query rewriting, cross-encoder re-ranking, and hallucination guardrails. Returns a grounded answer with source citations.

**Auth required:** Yes

**Request body:**
```json
{
  "query": "What is the remote work policy?",
  "user_id": "alice",
  "top_k": 5,
  "n_rewrites": 3
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | string | required | Natural-language question |
| `user_id` | string | required | User ID for RBAC clearance lookup |
| `top_k` | int [1–20] | `5` | Chunks to use after re-ranking |
| `n_rewrites` | int [1–5] | `3` | Number of query variants to generate |

**Response `200 OK`:**
```json
{
  "answer": "Employees may work remotely up to 3 days per week... [hr_policy.md, chunk 1]",
  "citations": ["[hr_policy.md, chunk 1]"],
  "flagged_sentences": [],
  "grounded": true,
  "sub_queries": [
    "What is the remote work policy?",
    "Summarize information about What is the remote work policy?",
    "List key facts regarding What is the remote work policy?"
  ],
  "chunks_used": 3
}
```

**RBAC user clearance levels:**

| User | Clearance | Departments |
|------|-----------|-------------|
| `alice` | `confidential` | all |
| `bob` | `internal` | finance |
| `carol` | `public` | all |
| `dave` | `internal` | hr, finance |

**`403 Forbidden`** is returned if `user_id` attempts to access documents above their clearance tier.

---

### 3.5 `POST /agent`

Autonomous ERP/CRM agent. Decomposes a natural-language task into tool calls, executes them with validation and retry, and returns the full thought-action-observation trace.

**Auth required:** Yes

**Request body:**
```json
{
  "task": "order 5 units of SKU-001 for CUST-002",
  "auto_approve": false
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `task` | string | required | Natural-language business task |
| `auto_approve` | bool | `false` | Skip HITL prompts for non-critical writes. `place_order` always requires approval when `false`. |

> **Note:** When `auto_approve` is `false` and the agent reaches a sensitive write operation (e.g. `place_order`), the request will block waiting for stdin input. **Set `auto_approve: true` for API usage.** HITL confirmation is designed for CLI use.

**Response `200 OK`:**
```json
{
  "task": "order 5 units of SKU-001 for CUST-002",
  "success": true,
  "summary": "Completed 3/3 steps.",
  "steps": [
    {
      "tool": "inventory_lookup",
      "success": true,
      "attempts": 1,
      "hitl_rejected": false,
      "output": {"sku": "SKU-001", "qty": 42, "unit_price": 1299.0, "warehouse": "WH-A"},
      "error": "",
      "skipped": false
    },
    {
      "tool": "customer_lookup",
      "success": true,
      "attempts": 1,
      "hitl_rejected": false,
      "output": {"customer_id": "CUST-002", "name": "Stark Industries", "tier": "enterprise"},
      "error": "",
      "skipped": false
    },
    {
      "tool": "place_order",
      "success": true,
      "attempts": 2,
      "hitl_rejected": false,
      "output": {"order_id": "ORD-301", "total": 6495.0, "status": "confirmed"},
      "error": "",
      "skipped": false
    }
  ]
}
```

**Available entity IDs for testing:**

| Type | IDs |
|------|-----|
| SKUs | `SKU-001`, `SKU-002`, `SKU-003`, `SKU-004` |
| Leads | `LEAD-100`, `LEAD-101`, `LEAD-102`, `LEAD-103` |
| Customers | `CUST-001`, `CUST-002`, `CUST-003` |

**Example tasks:**
```
"check inventory for SKU-002"
"advance LEAD-101 to qualified"
"create high priority ticket: billing issue for CUST-003"
"order 5 units of SKU-001 for CUST-002"
```

---

## 4. Error Codes

| HTTP Code | Meaning | Common Cause |
|-----------|---------|--------------|
| `400 Bad Request` | Invalid request body | Missing required field, value out of range |
| `401 Unauthorized` | Missing or invalid API key | `X-API-Key` header absent or wrong |
| `403 Forbidden` | RBAC access denied | `user_id` clearance too low for requested documents |
| `422 Unprocessable Entity` | Validation error | Pydantic schema violation |
| `500 Internal Server Error` | Unexpected server error | Check container logs: `docker compose logs app` |

**Error response body:**
```json
{
  "detail": "Human-readable error description"
}
```

---

## 5. Prometheus Metrics Reference

Metrics are exposed at `GET /metrics` in Prometheus text format. Scraped every 10 seconds by the bundled Prometheus instance at `http://localhost:9090`.

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `http_request_duration_seconds` | Histogram | `method`, `endpoint`, `status_code` | End-to-end request latency |
| `http_requests_total` | Counter | `method`, `endpoint`, `status_code` | Total request count |
| `http_errors_total` | Counter | `endpoint`, `status_code` | 4xx/5xx response count |
| `active_requests` | Gauge | — | In-flight requests |
| `rag_tokens_processed_total` | Counter | `user_id` | Approximate tokens processed |
| `rag_chunks_retrieved_total` | Counter | `user_id` | Chunks retrieved per query |
| `agent_steps_total` | Counter | `tool`, `status` | Agent tool-call outcomes |
| `agent_tool_errors_total` | Counter | `tool` | Per-tool failure count |
| `ingest_chunks_total` | Counter | `format` | Chunks written to ChromaDB |

**Useful PromQL queries:**

```promql
# P95 request latency over last 5 minutes
histogram_quantile(0.95,
  rate(http_request_duration_seconds_bucket[5m])
)

# Error rate per endpoint
rate(http_errors_total[5m])

# RAG token throughput per user
rate(rag_tokens_processed_total[5m])

# Agent tool success rate
rate(agent_steps_total{status="success"}[5m])
  / rate(agent_steps_total[5m])
```

---

## 6. Deployment

### 6.1 Local development

```bash
# Install dependencies
pip install -r requirements.txt

# Run API server directly (no Docker)
uvicorn api.app:app --reload --port 8000
```

### 6.2 Docker Compose (recommended)

```bash
# First-time setup
cp .env.example .env
# Edit .env — set a strong API_KEYS value

# Build and start
docker compose up --build -d

# View logs
docker compose logs -f app

# Stop
docker compose down

# Stop and remove volumes (wipes ChromaDB data)
docker compose down -v
```

### 6.3 Ingest documents into the running container

```bash
# Copy documents into the mounted volume path
cp your_docs/*.pdf ./sample_docs/
cp your_docs/*.csv ./sample_docs/

# Update manifest.json with metadata for new files

# Trigger ingestion via API
curl -X POST http://localhost:8000/ingest \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"docs_dir": "./sample_docs", "manifest": "./manifest.json"}'
```

### 6.4 Scaling

- The API is stateless (ChromaDB is on a volume). Scale horizontally by running multiple replicas behind a load balancer.
- ChromaDB is embedded — for multi-replica deployments, migrate to [ChromaDB server mode](https://docs.trychroma.com/usage-guide#running-chroma-in-clientserver-mode) or Qdrant.
- Increase `--workers` in the `CMD` of `Dockerfile` for CPU-bound workloads (one worker per CPU core is a safe starting point).

---

## 7. Security Checklist

Before going to production, verify each item:

- [ ] `API_KEYS` in `.env` replaced with cryptographically random values (≥32 chars)
- [ ] `.env` added to `.gitignore` — never committed to source control
- [ ] TLS termination configured at the load balancer or reverse proxy (nginx/ALB)
- [ ] `/metrics` endpoint firewalled — accessible only from Prometheus, not the public internet
- [ ] Docker image scanned for CVEs (`docker scout cves datheon-ai:latest`)
- [ ] Container runs as non-root user `appuser` (verified in Dockerfile)
- [ ] `sample_docs` volume mounted read-only (`:ro` in docker-compose.yml)
- [ ] Prometheus data volume not exposed publicly
- [ ] Log aggregation configured (CloudWatch, Datadog, etc.) — `docker compose logs` is not persistent
- [ ] Health check endpoint monitored by your alerting system
- [ ] RBAC user registry (`rag/rbac.py`) backed by your identity provider in production
