from __future__ import annotations

from datetime import date
from typing import Any, Literal, Self

from langgraph.graph import END, START, StateGraph
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

from wire_repair_agent import CsvRepairTools, EvidenceType, analyze_fixture


AgentOutcome = Literal[
    "RESOLVED",
    "RESOLVED_LOW_CONFIDENCE",
    "AMBIGUOUS",
    "NEEDS_INFO",
    "EXHAUSTED",
    "BLOCKED_POLICY",
]
ProposedField = Literal[
    "amount_usd",
    "beneficiary_account",
    "beneficiary_bank_aba",
    "beneficiary_name",
    "currency",
    "customer_name",
    "remittance_info",
]
SanctionsStatus = Literal["clear", "review", "match", "unknown"]
ScalarValue = StrictStr | StrictInt | StrictFloat


class ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class ProposedActionOutput(ContractModel):
    field: ProposedField = Field(
        description="Payment field that the agent proposes changing."
    )
    current_value: ScalarValue = Field(
        description="Value currently present on the payment."
    )
    proposed_value: ScalarValue = Field(
        description="Replacement value copied from cited read-only evidence."
    )

    @model_validator(mode="after")
    def proposed_value_must_change(self) -> Self:
        if self.current_value == self.proposed_value:
            raise ValueError("proposed_value must differ from current_value")
        if isinstance(self.proposed_value, str) and not self.proposed_value:
            raise ValueError("proposed_value must not be blank")
        return self


class EvidenceOutput(ContractModel):
    case_id: str = Field(
        min_length=1,
        description="Wire-repair case identifier for this evidence.",
    )
    type: EvidenceType = Field(
        description="Closed evidence category produced by a read-only source."
    )
    source: str = Field(
        min_length=1,
        description="Read-only source URI that produced the evidence.",
    )
    content: dict[str, Any] | str = Field(
        description="Canonical payload returned by the evidence source."
    )
    produced_by: str = Field(
        min_length=1,
        description="Read-only tool that produced this record.",
    )
    timestamp: AwareDatetime = Field(
        description="ISO-8601 timestamp assigned to the evidence."
    )


class PaymentInput(ContractModel):
    case_id: str = Field(
        min_length=1,
        description="Unique wire-repair case identifier.",
    )
    rail: str = Field(min_length=1, description="Payment rail, such as Fedwire.")
    direction: Literal["outbound", "inbound"] = Field(
        description="Inbound or outbound payment direction."
    )
    amount_usd: float = Field(gt=0, description="Payment amount normalized to USD.")
    currency: str = Field(
        pattern=r"^[A-Z]{3}$",
        description="Three-letter ISO currency code on the payment.",
    )
    value_date: date = Field(description="Payment value date in YYYY-MM-DD format.")
    cutoff_time: str = Field(
        pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$",
        description="Applicable rail cutoff time in HH:MM format.",
    )
    sla_deadline: AwareDatetime | None = Field(
        default=None,
        description="Optional processing SLA deadline.",
    )
    source_channel: str = Field(
        min_length=1,
        description="Channel through which the wire originated.",
    )
    customer_id: str = Field(
        min_length=1,
        description="Commercial customer identifier.",
    )
    customer_name: str = Field(
        min_length=1,
        description="Commercial customer display name.",
    )
    beneficiary_name: str = Field(
        min_length=1,
        description="Beneficiary name currently on the wire.",
    )
    beneficiary_account: str = Field(
        min_length=1,
        description="Beneficiary account currently on the wire."
    )
    beneficiary_bank_aba: str = Field(
        min_length=1,
        description="Beneficiary bank ABA routing number.",
    )
    remittance_info: str = Field(description="Wire remittance or invoice information.")
    exception_code: str = Field(
        pattern=r"^EX-\d{2}$",
        description="Intake exception code requiring repair.",
    )
    exception_type: str = Field(
        min_length=1,
        description="Human-readable intake exception category.",
    )
    current_queue: str = Field(
        min_length=1,
        description="Current operations queue.",
    )
    status: str = Field(
        min_length=1,
        description="Current payment-processing status.",
    )
    worked_by: str | None = Field(
        default=None,
        description="Current analyst or automation owner.",
    )
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
    touch_count: int = Field(
        default=0,
        ge=0,
        description="Number of prior human or automation touches.",
    )
    cycle_time: float | None = Field(
        default=None,
        ge=0,
        description="Elapsed repair cycle time, when available.",
    )


class GateContextInput(ContractModel):
    sanctions_status: SanctionsStatus = Field(
        description="Current sanctions-screening result for deterministic gate G0."
    )
    first_time_counterparty: bool = Field(
        description="Whether this is the customer's first payment to the counterparty."
    )
    same_day_beneficiary_total_usd: float = Field(
        ge=0,
        description="Same-day USD total used by the deterministic velocity gate.",
    )
    cross_border: bool = Field(
        description="Whether the payment crosses a national border."
    )
    evaluated_at: AwareDatetime = Field(
        description="ISO-8601 time at which the gate context was evaluated."
    )
    cutoff_at: AwareDatetime = Field(
        description="ISO-8601 payment-rail cutoff timestamp."
    )


class Input(ContractModel):
    payment_case: PaymentInput = Field(
        description="Typed payment record supplied by the repair queue."
    )
    gate_context: GateContextInput = Field(
        description="Typed context reserved for the separate deterministic gate layer."
    )
    demo_role: str | None = Field(
        default=None,
        description="Optional synthetic role used to organize hackathon demo cases.",
    )


class Output(ContractModel):
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
        description="Concise explanation of the evidence and control boundary.",
    )
    tools_called: list[str] = Field(
        description="Read-only tools called, in execution order."
    )

    @model_validator(mode="after")
    def resolved_outcome_requires_a_proposal(self) -> Self:
        if self.outcome in {"RESOLVED", "RESOLVED_LOW_CONFIDENCE"}:
            if self.proposed_action is None:
                raise ValueError("resolved outcomes require proposed_action")
        return self


class State(ContractModel):
    payment_case: PaymentInput
    gate_context: GateContextInput
    demo_role: str | None = None
    outcome: AgentOutcome | None = None
    proposed_action: ProposedActionOutput | None = None
    confidence: float | None = None
    evidence: list[EvidenceOutput] = Field(default_factory=list)
    reasoning_summary: str | None = None
    tools_called: list[str] = Field(default_factory=list)


async def investigate_and_propose(state: State) -> dict[str, Any]:
    fixture = {
        "payment_case": state.payment_case.model_dump(mode="json"),
        "gate_context": state.gate_context.model_dump(mode="json"),
        "demo_role": state.demo_role,
    }
    return await analyze_fixture(fixture, CsvRepairTools())


builder = StateGraph(
    State,
    input_schema=Input,
    output_schema=Output,
)
builder.add_node("investigate_and_propose", investigate_and_propose)
builder.add_edge(START, "investigate_and_propose")
builder.add_edge("investigate_and_propose", END)

graph = builder.compile()
