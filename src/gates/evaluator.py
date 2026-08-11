"""Deterministic, ordered payment-repair policy gates."""

from datetime import timedelta

from src.contracts import (
    AgentOutput,
    GateContext,
    GateId,
    Outcome,
    PaymentCase,
    PolicyConfig,
    PolicyDecision,
    PolicyResult,
    ProposedField,
    SanctionsStatus,
)


def _decision(
    payment_case: PaymentCase,
    gate_context: GateContext,
    result: PolicyResult,
    reason: str,
    gate: GateId | None = None,
) -> PolicyDecision:
    return PolicyDecision(
        case_id=payment_case.case_id,
        gate=gate,
        result=result,
        reason=reason,
        evaluated_at=gate_context.evaluated_at,
    )


def evaluate_policy(
    payment_case: PaymentCase,
    agent_output: AgentOutput,
    gate_context: GateContext,
    policy_config: PolicyConfig,
) -> PolicyDecision:
    """Return the first deterministic policy gate that applies to a repair."""
    if gate_context.sanctions_status != SanctionsStatus.CLEAR:
        return _decision(
            payment_case,
            gate_context,
            PolicyResult.COMPLIANCE_REFERRAL,
            "G0 sanctions status is not clear.",
            GateId.G0,
        )

    proposal = agent_output.proposed_action
    if proposal is not None:
        if proposal.field == ProposedField.BENEFICIARY_ACCOUNT:
            return _decision(
                payment_case,
                gate_context,
                PolicyResult.HUMAN_APPROVAL,
                "G1 proposed repair changes the beneficiary account.",
                GateId.G1,
            )
        if proposal.field in {ProposedField.AMOUNT_USD, ProposedField.CURRENCY}:
            return _decision(
                payment_case,
                gate_context,
                PolicyResult.HARD_STOP,
                "G2 proposed repair changes an amount or currency field.",
                GateId.G2,
            )

    if policy_config.customer_id != payment_case.customer_id:
        raise ValueError("PolicyConfig.customer_id must match PaymentCase.customer_id")

    if proposal is not None:
        if payment_case.amount_usd > policy_config.auto_apply_amount_threshold_usd:
            return _decision(
                payment_case,
                gate_context,
                PolicyResult.HUMAN_APPROVAL,
                "G3 payment amount exceeds the auto-apply threshold.",
                GateId.G3,
            )
        if gate_context.first_time_counterparty:
            return _decision(
                payment_case,
                gate_context,
                PolicyResult.HUMAN_APPROVAL,
                "G4 counterparty has no established payment history.",
                GateId.G4,
            )
        if agent_output.confidence < policy_config.minimum_confidence:
            return _decision(
                payment_case,
                gate_context,
                PolicyResult.HUMAN_APPROVAL,
                "G5 proposal confidence is below the configured minimum.",
                GateId.G5,
            )
        if gate_context.cross_border or payment_case.currency != "USD":
            return _decision(
                payment_case,
                gate_context,
                PolicyResult.HUMAN_APPROVAL,
                "G6 payment is cross-border or denominated outside USD.",
                GateId.G6,
            )
        if payment_case.exception_code == "EX-07":
            return _decision(
                payment_case,
                gate_context,
                PolicyResult.HUMAN_APPROVAL,
                "G7 payment is marked as a duplicate suspect.",
                GateId.G7,
            )
        if (
            gate_context.same_day_beneficiary_total_usd
            > policy_config.same_day_beneficiary_velocity_threshold_usd
        ):
            return _decision(
                payment_case,
                gate_context,
                PolicyResult.HUMAN_APPROVAL,
                "G8 beneficiary same-day value exceeds the velocity threshold.",
                GateId.G8,
            )

    if agent_output.outcome == Outcome.NEEDS_INFO:
        return _decision(
            payment_case,
            gate_context,
            PolicyResult.CALLBACK_THEN_HUMAN,
            "G9 agent needs additional information before a repair can proceed.",
            GateId.G9,
        )
    if agent_output.outcome in {Outcome.AMBIGUOUS, Outcome.EXHAUSTED}:
        return _decision(
            payment_case,
            gate_context,
            PolicyResult.ESCALATE,
            "G9 agent outcome requires escalation with its full trace.",
            GateId.G9,
        )
    if (
        gate_context.cutoff_at - gate_context.evaluated_at
        < timedelta(minutes=policy_config.cutoff_escalation_minutes)
    ):
        return _decision(
            payment_case,
            gate_context,
            PolicyResult.PRIORITY_ESCALATION,
            "G10 remaining cutoff time is inside the priority escalation window.",
            GateId.G10,
        )
    if agent_output.outcome == Outcome.BLOCKED_POLICY:
        return _decision(
            payment_case,
            gate_context,
            PolicyResult.ESCALATE,
            "Agent reported a policy block not explained by an earlier deterministic gate.",
        )

    return _decision(
        payment_case,
        gate_context,
        PolicyResult.AUTO_APPLY,
        "No deterministic policy gate fired; the repair is eligible for auto-apply.",
    )
