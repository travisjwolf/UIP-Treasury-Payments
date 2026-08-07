"""
Generate synthetic wire repair fixtures for the AMER SE Build Challenge.

Produces:
  fixtures/payments.csv              40 payment cases with a realistic repair-reason mix
  fixtures/counterparty_history.csv  prior repair history the agent reasons over

The data is DELIBERATELY ENGINEERED so the demo narrative works:
  - two hero cases (auto-resolve, gate-blocked) are pinned and labelled
  - the phone/fax origination channel is over-represented in repairs so the
    shift-left chart has something true to say
  - roughly a third of beneficiaries recur, which is what makes the
    counterparty-history lookup beat a rules engine

None of this is Ameris data. See fixtures/README.md before quoting any number.

Run:  python scripts/generate_fixtures.py
"""

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

random.seed(8841)

OUT = Path(__file__).resolve().parent.parent / "fixtures"
OUT.mkdir(exist_ok=True)

# ---------------------------------------------------------------- taxonomy

# (code, weight) - weights are a plausible mix, NOT measured. Replace with the
# real distribution once Ameris queue data lands.
EXCEPTIONS = [
    ("EX-01", "beneficiary_account_not_found", 28),
    ("EX-02", "name_account_mismatch", 22),
    ("EX-03", "missing_intermediary_routing", 14),
    ("EX-04", "insufficient_party_identification", 12),
    ("EX-05", "unstructured_remittance", 10),
    ("EX-06", "format_currency_mismatch", 8),
    ("EX-07", "duplicate_suspect", 6),
]

# Channel mix is skewed on purpose: phone/fax is ~14% of volume but ~38% of
# repairs. That gap is the shift-left story.
CHANNELS = [
    ("branch_teller", 26),
    ("online_banking", 22),
    ("file_upload", 16),
    ("phone_fax", 36),
]

RAILS = [("Fedwire", 62), ("ACH", 24), ("RTP", 8), ("Book", 6)]

COMMERCIAL_CLIENTS = [
    ("CUST-1042", "Ridgeline Construction LLC"),
    ("CUST-1188", "Harbor Point Logistics Inc"),
    ("CUST-1233", "Sawyer Medical Group PA"),
    ("CUST-1301", "Delta Ag Supply Co"),
    ("CUST-1355", "Northgate Property Partners"),
    ("CUST-1409", "Kestrel Manufacturing Corp"),
    ("CUST-1477", "Blue Fern Hospitality LLC"),
    ("CUST-1520", "Tidewater Freight Systems"),
]

BENEFICIARIES = [
    "PACIFIC STEEL & SUPPLY",
    "MERIDIAN EQUIPMENT LEASING",
    "COASTAL FUEL DISTRIBUTORS",
    "ATLAS TITLE & ESCROW",
    "SUMMIT PAYROLL SERVICES",
    "GRANITE ROOFING SUPPLY",
    "VERTEX MEDICAL DEVICES",
    "IRONWOOD LUMBER CO",
    "CLEARWATER SANITATION",
    "HALLMARK FREIGHT BROKERS",
    "NORTHSTAR INSURANCE TR",
    "EVERGREEN AG SERVICES",
    "KEYSTONE MACHINE WORKS",
    "BRIGHTLINE ELECTRICAL",
]


def weighted(pairs):
    vals = [p[0] if len(p) == 2 else p[:-1] for p in pairs]
    wts = [p[-1] for p in pairs]
    return random.choices(vals, weights=wts, k=1)[0]


def acct(n=10):
    return "".join(random.choice("0123456789") for _ in range(n))


# ------------------------------------------------- counterparty history

history = []
recurring = BENEFICIARIES[:9]   # these have prior repair history
one_off = BENEFICIARIES[9:]     # these do not -> agent must escalate

