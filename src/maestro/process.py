from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Protocol

from src.apps.action_center import EscalationPayload
from src.contracts.models import (
    AgentOutput,
    GateContext,
    PaymentCase,
    PolicyConfig,
    PolicyDecision,
)
from src.effectors.stub import (
    Effector,
    EffectorAuthorization,
    EffectorResult,
)
from src.maestro.ledger import InMemoryLedger


class RepairAgent(Protocol):
    def analyze(
        self,
        case: PaymentCase,
        fixture: dict[str, Any],
    ) -> AgentOutput | Awaitable[AgentOutput]:
        ...


class GateEvaluator(Protocol):
    def evaluate(
        self,
        case: PaymentCase,
        agent_output: AgentOutput,
        gate_context: GateContext,
        policy_config: PolicyConfig,
    ) -> PolicyDecision:
        ...


class PolicyConfigProvider(Protocol):
    def for_case(self, case: PaymentCase) -> PolicyConfig:
        ...


@dataclass(frozen=True)
class ProcessResult:
    case_id: str
    payment: PaymentCase
    path: str
    agent_output: AgentOutput
    decision: PolicyDecision
    escalation: EscalationPayload | None = None
    effector_result: EffectorResult | None = None


class PaymentProcess:
    def __init__(
        self,
        agent: RepairAgent,
        gate: GateEvaluator,
        effector: Effector,
        ledger: InMemoryLedger,
        *,
        policy_config_provider: PolicyConfigProvider,
    ):
        self.agent = agent
        self.gate = gate
        self.effector = effector
        self.ledger = ledger
        self.policy_config_provider = policy_config_provider

    def run(self, fixture: dict[str, Any]) -> ProcessResult:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.run_async(fixture))
        raise RuntimeError("run() cannot be used inside an event loop; await run_async()")

    async def run_async(self, fixture: dict[str, Any]) -> ProcessResult:
        canonical_fixture = _canonical_fixture(fixture)
        case = PaymentCase.model_validate(canonical_fixture["payment_case"])
        gate_context = GateContext.model_validate(canonical_fixture["gate_context"])
        self.ledger.append(case.case_id, "INTAKE_RECEIVED", case.current_queue or "repair")
        self.ledger.append(
            case.case_id,
            "AGENT_INVESTIGATION_STARTED",
            "Read-only repair investigation started.",
            actor="repair-agent",
        )

        candidate = self.agent.analyze(case, canonical_fixture)
        if inspect.isawaitable(candidate):
            candidate = await candidate
        agent_output = AgentOutput.model_validate(candidate)
        self.ledger.append(
            case.case_id,
            "AGENT_PROPOSED",
            agent_output.outcome.value,
            actor="repair-agent",
            data={"confidence": agent_output.confidence},
        )

        policy_config = self.policy_config_provider.for_case(case)
        decision = self.gate.evaluate(
            case,
            agent_output,
            gate_context,
            policy_config,
        )
        gate_value = getattr(decision.gate, "value", decision.gate) or "NONE"
        self.ledger.append(
            case.case_id,
            "GATE_EVALUATED",
            f"{gate_value}:{decision.result.value}",
            actor="deterministic-policy-gate",
            occurred_at=decision.evaluated_at.isoformat(),
            data={"gate": gate_value, "result": decision.result.value},
        )

        if decision.result.value == "AUTO_APPLY":
            if agent_output.proposed_action is None:
                raise ValueError("AUTO_APPLY requires a proposed action")
            self.ledger.append(
                case.case_id,
                "AUTO_APPLY_AUTHORIZED",
                decision.reason,
                actor="deterministic-policy-gate",
            )
            effector_result = self.effector.apply(
                case,
                agent_output.proposed_action,
                evidence=agent_output.evidence,
                authorization=EffectorAuthorization.from_policy(decision),
            )
            self.ledger.append(
                case.case_id,
                "EFFECT_RECORDED",
                effector_result.status,
                actor=effector_result.audit.credential_identity,
                data={
                    "field": effector_result.audit.field,
                    "before": effector_result.audit.before,
                    "after": effector_result.audit.after,
                    "payment_write_performed": False,
                },
            )
            self.ledger.append(
                case.case_id,
                "CASE_STATE_UPDATED",
                "AUTO_APPLY_SANDBOX_RECORDED",
                actor="payment-process",
            )
            return ProcessResult(case.case_id, case, "auto_apply", agent_output, decision, effector_result=effector_result)

        self.ledger.append(
            case.case_id,
            "AUTONOMY_REFUSED",
            decision.reason,
            actor="deterministic-policy-gate",
            data={"gate": gate_value},
        )
        path = _policy_path(decision)
        if path == "compliance_referral":
            self.ledger.append(
                case.case_id,
                "COMPLIANCE_REFERRAL_CREATED",
                decision.reason,
                actor="payment-process",
                data={"gate": gate_value, "overridable_in_app": False},
            )
            return ProcessResult(
                case.case_id,
                case,
                path,
                agent_output,
                decision,
            )

        callback = path == "callback_then_human"
        permitted = (
            ("provide_info", "approve", "reject", "escalate")
            if callback
            else ("approve", "edit", "reject", "escalate")
        )
        escalation = EscalationPayload(
            payment=case,
            proposal=agent_output.proposed_action,
            gate=decision.gate,
            reason=decision.reason,
            evidence=agent_output.evidence,
            cutoff_time=case.cutoff_time,
            permitted_actions=permitted,
        )
        if callback:
            self.ledger.append(
                case.case_id,
                "CALLBACK_REQUIRED",
                decision.reason,
                actor="payment-process",
            )
        self.ledger.append(
            case.case_id,
            "HUMAN_ESCALATION_CREATED",
            gate_value,
            actor="payment-process",
            data={"permitted_actions": list(permitted)},
        )
        return ProcessResult(case.case_id, case, path, agent_output, decision, escalation=escalation)


def _policy_path(decision: PolicyDecision) -> str:
    return {
        "AUTO_APPLY": "auto_apply",
        "COMPLIANCE_REFERRAL": "compliance_referral",
        "CALLBACK_THEN_HUMAN": "callback_then_human",
        "HUMAN_APPROVAL": "human_approval",
        "HARD_STOP": "human_approval",
        "PRIORITY_ESCALATION": "human_approval",
        "ESCALATE": "human_approval",
    }[decision.result.value]


def _canonical_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    if "payment_case" in fixture:
        return fixture
    if "payment" not in fixture or "fixture_metadata" not in fixture:
        return fixture

    payment = fixture["payment"]
    metadata = fixture["fixture_metadata"]
    canonical = {
        "payment_case": payment,
        "gate_context": {
            "sanctions_status": metadata["sanctions_flag"],
            "first_time_counterparty": metadata["first_time_counterparty"],
            "same_day_beneficiary_total_usd": payment["amount_usd"],
            "cross_border": payment["currency"] != "USD",
            "evaluated_at": metadata["received_at"],
            "cutoff_at": metadata["cutoff_at"],
        },
        "demo_role": metadata.get("demo_role") or None,
    }
    for optional_fixture_field in ("expected_outcome", "expected_path"):
        if optional_fixture_field in fixture:
            canonical[optional_fixture_field] = fixture[optional_fixture_field]
    return canonical
