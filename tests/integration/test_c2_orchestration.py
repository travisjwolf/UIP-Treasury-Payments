import inspect
from dataclasses import replace
from pathlib import Path
import subprocess
import sys

import pytest

from src.apps.action_center import ActionCenterService
from src.apps.control_tower import project_case
from src.contracts import AgentOutput, PaymentFixture, PolicyConfig, ProposedAction
from src.effectors import EffectorAuthorizationError, SandboxEffector
from src.maestro import (
    AsyncFixtureRepairAgent,
    DeterministicGateEvaluator,
    InMemoryLedger,
    PaymentProcess,
    StaticPolicyConfigProvider,
)


ROOT = Path(__file__).resolve().parents[2]
HERO_CASES = ("WIRE-8802", "WIRE-8841", "WIRE-8877")


def _fixture(case_id: str) -> dict:
    return PaymentFixture.model_validate_json(
        (ROOT / "fixtures" / "cases" / f"{case_id}.json").read_text(
            encoding="utf-8"
        )
    ).model_dump(mode="json")


def _process() -> tuple[PaymentProcess, SandboxEffector, InMemoryLedger]:
    effector = SandboxEffector(
        credential_identity="sandbox://wire-repair-effector",
        recorded_at="2026-08-07T09:15:00Z",
    )
    ledger = InMemoryLedger()
    policy_configs = {
        customer_id: PolicyConfig(
            customer_id=customer_id,
            same_day_beneficiary_velocity_threshold_usd=5_000_000.0,
        )
        for customer_id in ("CUST-1042", "CUST-1355")
    }
    process = PaymentProcess(
        AsyncFixtureRepairAgent(),
        DeterministicGateEvaluator(),
        effector,
        ledger,
        policy_config_provider=StaticPolicyConfigProvider(policy_configs),
    )
    return process, effector, ledger


@pytest.mark.anyio
async def test_real_async_agent_and_deterministic_gate_route_all_hero_cases():
    process, effector, ledger = _process()

    results = {
        case_id: await process.run_async(_fixture(case_id))
        for case_id in HERO_CASES
    }

    assert inspect.iscoroutinefunction(process.run_async)
    assert {case_id: result.path for case_id, result in results.items()} == {
        "WIRE-8802": "auto_apply",
        "WIRE-8841": "human_approval",
        "WIRE-8877": "callback_then_human",
    }
    assert {
        case_id: result.agent_output.outcome.value
        for case_id, result in results.items()
    } == {
        "WIRE-8802": "RESOLVED",
        "WIRE-8841": "BLOCKED_POLICY",
        "WIRE-8877": "NEEDS_INFO",
    }
    assert results["WIRE-8841"].decision.gate.value == "G1"
    assert results["WIRE-8841"].decision.result.value == "HUMAN_APPROVAL"
    assert results["WIRE-8877"].decision.gate.value == "G9"
    assert [request.case_id for request in effector.requests] == ["WIRE-8802"]
    assert effector.writes_performed is False
    assert {entry.case_id for entry in ledger.entries} == set(HERO_CASES)


@pytest.mark.anyio
async def test_wire_8841_g1_refuses_autonomy_with_exact_evidence_backed_proposal():
    process, effector, ledger = _process()

    result = await process.run_async(_fixture("WIRE-8841"))

    proposal = result.agent_output.proposed_action
    assert proposal is not None
    assert proposal.current_value == "882300441"
    assert proposal.proposed_value == "8823004417"
    assert result.agent_output.confidence == 0.91
    assert result.escalation is not None
    assert result.escalation.to_dict() == {
        "payment": result.payment.model_dump(mode="json"),
        "proposal": proposal.model_dump(mode="json"),
        "gate": "G1",
        "reason": "G1 proposed repair changes the beneficiary account.",
        "evidence": [
            evidence.model_dump(mode="json")
            for evidence in result.agent_output.evidence
        ],
        "cutoff_time": "17:00",
        "permitted_actions": ["approve", "edit", "reject", "escalate"],
    }
    assert any(
        proposal.proposed_value in str(evidence.content)
        for evidence in result.escalation.evidence
    )
    assert effector.requests == []
    assert [entry.state for entry in ledger.for_case("WIRE-8841")] == [
        "INTAKE_RECEIVED",
        "AGENT_INVESTIGATION_STARTED",
        "AGENT_PROPOSED",
        "GATE_EVALUATED",
        "AUTONOMY_REFUSED",
        "HUMAN_ESCALATION_CREATED",
    ]


