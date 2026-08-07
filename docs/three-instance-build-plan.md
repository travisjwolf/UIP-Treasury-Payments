# Three-Instance Payment Control Tower Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement the assigned checkpoint. Work only on the branch and paths assigned to your role, use test-driven development for Python features, and run the checkpoint exit commands before committing. Checkboxes are the shared build-day status record.

**Goal:** Deliver the three pinned wire-repair demo paths in one build day using three independently operated Codex instances named Alpha, Bravo, and Charlie.

**Architecture:** Alpha establishes the shared contracts and deterministic controls before parallel implementation begins. Bravo builds the read-only reasoning lane, while Charlie builds the orchestration and human experience against Alpha's contracts. Integration happens through verified merges into `main`; Git is authoritative and UiPath tenants are disposable deployment targets.

**Tech Stack:** UiPath CLI, coded agents with Python and LangGraph, Maestro, Coded Apps, Action Center, API workflows or robots, Data Fabric, and pytest.

## Global constraints

- The only implementation branches are `alpha`, `bravo`, and `charlie`; all three merge back to `main`.
- No implementation code starts on Bravo or Charlie until Alpha's contract checkpoint is merged into `main` and synced into both branches.
- Gates are deterministic code with no model calls. The agent proposes; only an effector or human applies.
- Every proposed value is traceable to `evidence[]`; the outcome enum is closed.
- G0, G1, and G2 are not configurable. G3, G5, G8, and G10 use per-customer configuration.
- The repair loop has a fixed iteration cap and token budget and returns `EXHAUSTED` with its trace at either limit.
- No live telephony. `WIRE-8877` uses a prerecorded transcript or audio fixture and preserves the human decision.
- Orchestrator configuration is scripted and checked in. Do not create required tenant state only through the UI.
- A role never edits another role's owned path without an explicit handoff agreed by both people.
- A branch is mergeable only when its listed exit commands pass and the handoff includes the exact commit SHA.

---

## Branch and ownership map

| Instance | Branch | Owns | Does not own |
|---|---|---|---|
| Alpha | `alpha` | `src/contracts/`, `src/gates/`, `src/platform/`, `fixtures/cases/`, `tests/contracts/`, `tests/gates/`, platform and solution configuration | Agent reasoning, apps, Action Center UI |
| Bravo | `bravo` | `src/agent/`, `src/tools/`, `tests/agent/`, `tests/tools/`, prerecorded callback analysis if time permits | Gates, write-capable effectors, app UI |
| Charlie | `charlie` | `src/maestro/`, `src/effectors/`, `src/apps/`, `tests/integration/`, demo scripts and UI assets | Agent reasoning, gate rules, shared contracts |

Alpha is also the integration steward for shared manifests, dependency files, `AGENTS.md`, and solution packaging. That responsibility does not allow Alpha to change another role's logic; integration fixes go back to the owning branch.

The repository itself determines the next checkpoint when a person prompts with only a role name:

- Alpha runs A0 if contract tests or per-case fixtures are absent, A1 if gate tests are absent, A2 if platform setup is absent, and otherwise the Phase 3 integration gate.
- Bravo stays in B0 until Alpha A0 is present, runs B1 if the stub-agent hero checks are absent, and otherwise runs B2.
- Charlie stays in C0 until Alpha A0 is present, runs C1 if the process harness is absent, and otherwise runs C2.

## Git protocol

Each person uses a separate clone or worktree. Start a role with:

```powershell
git fetch origin
git switch alpha   # replace with bravo or charlie
git pull --ff-only origin alpha
```

If the role branch does not yet exist locally:

```powershell
git fetch origin
git switch --track origin/alpha   # replace with bravo or charlie
```

Before each checkpoint, incorporate the latest shared baseline on the role branch and resolve conflicts there, never on `main`:

```powershell
git fetch origin
git merge --no-edit origin/main
```

After the exit checks pass:

```powershell
git status --short
git push origin HEAD
```

Open a pull request from the role branch to `main`. The reviewer confirms the exit evidence and owned paths before merging. Use a merge commit rather than a squash merge so the persistent role branch can resynchronize without rewriting history. Never force-push a role branch. After a checkpoint is merged, every active role fetches and merges the new `origin/main` before continuing.

Use small, descriptive commits such as `feat(gates): evaluate fixed policy controls`, `feat(agent): resolve known name mismatch`, or `feat(app): show evidence-backed escalation`.

## Phase 0: shared contract checkpoint

Only Alpha writes implementation code during this phase. Bravo and Charlie may install tools, authenticate, read the documents, and inspect UiPath examples, but they do not create `src/` content.

### Alpha A0 - contracts and fixtures

