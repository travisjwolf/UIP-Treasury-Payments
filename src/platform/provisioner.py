"""Discover-before-create provisioning over the supported ``uip`` CLI."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

from .manifest import (
    AssetDefinition,
    EntityDefinition,
    FieldDefinition,
    FolderDefinition,
    PlatformManifest,
    QueueDefinition,
)


_MISSING = object()
_NO_DEFAULT = object()
_SYSTEM_FIELDS = {"createdby", "createtime", "id", "updatedby", "updatetime"}


@dataclass(frozen=True)
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    def run(self, argv: Sequence[str]) -> CommandResult: ...


class SubprocessCommandRunner:
    """Run an argument vector without a shell on Windows, macOS, or Linux."""

    def run(self, argv: Sequence[str]) -> CommandResult:
        command = [str(part) for part in argv]
        executable = shutil.which(command[0])
        if executable is None:
            return CommandResult(127, "", f"executable not found: {command[0]}")
        command[0] = executable
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
            )
        except OSError as exc:
            return CommandResult(127, "", str(exc))
        return CommandResult(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


@dataclass(frozen=True)
class TenantTarget:
    base_url: str
    organization: str
    tenant: str

    def __post_init__(self) -> None:
        if not self.organization.strip() or not self.tenant.strip():
            raise ValueError("expected organization and tenant must be non-empty")
        object.__setattr__(self, "base_url", _normalize_base_url(self.base_url))
        object.__setattr__(self, "organization", self.organization.strip())
        object.__setattr__(self, "tenant", self.tenant.strip())

    @property
    def display_name(self) -> str:
        return f"{self.base_url} :: {self.organization}/{self.tenant}"


@dataclass(frozen=True)
class ProvisioningAction:
    resource_kind: str
    identifier: str
    command: tuple[str, ...]
    metadata: Mapping[str, str] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": "create",
            "resource_kind": self.resource_kind,
            "identifier": self.identifier,
            "command": list(_redact_command(self.command)),
        }


@dataclass(frozen=True)
class ProvisioningPlan:
    actions: tuple[ProvisioningAction, ...]
    target: TenantTarget | None
    assumed_clean: bool
    requires_schema_approval: bool

    @property
    def create_count(self) -> int:
        return len(self.actions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": "offline-clean" if self.assumed_clean else "tenant-discovery",
            "target": None if self.target is None else self.target.display_name,
            "create_count": self.create_count,
            "requires_schema_approval": self.requires_schema_approval,
            "actions": [action.to_dict() for action in self.actions],
        }


@dataclass(frozen=True)
class ApplyReport:
    initial_plan: ProvisioningPlan
    verification_plan: ProvisioningPlan
    created_count: int


class ProvisioningError(RuntimeError):
    """Base class for safe provisioning failures."""


class CommandExecutionError(ProvisioningError):
    pass


class DriftDetectedError(ProvisioningError):
    pass


class TargetMismatchError(ProvisioningError):
    pass


class ApprovalRequiredError(ProvisioningError):
    pass


def _normalize_base_url(value: str) -> str:
    raw_value = value.strip()
    try:
        parsed = urlsplit(raw_value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("expected base URL must be a valid HTTPS URL") from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("expected base URL must be a valid HTTPS URL")

    hostname = parsed.hostname.lower()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    netloc = hostname if port in (None, 443) else f"{hostname}:{port}"
    normalized_path = parsed.path.rstrip("/")
    return urlunsplit(("https", netloc, normalized_path, "", ""))


def redact_sensitive_text(value: str) -> str:
    """Redact common credential forms before propagating CLI diagnostics."""
    redacted = re.sub(
        r"(?i)(authorization\s*:\s*bearer\s+)([^\s,;]+)",
        r"\1<redacted>",
        value,
    )
    redacted = re.sub(
        r"(?i)((?:--)?(?:uipath[_-]?access[_-]?token|access[_-]?token|"
        r"client[_-]?secret|password)\s*(?:=|:|\s)\s*)"
        r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
        r"\1<redacted>",
        redacted,
    )
    return redacted


def _redact_command(argv: Sequence[str]) -> tuple[str, ...]:
    sensitive_flags = {
        "--client-secret",
        "--password",
        "--token",
        "--access-token",
    }
    safe: list[str] = []
    redact_next = False
    for raw_part in argv:
        part = str(raw_part)
        if redact_next:
            safe.append("<redacted>")
            redact_next = False
            continue
        safe.append(redact_sensitive_text(part))
        if part.lower() in sensitive_flags:
            redact_next = True
    return tuple(safe)


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _lookup(
    value: Mapping[str, Any],
    *names: str,
    default: Any = _NO_DEFAULT,
) -> Any:
    normalized = {_normalize_key(str(key)): item for key, item in value.items()}
    for name in names:
        key = _normalize_key(name)
        if key in normalized:
            return normalized[key]
    if default is not _NO_DEFAULT:
        return default
    raise DriftDetectedError(f"required tenant property is missing: {names[0]}")


def _mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CommandExecutionError(f"{context} returned a non-object JSON payload")
    return value


def _rows(value: Any, context: str) -> list[Mapping[str, Any]]:
    if isinstance(value, list):
        rows = value
    elif isinstance(value, Mapping):
        rows = _lookup(value, "items", "records", default=[])
    else:
        raise CommandExecutionError(f"{context} returned an invalid collection")
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise CommandExecutionError(f"{context} returned an invalid item collection")
    return list(rows)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    if value in {0, 1}:
        return bool(value)
    raise ValueError(f"not a boolean: {value!r}")


def _equivalent(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool):
        try:
            return _as_bool(actual) is expected
        except (TypeError, ValueError):
            return False
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        try:
            return Decimal(str(actual)) == Decimal(str(expected))
        except (InvalidOperation, TypeError, ValueError):
            return False
    if expected is None:
        return actual is None or actual == ""
    return str(actual) == str(expected)


def _type_token(value: Any) -> str:
    if isinstance(value, Mapping):
        value = _lookup(value, "name", "type", "dataType", default="")
    return _normalize_key(str(value)).upper()


def _field_value(field: Mapping[str, Any], *names: str, default: Any = _MISSING) -> Any:
    direct = _lookup(field, *names, default=_MISSING)
    if direct is not _MISSING:
        return direct
    field_type = _lookup(field, "fieldDataType", "dataType", default={})
    if isinstance(field_type, Mapping):
        nested = _lookup(field_type, *names, default=_MISSING)
        if nested is not _MISSING:
            return nested
    if default is not _MISSING:
        return default
    raise DriftDetectedError(f"required Data Fabric field property is missing: {names[0]}")


class _UiPathCli:
    def __init__(self, runner: CommandRunner) -> None:
        self._runner = runner

    def execute_json(self, argv: Sequence[str]) -> Any:
        command = tuple(str(part) for part in argv)
        result = self._runner.run(command)
        safe_command = " ".join(_redact_command(command))
        if result.exit_code != 0:
            details = redact_sensitive_text(result.stderr or result.stdout or "no output")
            raise CommandExecutionError(
                f"uip command failed ({result.exit_code}): {safe_command}: {details}"
            )
        try:
            envelope = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            details = redact_sensitive_text(result.stdout[:500])
            raise CommandExecutionError(
                f"uip command returned invalid JSON: {safe_command}: {details}"
            ) from exc
        if not isinstance(envelope, Mapping):
            raise CommandExecutionError(
                f"uip command returned a non-object envelope: {safe_command}"
            )
        logical_result = _lookup(envelope, "Result", default="Success")
        if str(logical_result).lower() != "success":
            details = _lookup(
                envelope,
                "Message",
                "Instructions",
                default=result.stderr or result.stdout,
            )
            raise CommandExecutionError(
                f"uip command reported failure: {safe_command}: "
                f"{redact_sensitive_text(str(details))}"
            )
        return _lookup(envelope, "Data", default=None)


class Provisioner:
    """Plan or apply additive desired state; any detected drift stops the run."""

    def __init__(self, manifest: PlatformManifest, runner: CommandRunner) -> None:
        self.manifest = manifest
        self._client = _UiPathCli(runner)

    def plan_assuming_clean(self) -> ProvisioningPlan:
        """Render a zero-I/O plan for a hypothetical empty tenant."""
        return ProvisioningPlan(
            actions=tuple(self._all_create_actions()),
            target=None,
            assumed_clean=True,
            requires_schema_approval=self.manifest.schema_approval.required,
        )

    def plan(self, target: TenantTarget) -> ProvisioningPlan:
        self._verify_target(target)
        actions: list[ProvisioningAction] = []

        entity_ids = self._plan_entities(actions)
        self._plan_gate_settings(actions, entity_ids)
        folder_exists = self._plan_folder(actions)
        self._plan_queues(actions, folder_exists)
        self._plan_assets(actions, folder_exists)

        return ProvisioningPlan(
            actions=tuple(actions),
            target=target,
            assumed_clean=False,
            requires_schema_approval=self.manifest.schema_approval.required,
        )

    def apply(
        self,
        target: TenantTarget,
        *,
        confirm: bool,
        approve_schema_mappings: bool,
    ) -> ApplyReport:
        if not confirm:
            raise ApprovalRequiredError(
                "live apply requires --confirm after reviewing a dry-run plan"
            )
        if self.manifest.schema_approval.required and not approve_schema_mappings:
            raise ApprovalRequiredError(
                "live apply requires explicit approval of schema mappings"
            )

        initial_plan = self.plan(target)
        for action in initial_plan.actions:
            if any(part in {"update", "delete"} for part in action.command):
                raise ProvisioningError("non-additive action refused")
            command = self._resolve_command(action.command)
            self._client.execute_json(command)

        verification_plan = self.plan(target)
        if verification_plan.create_count:
            missing = ", ".join(action.identifier for action in verification_plan.actions)
            raise ProvisioningError(
                f"post-apply verification still requires creates: {missing}"
            )
        return ApplyReport(
            initial_plan=initial_plan,
            verification_plan=verification_plan,
            created_count=initial_plan.create_count,
        )

    def _verify_target(self, target: TenantTarget) -> None:
        data = _mapping(
            self._client.execute_json(("uip", "login", "status", "--output", "json")),
            "uip login status",
        )
        status = str(_lookup(data, "Status", default=""))
        if status.lower() != "logged in":
            raise TargetMismatchError("uip is not logged in")
        active_base_url = str(_lookup(data, "BaseUrl", default="")).strip()
        if not active_base_url:
            active_base_url = str(_lookup(data, "Authority", default="")).strip()
        if not active_base_url:
            raise TargetMismatchError(
                "uip login status is missing required BaseUrl/Authority"
            )
        try:
            active = TenantTarget(
                base_url=active_base_url,
                organization=str(_lookup(data, "Organization", default="")),
                tenant=str(_lookup(data, "Tenant", default="")),
            )
        except ValueError as exc:
            raise TargetMismatchError(
                "uip login status contains an invalid BaseUrl/Authority or target name"
            ) from exc
        if active != target:
            raise TargetMismatchError(
                f"active UiPath target {active.display_name} does not match expected "
                f"{target.display_name}"
            )

    def _plan_entities(self, actions: list[ProvisioningAction]) -> dict[str, str]:
        data = self._client.execute_json(
            ("uip", "df", "entities", "list", "--native-only", "--output", "json")
        )
        rows = _rows(data, "uip df entities list")
        entity_ids: dict[str, str] = {}
        for expected in self.manifest.entities:
            existing = self._one_named(rows, expected.physical_name, "Data Fabric entity")
            if existing is None:
                actions.append(self._entity_action(expected))
                continue
            entity_id = str(_lookup(existing, "id", "key"))
            detail = _mapping(
                self._client.execute_json(
                    (
                        "uip",
                        "df",
                        "entities",
                        "get",
                        entity_id,
                        "--output",
                        "json",
                    )
                ),
                f"Data Fabric entity {expected.physical_name}",
            )
            self._assert_entity_matches(expected, detail)
            entity_ids[expected.contract] = entity_id
        return entity_ids

    def _plan_gate_settings(
        self,
        actions: list[ProvisioningAction],
        entity_ids: Mapping[str, str],
    ) -> None:
        contract = self.manifest.gate_settings.entity_contract
        entity = self.manifest.entity_for_contract(contract)
        entity_id = entity_ids.get(contract)
        for seed in self.manifest.gate_settings.seeds:
            if entity_id is None:
                actions.append(self._seed_action(entity, seed.model_dump(mode="json")))
                continue
            query = {
                "filterGroup": {
                    "logicalOperator": 0,
                    "queryFilters": [
                        {
                            "fieldName": "customer_id",
                            "operator": "=",
                            "value": seed.customer_id,
                        }
                    ],
                }
            }
            data = self._client.execute_json(
                (
                    "uip",
                    "df",
                    "records",
                    "query",
                    entity_id,
                    "--body",
                    _json_argument(query),
                    "--limit",
                    "2",
                    "--output",
                    "json",
                )
            )
            records = _rows(data, f"gate settings for {seed.customer_id}")
            if len(records) > 1:
                raise DriftDetectedError(
                    f"duplicate CustomerGateSettings records for {seed.customer_id}"
                )
            if not records:
                actions.append(self._seed_action(entity, seed.model_dump(mode="json")))
                continue
            self._assert_seed_matches(seed.model_dump(mode="json"), records[0])

    def _plan_folder(self, actions: list[ProvisioningAction]) -> bool:
        expected = self.manifest.orchestrator.folder
        data = self._client.execute_json(
            (
                "uip",
                "or",
                "folders",
                "list",
                "--all",
                "--name",
                expected.name,
                "--output",
                "json",
            )
        )
        rows = _rows(data, "uip or folders list")
        matches = [
            row
            for row in rows
            if str(_lookup(row, "path", default="")).lower() == expected.path.lower()
        ]
        if len(matches) > 1:
            raise DriftDetectedError(f"duplicate Orchestrator folder {expected.path}")
        if not matches:
            actions.append(self._folder_action(expected))
            return False
        detail = _mapping(
            self._client.execute_json(
                (
                    "uip",
                    "or",
                    "folders",
                    "get",
                    expected.path,
                    "--output",
                    "json",
                )
            ),
            f"Orchestrator folder {expected.path}",
        )
        self._assert_folder_matches(expected, detail)
        return True

    def _plan_queues(
        self,
        actions: list[ProvisioningAction],
        folder_exists: bool,
    ) -> None:
        if not folder_exists:
            actions.extend(self._queue_action(queue) for queue in self.manifest.orchestrator.queues)
            return
        folder_path = self.manifest.orchestrator.folder.path
        data = self._client.execute_json(
            (
                "uip",
                "or",
                "queues",
                "list",
                "--folder-path",
                folder_path,
                "--all-fields",
                "--output",
                "json",
            )
        )
        rows = _rows(data, "uip or queues list")
        for expected in self.manifest.orchestrator.queues:
            existing = self._one_named(rows, expected.name, "Orchestrator queue")
            if existing is None:
                actions.append(self._queue_action(expected))
                continue
            key = str(_lookup(existing, "key"))
            detail = _mapping(
                self._client.execute_json(
                    (
                        "uip",
                        "or",
                        "queues",
                        "get",
                        key,
                        "--all-fields",
                        "--output",
                        "json",
                    )
                ),
                f"Orchestrator queue {expected.name}",
            )
            self._assert_queue_matches(expected, detail)

    def _plan_assets(
        self,
        actions: list[ProvisioningAction],
        folder_exists: bool,
    ) -> None:
        if not folder_exists:
            actions.extend(self._asset_action(asset) for asset in self.manifest.orchestrator.assets)
            return
        folder_path = self.manifest.orchestrator.folder.path
        data = self._client.execute_json(
            (
                "uip",
                "or",
                "assets",
                "list",
                "--folder-path",
                folder_path,
                "--all-fields",
                "--output",
                "json",
            )
        )
        rows = _rows(data, "uip or assets list")
        for expected in self.manifest.orchestrator.assets:
            existing = self._one_named(rows, expected.name, "Orchestrator asset")
            if existing is None:
                actions.append(self._asset_action(expected))
                continue
            key = str(_lookup(existing, "key"))
            detail = _mapping(
                self._client.execute_json(
                    (
                        "uip",
                        "or",
                        "assets",
                        "get",
                        key,
                        "--all-fields",
                        "--output",
                        "json",
                    )
                ),
                f"Orchestrator asset {expected.name}",
            )
            self._assert_asset_matches(expected, detail)

    @staticmethod
    def _one_named(
        rows: Sequence[Mapping[str, Any]],
        desired_name: str,
        resource_kind: str,
    ) -> Mapping[str, Any] | None:
        matches = [
            row
            for row in rows
            if str(_lookup(row, "name", default="")).lower() == desired_name.lower()
        ]
        if len(matches) > 1:
            raise DriftDetectedError(f"duplicate {resource_kind} {desired_name}")
        if not matches:
            return None
        actual_name = str(_lookup(matches[0], "name"))
        if actual_name != desired_name:
            raise DriftDetectedError(
                f"{resource_kind} name drift: expected {desired_name!r}, got {actual_name!r}"
            )
        return matches[0]

    def _assert_entity_matches(
        self,
        expected: EntityDefinition,
        actual: Mapping[str, Any],
    ) -> None:
        checks = {
            "name": expected.physical_name,
            "displayName": expected.display_name,
            "description": expected.description,
            "isRbacEnabled": expected.is_rbac_enabled,
        }
        self._assert_properties(
            f"Data Fabric entity {expected.physical_name}", actual, checks
        )
        actual_fields_raw = _lookup(actual, "fields")
        if not isinstance(actual_fields_raw, list):
            raise DriftDetectedError(
                f"Data Fabric entity {expected.physical_name} has invalid fields"
            )
        actual_fields = {
            str(_field_value(field, "fieldName", "name")): field
            for field in actual_fields_raw
            if isinstance(field, Mapping)
            and _normalize_key(str(_field_value(field, "fieldName", "name")))
            not in _SYSTEM_FIELDS
        }
        expected_names = {field.physical_name for field in expected.fields}
        if set(actual_fields) != expected_names:
            raise DriftDetectedError(
                f"Data Fabric entity {expected.physical_name} field set drift"
            )
        for field in expected.fields:
            self._assert_field_matches(
                expected.physical_name,
                field,
                actual_fields[field.physical_name],
            )

    def _assert_field_matches(
        self,
        entity_name: str,
        expected: FieldDefinition,
        actual: Mapping[str, Any],
    ) -> None:
        actual_type = _field_value(actual, "type", "fieldDataType")
        if _type_token(actual_type) != _type_token(expected.field_type):
            raise DriftDetectedError(
                f"Data Fabric entity {entity_name}.{expected.physical_name} type drift"
            )
        checks: dict[str, Any] = {
            "displayName": expected.display_name,
            "description": expected.description,
            "isRequired": expected.is_required,
            "isUnique": expected.is_unique,
            "isEncrypted": expected.is_encrypted,
        }
        optional = {
            "lengthLimit": expected.length_limit,
            "minValue": expected.min_value,
            "maxValue": expected.max_value,
            "decimalPrecision": expected.decimal_precision,
            "defaultValue": expected.default_value,
        }
        checks.update({key: value for key, value in optional.items() if value is not None})
        for property_name, expected_value in checks.items():
            actual_value = _field_value(actual, property_name, default=False)
            if not _equivalent(actual_value, expected_value):
                raise DriftDetectedError(
                    f"Data Fabric entity {entity_name}.{expected.physical_name} "
                    f"{property_name} drift"
                )

    @staticmethod
    def _assert_seed_matches(
        expected: Mapping[str, Any],
        actual: Mapping[str, Any],
    ) -> None:
        customer_id = str(expected["customer_id"])
        for name, expected_value in expected.items():
            actual_value = _lookup(actual, name, default=_MISSING)
            if actual_value is _MISSING or not _equivalent(actual_value, expected_value):
                raise DriftDetectedError(
                    f"CustomerGateSettings drift for {customer_id}: {name}"
                )

    def _assert_folder_matches(
        self,
        expected: FolderDefinition,
        actual: Mapping[str, Any],
    ) -> None:
        checks = {
            "name": expected.name,
            "path": expected.path,
            "description": expected.description,
            "permissionModel": expected.permission_model,
            "feedType": expected.feed_type,
            "provisionType": expected.provision_type,
            "folderType": "Standard",
        }
        self._assert_properties(f"Orchestrator folder {expected.path}", actual, checks)

    def _assert_queue_matches(
        self,
        expected: QueueDefinition,
        actual: Mapping[str, Any],
    ) -> None:
        checks = {
            "name": expected.name,
            "description": expected.description,
            "maxNumberOfRetries": expected.max_retries,
            "acceptAutomaticallyRetry": expected.auto_retry,
            "retryAbandonedItems": expected.retry_abandoned_items,
            "enforceUniqueReference": expected.enforce_unique_reference,
            "encrypted": expected.encrypted,
            "retentionAction": expected.retention_action,
            "retentionPeriod": expected.retention_period_days,
            "staleRetentionAction": expected.stale_retention_action,
            "staleRetentionPeriod": expected.stale_retention_period_days,
        }
        self._assert_properties(f"Orchestrator queue {expected.name}", actual, checks)

    def _assert_asset_matches(
        self,
        expected: AssetDefinition,
        actual: Mapping[str, Any],
    ) -> None:
        checks = {
            "name": expected.name,
            "valueType": expected.value_type,
            "valueScope": expected.scope,
            "description": expected.description,
        }
        self._assert_properties(f"Orchestrator asset {expected.name}", actual, checks)
        actual_value = _lookup(actual, "value", default=_MISSING)
        if actual_value is _MISSING:
            type_field = {
                "Text": "stringValue",
                "Integer": "intValue",
                "Bool": "boolValue",
            }[expected.value_type]
            actual_value = _lookup(actual, type_field, default=_MISSING)
        if actual_value is _MISSING or not _equivalent(actual_value, expected.value):
            raise DriftDetectedError(
                f"Orchestrator asset {expected.name} value drift"
            )

    @staticmethod
    def _assert_properties(
        context: str,
        actual: Mapping[str, Any],
        expected: Mapping[str, Any],
    ) -> None:
        for name, expected_value in expected.items():
            actual_value = _lookup(actual, name, default=_MISSING)
            if actual_value is _MISSING or not _equivalent(actual_value, expected_value):
                raise DriftDetectedError(f"{context} {name} drift")

    def _all_create_actions(self) -> list[ProvisioningAction]:
        actions = [self._entity_action(entity) for entity in self.manifest.entities]
        settings_entity = self.manifest.entity_for_contract(
            self.manifest.gate_settings.entity_contract
        )
        actions.extend(
            self._seed_action(settings_entity, seed.model_dump(mode="json"))
            for seed in self.manifest.gate_settings.seeds
        )
        actions.append(self._folder_action(self.manifest.orchestrator.folder))
        actions.extend(
            self._queue_action(queue) for queue in self.manifest.orchestrator.queues
        )
        actions.extend(
            self._asset_action(asset) for asset in self.manifest.orchestrator.assets
        )
        return actions

    @staticmethod
    def _entity_action(entity: EntityDefinition) -> ProvisioningAction:
        return ProvisioningAction(
            resource_kind="data_fabric_entity",
            identifier=f"entity:{entity.physical_name}",
            command=(
                "uip",
                "df",
                "entities",
                "create",
                entity.physical_name,
                "--body",
                _json_argument(entity.cli_body()),
                "--output",
                "json",
            ),
        )

    @staticmethod
    def _seed_action(
        entity: EntityDefinition,
        record: Mapping[str, Any],
    ) -> ProvisioningAction:
        customer_id = str(record["customer_id"])
        return ProvisioningAction(
            resource_kind="data_fabric_record",
            identifier=f"gate-settings:{customer_id}",
            command=(
                "uip",
                "df",
                "records",
                "insert",
                f"@entity:{entity.physical_name}",
                "--body",
                _json_argument(record),
                "--output",
                "json",
            ),
            metadata={"entity": entity.physical_name},
        )

    @staticmethod
    def _folder_action(folder: FolderDefinition) -> ProvisioningAction:
        return ProvisioningAction(
            resource_kind="orchestrator_folder",
            identifier=f"folder:{folder.path}",
            command=(
                "uip",
                "or",
                "folders",
                "create",
                folder.name,
                "--description",
                folder.description,
                "--permission-model",
                folder.permission_model,
                "--feed-type",
                folder.feed_type,
                "--provision-type",
                folder.provision_type,
                "--output",
                "json",
            ),
        )

    def _queue_action(self, queue: QueueDefinition) -> ProvisioningAction:
        command = [
            "uip",
            "or",
            "queues",
            "create",
            queue.name,
            "--folder-path",
            self.manifest.orchestrator.folder.path,
            "--description",
            queue.description,
            "--max-retries",
            str(queue.max_retries),
            "--auto-retry" if queue.auto_retry else "--no-auto-retry",
            (
                "--retry-abandoned-items"
                if queue.retry_abandoned_items
                else "--no-retry-abandoned-items"
            ),
            (
                "--enforce-unique-reference"
                if queue.enforce_unique_reference
                else "--no-enforce-unique-reference"
            ),
        ]
        if queue.encrypted:
            command.append("--encrypted")
        command.extend(
            [
                "--retention-action",
                queue.retention_action,
                "--retention-period",
                str(queue.retention_period_days),
                "--stale-retention-action",
                queue.stale_retention_action,
                "--stale-retention-period",
                str(queue.stale_retention_period_days),
                "--output",
                "json",
            ]
        )
        return ProvisioningAction(
            resource_kind="orchestrator_queue",
            identifier=f"queue:{queue.name}",
            command=tuple(command),
        )

    def _asset_action(self, asset: AssetDefinition) -> ProvisioningAction:
        value = str(asset.value)
        if isinstance(asset.value, bool):
            value = str(asset.value).lower()
        return ProvisioningAction(
            resource_kind="orchestrator_asset",
            identifier=f"asset:{asset.name}",
            command=(
                "uip",
                "or",
                "assets",
                "create",
                asset.name,
                value,
                "--folder-path",
                self.manifest.orchestrator.folder.path,
                "--type",
                asset.value_type,
                "--scope",
                asset.scope,
                "--description",
                asset.description,
                "--output",
                "json",
            ),
        )

    def _resolve_command(self, command: Sequence[str]) -> tuple[str, ...]:
        resolved = list(command)
        for index, part in enumerate(resolved):
            if not part.startswith("@entity:"):
                continue
            physical_name = part.split(":", 1)[1]
            resolved[index] = self._discover_entity_id(physical_name)
        return tuple(resolved)

    def _discover_entity_id(self, physical_name: str) -> str:
        data = self._client.execute_json(
            ("uip", "df", "entities", "list", "--native-only", "--output", "json")
        )
        existing = self._one_named(
            _rows(data, "uip df entities list"),
            physical_name,
            "Data Fabric entity",
        )
        if existing is None:
            raise ProvisioningError(
                f"cannot seed missing Data Fabric entity {physical_name}"
            )
        return str(_lookup(existing, "id", "key"))


def _json_argument(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
