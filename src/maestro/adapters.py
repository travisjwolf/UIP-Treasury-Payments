from __future__ import annotations

from importlib import import_module
from dataclasses import dataclass, field
from pathlib import Path
import sys
from typing import Any, Mapping, Protocol

from src.contracts import (
    AgentOutput,
    GateContext,
    PaymentCase,
    PolicyConfig,
    PolicyDecision,
)
from src.gates import evaluate_policy


class AsyncAgentGraph(Protocol):
    async def ainvoke(self, input: dict[str, Any]) -> dict[str, Any]:
        ...


def _load_deployable_agent_graph() -> AsyncAgentGraph:
    """Load Bravo's UiPath entrypoint with its project root importable."""
    project_root = str(Path(__file__).resolve().parents[1] / "agent")
    inserted = project_root not in sys.path
    if inserted:
        sys.path.insert(0, project_root)
    try:
        module = import_module("src.agent.main")
    finally:
        if inserted:
            sys.path.remove(project_root)
    return module.graph


@dataclass
class AsyncFixtureRepairAgent:
    """Typed adapter from Bravo's deployable async graph to orchestration."""

    graph: AsyncAgentGraph = field(default_factory=_load_deployable_agent_graph)

    async def analyze(
        self,
        case: PaymentCase,
        fixture: dict,
    ) -> AgentOutput:
        if case.case_id != fixture.get("payment_case", {}).get("case_id"):
            raise ValueError("fixture payment case does not match the typed case")
        runtime_input = {
            "payment_case": fixture["payment_case"],
            "gate_context": fixture["gate_context"],
            "demo_role": fixture.get("demo_role"),
        }
        raw_output = await self.graph.ainvoke(runtime_input)
        return AgentOutput.model_validate(raw_output)


@dataclass(frozen=True)
class DeterministicGateEvaluator:
    """Typed adapter around Alpha's pure, deterministic gate evaluator."""

    def evaluate(
        self,
        case: PaymentCase,
        agent_output: AgentOutput,
        gate_context: GateContext,
        policy_config: PolicyConfig,
    ) -> PolicyDecision:
        return evaluate_policy(case, agent_output, gate_context, policy_config)


@dataclass(frozen=True)
class StaticPolicyConfigProvider:
    """Fixture/sandbox provider; production can inject a Data Fabric provider."""

    configs: Mapping[str, PolicyConfig]

    def for_case(self, case: PaymentCase) -> PolicyConfig:
        try:
            return self.configs[case.customer_id]
        except KeyError as error:
            raise KeyError(
                f"no policy configuration for customer {case.customer_id}"
            ) from error
