# Business case skeleton: payment operations

Three layers. Build them in this order, present them in reverse.

The FTE model is the floor and it is defensible. The deposit model is the ceiling and it is the one a CFO acts on. Do not lead with the floor and do not claim the ceiling can be proven from a demo.

All inputs below are placeholders. Nothing here is Ameris data.

---

## Layer 1: Operational cost (the backstop)

The model in the existing Treasury Operations Solution Kit. Conservative, easy to defend, and small.

| Input | Placeholder | Source needed |
|---|---|---|
| Annual payment volume | 1,000,000 | Customer, six-month queue export annualized |
| Exception rate | 10% | Customer. **Validate the "1 in 5" figure before using it.** |
| Total exceptions | 100,000 | Calculated |
| Average handle time (min) | 10 | Customer. Handle time is bimodal, so model two tiers rather than one blended average |
| Productive FTE hours | 1,920 | Standard |
| Fully loaded cost per hour | $46.88 | Customer or benchmark |
| **Current annual cost** | **$781,250** | Calculated |
| Target STP uplift on repair-eligible items | 30-40% | From the taxonomy: EX-02, EX-03, EX-05, EX-06 are the auto-eligible set |
| Handle-time reduction on escalated items | 8 min → 20 sec | The escalation contract is what delivers this |

**Model the second effect separately.** Most of this process does not become autonomous. It becomes fast. A 95% reduction in handle time on the 65% of items that still need a human is a larger number than full autonomy on the 35% that do not, and it is far more credible.

---

## Layer 2: Capacity (the bridge)

Ameris stated the objective directly: grow without increasing headcount. This layer converts that into money.

| Input | Placeholder | Source |
|---|---|---|
| Current treasury management client count | | Customer |
| Payment ops FTE | | Customer |
| Payments per FTE per year | | Calculated |
| TM client growth target | | Customer strategy |
| FTE required to serve that growth at current productivity | | Calculated |
| Fully loaded FTE cost | | Customer |
| **Avoided hiring** | | Calculated |

The argument: TM client growth is currently gated by ops capacity. Every new commercial relationship adds payment volume, and payment volume adds exceptions linearly. Automation breaks that link.

This layer is stronger than layer 1 because it is forward-looking and it maps to a plan the bank already has.

---

## Layer 3: Deposits (the ceiling)

The strategic argument. Handle it carefully, because the attribution is genuinely contestable and someone in the room will know that.

### The mechanism
Commercial operating deposits are the cheapest funding on the balance sheet and the stickiest. The operating account is anchored by payment rails and service quality, not by rate. Payment operations performance is therefore a funding cost lever, not just an expense line.

### Three defensible framings, in order of strength

**A. Defensive — deposit at risk**

| Input | Source |
|---|---|
| Commercial deposit balances by client | Customer |
| Payment service incidents per client (delays, repairs, missed cutoffs) | Producible from the case ledger |
| Balances held by the worst-served decile | Calculated |
| Historical attrition rate among clients with service incidents | Customer, if they track it |

This is the "client friction leaderboard" screen. No bank currently joins payment exception data to relationship balances, which is exactly why it lands. Frame it as visibility into risk, not as a promise of retention.

**B. Cost of funds sensitivity**

| Input | Placeholder |
|---|---|
| Commercial deposit book | $2.0B |
| Current blended cost of funds | |
| Basis point movement from a 1% shift in operating vs. time deposit mix | |
| **Value of 10 bps** | **$2.0M/yr** |

Compare to $781K of ops labor. Same bank, same year. Use it to size the prize, not to claim you will deliver it.

**C. RFP scorecard**

Treasury management RFPs score operational SLAs explicitly: wire cutoff times, exception resolution SLA, error rates, reporting. This is a concrete, winnable line item with no attribution problem at all. Ask the customer for their last three RFP scorecards.

### What not to claim
Do not model "faster wire repair generates $X in new deposits." You cannot support it and it will discredit the rest of the case. Attribution runs the other way: deposits are lost for service reasons more reliably than they are won for them.

---

## Presentation order

1. **Layer 3C (RFP)** — concrete, no attribution problem, opens the strategic frame
2. **Layer 3A (deposit at risk)** — the screen nobody else can show
3. **Layer 2 (capacity)** — maps to a growth plan they already have
4. **Layer 1 (FTE)** — "and here is the conservative floor, before any of that"

Leading with layer 1 anchors the whole conversation at $781K and you never recover the strategic frame.

---

## Inputs to request from the customer

- Six-month queue volume export by queue and exception reason
- Payment ops headcount and org structure
- TM client count and growth target
- Commercial deposit balances by client segment
- Last three TM RFP scorecards
- Current wire and ACH cutoff times and published SLAs
- Any tracked service incident or complaint data
