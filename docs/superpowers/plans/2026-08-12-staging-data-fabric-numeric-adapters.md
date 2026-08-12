# Staging Data Fabric Numeric Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve the logical Python contracts while provisioning the five approved numeric fields as staging-supported Data Fabric `DECIMAL` fields, with lossless fail-closed conversion in both directions.

**Architecture:** Alpha owns a tenant-neutral physical schema manifest and explicit record adapters. The manifest will declare the five reviewed logical-type-to-physical-type mappings, validate them against an immutable approval set, and emit `DECIMAL` definitions with precision 0 or 3. The record adapter will use that metadata to validate and convert values before writes and after reads; contracts and downstream components continue to see `int`, `float`, or `None` exactly as before.

**Tech Stack:** Python 3.11+, Pydantic 2, `decimal.Decimal`, pytest, UiPath CLI 1.196.0, UiPath Data Fabric, Git/GitHub.

## Global Constraints

- Work only on branch `alpha` in Alpha-owned paths: `src/platform/**` and its documentation/tests. Do not edit logical contracts, gates, Bravo agent/tool paths, or Charlie orchestration/app paths.
- Keep `PaymentCase`, `CounterpartyHistory`, and `PolicyConfig` unchanged. This is a physical persistence adapter, not a contract change.
- The approved numeric mapping set is closed: four logical integers use `DECIMAL` precision 0 and `PaymentCase.cycle_time` uses `DECIMAL` precision 3.
- Preserve the three approved name mappings: `PaymentCase.status`, `Evidence.type`, and `Evidence.timestamp`.
- Reject booleans, fractional logical integers, fractional physical values for integer fields, non-finite values, values outside manifest bounds, and values exceeding declared precision. Never round or truncate.
- Keep provisioning create-only, discover-before-create, drift-detecting, idempotent, and gated by `--confirm --approve-schema-mappings`.
- Use test-driven development for Tasks 1 and 2. Observe each targeted test fail for the intended reason before adding production code.
- Never include staging tokens, OAuth secrets, tenant IDs, or other credentials in Git. The manifest remains tenant-neutral.

---

## Task 1: Declare and validate the approved physical numeric schema

**Files:**

- Modify: `src/platform/tests/test_manifest.py`
- Modify: `src/platform/tests/test_provisioner.py`
- Modify: `src/platform/manifest.py`
- Modify: `src/platform/platform.manifest.json`

### 1.1 Add the failing manifest tests

- [ ] In `src/platform/tests/test_manifest.py`, add the exact reviewed approval set near `EXPECTED_MAPPINGS`:

```python
EXPECTED_NUMERIC_TYPE_ADAPTERS = {
    "PaymentCase.touch_count": {
        "logical_type": "int",
        "physical_type": "DECIMAL",
        "decimal_precision": 0,
    },
    "PaymentCase.cycle_time": {
        "logical_type": "float",
        "physical_type": "DECIMAL",
        "decimal_precision": 3,
    },
    "CounterpartyHistory.times_seen": {
        "logical_type": "int",
        "physical_type": "DECIMAL",
        "decimal_precision": 0,
    },
    "CounterpartyHistory.times_repaired": {
        "logical_type": "int",
        "physical_type": "DECIMAL",
        "decimal_precision": 0,
    },
    "PolicyConfig.cutoff_escalation_minutes": {
        "logical_type": "int",
        "physical_type": "DECIMAL",
        "decimal_precision": 0,
    },
}
```

- [ ] Add a test that proves the checked-in schema approval metadata and emitted CLI field definitions match that set exactly:

