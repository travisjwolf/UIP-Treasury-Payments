"""Validated declarative state for the Payment Operations platform."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.contracts import (
    CounterpartyHistory,
    Evidence,
    PaymentCase,
    PolicyConfig,
    PolicyDecision,
)


DEFAULT_MANIFEST_PATH = Path(__file__).with_name("platform.manifest.json")
_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,99}$")
_RESERVED_PHYSICAL_NAMES = {
    "case",
    "class",
    "else",
    "from",
    "group",
    "id",
    "if",
    "index",
    "key",
    "new",
    "object",
    "order",
    "public",
    "return",
    "role",
    "select",
    "status",
    "table",
    "then",
    "timestamp",
    "type",
    "user",
    "where",
}
_SYSTEM_FIELDS = {"createdby", "createtime", "id", "updatedby", "updatetime"}
_SECRET_ASSET_TYPES = {"credential", "secret"}
_CONTRACT_MODELS: dict[str, type[BaseModel]] = {
    "PaymentCase": PaymentCase,
    "Evidence": Evidence,
    "CounterpartyHistory": CounterpartyHistory,
    "PolicyDecision": PolicyDecision,
    "PolicyConfig": PolicyConfig,
}


class ManifestValidationError(ValueError):
    """Raised when checked-in desired state is unsafe or contract-incompatible."""


class ManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FieldDefinition(ManifestModel):
    logical_name: str
    physical_name: str
    field_type: str = Field(alias="type")
    display_name: str
    description: str
    is_required: bool = False
    is_unique: bool = False
    is_encrypted: bool = False
    length_limit: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    decimal_precision: int | None = None
    default_value: str | None = None

    def cli_definition(self) -> dict[str, Any]:
        definition: dict[str, Any] = {
            "fieldName": self.physical_name,
            "type": self.field_type,
            "displayName": self.display_name,
            "description": self.description,
            "isRequired": self.is_required,
            "isUnique": self.is_unique,
            "isEncrypted": self.is_encrypted,
        }
        optional = {
            "lengthLimit": self.length_limit,
            "minValue": self.min_value,
            "maxValue": self.max_value,
            "decimalPrecision": self.decimal_precision,
            "defaultValue": self.default_value,
        }
        definition.update({key: value for key, value in optional.items() if value is not None})
        return definition


class EntityDefinition(ManifestModel):
    contract: str
    physical_name: str
    display_name: str
    description: str
    is_rbac_enabled: bool = False
    fields: tuple[FieldDefinition, ...]

    def cli_body(self) -> dict[str, Any]:
        return {
            "displayName": self.display_name,
            "description": self.description,
            "isRbacEnabled": self.is_rbac_enabled,
            "fields": [field.cli_definition() for field in self.fields],
        }


class SchemaApproval(ManifestModel):
    required: bool
    reason: str
    logical_to_physical: dict[str, str]


class GateSettings(ManifestModel):
    entity_contract: Literal["PolicyConfig"]
    seeds: tuple[PolicyConfig, ...]


class FolderDefinition(ManifestModel):
    name: str
    path: str
    description: str
    permission_model: Literal["FineGrained", "InheritFromTenant"]
    feed_type: Literal["Processes", "FolderHierarchy", "Libraries"]
    provision_type: Literal["Automatic", "Manual"]


class QueueDefinition(ManifestModel):
    name: str
    description: str
    max_retries: int = Field(ge=0)
    auto_retry: bool
    retry_abandoned_items: bool
    enforce_unique_reference: bool
    encrypted: bool
    retention_action: Literal["Delete", "Archive", "None"]
    retention_period_days: int = Field(gt=0)
    stale_retention_action: Literal["Delete", "Archive", "None"]
    stale_retention_period_days: int = Field(gt=0)


class AssetDefinition(ManifestModel):
    name: str
    value_type: Literal["Text", "Bool", "Integer", "Credential", "Secret"]
    value: str | int | bool
    scope: Literal["Global", "PerRobot"] = "Global"
    description: str


class OrchestratorDefinition(ManifestModel):
    folder: FolderDefinition
    queues: tuple[QueueDefinition, ...]
    assets: tuple[AssetDefinition, ...]


class SecurityDefinition(ManifestModel):
    allow_secret_assets: bool
    agent_write_credentials: bool


class PlatformManifest(ManifestModel):
    manifest_version: Literal[1]
    schema_approval: SchemaApproval
    entities: tuple[EntityDefinition, ...]
    gate_settings: GateSettings
    orchestrator: OrchestratorDefinition
    security: SecurityDefinition

    def entity_for_contract(self, contract: str) -> EntityDefinition:
        matches = [entity for entity in self.entities if entity.contract == contract]
        if len(matches) != 1:
            raise ManifestValidationError(
                f"expected exactly one entity for contract {contract!r}"
            )
        return matches[0]


def _duplicates(values: list[str]) -> set[str]:
    return {value for value in values if values.count(value) > 1}


def _validate_contract_alignment(manifest: PlatformManifest) -> None:
    contract_names = [entity.contract for entity in manifest.entities]
    duplicate_contracts = _duplicates(contract_names)
    if duplicate_contracts:
        raise ManifestValidationError(
            f"duplicate entity contracts: {sorted(duplicate_contracts)}"
        )
    if set(contract_names) != set(_CONTRACT_MODELS):
        raise ManifestValidationError(
            "entity contracts must exactly match Alpha's persisted contract set"
        )

    actual_mappings: dict[str, str] = {}
    physical_entities: list[str] = []
    for entity in manifest.entities:
        physical_entities.append(entity.physical_name)
        if not _NAME_PATTERN.fullmatch(entity.physical_name):
            raise ManifestValidationError(
                f"invalid Data Fabric entity name: {entity.physical_name!r}"
            )
        expected_fields = set(_CONTRACT_MODELS[entity.contract].model_fields)
        actual_fields = {field.logical_name for field in entity.fields}
        if len(actual_fields) != len(entity.fields) or actual_fields != expected_fields:
            raise ManifestValidationError(
                f"{entity.contract} fields do not match the Alpha contract"
            )
        physical_fields = [field.physical_name for field in entity.fields]
        if _duplicates(physical_fields):
            raise ManifestValidationError(
                f"{entity.contract} contains duplicate physical field names"
            )
        for field in entity.fields:
            if not _NAME_PATTERN.fullmatch(field.physical_name):
                raise ManifestValidationError(
                    f"invalid Data Fabric field name: {field.physical_name!r}"
                )
            lowered = field.physical_name.lower()
            if lowered in _RESERVED_PHYSICAL_NAMES or lowered in _SYSTEM_FIELDS:
                raise ManifestValidationError(
                    f"reserved Data Fabric field name: {field.physical_name!r}"
                )
            if field.logical_name != field.physical_name:
                actual_mappings[f"{entity.contract}.{field.logical_name}"] = (
                    field.physical_name
                )

    if _duplicates(physical_entities):
        raise ManifestValidationError("Data Fabric physical entity names must be unique")
    if actual_mappings != manifest.schema_approval.logical_to_physical:
        raise ManifestValidationError(
            "logical-to-physical mappings must be declared exactly in schema_approval"
        )
    if actual_mappings and not manifest.schema_approval.required:
        raise ManifestValidationError(
            "logical-to-physical contract mappings require schema approval"
        )


def _validate_gate_settings(manifest: PlatformManifest) -> None:
    manifest.entity_for_contract(manifest.gate_settings.entity_contract)
    customer_ids = [seed.customer_id for seed in manifest.gate_settings.seeds]
    if not customer_ids or _duplicates(customer_ids):
        raise ManifestValidationError(
            "gate setting seeds require unique, non-empty customer IDs"
        )


def _validate_orchestrator(manifest: PlatformManifest) -> None:
    if manifest.security.allow_secret_assets:
        raise ManifestValidationError("secret assets are prohibited by this manifest")
    if manifest.security.agent_write_credentials:
        raise ManifestValidationError("the agent may not receive write credentials")

    queue_names = [queue.name for queue in manifest.orchestrator.queues]
    asset_names = [asset.name for asset in manifest.orchestrator.assets]
    if _duplicates(queue_names):
        raise ManifestValidationError("Orchestrator queue names must be unique")
    if _duplicates(asset_names):
        raise ManifestValidationError("Orchestrator asset names must be unique")
    if any(
        asset.value_type.lower() in _SECRET_ASSET_TYPES
        for asset in manifest.orchestrator.assets
    ):
        raise ManifestValidationError("secret assets are not allowed in source control")


def validate_manifest(manifest: PlatformManifest) -> PlatformManifest:
    _validate_contract_alignment(manifest)
    _validate_gate_settings(manifest)
    _validate_orchestrator(manifest)
    return manifest


def load_manifest(path: str | Path = DEFAULT_MANIFEST_PATH) -> PlatformManifest:
    manifest_path = Path(path)
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = PlatformManifest.model_validate(document)
        return validate_manifest(manifest)
    except ManifestValidationError:
        raise
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise ManifestValidationError(f"invalid platform manifest: {exc}") from exc
