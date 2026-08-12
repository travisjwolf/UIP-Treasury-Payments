import json
from pathlib import Path

import pytest

from src.agent.wire_repair_agent.repair import AgentLimits, analyze_fixture
from src.agent.wire_repair_agent.tooling import (
    EvidenceRecord,
    StubRepairTools,
    ToolResult,
)
from src.agent.wire_repair_agent import tooling
from src.contracts import (
    AgentOutput,
    GateId,
    PaymentFixture,
    PolicyConfig,
    PolicyResult,
)
from src.gates import evaluate_policy


ROOT = Path(__file__).resolve().parents[2]


def load_fixture(case_id: str) -> dict:
    return json.loads(
        (ROOT / "fixtures" / "cases" / f"{case_id}.json").read_text(
            encoding="utf-8"
        )
    )


def evidence_contains_scalar(output: AgentOutput, value: str) -> bool:
    return any(
        value
        in (
            json.loads(item.content).values()
            if isinstance(item.content, str)
            else item.content.values()
        )
        for item in output.evidence
    )


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
        return self.result(
            case,
            "sanctions",
            "sanctions",
            {
                "case_id": case.case_id,
                "customer_id": case.customer_id,
                "beneficiary_name": case.beneficiary_name,
                "beneficiary_account": case.beneficiary_account,
                "status": "clear",
            },
        )

    async def account_lookup(self, case):
        return self.result(
            case,
            "account_lookup",
            "lookup",
            {
                "customer_id": case.customer_id,
                "match_status": "not_found",
                "queried_beneficiary_account": case.beneficiary_account,
            },
        )

    async def counterparty_history(self, case):
        return self.result(
            case,
            "counterparty_history",
            "history_match",
            {
                "customer_id": case.customer_id,
                "queried_beneficiary_account": case.beneficiary_account,
                "matches": [],
            },
        )

    async def documents(self, case):
        return self.result(
            case, "documents", "document", {"status": "not_found"}
        )


class FailingTools:
    def __init__(self, fail_on: str, delegate=None):
        self.fail_on = fail_on
        self.delegate = delegate or StubRepairTools()

    async def _call(self, tool_name: str, case):
        if tool_name == self.fail_on:
            raise RuntimeError("synthetic read-only dependency failure")
        return await getattr(self.delegate, tool_name)(case)

    async def sanctions(self, case):
        return await self._call("sanctions", case)

    async def account_lookup(self, case):
        return await self._call("account_lookup", case)

    async def counterparty_history(self, case):
        return await self._call("counterparty_history", case)

    async def documents(self, case):
        return await self._call("documents", case)


class TransientFailTools(FailingTools):
    def __init__(self, fail_on: str, failures_before_success: int):
        super().__init__(fail_on)
        self.failures_remaining = failures_before_success

    async def _call(self, tool_name: str, case):
        if tool_name == self.fail_on and self.failures_remaining > 0:
            self.failures_remaining -= 1
            raise TimeoutError("synthetic transient dependency failure")
        return await getattr(self.delegate, tool_name)(case)


class SanctionsMatchTools(StubRepairTools):
    async def sanctions(self, case):
        return NoMatchTools.result(
            case,
            "sanctions",
            "sanctions",
            {
                "case_id": case.case_id,
                "customer_id": case.customer_id,
                "beneficiary_name": case.beneficiary_name,
                "beneficiary_account": case.beneficiary_account,
                "status": "match",
                "screening_id": f"MATCH-{case.case_id}",
                "lists_checked": ["OFAC-SDN", "EU-CFSP"],
            },
        )


class InconsistentHistoryTools(StubRepairTools):
    def __init__(self, corruption: str):
        self.corruption = corruption

    async def counterparty_history(self, case):
        valid = await super().counterparty_history(case)
        data = dict(valid.data)
        evidence = valid.evidence
        tool_name = valid.tool_name

        if self.corruption == "payload":
            data["beneficiary_name"] = "UNTRACEABLE BENEFICIARY"
        elif self.corruption == "case_id":
            evidence = EvidenceRecord(
                case_id="WIRE-OTHER",
                type=evidence.type,
                source=evidence.source,
                content=evidence.content,
                produced_by=evidence.produced_by,
                timestamp=evidence.timestamp,
            )
        elif self.corruption == "producer":
            evidence = EvidenceRecord(
                case_id=evidence.case_id,
                type=evidence.type,
                source=evidence.source,
                content=evidence.content,
                produced_by="different_tool",
                timestamp=evidence.timestamp,
            )
        elif self.corruption == "tool_name":
            tool_name = "different_tool"

        return ToolResult(tool_name=tool_name, data=data, evidence=evidence)