```python
def test_approved_numeric_type_adapters_emit_exact_decimal_definitions() -> None:
    manifest = load_manifest()
    declared = {
        name: adapter.model_dump()
        for name, adapter in manifest.schema_approval.logical_to_physical_types.items()
    }

    assert declared == EXPECTED_NUMERIC_TYPE_ADAPTERS
    for qualified_name, approval in EXPECTED_NUMERIC_TYPE_ADAPTERS.items():
        contract, logical_name = qualified_name.split(".", maxsplit=1)
        entity = manifest.entity_for_contract(contract)
        field = next(item for item in entity.fields if item.logical_name == logical_name)
        definition = field.cli_definition()

        assert definition["type"] == approval["physical_type"]
        assert definition["decimalPrecision"] == approval["decimal_precision"]
```

- [ ] Add two fail-closed mutation tests: one removes `PaymentCase.touch_count` from `logical_to_physical_types`; the other changes its approved precision from 0 to 3. Both must call `load_manifest(candidate)` and assert `ManifestValidationError` with `numeric type adapters` in the message.

```python
@pytest.mark.parametrize("mutation", ["missing", "precision_drift"])
def test_loader_rejects_unapproved_numeric_type_adapter_metadata(
    tmp_path: Path,
    mutation: str,
) -> None:
    document = json.loads(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    mappings = document["schema_approval"]["logical_to_physical_types"]
    if mutation == "missing":
        mappings.pop("PaymentCase.touch_count")
    else:
        mappings["PaymentCase.touch_count"]["decimal_precision"] = 3
    candidate = tmp_path / "manifest.json"
    candidate.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ManifestValidationError, match="numeric type adapters"):
        load_manifest(candidate)
```

- [ ] In `src/platform/tests/test_provisioner.py`, strengthen the clean-tenant acceptance check with `assert plan.create_count == 28`. This guards the approved resource inventory while leaving the existing dynamic count assertion intact.

### 1.2 Run the tests and confirm the intended failure

- [ ] Run:

```powershell
uv run --with-requirements requirements-dev.txt python -m pytest `
  src/platform/tests/test_manifest.py `
  src/platform/tests/test_provisioner.py::test_offline_clean_plan_contains_every_required_create_without_running_uip `
  -v
```

Expected: the new manifest test fails because `SchemaApproval` has no `logical_to_physical_types` field and the checked-in manifest still emits `INTEGER`/`DOUBLE`. Existing unrelated tests remain green.

### 1.3 Add the typed schema-approval model and fail-closed validation

- [ ] In `src/platform/manifest.py`, add a frozen model immediately before `SchemaApproval`:

```python
class NumericTypeAdapter(ManifestModel):
    logical_type: Literal["int", "float"]
    physical_type: Literal["DECIMAL"]
    decimal_precision: int = Field(ge=0)


class SchemaApproval(ManifestModel):
    required: bool
    reason: str
    logical_to_physical: dict[str, str]
    logical_to_physical_types: dict[str, NumericTypeAdapter]
```

- [ ] Add the immutable approval set in `src/platform/manifest.py`. Use the same five keys and values as `EXPECTED_NUMERIC_TYPE_ADAPTERS`; name it `_APPROVED_NUMERIC_TYPE_ADAPTERS`. This deliberate code/manifest duplication is the fail-closed review boundary: changing a physical adapter requires a reviewed code change as well as a JSON edit.

- [ ] Extend `_validate_contract_alignment` after the existing name-mapping validation:

```python
    declared_numeric_adapters = {
        name: adapter.model_dump()
        for name, adapter in manifest.schema_approval.logical_to_physical_types.items()
    }
    if declared_numeric_adapters != _APPROVED_NUMERIC_TYPE_ADAPTERS:
        raise ManifestValidationError(
            "numeric type adapters must match the approved mapping set exactly"
        )

    fields_by_qualified_name = {
        f"{entity.contract}.{field.logical_name}": field
        for entity in manifest.entities
        for field in entity.fields
    }
    for qualified_name, adapter in (
        manifest.schema_approval.logical_to_physical_types.items()
    ):
        field = fields_by_qualified_name[qualified_name]
        if (
            field.field_type != adapter.physical_type
            or field.decimal_precision != adapter.decimal_precision
        ):
            raise ManifestValidationError(
                f"numeric type adapter does not match field definition: {qualified_name}"
            )

    if declared_numeric_adapters and not manifest.schema_approval.required:
        raise ManifestValidationError(
            "numeric type adapters require schema approval"
        )
