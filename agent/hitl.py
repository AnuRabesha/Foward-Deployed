"""
Human-in-the-loop (HITL) confirmation gate.

Sensitive write operations (place_order, update_lead_status, create_ticket)
are held here until the operator explicitly approves or rejects them.

Pass auto_approve=True (or --auto-approve CLI flag) to skip prompts in CI.
"""

import json
from typing import Any


# Operations that always require human confirmation regardless of auto_approve
_ALWAYS_CONFIRM = {"place_order"}


def _format_call(tool_name: str, args: dict[str, Any]) -> str:
    args_str = json.dumps(args, indent=4)
    return f"  Tool : {tool_name}\n  Args : {args_str}"


def request_confirmation(
    tool_name: str,
    args: dict[str, Any],
    auto_approve: bool = False,
    sensitive: bool = False,
) -> bool:
    """
    Returns True if the operation is approved, False if rejected.

    - Non-sensitive tools: always approved silently.
    - Sensitive tools with auto_approve=True: approved with a log line
      (except _ALWAYS_CONFIRM tools which always prompt).
    - Sensitive tools without auto_approve: interactive stdin prompt.
    """
    if not sensitive:
        return True  # read-only ops need no confirmation

    always = tool_name in _ALWAYS_CONFIRM

    if auto_approve and not always:
        print(f"  [HITL] Auto-approved sensitive op: {tool_name}")
        return True

    print("\n" + "─" * 60)
    print("  ⚠  HUMAN CONFIRMATION REQUIRED")
    print(_format_call(tool_name, args))
    print("─" * 60)

    while True:
        answer = input("  Approve? [y/n]: ").strip().lower()
        if answer in ("y", "yes"):
            print("  [HITL] Approved.\n")
            return True
        if answer in ("n", "no"):
            print("  [HITL] Rejected by operator.\n")
            return False
        print("  Please enter y or n.")