class CrossSubjectTools(StubRepairTools):
    def __init__(self, corruption: str):
        self.corruption = corruption

    async def sanctions(self, case):
        valid = await super().sanctions(case)
        data = dict(valid.data)
        if self.corruption == "sanctions_customer":
            data.update(
                {
                    "customer_id": "CUST-ATTACKER",
                    "beneficiary_account": "9999999999",
                }
            )
        elif self.corruption == "sanctions_missing_subject":
            data.pop("customer_id")
        return NoMatchTools.result(case, "sanctions", "sanctions", data)

    async def account_lookup(self, case):
        valid = await super().account_lookup(case)
        data = dict(valid.data)
        if self.corruption == "lookup_account":
            data["beneficiary_account"] = "9999999999"
        elif self.corruption == "lookup_query":
            data["queried_beneficiary_account"] = "9999999999"
        elif self.corruption == "lookup_customer":
            data["customer_id"] = "CUST-ATTACKER"
        elif self.corruption == "lookup_missing_subject":
            data.pop("queried_beneficiary_account")
        return NoMatchTools.result(case, "account_lookup", "lookup", data)

    async def counterparty_history(self, case):
        valid = await super().counterparty_history(case)
        data = dict(valid.data)
        if self.corruption == "history_customer":
            data.update(
                {
                    "customer_id": "CUST-ATTACKER",
                    "beneficiary_name": "WRONG CROSS-CUSTOMER NAME",
                    "history_confidence": 0.99,
                }
            )
        elif self.corruption == "history_account":
            data["beneficiary_account"] = "9999999999"
        elif self.corruption == "history_name":
            data["beneficiary_name"] = "UNRELATED BENEFICIARY"
        elif self.corruption == "history_query":
            data["queried_beneficiary_account"] = "9999999999"
        elif self.corruption == "history_missing_subject":
            data.pop("queried_beneficiary_account")
        return NoMatchTools.result(
            case,
            "counterparty_history",
            "history_match",
            data,
        )


class MalformedEvidenceTools(StubRepairTools):
    async def counterparty_history(self, case):
        valid = await super().counterparty_history(case)
        return ToolResult(
            tool_name=valid.tool_name,
            data=valid.data,
            evidence=None,  # type: ignore[arg-type]
        )


def with_exception_code(fixture: dict, exception_code: str) -> dict:
    changed = json.loads(json.dumps(fixture))
    changed["payment_case"]["exception_code"] = exception_code
    return changed


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
    assert output.tools_called == [
        "sanctions",
        "account_lookup",
        "counterparty_history",
    ]
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
    assert output.tools_called == [
        "sanctions",
        "account_lookup",
        "counterparty_history",
    ]
    assert evidence_contains_scalar(output, output.proposed_action.proposed_value)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("case_id", "expected_gate", "expected_result"),
    [
        ("WIRE-8802", None, PolicyResult.AUTO_APPLY),
        ("WIRE-8841", GateId.G1, PolicyResult.HUMAN_APPROVAL),
    ],
)
async def test_hero_agent_outputs_route_through_the_alpha_gate_evaluator(
    case_id: str,
    expected_gate: GateId | None,
    expected_result: PolicyResult,
):
    fixture_data = load_fixture(case_id)
    fixture = PaymentFixture.model_validate(fixture_data)
    output = AgentOutput.from_dict(
        await analyze_fixture(fixture_data, StubRepairTools())
    )

    decision = evaluate_policy(
        fixture.payment_case,
        output,
        fixture.gate_context,
        PolicyConfig(
            customer_id=fixture.payment_case.customer_id,
            same_day_beneficiary_velocity_threshold_usd=5_000_000.0,
        ),
    )

    assert decision.gate == expected_gate
    assert decision.result == expected_result


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
    assert output.tools_called == [
        "sanctions",
        "account_lookup",
        "counterparty_history",
        "documents",
        "sanctions",
        "account_lookup",
        "counterparty_history",
        "documents",
    ]
    assert len(output.evidence) == 8
    assert "token budget" in output.reasoning_summary.lower()


@pytest.mark.anyio
async def test_non_clear_sanctions_evidence_fails_closed_when_gate_context_is_stale():
    fixture_data = load_fixture("WIRE-8802")
    fixture = PaymentFixture.model_validate(fixture_data)

    raw_output = await analyze_fixture(fixture_data, SanctionsMatchTools())
    output = AgentOutput.from_dict(raw_output)
    decision = evaluate_policy(
        fixture.payment_case,
        output,
        fixture.gate_context,
        PolicyConfig(
            customer_id=fixture.payment_case.customer_id,
            same_day_beneficiary_velocity_threshold_usd=5_000_000.0,
        ),
    )

    assert output.outcome == "BLOCKED_POLICY"
    assert output.proposed_action is None
    assert output.confidence == 0.0
    assert output.tools_called == ["sanctions"]
    assert json.loads(output.evidence[0].content)["status"] == "match"
    assert decision.gate is None
    assert decision.result == PolicyResult.ESCALATE