- [ ] Define importable `PaymentCase`, `Evidence`, `CounterpartyHistory`, `PolicyDecision`, `ProposedAction`, and agent-output schemas using exactly the fields and outcome enum in `AGENTS.md`.
- [ ] Split all 40 rows of `fixtures/payments.csv` into deterministic `fixtures/cases/<case_id>.json` inputs without changing the source CSV.
- [ ] Add contract tests that reject unknown outcomes, out-of-range confidence, and malformed proposed actions.
- [ ] Add a fixture test that proves every CSV row has one case file and preserves `expected_outcome` and `expected_path`.
- [ ] Run the contract and fixture tests and push the passing commit to `alpha`.
- [ ] Merge the Alpha contract checkpoint into `main`; announce the merge commit SHA to Bravo and Charlie.

Exit command:

```powershell
python -m pytest tests/contracts -v
```

Expected result: all contract and fixture tests pass for 40 cases.

### Bravo B0 - preparation only

- [ ] Install the UiPath CLI and repository skills.
- [ ] Confirm `uip login` and `uip codedagent setup` work.
- [ ] Read the agent contract and sketch tool interfaces without committing implementation files.
- [ ] Wait until `origin/main` contains Alpha A0, then merge `origin/main` into `bravo`.

### Charlie C0 - preparation only

- [ ] Install the UiPath CLI and repository skills.
- [ ] Confirm the nominated tenant and deployment folder are known.
- [ ] Read the escalation contract and map the three demo cases without committing implementation files.
- [ ] Wait until `origin/main` contains Alpha A0, then merge `origin/main` into `charlie`.

## Phase 1: parallel critical path

### Alpha A1 - deterministic gate evaluator

- [ ] Write table-driven failing tests for G0 through G10, including first-gate-wins ordering and threshold boundary values.
- [ ] Parameterize the gate suite over every row in `fixtures/payments.csv` and assert the resulting path equals `expected_path`.
- [ ] Implement the pure evaluator from `PaymentCase` plus agent output to `PolicyDecision`; do not import an LLM or UiPath runtime.
- [ ] Prove `WIRE-8841` returns a G1 human-approval decision even with confidence `0.91`.
- [ ] Push the passing gate checkpoint to `alpha` and merge it into `main` first.

Exit command:

```powershell
python -m pytest tests/gates -v
```

Expected result: all gate tests pass, including all 40 fixture rows.

### Bravo B1 - bounded repair agent with stubbed tools

- [ ] Scaffold the coded agent and keep every LLM-service call and LangGraph node async.
- [ ] Implement a read-only tool protocol and deterministic stubs for account lookup, counterparty history, sanctions, and documents.
- [ ] Build a bounded reasoning loop that always returns the exact agent-output schema and never exposes a write tool.
- [ ] Make `WIRE-8802` return evidence-backed `RESOLVED` and `WIRE-8841` return the proposed account repair with `0.91` confidence.
- [ ] Add tests proving every proposed value exists in a tool result and exhaustion returns the full trace.
- [ ] Push the passing stub-agent checkpoint to `bravo`.

Exit commands:

```powershell
python -m pytest tests/agent -v
uip codedagent run agent --file fixtures/cases/WIRE-8802.json
uip codedagent run agent --file fixtures/cases/WIRE-8841.json
```

Expected result: the two runs match their fixture `expected_outcome` values and all agent tests pass.

### Charlie C1 - process and human-path skeleton

- [ ] Scaffold the Maestro case flow: intake -> agent -> gate -> effect or escalation -> ledger.
- [ ] Define effectors behind a typed interface with stub implementations; no agent component receives write credentials.
- [ ] Define the escalation payload needed later by Action Center: payment, proposal, gate, evidence, cutoff, and permitted actions.
- [ ] Add an integration harness that can drive all three pinned cases without a live banking system.
- [ ] Push the passing skeleton checkpoint to `charlie`.

Exit command:

```powershell
python -m pytest tests/integration -v
```

Expected result: the harness records typed requests for auto-apply, human approval, and callback escalation without performing a real payment write.

## Phase 2: real adapters and branch integration

Merge Alpha A1 first. Bravo and Charlie then merge `origin/main` into their branches. Merge Bravo B1 second, then Charlie C1. All roles merge `origin/main` again before starting the following work.

### Alpha A2 - platform state and integration stewardship

- [ ] Script Data Fabric entities and per-customer gate settings.
- [ ] Script re-runnable Orchestrator folders, queues, and assets with no tenant-specific secrets committed.
- [ ] Own shared solution manifests and validate that component contracts match the Alpha schemas.
- [ ] Reject integration changes that bypass the gate evaluator or give the agent write credentials.

