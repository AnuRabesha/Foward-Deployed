"""
Mock ERP/CRM REST endpoints (in-process, no network required).

Simulates:
  - Realistic fake data for inventory, leads, tickets, orders, customers
  - Random transient 503s to exercise the retry loop
  - Deliberate business-rule errors (e.g. insufficient stock)
"""

import random
import time
from copy import deepcopy
from typing import Any

# ── Seed data ────────────────────────────────────────────────────────────────

_INVENTORY: dict[str, dict] = {
    "SKU-001": {"name": "Laptop Pro 15",    "qty": 42,  "unit_price": 1299.00, "warehouse": "WH-A"},
    "SKU-002": {"name": "Wireless Mouse",   "qty": 5,   "unit_price": 29.99,  "warehouse": "WH-B"},
    "SKU-003": {"name": "USB-C Hub 7-port", "qty": 0,   "unit_price": 49.99,  "warehouse": "WH-A"},
    "SKU-004": {"name": "4K Monitor 27\"",  "qty": 18,  "unit_price": 549.00, "warehouse": "WH-C"},
}

_LEADS: dict[str, dict] = {
    "LEAD-100": {"company": "Acme Corp",      "contact": "Jane Doe",    "status": "new",         "value": 45000},
    "LEAD-101": {"company": "Globex Inc",     "contact": "John Smith",  "status": "contacted",   "value": 120000},
    "LEAD-102": {"company": "Initech LLC",    "contact": "Bob Slydell", "status": "qualified",   "value": 8500},
    "LEAD-103": {"company": "Umbrella Corp",  "contact": "Alice Wong",  "status": "proposal",    "value": 250000},
}

_TICKETS: dict[str, dict] = {}
_ticket_seq = 200

_ORDERS: dict[str, dict] = {}
_order_seq = 300

_CUSTOMERS: dict[str, dict] = {
    "CUST-001": {"name": "Wayne Enterprises", "tier": "enterprise", "credit_limit": 500000, "balance": 12400},
    "CUST-002": {"name": "Stark Industries",  "tier": "enterprise", "credit_limit": 999999, "balance": 0},
    "CUST-003": {"name": "Daily Planet",      "tier": "standard",   "credit_limit": 25000,  "balance": 3200},
}

_VALID_LEAD_TRANSITIONS: dict[str, list[str]] = {
    "new":        ["contacted"],
    "contacted":  ["qualified", "lost"],
    "qualified":  ["proposal", "lost"],
    "proposal":   ["won", "lost"],
    "won":        [],
    "lost":       [],
}

# ── Helpers ──────────────────────────────────────────────────────────────────

def _latency() -> None:
    """Simulate realistic API latency (50–200 ms)."""
    time.sleep(random.uniform(0.05, 0.20))


def _maybe_transient_error(rate: float = 0.15) -> None:
    """Randomly raise a transient 503 to exercise retry logic."""
    if random.random() < rate:
        raise ConnectionError("503 Service Temporarily Unavailable")


# ── ERP endpoints ────────────────────────────────────────────────────────────

def erp_inventory_lookup(sku: str) -> dict[str, Any]:
    _latency()
    _maybe_transient_error()
    item = _INVENTORY.get(sku.upper())
    if not item:
        raise KeyError(f"SKU '{sku}' not found in inventory")
    return {"sku": sku.upper(), **deepcopy(item)}


def erp_place_order(sku: str, quantity: int, customer_id: str) -> dict[str, Any]:
    global _order_seq
    _latency()
    _maybe_transient_error()

    item = _INVENTORY.get(sku.upper())
    if not item:
        raise KeyError(f"SKU '{sku}' not found")
    if item["qty"] < quantity:
        raise ValueError(
            f"Insufficient stock for {sku}: requested {quantity}, available {item['qty']}"
        )
    customer = _CUSTOMERS.get(customer_id.upper())
    if not customer:
        raise KeyError(f"Customer '{customer_id}' not found")

    total = round(item["unit_price"] * quantity, 2)
    if customer["balance"] + total > customer["credit_limit"]:
        raise ValueError(
            f"Order exceeds credit limit for {customer_id}: "
            f"limit={customer['credit_limit']}, current balance={customer['balance']}, order={total}"
        )

    # All checks passed — commit: sequence first, then mutations
    _order_seq += 1
    order_id = f"ORD-{_order_seq}"
    _INVENTORY[sku.upper()]["qty"] -= quantity
    _ORDERS[order_id] = {
        "sku": sku.upper(), "quantity": quantity,
        "customer_id": customer_id.upper(), "total": total, "status": "confirmed",
    }
    customer["balance"] += total
    return {"order_id": order_id, "total": total, "status": "confirmed"}


# ── CRM endpoints ─────────────────────────────────────────────────────────────

def crm_lead_lookup(lead_id: str) -> dict[str, Any]:
    _latency()
    _maybe_transient_error()
    lead = _LEADS.get(lead_id.upper())
    if not lead:
        raise KeyError(f"Lead '{lead_id}' not found")
    return {"lead_id": lead_id.upper(), **deepcopy(lead)}


def crm_update_lead_status(lead_id: str, new_status: str) -> dict[str, Any]:
    _latency()
    _maybe_transient_error()
    lead = _LEADS.get(lead_id.upper())
    if not lead:
        raise KeyError(f"Lead '{lead_id}' not found")
    allowed = _VALID_LEAD_TRANSITIONS.get(lead["status"], [])
    if new_status not in allowed:
        raise ValueError(
            f"Invalid transition for {lead_id}: '{lead['status']}' → '{new_status}'. "
            f"Allowed: {allowed}"
        )
    old_status = lead["status"]
    _LEADS[lead_id.upper()]["status"] = new_status
    return {"lead_id": lead_id.upper(), "old_status": old_status, "new_status": new_status}


def crm_customer_lookup(customer_id: str) -> dict[str, Any]:
    _latency()
    _maybe_transient_error()
    customer = _CUSTOMERS.get(customer_id.upper())
    if not customer:
        raise KeyError(f"Customer '{customer_id}' not found")
    return {"customer_id": customer_id.upper(), **deepcopy(customer)}


def crm_create_ticket(
    customer_id: str,
    subject: str,
    priority: str,
    description: str,
) -> dict[str, Any]:
    global _ticket_seq
    _latency()
    _maybe_transient_error()
    if customer_id.upper() not in _CUSTOMERS:
        raise KeyError(f"Customer '{customer_id}' not found")
    _ticket_seq += 1
    ticket_id = f"TKT-{_ticket_seq}"
    _TICKETS[ticket_id] = {
        "customer_id": customer_id.upper(),
        "subject": subject,
        "priority": priority,
        "description": description,
        "status": "open",
    }
    return {"ticket_id": ticket_id, "status": "open", "priority": priority}
