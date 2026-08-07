from importlib import import_module

import pytest


def test_contract_package_exposes_required_models() -> None:
    try:
        contracts = import_module("src.contracts")
    except ModuleNotFoundError:
        pytest.fail("src.contracts must be importable")

    required = {
        "AgentOutput",
        "CounterpartyHistory",
        "Evidence",
        "GateContext",
        "PaymentCase",
        "PaymentFixture",
        "PolicyConfig",
        "PolicyDecision",
        "ProposedAction",
        "EvidenceType",
        "GateId",
        "Outcome",
        "PolicyPath",
        "ProposedField",
        "SanctionsStatus",
    }
    assert required <= set(dir(contracts))