@pytest.mark.anyio
@pytest.mark.parametrize(
    "corruption",
    ["payload", "case_id", "producer", "tool_name"],
)
async def test_inconsistent_tool_result_is_blocked_before_any_proposal(
    corruption: str,
):
    raw_output = await analyze_fixture(
        load_fixture("WIRE-8802"),
        InconsistentHistoryTools(corruption),
    )
    output = AgentOutput.from_dict(raw_output)

    assert output.outcome == "BLOCKED_POLICY"
    assert output.proposed_action is None
    assert output.confidence == 0.0
    assert output.tools_called == [
        "sanctions",
        "account_lookup",
        "counterparty_history",
    ]
    assert len(output.evidence) == 3
    assert {item.case_id for item in output.evidence} == {"WIRE-8802"}
    rejected = output.evidence[-1]
    assert rejected.source == "runtime://tool-call"
    assert rejected.produced_by == "agent_runtime"
    assert json.loads(rejected.content)["error_type"] == (
        "TraceabilityContractError"
    )
    assert "evidence" in output.reasoning_summary.lower()
    assert not evidence_contains_scalar(output, "UNTRACEABLE BENEFICIARY")


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("case_id", "corruption", "rejected_tool"),
    [
        ("WIRE-8802", "sanctions_customer", "sanctions"),
        ("WIRE-8802", "sanctions_missing_subject", "sanctions"),
        ("WIRE-8802", "history_customer", "counterparty_history"),
        ("WIRE-8802", "history_account", "counterparty_history"),
        ("WIRE-8802", "history_query", "counterparty_history"),
        ("WIRE-8802", "history_missing_subject", "counterparty_history"),
        ("WIRE-8802", "lookup_account", "account_lookup"),
        ("WIRE-8802", "lookup_customer", "account_lookup"),
        ("WIRE-8802", "lookup_missing_subject", "account_lookup"),
        ("WIRE-8841", "lookup_query", "account_lookup"),
        ("WIRE-8841", "history_name", "counterparty_history"),
    ],
)
async def test_protocol_conforming_cross_subject_results_fail_closed(
    case_id: str,
    corruption: str,
    rejected_tool: str,
):
    fixture_data = load_fixture(case_id)
    fixture = PaymentFixture.model_validate(fixture_data)
    output = AgentOutput.from_dict(
        await analyze_fixture(fixture_data, CrossSubjectTools(corruption))
    )

    decision = evaluate_policy(
        fixture.payment_case,
        output,
        fixture.gate_context,
        PolicyConfig(
            customer_id=fixture.payment_case.customer_id,
            same_day_beneficiary_velocity_threshold_usd=5_000_000.0,
        ),
    )

    assert output.outcome == "BLOCKED_POLICY"
    assert output.proposed_action is None
    assert output.confidence == 0.0
    assert output.tools_called[-1] == rejected_tool
    assert all(item.case_id == case_id for item in output.evidence)
    assert not evidence_contains_scalar(output, "CUST-ATTACKER")
    assert not evidence_contains_scalar(output, "WRONG CROSS-CUSTOMER NAME")
    assert not evidence_contains_scalar(output, "9999999999")
    assert not evidence_contains_scalar(output, "UNRELATED BENEFICIARY")
    assert "subject" in output.reasoning_summary.lower()
    assert decision.result != PolicyResult.AUTO_APPLY


