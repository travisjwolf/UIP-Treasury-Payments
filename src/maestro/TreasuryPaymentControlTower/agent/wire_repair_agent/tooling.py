from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol, runtime_checkable


EvidenceType = Literal[
    "lookup",
    "history_match",
    "sanctions",
    "document",
    "call_transcript",
]


class PaymentCaseLike(Protocol):
    case_id: str
    customer_id: str
    beneficiary_name: str
    beneficiary_account: str


@dataclass(frozen=True)
class EvidenceRecord:
    case_id: str
    type: EvidenceType
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


def normalize_beneficiary_name(value: str) -> str:
    """Return the canonical beneficiary-name key used for matching."""
    with_and = value.casefold().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", with_and).split())


class StubRepairTools:
    _TIMESTAMP = "2026-08-07T09:00:00Z"

    @staticmethod
    def _result(
        case: PaymentCaseLike,
        *,
        tool_name: str,
        evidence_type: EvidenceType,
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
                "case_id": case.case_id,
                "customer_id": case.customer_id,
                "beneficiary_name": case.beneficiary_name,
                "beneficiary_account": case.beneficiary_account,
                "status": "clear",
                "screening_id": f"STUB-{case.case_id}",
                "lists_checked": ["OFAC-SDN", "EU-CFSP"],
            },
        )

    async def account_lookup(self, case: PaymentCaseLike) -> ToolResult:
        if case.beneficiary_account == "8823004417":
            data = {
                "customer_id": case.customer_id,
                "match_status": "exact",
                "queried_beneficiary_account": case.beneficiary_account,
                "beneficiary_account": "8823004417",
                "beneficiary_name": "PACIFIC STEEL & SUPPLY",
            }
        else:
            data = {
                "customer_id": case.customer_id,
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
                "queried_beneficiary_account": case.beneficiary_account,
                "beneficiary_name": "PACIFIC STEEL & SUPPLY",
                "beneficiary_account": "8823004417",
                "times_seen": 31,
                "times_repaired": 11,
                "last_applied_fix": "expand_truncated_account",
                "history_confidence": 0.94,
            }
        else:
            data = {
                "customer_id": case.customer_id,
                "queried_beneficiary_account": case.beneficiary_account,
                "matches": [],
            }
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


class CsvRepairTools:
    _TIMESTAMP = "2026-08-07T09:00:00Z"
    _PACKAGE_HISTORY_PATH = (
        Path(__file__).resolve().parent / "data" / "counterparty_history.csv"
    )
    _REPOSITORY_HISTORY_PATH = (
        Path(__file__).resolve().parents[3]
        / "fixtures"
        / "counterparty_history.csv"
    )

    def __init__(self, *, history_path: str | Path | None = None) -> None:
        self.history_path = (
            Path(history_path)
            if history_path is not None
            else self._default_history_path()
        )
        self._delegate = StubRepairTools()

    @classmethod
    def _default_history_path(cls) -> Path:
        if cls._REPOSITORY_HISTORY_PATH.is_file():
            return cls._REPOSITORY_HISTORY_PATH
        return cls._PACKAGE_HISTORY_PATH

    def _rows(self) -> list[dict[str, str | int]]:
        with self.history_path.open(
            "r", encoding="utf-8-sig", newline=""
        ) as stream:
            reader = csv.DictReader(stream)
            return [
                {**row, "_fixture_row": row_number}
                for row_number, row in enumerate(reader, start=2)
            ]

    @staticmethod
    def _selected_data(
        case: PaymentCaseLike,
        row: Mapping[str, str | int],
    ) -> dict[str, Any]:
        return {
            "customer_id": str(row["customer_id"]),
            "queried_beneficiary_account": case.beneficiary_account,
            "beneficiary_name": str(row["beneficiary_name"]),
            "beneficiary_account": str(row["beneficiary_account"]),
            "times_seen": int(row["times_seen"]),
            "times_repaired": int(row["times_repaired"]),
            "last_applied_fix": str(row["last_applied_fix"]),
            "history_confidence": float(row["history_confidence"]),
        }

    def _source(self, row: Mapping[str, str | int] | None = None) -> str:
        source = f"fixture://{self.history_path.name}"
        if row is not None:
            source += f"#row={row['_fixture_row']}"
        return source

    @classmethod
    def _result(
        cls,
        case: PaymentCaseLike,
        *,
        tool_name: str,
        evidence_type: EvidenceType,
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
                timestamp=cls._TIMESTAMP,
            ),
        )

    async def sanctions(self, case: PaymentCaseLike) -> ToolResult:
        return await self._delegate.sanctions(case)

    async def account_lookup(self, case: PaymentCaseLike) -> ToolResult:
        matches = [
            row
            for row in self._rows()
            if row["customer_id"] == case.customer_id
            and row["beneficiary_account"] == case.beneficiary_account
        ]
        data: dict[str, Any] = {
            "customer_id": case.customer_id,
            "match_status": "not_found",
            "queried_beneficiary_account": case.beneficiary_account,
        }
        selected_row = matches[0] if len(matches) == 1 else None
        if selected_row is not None:
            data.update(
                {
                    "match_status": "exact",
                    "beneficiary_account": str(
                        selected_row["beneficiary_account"]
                    ),
                    "beneficiary_name": str(selected_row["beneficiary_name"]),
                }
            )
        elif len(matches) > 1:
            data.update(
                {
                    "match_status": "ambiguous",
                    "match_count": len(matches),
                }
            )
        return self._result(
            case,
            tool_name="account_lookup",
            evidence_type="lookup",
            source=self._source(selected_row),
            data=data,
        )

    async def counterparty_history(self, case: PaymentCaseLike) -> ToolResult:
        rows = self._rows()
        if getattr(case, "exception_code", None) == "EX-01":
            normalized_name = normalize_beneficiary_name(case.beneficiary_name)
            matches = [
                row
                for row in rows
                if row["customer_id"] == case.customer_id
                and normalize_beneficiary_name(str(row["beneficiary_name"]))
                == normalized_name
                and str(row["beneficiary_account"]).startswith(
                    case.beneficiary_account
                )
            ]
        elif getattr(case, "exception_code", None) == "EX-02":
            matches = [
                row
                for row in rows
                if row["customer_id"] == case.customer_id
                and row["beneficiary_account"] == case.beneficiary_account
            ]
        else:
            matches = []

        selected_row = matches[0] if len(matches) == 1 else None
        if selected_row is not None:
            data = self._selected_data(case, selected_row)
        else:
            data = {
                "customer_id": case.customer_id,
                "queried_beneficiary_account": case.beneficiary_account,
                "matches": [],
            }
            if len(matches) > 1:
                data.update(
                    {
                        "match_status": "ambiguous",
                        "match_count": len(matches),
                    }
                )
        return self._result(
            case,
            tool_name="counterparty_history",
            evidence_type="history_match",
            source=self._source(selected_row),
            data=data,
        )

    async def documents(self, case: PaymentCaseLike) -> ToolResult:
        return await self._delegate.documents(case)
