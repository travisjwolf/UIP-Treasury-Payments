from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, ClassVar


AGENT_OUTCOMES = frozenset(
    {
        "RESOLVED",
        "RESOLVED_LOW_CONFIDENCE",
        "AMBIGUOUS",
        "NEEDS_INFO",
        "EXHAUSTED",
        "BLOCKED_POLICY",
    }
)


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class ProposedAction:
    field: str
    current_value: str
    proposed_value: str

    @classmethod
    def from_dict(cls, value: Any) -> "ProposedAction":
        if not isinstance(value, dict):
            raise ValueError("proposed_action must be an object")
        missing = {"field", "current_value", "proposed_value"} - value.keys()
        if missing:
            raise ValueError("proposed_action is missing: " + ", ".join(sorted(missing)))
        return cls(
            field=_required_text(value["field"], "field"),
            current_value=_required_text(value["current_value"], "current_value"),
            proposed_value=_required_text(value["proposed_value"], "proposed_value"),
        )


@dataclass(frozen=True)
class Evidence:
    case_id: str
    type: str
    source: str
    content: str
    produced_by: str
    timestamp: str


@dataclass(frozen=True)
class AgentOutput:
    outcome: str
    proposed_action: ProposedAction | None
    confidence: float
    evidence: tuple[Evidence, ...]
    reasoning_summary: str
    tools_called: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Any) -> "AgentOutput":
        if not isinstance(value, dict):
            raise ValueError("agent output must be an object")
        outcome = value.get("outcome")
        if outcome not in AGENT_OUTCOMES:
            raise ValueError(f"unknown outcome: {outcome}")
        confidence = value.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        action = value.get("proposed_action")
        return cls(
            outcome=outcome,
            proposed_action=None if action is None else ProposedAction.from_dict(action),
            confidence=float(confidence),
            evidence=tuple(Evidence(**item) for item in value.get("evidence", [])),
            reasoning_summary=_required_text(value.get("reasoning_summary"), "reasoning_summary"),
            tools_called=tuple(_required_text(item, "tools_called item") for item in value.get("tools_called", [])),
        )


@dataclass(frozen=True)
class PaymentCase:
    case_id: str
    rail: str
    direction: str
    amount_usd: float
    currency: str
    value_date: str
    cutoff_time: str
    sla_deadline: str | None
    source_channel: str
    customer_id: str
    customer_name: str
    beneficiary_name: str
    beneficiary_account: str
    beneficiary_bank_aba: str
    remittance_info: str
    exception_code: str
    exception_type: str
    current_queue: str | None
    status: str | None
    worked_by: str | None
    confidence: float | None
    proposed_action: ProposedAction | None
    outcome: str | None
    touch_count: int | None
    cycle_time: float | None

    @classmethod
    def field_names(cls) -> tuple[str, ...]:
        return tuple(item.name for item in fields(cls))

    @classmethod
    def from_fixture(cls, fixture: dict[str, Any]) -> "PaymentCase":
        values = fixture.get("payment", fixture)
        missing = set(cls.field_names()) - values.keys()
        if missing:
            raise ValueError("payment is missing: " + ", ".join(sorted(missing)))
        data = dict(values)
        data["amount_usd"] = float(data["amount_usd"])
        if data["confidence"] is not None:
            data["confidence"] = float(data["confidence"])
        if data["touch_count"] is not None:
            data["touch_count"] = int(data["touch_count"])
        if data["cycle_time"] is not None:
            data["cycle_time"] = float(data["cycle_time"])
        if data["proposed_action"] is not None:
            data["proposed_action"] = ProposedAction.from_dict(data["proposed_action"])
        return cls(**data)


@dataclass(frozen=True)
class CounterpartyHistory:
    customer_id: str
    beneficiary_name: str
    beneficiary_account: str
    times_seen: int
    times_repaired: int
    last_applied_fix: str
    history_confidence: float


@dataclass(frozen=True)
class PolicyDecision:
    case_id: str
    gate: str
    result: str
    reason: str
    evaluated_at: str
