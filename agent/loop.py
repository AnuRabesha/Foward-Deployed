"""
ReAct agent loop.

Each cycle:
  Thought     — why this tool is being called (from planner reason)
  Action      — tool name + validated args
  Observation — structured result or error from executor

The loop continues through all planned steps, adapting on business errors
by injecting a diagnostic observation and skipping dependent steps.
"""

import json
import textwrap
from dataclasses import dataclass, field
from typing import Any

from agent.planner import plan
from agent.executor import execute, ExecutionResult

_WIDTH = 68


@dataclass
class AgentTrace:
    task: str
    steps: list[dict] = field(default_factory=list)   # full thought/action/obs log
    outputs: dict[str, Any] = field(default_factory=dict)  # tool_name → last output
    success: bool = False
    summary: str = ""


def _box(label: str, content: str, colour_code: str = "") -> None:
    reset = "\033[0m" if colour_code else ""
    border = "─" * _WIDTH
    print(f"\n{colour_code}┌─ {label} {'─' * max(0, _WIDTH - len(label) - 3)}┐{reset}")
    for line in textwrap.wrap(content, width=_WIDTH - 2) or [content]:
        print(f"{colour_code}│ {line:<{_WIDTH - 2}} │{reset}")
    print(f"{colour_code}└{border}┘{reset}")


def _print_thought(text: str) -> None:
    _box("THOUGHT", text, "\033[94m")       # blue


def _print_action(tool: str, args: dict) -> None:
    content = f"{tool}({json.dumps(args, separators=(',', ':'))})"
    _box("ACTION", content, "\033[93m")     # yellow


def _print_observation(result: ExecutionResult) -> None:
    if result.hitl_rejected:
        _box("OBSERVATION", f"[HITL REJECTED] {result.error}", "\033[91m")
        return
    if result.success:
        obs = json.dumps(result.output, indent=2, default=str)
        attempts_note = f"  (attempts: {result.attempts})" if result.attempts > 1 else ""
        _box("OBSERVATION", f"✓ Success{attempts_note}\n{obs}", "\033[92m")  # green
    else:
        retry_log = "; ".join(
            f"attempt {a['attempt']}: {a.get('error','')}" for a in result.attempt_log
        )
        _box("OBSERVATION", f"✗ Error: {result.error}\n{retry_log}", "\033[91m")  # red


def _summarise(trace: AgentTrace) -> str:
    successes = [s for s in trace.steps if s.get("success")]
    failures  = [s for s in trace.steps if not s.get("success") and not s.get("skipped")]
    skipped   = [s for s in trace.steps if s.get("skipped")]
    parts = [f"Completed {len(successes)}/{len(trace.steps)} steps."]
    if failures:
        parts.append(f"Failed: {[f['tool'] for f in failures]}.")
    if skipped:
        parts.append(f"Skipped: {[s['tool'] for s in skipped]}.")
    return " ".join(parts)


def run(task: str, auto_approve: bool = False) -> AgentTrace:
    trace = AgentTrace(task=task)

    print(f"\n{'═' * _WIDTH}")
    print(f"  AGENT TASK: {task}")
    print(f"{'═' * _WIDTH}")

    # ── Plan ─────────────────────────────────────────────────────────────────
    steps = plan(task)
    if not steps:
        print("\n[AGENT] Could not decompose task into tool calls. "
              "Try including entity IDs (SKU-xxx, LEAD-xxx, CUST-xxx).")
        trace.summary = "Planning failed: no steps generated."
        return trace

    print(f"\n[AGENT] Plan: {len(steps)} step(s)")
    for i, s in enumerate(steps, 1):
        print(f"  {i}. {s['tool']}({json.dumps(s['args'])})  ← {s['reason']}")

    # Track which tools have failed so dependent steps can be skipped
    failed_tools: set[str] = set()

    # Prerequisite map — built once, not per iteration
    _DEPS: dict[str, list[str]] = {
        "place_order":        ["inventory_lookup", "customer_lookup"],
        "update_lead_status": ["lead_lookup"],
        "create_ticket":      ["customer_lookup"],
    }

    # ── ReAct loop ────────────────────────────────────────────────────────────
    for i, step in enumerate(steps, 1):
        tool_name = step["tool"]
        args      = step["args"]
        reason    = step["reason"]

        print(f"\n{'·' * _WIDTH}")
        print(f"  Step {i}/{len(steps)}")

        blocked_by = [d for d in _DEPS.get(tool_name, []) if d in failed_tools]
        if blocked_by:
            msg = f"Skipped — prerequisite(s) failed: {blocked_by}"
            _print_thought(f"Cannot proceed with {tool_name}: {msg}")
            trace.steps.append({"tool": tool_name, "skipped": True, "reason": msg})
            print(f"  [SKIP] {msg}")
            continue

        # ── Thought ──────────────────────────────────────────────────────────
        _print_thought(reason)

        # ── Action ───────────────────────────────────────────────────────────
        _print_action(tool_name, args)

        # ── Execute (validate → HITL → retry) ────────────────────────────────
        result = execute(tool_name, args, auto_approve=auto_approve)

        # ── Observation ──────────────────────────────────────────────────────
        _print_observation(result)

        step_record = {
            "tool": tool_name,
            "args": result.args,
            "success": result.success,
            "attempts": result.attempts,
            "hitl_rejected": result.hitl_rejected,
            "output": result.output,
            "error": result.error,
        }
        trace.steps.append(step_record)

        if result.success:
            trace.outputs[tool_name] = result.output
        else:
            failed_tools.add(tool_name)

    # ── Final summary ─────────────────────────────────────────────────────────
    trace.success = all(
        s.get("success") or s.get("hitl_rejected") or s.get("skipped")
        for s in trace.steps
    )
    trace.summary = _summarise(trace)

    print(f"\n{'═' * _WIDTH}")
    print(f"  AGENT SUMMARY: {trace.summary}")
    print(f"{'═' * _WIDTH}\n")

    return trace
