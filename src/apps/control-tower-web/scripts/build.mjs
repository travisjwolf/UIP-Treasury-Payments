import { cp, mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const appDirectory = resolve("app");
const distDirectory = resolve("dist");
const fixtureDirectory = resolve("../../../fixtures/cases");

const heroRuntime = {
  "WIRE-8802": {
    status: "AUTO_APPLY_SANDBOX_RECORDED",
    outcome: "RESOLVED",
    gate: "NONE",
    confidence: 0.96,
    proposal: { field: "beneficiary_name", current_value: "PACIFIC STEEL & SUPPY", proposed_value: "PACIFIC STEEL & SUPPLY" },
    reason: "Known counterparty history supports a name-only repair; all deterministic gates are clear.",
    actions: [],
    evidence: [{ type: "history_match", source: "fixture://counterparty_history.csv#row=2", content: { beneficiary_account: "8823004417", beneficiary_name: "PACIFIC STEEL & SUPPLY", history_confidence: 0.96 } }],
  },
  "WIRE-8841": {
    status: "HUMAN_APPROVAL_REQUIRED",
    outcome: "BLOCKED_POLICY",
    gate: "G1",
    confidence: 0.91,
    proposal: { field: "beneficiary_account", current_value: "882300441", proposed_value: "8823004417" },
    reason: "G1 proposed repair changes the beneficiary account. Human approval is required at every amount.",
    actions: ["approve", "edit", "reject", "escalate"],
    evidence: [
      { type: "sanctions", source: "stub://sanctions-screening", content: { status: "clear", case_id: "WIRE-8841" } },
      { type: "lookup", source: "stub://core-account-lookup", content: { queried_beneficiary_account: "882300441", status: "not_found" } },
      { type: "history_match", source: "fixture://counterparty_history.csv#row=2", content: { queried_beneficiary_account: "882300441", beneficiary_account: "8823004417", beneficiary_name: "PACIFIC STEEL & SUPPLY", history_confidence: 0.91 } },
    ],
  },
  "WIRE-8877": {
    status: "CALLBACK_REQUIRED",
    outcome: "NEEDS_INFO",
    gate: "G9",
    confidence: 0.74,
    proposal: null,
    reason: "The callback transcript conflicts with the account on the payment; a human must complete verification.",
    actions: ["provide_info", "approve", "reject", "escalate"],
    evidence: [{ type: "call_transcript", source: "fixture://callback/WIRE-8877", content: { flagged_fields: ["beneficiary_account"], transcript: "Pre-recorded and sanitized demo transcript." } }],
  },
};

const files = (await readdir(fixtureDirectory)).filter((name) => name.endsWith(".json")).sort();
const cases = [];
for (const file of files) {
  const fixture = JSON.parse(await readFile(resolve(fixtureDirectory, file), "utf8"));
  const payment = fixture.payment_case;
  const runtime = heroRuntime[payment.case_id] ?? {
    status: fixture.expected_path === "compliance_referral" ? "COMPLIANCE_REFERRAL_REQUIRED" : `${fixture.expected_path.toUpperCase()}_PENDING`,
    outcome: fixture.expected_outcome,
    gate: "PENDING",
    confidence: null,
    proposal: null,
    reason: "Fixture case is ready for read-only agent investigation and deterministic gate evaluation.",
    actions: [],
    evidence: [],
  };
  cases.push({ case_id: payment.case_id, path: fixture.expected_path, payment, ...runtime });
}

await mkdir(distDirectory, { recursive: true });
for (const asset of ["index.html", "app.mjs", "model.mjs", "styles.css"]) {
  await cp(resolve(appDirectory, asset), resolve(distDirectory, asset));
}
await writeFile(resolve(distDirectory, "cases.json"), `${JSON.stringify(cases, null, 2)}\n`, "utf8");
console.log(`Built control-tower-web/dist with ${cases.length} fixture cases.`);