@pytest.mark.anyio
async def test_auto_apply_records_before_after_credential_and_complete_ledger():
    process, effector, ledger = _process()

    result = await process.run_async(_fixture("WIRE-8802"))

    assert result.effector_result is not None
    audit = result.effector_result.audit
    assert audit.before == "PACIFIC STEEL & SUPPY"
    assert audit.after == "PACIFIC STEEL & SUPPLY"
    assert audit.field == "beneficiary_name"
    assert audit.credential_identity == "sandbox://wire-repair-effector"
    assert audit.authorization_mode == "auto_apply"
    assert audit.authorized_by == "deterministic-policy-gate"
    assert audit.payment_write_performed is False
    assert effector.writes_performed is False
    assert [entry.state for entry in ledger.for_case("WIRE-8802")] == [
        "INTAKE_RECEIVED",
        "AGENT_INVESTIGATION_STARTED",
        "AGENT_PROPOSED",
        "GATE_EVALUATED",
        "AUTO_APPLY_AUTHORIZED",
        "EFFECT_RECORDED",
        "CASE_STATE_UPDATED",
    ]


@pytest.mark.anyio
async def test_callback_hero_preserves_transcript_trace_and_human_decision():
    process, effector, ledger = _process()

    result = await process.run_async(_fixture("WIRE-8877"))

    assert result.agent_output.outcome.value == "NEEDS_INFO"
    assert [item.type.value for item in result.agent_output.evidence] == [
        "call_transcript"
    ]
    assert result.escalation is not None
    assert result.escalation.permitted_actions == (
        "provide_info",
        "approve",
        "reject",
        "escalate",
    )
    assert effector.requests == []
    assert [entry.state for entry in ledger.for_case("WIRE-8877")] == [
        "INTAKE_RECEIVED",
        "AGENT_INVESTIGATION_STARTED",
        "AGENT_PROPOSED",
        "GATE_EVALUATED",
        "AUTONOMY_REFUSED",
        "CALLBACK_REQUIRED",
        "HUMAN_ESCALATION_CREATED",
    ]


@pytest.mark.anyio
async def test_one_click_human_approval_is_audited_before_sandbox_effect():
    process, effector, ledger = _process()
    blocked = await process.run_async(_fixture("WIRE-8841"))
    assert blocked.escalation is not None

    approval = ActionCenterService(effector, ledger).handle(
        blocked.escalation,
        "approve",
        reviewer_identity="ops://demo-reviewer",
    )

    assert approval.status == "EFFECT_RECORDED"
    assert approval.effector_result is not None
    audit = approval.effector_result.audit
    assert audit.before == "882300441"
    assert audit.after == "8823004417"
    assert audit.authorization_mode == "human_approval"
    assert audit.authorized_by == "ops://demo-reviewer"
    assert audit.credential_identity == "sandbox://wire-repair-effector"
    assert audit.payment_write_performed is False
    assert [entry.state for entry in ledger.for_case("WIRE-8841")][-3:] == [
        "HUMAN_APPROVED",
        "EFFECT_RECORDED",
        "CASE_STATE_UPDATED",
    ]


@pytest.mark.anyio
async def test_sandbox_effector_rejects_unapproved_or_untraceable_effects():
    process, effector, _ = _process()
    blocked = await process.run_async(_fixture("WIRE-8841"))
    assert blocked.escalation is not None
    assert blocked.escalation.proposal is not None

    with pytest.raises(EffectorAuthorizationError, match="human approval"):
        effector.apply(
            blocked.payment,
            blocked.escalation.proposal,
            evidence=blocked.escalation.evidence,
        )

    untraceable = blocked.escalation.proposal.model_copy(
        update={"proposed_value": "9999999999"}
    )
    with pytest.raises(EffectorAuthorizationError, match="traceable"):
        ActionCenterService(effector, InMemoryLedger()).handle(
            blocked.escalation,
            "edit",
            edited_proposal=untraceable,
            reviewer_identity="ops://demo-reviewer",
        )
    assert effector.requests == []


@pytest.mark.anyio
async def test_human_edit_cannot_switch_the_deterministically_evaluated_field():
    process, effector, ledger = _process()
    blocked = await process.run_async(_fixture("WIRE-8841"))
    assert blocked.escalation is not None
    states_before = [entry.state for entry in ledger.for_case("WIRE-8841")]
    cross_field_edit = ProposedAction(
        field="amount_usd",
        current_value=2_450_000.0,
        proposed_value=31,
    )

    with pytest.raises(ValueError, match="same field"):
        ActionCenterService(effector, ledger).handle(
            blocked.escalation,
            "edit",
            edited_proposal=cross_field_edit,
            reviewer_identity="ops://demo-reviewer",
        )

    assert effector.requests == []
    assert [entry.state for entry in ledger.for_case("WIRE-8841")] == states_before


