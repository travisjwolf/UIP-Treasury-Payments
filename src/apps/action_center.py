from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.contracts.models import Evidence, PaymentCase, ProposedAction
from src.effectors.stub import (
    Effector,
    EffectorAuthorization,
    EffectorResult,
)

if TYPE_CHECKING:
    from src.maestro.ledger import InMemoryLedger


@dataclass(frozen=True)
class EscalationPayload:
    payment: PaymentCase
    proposal: ProposedAction | None
    gate: str
    reason: str
    evidence: tuple[Evidence, ...]
    cutoff_time: str
    permitted_actions: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "payment": self.payment.model_dump(mode="json"),
            "proposal": (
                self.proposal.model_dump(mode="json")
                if self.proposal is not None
                else None
            ),
            "gate": getattr(self.gate, "value", self.gate),
            "reason": self.reason,
            "evidence": [item.model_dump(mode="json") for item in self.evidence],
            "cutoff_time": self.cutoff_time,
            "permitted_actions": list(self.permitted_actions),
        }


@dataclass(frozen=True)
class HumanActionResult:
    case_id: str
    action: str
    status: str
    effector_result: EffectorResult | None = None


class ActionCenterService:
    def __init__(self, effector: Effector, ledger: InMemoryLedger):
        self.effector = effector
        self.ledger = ledger

    def handle(
        self,
        payload: EscalationPayload,
        action: str,
        edited_proposal: ProposedAction | None = None,
        *,
        reviewer_identity: str = "action-center://demo-operator",
    ) -> HumanActionResult:
        if action not in payload.permitted_actions:
            raise ValueError(f"action {action!r} is not permitted")

        case_id = payload.payment.case_id
        if action == "approve":
            proposal = payload.proposal
            if proposal is None:
                raise ValueError("approve requires a proposal")
            self.ledger.append(case_id, "HUMAN_APPROVED", proposal.field)
            effect = self.effector.apply(
                payload.payment,
                proposal,
                evidence=payload.evidence,
                authorization=EffectorAuthorization.from_human(
                    gate=getattr(payload.gate, "value", payload.gate),
                    reason=payload.reason,
                    reviewer_identity=reviewer_identity,
                ),
            )
            self._record_effect(effect)
            return HumanActionResult(case_id, action, "EFFECT_RECORDED", effect)

        if action == "edit":
            if edited_proposal is None:
                raise ValueError("edit requires edited_proposal")
            if payload.proposal is None:
                raise ValueError("edit requires an original proposal")
            original_field = getattr(payload.proposal.field, "value", payload.proposal.field)
            edited_field = getattr(edited_proposal.field, "value", edited_proposal.field)
            if edited_field != original_field:
                raise ValueError(
                    "edit must preserve the same field evaluated by policy"
                )
            self.ledger.append(case_id, "HUMAN_EDITED", edited_proposal.field)
            effect = self.effector.apply(
                payload.payment,
                edited_proposal,
                evidence=payload.evidence,
                authorization=EffectorAuthorization.from_human(
                    gate=getattr(payload.gate, "value", payload.gate),
                    reason=payload.reason,
                    reviewer_identity=reviewer_identity,
                ),
            )
            self._record_effect(effect)
            return HumanActionResult(case_id, action, "EFFECT_RECORDED", effect)

        state = {
            "reject": ("HUMAN_REJECTED", "REJECTED"),
            "escalate": ("HUMAN_ESCALATED", "ESCALATED"),
            "provide_info": ("INFO_REQUESTED", "INFO_REQUESTED"),
        }[action]
        self.ledger.append(case_id, state[0], payload.gate)
        return HumanActionResult(case_id, action, state[1])

    def _record_effect(self, effect: EffectorResult) -> None:
        audit = effect.audit
        self.ledger.append(
            effect.case_id,
            "EFFECT_RECORDED",
            effect.status,
            actor=audit.credential_identity,
            data={
                "field": audit.field,
                "before": audit.before,
                "after": audit.after,
                "authorized_by": audit.authorized_by,
                "payment_write_performed": False,
            },
        )
        self.ledger.append(
            effect.case_id,
            "CASE_STATE_UPDATED",
            "HUMAN_APPROVED_SANDBOX_RECORDED",
            actor="payment-process",
        )