@pytest.mark.anyio
async def test_malformed_tool_evidence_fails_closed_with_a_typed_trace():
    output = AgentOutput.from_dict(
        await analyze_fixture(load_fixture("WIRE-8802"), MalformedEvidenceTools())
    )

    assert output.outcome == "BLOCKED_POLICY"
    assert output.proposed_action is None
    assert output.tools_called == [
        "sanctions",
        "account_lookup",
        "counterparty_history",
    ]
    assert len(output.evidence) == 3
    rejected = output.evidence[-1]
    assert rejected.source == "runtime://tool-call"
    assert json.loads(rejected.content)["error_type"] == (
        "TraceabilityContractError"
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("failed_tool", "successful_tools"),
    [
        ("sanctions", []),
        ("account_lookup", ["sanctions"]),
        ("counterparty_history", ["sanctions", "account_lookup"]),
        (
            "documents",
            ["sanctions", "account_lookup", "counterparty_history"],
        ),
    ],
)
async def test_tool_failures_exhaust_to_system_escalation_after_bounded_retries(
    failed_tool: str,
    successful_tools: list[str],
):
    fixture = load_fixture("WIRE-8802")
    if failed_tool == "documents":
        fixture = with_exception_code(fixture, "EX-99")

    raw_output = await analyze_fixture(fixture, FailingTools(failed_tool))
    output = AgentOutput.from_dict(raw_output)

    assert output.outcome == "EXHAUSTED"
    assert output.proposed_action is None
    assert output.confidence == 0.0
    assert output.tools_called == [*successful_tools, *([failed_tool] * 3)]
    assert len(output.evidence) == len(successful_tools) + 3
    assert failed_tool in output.reasoning_summary
    assert "3 bounded attempts" in output.reasoning_summary

    failure_evidence = output.evidence[-3:]
    for attempt, item in enumerate(failure_evidence, start=1):
        payload = json.loads(item.content)
        assert item.case_id == "WIRE-8802"
        assert item.source == "runtime://tool-call"
        assert item.produced_by == "agent_runtime"
        assert payload == {
            "attempt": attempt,
            "error_type": "RuntimeError",
            "status": "error",
            "tool_name": failed_tool,
        }

    fixture_model = PaymentFixture.model_validate(fixture)
    decision = evaluate_policy(
        fixture_model.payment_case,
        output,
        fixture_model.gate_context,
        PolicyConfig(
            customer_id=fixture_model.payment_case.customer_id,
            same_day_beneficiary_velocity_threshold_usd=5_000_000.0,
        ),
    )
    assert decision.gate == GateId.G9
    assert decision.result == PolicyResult.ESCALATE


@pytest.mark.anyio
async def test_transient_tool_failure_preserves_attempts_and_then_recovers():
    raw_output = await analyze_fixture(
        load_fixture("WIRE-8802"),
        TransientFailTools("account_lookup", failures_before_success=2),
    )
    output = AgentOutput.from_dict(raw_output)

    assert output.outcome == "RESOLVED"
    assert output.proposed_action is not None
    assert output.proposed_action.proposed_value == "PACIFIC STEEL & SUPPLY"
    assert output.tools_called == [
        "sanctions",
        "account_lookup",
        "account_lookup",
        "account_lookup",
        "counterparty_history",
    ]
    assert len(output.evidence) == 5
    assert [
        json.loads(item.content).get("error_type")
        for item in output.evidence
        if item.source == "runtime://tool-call"
    ] == ["TimeoutError", "TimeoutError"]
    timestamps = [item.timestamp for item in output.evidence]
    assert timestamps == sorted(timestamps)
    assert evidence_contains_scalar(output, output.proposed_action.proposed_value)


@pytest.mark.anyio
async def test_initial_transient_failure_trace_has_monotonic_timestamps():
    output = AgentOutput.from_dict(
        await analyze_fixture(
            load_fixture("WIRE-8802"),
            TransientFailTools("sanctions", failures_before_success=2),
        )
    )

    assert output.outcome == "RESOLVED"
    assert output.tools_called[:3] == ["sanctions", "sanctions", "sanctions"]
    timestamps = [item.timestamp for item in output.evidence]
    assert timestamps == sorted(timestamps)


@pytest.mark.anyio
@pytest.mark.parametrize(
    (
        "case_id",
        "expected_outcome",
        "field",
        "current_value",
        "proposed_value",
        "confidence",
    ),
    [
        (
            "WIRE-8802",
            "RESOLVED",
            "beneficiary_name",
            "PACIFIC STEEL & SUPPY",
            "PACIFIC STEEL & SUPPLY",
            0.94,
        ),
        (
            "WIRE-8841",
            "BLOCKED_POLICY",
            "beneficiary_account",
            "882300441",
            "8823004417",
            0.91,
        ),
    ],
)
async def test_csv_tools_produce_both_primary_hero_proposals_from_selected_history(
    case_id: str,
    expected_outcome: str,
    field: str,
    current_value: str,
    proposed_value: str,
    confidence: float,
):
    implementation = getattr(tooling, "CsvRepairTools", None)
    assert implementation is not None, "CsvRepairTools is not implemented"

    output = AgentOutput.from_dict(
        await analyze_fixture(load_fixture(case_id), implementation())
    )

    assert output.outcome == expected_outcome
    assert output.proposed_action is not None
    assert output.proposed_action.field == field
    assert output.proposed_action.current_value == current_value
    assert output.proposed_action.proposed_value == proposed_value
    assert output.confidence == confidence
    selected_history = [
        item
        for item in output.evidence
        if item.produced_by == "counterparty_history"
    ]
    assert len(selected_history) == 1
    assert selected_history[0].source == (
        "fixture://counterparty_history.csv#row=18"
    )
    assert proposed_value in json.loads(selected_history[0].content).values()
