from __future__ import annotations

import json
import sys
from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

import pytest

from src.platform.manifest import PlatformManifest, load_manifest
from src.platform.provisioner import (
    ApprovalRequiredError,
    CommandExecutionError,
    CommandResult,
    DriftDetectedError,
    Provisioner,
    SubprocessCommandRunner,
    TargetMismatchError,
    TenantTarget,
    redact_sensitive_text,
)


TARGET = TenantTarget(
    base_url="https://staging.uipath.com",
    organization="approved-org",
    tenant="approved-tenant",
)


def _success(data: Any, code: str = "OK") -> CommandResult:
    return CommandResult(
        exit_code=0,
        stdout=json.dumps({"Result": "Success", "Code": code, "Data": data}),
        stderr="",
    )


def _option(argv: Sequence[str], name: str) -> str:
    return argv[argv.index(name) + 1]


@dataclass
class FakeUiPathRunner:
    """Stateful boundary fake for the external uip process and tenant."""

    base_url: str | None = TARGET.base_url
    organization: str = TARGET.organization
    tenant: str = TARGET.tenant
    entities: dict[str, dict[str, Any]] = field(default_factory=dict)
    records: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    folder: dict[str, Any] | None = None
    queues: dict[str, dict[str, Any]] = field(default_factory=dict)
    assets: dict[str, dict[str, Any]] = field(default_factory=dict)
    commands: list[tuple[str, ...]] = field(default_factory=list)
    mutations: list[tuple[str, ...]] = field(default_factory=list)
    fail_prefix: tuple[str, ...] | None = None

    def run(self, argv: Sequence[str]) -> CommandResult:
        command = tuple(str(part) for part in argv)
        self.commands.append(command)
        if self.fail_prefix and command[: len(self.fail_prefix)] == self.fail_prefix:
            return CommandResult(
                exit_code=17,
                stdout="",
                stderr=(
                    "UIPATH_ACCESS_TOKEN=top-secret-token "
                    "Authorization: Bearer bearer-secret "
                    "--client-secret cli-secret upstream unavailable"
                ),
            )

        if command[:3] == ("uip", "login", "status"):
            return _success(
                {
                    "Status": "Logged in",
                    **({"BaseUrl": self.base_url} if self.base_url is not None else {}),
                    "Organization": self.organization,
                    "Tenant": self.tenant,
                },
                "LoginStatus",
            )
        if command[:4] == ("uip", "df", "entities", "list"):
            return _success(
                [
                    {
                        "id": entity["id"],
                        "name": entity["name"],
                        "displayName": entity["displayName"],
                        "source": "Native",
                    }
                    for entity in self.entities.values()
                ]
            )
        if command[:4] == ("uip", "df", "entities", "get"):
            entity_id = command[4]
            return _success(
                next(entity for entity in self.entities.values() if entity["id"] == entity_id)
            )
        if command[:4] == ("uip", "df", "entities", "create"):
            self.mutations.append(command)
            name = command[4]
            body = json.loads(_option(command, "--body"))
            entity_id = f"entity-{len(self.entities) + 1}"
            self.entities[name] = {
                "id": entity_id,
                "name": name,
                "displayName": body["displayName"],
                "description": body["description"],
                "isRbacEnabled": body["isRbacEnabled"],
                "fields": deepcopy(body["fields"]),
            }
            self.records[entity_id] = []
            return _success({"ID": entity_id}, "EntityCreated")
        if command[:4] == ("uip", "df", "records", "query"):
            entity_id = command[4]
            body = json.loads(_option(command, "--body"))
            customer_id = body["filterGroup"]["queryFilters"][0]["value"]
            matches = [
                record
                for record in self.records.get(entity_id, [])
                if record.get("customer_id") == customer_id
            ]
            return _success(
                {"items": deepcopy(matches), "totalCount": len(matches), "hasNextPage": False}
            )
        if command[:4] == ("uip", "df", "records", "insert"):
            self.mutations.append(command)
            entity_id = command[4]
            body = json.loads(_option(command, "--body"))
            record = {"Id": f"record-{len(self.records[entity_id]) + 1}", **body}
            self.records[entity_id].append(record)
            return _success(record, "RecordInserted")
        if command[:4] == ("uip", "or", "folders", "list"):
            return _success([] if self.folder is None else [deepcopy(self.folder)])
        if command[:4] == ("uip", "or", "folders", "get"):
            if self.folder is None:
                return CommandResult(1, "", "folder not found")
            return _success(deepcopy(self.folder))
        if command[:4] == ("uip", "or", "folders", "create"):
            self.mutations.append(command)
            name = command[4]
            self.folder = {
                "key": "folder-1",
                "name": name,
                "path": name,
                "description": _option(command, "--description"),
                "permissionModel": _option(command, "--permission-model"),
                "feedType": _option(command, "--feed-type"),
                "provisionType": _option(command, "--provision-type"),
                "folderType": "Standard",
            }
            return _success(deepcopy(self.folder), "FolderCreated")
        if command[:4] == ("uip", "or", "queues", "list"):
            return _success(
                [{"key": queue["key"], "name": queue["name"]} for queue in self.queues.values()]
            )
        if command[:4] == ("uip", "or", "queues", "get"):
            queue_key = command[4]
            return _success(
                deepcopy(next(queue for queue in self.queues.values() if queue["key"] == queue_key))
            )
        if command[:4] == ("uip", "or", "queues", "create"):
            self.mutations.append(command)
            name = command[4]
            self.queues[name] = {
                "key": f"queue-{name}",
                "name": name,
                "description": _option(command, "--description"),
                "maxNumberOfRetries": int(_option(command, "--max-retries")),
                "acceptAutomaticallyRetry": "--auto-retry" in command,
                "retryAbandonedItems": "--retry-abandoned-items" in command,
                "enforceUniqueReference": "--enforce-unique-reference" in command,
                "encrypted": "--encrypted" in command,
                "retentionAction": _option(command, "--retention-action"),
                "retentionPeriod": int(_option(command, "--retention-period")),
                "staleRetentionAction": _option(command, "--stale-retention-action"),
                "staleRetentionPeriod": int(_option(command, "--stale-retention-period")),
            }
            return _success(deepcopy(self.queues[name]), "QueueCreated")
        if command[:4] == ("uip", "or", "assets", "list"):
            return _success(
                [{"key": asset["key"], "name": asset["name"]} for asset in self.assets.values()]
            )
        if command[:4] == ("uip", "or", "assets", "get"):
            asset_key = command[4]
            return _success(
                deepcopy(next(asset for asset in self.assets.values() if asset["key"] == asset_key))
            )
        if command[:4] == ("uip", "or", "assets", "create"):
            self.mutations.append(command)
            name, value = command[4], command[5]
            value_type = _option(command, "--type")
            parsed_value: str | int | bool = value
            if value_type == "Integer":
                parsed_value = int(value)
            elif value_type == "Bool":
                parsed_value = value.lower() == "true"
            self.assets[name] = {
                "key": f"asset-{name}",
                "name": name,
                "valueType": value_type,
                "valueScope": _option(command, "--scope"),
                "value": parsed_value,
                "description": _option(command, "--description"),
            }
            return _success(deepcopy(self.assets[name]), "AssetCreated")
        raise AssertionError(f"unexpected uip command: {command!r}")


