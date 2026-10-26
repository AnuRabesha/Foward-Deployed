"""
Input validator for agent tool calls.

Validates and coerces arguments before they reach the mock ERP/CRM layer.
Raises ValueError with a descriptive message on any violation.
"""

from typing import Any

_VALID_PRIORITIES = {"low", "medium", "high", "critical"}
_VALID_LEAD_STATUSES = {"new", "contacted", "qualified", "proposal", "won", "lost"}


def _require(args: dict, *keys: str) -> None:
    missing = [k for k in keys if k not in args or args[k] is None or str(args[k]).strip() == ""]
    if missing:
        raise ValueError(f"Missing required fields: {missing}")


def validate_inventory_lookup(args: dict[str, Any]) -> dict[str, Any]:
    _require(args, "sku")
    return {"sku": str(args["sku"]).strip().upper()}


def validate_place_order(args: dict[str, Any]) -> dict[str, Any]:
    _require(args, "sku", "quantity", "customer_id")
    qty = int(args["quantity"])
    if qty <= 0:
        raise ValueError(f"quantity must be > 0, got {qty}")
    if qty > 10_000:
        raise ValueError(f"quantity {qty} exceeds single-order limit of 10,000")
    return {
        "sku": str(args["sku"]).strip().upper(),
        "quantity": qty,
        "customer_id": str(args["customer_id"]).strip().upper(),
    }


def validate_lead_lookup(args: dict[str, Any]) -> dict[str, Any]:
    _require(args, "lead_id")
    return {"lead_id": str(args["lead_id"]).strip().upper()}


def validate_update_lead_status(args: dict[str, Any]) -> dict[str, Any]:
    _require(args, "lead_id", "new_status")
    status = str(args["new_status"]).strip().lower()
    if status not in _VALID_LEAD_STATUSES:
        raise ValueError(f"Invalid lead status '{status}'. Valid: {sorted(_VALID_LEAD_STATUSES)}")
    return {"lead_id": str(args["lead_id"]).strip().upper(), "new_status": status}


def validate_customer_lookup(args: dict[str, Any]) -> dict[str, Any]:
    _require(args, "customer_id")
    return {"customer_id": str(args["customer_id"]).strip().upper()}


def validate_create_ticket(args: dict[str, Any]) -> dict[str, Any]:
    _require(args, "customer_id", "subject", "priority", "description")
    priority = str(args["priority"]).strip().lower()
    if priority not in _VALID_PRIORITIES:
        raise ValueError(f"Invalid priority '{priority}'. Valid: {sorted(_VALID_PRIORITIES)}")
    subject = str(args["subject"]).strip()
    if len(subject) < 5:
        raise ValueError("subject must be at least 5 characters")
    return {
        "customer_id": str(args["customer_id"]).strip().upper(),
        "subject": subject,
        "priority": priority,
        "description": str(args["description"]).strip(),
    }


_VALIDATORS = {
    "inventory_lookup":   validate_inventory_lookup,
    "place_order":        validate_place_order,
    "lead_lookup":        validate_lead_lookup,
    "update_lead_status": validate_update_lead_status,
    "customer_lookup":    validate_customer_lookup,
    "create_ticket":      validate_create_ticket,
}


def validate(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Validate and coerce args for the given tool. Returns cleaned args."""
    validator = _VALIDATORS.get(tool_name)
    if validator is None:
        raise ValueError(f"No validator registered for tool '{tool_name}'")
    return validator(args)
