from __future__ import annotations

import json
import sys
from pathlib import Path
from types import NoneType
from typing import get_args


AGENT_ROOT = Path(__file__).resolve().parents[1]
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

from main import GateContextInput, Input, Output, PaymentInput  # noqa: E402


def _allows_none(annotation: object) -> bool:
    return NoneType in get_args(annotation)


def _make_nullable(property_schema: dict, description: str | None) -> None:
    if any(
        option == {"type": "null"}
        for option in property_schema.get("anyOf", [])
    ):
        if description:
            property_schema["description"] = description
        return

    non_null_schema = dict(property_schema)
    non_null_schema.pop("description", None)
    property_schema.clear()
    property_schema["anyOf"] = [non_null_schema, {"type": "null"}]
    if description:
        property_schema["description"] = description


def _sync_model_properties(model: type, schema: dict) -> None:
    schema["additionalProperties"] = False
    schema["required"] = [
        name for name, field in model.model_fields.items() if field.is_required()
    ]
    properties = schema["properties"]
    for name, field in model.model_fields.items():
        property_schema = properties[name]
        if _allows_none(field.annotation):
            _make_nullable(property_schema, field.description)
        elif field.description:
            property_schema["description"] = field.description


def sync_entrypoints(path: Path = AGENT_ROOT / "entry-points.json") -> None:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    entrypoint = manifest["entryPoints"][0]

    _sync_model_properties(Input, entrypoint["input"])
    _sync_model_properties(
        PaymentInput,
        entrypoint["input"]["properties"]["payment_case"],
    )
    _sync_model_properties(
        GateContextInput,
        entrypoint["input"]["properties"]["gate_context"],
    )
    _sync_model_properties(Output, entrypoint["output"])

    path.write_text(json.dumps(manifest, indent=4) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sync_entrypoints()
