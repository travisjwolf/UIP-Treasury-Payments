import { decisionTiming, paginate, title } from "./model.mjs";

const queue = document.querySelector("#queue");
const detail = document.querySelector("#detail");
const statusBadge = document.querySelector("#case-status");
const summary = document.querySelector("#queue-summary");
const pageLabel = document.querySelector("#page-label");
const previous = document.querySelector("#previous-page");
const next = document.querySelector("#next-page");

let cases = [];
let selected = null;
let page = 1;
let reviewStartedAt = performance.now();

const escapeHtml = (value) => String(value ?? "—")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

const money = (amount, currency) => new Intl.NumberFormat("en-US", {
  style: "currency",
  currency,
  maximumFractionDigits: 2,
}).format(amount);

function badgeClass(path) {
  if (path === "auto_apply") return "green";
  if (path === "callback_then_human") return "blue";
  if (path === "compliance_referral") return "red";
  return "amber";
}

function renderQueue() {
  const projection = paginate(cases, page);
  page = projection.page;
  summary.textContent = `${projection.totalItems} in-flight fixture cases`;
  pageLabel.textContent = `Page ${page} of ${projection.totalPages}`;
  previous.disabled = page === 1;
  next.disabled = page === projection.totalPages;
  queue.innerHTML = projection.items.map((item) => `
    <button class="case ${selected?.case_id === item.case_id ? "selected" : ""}" data-id="${escapeHtml(item.case_id)}" type="button">
      <span class="case-top"><strong>${escapeHtml(item.case_id)}</strong><span class="badge ${badgeClass(item.path)}">${escapeHtml(title(item.status))}</span></span>
      <span class="case-bottom"><span>${escapeHtml(item.payment.customer_name)}</span><span>${escapeHtml(money(item.payment.amount_usd, item.payment.currency))}</span></span>
      <span class="case-bottom"><span>${escapeHtml(item.payment.exception_code)} · ${escapeHtml(title(item.payment.exception_type))}</span><span>Cutoff ${escapeHtml(item.payment.cutoff_time)}</span></span>
    </button>`).join("");
  queue.querySelectorAll(".case").forEach((button) => {
    button.addEventListener("click", () => {
      selected = cases.find((item) => item.case_id === button.dataset.id);
      reviewStartedAt = performance.now();
      render();
    });
  });
}

function renderEvidence(items) {
  if (!items.length) return '<p class="muted">Evidence is produced when the read-only agent runs.</p>';
  return `<ol class="evidence-list">${items.map((item) => `
    <li><strong>${escapeHtml(item.type)}</strong><span>${escapeHtml(item.source)}</span><pre>${escapeHtml(JSON.stringify(item.content, null, 2))}</pre></li>`).join("")}</ol>`;
}

function renderDetail() {
  if (!selected) return;
  const proposal = selected.proposal;
  statusBadge.className = `badge ${badgeClass(selected.path)}`;
  statusBadge.textContent = title(selected.status);
  detail.innerHTML = `
    <div class="case-heading"><div><h2>${escapeHtml(selected.case_id)}</h2><p class="muted">${escapeHtml(selected.payment.customer_name)}</p></div><strong>${escapeHtml(money(selected.payment.amount_usd, selected.payment.currency))}</strong></div>
    <div class="detail-grid">
      <div class="metric"><span>Outcome</span><strong>${escapeHtml(selected.outcome)}</strong></div>
      <div class="metric"><span>Confidence</span><strong>${selected.confidence ?? "—"}</strong></div>
      <div class="metric"><span>Deterministic gate</span><strong>${escapeHtml(selected.gate)}</strong></div>
      <div class="metric"><span>Rail cutoff</span><strong>${escapeHtml(selected.payment.cutoff_time)}</strong></div>
      <div class="metric"><span>Beneficiary</span><strong>${escapeHtml(selected.payment.beneficiary_name)}</strong></div>
      <div class="metric"><span>Account on payment</span><strong>${escapeHtml(selected.payment.beneficiary_account)}</strong></div>
    </div>
    <section class="proposal"><h3>Proposed repair</h3>${proposal ? `<p><span>${escapeHtml(proposal.field)}</span><del>${escapeHtml(proposal.current_value)}</del><strong>→ ${escapeHtml(proposal.proposed_value)}</strong></p>` : '<p class="muted">No proposal available.</p>'}<p>${escapeHtml(selected.reason)}</p></section>
    <section><h3>Evidence packet (${selected.evidence.length})</h3>${renderEvidence(selected.evidence)}</section>
    <div class="actions">${selected.actions.map((action) => `<button type="button" data-action="${escapeHtml(action)}" class="${action === "approve" ? "primary" : ""}">${escapeHtml(title(action))}</button>`).join("")}</div>
    <p id="notice" role="status"></p>`;
  detail.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const timing = decisionTiming(reviewStartedAt);
      document.querySelector("#notice").textContent = `${title(button.dataset.action)} recorded in ${timing.elapsedSeconds.toFixed(1)}s (${timing.insideTarget ? "inside" : "outside"} the 20-second target). Sandbox only; no payment write performed.`;
    });
  });
}

function render() {
  renderQueue();
  renderDetail();
}

previous.addEventListener("click", () => { page -= 1; renderQueue(); });
next.addEventListener("click", () => { page += 1; renderQueue(); });

try {
  const response = await fetch("./cases.json");
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  cases = await response.json();
  selected = cases.find((item) => item.case_id === "WIRE-8841") ?? cases[0];
  render();
} catch (error) {
  detail.innerHTML = `<p class="error">Could not load fixture cases: ${escapeHtml(error.message)}</p>`;
}
