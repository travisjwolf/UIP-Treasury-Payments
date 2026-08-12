const payment = $vars.start.output.payment_case;
const context = $vars.start.output.gate_context;
const config = $vars.start.output.policy_config;
const agent = $vars.repairAgent.output;

const fail = (contract, message) => {
  throw new Error(`${contract}: ${message}`);
};
const object = (value, contract) => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    fail(contract, "must be an object");
  }
};
const shape = (value, allowed, required, contract) => {
  object(value, contract);
  const extras = Object.keys(value).filter((key) => !allowed.includes(key));
  if (extras.length) fail(contract, `unexpected field ${extras[0]}`);
  const missing = required.filter((key) => !Object.prototype.hasOwnProperty.call(value, key));
  if (missing.length) fail(contract, `missing field ${missing[0]}`);
};
const string = (value, contract, field, allowBlank = false) => {
  if (typeof value !== "string" || (!allowBlank && value.trim() === "")) {
    fail(contract, `${field} must be ${allowBlank ? "a string" : "a nonblank string"}`);
  }
};
const number = (value, contract, field, minimum, maximum, exclusiveMinimum = false) => {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    fail(contract, `${field} must be a finite number`);
  }
  if (minimum !== undefined && (exclusiveMinimum ? value <= minimum : value < minimum)) {
    fail(contract, `${field} is below its minimum`);
  }
  if (maximum !== undefined && value > maximum) {
    fail(contract, `${field} is above its maximum`);
  }
};
const integer = (value, contract, field, minimum, exclusiveMinimum = false) => {
  number(value, contract, field, minimum, undefined, exclusiveMinimum);
  if (!Number.isInteger(value)) fail(contract, `${field} must be an integer`);
};
const scalar = (value, contract, field) => {
  if (typeof value === "string") return;
  if (typeof value === "number" && Number.isFinite(value)) return;
  fail(contract, `${field} must be a string or finite number`);
};
const dateOnly = (value, contract, field) => {
  string(value, contract, field);
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  const parsed = match ? new Date(`${value}T00:00:00Z`) : null;
  const roundTrip = parsed && Number.isFinite(parsed.getTime())
    ? parsed.toISOString().slice(0, 10)
    : "";
  if (!match || Number(match[1]) < 1 || roundTrip !== value) {
    fail(contract, `${field} must be an ISO date`);
  }
};
const awareDateTime = (value, contract, field) => {
  string(value, contract, field);
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|([+-])(\d{2}):(\d{2}))$/.exec(value);
  if (!match) {
    fail(contract, `${field} must be an ISO timestamp with timezone`);
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);
  const millisecond = Number((match[7] || "").padEnd(3, "0").slice(0, 3));
  const offsetHour = match[8] === "Z" ? 0 : Number(match[10]);
  const offsetMinute = match[8] === "Z" ? 0 : Number(match[11]);
  const calendar = new Date(0);
  calendar.setUTCFullYear(year, month - 1, day);
  calendar.setUTCHours(hour, minute, second, millisecond);
  const calendarMatches = calendar.getUTCFullYear() === year
    && calendar.getUTCMonth() === month - 1
    && calendar.getUTCDate() === day
    && calendar.getUTCHours() === hour
    && calendar.getUTCMinutes() === minute
    && calendar.getUTCSeconds() === second;
  if (year < 1 || !calendarMatches || offsetHour > 23 || offsetMinute > 59 || !Number.isFinite(Date.parse(value))) {
    fail(contract, `${field} must be an ISO timestamp with timezone`);
  }
};
const optional = (value, validator) => {
  if (value !== undefined && value !== null) validator(value);
};
const enumValue = (value, values, contract, field) => {
  if (!values.includes(value)) fail(contract, `${field} is not an allowed value`);
};

