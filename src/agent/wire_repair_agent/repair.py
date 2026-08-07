from __future__ import annotations

from dataclasses import asdict, dataclass
from types import SimpleNamespace
from typing import Any, Awaitable, Callable

from .tooling import RepairTools, ToolResult


@dataclass(frozen=True)
class AgentLimits:
    max_iterations: int = 3
    token_budget: int = 1_200
    estimated_tokens_per_iteration: int = 400


async def analyze_fixture(
    fixture: dict[str, Any],
    tools: RepairTools,
    *,
    limits: AgentLimits = AgentLimits(),
) -> dict[str, Any]:
    payment = fixture.get("payment_case", fixture.get("payment"))
    if not isinstance(payment, dict):
        raise ValueError("fixture must contain payment_case")
    case = SimpleNamespace(**payment)
    trace: list[ToolResult] = []
    iterations_allowed_by_budget = (
        limits.token_budget // limits.estimated_tokens_per_iteration
    )
    iteration_limit = min(limits.max_iterations, iterations_allowed_by_budget)

    for _ in range(iteration_limit):
        sanctions, failure = await _call_read_tool(
            case=case,
            tool_name="sanctions",
            operation=tools.sanctions,
            trace=trace,
        )
        if failure is not None:
            return failure
        account, failure = await _call_read_tool(
            case=case,
            tool_name="account_lookup",
            operation=tools.account_lookup,
            trace=trace,
        )
        if failure is not None:
            return failure
        history_result, failure = await _call_read_tool(
            case=case,
            tool_name="counterparty_history",
            operation=tools.counterparty_history,
            trace=trace,
        )
        if failure is not None:
            return failure
        assert sanctions is not None
        assert account is not None
        assert history_result is not None
        history = history_result.data

        if case.exception_code == "EX-01" and history.get("beneficiary_account"):
            return _output(
                outcome="BLOCKED_POLICY",
                proposed_action={
                    "field": "beneficiary_account",
                    "current_value": case.beneficiary_account,
                    "proposed_value": history["beneficiary_account"],
                },
                confidence=0.91,
                reasoning_summary=(
                    "History identifies the expanded account, but changing a "
                    "beneficiary account requires the authoritative deterministic "
                    "G1 gate and human approval."
                ),
                trace=trace,
            )

        if case.exception_code == "EX-02" and history.get("beneficiary_name"):
            return _output(
                outcome="RESOLVED",
                proposed_action={
                    "field": "beneficiary_name",
                    "current_value": case.beneficiary_name,
                    "proposed_value": history["beneficiary_name"],
                },
                confidence=history["history_confidence"],
                reasoning_summary=(
                    "Prior successful payments confirm the registered beneficiary "
                    "name for the unchanged account."
                ),
                trace=trace,
            )

        _, failure = await _call_read_tool(
            case=case,
            tool_name="documents",
            operation=tools.documents,
            trace=trace,
        )
        if failure is not None:
            return failure

    stop_reason = (
        "token budget"
        if iterations_allowed_by_budget <= limits.max_iterations
        else "iteration limit"
    )
    return _output(
        outcome="EXHAUSTED",
        proposed_action=None,
        confidence=0.0,
        reasoning_summary=(
            f"Repair investigation exhausted its {stop_reason} after "
            f"{iteration_limit} iterations; the full read-only trace is preserved."
        ),
        trace=trace,
    )


async def _call_read_tool(
    *,
    case: Any,
    tool_name: str,
    operation: Callable[[Any], Awaitable[ToolResult]],
    trace: list[ToolResult],
) -> tuple[ToolResult | None, dict[str, Any] | None]:
    try:
        result = await operation(case)
    except Exception:
        return None, _output(
            outcome="NEEDS_INFO",
            proposed_action=None,
            confidence=0.0,
            reasoning_summary=(
                f"Read-only tool {tool_name} failed; a system retry or human "
                "investigation is required. Evidence collected before the failure "
                "is preserved."
            ),
            trace=trace,
            tools_called=[*[item.tool_name for item in trace], tool_name],
        )
    trace.append(result)
    return result, None


def _output(
    *,
    outcome: str,
    proposed_action: dict[str, Any] | None,
    confidence: float,
    reasoning_summary: str,
    trace: list[ToolResult],
    tools_called: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "outcome": outcome,
        "proposed_action": proposed_action,
        "confidence": confidence,
        "evidence": [asdict(item.evidence) for item in trace],
        "reasoning_summary": reasoning_summary,
        "tools_called": (
            tools_called
            if tools_called is not None
            else [item.tool_name for item in trace]
        ),
    }
