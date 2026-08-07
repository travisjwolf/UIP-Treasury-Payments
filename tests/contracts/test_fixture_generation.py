import csv
from pathlib import Path

from src.contracts import PaymentFixture
from src.contracts.fixtures import build_payment_fixture, write_case_fixtures


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PAYMENTS_CSV = REPOSITORY_ROOT / "fixtures" / "payments.csv"


def load_rows() -> list[dict[str, str]]:
    with PAYMENTS_CSV.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def test_build_payment_fixture_maps_hero_case_to_contract_envelope() -> None:
    row = next(item for item in load_rows() if item["case_id"] == "WIRE-8802")

    fixture = build_payment_fixture(row)

    assert fixture.payment_case.case_id == "WIRE-8802"
    assert fixture.payment_case.amount_usd == 84_500.0
    assert fixture.payment_case.current_queue == "repair"
    assert fixture.payment_case.status == "pending"
    assert fixture.payment_case.sla_deadline is None
    assert fixture.gate_context.sanctions_status.value == "clear"
    assert fixture.gate_context.first_time_counterparty is False
    assert fixture.gate_context.same_day_beneficiary_total_usd == 84_500.0
    assert fixture.gate_context.evaluated_at.isoformat() == "2026-08-07T08:18:00-04:00"
    assert fixture.expected_outcome.value == "RESOLVED"
    assert fixture.expected_path.value == "auto_apply"
    assert fixture.demo_role == "hero_auto_resolve"


def test_write_case_fixtures_is_deterministic_and_preserves_source(
    tmp_path: Path,
) -> None:
    source_before = PAYMENTS_CSV.read_bytes()
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    first_paths = write_case_fixtures(PAYMENTS_CSV, first_dir)
    second_paths = write_case_fixtures(PAYMENTS_CSV, second_dir)

    expected_names = {f"{row['case_id']}.json" for row in load_rows()}
    assert len(first_paths) == 40
    assert {path.name for path in first_paths} == expected_names
    assert {path.name for path in first_dir.glob("*.json")} == expected_names
    assert PAYMENTS_CSV.read_bytes() == source_before
    for first_path in first_paths:
        second_path = second_dir / first_path.name
        assert first_path.read_bytes() == second_path.read_bytes()
        PaymentFixture.model_validate_json(first_path.read_text(encoding="utf-8"))


def test_repository_case_files_match_every_csv_row() -> None:
    expected = {
        row["case_id"]: (row["expected_outcome"], row["expected_path"])
        for row in load_rows()
    }
    case_dir = REPOSITORY_ROOT / "fixtures" / "cases"
    actual_paths = {path.stem: path for path in case_dir.glob("*.json")}

    assert set(actual_paths) == set(expected)
    for case_id, path in actual_paths.items():
        fixture = PaymentFixture.model_validate_json(path.read_text(encoding="utf-8"))
        assert fixture.payment_case.case_id == case_id
        assert fixture.expected_outcome.value == expected[case_id][0]
        assert fixture.expected_path.value == expected[case_id][1]
