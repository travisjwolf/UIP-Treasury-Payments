# Fixture data

The files in this directory are synthetic test data for the UiPath AMER SE Build Challenge. They are engineered to exercise the demo paths and must not be described as Ameris Bank production data or as a measured distribution of real exceptions.

## Files

- `payments.csv` contains 40 payment cases. `expected_outcome` is the repair-agent result and `expected_path` is the deterministic routing result used by the gate tests.
- `counterparty_history.csv` contains prior beneficiary relationships used by the read-only tool layer.
- `cases/` is created by Alpha during the contract checkpoint. It contains one JSON input per payment row and the expected result needed by the local agent runner.

Three payment rows are pinned for the demo: `WIRE-8802` auto-resolves, `WIRE-8841` is blocked by policy and sent to a human, and `WIRE-8877` follows the assisted-callback path.

Regenerate the CSV fixtures from the repository root with:

```powershell
python scripts/generate_fixtures.py
```

The generator uses a fixed seed. Review changes to both CSV files before committing them because fixture changes are contract changes for downstream branches.

Generate the validated per-case JSON envelopes after installing the Python dependencies:

```powershell
python -m pip install -r requirements-dev.txt
python -m src.contracts.fixtures
python -m pytest tests/contracts -v
```

Each case envelope keeps the published `PaymentCase` fields separate from deterministic `GateContext` inputs and the expected demo result.
