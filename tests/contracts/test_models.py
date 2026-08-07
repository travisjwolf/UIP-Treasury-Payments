from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.contracts import (
    AgentOutput,
    CounterpartyHistory,
    Evidence,
    GateContext,
    PaymentCase,
    PaymentFixture,
    PolicyConfig,
    PolicyDecision,
    Outcome,
    PolicyPath,
    PolicyResult,
    ProposedAction,
    ProposedField,
)


PAYMENT_FIELDS = {
    "case_id",
    "rail",
    "direction",
    "amount_usd",
    "currency",
    "value_date",
    "cutoff_time",
    "sla_deadline",
    "source_channel",
    "customer_id",
    "customer_name",
    "beneficiary_name",
    "beneficiary_account",
    "beneficiary_bank_aba",
    "remittance_info",
    "exception_code",
    "exception_type",
    "current_queue",
    "status",
    "worked_by",
    "confidence",
    "proposed_action",
    "outcome",
    "touch_count",
    "cycle_time",
}


def payment_data() -> dict[str, object]:
    return {
        "case_id": "WIRE-8802",
        "rail": "Fedwire",
        "direction": "outbound",
        "amount_usd": 84_500.0,
        "currency": "USD",
        "value_date": "2026-08-07",
        "cutoff_time": "17:00",
        "sla_deadline": None,
        "source_channel": "file_upload",
        "customer_id": "CUST-1042",
        "customer_name": "Ridgeline Construction LLC",
        "beneficiary_name": "PACIFIC STEEL & SUPPY",
        "beneficiary_account": "8823004417",
        "beneficiary_bank_aba": "121000248",
        "remittance_info": "INV 44821 STEEL DELIVERY",
        "exception_code": "EX-02",
        "exception_type": "name_account_mismatch",
        "current_queue": "repair",
        "status": "pending",
        "worked_by": None,
        "confidence": None,
        "proposed_action": None,
        "outcome": None,
        "touch_count": 0,
        "cycle_time": None,
    }


def proposed_action() -> ProposedAction:
    return ProposedAction(
        field="beneficiary_name",
        current_value="PACIFIC STEEL & SUPPY",
        proposed_value="PACIFIC STEEL & SUPPLY",
    )


def evidence() -> Evidence:
    return Evidence(
        case_id="WIRE-8802",
        type="history_match",
        source="counterparty_history.csv",
        content={"matched_name": "PACIFIC STEEL & SUPPLY"},
        produced_by="counterparty_history_lookup",
        timestamp=datetime(2026, 8, 7, 12, 19, tzinfo=timezone.utc),
    )


def test_payment_case_fields_match_the_published_entity_contract() -> None:
    assert set(getattr(PaymentCase, "model_fields", {})) == PAYMENT_FIELDS


def test_payment_case_rejects_fields_outside_the_published_contract() -> None:
    data = payment_data()
    data["sanctions_status"] = "clear"

    with pytest.raises(ValidationError):
        PaymentCase.model_validate(data)


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_agent_output_rejects_confidence_outside_zero_to_one(
    confidence: float,
) -> None:
    with pytest.raises(ValidationError):
        AgentOutput(
            outcome="RESOLVED",
            proposed_action=proposed_action(),
            confidence=confidence,
            evidence=[evidence()],
            reasoning_summary="History confirms the registered name.",
            tools_called=["counterparty_history_lookup"],
        )


def test_agent_output_rejects_unknown_outcome() -> None:
    with pytest.raises(ValidationError):
        AgentOutput(
            outcome="MAYBE_RESOLVED",
            proposed_action=proposed_action(),
            confidence=0.91,
            evidence=[evidence()],
            reasoning_summary="Unknown outcomes must not cross the boundary.",
            tools_called=["counterparty_history_lookup"],
        )


def test_proposed_action_rejects_a_blank_field_name() -> None:
    with pytest.raises(ValidationError):
        ProposedAction(field=" ", current_value="old", proposed_value="new")


def test_proposed_action_requires_the_proposed_value_key() -> None:
    with pytest.raises(ValidationError):
        ProposedAction(field="beneficiary_name", current_value="old")


@pytest.mark.parametrize(
    "field",
    ["beneficiary_accout", "not_a_payment_field"],
)
def test_proposed_action_rejects_unknown_or_misspelled_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        ProposedAction(field=field, current_value="old", proposed_value="new")


@pytest.mark.parametrize(
    ("current_value", "proposed_value"),
    [
        (None, "new"),
        ("old", None),
        ({"old": "value"}, "new"),
        ("old", ["new"]),
    ],
)
def test_proposed_action_rejects_null_or_compound_values(
    current_value: object,
    proposed_value: object,
) -> None:
    with pytest.raises(ValidationError):
        ProposedAction(
            field="beneficiary_name",
            current_value=current_value,
            proposed_value=proposed_value,
        )


def test_proposed_action_rejects_an_unchanged_value() -> None:
    with pytest.raises(ValidationError):
        ProposedAction(
            field="beneficiary_name",
            current_value="PACIFIC STEEL & SUPPLY",
            proposed_value="PACIFIC STEEL & SUPPLY",
        )


def test_proposed_field_enum_uses_canonical_payment_case_names() -> None:
    assert {item.value for item in ProposedField} == {
        "amount_usd",
        "beneficiary_account",
        "beneficiary_bank_aba",
        "beneficiary_name",
        "currency",
        "customer_name",
        "remittance_info",
    }


