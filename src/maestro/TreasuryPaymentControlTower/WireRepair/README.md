# WireRepair Maestro Flow

`WireRepair.flow` is the executable process spine for the fixture-driven repair
lane:

1. The in-solution Bravo coded agent receives the typed `payment_case`,
   `gate_context`, and optional `demo_role`. Its registered resource key is
   `ee894252-e868-4de2-a8b2-2b29ba8efd07`.
2. A pure JavaScript policy node evaluates G0 through G10 in the same order and
   with the same reasons as Alpha's canonical Python evaluator. The route tests
   execute that script and compare its typed `PolicyDecision` to Alpha.
3. Only `PolicyDecision.result == AUTO_APPLY` reaches the automatic sandbox
   effector. G0 and G2 take non-overridable terminal paths. All other paths build
   the exact C1 seven-field escalation packet and open an OOTB Action Center
   QuickForm.
4. Approve or evidence-backed same-field Edit reaches the separately
   credentialed sandbox effector only from an overridable approval path.
   Reject/Escalate never reaches an effector. `CALLBACK_THEN_HUMAN` offers
   `Provide Info` and is structurally routed to a no-effect ledger regardless of
   the selected QuickForm outcome.
5. Every terminal path returns the same typed `caseLedger` record. Effectors
   record before/after values, policy authorization, credential identity, and
   `payment_write_performed: false`; no node writes to a payment system. Agent
   and script failures route to `incidentLedger` so the case does not disappear
   as an unobserved Flow fault.

The QuickForm result does not expose the authenticated performer identity. The
Flow therefore records the selected action, task node, and Flow instance while
setting `performer_identity` to `null`; Action Center's own task audit is the
authoritative reviewer record. It never invents a reviewer identity.

The richer standalone `wire-repair-approval` Coded Action App carries the same
escalation contract, but the Flow deliberately uses QuickForm until the staging
tenant supplies a deployed app `systemName`.

The agent definition and its two resource bindings are generated from the
Alpha-owned solution registration. Do not hand-edit the shared `.uipx` or its
generated resource files from this project.

```powershell
uip maestro flow format WireRepair.flow
uip maestro flow validate WireRepair.flow --strict-bindings --output json
```

UiPath CLI 1.196.4 currently emits a non-fatal agent folder-binding warning
during `uip solution pack --dry-run` even though strict Flow validation and the
solution pack both report `Valid`. The deployable top-level `folderPath`
binding is `TreasuryPayments`; keep the registry-derived definition verbatim
and recheck this warning after a CLI upgrade.
