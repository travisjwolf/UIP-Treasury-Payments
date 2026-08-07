from __future__ import annotations

from dataclasses import dataclass

from src.contracts.models import Evidence, PaymentCase, ProposedAction


@dataclass(frozen=True)
class EscalationPayload:
    payment: PaymentCase
    proposal: ProposedAction | None
    gate: str
    reason: str
    evidence: tuple[Evidence, ...]
    cutoff_time: str
    permitted_actions: tuple[str, ...]
