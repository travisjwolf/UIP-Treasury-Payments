# Exception taxonomy and gate list

Two things live here, and the split matters.

**The taxonomy** describes what went wrong and what the agent is allowed to try. It is domain knowledge.

**The gates** decide whether the agent's proposal may be applied without a human. Gates are deterministic code. **No gate is ever evaluated by an LLM.** That rule is the entire compliance argument, and it is the thing to defend if anyone on the team suggests "just let the model decide."

---

## 1. Typed outcomes

The repair agent must terminate in exactly one of these. Never free text.

| Outcome | Meaning |
|---|---|
| `RESOLVED` | A fix was determined with high confidence and supporting evidence |
| `RESOLVED_LOW_CONFIDENCE` | A fix was determined but evidence is thin or conflicting |
| `AMBIGUOUS` | More than one plausible fix, agent cannot choose between them |
| `NEEDS_INFO` | Resolution requires information not available internally (client or branch outreach) |
| `EXHAUSTED` | Iteration or budget cap hit without convergence |
| `BLOCKED_POLICY` | A gate prevented evaluation or application, regardless of what the agent found |

Every outcome carries: `proposed_action`, `confidence` (0-1), `evidence[]`, `reasoning_summary`, `tools_called[]`.

---

## 2. Exception taxonomy

| Code | Type | Detection signal | Agent tools | Typical fix | Auto-eligible? |
|---|---|---|---|---|---|
| **EX-01** | `beneficiary_account_not_found` | Account lookup returns no match | Core lookup, counterparty history, fuzzy account match, standing instructions | Expand truncated account, correct transposed digits, append check digit | **No.** Always changes the beneficiary account, so G1 fires. Agent proposes, human approves. |
| **EX-02** | `name_account_mismatch` | Account exists, registered name differs from instruction | Core lookup, counterparty history, entity name normalization | Normalize name to registered entity (DBA, abbreviation, punctuation) | **Yes,** when the account is unchanged and history confirms the pairing |
| **EX-03** | `missing_intermediary_routing` | Beneficiary bank requires a correspondent, none supplied | Routing directory, counterparty history, prior payment reconstruction | Insert intermediary ABA or BIC from prior successful payment | **Yes,** when a prior payment to the same pair cleared with that intermediary |
| **EX-04** | `insufficient_party_identification` | Required party field blank or non-conforming (address, legal name) | Core lookup, customer master, prior payment | Populate from customer master or prior payment | **Yes** when sourced internally. `NEEDS_INFO` when it requires client outreach. |
| **EX-05** | `unstructured_remittance` | Remittance field free-text, truncated, or empty where structured data is required | Document extraction (IXP), prior payment patterning | Restructure into conforming format | **Yes.** Does not touch money movement fields. |
| **EX-06** | `format_currency_mismatch` | Currency, country, or field format violates rail spec | Format validator, rail spec | Reformat field | **Yes** for pure formatting. **No** if the fix changes currency (G10). |
| **EX-07** | `duplicate_suspect` | Same originator, beneficiary, amount, and date within window | Payment history, duplicate policy | Confirm distinct, or suppress | **No.** Judgment about intent, and the duplicate release policy is customer-specific. |

Notes:
- EX-01 is the highest-volume type and the least auto-eligible. That is the honest shape of this problem, and it is why the value is mostly in making the human decision fast rather than in removing the human.
- EX-02 and EX-03 are where straight-through processing actually comes from. They are also the two where counterparty history does the heavy lifting.

---

## 3. Gate list

Evaluated in order. First gate that fires wins. All are deterministic.

| Gate | Condition | Result |
|---|---|---|
| **G0** | Sanctions or OFAC status is not `clear` | Hard stop. Route to compliance. Never auto, never overridable in-app. |
| **G1** | Proposed fix changes `beneficiary_account` | Human approval required, always, at any amount |
| **G2** | Proposed fix changes `amount` or `currency` | Hard stop. Agent may not propose this at all. |
| **G3** | `amount_usd` > auto-apply threshold (default $250,000, configurable per customer) | Human approval required |
| **G4** | `first_time_counterparty` is true (no prior payment between this originator and beneficiary) | Human approval required |
| **G5** | `confidence` < 0.85 | Human approval required |
| **G6** | Cross-border, or currency is not USD | Human approval required in phase 1 |
| **G7** | Exception code is `EX-07` (duplicate suspect) | Human approval required |
| **G8** | Same-day cumulative value to this beneficiary exceeds velocity threshold | Human approval required |
| **G9** | Agent outcome is `EXHAUSTED`, `AMBIGUOUS`, or `NEEDS_INFO` | Escalate with full trace |
| **G10** | Time remaining to rail cutoff < 30 minutes | Escalate immediately with priority flag, regardless of confidence. Do not spend the remaining window on agent iteration. |

**G10 is worth demoing.** It is the gate that shows the system understands the business, not just the data.

### Configurability
Thresholds in G3, G5, G8, and G10 are per-customer configuration in Data Fabric, not hardcoded. G0, G1, and G2 are not configurable. That distinction is the conversation to have with a bank's risk officer, and having drawn the line already is what makes this credible.

---

## 4. Escalation contract

An escalation is not an item dumped in an inbox. Every human task carries:

1. The payment record with the failing field highlighted
2. The proposed fix, pre-filled and editable
3. Which gate fired, and why, in plain language
4. The evidence list: every tool called, what it returned, and the confidence contribution
5. Time remaining to cutoff
6. One-click approve, edit, reject, escalate

**Target: 20 seconds to a human decision.** That is the number to hold the build to, and it is where most of the value in this process actually sits.

---

## 5. Things the agent may never do

Independent of gates, and worth stating separately because it is a design constraint rather than a runtime check:

- Release a payment. The agent proposes; a robot or a human applies.
- Modify a sanctions screening result or re-run screening to obtain a different answer.
- Contact a client directly without a human on the line.
- Write to the core banking system. All writes go through a robot or API workflow with its own credentials and audit trail.
- Invent a beneficiary account number that is not sourced from a lookup, standing instruction, or prior payment. Every proposed value must be traceable to a tool result in `evidence[]`.
