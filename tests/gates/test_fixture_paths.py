import csv
from pathlib import Path

import pytest

from src.contracts import (
    AgentOutput,
    GateId,
    Outcome,
    PaymentFixture,
    PolicyConfig,
    PolicyResult,
    ProposedAction,
    ProposedField,
)
from src.gates import evaluate_policy


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PAYMENTS_CSV = REPOSITORY_ROOT / "fixtures" / "payments.csv"
CASE_DIRECTORY = REPOSITORY_ROOT / "fixtures" / "cases"

RESULT_PATHS = {
    "AUTO_APPLY": "auto_apply",
    "COMPLIANCE_REFERRAL": "compliance_referral",
    "CALLBACK_THEN_HUMAN": "callback_then_human",
    "HUMAN_APPROVAL": "human_approval",
    "HARD_STOP": "human_approval",
    "PRIORITY_ESCALATION": "human_approval",
    "ESCALATE": "human_approval",
}

PROPOSAL_FIELDS = {
    "EX-01": ProposedField.BENEFICIARY_ACCOUNT,
    "EX-02": ProposedField.BENEFICIARY_NAME,
    "EX-03": ProposedField.BENEFICIARY_BANK_ABA,
    "EX-04": ProposedField.CUSTOMER_NAME,
    "EX-05": ProposedField.REMITTANCE_INFO,
    "EX-06": ProposedField.REMITTANCE_INFO,
    "EX-07": ProposedField.REMITTANCE_INFO,
}


def load_csv_rows() -> list[dict[str, str]]:
    with PAYMENTS_CSV.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


CSV_ROWS = load_csv_rows()


def load_fixture(case_id: str) -> PaymentFixture:
    return PaymentFixture.model_validate_json(
        (CASE_DIRECTORY / f"{case_id}.json").read_text(encoding="utf-8")
    )


def build_agent_output(fixture: PaymentFixture) -> AgentOutput:
    payment_case = fixture.payment_case
    outcome = fixture.expected_outcome
    if outcome == Outcome.AMBIGUOUS:
        return AgentOutput(
            outcome=outcome,
            proposed_action=None,
            confidence=0.50,
            evidence=[],
            reasoning_summary="Fixture outcome is ambiguous.",
            tools_called=[],
        )
    if outcome == Outcome.NEEDS_INFO:
        return AgentOutput(
            outcome=outcome,
            proposed_action=None,
            confidence=0.0,
            evidence=[],
            reasoning_summary="Fixture outcome needs additional information.",
            tools_called=[],
        )

    field = PROPOSAL_FIELDS[payment_case.exception_code]
    current_value = getattr(payment_case, field.value)
    return AgentOutput(
        outcome=outcome,
        proposed_action=ProposedAction(
            field=field,
            current_value=current_value,
            proposed_value=f"{current_value} (proposed)",
        ),
        confidence=0.80 if outcome == Outcome.RESOLVED_LOW_CONFIDENCE else 0.91,
        evidence=[],
        reasoning_summary="Fixture proposal for routing verification.",
        tools_called=[],
    )


def fixture_policy_config(fixture: PaymentFixture) -> PolicyConfig:
    return PolicyConfig(
        customer_id=fixture.payment_case.customer_id,
        same_day_beneficiary_velocity_threshold_usd=5_000_000.0,
    )


@pytest.mark.parametrize("csv_row", CSV_ROWS, ids=lambda row: row["case_id"])
def test_every_canonical_fixture_routes_to_its_csv_path(csv_row: dict[str, str]) -> None:
    fixture = load_fixture(csv_row["case_id"])

    assert fixture.expected_outcome.value == csv_row["expected_outcome"]
    assert fixture.expected_path.value == csv_row["expected_path"]

    decision = evaluate_policy(
        fixture.payment_case,
        build_agent_output(fixture),
        fixture.gate_context,
        fixture_policy_config(fixture),
    )

    assert RESULT_PATHS[decision.result.value] == csv_row["expected_path"]


def test_wire_8841_account_repair_is_blocked_by_g1_before_g3() -> None:
    fixture = load_fixture("WIRE-8841")
    agent_output = build_agent_output(fixture)
    decision = evaluate_policy(
        fixture.payment_case,
        agent_output,
        fixture.gate_context,
        fixture_policy_config(fixture),
    )

    assert agent_output.proposed_action is not None
    assert agent_output.proposed_action.field == ProposedField.BENEFICIARY_ACCOUNT
    assert agent_output.confidence == 0.91
    assert fixture.payment_case.amount_usd > 250_000.0
    assert decision.gate == GateId.G1
    assert decision.result == PolicyResult.HUMAN_APPROVAL
