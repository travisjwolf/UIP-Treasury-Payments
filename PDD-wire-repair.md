# Process Design Document: Wire Repair Queue

**Process:** Inbound and outbound wire exception repair
**Domain:** Commercial bank treasury / payment operations
**Source:** Ameris Bank discovery sessions, 20 and 23 July 2026 (use case 3, "Wire Repair Queue")
**Status:** Draft for `uipath-planner` ingestion. Volumes unvalidated, see §9.

---

## 1. Business context

Commercial operating deposits are the cheapest and stickiest funding a regional bank has, and the operating account is anchored by payment rails and service quality, not by rate. A wire that misses cutoff is a client cash-positioning problem the treasurer notices the same day.

The repair queue is where wires that fail automated validation wait for a human. It is the largest queue by volume and it sits directly on the settlement critical path.

Stated customer objective (Ameris, 20 July): grow without increasing headcount.

## 2. Current state

Wire processing at Ameris runs through a set of queues in FIS:

| Queue | Where it happens | In scope |
|---|---|---|
| Fed wire queue | Branch / back office. Wire keyed, waiting on a teammate to verify. | No, unless ops approves on the customer's behalf because no approver with the right credentials or limits is available |
| First verify | Branch / back office | No, same exception as above |
| Second verify (incl. NSF / fund control) | Loan ops team | Yes |
| Callback | Loan ops team. Team calls the **customer** directly to verify wires entered by phone or fax; customer provides wire instruction detail and a PIN. Does not apply to standard branch-keyed wires. | Partial, see §7 |
| **Repair** | Loan ops team | **Yes, primary** |

Handling time is bimodal. Moving an item between queues is a few clicks and takes seconds. Anything requiring outreach (NSF funding, missing party detail) takes materially longer because it blocks on a third party.

## 3. Trigger

A payment fails automated validation on intake and is routed to the repair queue. Intake channels observed: branch teller, online banking, file upload, phone, fax.

## 4. Current process steps

1. Analyst opens the repair queue and selects the oldest or highest-value item.
2. Reads the failure reason and the payment record.
3. Investigates: looks up the beneficiary in the core, checks whether this counterparty has been paid before, checks standing instructions, checks the originating document or file.
4. Determines the correct value for the failing field.
5. Applies the repair in FIS, or routes the item to another queue, or contacts the branch or client for missing information.
6. Releases the payment or returns it to the queue for verification.

## 5. Exception types

See `docs/exception-taxonomy-and-gates.md` for the full taxonomy with detection signals and resolution paths. Summary: beneficiary account not found, name/account mismatch, missing intermediary routing, insufficient party identification, unstructured or truncated remittance, format or currency mismatch, duplicate suspect.

## 6. Business rules and controls

Policy documents pending from Ameris and FIS (John Sims / James Battle, 23 July): duplicate release policies, return logging, customer callback procedures, temporary limit increase procedures. Wire policy and procedure has been uploaded to the Ameris SharePoint under use case 3.

Known controls that must survive automation:
- Dual control on wire release
- Callback verification for phone and fax originated wires
- Sanctions screening before release
- Dollar-threshold approval limits by role

Redundant manual checks exist specifically to catch human error and have been added in response to audit findings. That is a stated pattern at Ameris (20 July, on the lending QC process): when a control gap is found, the remediation is another manual control, because there is no automation in place. This is the wedge.

## 7. Target state

A Maestro-orchestrated case per payment. A repair agent investigates, proposes a fix with evidence and a confidence score, and returns a typed outcome. A deterministic policy gate decides whether the proposed fix may be auto-applied or must go to a human. Robots and API workflows execute against FIS and the core. Humans see an Action Center task pre-filled with the proposal and the evidence, so the decision takes seconds rather than minutes.

Every state transition is written to a case ledger, which serves both the audit trail and a feedback signal to intake: which origination channel and which field are generating the repairs.

**Callback scope decision:** automating an outbound verification call that collects a PIN and releases a wire is out of scope. It is the last human control against business email compromise. In scope is agent-assisted callback: transcription, entity extraction, and live reconciliation of what the client states against the payment record, with the transcript filed as case evidence. The human keeps the decision.

## 8. In scope / out of scope

**In:** repair queue, second verify including NSF fund control, and the queues covered in the 23 July session. Wire rail first; ACH returns and notifications of change as a second lane to prove the spine is rail-agnostic.

**Out:** fed wire queue and first verify (branch-level). Autonomous outbound voice verification. Any repair that changes the beneficiary account, the amount, or the currency without human approval.

## 9. Volumes and assumptions

Ameris provided six months of queue volume for annualization. Two numbers need validation before either is used in a customer-facing business case:

1. **"1 in 5 incoming wires requires manual intervention before settling."** If this is a true repair rate it is far worse than typical wire STP and it is a strong wedge. If it is actually "1 in 5 wires is touched by any queue," the business case inflates. Cross-check queue volume times handle time against the actual headcount doing the work and see whether it maps to FTE count.
2. **Handle time per queue.** Ameris confirmed the team does not track time by queue item type, and described handling as bimodal (seconds for a reroute, much longer for anything needing outreach). A single blended average will be wrong in both directions.

Fixtures in `fixtures/` are synthetic and their distribution is engineered for the demo. They are not Ameris data.

## 10. Success metrics

| Metric | Why it matters |
|---|---|
| Straight-through processing rate on repair-eligible items | The automation headline |
| Time to resolve, by exception type | The client-facing consequence |
| Payments cleared before rail cutoff | The metric a treasurer actually feels |
| Human touches per payment | Where the cost sits |
| Repairs by origination channel and field | The shift-left signal that eventually kills the queue |
| Delayed or repaired payments by commercial client, with balances | The deposit-at-risk view |

## 11. Open questions for the customer

1. What is the actual repair-reason distribution in the queue over the last six months?
2. Which repairs are applied by the ops team versus routed back to the branch or the client?
3. What is the current dollar threshold and role matrix for wire approval?
4. Are repair actions in FIS available via API, or is UI automation required?
5. What is retained today about a repair, and for how long? (Determines whether counterparty history can be built from existing data or needs to accumulate.)
6. Which controls are regulatory versus internal remediation for past audit findings? The 20 July session suggested several are the latter and could be consolidated.
