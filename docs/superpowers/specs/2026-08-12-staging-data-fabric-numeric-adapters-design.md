# Staging Data Fabric Numeric Adapters

Date: 2026-08-12
Owner: Alpha integration stewardship
Status: Design approved; implementation pending written-spec review

## Context

The checked-in platform manifest models four whole-number fields as `INTEGER`
and `PaymentCase.cycle_time` as `DOUBLE`. The first live staging apply stopped
before creating any resource because the FINS Data Fabric service rejected the
first `INTEGER` field:

> Field 'touch_count' has unsupported SQL type 'INT' for Basic fields. Supported
> types: BIT, DATE, DATETIMEOFFSET, DECIMAL, MULTILINE, MULTILINE_MAX, NVARCHAR.

Read-only discovery confirmed that none of the five Treasury Payments entities
or the `TreasuryPayments` Orchestrator folder was created. Existing native
staging entities use `DECIMAL` for numeric Basic fields.

## Goals

- Preserve Alpha's logical Pydantic contracts and their integer/float types.
- Represent the five unsupported numeric fields using a staging-supported
  physical type.
- Make conversions explicit, bounded, lossless for accepted values, and
  unit-testable.
- Keep provisioning fail-closed and idempotent.

## Non-goals

- Do not change the business meaning, name, required status, or range of any
  logical field.
- Do not alter gate thresholds, agent behavior, Maestro routing, or app logic.
- Do not create a tenant-specific fork of the logical contracts.
- Do not silently round or truncate numeric data.

## Decision

Use `DECIMAL` as the physical Data Fabric type for all five fields. Whole-number
fields use `decimalPrecision: 0`. Cycle time uses `decimalPrecision: 3`, giving
millisecond resolution for a value measured in seconds.

| Logical contract field | Physical entity and field | Physical type |
|---|---|---|
| `PaymentCase.touch_count: int` | `PaymentCase.touch_count` | `DECIMAL`, precision 0 |
| `PaymentCase.cycle_time: float | None` | `PaymentCase.cycle_time` | `DECIMAL`, precision 3 |
| `CounterpartyHistory.times_seen: int` | `CounterpartyHistory.times_seen` | `DECIMAL`, precision 0 |
| `CounterpartyHistory.times_repaired: int` | `CounterpartyHistory.times_repaired` | `DECIMAL`, precision 0 |
| `PolicyConfig.cutoff_escalation_minutes: int` | `CustomerGateSettings.cutoff_escalation_minutes` | `DECIMAL`, precision 0 |

All previously approved name adapters remain unchanged:

- `PaymentCase.status` to `payment_status`
- `Evidence.type` to `evidence_type`
- `Evidence.timestamp` to `evidence_timestamp`

## Adapter behavior

`logical_to_physical` will retain JSON numeric values while validating the
physical precision contract. The four integer fields must be integers and must
not be booleans. `cycle_time` must be finite, non-negative, and have no more
than three fractional decimal places when present; `None` passes through
unchanged. Invalid values fail before any CLI write.

`physical_to_logical` will convert precision-zero numeric values back to Python
integers only when they are mathematically integral. It will convert accepted
cycle-time values to Python floats. Fractional values in an integer-backed
field, non-finite values, and cycle-time values beyond three decimal places are
treated as schema/data drift and fail closed.

The schema-approval metadata will record both the existing name mappings and
these physical-type mappings so a live apply still requires
`--approve-schema-mappings`.

## Provisioner behavior

The manifest will emit `DECIMAL` plus the declared precision for these fields.
Online discovery will compare the actual physical Data Fabric type and
precision against the manifest. Any mismatch remains a drift error; the
provisioner will not update, delete, or overwrite an existing entity.

The failed staging attempt needs no cleanup because it stopped on the first
create and post-failure discovery found zero Treasury entities and zero
Treasury folders.

## Alternatives considered

1. **DECIMAL physical adapters - selected.** Supported by the target service,
   retains numeric filtering/ranges, and preserves logical types through an
   explicit adapter.
2. **Store numeric values as strings.** Rejected because it loses numeric
   ordering and constraints and pushes parsing into every consumer.
3. **Remove the unsupported fields.** Rejected because it violates the shared
   data contract and removes operational metrics and configurable policy.
4. **Target a different tenant or wait for an integer-capable service.**
   Rejected because the nominated staging tenant is fixed for the hackathon.

## Verification

Implementation must add tests that prove:

- the manifest emits the five exact `DECIMAL` definitions and precisions;
- integer and cycle-time values round-trip through both adapter directions;
- fractional physical values for logical integers fail closed;
- non-finite, negative, or over-precision cycle times fail closed;
- the offline clean plan still contains exactly 28 creates;
- all existing platform and repository tests pass;
- a staging online plan succeeds before apply;
- the first approved apply succeeds and a second plan reports zero creates.

## Acceptance criteria

The change is complete when the reviewed Alpha commit is merged into `main`,
the checked-in provisioner creates the five entities, eight gate-setting
records, folder, queues, and assets in `uipathstgSS_updated/FINS`, and a
subsequent identical plan is a no-op. No logical contract or gate behavior may
change.
