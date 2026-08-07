import csv
import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import GateContext, PaymentCase, PaymentFixture


EASTERN = ZoneInfo("America/New_York")


def _parse_bool(value: str, field_name: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"{field_name} must be 'true' or 'false', got {value!r}")


def _parse_evaluated_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=EASTERN)
    return parsed.astimezone(EASTERN)


def _parse_cutoff_at(value_date: str, cutoff_time: str) -> datetime:
    return datetime.fromisoformat(f"{value_date}T{cutoff_time}").replace(tzinfo=EASTERN)


def build_payment_fixture(row: Mapping[str, str]) -> PaymentFixture:
    amount_usd = float(row["amount_usd"])
    payment_case = PaymentCase(
        case_id=row["case_id"],
        rail=row["rail"],
        direction=row["direction"],
        amount_usd=amount_usd,
        currency=row["currency"],
        value_date=row["value_date"],
        cutoff_time=row["cutoff_time"],
        sla_deadline=None,
        source_channel=row["source_channel"],
        customer_id=row["customer_id"],
        customer_name=row["customer_name"],
        beneficiary_name=row["beneficiary_name"],
        beneficiary_account=row["beneficiary_account"],
        beneficiary_bank_aba=row["beneficiary_bank_aba"],
        remittance_info=row["remittance_info"],
        exception_code=row["exception_code"],
        exception_type=row["exception_type"],
        current_queue="repair",
        status="pending",
        worked_by=None,
        confidence=None,
        proposed_action=None,
        outcome=None,
        touch_count=0,
        cycle_time=None,
    )
    gate_context = GateContext(
        sanctions_status=row["sanctions_flag"],
        first_time_counterparty=_parse_bool(
            row["first_time_counterparty"],
            "first_time_counterparty",
        ),
        same_day_beneficiary_total_usd=amount_usd,
        cross_border=row["currency"] != "USD",
        evaluated_at=_parse_evaluated_at(row["received_at"]),
        cutoff_at=_parse_cutoff_at(row["value_date"], row["cutoff_time"]),
    )
    return PaymentFixture(
        payment_case=payment_case,
        gate_context=gate_context,
        expected_outcome=row["expected_outcome"],
        expected_path=row["expected_path"],
        demo_role=row["demo_role"] or None,
    )


def write_case_fixtures(source_csv: Path, output_dir: Path) -> list[Path]:
    with source_csv.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))

    case_ids = [row["case_id"] for row in rows]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("case_id values must be unique")

    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for row in rows:
        fixture = build_payment_fixture(row)
        output_path = output_dir / f"{fixture.payment_case.case_id}.json"
        payload = fixture.model_dump(mode="json")
        output_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written.append(output_path)
    return written


def main() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    paths = write_case_fixtures(
        repository_root / "fixtures" / "payments.csv",
        repository_root / "fixtures" / "cases",
    )
    print(f"Wrote {len(paths)} payment case fixtures.")


if __name__ == "__main__":
    main()