@pytest.fixture
def manifest() -> PlatformManifest:
    return load_manifest()


def _provision_clean_tenant(
    manifest: PlatformManifest,
) -> tuple[Provisioner, FakeUiPathRunner]:
    runner = FakeUiPathRunner()
    provisioner = Provisioner(manifest, runner)
    report = provisioner.apply(
        TARGET,
        confirm=True,
        approve_schema_mappings=True,
    )
    assert report.created_count > 0
    return provisioner, runner


def test_offline_clean_plan_contains_every_required_create_without_running_uip(
    manifest: PlatformManifest,
) -> None:
    runner = FakeUiPathRunner()
    plan = Provisioner(manifest, runner).plan_assuming_clean()

    assert plan.assumed_clean is True
    assert plan.requires_schema_approval is True
    assert plan.create_count == (
        len(manifest.entities)
        + len(manifest.gate_settings.seeds)
        + 1
        + len(manifest.orchestrator.queues)
        + len(manifest.orchestrator.assets)
    )
    assert {action.resource_kind for action in plan.actions} == {
        "data_fabric_entity",
        "data_fabric_record",
        "orchestrator_folder",
        "orchestrator_queue",
        "orchestrator_asset",
    }
    assert runner.mutations == []
    assert runner.commands == []


def test_live_plan_discovers_before_create_and_performs_no_mutation(
    manifest: PlatformManifest,
) -> None:
    runner = FakeUiPathRunner()
    plan = Provisioner(manifest, runner).plan(TARGET)

    assert plan.create_count > 0
    assert runner.mutations == []


def test_apply_is_idempotent_and_verifies_a_zero_create_second_plan(
    manifest: PlatformManifest,
) -> None:
    runner = FakeUiPathRunner()
    provisioner = Provisioner(manifest, runner)

    first = provisioner.apply(TARGET, confirm=True, approve_schema_mappings=True)
    mutations_after_first = len(runner.mutations)
    second = provisioner.apply(TARGET, confirm=True, approve_schema_mappings=True)

    assert first.created_count == first.initial_plan.create_count
    assert first.verification_plan.create_count == 0
    assert second.created_count == 0
    assert second.verification_plan.create_count == 0
    assert len(runner.mutations) == mutations_after_first


