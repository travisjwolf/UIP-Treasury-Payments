from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Mapping

from .callback import CallbackTranscriptAnalyzer, CallbackTranscriptError
from .tooling import EvidenceRecord, EvidenceType, RepairTools, ToolResult


_EXPECTED_EVIDENCE_TYPES: dict[str, EvidenceType] = {
    "sanctions": "sanctions",
    "account_lookup": "lookup",
    "counterparty_history": "history_match",
    "documents": "document",
    "callback_transcript": "call_transcript",
}


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
    tools_called: list[str] = []
    if (
        case.exception_code == "EX-04"
        and CallbackTranscriptAnalyzer.is_mapped_case(case.case_id)
    ):
        try:
            callback = CallbackTranscriptAnalyzer().analyze(case)
        except CallbackTranscriptError:
            return _callback_failure_output(case)
        invariant_error = _tool_result_invariant_error(
            callback,
            case=case,
            expected_tool_name="callback_transcript",
        )
        if invariant_error is not None:
            return _callback_failure_output(case)
        return _output(
            outcome="NEEDS_INFO",
            proposed_action=None,
            confidence=0.74,
            reasoning_summary=(
                "The partial account confirmation conflicts with the payment "
                "record, so a human must complete verification before any "
                "repair can proceed."
            ),
            trace=[callback],
            tools_called=["callback_transcript"],
        )
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
            tools_called=tools_called,
            max_attempts=iteration_limit,
        )
        if failure is not None:
            return failure
        assert sanctions is not None
        if sanctions.data.get("status") != "clear":
            return _output(
                outcome="BLOCKED_POLICY",
                proposed_action=None,
                confidence=0.0,
                reasoning_summary=(
                    "Latest read-only sanctions evidence is not clear; repair "
                    "evaluation is blocked pending compliance review by the "
                    "authoritative deterministic policy layer."
                ),
                trace=trace,
                tools_called=tools_called,
            )
        account, failure = await _call_read_tool(
            case=case,
            tool_name="account_lookup",
            operation=tools.account_lookup,
            trace=trace,
            tools_called=tools_called,
            max_attempts=iteration_limit,
        )
        if failure is not None:
            return failure
        history_result, failure = await _call_read_tool(
            case=case,
            tool_name="counterparty_history",
            operation=tools.counterparty_history,
            trace=trace,
            tools_called=tools_called,
            max_attempts=iteration_limit,
        )
        if failure is not None:
            return failure
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
                    "History supports the expanded account as a proposal. The "
                    "agent has no authority to apply it; the independent "
                    "deterministic policy evaluation remains authoritative."
                ),
                trace=trace,
                tools_called=tools_called,
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
                tools_called=tools_called,
            )

        _, failure = await _call_read_tool(
            case=case,
            tool_name="documents",
            operation=tools.documents,
            trace=trace,
            tools_called=tools_called,
            max_attempts=iteration_limit,
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
        tools_called=tools_called,
    )


def _callback_failure_output(case: Any) -> dict[str, Any]:
    failure = _runtime_failure_result(
        case_id=case.case_id,
        tool_name="callback_transcript",
        attempt=1,
        error_type="CallbackTranscriptError",
        timestamp=_runtime_trace_timestamp(case, []),
    )
    return _output(
        outcome="EXHAUSTED",
        proposed_action=None,
        confidence=0.0,
        reasoning_summary=(
            "Callback transcript analysis failed closed; a human must review "
            "the case using the sanitized failure trace."
        ),
        trace=[failure],
        tools_called=["callback_transcript"],
    )


async def _call_read_tool(
    *,
    case: Any,
    tool_name: str,
    operation: Callable[[Any], Awaitable[ToolResult]],
    trace: list[ToolResult],
    tools_called: list[str],
    max_attempts: int,
) -> tuple[ToolResult | None, dict[str, Any] | None]:
    for attempt in range(1, max_attempts + 1):
        tools_called.append(tool_name)
        try:
            result = await operation(case)
        except Exception as error:
            trace.append(
                _runtime_failure_result(
                    case_id=case.case_id,
                    tool_name=tool_name,
                    attempt=attempt,
                    error_type=type(error).__name__,
                    timestamp=_runtime_trace_timestamp(case, trace),
                )
            )
            continue

        invariant_error = _tool_result_invariant_error(
            result,
            case=case,
            expected_tool_name=tool_name,
        )
        if invariant_error is not None:
            trace.append(
                _runtime_failure_result(
                    case_id=case.case_id,
                    tool_name=tool_name,
                    attempt=attempt,
                    error_type="TraceabilityContractError",
                    timestamp=_runtime_trace_timestamp(case, trace),
                    reason=invariant_error,
                )
            )
            return None, _output(
                outcome="BLOCKED_POLICY",
                proposed_action=None,
                confidence=0.0,
                reasoning_summary=(
                    f"Read-only tool {tool_name} returned evidence that failed "
                    f"the traceability contract: {invariant_error}. Repair "
                    "evaluation is blocked for system escalation."
                ),
                trace=trace,
                tools_called=tools_called,
            )
        trace.append(result)
        return result, None

    return None, _output(
        outcome="EXHAUSTED",
        proposed_action=None,
        confidence=0.0,
        reasoning_summary=(
            f"Read-only tool {tool_name} failed after {max_attempts} bounded "
            "attempts; the sanitized attempt trace is preserved for system "
            "escalation."
        ),
        trace=trace,
        tools_called=tools_called,
    )


