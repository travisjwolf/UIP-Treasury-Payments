import pytest

from src.apps.action_center import ActionCenterService, EscalationPayload
from src.apps.control_tower import project_case, project_queue
from src.effectors.stub import StubEffector
from src.maestro.ledger import InMemoryLedger
from src.contracts.models import ProposedAction

from tests.integration.test_process_harness import _process
from src.contracts.fixture_io import load_case_files
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _result(case_id: str):
    process, _, _ = _process()
    fixture = next(item for item in load_case_files(ROOT / "fixtures" / "cases") if item["case_id"] == case_id)
    return process.run(fixture)


def test_control_tower_projection_exposes_queue_and_case_detail_fields():
    auto = _result("WIRE-8802")
    blocked = _result("WIRE-8841")

    queue = project_queue([auto, blocked])
    detail = project_case(blocked)

    assert queue[0].case_id == "WIRE-8802"
    assert queue[0].status == "AUTO_APPLY_PENDING"
    assert queue[1].status == "HUMAN_APPROVAL_REQUIRED"
    assert detail.cutoff_time == "17:00"
    assert detail.confidence == 0.91
    assert detail.gate == "G1"
    assert detail.evidence_count == 1
    assert detail.proposed_value == "4628492309"


def test_escalation_payload_serializes_the_full_human_review_packet():
    payload = _result("WIRE-8841").escalation

    assert isinstance(payload, EscalationPayload)
    serialized = payload.to_dict()

    assert serialized["payment"]["case_id"] == "WIRE-8841"
    assert serialized["gate"] == "G1"
    assert serialized["proposal"]["proposed_value"] == "4628492309"
    assert serialized["evidence"][0]["source"] == "test-fixture"
    assert serialized["permitted_actions"] == ["approve", "edit", "reject", "escalate"]


def test_approve_routes_only_the_human_approved_value_to_the_effector():
    payload = _result("WIRE-8841").escalation
    effector = StubEffector()
    ledger = InMemoryLedger()

    result = ActionCenterService(effector, ledger).handle(payload, "approve")

    assert result.status == "EFFECT_REQUESTED"
    assert effector.requests[0].action.proposed_value == "4628492309"
    assert ledger.entries[-1].state == "EFFECT_REQUESTED"


def test_reject_never_calls_the_effector():
    payload = _result("WIRE-8841").escalation
    effector = StubEffector()
    ledger = InMemoryLedger()

    result = ActionCenterService(effector, ledger).handle(payload, "reject")

    assert result.status == "REJECTED"
    assert effector.requests == []
    assert ledger.entries[-1].state == "HUMAN_REJECTED"


def test_callback_case_is_visible_as_callback_required_with_info_action():
    result = _result("WIRE-8877")

    detail = project_case(result)

    assert detail.status == "CALLBACK_REQUIRED"
    assert result.escalation.permitted_actions == ("provide_info", "approve", "reject", "escalate")


def test_edit_requires_a_replacement_proposal_and_routes_that_value():
    payload = _result("WIRE-8841").escalation
    effector = StubEffector()
    ledger = InMemoryLedger()
    edited = ProposedAction("beneficiary_account", "882300441", "4628492309")

    result = ActionCenterService(effector, ledger).handle(payload, "edit", edited)

    assert result.status == "EFFECT_REQUESTED"
    assert effector.requests[0].action == edited


def test_action_center_rejects_actions_not_allowed_by_the_payload():
    payload = _result("WIRE-8841").escalation

    with pytest.raises(ValueError, match="not permitted"):
        ActionCenterService(StubEffector(), InMemoryLedger()).handle(payload, "provide_info")