def test_entity_comparison_accepts_the_cli_nested_field_data_type_shape(
    manifest: PlatformManifest,
) -> None:
    provisioner, runner = _provision_clean_tenant(manifest)
    constraint_names = {
        "lengthLimit",
        "minValue",
        "maxValue",
        "decimalPrecision",
        "defaultValue",
    }
    for entity in runner.entities.values():
        for field_definition in entity["fields"]:
            field_definition["name"] = field_definition.pop("fieldName")
            field_data_type = {"name": field_definition.pop("type")}
            for constraint in constraint_names:
                if constraint in field_definition:
                    field_data_type[constraint] = field_definition.pop(constraint)
            field_definition["fieldDataType"] = field_data_type

    plan = provisioner.plan(TARGET)

    assert plan.create_count == 0


def test_partial_state_plans_and_creates_only_missing_resources(
    manifest: PlatformManifest,
) -> None:
    provisioner, runner = _provision_clean_tenant(manifest)
    settings_entity = runner.entities["CustomerGateSettings"]
    runner.records[settings_entity["id"]] = [
        record
        for record in runner.records[settings_entity["id"]]
        if record["customer_id"] != "CUST-1042"
    ]
    del runner.queues["PaymentEscalations"]
    del runner.assets["AgentMaxIterations"]

    plan = provisioner.plan(TARGET)

    assert {action.identifier for action in plan.actions} == {
        "gate-settings:CUST-1042",
        "queue:PaymentEscalations",
        "asset:AgentMaxIterations",
    }
    report = provisioner.apply(TARGET, confirm=True, approve_schema_mappings=True)
    assert report.created_count == 3
    assert report.verification_plan.create_count == 0


def _drift_entity(runner: FakeUiPathRunner) -> None:
    runner.entities["PaymentCase"]["fields"][0]["type"] = "INTEGER"


def _drift_seed(runner: FakeUiPathRunner) -> None:
    entity_id = runner.entities["CustomerGateSettings"]["id"]
    runner.records[entity_id][0]["minimum_confidence"] = 0.12


def _drift_folder(runner: FakeUiPathRunner) -> None:
    assert runner.folder is not None
    runner.folder["permissionModel"] = "InheritFromTenant"


def _drift_queue(runner: FakeUiPathRunner) -> None:
    runner.queues["PaymentEffectRequests"]["maxNumberOfRetries"] = 99


def _drift_asset(runner: FakeUiPathRunner) -> None:
    runner.assets["AgentTokenBudget"]["value"] = 1


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (_drift_entity, "PaymentCase"),
        (_drift_seed, "CUST-1042"),
        (_drift_folder, "TreasuryPayments"),
        (_drift_queue, "PaymentEffectRequests"),
        (_drift_asset, "AgentTokenBudget"),
    ],
)
def test_drift_fails_closed_without_delete_update_or_create(
    manifest: PlatformManifest,
    mutate: Callable[[FakeUiPathRunner], None],
    match: str,
) -> None:
    provisioner, runner = _provision_clean_tenant(manifest)
    mutate(runner)
    mutations_before_drift = len(runner.mutations)

    with pytest.raises(DriftDetectedError, match=match):
        provisioner.apply(TARGET, confirm=True, approve_schema_mappings=True)

    assert len(runner.mutations) == mutations_before_drift
    assert all("update" not in command and "delete" not in command for command in runner.mutations)


def test_apply_requires_explicit_confirmation_and_mapping_approval(
    manifest: PlatformManifest,
) -> None:
    runner = FakeUiPathRunner()
    provisioner = Provisioner(manifest, runner)

    with pytest.raises(ApprovalRequiredError, match="--confirm"):
        provisioner.apply(TARGET, confirm=False, approve_schema_mappings=True)
    with pytest.raises(ApprovalRequiredError, match="schema mappings"):
        provisioner.apply(TARGET, confirm=True, approve_schema_mappings=False)

    assert runner.mutations == []


def test_target_mismatch_stops_before_tenant_discovery_or_mutation(
    manifest: PlatformManifest,
) -> None:
    runner = FakeUiPathRunner(organization="wrong-org", tenant="wrong-tenant")

    with pytest.raises(TargetMismatchError, match="wrong-org/wrong-tenant"):
        Provisioner(manifest, runner).plan(TARGET)

    assert runner.mutations == []


def test_same_named_org_and_tenant_on_production_base_url_fails_closed(
    manifest: PlatformManifest,
) -> None:
    runner = FakeUiPathRunner(base_url="https://cloud.uipath.com")

    with pytest.raises(TargetMismatchError) as captured:
        Provisioner(manifest, runner).plan(TARGET)

    message = str(captured.value)
    assert "https://cloud.uipath.com" in message
    assert "https://staging.uipath.com" in message
    assert runner.commands == [("uip", "login", "status", "--output", "json")]
    assert runner.mutations == []


