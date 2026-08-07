from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LedgerEntry:
    case_id: str
    state: str
    detail: str


@dataclass
class InMemoryLedger:
    entries: list[LedgerEntry] = field(default_factory=list)

    def append(self, case_id: str, state: str, detail: str) -> LedgerEntry:
        entry = LedgerEntry(case_id, state, detail)
        self.entries.append(entry)
        return entry