```

Keep the existing exact validation for `logical_to_physical` name mappings.

### 1.4 Change only the five physical manifest definitions

- [ ] In `src/platform/platform.manifest.json`, extend `schema_approval` with `logical_to_physical_types` containing the five exact records from the test. Update `reason` so it mentions both reserved-name adapters and staging-supported numeric adapters.

- [ ] Replace only these field definitions:

| Contract field | Old type | New type | Precision |
|---|---:|---:|---:|
| `PaymentCase.touch_count` | `INTEGER` | `DECIMAL` | 0 |
| `PaymentCase.cycle_time` | `DOUBLE` | `DECIMAL` | 3 |
| `CounterpartyHistory.times_seen` | `INTEGER` | `DECIMAL` | 0 |
| `CounterpartyHistory.times_repaired` | `INTEGER` | `DECIMAL` | 0 |
| `PolicyConfig.cutoff_escalation_minutes` | `INTEGER` | `DECIMAL` | 0 |

Preserve each field's logical name, physical name, description, required flag, minimum, maximum, and default.

### 1.5 Run the focused tests to green

- [ ] Run the same command from Step 1.2.

Expected: all selected tests pass, the plan still contains 28 creates, and the five entity field payloads contain `type: DECIMAL` with the exact precision.

### 1.6 Commit the schema change

- [ ] Run:

```powershell
git diff --check
git status --short
git add src/platform/manifest.py `
  src/platform/platform.manifest.json `
  src/platform/tests/test_manifest.py `
  src/platform/tests/test_provisioner.py
git commit -m "fix(platform): declare staging numeric adapters"
```

Expected: one focused Alpha commit containing only schema metadata, physical field definitions, and their tests.

---

## Task 2: Implement lossless bidirectional numeric conversion

**Files:**

- Modify: `src/platform/tests/test_adapter.py`
- Modify: `src/platform/adapter.py`

### 2.1 Add failing round-trip and rejection tests

- [ ] Extend `src/platform/tests/test_adapter.py` with successful logical-to-physical and physical-to-logical cases for all five approved fields. Include numeric-string Data Fabric responses because the CLI/API may serialize decimals as strings:

```python
@pytest.mark.parametrize(
    ("contract", "logical", "physical"),
    [
        ("PaymentCase", {"touch_count": 2}, {"touch_count": 2}),
        ("PaymentCase", {"cycle_time": 12.345}, {"cycle_time": 12.345}),
        ("PaymentCase", {"cycle_time": None}, {"cycle_time": None}),
        ("CounterpartyHistory", {"times_seen": 7}, {"times_seen": 7}),
        ("CounterpartyHistory", {"times_repaired": 3}, {"times_repaired": 3}),
        (
            "PolicyConfig",
            {"cutoff_escalation_minutes": 30},
            {"cutoff_escalation_minutes": 30},
        ),
    ],
)
def test_numeric_adapters_round_trip_json_values(
    contract: str,
    logical: dict[str, object],
    physical: dict[str, object],
) -> None:
    manifest = load_manifest()

    assert logical_to_physical(manifest, contract, logical) == physical
    assert physical_to_logical(manifest, contract, physical) == logical


def test_numeric_adapters_parse_integral_and_decimal_data_fabric_strings() -> None:
    manifest = load_manifest()

    assert physical_to_logical(
        manifest,
        "PaymentCase",
        {"touch_count": "3.0", "cycle_time": "12.345"},
    ) == {"touch_count": 3, "cycle_time": 12.345}
```

- [ ] Add parameterized failures for logical integers: `True`, `1.5`, and `-1`; physical integers: `True`, `"1.5"`, and `-1`; and cycle time in both directions: `True`, `float("nan")`, `float("inf")`, `-0.001`, and `1.2345`. Each must raise `RecordAdapterError` and identify the qualified field.

