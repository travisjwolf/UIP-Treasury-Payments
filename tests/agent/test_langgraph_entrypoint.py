import importlib.util
import json
import sys
from pathlib import Path

import pytest

from src.contracts import AgentOutput


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
    assert output.tools_called == (
        "sanctions",
        "account_lookup",
        "counterparty_history",
    )


def test_public_schema_is_typed_described_and_does_not_expose_fixture_answers():
    module = load_graph_module()

    input_schema = module.Input.model_json_schema()
    output_schema = module.Output.model_json_schema()

    assert "expected_outcome" not in input_schema["properties"]
    assert "expected_path" not in input_schema["properties"]
    assert input_schema["properties"]["payment"]["description"]
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


def test_packaging_excludes_machine_local_agent_state():
    config = json.loads((AGENT_ROOT / "uipath.json").read_text(encoding="utf-8"))
    pack_options = config["packOptions"]

    assert {".venv", ".uipath", "__uipath", "__pycache__"}.issubset(
        pack_options["directoriesExcluded"]
    )
    assert ".env" in pack_options["filesExcluded"]
