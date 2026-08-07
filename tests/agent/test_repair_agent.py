import json
from pathlib import Path

import pytest

from src.agent.wire_repair_agent.repair import AgentLimits, analyze_fixture
from src.agent.wire_repair_agent.tooling import (
    EvidenceRecord,
    StubRepairTools,
    ToolResult,
)
from src.contracts import AgentOutput


ROOT = Path(__file__).resolve().parents[2]


def load_fixture(case_id: str) -> dict:
    return json.loads(
        (ROOT / "fixtures" / "cases" / f"{case_id}.json").read_text(
            encoding="utf-8"
        )
    )


def evidence_contains_scalar(output: AgentOutput, value: str) -> bool:
    return any(value in json.loads(item.content).values() for item in output.evidence)


class NoMatchTools:
    @staticmethod
    def result(case, tool_name: str, evidence_type: str, data: dict) -> ToolResult:
        return ToolResult(
            tool_name=tool_name,
            data=data,
            evidence=EvidenceRecord(
                case_id=case.case_id,
                type=evidence_type,
                source=f"stub://{tool_name}",
                content=json.dumps(data, sort_keys=True),
                produced_by=tool_name,
                timestamp="2026-08-07T09:00:00Z",
            ),
        )

    async def sanctions(self, case):
        return self.result(case, "sanctions", "sanctions", {"status": "clear"})

    async def account_lookup(self, case):
        return self.result(
            case, "account_lookup", "lookup", {"match_status": "not_found"}
        )

    async def counterparty_history(self, case):
        return self.result(
            case, "counterparty_history", "history_match", {"matches": []}
        )

    async def documents(self, case):
        return self.result(
            case, "documents", "document", {"status": "not_found"}
        )


@pytest.mark.anyio
async def test_wire_8802_returns_an_evidence_backed_name_repair():
    raw_output = await analyze_fixture(load_fixture("WIRE-8802"), StubRepairTools())
    output = AgentOutput.from_dict(raw_output)

    assert set(raw_output) == {
        "outcome",
        "proposed_action",
        "confidence",
        "evidence",
        "reasoning_summary",
        "tools_called",
    }
    assert output.outcome == "RESOLVED"
    assert output.proposed_action is not None
    assert output.proposed_action.field == "beneficiary_name"
    assert output.proposed_action.current_value == "PACIFIC STEEL & SUPPY"
    assert output.proposed_action.proposed_value == "PACIFIC STEEL & SUPPLY"
    assert output.confidence == 0.94
    assert output.tools_called == (
        "sanctions",
        "account_lookup",
        "counterparty_history",
    )
    assert evidence_contains_scalar(output, output.proposed_action.proposed_value)


@pytest.mark.anyio
async def test_wire_8841_returns_the_deterministic_policy_block_preview():
    raw_output = await analyze_fixture(load_fixture("WIRE-8841"), StubRepairTools())
    output = AgentOutput.from_dict(raw_output)

    assert output.outcome == "BLOCKED_POLICY"
    assert output.proposed_action is not None
    assert output.proposed_action.field == "beneficiary_account"
    assert output.proposed_action.current_value == "882300441"
    assert output.proposed_action.proposed_value == "8823004417"
    assert output.confidence == 0.91
    assert output.tools_called == (
        "sanctions",
        "account_lookup",
        "counterparty_history",
    )
    assert evidence_contains_scalar(output, output.proposed_action.proposed_value)


@pytest.mark.anyio
async def test_exhaustion_preserves_the_full_bounded_tool_trace():
    raw_output = await analyze_fixture(
        load_fixture("WIRE-8802"),
        NoMatchTools(),
        limits=AgentLimits(
            max_iterations=5,
            token_budget=200,
            estimated_tokens_per_iteration=100,
        ),
    )
    output = AgentOutput.from_dict(raw_output)

    assert output.outcome == "EXHAUSTED"
    assert output.proposed_action is None
    assert output.confidence == 0.0
    assert output.tools_called == (
        "sanctions",
        "account_lookup",
        "counterparty_history",
        "documents",
        "sanctions",
        "account_lookup",
        "counterparty_history",
        "documents",
    )
    assert len(output.evidence) == 8
    assert "token budget" in output.reasoning_summary.lower()
