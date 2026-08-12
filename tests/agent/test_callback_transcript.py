import inspect
import json
import sys
from importlib import util
from pathlib import Path

import pytest

from src.agent import wire_repair_agent
from src.agent.wire_repair_agent import tooling
from src.agent.wire_repair_agent.repair import analyze_fixture
from src.contracts import (
    AgentOutput,
    GateId,
    PaymentCase,
    PaymentFixture,
    PolicyConfig,
    PolicyResult,
)
from src.gates import evaluate_policy


ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "src" / "agent"
TRANSCRIPT_PATH = (
    AGENT_ROOT
    / "wire_repair_agent"
    / "data"
    / "WIRE-8877-callback-transcript.txt"
)


def load_fixture(case_id: str) -> dict:
    return json.loads(
        (ROOT / "fixtures" / "cases" / f"{case_id}.json").read_text(
            encoding="utf-8"
        )
    )


def callback_api():
    analyzer_type = getattr(
        wire_repair_agent, "CallbackTranscriptAnalyzer", None
    )
    error_type = getattr(wire_repair_agent, "CallbackTranscriptError", None)
    parser = getattr(wire_repair_agent, "parse_callback_transcript", None)
    assert analyzer_type is not None, "callback analyzer is not implemented"
    assert error_type is not None, "callback analyzer error type is not implemented"
    assert parser is not None, "callback transcript parser is not implemented"
    return analyzer_type, error_type, parser


def load_graph_module():
    sys.path.insert(0, str(AGENT_ROOT))
    spec = util.spec_from_file_location(
        "wire_repair_callback_graph", AGENT_ROOT / "main.py"
    )
    assert spec is not None and spec.loader is not None
    module = util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_prerecorded_transcript_is_synthetic_explicit_and_packaged():
    assert TRANSCRIPT_PATH.is_file(), "checked-in callback transcript is missing"
    transcript = TRANSCRIPT_PATH.read_text(encoding="utf-8")
    assert "case_id: WIRE-8877" in transcript
    assert "recorded_at: 2026-08-07T09:05:00Z" in transcript
    assert "customer_name: Northgate Property Partners" in transcript
    assert "beneficiary_name: ATLAS TITLE & ESCROW" in transcript
    assert "remittance_reference: NG-2291" in transcript
    assert "beneficiary_account_last_four: 2299" in transcript
    assert "full_replacement_account_provided: false" in transcript
    assert "full_replacement_account_authorized: false" in transcript
    assert "4471902299" not in transcript

    config = json.loads((AGENT_ROOT / "uipath.json").read_text(encoding="utf-8"))
    assert ".txt" in config["packOptions"]["fileExtensionsIncluded"]


def test_callback_analyzer_extracts_and_flags_only_the_account_conflict():
    analyzer_type, _, _ = callback_api()
    payment = PaymentCase.from_fixture(load_fixture("WIRE-8877"))

    result = analyzer_type().analyze(payment)

    assert result.tool_name == "callback_transcript"
    assert result.evidence.case_id == "WIRE-8877"
    assert result.evidence.type == "call_transcript"
    assert result.evidence.source == (
        "fixture://callback-transcripts/WIRE-8877.txt"
    )
    assert result.evidence.produced_by == "callback_transcript"
    assert result.evidence.timestamp == "2026-08-07T09:05:00Z"
    assert json.loads(result.evidence.content) == result.data
    assert result.data == {
        "transcript": {
            "case_id": "WIRE-8877",
            "recorded_at": "2026-08-07T09:05:00Z",
            "text": (
                "Synthetic prerecorded callback: Northgate Property Partners "
                "confirms beneficiary ATLAS TITLE & ESCROW and closing "
                "reference NG-2291. The caller confirms only that the beneficiary "
                "account ends in 2299 and does not provide or authorize a full "
                "replacement account."
            ),
        },
        "extracted_entities": {
            "customer_name": "Northgate Property Partners",
            "beneficiary_name": "ATLAS TITLE & ESCROW",
            "remittance_reference": "NG-2291",
            "beneficiary_account_last_four": "2299",
            "full_replacement_account_provided": False,
            "full_replacement_account_authorized": False,
        },
        "reconciliation": {
            "customer_name": {
                "payment_value": "Northgate Property Partners",
                "transcript_value": "Northgate Property Partners",
                "status": "match",
            },
            "beneficiary_name": {
                "payment_value": "ATLAS TITLE & ESCROW",
                "transcript_value": "ATLAS TITLE & ESCROW",
                "status": "match",
            },
            "remittance_reference": {
                "payment_value": "CLOSING FILE NG-2291",
                "transcript_value": "NG-2291",
                "status": "match",
            },
            "beneficiary_account": {
                "payment_last_four": "2288",
                "transcript_last_four": "2299",
                "status": "conflict",
            },
        },
        "flagged_fields": ["beneficiary_account"],
    }
    assert "beneficiary_account" not in result.data["extracted_entities"]


