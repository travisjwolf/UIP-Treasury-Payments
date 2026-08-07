from datetime import date
from typing import Any, Literal, Self

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

from .enums import (
    EvidenceType,
    GateId,
    Outcome,
    PolicyPath,
    PolicyResult,
    ProposedField,
    SanctionsStatus,
)


ScalarValue = StrictStr | StrictInt | StrictFloat
AGENT_OUTCOMES = frozenset(item.value for item in Outcome)


class ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class ProposedAction(ContractModel):
    field: ProposedField
    current_value: ScalarValue
    proposed_value: ScalarValue

    def __init__(self, *args: Any, **data: Any) -> None:
        field_names = ("field", "current_value", "proposed_value")
        if len(args) > len(field_names):
            raise TypeError(f"Expected at most {len(field_names)} positional arguments")
        positional = dict(zip(field_names, args, strict=False))
        duplicates = positional.keys() & data.keys()
        if duplicates:
            duplicate = sorted(duplicates)[0]
            raise TypeError(f"Multiple values for {duplicate}")
        super().__init__(**positional, **data)

    @model_validator(mode="after")
    def proposed_value_must_change(self) -> Self:
        if self.current_value == self.proposed_value:
            raise ValueError("proposed_value must differ from current_value")
        if isinstance(self.proposed_value, str) and not self.proposed_value:
            raise ValueError("proposed_value must not be blank")
        return self

    @classmethod
    def from_dict(cls, value: Any) -> "ProposedAction":
        if not isinstance(value, dict):
            raise ValueError("proposed_action must be an object")
        missing = {"field", "current_value", "proposed_value"} - value.keys()
        if missing:
            names = ", ".join(sorted(missing))
            raise ValueError(f"proposed_action is missing: {names}")
        return cls.model_validate(value)


class PaymentCase(ContractModel):
    case_id: str = Field(min_length=1)
    rail: str = Field(min_length=1)
    direction: Literal["outbound", "inbound"]
    amount_usd: float = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    value_date: date
    cutoff_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$")
    sla_deadline: AwareDatetime | None = None
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

    @classmethod
    def field_names(cls) -> tuple[str, ...]:
        return tuple(cls.model_fields)

    @classmethod
    def from_fixture(cls, fixture: dict[str, Any]) -> "PaymentCase":
        values = fixture.get("payment_case", fixture.get("payment", fixture))
        return cls.model_validate(values)


class Evidence(ContractModel):
    case_id: str = Field(min_length=1)
    type: EvidenceType
    source: str = Field(min_length=1)
    content: dict[str, Any] | str
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
    gate: GateId | Literal["NONE"] | None
    result: PolicyResult
    reason: str = Field(min_length=1)
    evaluated_at: AwareDatetime

    def __init__(self, *args: Any, **data: Any) -> None:
        field_names = ("case_id", "gate", "result", "reason", "evaluated_at")
        if len(args) > len(field_names):
            raise TypeError(f"Expected at most {len(field_names)} positional arguments")
        positional = dict(zip(field_names, args, strict=False))
        duplicates = positional.keys() & data.keys()
        if duplicates:
            duplicate = sorted(duplicates)[0]
            raise TypeError(f"Multiple values for {duplicate}")
        super().__init__(**positional, **data)


class AgentOutput(ContractModel):
    outcome: Outcome
    proposed_action: ProposedAction | None
    confidence: float = Field(ge=0, le=1)
    evidence: list[Evidence]
    reasoning_summary: str
    tools_called: list[str]

    @model_validator(mode="after")
    def resolved_outcome_requires_a_proposal(self) -> Self:
        resolved = {Outcome.RESOLVED, Outcome.RESOLVED_LOW_CONFIDENCE}
        if self.outcome in resolved and self.proposed_action is None:
            raise ValueError("resolved outcomes require proposed_action")
        return self

    @classmethod
    def from_dict(cls, value: Any) -> "AgentOutput":
        if not isinstance(value, dict):
            raise ValueError("agent output must be an object")
        if value.get("outcome") not in AGENT_OUTCOMES:
            raise ValueError(f"unknown outcome: {value.get('outcome')}")
        confidence = value.get("confidence")
        if (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0 <= confidence <= 1
        ):
            raise ValueError("confidence must be between 0 and 1")
        return cls.model_validate(value)


class GateContext(ContractModel):
    sanctions_status: SanctionsStatus
    first_time_counterparty: bool
    same_day_beneficiary_total_usd: float = Field(ge=0)
    cross_border: bool
    evaluated_at: AwareDatetime
    cutoff_at: AwareDatetime


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