Exit condition: platform setup is re-runnable on a clean tenant and a second run makes no duplicate required resources.

### Bravo B2 - CSV-backed tools and callback stretch lane

- [ ] Replace stubs with read-only account and counterparty-history adapters over `fixtures/counterparty_history.csv`.
- [ ] Preserve the same tool interface so Charlie's orchestration does not change.
- [ ] If the two primary hero cases pass, add prerecorded callback transcription/extraction for `WIRE-8877` and return `NEEDS_INFO` with evidence.
- [ ] Run the complete agent and tool suites and push the adapter checkpoint.

Exit condition: the two primary hero cases pass with real fixture-backed tools; `WIRE-8877` is required only after that baseline is green.

### Charlie C2 - working orchestration and operator experience

- [ ] Connect the merged agent and gate evaluator to the Maestro skeleton.
- [ ] Implement an auditable stub or sandbox effector for auto-eligible repairs.
- [ ] Build the Action Center path for `WIRE-8841`, with G1 reason and full evidence visible in one task.
- [ ] After the process and Action Center paths work, build the control-tower queue and case detail with status, cutoff, confidence, outcome, gate, and evidence.
- [ ] Measure the demo interaction so the human decision can be completed in approximately 20 seconds.

Exit condition: the integration harness routes all three hero cases to their expected paths and every state transition appears in the ledger.

## Phase 3: final integration and demo gate

Merge order is `alpha` -> `bravo` -> `charlie`. Alpha then syncs its branch from `main`, performs integration-only fixes in shared files, and opens the final Alpha pull request. Logic fixes return to their owning branch.

- [ ] Run all Python tests across contracts, gates, agent, tools, and integration.
- [ ] Run `uipath-review` on every project and resolve all errors in the owning branch.
- [ ] Run `uip solution pack` successfully from a clean checkout.
- [ ] Deploy to the nominated demo tenant using only checked-in configuration plus secrets supplied at runtime.
- [ ] Rehearse `WIRE-8802`, then `WIRE-8841`, then `WIRE-8877` if the stretch lane is ready.
- [ ] Confirm `WIRE-8841` visibly refuses autonomous action because G1 fired; do not describe this as an agent failure.
- [ ] Tag or record the final demo commit SHA.

Whole-solution exit commands:

```powershell
python -m pytest -v
uip solution pack
```

Expected result: tests pass, each UiPath review has zero errors, packaging succeeds, and the three demo paths match the fixtures.

## Ready-to-paste instance prompts

After cloning the repository, the shortest supported prompt is just the role name: `Alpha`, `Bravo`, or `Charlie`. `AGENTS.md` maps that name to this plan. Use the full prompts below when you want the branch and stopping rule stated explicitly.

### Alpha

```text
Alpha. Work only on the alpha branch and execute the next incomplete Alpha checkpoint in docs/three-instance-build-plan.md. Read AGENTS.md and both required domain documents first. Enforce contract-first development and deterministic gates. Run the checkpoint exit commands, make focused commits, push origin/alpha, and report the commit SHA plus exact test evidence. Stop at the checkpoint; do not implement Bravo or Charlie work and do not merge to main without review.
```

### Bravo

```text
Bravo. Work only on the bravo branch and execute the next incomplete Bravo checkpoint in docs/three-instance-build-plan.md. Read AGENTS.md and both required domain documents first. Before writing implementation code, verify Alpha A0 is present on origin/main and merge origin/main into bravo. Keep the agent read-only, async, evidence-backed, typed, and bounded. Run the checkpoint exit commands, make focused commits, push origin/bravo, and report the commit SHA plus exact test evidence. Stop at the checkpoint; do not edit Alpha or Charlie paths.
```

### Charlie

```text
Charlie. Work only on the charlie branch and execute the next incomplete Charlie checkpoint in docs/three-instance-build-plan.md. Read AGENTS.md and both required domain documents first. Before writing implementation code, verify Alpha A0 is present on origin/main and merge origin/main into charlie. Build orchestration and operator surfaces against the shared contracts; keep all payment writes behind effectors. Run the checkpoint exit commands, make focused commits, push origin/charlie, and report the commit SHA plus exact test evidence. Stop at the checkpoint; do not edit Alpha or Bravo paths.
```

## Checkpoint handoff format

Every branch handoff uses this compact record so another person can reproduce it:

```text
Role/checkpoint:
Branch and commit SHA:
Files changed:
Exit commands run:
Observed result:
Contract or configuration changes:
Known limitations:
Ready to merge: yes/no
```

If a checkpoint fails to converge after roughly five implementation attempts, stop. Record the failing command and evidence, then repair the contract or fixture in the owning branch before resuming.
