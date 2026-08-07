import csv
import json
from pathlib import Path

import pytest

from src.contracts.models import (
    AGENT_OUTCOMES,
    AgentOutput,
    PaymentCase,
    ProposedAction,
)
from src.contracts.fixture_io import load_case_files


ROOT = Path(__file__).resolve().parents[2]


def test_payment_case_contains_the_shared_fields():
    case = PaymentCase.from_fixture(load_case_files(ROOT / "fixtures" / "cases")[0])

    assert case.case_id.startswith("WIRE-")
    assert case.rail == "Fedwire"
    assert case.amount_usd > 0
    assert case.exception_code.startswith("EX-")


def test_agent_output_rejects_unknown_outcome():
    with pytest.raises(ValueError, match="unknown outcome"):
        AgentOutput.from_dict(
            {
                "outcome": "MAYBE",
                "proposed_action": None,
                "confidence": 0.5,
                "evidence": [],
                "reasoning_summary": "",
                "tools_called": [],
            }
        )


def test_agent_output_rejects_confidence_outside_zero_to_one():
    with pytest.raises(ValueError, match="confidence"):
        AgentOutput.from_dict(
            {
                "outcome": "RESOLVED",
                "proposed_action": None,
                "confidence": 1.1,
                "evidence": [],
                "reasoning_summary": "",
                "tools_called": [],
            }
        )


def test_proposed_action_requires_all_three_values():
    with pytest.raises(ValueError, match="proposed_action"):
        ProposedAction.from_dict(
            {"field": "beneficiary_name", "current_value": "old"}
        )


def test_every_csv_row_has_one_case_file_and_preserves_expected_fields():
    with (ROOT / "fixtures" / "payments.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))

    case_files = load_case_files(ROOT / "fixtures" / "cases")
    assert len(case_files) == len(rows) == 40

    by_id = {item["case_id"]: item for item in case_files}
    for row in rows:
        case = by_id[row["case_id"]]
        assert case["expected_outcome"] == row["expected_outcome"]
        assert case["expected_path"] == row["expected_path"]
        assert case["payment"]["case_id"] == row["case_id"]
        assert set(case["payment"]) == set(PaymentCase.field_names())


def test_agent_outcome_enum_is_closed():
    assert AGENT_OUTCOMES == {
        "RESOLVED",
        "RESOLVED_LOW_CONFIDENCE",
        "AMBIGUOUS",
        "NEEDS_INFO",
        "EXHAUSTED",
        "BLOCKED_POLICY",
    }
