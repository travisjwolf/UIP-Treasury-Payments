import json
from pathlib import Path
import subprocess

import pytest

from src.contracts import AgentOutput, PaymentFixture, PolicyConfig, PolicyDecision
from src.gates import evaluate_policy


ROOT = Path(__file__).resolve().parents[2]
FLOW_PATH = (
    ROOT
    / "src"
    / "maestro"
    / "TreasuryPaymentControlTower"
    / "WireRepair"
    / "WireRepair.flow"
)


def _flow() -> dict:
    return json.loads(FLOW_PATH.read_text(encoding="utf-8"))


def _node(flow: dict, node_id: str) -> dict:
    return next(node for node in flow["nodes"] if node["id"] == node_id)


def _script_process(script: str, variables: dict) -> subprocess.CompletedProcess[str]:
    statement = (
        f"const body={json.dumps(script)};"
        f"const variables={json.dumps(variables)};"
        "const result=(new Function('$vars', body))(variables);"
        "process.stdout.write(JSON.stringify(result));"
    )
    return subprocess.run(
        ["node", "-e", statement],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_script(script: str, variables: dict) -> dict:
    completed = _script_process(script, variables)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _fixture(case_id: str) -> PaymentFixture:
    return PaymentFixture.model_validate_json(
        (ROOT / "fixtures" / "cases" / f"{case_id}.json").read_text(
            encoding="utf-8"
        )
    )


def test_flow_has_no_mock_or_caller_controlled_auto_apply_path():
    flow = _flow()
    node_types = {node["type"] for node in flow["nodes"]}
    definition_types = {item["nodeType"] for item in flow["definitions"]}
    globals_by_id = {item["id"]: item for item in flow["variables"]["globals"]}

    assert "core.logic.mock" not in node_types
    assert "core.logic.mock" not in definition_types
    assert "autoApply" not in globals_by_id
    assert {"payment_case", "gate_context", "policy_config"}.issubset(globals_by_id)
    assert _node(flow, "routeDecision")["inputs"]["expression"] == (
        '$vars.policyGate.output.result === "AUTO_APPLY"'
    )
    gate_edge = next(edge for edge in flow["edges"] if edge["id"] == "edge-gate-route")
    assert gate_edge["sourcePort"] == "success"
    assert _node(flow, "end")["outputs"]["reviewedProposedValue"] == {
        "source": "=js:$vars.reviewedProposedValue"
    }

    repair_agent = _node(flow, "repairAgent")
    assert repair_agent == {
        "id": "repairAgent",
        "type": "uipath.core.agent.ee894252-e868-4de2-a8b2-2b29ba8efd07",
        "typeVersion": "1.0.0",
        "display": {"label": "Bravo repair agent", "icon": "coded-agent"},
        "inputs": {
            "payment_case": "=js:$vars.start.output.payment_case",
            "gate_context": "=js:$vars.start.output.gate_context",
            "demo_role": "=js:$vars.start.output.demo_role",
        },
    }
    agent_bindings = [
        item
        for item in flow["bindings"]
        if item["resourceKey"] == "ee894252-e868-4de2-a8b2-2b29ba8efd07"
    ]
    assert {item["name"] for item in agent_bindings} == {"name", "folderPath"}
    assert len(agent_bindings) == 2
    assert next(
        item for item in agent_bindings if item["name"] == "folderPath"
    )["default"] == "TreasuryPayments"

    # The definition is copied verbatim from `registry get --local`; only the
    # deployable top-level resource binding carries the provisioned folder.
    agent_definition = next(
        item
        for item in flow["definitions"]
        if item["nodeType"]
        == "uipath.core.agent.ee894252-e868-4de2-a8b2-2b29ba8efd07"
    )
    definition_bindings = agent_definition["model"]["bindings"]["values"]
    assert next(
        item for item in definition_bindings if item["name"] == "folderPath"
    )["default"] == ""


@pytest.mark.parametrize(
    ("case_id", "agent_values"),
    [
        (
            "WIRE-8802",
            {
                "outcome": "RESOLVED",
                "proposed_action": {
                    "field": "beneficiary_name",
                    "current_value": "PACIFIC STEEL & SUPPY",
                    "proposed_value": "PACIFIC STEEL & SUPPLY",
                },
                "confidence": 0.96,
            },
        ),
        (
            "WIRE-8841",
            {
                "outcome": "BLOCKED_POLICY",
                "proposed_action": {
                    "field": "beneficiary_account",
                    "current_value": "882300441",
                    "proposed_value": "8823004417",
                },
                "confidence": 0.91,
            },
        ),
        (
            "WIRE-8877",
            {
                "outcome": "NEEDS_INFO",
                "proposed_action": None,
                "confidence": 0.74,
            },
        ),
        (
            "WIRE-8917",
            {
                "outcome": "BLOCKED_POLICY",
                "proposed_action": None,
                "confidence": 0.0,
            },
        ),
    ],
)
def test_embedded_gate_matches_alpha_deterministic_evaluator(
    case_id: str,
    agent_values: dict,
):
    flow = _flow()
    fixture = _fixture(case_id)
    agent_output = AgentOutput.model_validate(
        {
            **agent_values,
            "evidence": [],
            "reasoning_summary": "Flow parity fixture.",
            "tools_called": [],
        }
    )
    policy_config = PolicyConfig(
        customer_id=fixture.payment_case.customer_id,
        same_day_beneficiary_velocity_threshold_usd=5_000_000.0,
    )
    expected = evaluate_policy(
        fixture.payment_case,
        agent_output,
        fixture.gate_context,
        policy_config,
    )
    actual = PolicyDecision.model_validate(
        _run_script(
            _node(flow, "policyGate")["inputs"]["script"],
            {
                "start": {
                    "output": {
                        "payment_case": fixture.payment_case.model_dump(mode="json"),
                        "gate_context": fixture.gate_context.model_dump(mode="json"),
                        "policy_config": policy_config.model_dump(mode="json"),
                    }
                },
                "repairAgent": {
                    "output": agent_output.model_dump(mode="json"),
                },
            },
        )
    )

    assert actual == expected


def test_g2_in_embedded_gate_is_a_terminal_non_overridable_result():
    flow = _flow()
    fixture = _fixture("WIRE-8802")
    agent_output = AgentOutput.model_validate(
        {
            "outcome": "BLOCKED_POLICY",
            "proposed_action": {
                "field": "amount_usd",
                "current_value": 84_500.0,
                "proposed_value": 84_501.0,
            },
            "confidence": 1.0,
            "evidence": [],
            "reasoning_summary": "Forbidden amount change.",
            "tools_called": [],
        }
    )
    policy_config = PolicyConfig(
        customer_id=fixture.payment_case.customer_id,
        same_day_beneficiary_velocity_threshold_usd=5_000_000.0,
    )
    result = _run_script(
        _node(flow, "policyGate")["inputs"]["script"],
        {
            "start": {
                "output": {
                    "payment_case": fixture.payment_case.model_dump(mode="json"),
                    "gate_context": fixture.gate_context.model_dump(mode="json"),
                    "policy_config": policy_config.model_dump(mode="json"),
                }
            },
            "repairAgent": {"output": agent_output.model_dump(mode="json")},
        },
    )

    assert result["gate"] == "G2"
    assert result["result"] == "HARD_STOP"
    terminal_edge = next(
        edge
        for edge in flow["edges"]
        if edge["sourceNodeId"] == "humanTaskEligible"
        and edge["sourcePort"] == "false"
    )
    assert terminal_edge["targetNodeId"] == "terminalLedger"


def test_hitl_packet_schema_completed_route_and_effect_boundary_are_auditable():
    flow = _flow()
    task = _node(flow, "humanEscalation")
    fields = {field["id"]: field for field in task["inputs"]["schema"]["fields"]}
    outcomes = task["inputs"]["schema"]["outcomes"]

    assert task["type"] == "uipath.human-in-the-loop"
    assert set(fields) == {
        "payment",
        "proposalfield",
        "currentvalue",
        "proposedvalue",
        "gate",
        "reason",
        "evidence",
        "cutoff",
        "permittedactions",
    }
    assert fields["proposedvalue"]["direction"] == "inOut"
    assert [item["name"] for item in outcomes] == [
        "Approve",
        "Edit",
        "Reject",
        "Escalate",
    ]
    assert any(
        edge["sourceNodeId"] == "humanEscalation"
        and edge["sourcePort"] == "completed"
        for edge in flow["edges"]
    )

    packet = _run_script(
        _node(flow, "escalationPacket")["inputs"]["script"],
        {
            "start": {"output": {"payment_case": {"case_id": "WIRE-8841", "cutoff_time": "17:00"}}},
            "repairAgent": {"output": {"proposed_action": {"field": "beneficiary_account"}, "evidence": []}},
            "policyGate": {"output": {"gate": "G1", "reason": "G1 account change.", "result": "HUMAN_APPROVAL"}},
        },
    )
    assert set(packet) == {
        "payment",
        "proposal",
        "gate",
        "reason",
        "evidence",
        "cutoff_time",
        "permitted_actions",
    }

    for node_id in ("autoEffect", "humanEffect"):
        script = _node(flow, node_id)["inputs"]["script"]
        assert "payment_write_performed: false" in script
        assert "credential_identity" in script
    assert "credential_identity" not in json.dumps(
        _node(flow, "repairAgent")["inputs"]
    )

    ledger_scripts = "\n".join(
        _node(flow, node_id)["inputs"]["script"]
        for node_id in (
            "autoLedger",
            "terminalLedger",
            "humanEffectLedger",
            "humanNoEffectLedger",
        )
    )
    for transition in (
        "GATE_EVALUATED",
        "EFFECT_RECORDED",
        "HUMAN_ESCALATION_CREATED",
        "CASE_STATE_UPDATED",
    ):
        assert transition in ledger_scripts


def test_flow_effectors_parse_canonical_json_evidence_and_fail_closed_cross_case():
    flow = _flow()
    auto_script = _node(flow, "autoEffect")["inputs"]["script"]
    auto_variables = {
        "start": {
            "output": {
                "payment_case": {
                    "case_id": "WIRE-8802",
                    "beneficiary_name": "PACIFIC STEEL & SUPPY",
                },
                "gate_context": {"evaluated_at": "2026-08-07T08:18:00-04:00"},
            }
        },
        "repairAgent": {
            "output": {
                "proposed_action": {
                    "field": "beneficiary_name",
                    "current_value": "PACIFIC STEEL & SUPPY",
                    "proposed_value": "PACIFIC STEEL & SUPPLY",
                },
                "evidence": [
                    {
                        "case_id": "WIRE-8802",
                        "content": json.dumps(
                            {"beneficiary_name": "PACIFIC STEEL & SUPPLY"}
                        ),
                    }
                ],
            }
        },
        "policyGate": {"output": {"result": "AUTO_APPLY", "gate": None}},
    }

    auto_result = _run_script(auto_script, auto_variables)

    assert auto_result["audit"]["after"] == "PACIFIC STEEL & SUPPLY"
    assert auto_result["audit"]["payment_write_performed"] is False

    foreign_variables = json.loads(json.dumps(auto_variables))
    foreign_variables["repairAgent"]["output"]["evidence"][0]["case_id"] = (
        "WIRE-FOREIGN"
    )
    rejected = _script_process(auto_script, foreign_variables)
    assert rejected.returncode != 0
    assert "Evidence case_id must match" in rejected.stderr

    human_script = _node(flow, "humanEffect")["inputs"]["script"]
    human_variables = {
        "start": {
            "output": {
                "payment_case": {
                    "case_id": "WIRE-8841",
                    "beneficiary_account": "882300441",
                },
                "gate_context": {"evaluated_at": "2026-08-07T08:56:00-04:00"},
            }
        },
        "escalationPacket": {
            "output": {
                "proposal": {
                    "field": "beneficiary_account",
                    "current_value": "882300441",
                    "proposed_value": "8823004417",
                },
                "evidence": [
                    {
                        "case_id": "WIRE-8841",
                        "content": json.dumps(
                            {"beneficiary_account": "8823004417"}
                        ),
                    }
                ],
            }
        },
        "policyGate": {"output": {"result": "HUMAN_APPROVAL", "gate": "G1"}},
        "humanEscalation": {
            "status": "Approve",
            "output": {"proposedvalue": "8823004417"},
        },
    }

    human_result = _run_script(human_script, human_variables)

    assert human_result["audit"]["before"] == "882300441"
    assert human_result["audit"]["after"] == "8823004417"
    assert human_result["audit"]["authorization_mode"] == "human_approval"
    assert human_result["audit"]["payment_write_performed"] is False
