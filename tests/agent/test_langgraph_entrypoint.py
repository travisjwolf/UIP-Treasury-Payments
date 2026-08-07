import importlib.util
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from pydantic import ValidationError

from src.contracts import AgentOutput, GateContext, PaymentCase


ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = ROOT / "src" / "agent"


def load_graph_module():
    sys.path.insert(0, str(AGENT_ROOT))
    spec = importlib.util.spec_from_file_location(
        "wire_repair_graph", AGENT_ROOT / "main.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_fixture(case_id: str) -> dict:
    return json.loads(
        (ROOT / "fixtures" / "cases" / f"{case_id}.json").read_text(
            encoding="utf-8"
        )
    )


@pytest.mark.anyio
async def test_langgraph_entrypoint_emits_the_complete_agent_contract():
    module = load_graph_module()

    raw_output = await module.graph.ainvoke(load_fixture("WIRE-8802"))
    output = AgentOutput.from_dict(raw_output)

    assert output.outcome == "RESOLVED"
    assert output.proposed_action is not None
    assert output.proposed_action.proposed_value == "PACIFIC STEEL & SUPPLY"
    assert len(output.evidence) == 3
    assert output.tools_called == [
        "sanctions",
        "account_lookup",
        "counterparty_history",
    ]


def test_public_schema_is_typed_described_and_does_not_expose_fixture_answers():
    module = load_graph_module()

    input_schema = module.Input.model_json_schema()
    output_schema = module.Output.model_json_schema()

    assert "expected_outcome" not in input_schema["properties"]
    assert "expected_path" not in input_schema["properties"]
    assert "case_id" not in input_schema["properties"]
    assert "payment" not in input_schema["properties"]
    assert input_schema["properties"]["payment_case"]["description"]
    assert input_schema["properties"]["gate_context"]["description"]
    assert set(output_schema["properties"]["outcome"]["enum"]) == {
        "RESOLVED",
        "RESOLVED_LOW_CONFIDENCE",
        "AMBIGUOUS",
        "NEEDS_INFO",
        "EXHAUSTED",
        "BLOCKED_POLICY",
    }
    assert all(
        property_schema.get("description")
        for property_schema in output_schema["properties"].values()
    )


def test_deploy_models_preserve_shared_required_fields_and_reject_extras():
    module = load_graph_module()
    fixture = load_fixture("WIRE-8802")

    payment_schema = module.PaymentInput.model_json_schema()
    gate_schema = module.GateContextInput.model_json_schema()
    assert set(payment_schema["required"]) == set(
        PaymentCase.model_json_schema()["required"]
    )
    assert set(gate_schema["required"]) == set(
        GateContext.model_json_schema()["required"]
    )

    payment_without_optional_owner_fields = dict(fixture["payment_case"])
    payment_without_optional_owner_fields.pop("sla_deadline")
    payment_without_optional_owner_fields.pop("worked_by")
    payment = module.PaymentInput.model_validate(
        payment_without_optional_owner_fields
    )
    assert payment.sla_deadline is None
    assert payment.worked_by is None

    runtime_input = {
        "payment_case": fixture["payment_case"],
        "gate_context": fixture["gate_context"],
        "demo_role": fixture["demo_role"],
    }
    module.Input.model_validate(runtime_input)
    with pytest.raises(ValidationError):
        module.Input.model_validate(
            {**runtime_input, "expected_outcome": fixture["expected_outcome"]}
        )
    with pytest.raises(ValidationError):
        module.PaymentInput.model_validate(
            {**fixture["payment_case"], "unexpected_payment_field": "unsafe"}
        )

    for case_path in sorted((ROOT / "fixtures" / "cases").glob("*.json")):
        case_fixture = json.loads(case_path.read_text(encoding="utf-8"))
        shared_payment = PaymentCase.model_validate(case_fixture["payment_case"])
        deploy_payment = module.PaymentInput.model_validate(
            case_fixture["payment_case"]
        )
        assert deploy_payment.model_dump(mode="json") == shared_payment.model_dump(
            mode="json"
        )

        shared_gate = GateContext.model_validate(case_fixture["gate_context"])
        deploy_gate = module.GateContextInput.model_validate(
            case_fixture["gate_context"]
        )
        assert deploy_gate.model_dump(mode="json") == shared_gate.model_dump(
            mode="json"
        )


def test_checked_in_entrypoint_schemas_accept_nullable_contract_values():
    manifest = json.loads(
        (AGENT_ROOT / "entry-points.json").read_text(encoding="utf-8")
    )
    entrypoint = manifest["entryPoints"][0]
    input_validator = Draft202012Validator(entrypoint["input"])
    output_validator = Draft202012Validator(entrypoint["output"])

    for case_id in ("WIRE-8802", "WIRE-8841"):
        runtime_fixture = load_fixture(case_id)
        runtime_fixture.pop("expected_outcome")
        runtime_fixture.pop("expected_path")
        assert list(input_validator.iter_errors(runtime_fixture)) == []

    exhausted_output = {
        "outcome": "EXHAUSTED",
        "proposed_action": None,
        "confidence": 0.0,
        "evidence": [],
        "reasoning_summary": "The bounded investigation exhausted its budget.",
        "tools_called": [],
    }
    assert list(output_validator.iter_errors(exhausted_output)) == []


def test_checked_in_schema_closes_evidence_types_and_describes_nullable_fields():
    manifest = json.loads(
        (AGENT_ROOT / "entry-points.json").read_text(encoding="utf-8")
    )
    entrypoint = manifest["entryPoints"][0]
    payment_properties = entrypoint["input"]["properties"]["payment_case"][
        "properties"
    ]
    evidence_type = entrypoint["output"]["properties"]["evidence"]["items"][
        "properties"
    ]["type"]

    assert set(evidence_type["enum"]) == {
        "lookup",
        "history_match",
        "sanctions",
        "document",
        "call_transcript",
    }
    for field_name in (
        "sla_deadline",
        "worked_by",
        "confidence",
        "proposed_action",
        "outcome",
        "cycle_time",
    ):
        assert payment_properties[field_name]["description"]


def test_checked_in_schema_preserves_optional_fields_and_forbids_extras():
    manifest = json.loads(
        (AGENT_ROOT / "entry-points.json").read_text(encoding="utf-8")
    )
    entrypoint = manifest["entryPoints"][0]
    input_schema = entrypoint["input"]
    payment_schema = input_schema["properties"]["payment_case"]
    gate_schema = input_schema["properties"]["gate_context"]
    output_schema = entrypoint["output"]
    evidence_schema = output_schema["properties"]["evidence"]["items"]
    payment_action_schema = next(
        option
        for option in payment_schema["properties"]["proposed_action"]["anyOf"]
        if option.get("type") == "object"
    )
    output_action_schema = next(
        option
        for option in output_schema["properties"]["proposed_action"]["anyOf"]
        if option.get("type") == "object"
    )

    assert input_schema["additionalProperties"] is False
    assert payment_schema["additionalProperties"] is False
    assert gate_schema["additionalProperties"] is False
    assert output_schema["additionalProperties"] is False
    assert evidence_schema["additionalProperties"] is False
    assert payment_action_schema["additionalProperties"] is False
    assert output_action_schema["additionalProperties"] is False
    assert "sla_deadline" not in payment_schema["required"]
    assert "worked_by" not in payment_schema["required"]

    runtime_fixture = load_fixture("WIRE-8802")
    runtime_fixture.pop("expected_outcome")
    runtime_fixture.pop("expected_path")
    runtime_fixture["payment_case"].pop("sla_deadline")
    runtime_fixture["payment_case"].pop("worked_by")
    assert list(
        Draft202012Validator(input_schema).iter_errors(runtime_fixture)
    ) == []


def test_packaging_excludes_machine_local_agent_state():
    config = json.loads((AGENT_ROOT / "uipath.json").read_text(encoding="utf-8"))
    pack_options = config["packOptions"]

    assert {".venv", ".uipath", "__uipath", "__pycache__"}.issubset(
        pack_options["directoriesExcluded"]
    )
    assert ".env" in pack_options["filesExcluded"]

    bindings = json.loads((AGENT_ROOT / "bindings.json").read_text(encoding="utf-8"))
    assert bindings == {"version": "2.0", "resources": []}