def test_base_url_comparison_normalizes_host_case_and_trailing_slash(
    manifest: PlatformManifest,
) -> None:
    runner = FakeUiPathRunner(base_url="HTTPS://STAGING.UIPATH.COM/")

    plan = Provisioner(manifest, runner).plan(TARGET)

    assert plan.create_count > 0
    assert runner.mutations == []


def test_missing_login_status_base_url_fails_closed_before_discovery(
    manifest: PlatformManifest,
) -> None:
    runner = FakeUiPathRunner(base_url=None)

    with pytest.raises(TargetMismatchError, match="BaseUrl"):
        Provisioner(manifest, runner).plan(TARGET)

    assert runner.commands == [("uip", "login", "status", "--output", "json")]
    assert runner.mutations == []


def test_login_status_authority_is_accepted_as_a_base_url_fallback(
    manifest: PlatformManifest,
) -> None:
    class AuthorityOnlyRunner(FakeUiPathRunner):
        def run(self, argv: Sequence[str]) -> CommandResult:
            command = tuple(argv)
            if command[:3] == ("uip", "login", "status"):
                self.commands.append(command)
                return _success(
                    {
                        "Status": "Logged in",
                        "BaseUrl": "",
                        "Authority": "HTTPS://STAGING.UIPATH.COM/",
                        "Organization": self.organization,
                        "Tenant": self.tenant,
                    },
                    "LoginStatus",
                )
            return super().run(argv)

    runner = AuthorityOnlyRunner(base_url=None)

    plan = Provisioner(manifest, runner).plan(TARGET)

    assert plan.create_count > 0
    assert runner.mutations == []


def test_logged_out_status_fails_closed_before_any_tenant_discovery() -> None:
    class LoggedOutRunner(FakeUiPathRunner):
        def run(self, argv: Sequence[str]) -> CommandResult:
            command = tuple(argv)
            self.commands.append(command)
            if command[:3] == ("uip", "login", "status"):
                return _success(
                    {"Status": "Not logged in", "Organization": "", "Tenant": ""},
                    "LoginStatus",
                )
            raise AssertionError(f"tenant discovery unexpectedly ran: {command!r}")

    runner = LoggedOutRunner()

    with pytest.raises(TargetMismatchError, match="not logged in"):
        Provisioner(load_manifest(), runner).plan(TARGET)

    assert runner.commands == [
        ("uip", "login", "status", "--output", "json")
    ]


def test_uip_errors_are_redacted_and_abort_without_mutation(
    manifest: PlatformManifest,
) -> None:
    runner = FakeUiPathRunner(fail_prefix=("uip", "df", "entities", "list"))

    with pytest.raises(CommandExecutionError) as captured:
        Provisioner(manifest, runner).plan(TARGET)

    message = str(captured.value)
    assert "top-secret-token" not in message
    assert "bearer-secret" not in message
    assert "cli-secret" not in message
    assert message.count("<redacted>") >= 3
    assert runner.mutations == []


def test_logical_failure_envelopes_are_treated_as_command_errors(
    manifest: PlatformManifest,
) -> None:
    class LogicalFailureRunner(FakeUiPathRunner):
        def run(self, argv: Sequence[str]) -> CommandResult:
            if tuple(argv[:4]) == ("uip", "df", "entities", "list"):
                return CommandResult(
                    0,
                    json.dumps(
                        {
                            "Result": "Failure",
                            "Message": "Authorization: Bearer logical-secret",
                        }
                    ),
                    "",
                )
            return super().run(argv)

    with pytest.raises(CommandExecutionError) as captured:
        Provisioner(manifest, LogicalFailureRunner()).plan(TARGET)

    assert "logical-secret" not in str(captured.value)


def test_redaction_handles_environment_flags_and_authorization_headers() -> None:
    raw = (
        "UIPATH_ACCESS_TOKEN=abc123 --client-secret xyz789 "
        "password: hunter2 Authorization: Bearer eyJhbGciOi"
    )

    redacted = redact_sensitive_text(raw)

    for secret in ("abc123", "xyz789", "hunter2", "eyJhbGciOi"):
        assert secret not in redacted
    assert redacted.count("<redacted>") >= 4


def test_subprocess_runner_executes_an_argument_vector_cross_platform() -> None:
    result = SubprocessCommandRunner().run(
        [sys.executable, "-c", "import json; print(json.dumps({'ok': True}))"]
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"ok": True}


def test_subprocess_runner_resolves_npm_command_shims_without_a_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.platform.provisioner.shutil.which",
        lambda executable: sys.executable if executable == "uip" else executable,
    )

    result = SubprocessCommandRunner().run(
        ["uip", "-c", "import json; print(json.dumps({'resolved': True}))"]
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"resolved": True}
