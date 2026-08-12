from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal, Protocol, Sequence

from src.contracts.models import Evidence, PaymentCase, PolicyDecision, ProposedAction


class EffectorAuthorizationError(ValueError):
    """Raised when a proposal is not authorized for the sandbox effector."""


@dataclass(frozen=True)
class EffectorAuthorization:
    mode: Literal["auto_apply", "human_approval"]
    gate: str
    reason: str
    authorized_by: str

    @classmethod
    def from_policy(cls, decision: PolicyDecision) -> "EffectorAuthorization":
        if decision.result.value != "AUTO_APPLY":
            raise EffectorAuthorizationError(
                "deterministic AUTO_APPLY authorization is required"
            )
        return cls(
            mode="auto_apply",
            gate=getattr(decision.gate, "value", decision.gate) or "NONE",
            reason=decision.reason,
            authorized_by="deterministic-policy-gate",
        )

    @classmethod
    def from_human(
        cls,
        *,
        gate: str,
        reason: str,
        reviewer_identity: str,
    ) -> "EffectorAuthorization":
        reviewer_identity = reviewer_identity.strip()
        if not reviewer_identity:
            raise EffectorAuthorizationError("human approval identity is required")
        if gate in {"G0", "G2"}:
            raise EffectorAuthorizationError(f"{gate} cannot be overridden by a human")
        return cls(
            mode="human_approval",
            gate=gate,
            reason=reason,
            authorized_by=reviewer_identity,
        )


@dataclass(frozen=True)
class EffectorAuditRecord:
    case_id: str
    field: str
    before: str | int | float
    after: str | int | float
    credential_identity: str
    authorization_mode: str
    authorized_by: str
    gate: str
    recorded_at: str
    payment_write_performed: bool = False


@dataclass(frozen=True)
class EffectorRequest:
    case_id: str
    action: ProposedAction
    authorization: EffectorAuthorization
    audit: EffectorAuditRecord


@dataclass(frozen=True)
class EffectorResult:
    case_id: str
    status: str
    message: str
    audit: EffectorAuditRecord


class Effector(Protocol):
    def apply(
        self,
        case: PaymentCase,
        action: ProposedAction,
        *,
        evidence: Sequence[Evidence],
        authorization: EffectorAuthorization | None = None,
    ) -> EffectorResult:
        ...


@dataclass
class SandboxEffector:
    credential_identity: str = "sandbox://wire-repair-effector"
    recorded_at: str = "2026-08-07T09:15:00Z"
    requests: list[EffectorRequest] = field(default_factory=list)
    writes_performed: bool = False

    def apply(
        self,
        case: PaymentCase,
        action: ProposedAction,
        *,
        evidence: Sequence[Evidence],
        authorization: EffectorAuthorization | None = None,
    ) -> EffectorResult:
        if authorization is None:
            raise EffectorAuthorizationError(
                "human approval or deterministic AUTO_APPLY authorization is required"
            )

        field_name = getattr(action.field, "value", action.field)
        before = getattr(case, field_name)
        if action.current_value != before:
            raise EffectorAuthorizationError(
                "proposal current_value does not match the payment record"
            )
        if any(item.case_id != case.case_id for item in evidence):
            raise EffectorAuthorizationError(
                "evidence case_id must match the payment record"
            )
        if not _is_traceable(action.proposed_value, evidence):
            raise EffectorAuthorizationError(
                "proposed value must be traceable to the supplied evidence"
            )
        if field_name in {"amount_usd", "currency"}:
            raise EffectorAuthorizationError(
                f"{field_name} is a non-overridable policy hard stop"
            )
        if authorization.mode == "auto_apply" and field_name == "beneficiary_account":
            raise EffectorAuthorizationError(
                f"{field_name} is not eligible for autonomous application"
            )

        audit = EffectorAuditRecord(
            case_id=case.case_id,
            field=field_name,
            before=before,
            after=action.proposed_value,
            credential_identity=self.credential_identity,
            authorization_mode=authorization.mode,
            authorized_by=authorization.authorized_by,
            gate=authorization.gate,
            recorded_at=self.recorded_at,
        )
        self.requests.append(EffectorRequest(case.case_id, action, authorization, audit))
        return EffectorResult(
            case.case_id,
            "RECORDED",
            "Sandbox effect recorded; no payment write performed.",
            audit,
        )


def _is_traceable(value: str | int | float, evidence: Sequence[Evidence]) -> bool:
    return any(_contains_value(_content(item), value) for item in evidence)


def _content(evidence: Evidence) -> object:
    content = evidence.content
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return content
    return content


def _contains_value(payload: object, expected: object) -> bool:
    if payload == expected:
        return True
    if isinstance(payload, dict):
        return any(_contains_value(value, expected) for value in payload.values())
    if isinstance(payload, (list, tuple)):
        return any(_contains_value(value, expected) for value in payload)
    return False


StubEffector = SandboxEffector