```python
@pytest.mark.parametrize("value", [True, 1.5, -1])
def test_logical_integer_adapter_rejects_lossy_or_invalid_values(value: object) -> None:
    with pytest.raises(RecordAdapterError, match="PaymentCase.touch_count"):
        logical_to_physical(load_manifest(), "PaymentCase", {"touch_count": value})


@pytest.mark.parametrize("value", [True, "1.5", -1])
def test_physical_integer_adapter_rejects_fractional_or_invalid_values(
    value: object,
) -> None:
    with pytest.raises(RecordAdapterError, match="PaymentCase.touch_count"):
        physical_to_logical(load_manifest(), "PaymentCase", {"touch_count": value})


@pytest.mark.parametrize(
    "value",
    [True, float("nan"), float("inf"), -0.001, 1.2345],
)
@pytest.mark.parametrize("direction", ["logical", "physical"])
def test_cycle_time_adapter_rejects_nonfinite_negative_or_overprecision_values(
    value: object,
    direction: str,
) -> None:
    adapter = logical_to_physical if direction == "logical" else physical_to_logical
    with pytest.raises(RecordAdapterError, match="PaymentCase.cycle_time"):
        adapter(load_manifest(), "PaymentCase", {"cycle_time": value})
```

### 2.2 Run the adapter tests and confirm the intended failure

- [ ] Run:

```powershell
uv run --with-requirements requirements-dev.txt python -m pytest `
  src/platform/tests/test_adapter.py -v
```

Expected: successful plain numeric round trips may pass through the old adapter, but numeric-string normalization and every invalid-value rejection fail because numeric validation/conversion is not implemented.

### 2.3 Implement metadata-driven conversion

- [ ] In `src/platform/adapter.py`, import `Decimal` and `InvalidOperation`. Add a helper that rejects booleans, optionally accepts physical numeric strings, rejects non-finite values, enforces the field's `min_value`/`max_value`, and checks declared decimal precision without quantizing:

```python
def _to_decimal(
    value: Any,
    *,
    qualified_name: str,
    allow_string: bool,
) -> Decimal:
    if isinstance(value, bool) or (
        isinstance(value, str) and not allow_string
    ):
        raise RecordAdapterError(f"invalid numeric value for {qualified_name}")
    if not isinstance(value, (int, float, Decimal, str)):
        raise RecordAdapterError(f"invalid numeric value for {qualified_name}")
    try:
        candidate = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise RecordAdapterError(
            f"invalid numeric value for {qualified_name}"
        ) from None
    if not candidate.is_finite():
        raise RecordAdapterError(f"non-finite numeric value for {qualified_name}")
    return candidate
```

- [ ] Add helpers that enforce bounds and precision. Precision checking must compare the value to its exact quantum and raise on mismatch; it must never return the quantized value:

```python
def _validate_bounds_and_precision(
    candidate: Decimal,
    *,
    qualified_name: str,
    min_value: float | None,
    max_value: float | None,
    decimal_precision: int,
) -> None:
    if min_value is not None and candidate < Decimal(str(min_value)):
        raise RecordAdapterError(f"value below minimum for {qualified_name}")
    if max_value is not None and candidate > Decimal(str(max_value)):
        raise RecordAdapterError(f"value above maximum for {qualified_name}")
    quantum = Decimal(1).scaleb(-decimal_precision)
    try:
        if candidate != candidate.quantize(quantum):
            raise RecordAdapterError(f"value exceeds precision for {qualified_name}")
    except InvalidOperation:
        raise RecordAdapterError(
            f"value exceeds precision for {qualified_name}"
        ) from None
