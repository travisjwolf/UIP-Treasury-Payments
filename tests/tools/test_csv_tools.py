import inspect
import json
from pathlib import Path

import pytest

from src.agent.wire_repair_agent import tooling
from src.contracts import PaymentCase
from src.tools import CsvRepairTools as PublicCsvRepairTools


ROOT = Path(__file__).resolve().parents[2]
SOURCE_HISTORY = ROOT / "fixtures" / "counterparty_history.csv"
PACKAGED_HISTORY = (
    ROOT
    / "src"
    / "agent"
    / "wire_repair_agent"
    / "data"
    / "counterparty_history.csv"
)


def load_case(case_id: str) -> PaymentCase:
    fixture = json.loads(
        (ROOT / "fixtures" / "cases" / f"{case_id}.json").read_text(
            encoding="utf-8"
        )
    )
    return PaymentCase.from_fixture(fixture)


def csv_tools(*, history_path: Path | None = None):
    implementation = getattr(tooling, "CsvRepairTools", None)
    assert implementation is not None, "CsvRepairTools is not implemented"
    return implementation(history_path=history_path)


@pytest.mark.anyio
async def test_account_lookup_finds_one_exact_customer_account_row():
    result = await csv_tools().account_lookup(load_case("WIRE-8802"))

    assert result.data == {
        "customer_id": "CUST-1042",
        "match_status": "exact",
        "queried_beneficiary_account": "8823004417",
        "beneficiary_account": "8823004417",
        "beneficiary_name": "PACIFIC STEEL & SUPPLY",
    }
    assert json.loads(result.evidence.content) == result.data
    assert result.evidence.source == "fixture://counterparty_history.csv#row=18"
    assert isinstance(result.data["beneficiary_account"], str)


@pytest.mark.anyio
async def test_account_lookup_does_not_expand_a_truncated_account():
    result = await csv_tools().account_lookup(load_case("WIRE-8841"))

    assert result.data == {
        "customer_id": "CUST-1042",
        "match_status": "not_found",
        "queried_beneficiary_account": "882300441",
    }
    assert json.loads(result.evidence.content) == result.data


@pytest.mark.anyio
async def test_ex02_history_requires_one_exact_customer_account_row():
    result = await csv_tools().counterparty_history(load_case("WIRE-8802"))

    assert result.data == {
        "customer_id": "CUST-1042",
        "queried_beneficiary_account": "8823004417",
        "beneficiary_name": "PACIFIC STEEL & SUPPLY",
        "beneficiary_account": "8823004417",
        "times_seen": 31,
        "times_repaired": 11,
        "last_applied_fix": "expand_truncated_account",
        "history_confidence": 0.94,
    }
    assert json.loads(result.evidence.content) == result.data
    assert result.evidence.source == "fixture://counterparty_history.csv#row=18"
    assert isinstance(result.data["beneficiary_account"], str)


@pytest.mark.anyio
async def test_leading_zero_account_identifier_is_preserved_as_a_string():
    case = load_case("WIRE-8802").model_copy(
        update={
            "customer_id": "CUST-1355",
            "beneficiary_account": "0517769650",
        }
    )

    account = await csv_tools().account_lookup(case)
    history = await csv_tools().counterparty_history(case)

    assert account.data["beneficiary_account"] == "0517769650"
    assert history.data["beneficiary_account"] == "0517769650"
    assert isinstance(account.data["beneficiary_account"], str)
    assert isinstance(history.data["beneficiary_account"], str)


@pytest.mark.anyio
async def test_ex01_history_finds_one_customer_name_account_prefix_row():
    result = await csv_tools().counterparty_history(load_case("WIRE-8841"))

    assert result.data == {
        "customer_id": "CUST-1042",
        "queried_beneficiary_account": "882300441",
        "beneficiary_name": "PACIFIC STEEL & SUPPLY",
        "beneficiary_account": "8823004417",
        "times_seen": 31,
        "times_repaired": 11,
        "last_applied_fix": "expand_truncated_account",
        "history_confidence": 0.94,
    }
    assert json.loads(result.evidence.content) == result.data
    assert result.evidence.source == "fixture://counterparty_history.csv#row=18"