def test_outcome_enum_is_the_exact_closed_contract() -> None:
    assert {item.value for item in Outcome} == {
        "RESOLVED",
        "RESOLVED_LOW_CONFIDENCE",
        "AMBIGUOUS",
        "NEEDS_INFO",
        "EXHAUSTED",
        "BLOCKED_POLICY",
    }


def test_policy_path_is_the_exact_fixture_routing_contract() -> None:
    assert {item.value for item in PolicyPath} == {
        "auto_apply",
        "human_approval",
        "compliance_referral",
        "callback_then_human",
    }


def test_policy_results_represent_every_gate_disposition() -> None:
    assert {item.value for item in PolicyResult} == {
        "AUTO_APPLY",
        "HUMAN_APPROVAL",
        "COMPLIANCE_REFERRAL",
        "CALLBACK_THEN_HUMAN",
        "HARD_STOP",
        "PRIORITY_ESCALATION",
        "ESCALATE",
    }
    for result in ("HARD_STOP", "PRIORITY_ESCALATION"):
        decision = PolicyDecision(
            case_id="WIRE-8802",
            gate="G2" if result == "HARD_STOP" else "G10",
            result=result,
            reason="Deterministic gate result.",
            evaluated_at=datetime(2026, 8, 7, 12, 19, tzinfo=timezone.utc),
        )
        assert decision.result.value == result


def test_unresolved_agent_output_can_omit_a_proposed_action() -> None:
    output = AgentOutput(
        outcome="NEEDS_INFO",
        proposed_action=None,
        confidence=0.74,
        evidence=[
            Evidence(
                case_id="WIRE-8877",
                type="call_transcript",
                source="test-fixture",
                content="Callback required.",
                produced_by="test-agent",
                timestamp="2026-08-07T09:00:00Z",
            )
        ],
        reasoning_summary="Customer confirmation is required.",
        tools_called=("callback_transcript",),
    )

    assert output.proposed_action is None
    assert output.evidence[0].content == "Callback required."


def test_policy_decision_accepts_legacy_positional_construction() -> None:
    decision = PolicyDecision(
        "WIRE-8802",
        "NONE",
        "AUTO_APPLY",
        "All gates clear.",
        "2026-08-07T09:00:01Z",
    )

    assert decision.gate == "NONE"
    assert decision.result == "AUTO_APPLY"


def test_gate_context_requires_an_aware_evaluation_time() -> None:
    with pytest.raises(ValidationError):
        GateContext(
            sanctions_status="clear",
            first_time_counterparty=False,
            same_day_beneficiary_total_usd=84_500.0,
            cross_border=False,
            evaluated_at=datetime(2026, 8, 7, 8, 18),
            cutoff_at=datetime(2026, 8, 7, 17, 0, tzinfo=timezone.utc),
        )


def test_payment_case_requires_an_aware_sla_deadline_when_present() -> None:
    data = payment_data()
    data["sla_deadline"] = datetime(2026, 8, 7, 17, 0)

    with pytest.raises(ValidationError):
        PaymentCase.model_validate(data)


def test_policy_config_defaults_match_the_documented_gate_thresholds() -> None:
    config = PolicyConfig(
        customer_id="CUST-1042",
        same_day_beneficiary_velocity_threshold_usd=5_000_000.0,
    )

    assert config.auto_apply_amount_threshold_usd == 250_000.0
    assert config.minimum_confidence == 0.85
    assert config.cutoff_escalation_minutes == 30
    assert config.same_day_beneficiary_velocity_threshold_usd == 5_000_000.0


def test_policy_config_requires_customer_velocity_threshold() -> None:
    with pytest.raises(ValidationError):
        PolicyConfig(customer_id="CUST-1042")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("auto_apply_amount_threshold_usd", 0),
        ("minimum_confidence", 1.01),
        ("same_day_beneficiary_velocity_threshold_usd", -1),
        ("cutoff_escalation_minutes", 0),
    ],
)
def test_policy_config_rejects_invalid_thresholds(field: str, value: float) -> None:
    values: dict[str, object] = {"customer_id": "CUST-1042", field: value}

    with pytest.raises(ValidationError):
        PolicyConfig.model_validate(values)


def test_supporting_contracts_validate_a_complete_fixture_envelope() -> None:
    payment = PaymentCase.model_validate(payment_data())
    context = GateContext(
        sanctions_status="clear",
        first_time_counterparty=False,
        same_day_beneficiary_total_usd=84_500.0,
        cross_border=False,
        evaluated_at=datetime(2026, 8, 7, 8, 18, tzinfo=timezone.utc),
        cutoff_at=datetime(2026, 8, 7, 17, 0, tzinfo=timezone.utc),
    )
    fixture = PaymentFixture(
        payment_case=payment,
        gate_context=context,
        expected_outcome="RESOLVED",
        expected_path="auto_apply",
        demo_role="hero_auto_resolve",
    )
    history = CounterpartyHistory(
        customer_id="CUST-1042",
        beneficiary_name="PACIFIC STEEL & SUPPLY",
        beneficiary_account="8823004417",
        times_seen=9,
        times_repaired=3,
        last_applied_fix="normalize_name_to_registered_entity",
        history_confidence=0.96,
    )
    decision = PolicyDecision(
        case_id="WIRE-8802",
        gate=None,
        result="AUTO_APPLY",
        reason="No policy gate fired.",
        evaluated_at=datetime(2026, 8, 7, 8, 19, tzinfo=timezone.utc),
    )

    assert fixture.payment_case.case_id == "WIRE-8802"
    assert fixture.gate_context.sanctions_status.value == "clear"
    assert history.history_confidence == 0.96
    assert decision.result.value == "AUTO_APPLY"
