import json
from pathlib import Path
from typing import Any

from .fixtures import write_case_fixtures


def write_case_files(payments_csv: Path, cases_dir: Path) -> None:
    write_case_fixtures(payments_csv, cases_dir)


def _legacy_view(fixture: dict[str, Any]) -> dict[str, Any]:
    if "payment_case" not in fixture:
        return fixture
    context = fixture["gate_context"]
    payment = fixture["payment_case"]
    return {
        "case_id": payment["case_id"],
        "payment": payment,
        "fixture_metadata": {
            "demo_role": fixture["demo_role"] or "",
            "first_time_counterparty": context["first_time_counterparty"],
            "sanctions_flag": context["sanctions_status"],
            "received_at": context["evaluated_at"],
            "cutoff_at": context["cutoff_at"],
        },
        "expected_outcome": fixture["expected_outcome"],
        "expected_path": fixture["expected_path"],
    }


def load_case_files(cases_dir: Path) -> list[dict[str, Any]]:
    return [
        _legacy_view(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(cases_dir.glob("*.json"))
    ]
