from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.maestro.process import ProcessResult


@dataclass(frozen=True)
class QueueItem:
    case_id: str
    amount_usd: float
    currency: str
    cutoff_time: str
    status: str
    confidence: float
    outcome: str
    gate: str
    evidence_count: int


@dataclass(frozen=True)
class CaseDetail(QueueItem):
    customer_name: str
    beneficiary_name: str
    exception_code: str
    exception_type: str
    proposed_field: str | None
    proposed_value: str | None
    reasoning_summary: str
    tools_called: tuple[str, ...]


def _status(result: ProcessResult) -> str:
    return {
        "auto_apply": "AUTO_APPLY_PENDING",
        "human_approval": "HUMAN_APPROVAL_REQUIRED",
        "callback_then_human": "CALLBACK_REQUIRED",
    }[result.path]


def project_case(result: ProcessResult) -> CaseDetail:
    case = result.payment
    proposal = result.agent_output.proposed_action
    return CaseDetail(
        case_id=result.case_id,
        amount_usd=case.amount_usd,
        currency=case.currency,
        cutoff_time=case.cutoff_time,
        status=_status(result),
        confidence=result.agent_output.confidence,
        outcome=result.agent_output.outcome,
        gate=result.decision.gate,
        evidence_count=len(result.agent_output.evidence),
        customer_name=case.customer_name,
        beneficiary_name=case.beneficiary_name,
        exception_code=case.exception_code,
        exception_type=case.exception_type,
        proposed_field=proposal.field if proposal else None,
        proposed_value=proposal.proposed_value if proposal else None,
        reasoning_summary=result.agent_output.reasoning_summary,
        tools_called=result.agent_output.tools_called,
    )


def project_queue(results: list[ProcessResult]) -> list[QueueItem]:
    return [
        QueueItem(
            case_id=item.case_id,
            amount_usd=item.amount_usd,
            currency=item.currency,
            cutoff_time=item.cutoff_time,
            status=item.status,
            confidence=item.confidence,
            outcome=item.outcome,
            gate=item.gate,
            evidence_count=item.evidence_count,
        )
        for item in (project_case(result) for result in results)
    ]
