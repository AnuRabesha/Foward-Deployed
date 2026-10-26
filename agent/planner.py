"""
Rule-based task planner.

Parses a natural-language task into an ordered list of tool-call steps.
Each step is a dict: {"tool": str, "args": dict, "reason": str}.

In production, replace `plan()` with an LLM call (e.g. Bedrock Claude
with function-calling) that returns the same step schema.
"""

import re
from typing import Any


# ── Entity extractors ────────────────────────────────────────────────────────

def _find(pattern: str, text: str, group: int = 1) -> str | None:
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(group).strip() if m else None


def _extract_sku(text: str) -> str | None:
    return _find(r"\b(SKU-\d+)\b", text)


def _extract_lead(text: str) -> str | None:
    return _find(r"\b(LEAD-\d+)\b", text)


def _extract_customer(text: str) -> str | None:
    return _find(r"\b(CUST-\d+)\b", text)


def _extract_qty(text: str) -> int | None:
    # Match "5 units", "5 pcs", etc.
    m = _find(r"\b(\d+)\s*(?:units?|pcs?|pieces?|items?|qty)\b", text)
    if m:
        return int(m)
    # Fallback: bare number immediately before or after a SKU token
    m2 = re.search(r"\b(\d+)\s+SKU-\d+|SKU-\d+\s+(\d+)\b", text, re.IGNORECASE)
    if m2:
        raw = m2.group(1) or m2.group(2)
        return int(raw)
    return None


def _extract_status(text: str) -> str | None:
    statuses = ["contacted", "qualified", "proposal", "won", "lost"]
    for s in statuses:
        if s in text.lower():
            return s
    return None


def _extract_priority(text: str) -> str:
    for p in ("critical", "high", "medium", "low"):
        if p in text.lower():
            return p
    return "medium"


# ── Intent → plan rules ──────────────────────────────────────────────────────

def _plan_order(text: str) -> list[dict[str, Any]]:
    sku = _extract_sku(text)
    qty = _extract_qty(text)
    cust = _extract_customer(text)
    steps = []
    if sku:
        steps.append({"tool": "inventory_lookup", "args": {"sku": sku},
                      "reason": f"Verify stock availability for {sku} before placing order"})
    if cust:
        steps.append({"tool": "customer_lookup", "args": {"customer_id": cust},
                      "reason": f"Check credit limit for {cust} before committing order"})
    if sku and qty and cust:
        steps.append({"tool": "place_order",
                      "args": {"sku": sku, "quantity": qty, "customer_id": cust},
                      "reason": f"Place order: {qty}x {sku} for {cust}"})
    return steps


def _plan_lead(text: str) -> list[dict[str, Any]]:
    lead = _extract_lead(text)
    status = _extract_status(text)
    steps = []
    if lead:
        steps.append({"tool": "lead_lookup", "args": {"lead_id": lead},
                      "reason": f"Retrieve current lead state for {lead}"})
    if lead and status:
        steps.append({"tool": "update_lead_status",
                      "args": {"lead_id": lead, "new_status": status},
                      "reason": f"Advance {lead} to '{status}'"})
    return steps


def _plan_ticket(text: str) -> list[dict[str, Any]]:
    cust = _extract_customer(text)
    priority = _extract_priority(text)
    subject_m = re.search(r'(?:ticket|issue|problem|support)[:\s]+["\']?([^"\'.\n]{5,60})', text, re.I)
    subject = subject_m.group(1).strip() if subject_m else "Support request"
    steps = []
    if cust:
        steps.append({"tool": "customer_lookup", "args": {"customer_id": cust},
                      "reason": f"Verify customer {cust} exists before creating ticket"})
        steps.append({"tool": "create_ticket",
                      "args": {
                          "customer_id": cust,
                          "subject": subject,
                          "priority": priority,
                          "description": text[:300],
                      },
                      "reason": f"Open {priority}-priority ticket for {cust}"})
    return steps


def _plan_inventory(text: str) -> list[dict[str, Any]]:
    sku = _extract_sku(text)
    if sku:
        return [{"tool": "inventory_lookup", "args": {"sku": sku},
                 "reason": f"Look up inventory for {sku}"}]
    return []


# ── Intent classifier ────────────────────────────────────────────────────────

_INTENT_KEYWORDS: list[tuple[list[str], Any]] = [
    (["order", "purchase", "buy", "place order"],          _plan_order),
    (["lead", "pipeline", "crm", "advance", "qualify"],    _plan_lead),
    (["ticket", "support", "issue", "problem", "incident"], _plan_ticket),
    (["inventory", "stock", "sku", "warehouse"],           _plan_inventory),
]


def plan(task: str) -> list[dict[str, Any]]:
    """
    Decompose a natural-language task into ordered tool-call steps.
    Returns a list of {"tool": str, "args": dict, "reason": str}.
    """
    lower = task.lower()
    for keywords, handler in _INTENT_KEYWORDS:
        if any(kw in lower for kw in keywords):
            steps = handler(task)
            if steps:
                return steps

    # Fallback: try all extractors and return whatever makes sense
    steps: list[dict[str, Any]] = []
    if sku := _extract_sku(task):
        steps.append({"tool": "inventory_lookup", "args": {"sku": sku},
                      "reason": "Fallback: found SKU in task"})
    if lead := _extract_lead(task):
        steps.append({"tool": "lead_lookup", "args": {"lead_id": lead},
                      "reason": "Fallback: found lead ID in task"})
    if cust := _extract_customer(task):
        steps.append({"tool": "customer_lookup", "args": {"customer_id": cust},
                      "reason": "Fallback: found customer ID in task"})
    return steps
