"""
Tool registry.

Each tool entry defines:
  - name        : unique identifier used by the agent
  - description : natural-language description for the planner
  - params      : required parameter names
  - sensitive   : True → requires human-in-the-loop confirmation before execution
  - fn          : callable that executes the tool
"""

from dataclasses import dataclass, field
from typing import Callable, Any

from agent.mock_erp import (
    erp_inventory_lookup,
    erp_place_order,
    crm_lead_lookup,
    crm_update_lead_status,
    crm_customer_lookup,
    crm_create_ticket,
)


@dataclass
class ToolSpec:
    name: str
    description: str
    params: list[str]
    fn: Callable[..., Any]
    sensitive: bool = False          # write ops that need HITL confirmation
    optional_params: list[str] = field(default_factory=list)


TOOLS: dict[str, ToolSpec] = {
    t.name: t for t in [
        ToolSpec(
            name="inventory_lookup",
            description="Look up current stock level, unit price, and warehouse for a SKU.",
            params=["sku"],
            fn=erp_inventory_lookup,
        ),
        ToolSpec(
            name="place_order",
            description="Place a purchase order for a SKU on behalf of a customer. Deducts stock.",
            params=["sku", "quantity", "customer_id"],
            fn=erp_place_order,
            sensitive=True,
        ),
        ToolSpec(
            name="lead_lookup",
            description="Retrieve CRM lead details including company, contact, status, and deal value.",
            params=["lead_id"],
            fn=crm_lead_lookup,
        ),
        ToolSpec(
            name="update_lead_status",
            description="Advance a CRM lead to the next pipeline stage.",
            params=["lead_id", "new_status"],
            fn=crm_update_lead_status,
            sensitive=True,
        ),
        ToolSpec(
            name="customer_lookup",
            description="Retrieve customer profile including tier, credit limit, and current balance.",
            params=["customer_id"],
            fn=crm_customer_lookup,
        ),
        ToolSpec(
            name="create_ticket",
            description="Open a support ticket for a customer with subject, priority, and description.",
            params=["customer_id", "subject", "priority", "description"],
            fn=crm_create_ticket,
            sensitive=True,
        ),
    ]
}


def dispatch(tool_name: str, args: dict[str, Any]) -> Any:
    """Look up and call a tool by name with the given arguments."""
    spec = TOOLS.get(tool_name)
    if spec is None:
        raise ValueError(f"Unknown tool: '{tool_name}'. Available: {list(TOOLS)}")
    return spec.fn(**args)
