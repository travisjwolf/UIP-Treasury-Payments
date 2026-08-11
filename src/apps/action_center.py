from __future__ import annotations

from dataclasses import dataclass

from src.contracts.models import Evidence, PaymentCase, ProposedAction
from src.effectors.stub import Effector, EffectorResult
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
    ) -> HumanActionResult:
        if action not in payload.permitted_actions:
            raise ValueError(f"action {action!r} is not permitted")

        case_id = payload.payment.case_id
        if action == "approve":
            proposal = payload.proposal
            if proposal is None:
                raise ValueError("approve requires a proposal")
            self.ledger.append(case_id, "HUMAN_APPROVED", proposal.field)
            effect = self.effector.apply(payload.payment, proposal)
            self.ledger.append(case_id, "EFFECT_REQUESTED", effect.status)
            return HumanActionResult(case_id, action, "EFFECT_REQUESTED", effect)

        if action == "edit":
            if edited_proposal is None:
                raise ValueError("edit requires edited_proposal")
            self.ledger.append(case_id, "HUMAN_EDITED", edited_proposal.field)
            effect = self.effector.apply(payload.payment, edited_proposal)
            self.ledger.append(case_id, "EFFECT_REQUESTED", effect.status)
            return HumanActionResult(case_id, action, "EFFECT_REQUESTED", effect)

        state = {
            "reject": ("HUMAN_REJECTED", "REJECTED"),
            "escalate": ("HUMAN_ESCALATED", "ESCALATED"),
            "provide_info": ("INFO_REQUESTED", "INFO_REQUESTED"),
        }[action]
        self.ledger.append(case_id, state[0], payload.gate)
        return HumanActionResult(case_id, action, state[1])