```

- [ ] Add one conversion helper that takes the manifest field, `NumericTypeAdapter`, direction, and value. Required numeric fields reject `None`; optional `cycle_time` passes `None`. For `logical_type == "int"`, logical input must be an actual Python `int` excluding `bool`, physical input may be numeric/string but must be mathematically integral, and output is `int`. For `logical_type == "float"`, accepted output is `float`.

- [ ] Refactor both public adapter functions to look up fields by logical/physical name, retrieve metadata from `manifest.schema_approval.logical_to_physical_types` using `f"{contract}.{field.logical_name}"`, and invoke numeric conversion only when that exact key is declared. Preserve unknown-field and Data Fabric system-field behavior.

The resulting loops should have this shape:

```python
    converted: dict[str, Any] = {}
    for logical_name, value in record.items():
        field = fields_by_logical_name[logical_name]
        qualified_name = f"{contract}.{logical_name}"
        type_adapter = manifest.schema_approval.logical_to_physical_types.get(
            qualified_name
        )
        converted[field.physical_name] = _convert_numeric_value(
            value,
            field=field,
            adapter=type_adapter,
            qualified_name=qualified_name,
            from_physical=False,
        )
    return converted
```

`_convert_numeric_value` returns the original value unchanged when `adapter is None`.

### 2.4 Run the adapter and platform suites to green

- [ ] Run:

```powershell
uv run --with-requirements requirements-dev.txt python -m pytest `
  src/platform/tests/test_adapter.py `
  src/platform/tests/test_manifest.py `
  src/platform/tests/test_provisioner.py `
  src/platform/tests/test_cli.py `
  -v
```

Expected: all platform tests pass. Existing reserved-name conversions and Data Fabric system-field handling remain unchanged.

### 2.5 Commit the conversion change

- [ ] Run:

```powershell
git diff --check
git status --short
git add src/platform/adapter.py src/platform/tests/test_adapter.py
git commit -m "fix(platform): validate numeric record adapters"
```

Expected: one focused Alpha commit containing the conversion implementation and its tests.

---

## Task 3: Document the approved adapter boundary and run repository verification

**Files:**

- Modify: `src/platform/README.md`

Documentation is the implementation in this task, so no additional failing unit test is required. Tasks 1 and 2 already provide machine-checkable behavior.

### 3.1 Update operator documentation

- [ ] In `src/platform/README.md`, retain the name-mapping table and add a second table for the five numeric mappings, including physical precision and logical return type.

- [ ] State explicitly that consumers must use `logical_to_physical` and `physical_to_logical`, values are never rounded/truncated, and live apply requires approval for both name and type adapters.

- [ ] Keep all command examples tenant-neutral. Do not add the staging OAuth client ID, tenant ID, access token, or a concrete organization/tenant to the checked-in README.

### 3.2 Run formatting and full regression checks

- [ ] Run:

```powershell
git diff --check
uv run --with-requirements requirements-dev.txt python -m pytest -v
uv run --with-requirements requirements.txt python -m src.platform plan --offline-clean
```

Expected:

- The entire repository test suite passes.
- The offline JSON plan reports `mode: offline-clean`, `create_count: 28`, and `requires_schema_approval: true`.
- Entity create actions show `DECIMAL` precision 0 for the four integer adapters and precision 3 for `PaymentCase.cycle_time`.

### 3.3 Perform the UiPath structural review

- [ ] Invoke the `uipath-review` skill against the changed platform manifest, adapter, and provisioning tests. Resolve every error within Alpha-owned paths and rerun the affected tests. Record warnings separately; do not broaden scope into Bravo or Charlie paths.

### 3.4 Commit the documentation

- [ ] Run:

```powershell
git add src/platform/README.md
git commit -m "docs(platform): explain numeric schema adapters"
git status --short --branch
```

Expected: the worktree is clean and branch `alpha` contains the approved design, this plan, two implementation commits, and the operator-documentation commit.

---

## Task 4: Review, publish, and merge the Alpha checkpoint

**Files:** None unless review finds an Alpha-owned defect. Any review fix repeats the relevant red/green test and receives its own focused commit.

### 4.1 Request an independent code review

