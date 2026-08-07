from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from src.apps.action_center import EscalationPayload
from src.contracts.models import AgentOutput, PaymentCase, PolicyDecision
from src.effectors.stub import Effector, EffectorResult
from src.maestro.ledger import InMemoryLedger


class RepairAgent(Protocol):
    def analyze(self, case: PaymentCase, fixture: dict[str, Any]) -> AgentOutput:
        ...


class GateEvaluator(Protocol):
    def evaluate(self, case: PaymentCase, agent_output: AgentOutput) -> PolicyDecision:
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
    def __init__(self, agent: RepairAgent, gate: GateEvaluator, effector: Effector, ledger: InMemoryLedger):
        self.agent = agent
        self.gate = gate
        self.effector = effector
        self.ledger = ledger

    def run(self, fixture: dict[str, Any]) -> ProcessResult:
        case = PaymentCase.from_fixture(fixture)
        self.ledger.append(case.case_id, "INTAKE_RECEIVED", case.current_queue or "repair")

        agent_output = self.agent.analyze(case, fixture)
        self.ledger.append(case.case_id, "AGENT_PROPOSED", agent_output.outcome)

        decision = self.gate.evaluate(case, agent_output)
        self.ledger.append(case.case_id, "GATE_EVALUATED", f"{decision.gate}:{decision.result}")

        if decision.result == "AUTO_APPLY":
            if agent_output.proposed_action is None:
                raise ValueError("AUTO_APPLY requires a proposed action")
            effector_result = self.effector.apply(case, agent_output.proposed_action)
            self.ledger.append(case.case_id, "EFFECT_REQUESTED", effector_result.status)
            return ProcessResult(case.case_id, case, "auto_apply", agent_output, decision, effector_result=effector_result)

        callback = agent_output.outcome == "NEEDS_INFO"
        path = "callback_then_human" if callback else "human_approval"
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
        self.ledger.append(case.case_id, "HUMAN_ESCALATION_CREATED", decision.gate)
        return ProcessResult(case.case_id, case, path, agent_output, decision, escalation=escalation)
