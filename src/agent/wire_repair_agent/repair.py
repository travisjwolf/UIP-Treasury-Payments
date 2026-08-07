from __future__ import annotations

from dataclasses import asdict, dataclass
from types import SimpleNamespace
from typing import Any

from .tooling import RepairTools


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
    case = SimpleNamespace(**fixture["payment"])
    trace = []
    iterations_allowed_by_budget = (
        limits.token_budget // limits.estimated_tokens_per_iteration
    )
    iteration_limit = min(limits.max_iterations, iterations_allowed_by_budget)

    for _ in range(iteration_limit):
        iteration_results = [
            await tools.sanctions(case),
            await tools.account_lookup(case),
            await tools.counterparty_history(case),
        ]
        trace.extend(iteration_results)
        history = iteration_results[-1].data

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

        trace.append(await tools.documents(case))

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


def _output(
    *,
    outcome: str,
    proposed_action: dict[str, str] | None,
    confidence: float,
    reasoning_summary: str,
    trace: list[Any],
) -> dict[str, Any]:
    return {
        "outcome": outcome,
        "proposed_action": proposed_action,
        "confidence": confidence,
        "evidence": [asdict(item.evidence) for item in trace],
        "reasoning_summary": reasoning_summary,
        "tools_called": [item.tool_name for item in trace],
    }
