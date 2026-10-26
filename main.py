"""
CLI entry point.

Usage:
  python main.py ingest [--docs ./sample_docs] [--batch-size 64]
  python main.py query "your search query" [--department finance] [--access-tier internal] [--top-k 5]
  python main.py ask "your question" --user alice [--top-k 5]
  python main.py agent "order 5 units of SKU-001 for CUST-002" [--auto-approve]
"""

import argparse
import json

from pipeline.ingest import run_pipeline
from pipeline.embedder import VectorStore
from rag.engine import RAGEngine
from agent.loop import run as agent_run


def cmd_ingest(args):
    benchmark = run_pipeline(
        docs_dir=args.docs,
        manifest=args.manifest,
        batch_size=args.batch_size,
        db_path=args.db,
    )
    print("\n--- Benchmark Summary ---")
    print(json.dumps(benchmark, indent=2))


def cmd_query(args):
    store = VectorStore(db_path=args.db)
    where = {}
    if args.department:
        where["department"] = args.department
    if args.access_tier:
        where["access_tier"] = args.access_tier

    results = store.query(args.query, n_results=args.top_k, where=where or None)
    print(f"\nTop {len(results)} results for: '{args.query}'\n")
    for i, r in enumerate(results, 1):
        print(f"[{i}] distance={r['distance']:.4f} | {r['metadata']}")
        print(f"    {r['text'][:200]}\n")


def cmd_ask(args):
    engine = RAGEngine(db_path=args.db)
    try:
        response = engine.ask(
            query=args.query,
            user_id=args.user,
            top_k=args.top_k,
            n_rewrites=args.rewrites,
        )
    except PermissionError as e:
        print(f"\n[ACCESS DENIED] {e}")
        return

    print(f"\n{'='*60}")
    print(f"Query   : {args.query}")
    print(f"User    : {args.user}")
    print(f"Rewrites: {response.sub_queries}")
    print(f"{'='*60}")
    print(f"\nAnswer:\n{response.answer}")
    print(f"\nCitations: {', '.join(response.citations) or 'none'}")
    if response.flagged_sentences:
        print(f"\n[GUARDRAIL] Removed ungrounded sentences:")
        for s in response.flagged_sentences:
            print(f"  - {s}")
    print(f"\nGrounded: {response.grounded}")
    print(f"Chunks used: {len(response.chunks_used)}")
    for i, c in enumerate(response.chunks_used, 1):
        meta = c['metadata']
        score = c.get('rerank_score', 'n/a')
        print(f"  [{i}] score={score} | {meta.get('source')} | "
              f"dept={meta.get('department')} | tier={meta.get('access_tier')} | "
              f"page={meta.get('page', 'n/a')}")


def main():
    parser = argparse.ArgumentParser(description="Vector ETL Pipeline + RAG Engine")
    parser.add_argument("--db", default="./chroma_db", help="ChromaDB storage path")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Ingest documents into vector DB")
    p_ingest.add_argument("--docs", default="./sample_docs")
    p_ingest.add_argument("--manifest", default="./manifest.json")
    p_ingest.add_argument("--batch-size", type=int, default=64)
    p_ingest.set_defaults(func=cmd_ingest)

    p_query = sub.add_parser("query", help="Raw semantic search with metadata filters")
    p_query.add_argument("query")
    p_query.add_argument("--department", default=None)
    p_query.add_argument("--access-tier", default=None)
    p_query.add_argument("--top-k", type=int, default=5)
    p_query.set_defaults(func=cmd_query)

    p_ask = sub.add_parser("ask", help="RAG: RBAC-enforced Q&A with citations")
    p_ask.add_argument("query")
    p_ask.add_argument("--user", required=True, help="User ID for RBAC enforcement")
    p_ask.add_argument("--top-k", type=int, default=5)
    p_ask.add_argument("--rewrites", type=int, default=3)
    p_ask.set_defaults(func=cmd_ask)

    p_agent = sub.add_parser("agent", help="Autonomous ERP/CRM agent with HITL confirmation")
    p_agent.add_argument("task", help="Natural-language task description")
    p_agent.add_argument(
        "--auto-approve", action="store_true",
        help="Skip HITL prompts for non-critical sensitive ops (useful for demos/CI)",
    )
    p_agent.set_defaults(func=lambda a: agent_run(a.task, auto_approve=a.auto_approve))

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
