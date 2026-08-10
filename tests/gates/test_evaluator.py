from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.contracts import (
    AgentOutput,
    GateContext,
    Outcome,
    PaymentCase,
    PolicyConfig,
    ProposedAction,
    ProposedField,
    SanctionsStatus,
)
from src.gates import evaluate_policy


EASTERN = ZoneInfo("America/New_York")
EVALUATED_AT = datetime(2026, 8, 10, 12, 0, tzinfo=EASTERN)


def make_payment_case(**overrides: object) -> PaymentCase:
    values: dict[str, object] = {
        "case_id": "WIRE-TEST",
        "rail": "wire",
        "direction": "outbound",
        "amount_usd": 100_000.0,
        "currency": "USD",
        "value_date": EVALUATED_AT.date(),
        "cutoff_time": "17:00",
        "sla_deadline": None,
        "source_channel": "online",
        "customer_id": "CUST-001",
        "customer_name": "Example Customer",
        "beneficiary_name": "Example Beneficiary",
        "beneficiary_account": "000123456789",
        "beneficiary_bank_aba": "021000021",
        "remittance_info": "Invoice 123",
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
    values.update(overrides)
    return PaymentCase(**values)


def make_agent_output(
    *,
    outcome: Outcome = Outcome.RESOLVED,
    field: ProposedField | None = ProposedField.BENEFICIARY_NAME,
    confidence: float = 0.91,
) -> AgentOutput:
    proposed_action = (
        None
        if field is None
        else ProposedAction(
            field=field,
            current_value="Example Beneficiary",
            proposed_value="Example Beneficiary LLC",
        )
    )
    return AgentOutput(
        outcome=outcome,
        proposed_action=proposed_action,
        confidence=confidence,
        evidence=[],
        reasoning_summary="Fixture proposal",
        tools_called=[],
    )


def make_gate_context(**overrides: object) -> GateContext:
    values: dict[str, object] = {
        "sanctions_status": SanctionsStatus.CLEAR,
        "first_time_counterparty": False,
        "same_day_beneficiary_total_usd": 100_000.0,
        "cross_border": False,
        "evaluated_at": EVALUATED_AT,
        "cutoff_at": EVALUATED_AT.replace(hour=17),
    }
    values.update(overrides)
    return GateContext(**values)


def make_policy_config(**overrides: object) -> PolicyConfig:
    values: dict[str, object] = {
        "customer_id": "CUST-001",
        "auto_apply_amount_threshold_usd": 250_000.0,
        "minimum_confidence": 0.85,
        "same_day_beneficiary_velocity_threshold_usd": 1_000_000.0,
        "cutoff_escalation_minutes": 30,
    }
    values.update(overrides)
    return PolicyConfig(**values)


@pytest.mark.parametrize(
    ("expected_gate", "expected_result", "payment_overrides", "output_args", "context_overrides"),
    [
        ("G0", "COMPLIANCE_REFERRAL", {}, {}, {"sanctions_status": SanctionsStatus.REVIEW}),
        ("G1", "HUMAN_APPROVAL", {}, {"field": ProposedField.BENEFICIARY_ACCOUNT}, {}),
        ("G2", "HARD_STOP", {}, {"field": ProposedField.AMOUNT_USD}, {}),
        ("G3", "HUMAN_APPROVAL", {"amount_usd": 250_000.01}, {}, {}),
        ("G4", "HUMAN_APPROVAL", {}, {}, {"first_time_counterparty": True}),
        ("G5", "HUMAN_APPROVAL", {}, {"confidence": 0.849999}, {}),
        ("G6", "HUMAN_APPROVAL", {}, {}, {"cross_border": True}),
        ("G7", "HUMAN_APPROVAL", {"exception_code": "EX-07"}, {}, {}),
        (
            "G8",
            "HUMAN_APPROVAL",
            {},
            {},
            {"same_day_beneficiary_total_usd": 1_000_000.01},
        ),
        ("G9", "ESCALATE", {}, {"outcome": Outcome.AMBIGUOUS, "field": None}, {}),
        (
            "G10",
            "PRIORITY_ESCALATION",
            {},
            {},
            {"cutoff_at": EVALUATED_AT + timedelta(minutes=29, seconds=59)},
        ),
    ],
)
def test_each_gate_returns_its_documented_result(
    expected_gate: str,
    expected_result: str,
    payment_overrides: dict[str, object],
    output_args: dict[str, object],
    context_overrides: dict[str, object],
) -> None:
    decision = evaluate_policy(
        make_payment_case(**payment_overrides),
        make_agent_output(**output_args),
        make_gate_context(**context_overrides),
        make_policy_config(),
    )

    assert decision.gate == expected_gate
    assert decision.result == expected_result


@pytest.mark.parametrize("field", [ProposedField.AMOUNT_USD, ProposedField.CURRENCY])
def test_g2_hard_stops_money_movement_field_changes(field: ProposedField) -> None:
    decision = evaluate_policy(
        make_payment_case(), make_agent_output(field=field), make_gate_context(), make_policy_config()
    )

    assert decision.gate == "G2"
    assert decision.result == "HARD_STOP"


@pytest.mark.parametrize(
    ("payment_overrides", "context_overrides"),
    [({}, {"cross_border": True}), ({"currency": "EUR"}, {})],
)
def test_g6_requires_human_approval_for_cross_border_or_non_usd(
    payment_overrides: dict[str, object], context_overrides: dict[str, object]
) -> None:
    decision = evaluate_policy(
        make_payment_case(**payment_overrides),
        make_agent_output(),
        make_gate_context(**context_overrides),
        make_policy_config(),
    )

    assert decision.gate == "G6"
    assert decision.result == "HUMAN_APPROVAL"


@pytest.mark.parametrize(
    ("outcome", "expected_result"),
    [
        (Outcome.EXHAUSTED, "ESCALATE"),
        (Outcome.AMBIGUOUS, "ESCALATE"),
        (Outcome.NEEDS_INFO, "CALLBACK_THEN_HUMAN"),
    ],
)
def test_g9_routes_non_resolved_outcomes(outcome: Outcome, expected_result: str) -> None:
    decision = evaluate_policy(
        make_payment_case(),
        make_agent_output(outcome=outcome, field=None),
        make_gate_context(),
        make_policy_config(),
    )

    assert decision.gate == "G9"
    assert decision.result == expected_result


@pytest.mark.parametrize("field", [ProposedField.BENEFICIARY_NAME, None])
def test_unexplained_blocked_policy_never_auto_applies(
    field: ProposedField | None,
) -> None:
    decision = evaluate_policy(
        make_payment_case(),
        make_agent_output(outcome=Outcome.BLOCKED_POLICY, field=field),
        make_gate_context(),
        make_policy_config(),
    )

    assert decision.gate is None
    assert decision.result == "ESCALATE"


def test_customer_mismatched_policy_configuration_fails_closed() -> None:
    with pytest.raises(
        ValueError,
        match="PolicyConfig.customer_id must match PaymentCase.customer_id",
    ):
        evaluate_policy(
            make_payment_case(customer_id="CUST-001"),
            make_agent_output(),
            make_gate_context(),
            make_policy_config(customer_id="CUST-OTHER"),
        )


@pytest.mark.parametrize(
    ("expected_gate", "field", "context_overrides"),
    [
        ("G0", ProposedField.BENEFICIARY_NAME, {"sanctions_status": SanctionsStatus.MATCH}),
        ("G1", ProposedField.BENEFICIARY_ACCOUNT, {}),
        ("G2", ProposedField.AMOUNT_USD, {}),
    ],
)
def test_fixed_gates_precede_customer_configuration_validation(
    expected_gate: str,
    field: ProposedField,
    context_overrides: dict[str, object],
) -> None:
    decision = evaluate_policy(
        make_payment_case(),
        make_agent_output(field=field),
        make_gate_context(**context_overrides),
        make_policy_config(customer_id="CUST-OTHER"),
    )

    assert decision.gate == expected_gate


def test_g10_precedes_unexplained_blocked_policy_fallback() -> None:
    decision = evaluate_policy(
        make_payment_case(),
        make_agent_output(outcome=Outcome.BLOCKED_POLICY, field=None),
        make_gate_context(cutoff_at=EVALUATED_AT + timedelta(minutes=1)),
        make_policy_config(),
    )

    assert decision.gate == "G10"
    assert decision.result == "PRIORITY_ESCALATION"


def test_g0_wins_before_an_account_change() -> None:
    decision = evaluate_policy(
        make_payment_case(),
        make_agent_output(field=ProposedField.BENEFICIARY_ACCOUNT),
        make_gate_context(sanctions_status=SanctionsStatus.MATCH),
        make_policy_config(),
    )

    assert decision.gate == "G0"
    assert decision.result == "COMPLIANCE_REFERRAL"


@pytest.mark.parametrize("sanctions_status", [SanctionsStatus.MATCH, SanctionsStatus.UNKNOWN])
def test_g0_refers_every_non_clear_sanctions_status(
    sanctions_status: SanctionsStatus,
) -> None:
    decision = evaluate_policy(
        make_payment_case(),
        make_agent_output(),
        make_gate_context(sanctions_status=sanctions_status),
        make_policy_config(),
    )

    assert decision.gate == "G0"
    assert decision.result == "COMPLIANCE_REFERRAL"


def test_g1_wins_before_high_value_gate_for_wire_8841_pattern() -> None:
    decision = evaluate_policy(
        make_payment_case(case_id="WIRE-8841", amount_usd=2_450_000.0),
        make_agent_output(field=ProposedField.BENEFICIARY_ACCOUNT, confidence=0.91),
        make_gate_context(),
        make_policy_config(),
    )

    assert decision.gate == "G1"
    assert decision.result == "HUMAN_APPROVAL"


def test_g3_through_g8_do_not_apply_without_a_proposal() -> None:
    decision = evaluate_policy(
        make_payment_case(amount_usd=250_000.01, currency="EUR", exception_code="EX-07"),
        make_agent_output(outcome=Outcome.AMBIGUOUS, field=None, confidence=0.0),
        make_gate_context(
            first_time_counterparty=True,
            cross_border=True,
            same_day_beneficiary_total_usd=1_000_000.01,
        ),
        make_policy_config(),
    )

    assert decision.gate == "G9"
    assert decision.result == "ESCALATE"


@pytest.mark.parametrize(
    ("amount_usd", "expected_gate"),
    [(250_000.0, None), (250_000.01, "G3")],
)
def test_g3_only_fires_above_its_threshold(amount_usd: float, expected_gate: str | None) -> None:
    decision = evaluate_policy(
        make_payment_case(amount_usd=amount_usd),
        make_agent_output(),
        make_gate_context(),
        make_policy_config(),
    )

    assert decision.gate == expected_gate


@pytest.mark.parametrize(
    ("confidence", "expected_gate"),
    [(0.85, None), (0.849999, "G5")],
)
def test_g5_only_fires_below_its_threshold(confidence: float, expected_gate: str | None) -> None:
    decision = evaluate_policy(
        make_payment_case(),
        make_agent_output(confidence=confidence),
        make_gate_context(),
        make_policy_config(),
    )

    assert decision.gate == expected_gate


@pytest.mark.parametrize(
    ("same_day_total", "expected_gate"),
    [(1_000_000.0, None), (1_000_000.01, "G8")],
)
def test_g8_only_fires_above_its_velocity_threshold(
    same_day_total: float, expected_gate: str | None
) -> None:
    decision = evaluate_policy(
        make_payment_case(),
        make_agent_output(),
        make_gate_context(same_day_beneficiary_total_usd=same_day_total),
        make_policy_config(),
    )

    assert decision.gate == expected_gate


@pytest.mark.parametrize(
    ("remaining", "expected_gate"),
    [(timedelta(minutes=30), None), (timedelta(minutes=29, seconds=59), "G10")],
)
def test_g10_only_fires_inside_its_cutoff_window(
    remaining: timedelta, expected_gate: str | None
) -> None:
    decision = evaluate_policy(
        make_payment_case(),
        make_agent_output(),
        make_gate_context(cutoff_at=EVALUATED_AT + remaining),
        make_policy_config(),
    )

    assert decision.gate == expected_gate


@pytest.mark.parametrize(
    (
        "payment_overrides",
        "output_args",
        "context_overrides",
        "config_overrides",
        "expected_gate",
    ),
    [
        (
            {"amount_usd": 100_000.0},
            {},
            {},
            {"auto_apply_amount_threshold_usd": 75_000.0},
            "G3",
        ),
        ({}, {"confidence": 0.91}, {}, {"minimum_confidence": 0.92}, "G5"),
        (
            {},
            {},
            {"same_day_beneficiary_total_usd": 100_000.0},
            {"same_day_beneficiary_velocity_threshold_usd": 75_000.0},
            "G8",
        ),
        (
            {},
            {},
            {"cutoff_at": EVALUATED_AT + timedelta(minutes=90)},
            {"cutoff_escalation_minutes": 120},
            "G10",
        ),
    ],
)
def test_configurable_gates_use_customer_specific_non_default_values(
    payment_overrides: dict[str, object],
    output_args: dict[str, object],
    context_overrides: dict[str, object],
    config_overrides: dict[str, object],
    expected_gate: str,
) -> None:
    decision = evaluate_policy(
        make_payment_case(**payment_overrides),
        make_agent_output(**output_args),
        make_gate_context(**context_overrides),
        make_policy_config(**config_overrides),
    )

    assert decision.gate == expected_gate


@pytest.mark.parametrize(
    ("expected_gate", "payment_overrides", "output_args", "context_overrides"),
    [
        (
            "G3",
            {"amount_usd": 300_000.0, "exception_code": "EX-07"},
            {"confidence": 0.1},
            {
                "first_time_counterparty": True,
                "cross_border": True,
                "same_day_beneficiary_total_usd": 1_000_000.01,
            },
        ),
        (
            "G4",
            {"exception_code": "EX-07"},
            {"confidence": 0.1},
            {
                "first_time_counterparty": True,
                "cross_border": True,
                "same_day_beneficiary_total_usd": 1_000_000.01,
            },
        ),
        (
            "G5",
            {"exception_code": "EX-07"},
            {"confidence": 0.1},
            {"cross_border": True, "same_day_beneficiary_total_usd": 1_000_000.01},
        ),
        (
            "G6",
            {"exception_code": "EX-07"},
            {},
            {"cross_border": True, "same_day_beneficiary_total_usd": 1_000_000.01},
        ),
        (
            "G7",
            {"exception_code": "EX-07"},
            {},
            {"same_day_beneficiary_total_usd": 1_000_000.01},
        ),
        (
            "G8",
            {},
            {"outcome": Outcome.AMBIGUOUS},
            {"same_day_beneficiary_total_usd": 1_000_000.01},
        ),
        (
            "G9",
            {},
            {"outcome": Outcome.AMBIGUOUS, "field": None},
            {"cutoff_at": EVALUATED_AT + timedelta(minutes=1)},
        ),
    ],
)
def test_later_gates_preserve_first_gate_wins_ordering(
    expected_gate: str,
    payment_overrides: dict[str, object],
    output_args: dict[str, object],
    context_overrides: dict[str, object],
) -> None:
    decision = evaluate_policy(
        make_payment_case(**payment_overrides),
        make_agent_output(**output_args),
        make_gate_context(**context_overrides),
        make_policy_config(),
    )

    assert decision.gate == expected_gate


def test_clear_evaluation_auto_applies_without_a_gate() -> None:
    decision = evaluate_policy(
        make_payment_case(), make_agent_output(), make_gate_context(), make_policy_config()
    )

    assert decision.gate is None
    assert decision.result == "AUTO_APPLY"
