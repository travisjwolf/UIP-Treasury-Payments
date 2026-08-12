# Platform provisioning

`src.platform` declares the tenant-neutral platform state for the Payment
Operations Control Tower and applies it exclusively through supported `uip`
CLI commands. It does not read UiPath auth files or issue raw REST requests.

The checked-in manifest provisions:

- Data Fabric entities for `PaymentCase`, `Evidence`, `CounterpartyHistory`,
  `PolicyDecision`, and the `PolicyConfig`-backed `CustomerGateSettings`.
- One settings record for each fixture customer, covering configurable gates
  G3, G5, G8, and G10. Fixed gates G0, G1, and G2 are not configurable.
- The `TreasuryPayments` Orchestrator folder, three encrypted queues, and
  non-secret runtime assets.

## Safety model

- `plan --offline-clean` performs no `uip` calls and shows the exact empty-
  tenant create plan.
- An online plan requires the expected base URL, organization, and tenant,
  checks `uip login status`, and stops if any active target component differs.
  This prevents a same-named organization and tenant on production from
  satisfying an explicitly staging-scoped run.
- Apply requires both `--confirm` and `--approve-schema-mappings`.
- Existing state must exactly match the manifest. Drift fails closed; the
  provisioner never updates, deletes, or overwrites a resource or seed record.
- Apply re-discovers state after creation. A successful result has zero
  remaining creates, and the next identical apply is a no-op.
- Subprocesses receive argument vectors with `shell=False`, making invocation
  safe across PowerShell, cmd, Bash, and other host shells.

## Schema approval required

The logical Alpha contracts stay unchanged. Data Fabric rejects or risks
rejecting three logical names as reserved SQL/C#/VB language terms, so the
manifest declares explicit adapters:

| Logical contract field | Physical Data Fabric field |
|---|---|
| `PaymentCase.status` | `payment_status` |
| `Evidence.type` | `evidence_type` |
| `Evidence.timestamp` | `evidence_timestamp` |

Review and approve these mappings before live apply. Consumers must use
`logical_to_physical` and `physical_to_logical` rather than leaking physical
names into the shared models.

## Commands

Offline plan, safe in any login state:

```powershell
python -m src.platform plan --offline-clean
```

Read-only discovery against an explicitly named target:

```powershell
python -m src.platform plan `
  --base-url https://staging.uipath.com `
  --organization <org-name> `
  --tenant <tenant-name>
```

Live apply is intentionally separate and must only follow schema review and a
successful online plan:

```powershell
python -m src.platform apply `
  --base-url https://staging.uipath.com `
  --organization <org-name> `
  --tenant <tenant-name> `
  --confirm `
  --approve-schema-mappings
```

No tenant-specific IDs, tokens, credential assets, secret assets, or passwords
belong in this directory or manifest.

## Shared solution integration handoff

The existing solution manifest lives at
`src/maestro/TreasuryPaymentControlTower/TreasuryPaymentControlTower.uipx` and
currently registers only the `WireRepair` Flow. The Bravo coded agent lives at
`src/agent`, outside that solution root. The supported CLI therefore rejects:

```powershell
uip solution project add src/agent `
  src/maestro/TreasuryPaymentControlTower/TreasuryPaymentControlTower.uipx
```

with `Project must reside within the solution folder`. The supported integration
command is:

```powershell
uip solution project import src/agent `
  --solutionFile src/maestro/TreasuryPaymentControlTower/TreasuryPaymentControlTower.uipx
```

`project import` copies the entire agent into the solution tree. Run it only
after Bravo hands off the final agent commit and Charlie approves the generated
copy under its owned `src/maestro/**` path. Then verify with
`uip solution project list --solution-folder
src/maestro/TreasuryPaymentControlTower --output json` and inspect that the
`.uipx` project set agrees with the CLI-generated `resources/solution_folder/`
artefacts. Do not hand-edit either generated surface. Coded apps deploy
independently and must not be registered in `.uipx`.
