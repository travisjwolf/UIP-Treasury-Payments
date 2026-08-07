# AGENTS.md

Context for coding agents (Codex, Claude Code, Cursor) working in this repo.

Read this file, then `docs/PDD-wire-repair.md` and `docs/exception-taxonomy-and-gates.md`, before writing any code.

---

## What we are building

**Payment Operations Control Tower.** A UiPath process app that is the single pane of glass over every in-flight payment at a commercial bank. Maestro runs one long-lived case per payment. Coded agents make judgment calls. Robots and API workflows execute. Humans are pulled in only where a deterministic policy gate says so.

The reference lane is **wire repair**: payments that fail automated validation and sit in a queue waiting for a human to work out what the correct value of a failing field should be.

Built for the UiPath AMER SE Build Challenge, 7 August 2026. One build day. Optimize for a working end-to-end path over completeness.

---

## Repo layout

```
AGENTS.md                                  this file
README.md                                  orientation for humans
docs/PDD-wire-repair.md                    the process, grounded in customer discovery
docs/exception-taxonomy-and-gates.md       exception types, typed outcomes, gate list
docs/three-instance-build-plan.md          Alpha / Bravo / Charlie ownership and merge plan
docs/business-case-skeleton.md             not needed for the build
fixtures/payments.csv                      40 payment cases
fixtures/counterparty_history.csv          prior repair history the agent reasons over
fixtures/README.md                         what the fixture data is and is not
scripts/generate_fixtures.py               regenerate or expand the fixtures
```

Everything built on the day goes under `src/`. Do not create it before the build day starts.

---

## Three-instance role dispatch

The implementation uses three persistent branches: `alpha`, `bravo`, and `charlie`. Their ownership, checkpoints, and merge order are defined in `docs/three-instance-build-plan.md`.

If the user's prompt is only `Alpha`, `Bravo`, or `Charlie`, treat that name as the instruction to execute the next incomplete checkpoint for that role. Before editing:

1. Fetch `origin` and verify that the checked-out branch is the lowercase form of the role name.
2. Read this file, `docs/PDD-wire-repair.md`, `docs/exception-taxonomy-and-gates.md`, and `docs/three-instance-build-plan.md`.
3. Confirm that every required upstream checkpoint is present on the branch. Bravo and Charlie may not write implementation code until Alpha's contract checkpoint is merged into `main` and incorporated into their branches.
4. Work only inside the role's owned paths. Stop and request a handoff instead of editing another role's files.
5. Run the role's exit checks, make focused commits to the role branch, and push that branch. Never commit implementation work directly to `main`, and never merge another role's branch without its exit evidence.

---

## Stack and which UiPath skill owns what

Install first: `npm -g install @uipath/cli` then `uip skills install`. That pulls the UiPath agent skills into this repo's agent directory.

| Component | UiPath surface | Skill |
|---|---|---|
| Pane of glass | Coded Web App | `uipath-coded-apps` |
| Human decision surface | Coded Action App + Action Center | `uipath-coded-apps`, `uipath-human-in-the-loop` |
| Process spine | Maestro Flow | `uipath-maestro-flow` |
| Repair agent | Coded agent, LangGraph, Python | `uipath-agents` |
| Effectors | API workflows, robots | `uipath-api-workflow`, `uipath-rpa` |
| State and ledger | Data Fabric entities | `uipath-platform` |
| Orchestrator config | folders, queues, assets | `uipath-platform` |
| Pre-build planning | PDD → SDD → task list | `uipath-planner` |
| Pre-demo audit | structural and quality review | `uipath-review` |

Core CLI loop:
```bash
uip login
uip codedagent setup
uip codedagent init
uip codedagent run agent --file fixtures/cases/<case>.json
uip codedagent deploy
uip solution pack
```

The Python SDK's LLM service methods are **async**. LangGraph nodes calling them must be async too. This is the most common first bug.

---

## Data contract

Define these before anything is built. Everything downstream generates against them.

### `PaymentCase` (Data Fabric entity)
`case_id` · `rail` · `direction` · `amount_usd` · `currency` · `value_date` · `cutoff_time` · `sla_deadline` · `source_channel` · `customer_id` · `customer_name` · `beneficiary_name` · `beneficiary_account` · `beneficiary_bank_aba` · `remittance_info` · `exception_code` · `exception_type` · `current_queue` · `status` · `worked_by` · `confidence` · `proposed_action` · `outcome` · `touch_count` · `cycle_time`

### `Evidence`
`case_id` · `type` (`lookup` | `history_match` | `sanctions` | `document` | `call_transcript`) · `source` · `content` · `produced_by` · `timestamp`

### `CounterpartyHistory`
`customer_id` · `beneficiary_name` · `beneficiary_account` · `times_seen` · `times_repaired` · `last_applied_fix` · `history_confidence`

### `PolicyDecision`
`case_id` · `gate` · `result` · `reason` · `evaluated_at`

