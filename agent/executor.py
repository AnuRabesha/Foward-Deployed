"""
Tool executor with validation, HITL gate, and exponential-backoff retry.

Retry policy:
  - Retries only on transient errors (ConnectionError, TimeoutError).
  - Business-rule errors (ValueError, KeyError) are NOT retried — they
    require the agent to revise its arguments.
  - Max 3 attempts with 0.5 s → 1 s → 2 s backoff.
"""

import time
from dataclasses import dataclass, field
from typing import Any

from agent.tools import dispatch
from agent.validator import validate
from agent.hitl import request_confirmation

_MAX_RETRIES = 3
_BASE_BACKOFF = 0.5   # seconds
_TRANSIENT = (ConnectionError, TimeoutError)


@dataclass
class ExecutionResult:
    tool_name: str
    args: dict[str, Any]
    success: bool
    output: Any = None
    error: str = ""
    attempts: int = 0
    hitl_rejected: bool = False
    attempt_log: list[dict] = field(default_factory=list)


def execute(
    tool_name: str,
    raw_args: dict[str, Any],
    auto_approve: bool = False,
) -> ExecutionResult:
    result = ExecutionResult(tool_name=tool_name, args=raw_args, success=False, attempts=0)

    # ── 1. Validate & coerce ─────────────────────────────────────────────────
    try:
        clean_args = validate(tool_name, raw_args)
    except (ValueError, KeyError) as e:
        result.error = f"Validation error: {e}"
        result.attempt_log.append({"attempt": 0, "status": "validation_error", "error": str(e)})
        return result

    result.args = clean_args

    # ── 2. HITL gate ─────────────────────────────────────────────────────────
    from agent.tools import TOOLS
    spec = TOOLS.get(tool_name)
    approved = request_confirmation(
        tool_name, clean_args,
        auto_approve=auto_approve,
        sensitive=spec.sensitive if spec else False,
    )
    if not approved:
        result.hitl_rejected = True
        result.error = "Rejected by human operator."
        return result

    # ── 3. Retry loop ────────────────────────────────────────────────────────
    for attempt in range(1, _MAX_RETRIES + 1):
        result.attempts = attempt
        try:
            output = dispatch(tool_name, clean_args)
            result.success = True
            result.output = output
            result.attempt_log.append({"attempt": attempt, "status": "success"})
            return result

        except _TRANSIENT as e:
            wait = _BASE_BACKOFF * (2 ** (attempt - 1))
            result.attempt_log.append({
                "attempt": attempt, "status": "transient_error",
                "error": str(e), "retry_in_s": wait,
            })
            if attempt < _MAX_RETRIES:
                time.sleep(wait)
            else:
                result.error = f"Max retries exceeded. Last error: {e}"

        except (ValueError, KeyError, PermissionError) as e:
            # Business-rule error — do not retry
            result.error = f"Business error: {e}"
            result.attempt_log.append({"attempt": attempt, "status": "business_error", "error": str(e)})
            return result

    return result