def test_callback_analyzer_fails_closed_for_unknown_case():
    analyzer_type, error_type, _ = callback_api()
    payment = PaymentCase.from_fixture(load_fixture("WIRE-8877")).model_copy(
        update={"case_id": "WIRE-UNKNOWN"}
    )

    with pytest.raises(error_type, match="not mapped"):
        analyzer_type().analyze(payment)


@pytest.mark.parametrize(
    "malformed_transcript",
    [
        "case_id: WIRE-8877\n",
        (
            "format_version: CALLBACK_TRANSCRIPT_V1\n"
            "case_id: WIRE-8877\n"
            "recorded_at: 2026-08-07T09:05:00Z\n"
            "customer_name: Northgate Property Partners\n"
            "beneficiary_name: ATLAS TITLE & ESCROW\n"
            "remittance_reference: NG-2291\n"
            "beneficiary_account_last_four: 2299\n"
            "full_replacement_account_provided: true\n"
            "full_replacement_account_authorized: false\n"
            "transcript_text: synthetic text\n"
        ),
    ],
)
def test_callback_parser_fails_closed_for_missing_fields_or_full_account(
    malformed_transcript: str,
):
    _, error_type, parser = callback_api()

    with pytest.raises(error_type):
        parser(malformed_transcript)


@pytest.mark.anyio
async def test_wire_8877_returns_one_canonical_callback_evidence_record():
    raw_output = await analyze_fixture(
        load_fixture("WIRE-8877"), tooling.CsvRepairTools()
    )
    output = AgentOutput.from_dict(raw_output)

    assert output.outcome == "NEEDS_INFO"
    assert output.proposed_action is None
    assert output.confidence == 0.74
    assert output.tools_called == ["callback_transcript"]
    assert len(output.evidence) == 1
    evidence = output.evidence[0]
    assert evidence.type == "call_transcript"
    assert evidence.source == "fixture://callback-transcripts/WIRE-8877.txt"
    assert evidence.produced_by == "callback_transcript"
    assert json.loads(evidence.content)["flagged_fields"] == [
        "beneficiary_account"
    ]
    assert "partial account confirmation conflicts" in (
        output.reasoning_summary.lower()
    )
    assert "human" in output.reasoning_summary.lower()


@pytest.mark.anyio
async def test_wire_8877_routes_through_alpha_gate_g9_to_callback_then_human():
    fixture_data = load_fixture("WIRE-8877")
    fixture = PaymentFixture.model_validate(fixture_data)
    output = AgentOutput.from_dict(
        await analyze_fixture(fixture_data, tooling.CsvRepairTools())
    )

    decision = evaluate_policy(
        fixture.payment_case,
        output,
        fixture.gate_context,
        PolicyConfig(
            customer_id=fixture.payment_case.customer_id,
            same_day_beneficiary_velocity_threshold_usd=5_000_000.0,
        ),
    )

    assert decision.gate == GateId.G9
    assert decision.result == PolicyResult.CALLBACK_THEN_HUMAN


@pytest.mark.anyio
async def test_real_langgraph_entrypoint_defaults_to_callback_analysis():
    module = load_graph_module()

    output = AgentOutput.from_dict(
        await module.graph.ainvoke(load_fixture("WIRE-8877"))
    )

    assert output.outcome == "NEEDS_INFO"
    assert output.proposed_action is None
    assert output.confidence == 0.74
    assert output.tools_called == ["callback_transcript"]
    assert len(output.evidence) == 1
    assert output.evidence[0].type == "call_transcript"


def test_callback_analysis_does_not_extend_repair_tools_protocol():
    protocol_methods = {
        name
        for name, value in vars(tooling.RepairTools).items()
        if not name.startswith("_") and callable(value)
    }
    tools = tooling.CsvRepairTools()
    public_callables = {
        name
        for name in dir(tools)
        if not name.startswith("_") and callable(getattr(tools, name))
    }

    assert protocol_methods == {
        "account_lookup",
        "counterparty_history",
        "documents",
        "sanctions",
    }
    assert public_callables == protocol_methods
    assert all(
        inspect.iscoroutinefunction(getattr(tools, name))
        for name in protocol_methods
    )
