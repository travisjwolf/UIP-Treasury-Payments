from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from src.contracts.models import PaymentCase, ProposedAction


@dataclass(frozen=True)
class EffectorRequest:
    case_id: str
    action: ProposedAction


@dataclass(frozen=True)
class EffectorResult:
    case_id: str
    status: str
    message: str


class Effector(Protocol):
    def apply(self, case: PaymentCase, action: ProposedAction) -> EffectorResult:
        ...


@dataclass
class StubEffector:
    requests: list[EffectorRequest] = field(default_factory=list)
    writes_performed: bool = False

    def apply(self, case: PaymentCase, action: ProposedAction) -> EffectorResult:
        self.requests.append(EffectorRequest(case.case_id, action))
        return EffectorResult(case.case_id, "RECORDED", "Sandbox request recorded; no payment write performed.")
