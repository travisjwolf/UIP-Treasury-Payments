from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class LedgerEntry:
    case_id: str
    state: str
    detail: str
    actor: str
    occurred_at: str
    data: dict[str, Any]


@dataclass
class InMemoryLedger:
    entries: list[LedgerEntry] = field(default_factory=list)

    def append(
        self,
        case_id: str,
        state: str,
        detail: str,
        *,
        actor: str = "payment-process",
        occurred_at: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> LedgerEntry:
        entry = LedgerEntry(
            case_id=case_id,
            state=state,
            detail=detail,
            actor=actor,
            occurred_at=(
                occurred_at
                or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            ),
            data=dict(data or {}),
        )
        self.entries.append(entry)
        return entry

    def for_case(self, case_id: str) -> list[LedgerEntry]:
        return [entry for entry in self.entries if entry.case_id == case_id]