@pytest.mark.anyio
async def test_cross_case_evidence_cannot_authorize_an_effect():
    process, effector, ledger = _process()
    blocked = await process.run_async(_fixture("WIRE-8841"))
    assert blocked.escalation is not None
    foreign_payload = replace(
        blocked.escalation,
        evidence=tuple(
            item.model_copy(update={"case_id": "WIRE-FOREIGN"})
            for item in blocked.escalation.evidence
        ),
    )

    with pytest.raises(EffectorAuthorizationError, match="evidence case_id"):
        ActionCenterService(effector, ledger).handle(
            foreign_payload,
            "approve",
            reviewer_identity="ops://demo-reviewer",
        )

    assert effector.requests == []


@pytest.mark.anyio
async def test_async_orchestration_keeps_sync_test_doubles_injectable():
    fixture = _fixture("WIRE-8802")
    expected = AgentOutput.model_validate(
        await AsyncFixtureRepairAgent().analyze(
            PaymentFixture.model_validate(fixture).payment_case,
            fixture,
        )
    )

    class SyncAgent:
        def analyze(self, _case, _fixture):
            return expected

    process, effector, ledger = _process()
    process.agent = SyncAgent()

    result = await process.run_async(fixture)

    assert result.path == "auto_apply"
    assert len(effector.requests) == 1
    assert ledger.for_case("WIRE-8802")[-1].state == "CASE_STATE_UPDATED"


@pytest.mark.anyio
async def test_runtime_input_does_not_require_test_only_expected_fields():
    process, effector, _ = _process()
    runtime_input = _fixture("WIRE-8802")
    runtime_input.pop("expected_outcome")
    runtime_input.pop("expected_path")

    result = await process.run_async(runtime_input)

    assert result.path == "auto_apply"
    assert [request.case_id for request in effector.requests] == ["WIRE-8802"]


@pytest.mark.anyio
async def test_g0_routes_to_compliance_without_an_overridable_action_task():
    process, effector, ledger = _process()

    result = await process.run_async(_fixture("WIRE-8917"))

    assert result.path == "compliance_referral"
    assert result.decision.gate.value == "G0"
    assert result.decision.result.value == "COMPLIANCE_REFERRAL"
    assert result.escalation is None
    assert result.effector_result is None
    assert project_case(result).status == "COMPLIANCE_REFERRAL_REQUIRED"
    assert effector.requests == []
    assert [entry.state for entry in ledger.for_case("WIRE-8917")][-2:] == [
        "AUTONOMY_REFUSED",
        "COMPLIANCE_REFERRAL_CREATED",
    ]


@pytest.mark.anyio
async def test_g2_routes_to_non_overridable_policy_hard_stop():
    fixture = _fixture("WIRE-8802")

    class AmountChangingAgent:
        def analyze(self, _case, _fixture):
            return AgentOutput(
                outcome="BLOCKED_POLICY",
                proposed_action={
                    "field": "amount_usd",
                    "current_value": 84_500.0,
                    "proposed_value": 84_501.0,
                },
                confidence=1.0,
                evidence=[],
                reasoning_summary="Synthetic forbidden amount change.",
                tools_called=[],
            )

    process, effector, ledger = _process()
    process.agent = AmountChangingAgent()

    result = await process.run_async(fixture)

    assert result.path == "policy_hard_stop"
    assert result.decision.gate.value == "G2"
    assert result.decision.result.value == "HARD_STOP"
    assert result.escalation is None
    assert result.effector_result is None
    assert effector.requests == []
    assert [entry.state for entry in ledger.for_case("WIRE-8802")][-2:] == [
        "AUTONOMY_REFUSED",
        "POLICY_HARD_STOP_RECORDED",
    ]


@pytest.mark.parametrize(
    "statement",
    [
        (
            "from src.apps.action_center import EscalationPayload; "
            "from src.maestro import PaymentProcess"
        ),
        (
            "from src.maestro import PaymentProcess; "
            "from src.apps.action_center import EscalationPayload"
        ),
    ],
)
def test_apps_and_maestro_packages_import_cleanly_in_either_order(statement: str):
    completed = subprocess.run(
        [sys.executable, "-c", statement],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_agent_adapter_loads_and_invokes_deployable_graph_from_clean_repo_root():
    statement = r'''
import asyncio
import json
from pathlib import Path
import sys

from src.maestro.adapters import AsyncFixtureRepairAgent

assert "src.agent.main" not in sys.modules
fixture = json.loads(
    Path("fixtures/cases/WIRE-8802.json").read_text(encoding="utf-8")
)

async def exercise():
    adapter = AsyncFixtureRepairAgent()
    assert "src.agent.main" in sys.modules
    assert hasattr(adapter.graph, "ainvoke")
    result = await adapter.analyze(
        __import__("src.contracts", fromlist=["PaymentCase"])
        .PaymentCase.model_validate(fixture["payment_case"]),
        fixture,
    )
    assert result.outcome.value == "RESOLVED"

asyncio.run(exercise())
'''
    completed = subprocess.run(
        [sys.executable, "-c", statement],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