for name in recurring:
    for cust_id, _ in random.sample(COMMERCIAL_CLIENTS, k=random.randint(1, 3)):
        seen = random.randint(4, 34)
        repaired = random.randint(2, max(2, seen // 2))
        history.append({
            "customer_id": cust_id,
            "beneficiary_name": name,
            "beneficiary_account": acct(),
            "times_seen": seen,
            "times_repaired": repaired,
            "last_applied_fix": random.choice([
                "append_check_digit",
                "normalize_name_to_registered_entity",
                "add_intermediary_aba",
                "expand_truncated_account",
                "correct_transposed_digits",
            ]),
            "history_confidence": round(min(0.98, 0.55 + repaired * 0.045), 2),
        })

# pinned high-confidence counterparty for the auto-resolve hero case
history.append({
    "customer_id": "CUST-1042",
    "beneficiary_name": "PACIFIC STEEL & SUPPLY",
    "beneficiary_account": "8823004417",
    "times_seen": 31,
    "times_repaired": 11,
    "last_applied_fix": "expand_truncated_account",
    "history_confidence": 0.94,
})

with open(OUT / "counterparty_history.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(history[0].keys()))
    w.writeheader()
    w.writerows(history)

# ------------------------------------------------------------- payments

base = datetime(2026, 8, 7, 8, 15)
rows = []

# --- hero case 1: auto-resolves. Known counterparty, non-beneficiary field,
#     under threshold. Every gate clears.
rows.append({
    "case_id": "WIRE-8802",
    "demo_role": "hero_auto_resolve",
    "rail": "Fedwire",
    "direction": "outbound",
    "amount_usd": 84500.00,
    "currency": "USD",
    "value_date": "2026-08-07",
    "cutoff_time": "17:00",
    "source_channel": "file_upload",
    "customer_id": "CUST-1042",
    "customer_name": "Ridgeline Construction LLC",
    "beneficiary_name": "PACIFIC STEEL & SUPPY",
    "beneficiary_account": "8823004417",
    "beneficiary_bank_aba": "121000248",
    "remittance_info": "INV 44821 STEEL DELIVERY",
    "exception_code": "EX-02",
    "exception_type": "name_account_mismatch",
    "first_time_counterparty": "false",
    "sanctions_flag": "clear",
    "expected_outcome": "RESOLVED",
    "expected_path": "auto_apply",
    "received_at": (base + timedelta(minutes=3)).isoformat(timespec="minutes"),
})

# --- hero case 2: gate-blocked. Same exception family, but the fix would
#     change the beneficiary account -> G1 fires, human decides.
rows.append({
    "case_id": "WIRE-8841",
    "demo_role": "hero_gate_blocked",
    "rail": "Fedwire",
    "direction": "outbound",
    "amount_usd": 2450000.00,
    "currency": "USD",
    "value_date": "2026-08-07",
    "cutoff_time": "17:00",
    "source_channel": "phone_fax",
    "customer_id": "CUST-1042",
    "customer_name": "Ridgeline Construction LLC",
    "beneficiary_name": "PACIFIC STEEL & SUPPLY",
    "beneficiary_account": "882300441",
    "beneficiary_bank_aba": "121000248",
    "remittance_info": "PROGRESS DRAW 7",
    "exception_code": "EX-01",
    "exception_type": "beneficiary_account_not_found",
    "first_time_counterparty": "false",
    "sanctions_flag": "clear",
    "expected_outcome": "BLOCKED_POLICY",
    "expected_path": "human_approval",
    "received_at": (base + timedelta(minutes=41)).isoformat(timespec="minutes"),
})

# --- hero case 3 (stretch): callback transcript reconciliation
rows.append({
    "case_id": "WIRE-8877",
    "demo_role": "hero_callback",
    "rail": "Fedwire",
    "direction": "outbound",
    "amount_usd": 615000.00,
    "currency": "USD",
    "value_date": "2026-08-07",
    "cutoff_time": "17:00",
    "source_channel": "phone_fax",
    "customer_id": "CUST-1355",
    "customer_name": "Northgate Property Partners",
    "beneficiary_name": "ATLAS TITLE & ESCROW",
    "beneficiary_account": "4471902288",
    "beneficiary_bank_aba": "053000196",
    "remittance_info": "CLOSING FILE NG-2291",
    "exception_code": "EX-04",
    "exception_type": "insufficient_party_identification",
    "first_time_counterparty": "false",
    "sanctions_flag": "clear",
    "expected_outcome": "NEEDS_INFO",
    "expected_path": "callback_then_human",
    "received_at": (base + timedelta(minutes=52)).isoformat(timespec="minutes"),
})

# --- the rest
for i in range(37):
    code, etype = weighted([(e[:2], e[2]) for e in EXCEPTIONS])
    channel = weighted(CHANNELS)
    # bias phone_fax toward the harder exception types
    if channel == "phone_fax" and random.random() < 0.30:
        code, etype = random.choice([("EX-01", "beneficiary_account_not_found"),
                                     ("EX-04", "insufficient_party_identification")])
    name = random.choice(BENEFICIARIES)
    first_time = "true" if name in one_off and random.random() < 0.7 else "false"
    amount = round(random.choice([
        random.uniform(2_500, 95_000),
        random.uniform(95_000, 250_000),
        random.uniform(250_000, 4_000_000),
    ]), 2)
    sanctions = "review" if random.random() < 0.05 else "clear"
    cust_id, cust_name = random.choice(COMMERCIAL_CLIENTS)

    if sanctions == "review":
        outcome, path = "BLOCKED_POLICY", "compliance_referral"
    elif first_time == "true":
        outcome, path = "AMBIGUOUS", "human_approval"
    elif amount > 250_000 or code == "EX-01":
        outcome, path = "RESOLVED_LOW_CONFIDENCE", "human_approval"
    elif code == "EX-07":
        outcome, path = "AMBIGUOUS", "human_approval"
    else:
        outcome, path = "RESOLVED", "auto_apply"

    rows.append({
        "case_id": f"WIRE-{8900 + i}",
        "demo_role": "",
        "rail": weighted(RAILS),
        "direction": random.choice(["outbound", "inbound"]),
        "amount_usd": amount,
        "currency": "USD" if random.random() > 0.06 else random.choice(["EUR", "GBP", "CAD"]),
        "value_date": "2026-08-07",
        "cutoff_time": "17:00",
        "source_channel": channel,
        "customer_id": cust_id,
        "customer_name": cust_name,
        "beneficiary_name": name,
        "beneficiary_account": acct(random.choice([9, 10, 10, 11])),
        "beneficiary_bank_aba": random.choice(
            ["121000248", "053000196", "026009593", "111000025", "021000021"]),
        "remittance_info": random.choice([
            "INV 90112", "PAYROLL FUNDING", "EQUIP PMT", "SETTLEMENT",
            "", "REF 88-2210 PARTIAL", "MONTHLY DRAW",
        ]),
        "exception_code": code,
        "exception_type": etype,
        "first_time_counterparty": first_time,
        "sanctions_flag": sanctions,
        "expected_outcome": outcome,
        "expected_path": path,
        "received_at": (base + timedelta(minutes=random.randint(1, 300))).isoformat(timespec="minutes"),
    })

fields = list(rows[0].keys())
with open(OUT / "payments.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(rows)

# ---------------------------------------------------------------- summary
from collections import Counter
print(f"payments.csv: {len(rows)} rows")
print("exception mix:", dict(Counter(r["exception_type"] for r in rows)))
print("channel mix:", dict(Counter(r["source_channel"] for r in rows)))
print("expected path:", dict(Counter(r["expected_path"] for r in rows)))
print(f"counterparty_history.csv: {len(history)} rows")
pf = [r for r in rows if r["source_channel"] == "phone_fax"]
print(f"phone_fax share of repairs: {len(pf)/len(rows):.0%}")
