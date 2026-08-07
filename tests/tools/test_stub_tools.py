import json
from pathlib import Path

import pytest

from src.contracts import PaymentCase
from src.tools import RepairTools, StubRepairTools


ROOT = Path(__file__).resolve().parents[2]


def load_case(case_id: str) -> PaymentCase:
    fixture = json.loads(
        (ROOT / "fixtures" / "cases" / f"{case_id}.json").read_text(
            encoding="utf-8"
        )
    )
    return PaymentCase.from_fixture(fixture)


@pytest.mark.anyio
async def test_counterparty_history_evidence_contains_known_beneficiary():
    result = await StubRepairTools().counterparty_history(load_case("WIRE-8802"))

    assert result.tool_name == "counterparty_history"
    assert result.data == {
        "customer_id": "CUST-1042",
        "beneficiary_name": "PACIFIC STEEL & SUPPLY",
        "beneficiary_account": "8823004417",
        "times_seen": 31,
        "times_repaired": 11,
        "last_applied_fix": "expand_truncated_account",
        "history_confidence": 0.94,
    }
    assert json.loads(result.evidence.content) == result.data
    assert result.evidence.case_id == "WIRE-8802"
    assert result.evidence.type == "history_match"
    assert result.evidence.produced_by == "counterparty_history"


@pytest.mark.anyio
async def test_counterparty_history_does_not_cross_customer_boundaries():
    unrelated_case = load_case("WIRE-8802").model_copy(
        update={"customer_id": "CUST-9999"}
    )

    result = await StubRepairTools().counterparty_history(unrelated_case)

    assert result.data == {"customer_id": "CUST-9999", "matches": []}
    assert json.loads(result.evidence.content) == result.data


@pytest.mark.anyio
async def test_account_lookup_distinguishes_exact_from_truncated_accounts():
    exact = await StubRepairTools().account_lookup(load_case("WIRE-8802"))
    truncated = await StubRepairTools().account_lookup(load_case("WIRE-8841"))

    assert exact.data == {
        "match_status": "exact",
        "beneficiary_account": "8823004417",
        "beneficiary_name": "PACIFIC STEEL & SUPPLY",
    }
    assert truncated.data == {
        "match_status": "not_found",
        "queried_beneficiary_account": "882300441",
    }
    assert json.loads(exact.evidence.content) == exact.data
    assert json.loads(truncated.evidence.content) == truncated.data
    assert truncated.evidence.case_id == "WIRE-8841"
    assert truncated.evidence.type == "lookup"


@pytest.mark.anyio
async def test_sanctions_check_returns_clear_evidence():
    result = await StubRepairTools().sanctions(load_case("WIRE-8802"))

    assert result.tool_name == "sanctions"
    assert result.data == {
        "status": "clear",
        "screening_id": "STUB-WIRE-8802",
        "lists_checked": ["OFAC-SDN", "EU-CFSP"],
    }
    assert json.loads(result.evidence.content) == result.data
    assert result.evidence.type == "sanctions"


@pytest.mark.anyio
async def test_documents_tool_returns_an_auditable_not_required_result():
    result = await StubRepairTools().documents(load_case("WIRE-8802"))

    assert result.tool_name == "documents"
    assert result.data == {"status": "not_required", "documents": []}
    assert json.loads(result.evidence.content) == result.data
    assert result.evidence.type == "document"


def test_stub_toolset_implements_a_read_only_protocol():
    tools = StubRepairTools()

    assert isinstance(tools, RepairTools)
    assert {
        name
        for name in dir(tools)
        if not name.startswith("_") and callable(getattr(tools, name))
    } == {
        "account_lookup",
        "counterparty_history",
        "documents",
        "sanctions",
    }
