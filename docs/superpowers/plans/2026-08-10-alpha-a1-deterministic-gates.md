# Alpha A1 Deterministic Gate Evaluator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a pure, deterministic G0-G10 policy evaluator and prove that all 40 payment fixtures route to their declared path.

**Architecture:** `src/gates/evaluator.py` exposes one functional boundary that consumes the A0 `PaymentCase`, `AgentOutput`, `GateContext`, and `PolicyConfig` contracts and returns a `PolicyDecision`. Gate conditions are evaluated without UiPath or model dependencies, with the first applicable gate winning; focused tests cover each rule and configurable boundary, while a separate fixture test supplies typed representative agent outputs and checks every CSV row.

**Tech Stack:** Python 3.13, Pydantic 2 contracts from `src/contracts`, pytest.

## Global Constraints

- Work only on branch `alpha` and only in Alpha-owned paths.
- Gates are deterministic code with no model calls or UiPath runtime imports.
- The agent proposes; the evaluator only returns a `PolicyDecision` and never mutates a payment.
- G0, G1, and G2 are not configurable.
- G3, G5, G8, and G10 use `PolicyConfig` values.
- Gates are evaluated in documented G0-G10 order and the first applicable gate wins.
- G1 must beat the amount threshold for `WIRE-8841`, producing human approval at confidence `0.91`.
- Strict boundaries follow the taxonomy: G3 and G8 fire only above their thresholds, G5 only below its threshold, and G10 only below its remaining-time threshold.
- Agent outcomes without an actionable proposal skip application-risk gates G1-G8 and route through G9, after the unconditional sanctions gate G0.
- `NEEDS_INFO` at G9 returns `CALLBACK_THEN_HUMAN`; `AMBIGUOUS` and `EXHAUSTED` return `ESCALATE`.
- A clear evaluation returns `gate=None` and `result=AUTO_APPLY`.

---

### Task 1: Pure G0-G10 Evaluator

**Files:**
- Create: `src/gates/__init__.py`
- Create: `src/gates/evaluator.py`
- Create: `tests/gates/test_evaluator.py`

**Interfaces:**
- Consumes: `PaymentCase`, `AgentOutput`, `GateContext`, and `PolicyConfig` from `src.contracts`.
- Produces: `evaluate_policy(payment_case: PaymentCase, agent_output: AgentOutput, gate_context: GateContext, policy_config: PolicyConfig) -> PolicyDecision`.
- Public import: `from src.gates import evaluate_policy`.

- [ ] **Step 1: Write focused failing tests for the public evaluator and every gate**

Create typed builders in `tests/gates/test_evaluator.py` with safe defaults: a USD payment below all thresholds, a high-confidence name-only proposal, clear sanctions, an established domestic counterparty, a same-day total below the configured velocity threshold, evaluation at 12:00 Eastern, cutoff at 17:00 Eastern, and customer-matched configuration.

Add a table-driven test with literal expected gate/result pairs for:

```python
[
    ("G0", "COMPLIANCE_REFERRAL"),
    ("G1", "HUMAN_APPROVAL"),
    ("G2", "HARD_STOP"),
    ("G3", "HUMAN_APPROVAL"),
    ("G4", "HUMAN_APPROVAL"),
    ("G5", "HUMAN_APPROVAL"),
    ("G6", "HUMAN_APPROVAL"),
    ("G7", "HUMAN_APPROVAL"),
    ("G8", "HUMAN_APPROVAL"),
    ("G9", "ESCALATE"),
    ("G10", "PRIORITY_ESCALATION"),
]
```

