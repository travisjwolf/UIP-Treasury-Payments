import json
from pathlib import Path
import subprocess
import sys

from src.apps.action_center import EscalationPayload
from src.contracts.fixture_io import load_case_files
from src.contracts.models import AgentOutput, Evidence, PaymentCase, PolicyDecision, ProposedAction
from src.effectors.stub import StubEffector
from src.maestro.ledger import InMemoryLedger
from src.maestro.process import PaymentProcess


ROOT = Path(__file__).resolve().parents[2]
FLOW_PATH = (
    ROOT
    / "src"
    / "maestro"
    / "TreasuryPaymentControlTower"
    / "WireRepair"
    / "WireRepair.flow"
)


def _evidence(case_id: str, content: str) -> list[Evidence]:
    return [
        Evidence(
            case_id=case_id,
            type="history_match",
            source="test-fixture",
            content=content,
            produced_by="test-agent",
            timestamp="2026-08-07T09:00:00Z",
        )
    ]


class DemoAgent:
    def analyze(self, case: PaymentCase, fixture: dict) -> AgentOutput:
        if case.case_id == "WIRE-8802":
            return AgentOutput(
                outcome="RESOLVED",
                proposed_action=ProposedAction(
                    field="beneficiary_name",
                    current_value=case.beneficiary_name,
                    proposed_value="PACIFIC STEEL & SUPPLY",
                ),
                confidence=0.96,
                evidence=tuple(_evidence(case.case_id, "known counterparty name")),
                reasoning_summary="Matched the known counterparty history.",
                tools_called=("counterparty_history",),
            )
        if case.case_id == "WIRE-8841":
            return AgentOutput(
                outcome="RESOLVED",
                proposed_action=ProposedAction(
                    field="beneficiary_account",
                    current_value=case.beneficiary_account,
                    proposed_value="4628492309",
                ),
                confidence=0.91,
                evidence=tuple(_evidence(case.case_id, "prior account lookup")),
                reasoning_summary="Found a prior account for the counterparty.",
                tools_called=("account_lookup",),
            )
        return AgentOutput(
            outcome="NEEDS_INFO",
            proposed_action=None,
            confidence=0.74,
            evidence=tuple(_evidence(case.case_id, "callback required")),
            reasoning_summary="Customer confirmation is required.",
            tools_called=("callback_transcript",),
        )


class DemoGate:
    def evaluate(self, case: PaymentCase, agent_output: AgentOutput) -> PolicyDecision:
        if case.case_id == "WIRE-8802":
            return PolicyDecision(case.case_id, "NONE", "AUTO_APPLY", "All gates clear.", "2026-08-07T09:00:01Z")
        if case.case_id == "WIRE-8841":
            return PolicyDecision(case.case_id, "G1", "HUMAN_APPROVAL", "Beneficiary account change.", "2026-08-07T09:00:01Z")
        return PolicyDecision(case.case_id, "G9", "ESCALATE", "Callback information is required.", "2026-08-07T09:00:01Z")


def _process() -> tuple[PaymentProcess, StubEffector, InMemoryLedger]:
    effector = StubEffector()
    ledger = InMemoryLedger()
    return PaymentProcess(DemoAgent(), DemoGate(), effector, ledger), effector, ledger


def test_harness_routes_all_three_pinned_cases_to_expected_paths():
    process, effector, ledger = _process()
    fixtures = {
        item["case_id"]: item
        for item in load_case_files(ROOT / "fixtures" / "cases")
        if item["case_id"] in {"WIRE-8802", "WIRE-8841", "WIRE-8877"}
    }

    results = [process.run(fixtures[case_id]) for case_id in sorted(fixtures)]

    assert {result.case_id: result.path for result in results} == {
        "WIRE-8802": "auto_apply",
        "WIRE-8841": "human_approval",
        "WIRE-8877": "callback_then_human",
    }
    assert [request.case_id for request in effector.requests] == ["WIRE-8802"]
    assert all(entry.case_id in fixtures for entry in ledger.entries)


def test_human_approval_contains_typed_evidence_packet_and_permitted_actions():
    process, _, _ = _process()
    fixture = next(item for item in load_case_files(ROOT / "fixtures" / "cases") if item["case_id"] == "WIRE-8841")

    result = process.run(fixture)

    assert isinstance(result.escalation, EscalationPayload)
    assert result.escalation.gate == "G1"
    assert result.escalation.proposal.proposed_value == "4628492309"
    assert result.escalation.evidence[0].source == "test-fixture"
    assert result.escalation.permitted_actions == ("approve", "edit", "reject", "escalate")


def test_stub_effector_records_requests_without_performing_payment_writes():
    process, effector, _ = _process()
    fixture = next(item for item in load_case_files(ROOT / "fixtures" / "cases") if item["case_id"] == "WIRE-8802")

    result = process.run(fixture)

    assert result.effector_result.status == "RECORDED"
    assert effector.requests[0].action.proposed_value == "PACIFIC STEEL & SUPPLY"
    assert effector.writes_performed is False


def test_process_module_imports_cleanly_in_a_fresh_interpreter():
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from src.maestro.process import PaymentProcess, ProcessResult",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_maestro_flow_scaffold_models_the_control_path():
    flow = json.loads(FLOW_PATH.read_text(encoding="utf-8"))
    nodes_by_label = {node["display"]["label"]: node for node in flow["nodes"]}

    expected_types = {
        "Intake payment": "core.trigger.manual",
        "Repair agent proposal": "core.logic.mock",
        "Deterministic policy gate": "core.logic.mock",
        "Auto-apply eligible?": "core.logic.decision",
        "Request payment effect": "core.logic.mock",
        "Create human escalation": "core.logic.mock",
        "Append case ledger": "core.logic.mock",
        "Complete payment case": "core.control.end",
    }
    assert {
        label: nodes_by_label[label]["type"] for label in expected_types
    } == expected_types

    node_ids = {label: nodes_by_label[label]["id"] for label in expected_types}
    connected = {
        (edge["sourceNodeId"], edge["sourcePort"], edge["targetNodeId"])
        for edge in flow["edges"]
    }
    assert connected == {
        (node_ids["Intake payment"], "output", node_ids["Repair agent proposal"]),
        (
            node_ids["Repair agent proposal"],
            "output",
            node_ids["Deterministic policy gate"],
        ),
        (
            node_ids["Deterministic policy gate"],
            "output",
            node_ids["Auto-apply eligible?"],
        ),
        (
            node_ids["Auto-apply eligible?"],
            "true",
            node_ids["Request payment effect"],
        ),
        (
            node_ids["Auto-apply eligible?"],
            "false",
            node_ids["Create human escalation"],
        ),
        (
            node_ids["Request payment effect"],
            "output",
            node_ids["Append case ledger"],
        ),
        (
            node_ids["Create human escalation"],
            "output",
            node_ids["Append case ledger"],
        ),
        (
            node_ids["Append case ledger"],
            "output",
            node_ids["Complete payment case"],
        ),
    }