const proposalFields = [
  "amount_usd",
  "beneficiary_account",
  "beneficiary_bank_aba",
  "beneficiary_name",
  "currency",
  "customer_name",
  "remittance_info",
];
const outcomes = [
  "RESOLVED",
  "RESOLVED_LOW_CONFIDENCE",
  "AMBIGUOUS",
  "NEEDS_INFO",
  "EXHAUSTED",
  "BLOCKED_POLICY",
];
const validateProposal = (proposal, contract) => {
  shape(
    proposal,
    ["field", "current_value", "proposed_value"],
    ["field", "current_value", "proposed_value"],
    contract,
  );
  enumValue(proposal.field, proposalFields, contract, "field");
  scalar(proposal.current_value, contract, "current_value");
  scalar(proposal.proposed_value, contract, "proposed_value");
  if (typeof proposal.proposed_value === "string" && proposal.proposed_value.trim() === "") {
    fail(contract, "proposed_value must not be blank");
  }
  if (proposal.current_value === proposal.proposed_value) {
    fail(contract, "proposed_value must differ from current_value");
  }
};
const validatePayment = () => {
  const allowed = [
    "case_id", "rail", "direction", "amount_usd", "currency", "value_date",
    "cutoff_time", "sla_deadline", "source_channel", "customer_id", "customer_name",
    "beneficiary_name", "beneficiary_account", "beneficiary_bank_aba", "remittance_info",
    "exception_code", "exception_type", "current_queue", "status", "worked_by",
    "confidence", "proposed_action", "outcome", "touch_count", "cycle_time",
  ];
  const required = [
    "case_id", "rail", "direction", "amount_usd", "currency", "value_date",
    "cutoff_time", "source_channel", "customer_id", "customer_name", "beneficiary_name",
    "beneficiary_account", "beneficiary_bank_aba", "remittance_info", "exception_code",
    "exception_type", "current_queue", "status",
  ];
  shape(payment, allowed, required, "PaymentCase");
  ["case_id", "rail", "source_channel", "customer_id", "customer_name", "beneficiary_name",
    "beneficiary_account", "beneficiary_bank_aba", "exception_type", "current_queue", "status"]
    .forEach((field) => string(payment[field], "PaymentCase", field));
  string(payment.remittance_info, "PaymentCase", "remittance_info", true);
  enumValue(payment.direction, ["outbound", "inbound"], "PaymentCase", "direction");
  number(payment.amount_usd, "PaymentCase", "amount_usd", 0, undefined, true);
  if (typeof payment.currency !== "string" || !/^[A-Z]{3}$/.test(payment.currency)) {
    fail("PaymentCase", "currency must be a three-letter uppercase code");
  }
  dateOnly(payment.value_date, "PaymentCase", "value_date");
  if (typeof payment.cutoff_time !== "string" || !/^(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$/.test(payment.cutoff_time)) {
    fail("PaymentCase", "cutoff_time must be HH:MM or HH:MM:SS");
  }
  if (typeof payment.exception_code !== "string" || !/^EX-\d{2}$/.test(payment.exception_code)) {
    fail("PaymentCase", "exception_code must match EX-NN");
  }
  optional(payment.sla_deadline, (value) => awareDateTime(value, "PaymentCase", "sla_deadline"));
  optional(payment.worked_by, (value) => string(value, "PaymentCase", "worked_by", true));
  optional(payment.confidence, (value) => number(value, "PaymentCase", "confidence", 0, 1));
  optional(payment.proposed_action, (value) => validateProposal(value, "PaymentCase.proposed_action"));
  optional(payment.outcome, (value) => enumValue(value, outcomes, "PaymentCase", "outcome"));
  if (payment.touch_count !== undefined) integer(payment.touch_count, "PaymentCase", "touch_count", 0);
  optional(payment.cycle_time, (value) => number(value, "PaymentCase", "cycle_time", 0));
};
const validateContext = () => {
  const fields = [
    "sanctions_status", "first_time_counterparty", "same_day_beneficiary_total_usd",
    "cross_border", "evaluated_at", "cutoff_at",
  ];
  shape(context, fields, fields, "GateContext");
  enumValue(context.sanctions_status, ["clear", "review", "match", "unknown"], "GateContext", "sanctions_status");
  if (typeof context.first_time_counterparty !== "boolean") fail("GateContext", "first_time_counterparty must be boolean");
  if (typeof context.cross_border !== "boolean") fail("GateContext", "cross_border must be boolean");
  number(context.same_day_beneficiary_total_usd, "GateContext", "same_day_beneficiary_total_usd", 0);
  awareDateTime(context.evaluated_at, "GateContext", "evaluated_at");
  awareDateTime(context.cutoff_at, "GateContext", "cutoff_at");
};
const validateAgent = () => {
  const fields = ["outcome", "proposed_action", "confidence", "evidence", "reasoning_summary", "tools_called"];
  shape(agent, fields, fields, "AgentOutput");
  enumValue(agent.outcome, outcomes, "AgentOutput", "outcome");
  if (agent.proposed_action !== null) validateProposal(agent.proposed_action, "AgentOutput.proposed_action");
  if (["RESOLVED", "RESOLVED_LOW_CONFIDENCE"].includes(agent.outcome) && agent.proposed_action === null) {
    fail("AgentOutput", "resolved outcomes require proposed_action");
  }
  number(agent.confidence, "AgentOutput", "confidence", 0, 1);
  if (!Array.isArray(agent.evidence)) fail("AgentOutput", "evidence must be an array");
  agent.evidence.forEach((item, index) => {
    const contract = `AgentOutput.evidence[${index}]`;
    const fields = ["case_id", "type", "source", "content", "produced_by", "timestamp"];
    shape(item, fields, fields, contract);
    string(item.case_id, contract, "case_id");
    enumValue(item.type, ["lookup", "history_match", "sanctions", "document", "call_transcript"], contract, "type");
    string(item.source, contract, "source");
    string(item.produced_by, contract, "produced_by");
    awareDateTime(item.timestamp, contract, "timestamp");
    if (typeof item.content !== "string" && (!item.content || typeof item.content !== "object" || Array.isArray(item.content))) {
      fail(contract, "content must be a string or object");
    }
  });
  string(agent.reasoning_summary, "AgentOutput", "reasoning_summary", true);
  if (!Array.isArray(agent.tools_called) || agent.tools_called.some((item) => typeof item !== "string")) {
    fail("AgentOutput", "tools_called must be an array of strings");
  }
};
const validateFixedGateAgent = () => {
  object(agent, "AgentOutput");
  if (!Object.prototype.hasOwnProperty.call(agent, "proposed_action")) {
    fail("AgentOutput", "missing field proposed_action");
  }
  if (agent.proposed_action !== null) {
    validateProposal(agent.proposed_action, "AgentOutput.proposed_action");
  }
};
const validateConfig = () => {
  const fields = [
    "customer_id", "auto_apply_amount_threshold_usd", "minimum_confidence",
    "same_day_beneficiary_velocity_threshold_usd", "cutoff_escalation_minutes",
  ];
  shape(config, fields, fields, "PolicyConfig");
  string(config.customer_id, "PolicyConfig", "customer_id");
  number(config.auto_apply_amount_threshold_usd, "PolicyConfig", "auto_apply_amount_threshold_usd", 0, undefined, true);
  number(config.minimum_confidence, "PolicyConfig", "minimum_confidence", 0, 1);
  number(config.same_day_beneficiary_velocity_threshold_usd, "PolicyConfig", "same_day_beneficiary_velocity_threshold_usd", 0, undefined, true);
  integer(config.cutoff_escalation_minutes, "PolicyConfig", "cutoff_escalation_minutes", 0, true);
  if (config.customer_id !== payment.customer_id) {
    fail("PolicyConfig", "customer_id must match PaymentCase.customer_id");
  }
};

validatePayment();
validateContext();

const decide = (gate, result, reason) => ({
  case_id: payment.case_id,
  gate,
  result,
  reason,
  evaluated_at: context.evaluated_at,
});
if (context.sanctions_status !== "clear") {
  return decide("G0", "COMPLIANCE_REFERRAL", "G0 sanctions status is not clear.");
}
validateFixedGateAgent();
const proposal = agent.proposed_action;
if (proposal) {
  if (proposal.field === "beneficiary_account") {
    return decide("G1", "HUMAN_APPROVAL", "G1 proposed repair changes the beneficiary account.");
  }
  if (["amount_usd", "currency"].includes(proposal.field)) {
    return decide("G2", "HARD_STOP", "G2 proposed repair changes an amount or currency field.");
  }
}

validateAgent();
validateConfig();
if (proposal) {
  if (payment.amount_usd > config.auto_apply_amount_threshold_usd) {
    return decide("G3", "HUMAN_APPROVAL", "G3 payment amount exceeds the auto-apply threshold.");
  }
  if (context.first_time_counterparty) {
    return decide("G4", "HUMAN_APPROVAL", "G4 counterparty has no established payment history.");
  }
  if (agent.confidence < config.minimum_confidence) {
    return decide("G5", "HUMAN_APPROVAL", "G5 proposal confidence is below the configured minimum.");
  }
  if (context.cross_border || payment.currency !== "USD") {
    return decide("G6", "HUMAN_APPROVAL", "G6 payment is cross-border or denominated outside USD.");
  }
  if (payment.exception_code === "EX-07") {
    return decide("G7", "HUMAN_APPROVAL", "G7 payment is marked as a duplicate suspect.");
  }
  if (context.same_day_beneficiary_total_usd > config.same_day_beneficiary_velocity_threshold_usd) {
    return decide("G8", "HUMAN_APPROVAL", "G8 beneficiary same-day value exceeds the velocity threshold.");
  }
}
if (agent.outcome === "NEEDS_INFO") {
  return decide("G9", "CALLBACK_THEN_HUMAN", "G9 agent needs additional information before a repair can proceed.");
}
if (["AMBIGUOUS", "EXHAUSTED"].includes(agent.outcome)) {
  return decide("G9", "ESCALATE", "G9 agent outcome requires escalation with its full trace.");
}
if ((new Date(context.cutoff_at).getTime() - new Date(context.evaluated_at).getTime()) < config.cutoff_escalation_minutes * 60000) {
  return decide("G10", "PRIORITY_ESCALATION", "G10 remaining cutoff time is inside the priority escalation window.");
}
if (agent.outcome === "BLOCKED_POLICY") {
  return decide(null, "ESCALATE", "Agent reported a policy block not explained by an earlier deterministic gate.");
}
return decide(null, "AUTO_APPLY", "No deterministic policy gate fired; the repair is eligible for auto-apply.");