- [ ] Invoke `superpowers:requesting-code-review` with the approved design, this plan, and the full Alpha commit range. The reviewer must check exact mapping coverage, type preservation, failure behavior, no rounding, ownership boundaries, test evidence, and tenant neutrality.

- [ ] Resolve all High and Medium findings. For each code defect, first add or tighten a test that reproduces it, observe failure, implement the minimal correction, and rerun the platform plus full suites.

### 4.2 Push and open the reviewed pull request

- [ ] Run:

```powershell
git status --short --branch
git log --oneline origin/main..HEAD
git push origin alpha
```

- [ ] Open a ready-for-review pull request from `alpha` to `main`. Include the exact full-suite result, offline create count, and reviewer result. Preserve all commits; do not squash or rewrite history.

### 4.3 Merge and verify the authoritative baseline

- [ ] After required checks/review succeed, merge the pull request normally. Then run:

```powershell
git fetch origin
git rev-parse origin/main
git log --oneline --decorate -8 origin/main
```

Expected: `origin/main` contains every Alpha design, plan, implementation, and documentation commit. Record and announce the resulting merge SHA before provisioning.

---

## Task 5: Re-provision and prove staging idempotency

**Files:** None. This task mutates only the explicitly authorized disposable staging tenant.

**Target:** `https://staging.uipath.com` / `uipathstgSS_updated` / `FINS`

### 5.1 Verify authentication and run a read-only online plan

- [ ] From a clean checkout of merged `origin/main`, run:

```powershell
uip login status
uv run --with-requirements requirements.txt python -m src.platform plan `
  --base-url https://staging.uipath.com `
  --organization uipathstgSS_updated `
  --tenant FINS
```

Expected: login status identifies the intended staging base URL, organization, and FINS tenant. The online plan succeeds, performs no mutation, reports exactly 28 creates, and requires schema approval. If target identity differs or any same-named resource drifts, stop without applying.

### 5.2 Apply the reviewed state once

- [ ] Run the exact approved mutation:

```powershell
uv run --with-requirements requirements.txt python -m src.platform apply `
  --base-url https://staging.uipath.com `
  --organization uipathstgSS_updated `
  --tenant FINS `
  --confirm `
  --approve-schema-mappings
```

Expected: five Data Fabric entities, eight customer gate-setting records, one `TreasuryPayments` folder, three queues, and eleven non-secret assets are created. The command's built-in verification reports `created_count: 28` and `verification_create_count: 0`.

### 5.3 Prove the second plan is a no-op

- [ ] Rerun the online plan command from Step 5.1.

Expected: `create_count: 0`, no drift, and no mutation. This is the platform checkpoint exit condition.

### 5.4 Record the handoff

- [ ] Report:

```text
Role/checkpoint: Alpha A2 numeric Data Fabric compatibility
Branch: alpha
Files changed: manifest, adapter, platform tests, platform README
Exit commands: targeted platform tests; full pytest; offline plan; online plan; approved apply; second online plan
Observed result: all tests pass; 28 resources created; verification and second plan require zero creates
Contract changes: none; physical adapters only
Known limitations: staging DECIMAL Basic-field compatibility is tenant-specific physical behavior hidden behind the checked-in adapter
Ready for solution deployment: yes
```

Add the actual commit SHA, merge SHA, test count, and command outputs when executing; do not place credentials in the handoff.

---

## Completion Criteria

- [ ] The five exact numeric mappings are declared, reviewed, and emitted as `DECIMAL` with precision 0/3.
- [ ] Logical contracts are byte-for-byte unchanged.
- [ ] Both adapter directions preserve valid logical types and reject lossy or invalid values before persistence/consumption.
- [ ] Existing name adapters, gates, agent behavior, and orchestration tests remain green.
- [ ] Full pytest and UiPath structural review report zero errors.
- [ ] The reviewed Alpha history is merged into `main` without squashing or rewriting.
- [ ] Staging contains all 28 required resources and the subsequent online plan reports zero creates.