def _tool_result_invariant_error(
    result: Any,
    *,
    case: Any,
    expected_tool_name: str,
) -> str | None:
    if not isinstance(result, ToolResult):
        return "operation did not return a ToolResult"
    evidence = result.evidence
    if result.tool_name != expected_tool_name:
        return "tool identity does not match the operation invoked"
    if not isinstance(evidence, EvidenceRecord):
        return "tool result does not contain a valid EvidenceRecord"
    if evidence.case_id != case.case_id:
        return "evidence case_id does not match the payment case"
    if evidence.produced_by != expected_tool_name:
        return "evidence producer does not match the operation invoked"
    if evidence.type != _EXPECTED_EVIDENCE_TYPES[expected_tool_name]:
        return "evidence type does not match the operation invoked"
    if not isinstance(result.data, Mapping):
        return "tool decision data is not a structured object"

    try:
        payload = (
            json.loads(evidence.content)
            if isinstance(evidence.content, str)
            else evidence.content
        )
    except (TypeError, json.JSONDecodeError):
        return "evidence content is not valid structured JSON"
    if not isinstance(payload, Mapping):
        return "evidence content is not a structured object"
    if dict(payload) != dict(result.data):
        return "decision data does not match the canonical evidence payload"
    return _tool_subject_invariant_error(
        result.data,
        case=case,
        expected_tool_name=expected_tool_name,
    )


def _tool_subject_invariant_error(
    data: Mapping[str, Any],
    *,
    case: Any,
    expected_tool_name: str,
) -> str | None:
    if expected_tool_name == "sanctions":
        required_subject = {
            "case_id": case.case_id,
            "customer_id": case.customer_id,
            "beneficiary_name": case.beneficiary_name,
            "beneficiary_account": case.beneficiary_account,
        }
        if any(key not in data for key in required_subject):
            return "sanctions payload does not identify its complete query subject"
        if any(data[key] != value for key, value in required_subject.items()):
            return "sanctions query subject does not match the payment case"

    if expected_tool_name == "account_lookup":
        if data.get("customer_id") != case.customer_id:
            return "account lookup customer subject does not match the payment case"
        if data.get("queried_beneficiary_account") != case.beneficiary_account:
            return "account lookup query subject does not match the payment case"
        subject_fields = {
            key: data[key]
            for key in ("beneficiary_account", "queried_beneficiary_account")
            if key in data
        }
        if not subject_fields:
            return "account lookup payload does not identify its query subject"
        if any(
            value != case.beneficiary_account
            for value in subject_fields.values()
        ):
            return "account lookup subject does not match the payment case"

    if expected_tool_name == "counterparty_history":
        if data.get("customer_id") != case.customer_id:
            return "history customer subject does not match the payment case"
        if data.get("queried_beneficiary_account") != case.beneficiary_account:
            return "history query subject does not match the payment case"
        if (
            case.exception_code == "EX-02"
            and data.get("beneficiary_name") is not None
            and data.get("beneficiary_account") != case.beneficiary_account
        ):
            return "history account subject does not match the payment case"
        if (
            case.exception_code == "EX-01"
            and data.get("beneficiary_account") is not None
            and data.get("beneficiary_name") != case.beneficiary_name
        ):
            return "history beneficiary subject does not match the payment case"

    if expected_tool_name == "callback_transcript":
        transcript = data.get("transcript")
        if not isinstance(transcript, Mapping):
            return "callback payload does not identify its transcript"
        if transcript.get("case_id") != case.case_id:
            return "callback transcript subject does not match the payment case"
        flagged_fields = data.get("flagged_fields")
        if flagged_fields != ["beneficiary_account"]:
            return "callback transcript does not isolate the account conflict"

    return None


def _runtime_failure_result(
    *,
    case_id: str,
    tool_name: str,
    attempt: int,
    error_type: str,
    timestamp: str,
    reason: str | None = None,
) -> ToolResult:
    data: dict[str, Any] = {
        "attempt": attempt,
        "error_type": error_type,
        "status": "error",
        "tool_name": tool_name,
    }
    if reason is not None:
        data["reason"] = reason
    return ToolResult(
        tool_name=tool_name,
        data=data,
        evidence=EvidenceRecord(
            case_id=case_id,
            type=_EXPECTED_EVIDENCE_TYPES[tool_name],
            source="runtime://tool-call",
            content=json.dumps(data, sort_keys=True),
            produced_by="agent_runtime",
            timestamp=timestamp,
        ),
    )


def _runtime_trace_timestamp(case: Any, trace: list[ToolResult]) -> str:
    if trace:
        previous = trace[-1].evidence.timestamp
        return (
            previous.isoformat()
            if isinstance(previous, datetime)
            else str(previous)
        )

    value_date = getattr(case, "value_date", None)
    if value_date is not None:
        try:
            logical_start = datetime.fromisoformat(str(value_date))
        except ValueError:
            pass
        else:
            if logical_start.tzinfo is None:
                logical_start = logical_start.replace(tzinfo=timezone.utc)
            return logical_start.isoformat()

    return datetime.now(timezone.utc).isoformat()


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
