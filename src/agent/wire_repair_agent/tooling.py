from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable


class PaymentCaseLike(Protocol):
    case_id: str
    customer_id: str
    beneficiary_account: str


@dataclass(frozen=True)
class EvidenceRecord:
    case_id: str
    type: str
    source: str
    content: str
    produced_by: str
    timestamp: str


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    data: Mapping[str, Any]
    evidence: EvidenceRecord


@runtime_checkable
class RepairTools(Protocol):
    async def sanctions(self, case: PaymentCaseLike) -> ToolResult: ...

    async def account_lookup(self, case: PaymentCaseLike) -> ToolResult: ...

    async def counterparty_history(self, case: PaymentCaseLike) -> ToolResult: ...

    async def documents(self, case: PaymentCaseLike) -> ToolResult: ...


class StubRepairTools:
    _TIMESTAMP = "2026-08-07T09:00:00Z"

    @staticmethod
    def _result(
        case: PaymentCaseLike,
        *,
        tool_name: str,
        evidence_type: str,
        source: str,
        data: Mapping[str, Any],
    ) -> ToolResult:
        return ToolResult(
            tool_name=tool_name,
            data=data,
            evidence=EvidenceRecord(
                case_id=case.case_id,
                type=evidence_type,
                source=source,
                content=json.dumps(data, sort_keys=True),
                produced_by=tool_name,
                timestamp=StubRepairTools._TIMESTAMP,
            ),
        )

    async def sanctions(self, case: PaymentCaseLike) -> ToolResult:
        return self._result(
            case,
            tool_name="sanctions",
            evidence_type="sanctions",
            source="stub://sanctions-screening",
            data={
                "status": "clear",
                "screening_id": f"STUB-{case.case_id}",
                "lists_checked": ["OFAC-SDN", "EU-CFSP"],
            },
        )

    async def account_lookup(self, case: PaymentCaseLike) -> ToolResult:
        if case.beneficiary_account == "8823004417":
            data = {
                "match_status": "exact",
                "beneficiary_account": "8823004417",
                "beneficiary_name": "PACIFIC STEEL & SUPPLY",
            }
        else:
            data = {
                "match_status": "not_found",
                "queried_beneficiary_account": case.beneficiary_account,
            }
        return self._result(
            case,
            tool_name="account_lookup",
            evidence_type="lookup",
            source="stub://core-account-lookup",
            data=data,
        )

    async def counterparty_history(self, case: PaymentCaseLike) -> ToolResult:
        is_known_counterparty = (
            case.customer_id == "CUST-1042"
            and case.beneficiary_account in {"882300441", "8823004417"}
        )
        if is_known_counterparty:
            data = {
                "customer_id": "CUST-1042",
                "beneficiary_name": "PACIFIC STEEL & SUPPLY",
                "beneficiary_account": "8823004417",
                "times_seen": 31,
                "times_repaired": 11,
                "last_applied_fix": "expand_truncated_account",
                "history_confidence": 0.94,
            }
        else:
            data = {"customer_id": case.customer_id, "matches": []}
        return self._result(
            case,
            tool_name="counterparty_history",
            evidence_type="history_match",
            source="stub://counterparty-history",
            data=data,
        )

    async def documents(self, case: PaymentCaseLike) -> ToolResult:
        return self._result(
            case,
            tool_name="documents",
            evidence_type="document",
            source="stub://document-store",
            data={"status": "not_required", "documents": []},
        )