### Agent output contract
The repair agent returns exactly:
```json
{
  "outcome": "RESOLVED | RESOLVED_LOW_CONFIDENCE | AMBIGUOUS | NEEDS_INFO | EXHAUSTED | BLOCKED_POLICY",
  "proposed_action": { "field": "...", "current_value": "...", "proposed_value": "..." },
  "confidence": 0.0,
  "evidence": [],
  "reasoning_summary": "",
  "tools_called": []
}
```
Never free text. The enum is closed. Adding a value to it is a contract change that requires updating the gate evaluator and the app.

---

## Hard rules

These are not style preferences. Violating them breaks the product argument.

1. **Gates are deterministic code. Never an LLM.** The gate evaluator takes a `PaymentCase` plus an agent output and returns a `PolicyDecision`. It must be unit-testable with no model call. See `docs/exception-taxonomy-and-gates.md` §3.
2. **The agent proposes, it never applies.** All writes go through a robot or API workflow with its own credentials. The agent has no write tools.
3. **Every proposed value must be traceable to a tool result in `evidence[]`.** The agent may not invent an account number, a routing number, or a party name.
4. **G0, G1, G2 are not configurable.** Sanctions, beneficiary account change, and amount/currency change. Thresholds in G3, G5, G8, G10 are per-customer config in Data Fabric.
5. **Bound the loop.** Max iterations and a token budget. On exhaustion, return `EXHAUSTED` with the full trace. Do not retry indefinitely.
6. **No live telephony.** The callback lane uses a pre-recorded audio fixture. Transcription, entity extraction, and reconciliation against the payment record are in scope. An agent placing a call and collecting a PIN is not.
7. **Orchestrator config is scripted and checked in.** Folders, queues, and assets are created by a re-runnable script via `uipath-platform`, not clicked through a UI. Team members are on different tenants, so any tenant must be reproducible from the repo.
8. **Git is the source of truth. Tenants are disposable build targets.** `.uipx` is the merge unit.

---

## Build conventions

**Contract-first.** No parallel work starts until the schemas above exist in the repo. Branches either conform or fail a check.

**Fixture-driven.** Write the input fixture and its expected output before building the thing that produces it. `fixtures/payments.csv` has an `expected_outcome` and `expected_path` column for exactly this. Split it into per-case JSON under `fixtures/cases/` on day one.

**Machine-checkable exit criteria.** A coding agent never declares itself done. Every unit of work exits on a command that returns a status:

| Work | Exit condition |
|---|---|
| Coded agent | `uip codedagent run agent --file fixtures/cases/<case>.json` matches `expected_outcome` |
| Gate evaluator | Unit tests pass across all 40 fixture rows |
| Any project | `uipath-review` returns zero errors |
| Whole solution | `uip solution pack` succeeds |

**Bounded iteration.** If a coding agent has not converged in roughly five attempts, the spec is wrong, not the code. Stop, fix the contract or the fixture, restart.

---

## Build order

Do not build the app first. It is the most seductive and the least load-bearing.

1. Contracts and per-case fixture JSON
2. Gate evaluator with unit tests over all 40 fixture rows (pure logic, no model, fast, and it de-risks the compliance story)
3. Repair agent against a stubbed tool layer, exiting on the two hero cases
4. Real tool layer: account lookup and counterparty history over the CSVs
5. Maestro Flow wiring intake → agent → gate → effect → ledger
6. Action Center escalation with the full evidence packet
7. Coded web app: control tower, queue view, case detail
8. `uipath-review`, deploy to the nominated demo tenant, rehearse

Steps 2, 3, and 4 are the critical path. Everything else can be stubbed.

---

## Demo cases

Three rows in `fixtures/payments.csv` are pinned with a `demo_role` value. They must work.

| `case_id` | `demo_role` | Expected |
|---|---|---|
| `WIRE-8802` | `hero_auto_resolve` | `RESOLVED`, auto-applied. Known counterparty, name-only fix, $84.5K, all gates clear. |
| `WIRE-8841` | `hero_gate_blocked` | `BLOCKED_POLICY`. Agent finds the fix with 0.91 confidence, but it changes the beneficiary account, so G1 fires. Human approves in one click. |
| `WIRE-8877` | `hero_callback` | `NEEDS_INFO`. Stretch lane: callback transcript reconciled against the payment record, one field flagged. |

`WIRE-8841` is the most important. It is the case where the system correctly refuses to act on its own, and that refusal is the feature.

---

## Starting prompt

```
Read AGENTS.md, docs/PDD-wire-repair.md, and
docs/exception-taxonomy-and-gates.md.

Then build the gate evaluator described in the taxonomy doc §3.
It takes a PaymentCase and an agent output and returns a PolicyDecision.
Pure Python, deterministic, no model calls.

Write unit tests that run it against every row in fixtures/payments.csv
and assert the resulting path matches the expected_path column.

Do not build the agent yet.
```
