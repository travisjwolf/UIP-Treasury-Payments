# Wire repair pre-work

Pre-work for the UiPath AMER SE Build Challenge, Friday 7 August 2026. Treasury payments use case.

**We are not building yet.** Everything here is design and test data, which is what the offsite asked for. Building starts Friday.

---

## Start here

If you have five minutes: read §"The idea" below, then `docs/PDD-wire-repair.md`.

If you are about to build: read `AGENTS.md`, then `docs/three-instance-build-plan.md`. The plan assigns the work to the `alpha`, `bravo`, and `charlie` branches and includes the prompts to start each Codex instance.

---

## The idea

**What we are building:** a Payment Operations Control Tower. A UiPath process app that is the single pane of glass over every in-flight payment at a commercial bank, with Maestro running one long-lived case per payment, coded agents making judgment calls, robots executing, and humans pulled in only where a deterministic policy gate says so.

**Why treasury:** commercial operating deposits are the cheapest and stickiest funding a regional bank has, and the operating account is anchored by payment rails and service quality rather than by rate. Treasury operations performance is a funding cost lever disguised as an ops cost lever. That reframes the pitch from "save FTEs" to "protect and grow the deposit book."

**Where it came from:** two Ameris Bank discovery sessions in July on their wire repair queue. The repair queue is the largest by volume and sits directly on the settlement critical path.

**The reference lane:** wire repair. Payments that fail automated validation and wait for a human to determine the correct value of a failing field.

---

## What is in here

| File | What it is |
|---|---|
| `AGENTS.md` | Full build context: stack, data contracts, hard rules, build order, starting prompt. Codex and Claude Code read this automatically. |
| `docs/PDD-wire-repair.md` | One-page process design document, grounded in the Ameris transcripts. Feeds `uipath-planner` on Friday to produce the SDD. |
| `docs/exception-taxonomy-and-gates.md` | Seven exception types with resolution paths, six typed outcomes, eleven deterministic policy gates. The domain thinking. |
| `docs/three-instance-build-plan.md` | Phase-gated Alpha / Bravo / Charlie execution plan, ownership map, prompts, and merge protocol. |
| `docs/business-case-skeleton.md` | Three-layer model: deposits, capacity, FTE. Not needed for the build. |
| `fixtures/payments.csv` | 40 synthetic payment cases with expected outcomes |
| `fixtures/counterparty_history.csv` | Prior repair history the agent reasons over |
| `scripts/generate_fixtures.py` | Regenerate or reshape the fixture data |

---

## The one design decision to understand

The system splits into two halves and the split is the whole product argument.

**The agent decides what the fix should be.** It investigates, calls tools, and returns a proposal with evidence and a confidence score.

**Deterministic code decides whether that fix may be applied.** Gates are plain logic, unit-testable, no model call. A gate can block a proposal the agent is 99% confident in, and it should.

Keeping gates out of the model is what makes this sellable into a bank. If anyone suggests letting the model evaluate policy, that is the thing to push back on.

The most important demo case is `WIRE-8841`, where the agent finds the right answer and the system refuses to act on it anyway, because the fix would change a beneficiary account. That refusal is the feature.

---

## Before Friday

- [ ] `npm -g install @uipath/cli` and `uip skills install`
- [ ] `uip login` works against a tenant you can actually deploy to
- [ ] `uip codedagent init` scaffolds and runs locally
- [ ] Read `AGENTS.md`
- [ ] Confirm the `alpha`, `bravo`, and `charlie` branches exist on `origin`
- [ ] Read `docs/three-instance-build-plan.md` and claim one role per person
- [ ] Sanity-check the volume assumptions in `docs/PDD-wire-repair.md` §9 if you have access to the Ameris queue data

Everyone on the team should have a working coding-agent setup before Friday morning. The build plan assumes at least three people can each run an independent branch. If it is two, the effectors stay stubbed permanently.

---

## Honest caveats

- **All fixture data is synthetic and its distribution is engineered for the demo.** See `fixtures/README.md`. Do not quote any of it as measured.
- **The "1 in 5 wires needs manual intervention" figure from Ameris is unvalidated.** If it is a true repair rate it is a strong wedge. If it counts any queue touch, the business case inflates. See `docs/PDD-wire-repair.md` §9.
- **Autonomous outbound voice verification is deliberately out of scope.** Callback verification is the last human control against business email compromise. The agent-assisted version, where a transcript is captured and reconciled against the payment record while a human keeps the decision, is in scope and is the better demo anyway.
- **Only about 30% of the fixture set is auto-applicable.** That is the honest shape of wire repair, not a modelling failure. Most of the value is in making the human decision take 20 seconds instead of 8 minutes. Pitch it that way.