@pytest.mark.anyio
async def test_history_matching_never_crosses_customer_boundaries():
    case = load_case("WIRE-8841").model_copy(
        update={"customer_id": "CUST-OTHER"}
    )

    history = await csv_tools().counterparty_history(case)
    account = await csv_tools().account_lookup(
        case.model_copy(update={"beneficiary_account": "8823004417"})
    )

    assert history.data == {
        "customer_id": "CUST-OTHER",
        "queried_beneficiary_account": "882300441",
        "matches": [],
    }
    assert account.data == {
        "customer_id": "CUST-OTHER",
        "match_status": "not_found",
        "queried_beneficiary_account": "8823004417",
    }


@pytest.mark.anyio
async def test_ambiguous_history_candidates_expose_no_top_level_proposal(
    tmp_path: Path,
):
    history_path = tmp_path / "counterparty_history.csv"
    history_path.write_text(
        "customer_id,beneficiary_name,beneficiary_account,times_seen,"
        "times_repaired,last_applied_fix,history_confidence\n"
        "CUST-1042,PACIFIC STEEL & SUPPLY,8823004417,31,11,"
        "expand_truncated_account,0.94\n"
        "CUST-1042,Pacific Steel and Supply,8823004418,6,2,"
        "expand_truncated_account,0.88\n",
        encoding="utf-8",
    )

    result = await csv_tools(history_path=history_path).counterparty_history(
        load_case("WIRE-8841")
    )

    assert result.data["match_status"] == "ambiguous"
    assert result.data["match_count"] == 2
    assert "beneficiary_name" not in result.data
    assert "beneficiary_account" not in result.data
    assert json.loads(result.evidence.content) == result.data


@pytest.mark.anyio
async def test_conflicting_exact_account_rows_fail_closed_as_ambiguous(
    tmp_path: Path,
):
    history_path = tmp_path / "counterparty_history.csv"
    history_path.write_text(
        "customer_id,beneficiary_name,beneficiary_account,times_seen,"
        "times_repaired,last_applied_fix,history_confidence\n"
        "CUST-1042,PACIFIC STEEL & SUPPLY,8823004417,31,11,"
        "expand_truncated_account,0.94\n"
        "CUST-1042,PACIFIC STEEL SUPPLY LLC,8823004417,2,1,"
        "normalize_name_to_registered_entity,0.72\n",
        encoding="utf-8",
    )

    result = await csv_tools(history_path=history_path).account_lookup(
        load_case("WIRE-8802")
    )

    assert result.data == {
        "customer_id": "CUST-1042",
        "match_status": "ambiguous",
        "match_count": 2,
        "queried_beneficiary_account": "8823004417",
    }
    assert "beneficiary_name" not in result.data
    assert "beneficiary_account" not in result.data
    assert json.loads(result.evidence.content) == result.data


def test_deploy_copy_is_byte_identical_and_csv_is_packaged():
    assert PACKAGED_HISTORY.exists(), "deploy-local history copy is missing"
    assert PACKAGED_HISTORY.read_bytes() == SOURCE_HISTORY.read_bytes()

    config = json.loads(
        (ROOT / "src" / "agent" / "uipath.json").read_text(encoding="utf-8")
    )
    assert ".csv" in config["packOptions"]["fileExtensionsIncluded"]


def test_csv_toolset_preserves_the_four_method_async_read_only_protocol():
    tools = csv_tools()

    assert isinstance(tools, tooling.RepairTools)
    assert PublicCsvRepairTools is tooling.CsvRepairTools
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
    assert all(
        inspect.iscoroutinefunction(getattr(tools, name))
        for name in (
            "account_lookup",
            "counterparty_history",
            "documents",
            "sanctions",
        )
    )


@pytest.mark.anyio
async def test_default_path_falls_back_to_the_packaged_copy(monkeypatch, tmp_path):
    implementation = tooling.CsvRepairTools
    monkeypatch.setattr(
        implementation,
        "_REPOSITORY_HISTORY_PATH",
        tmp_path / "missing.csv",
    )

    tools = implementation()
    result = await tools.counterparty_history(load_case("WIRE-8802"))

    assert tools.history_path == PACKAGED_HISTORY
    assert result.data["beneficiary_name"] == "PACIFIC STEEL & SUPPLY"
