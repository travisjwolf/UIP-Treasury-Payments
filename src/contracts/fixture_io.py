from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .models import PaymentCase


def _payment_from_row(row: dict[str, str]) -> dict[str, Any]:
    return {
        "case_id": row["case_id"],
        "rail": row["rail"],
        "direction": row["direction"],
        "amount_usd": float(row["amount_usd"]),
        "currency": row["currency"],
        "value_date": row["value_date"],
        "cutoff_time": row["cutoff_time"],
        "sla_deadline": None,
        "source_channel": row["source_channel"],
        "customer_id": row["customer_id"],
        "customer_name": row["customer_name"],
        "beneficiary_name": row["beneficiary_name"],
        "beneficiary_account": row["beneficiary_account"],
        "beneficiary_bank_aba": row["beneficiary_bank_aba"],
        "remittance_info": row["remittance_info"],
        "exception_code": row["exception_code"],
        "exception_type": row["exception_type"],
        "current_queue": "repair",
        "status": "in_flight",
        "worked_by": None,
        "confidence": None,
        "proposed_action": None,
        "outcome": None,
        "touch_count": 0,
        "cycle_time": None,
    }


def write_case_files(payments_csv: Path, cases_dir: Path) -> None:
    cases_dir.mkdir(parents=True, exist_ok=True)
    with payments_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            fixture = {
                "case_id": row["case_id"],
                "payment": _payment_from_row(row),
                "fixture_metadata": {
                    "demo_role": row["demo_role"],
                    "first_time_counterparty": row["first_time_counterparty"] == "true",
                    "sanctions_flag": row["sanctions_flag"],
                    "received_at": row["received_at"],
                },
                "expected_outcome": row["expected_outcome"],
                "expected_path": row["expected_path"],
            }
            destination = cases_dir / f"{row['case_id']}.json"
            destination.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")


def load_case_files(cases_dir: Path) -> list[dict[str, Any]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(cases_dir.glob("*.json"))
    ]
