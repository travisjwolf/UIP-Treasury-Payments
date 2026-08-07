from __future__ import annotations

from typing import Any, Literal, Self

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field, model_validator

from wire_repair_agent import StubRepairTools, analyze_fixture


AgentOutcome = Literal[
    "RESOLVED",
    "RESOLVED_LOW_CONFIDENCE",
    "AMBIGUOUS",
    "NEEDS_INFO",
    "EXHAUSTED",
    "BLOCKED_POLICY",
]


class ProposedActionOutput(BaseModel):
    field: str = Field(
        min_length=1,
        description="Payment field that the agent proposes changing.",
    )
    current_value: str = Field(
        min_length=1,
        description="Value currently present on the payment.",
    )
    proposed_value: str = Field(
        min_length=1,
        description="Replacement value copied from cited read-only evidence.",
    )


class EvidenceOutput(BaseModel):
    case_id: str = Field(description="Wire-repair case identifier for this evidence.")
    type: str = Field(description="Evidence category, such as lookup or history_match.")
    source: str = Field(description="Read-only source URI that produced the evidence.")
    content: str = Field(description="Canonical JSON payload returned by the source.")
    produced_by: str = Field(description="Read-only tool that produced this record.")
    timestamp: str = Field(description="ISO-8601 timestamp assigned to the evidence.")


class PaymentInput(BaseModel):
    case_id: str = Field(description="Unique wire-repair case identifier.")
    rail: str = Field(description="Payment rail, such as Fedwire.")
    direction: str = Field(description="Inbound or outbound payment direction.")
    amount_usd: float = Field(gt=0, description="Payment amount normalized to USD.")
    currency: str = Field(description="ISO currency code on the payment.")
    value_date: str = Field(description="Payment value date in YYYY-MM-DD format.")
    cutoff_time: str = Field(description="Applicable rail cutoff time in HH:MM format.")
    sla_deadline: str | None = Field(description="Optional processing SLA deadline.")
    source_channel: str = Field(description="Channel through which the wire originated.")
    customer_id: str = Field(description="Commercial customer identifier.")
    customer_name: str = Field(description="Commercial customer display name.")
    beneficiary_name: str = Field(description="Beneficiary name currently on the wire.")
    beneficiary_account: str = Field(
        description="Beneficiary account currently on the wire."
    )
    beneficiary_bank_aba: str = Field(description="Beneficiary bank ABA routing number.")
    remittance_info: str = Field(description="Wire remittance or invoice information.")
    exception_code: str = Field(description="Intake exception code requiring repair.")
    exception_type: str = Field(description="Human-readable intake exception category.")
    current_queue: str | None = Field(description="Current operations queue, if assigned.")
    status: str | None = Field(description="Current payment-processing status.")
    worked_by: str | None = Field(description="Current analyst or automation owner.")
    confidence: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Existing repair confidence, when already calculated.",
    )
    proposed_action: ProposedActionOutput | None = Field(
        default=None,
        description="Existing proposed action, when already calculated.",
    )
    outcome: AgentOutcome | None = Field(
        default=None,
        description="Existing closed-set repair outcome, when already assigned.",
    )
    touch_count: int | None = Field(
        default=None,
        ge=0,
        description="Number of prior human or automation touches.",
    )
    cycle_time: float | None = Field(
        default=None,
        ge=0,
        description="Elapsed repair cycle time, when available.",
    )


class FixtureMetadataInput(BaseModel):
    demo_role: str | None = Field(
        default=None,
        description="Synthetic-fixture role used to organize the demo.",
    )
    first_time_counterparty: bool | None = Field(
        default=None,
        description="Whether this is the customer's first payment to the counterparty.",
    )
    sanctions_flag: str | None = Field(
        default=None,
        description="Synthetic sanctions-screening setup for the fixture.",
    )
    received_at: str | None = Field(
        default=None,
        description="ISO-8601 time at which the repair case was received.",
    )


class Input(BaseModel):
    case_id: str = Field(description="Wire-repair case identifier to investigate.")
    payment: PaymentInput = Field(
        description="Typed payment record supplied by the repair queue."
    )
    fixture_metadata: FixtureMetadataInput = Field(
        default_factory=FixtureMetadataInput,
        description="Optional synthetic context used by the hackathon demo.",
    )

    @model_validator(mode="after")
    def require_matching_case_ids(self) -> Self:
        if self.case_id != self.payment.case_id:
            raise ValueError("case_id must match payment.case_id")
        return self


class Output(BaseModel):
    outcome: AgentOutcome = Field(
        description="Closed-set repair outcome returned to orchestration."
    )
    proposed_action: ProposedActionOutput | None = Field(
        description="Evidence-backed repair proposal, or null when none is supportable."
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description="Confidence in the proposed repair, between zero and one.",
    )
    evidence: list[EvidenceOutput] = Field(
        description="Cumulative read-only evidence trace supporting the result."
    )
    reasoning_summary: str = Field(
        min_length=1,
        description="Concise explanation of the evidence and control boundary.",
    )
    tools_called: list[str] = Field(
        description="Read-only tools called, in execution order."
    )


class State(BaseModel):
    case_id: str
    payment: PaymentInput
    fixture_metadata: FixtureMetadataInput = Field(
        default_factory=FixtureMetadataInput
    )
    outcome: AgentOutcome | None = None
    proposed_action: ProposedActionOutput | None = None
    confidence: float | None = None
    evidence: list[EvidenceOutput] = Field(default_factory=list)
    reasoning_summary: str | None = None
    tools_called: list[str] = Field(default_factory=list)


async def investigate_and_propose(state: State) -> dict[str, Any]:
    fixture = {
        "case_id": state.case_id,
        "payment": state.payment.model_dump(mode="json"),
        "fixture_metadata": state.fixture_metadata.model_dump(mode="json"),
    }
    return await analyze_fixture(fixture, StubRepairTools())


builder = StateGraph(
    State,
    input_schema=Input,
    output_schema=Output,
)
builder.add_node("investigate_and_propose", investigate_and_propose)
builder.add_edge(START, "investigate_and_propose")
builder.add_edge("investigate_and_propose", END)

graph = builder.compile()
