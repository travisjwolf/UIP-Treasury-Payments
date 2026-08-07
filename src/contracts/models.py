from datetime import date, datetime, time
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .enums import EvidenceType, GateId, Outcome, PolicyPath, SanctionsStatus


class ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class ProposedAction(ContractModel):
    field: str = Field(min_length=1)
    current_value: Any
    proposed_value: Any


class PaymentCase(ContractModel):
    case_id: str = Field(min_length=1)
    rail: str = Field(min_length=1)
    direction: Literal["outbound", "inbound"]
    amount_usd: float = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    value_date: date
    cutoff_time: time
    sla_deadline: datetime | None = None
    source_channel: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    customer_name: str = Field(min_length=1)
    beneficiary_name: str = Field(min_length=1)
    beneficiary_account: str = Field(min_length=1)
    beneficiary_bank_aba: str = Field(min_length=1)
    remittance_info: str
    exception_code: str = Field(pattern=r"^EX-\d{2}$")
    exception_type: str = Field(min_length=1)
    current_queue: str = Field(min_length=1)
    status: str = Field(min_length=1)
    worked_by: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    proposed_action: ProposedAction | None = None
    outcome: Outcome | None = None
    touch_count: int = Field(default=0, ge=0)
    cycle_time: float | None = Field(default=None, ge=0)


class Evidence(ContractModel):
    case_id: str = Field(min_length=1)
    type: EvidenceType
    source: str = Field(min_length=1)
    content: dict[str, Any]
    produced_by: str = Field(min_length=1)
    timestamp: AwareDatetime


class CounterpartyHistory(ContractModel):
    customer_id: str = Field(min_length=1)
    beneficiary_name: str = Field(min_length=1)
    beneficiary_account: str = Field(min_length=1)
    times_seen: int = Field(ge=0)
    times_repaired: int = Field(ge=0)
    last_applied_fix: str = Field(min_length=1)
    history_confidence: float = Field(ge=0, le=1)


class PolicyDecision(ContractModel):
    case_id: str = Field(min_length=1)
    gate: GateId | None
    result: PolicyPath
    reason: str = Field(min_length=1)
    evaluated_at: AwareDatetime


class AgentOutput(ContractModel):
    outcome: Outcome
    proposed_action: ProposedAction
    confidence: float = Field(ge=0, le=1)
    evidence: list[Evidence]
    reasoning_summary: str
    tools_called: list[str]


class GateContext(ContractModel):
    sanctions_status: SanctionsStatus
    first_time_counterparty: bool
    same_day_beneficiary_total_usd: float = Field(ge=0)
    cross_border: bool
    evaluated_at: AwareDatetime


class PolicyConfig(ContractModel):
    customer_id: str = Field(min_length=1)
    auto_apply_amount_threshold_usd: float = Field(default=250_000.0, gt=0)
    minimum_confidence: float = Field(default=0.85, ge=0, le=1)
    same_day_beneficiary_velocity_threshold_usd: float = Field(
        gt=0,
    )
    cutoff_escalation_minutes: int = Field(default=30, gt=0)


class PaymentFixture(ContractModel):
    payment_case: PaymentCase
    gate_context: GateContext
    expected_outcome: Outcome
    expected_path: PolicyPath
    demo_role: str | None = None