Cover both G2 fields (`amount_usd`, `currency`), both G6 signals (cross-border and non-USD), and all G9 outcomes (`EXHAUSTED`, `AMBIGUOUS`, `NEEDS_INFO`), asserting `NEEDS_INFO` maps to `CALLBACK_THEN_HUMAN`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tests/gates/test_evaluator.py -v
```

Expected: collection fails because `src.gates` does not exist.

- [ ] **Step 3: Implement the minimal evaluator in documented order**

Implement `evaluate_policy(...)` as pure sequential conditions. Build decisions with `case_id=payment_case.case_id` and `evaluated_at=gate_context.evaluated_at`. Use plain-language reasons that name the gate condition. Evaluate G0 unconditionally; apply G1-G8 only when `agent_output.proposed_action` is present; evaluate G9 from the typed outcome; evaluate G10 from `gate_context.cutoff_at - gate_context.evaluated_at`; otherwise return `AUTO_APPLY` with no gate.

The exact rule mapping is:

```python
G0: sanctions_status != CLEAR -> COMPLIANCE_REFERRAL
G1: proposed field == BENEFICIARY_ACCOUNT -> HUMAN_APPROVAL
G2: proposed field in {AMOUNT_USD, CURRENCY} -> HARD_STOP
G3: amount_usd > auto_apply_amount_threshold_usd -> HUMAN_APPROVAL
G4: first_time_counterparty -> HUMAN_APPROVAL
G5: confidence < minimum_confidence -> HUMAN_APPROVAL
G6: cross_border or currency != "USD" -> HUMAN_APPROVAL
G7: exception_code == "EX-07" -> HUMAN_APPROVAL
G8: same_day_beneficiary_total_usd > same_day_beneficiary_velocity_threshold_usd -> HUMAN_APPROVAL
G9 NEEDS_INFO -> CALLBACK_THEN_HUMAN
G9 AMBIGUOUS or EXHAUSTED -> ESCALATE
G10: remaining cutoff time < configured minutes -> PRIORITY_ESCALATION
clear: gate=None -> AUTO_APPLY
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
python -m pytest tests/gates/test_evaluator.py -v
```

Expected: every focused evaluator test passes.

- [ ] **Step 5: Add first-gate-wins and exact-boundary regression tests**

Add literal tests proving:

- G0 beats an account-changing G1 proposal.
- G1 beats G3 for a $2,450,000 account-changing proposal at confidence `0.91`.
- G3 does not fire at exactly `250000.0` and does fire at `250000.01`.
- G5 does not fire at exactly `0.85` and does fire at `0.849999`.
- G8 does not fire at exactly its configured threshold and does fire one cent above.
- G10 does not fire with exactly 30 minutes remaining and does fire with 29 minutes 59 seconds remaining.
- A fully clear evaluation returns no gate and `AUTO_APPLY`.

- [ ] **Step 6: Run the complete focused gate module**

Run:

```powershell
python -m pytest tests/gates/test_evaluator.py -v
```

Expected: all gate, ordering, and boundary tests pass.

- [ ] **Step 7: Commit Task 1**

```powershell
git add src/gates tests/gates/test_evaluator.py
git commit -m "feat(gates): evaluate deterministic policy controls"
```

### Task 2: Forty-Fixture Routing Matrix

**Files:**
- Create: `tests/gates/test_fixture_paths.py`
- Modify only if a failing fixture exposes a rule defect: `src/gates/evaluator.py`

**Interfaces:**
- Consumes: `evaluate_policy(...)` from Task 1 and canonical `fixtures/cases/<case_id>.json` envelopes.
- Produces: one parameterized routing assertion for every row in `fixtures/payments.csv` plus an explicit `WIRE-8841` G1 proof.

- [ ] **Step 1: Write a failing parameterized fixture-path test**

Load all CSV rows and their matching canonical JSON files. Validate `PaymentFixture`, synthesize a typed `AgentOutput`, and map decision results to expected fixture paths with an independent literal mapping:

```python
RESULT_PATHS = {
    "AUTO_APPLY": "auto_apply",
    "COMPLIANCE_REFERRAL": "compliance_referral",
    "CALLBACK_THEN_HUMAN": "callback_then_human",
    "HUMAN_APPROVAL": "human_approval",
    "HARD_STOP": "human_approval",
    "PRIORITY_ESCALATION": "human_approval",
    "ESCALATE": "human_approval",
}
```

Use fixture-driven agent values without calling Bravo code:

- `RESOLVED`: confidence `0.91` and a non-monetary proposal appropriate to the exception.
- `RESOLVED_LOW_CONFIDENCE`: confidence `0.80` and a proposal appropriate to the exception.
- `BLOCKED_POLICY`: confidence `0.91` and a proposal appropriate to the exception; EX-01 changes `beneficiary_account`.
- `AMBIGUOUS`: confidence `0.50`, no proposal.
- `NEEDS_INFO`: confidence `0.0`, no proposal.
- Every output uses empty evidence/tools because this suite tests policy routing, not agent provenance.

Use a `PolicyConfig` for the fixture customer with defaults and a velocity threshold of `5_000_000.0`.

- [ ] **Step 2: Run the fixture test and verify RED**

Run:

```powershell
python -m pytest tests/gates/test_fixture_paths.py -v
```

Expected: fail until the synthesized proposal and routing behavior cover the complete fixture matrix.

- [ ] **Step 3: Complete the typed fixture-output builder and minimal rule corrections**

Use only canonical `ProposedField` values. For EX-01 use `beneficiary_account`; EX-02 use `beneficiary_name`; EX-03 use `beneficiary_bank_aba`; EX-04 use `customer_name`; EX-05 and EX-06 use `remittance_info`; EX-07 use `remittance_info`. Proposed values must differ from the current values so contract validation remains real.

- [ ] **Step 4: Add the explicit WIRE-8841 proof**

Assert that the hero case uses a `beneficiary_account` proposal, confidence `0.91`, decision gate `G1`, and result `HUMAN_APPROVAL`, despite the payment exceeding the default G3 amount threshold.

- [ ] **Step 5: Run the Alpha A1 exit command**

Run:

```powershell
python -m pytest tests/gates -v
```

Expected: all focused tests and all 40 fixture rows pass.

- [ ] **Step 6: Run contract regression tests**

Run:

```powershell
python -m pytest tests/contracts tests/gates -v
```

Expected: A0 contracts and A1 gates all pass.

- [ ] **Step 7: Commit Task 2**

```powershell
git add tests/gates/test_fixture_paths.py src/gates/evaluator.py
git commit -m "test(gates): verify all fixture routing paths"
```

