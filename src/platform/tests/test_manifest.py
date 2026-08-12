import csv
import json
import re
from pathlib import Path

import pytest

from src.contracts import (
    CounterpartyHistory,
    Evidence,
    PaymentCase,
    PolicyConfig,
    PolicyDecision,
)
from src.platform.manifest import (
    DEFAULT_MANIFEST_PATH,
    ManifestValidationError,
    is_data_fabric_reserved_name,
    load_manifest,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = {
    "PaymentCase": PaymentCase,
    "Evidence": Evidence,
    "CounterpartyHistory": CounterpartyHistory,
    "PolicyDecision": PolicyDecision,
    "PolicyConfig": PolicyConfig,
}
EXPECTED_MAPPINGS = {
    "PaymentCase.status": "payment_status",
    "Evidence.type": "evidence_type",
    "Evidence.timestamp": "evidence_timestamp",
}
EXPECTED_QUEUES = {
    "PaymentRepairIntake",
    "PaymentEffectRequests",
    "PaymentEscalations",
}
EXPECTED_ASSETS = {
    "PaymentCaseEntityName",
    "EvidenceEntityName",
    "CounterpartyHistoryEntityName",
    "PolicyDecisionEntityName",
    "CustomerGateSettingsEntityName",
    "PaymentRepairIntakeQueueName",
    "PaymentEffectRequestsQueueName",
    "PaymentEscalationsQueueName",
    "AgentMaxIterations",
    "AgentTokenBudget",
    "PaymentAutoApplyEnabled",
}


def _fixture_customer_ids() -> set[str]:
    with (REPO_ROOT / "fixtures" / "payments.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        return {row["customer_id"] for row in csv.DictReader(handle)}


def test_manifest_contains_every_contract_entity_and_logical_field() -> None:
    manifest = load_manifest()
    entities_by_contract = {entity.contract: entity for entity in manifest.entities}

    assert set(entities_by_contract) == set(CONTRACTS)
    for contract_name, contract_model in CONTRACTS.items():
        logical_fields = {
            field.logical_name for field in entities_by_contract[contract_name].fields
        }
        assert logical_fields == set(contract_model.model_fields)


def test_reserved_contract_names_have_explicit_approved_physical_mappings() -> None:
    manifest = load_manifest()
    actual_mappings = {
        f"{entity.contract}.{field.logical_name}": field.physical_name
        for entity in manifest.entities
        for field in entity.fields
        if field.logical_name != field.physical_name
    }

    assert actual_mappings == EXPECTED_MAPPINGS
    assert manifest.schema_approval.required is True
    assert manifest.schema_approval.logical_to_physical == EXPECTED_MAPPINGS
    assert "reserved" in manifest.schema_approval.reason.lower()
    assert all(
        field.physical_name.lower() not in {"status", "timestamp", "type"}
        for entity in manifest.entities
        for field in entity.fields
    )


def test_every_logical_name_in_the_conservative_reserved_set_is_mapped() -> None:
    manifest = load_manifest()
    collisions = {
        f"{entity.contract}.{field.logical_name}"
        for entity in manifest.entities
        for field in entity.fields
        if is_data_fabric_reserved_name(field.logical_name)
    }

    assert collisions == set(EXPECTED_MAPPINGS)


@pytest.mark.parametrize(
    "name",
    ["select", "timestamp", "public", "boolean", "function", "value", "while"],
)
def test_conservative_reserved_set_covers_sql_csharp_and_visual_basic(
    name: str,
) -> None:
    assert is_data_fabric_reserved_name(name)


def test_gate_settings_seed_every_fixture_customer_with_all_configurable_gates() -> None:
    manifest = load_manifest()

    assert {seed.customer_id for seed in manifest.gate_settings.seeds} == (
        _fixture_customer_ids()
    )
    for seed in manifest.gate_settings.seeds:
        validated = PolicyConfig.model_validate(seed.model_dump())
        assert validated.auto_apply_amount_threshold_usd == 250_000.0
        assert validated.minimum_confidence == 0.85
        assert validated.same_day_beneficiary_velocity_threshold_usd == 5_000_000.0
        assert validated.cutoff_escalation_minutes == 30


def test_orchestrator_resources_are_complete_and_non_secret() -> None:
    manifest = load_manifest()

    assert manifest.orchestrator.folder.path == "TreasuryPayments"
    assert {queue.name for queue in manifest.orchestrator.queues} == EXPECTED_QUEUES
    assert {asset.name for asset in manifest.orchestrator.assets} == EXPECTED_ASSETS
    assert all(
        asset.value_type not in {"Credential", "Secret"}
        for asset in manifest.orchestrator.assets
    )
    assert manifest.security.allow_secret_assets is False
    assert manifest.security.agent_write_credentials is False


def test_bounded_agent_assets_match_the_merged_bravo_runtime_defaults() -> None:
    assets = {asset.name: asset.value for asset in load_manifest().orchestrator.assets}

    assert assets["AgentMaxIterations"] == 3
    assert assets["AgentTokenBudget"] == 1_200


def test_checked_in_manifest_is_tenant_neutral_and_contains_no_secret_markers() -> None:
    raw = DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8")
    lowered = raw.lower()

    assert "uipathstgss_updated" not in lowered
    assert "fins" not in lowered
    assert "uipath_access_token" not in lowered
    assert "client_secret" not in lowered
    assert "password" not in lowered
    assert re.search(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
        raw,
        re.IGNORECASE,
    ) is None


def test_loader_rejects_an_unapproved_logical_to_physical_mapping(
    tmp_path: Path,
) -> None:
    document = json.loads(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    document["schema_approval"]["required"] = False
    candidate = tmp_path / "manifest.json"
    candidate.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ManifestValidationError, match="schema approval"):
        load_manifest(candidate)


@pytest.mark.parametrize("value_type", ["Credential", "Secret"])
def test_loader_rejects_secret_or_credential_assets(
    tmp_path: Path,
    value_type: str,
) -> None:
    document = json.loads(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    document["orchestrator"]["assets"][0]["value_type"] = value_type
    candidate = tmp_path / "manifest.json"
    candidate.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ManifestValidationError, match="secret assets"):
        load_manifest(candidate)
