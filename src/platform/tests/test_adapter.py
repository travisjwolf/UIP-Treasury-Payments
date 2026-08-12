import pytest

from src.platform.adapter import RecordAdapterError, logical_to_physical, physical_to_logical
from src.platform.manifest import load_manifest


@pytest.mark.parametrize(
    ("contract", "logical", "physical"),
    [
        (
            "PaymentCase",
            {"case_id": "WIRE-8802", "status": "pending"},
            {"case_id": "WIRE-8802", "payment_status": "pending"},
        ),
        (
            "Evidence",
            {
                "case_id": "WIRE-8802",
                "type": "history_match",
                "timestamp": "2026-08-07T12:19:00Z",
            },
            {
                "case_id": "WIRE-8802",
                "evidence_type": "history_match",
                "evidence_timestamp": "2026-08-07T12:19:00Z",
            },
        ),
    ],
)
def test_adapter_round_trips_explicit_contract_mappings(
    contract: str,
    logical: dict[str, object],
    physical: dict[str, object],
) -> None:
    manifest = load_manifest()

    assert logical_to_physical(manifest, contract, logical) == physical
    assert physical_to_logical(manifest, contract, physical) == logical


def test_adapter_rejects_unknown_logical_fields_instead_of_silently_persisting_them() -> None:
    with pytest.raises(RecordAdapterError, match="unknown logical field"):
        logical_to_physical(
            load_manifest(),
            "Evidence",
            {"case_id": "WIRE-8802", "invented_field": "unsafe"},
        )


def test_adapter_rejects_unknown_physical_fields_except_data_fabric_system_fields() -> None:
    manifest = load_manifest()

    with pytest.raises(RecordAdapterError, match="unknown physical field"):
        physical_to_logical(manifest, "PaymentCase", {"mystery": "unsafe"})

    assert physical_to_logical(
        manifest,
        "PaymentCase",
        {"Id": "record-id", "case_id": "WIRE-8802", "payment_status": "pending"},
    ) == {"case_id": "WIRE-8802", "status": "pending"}
