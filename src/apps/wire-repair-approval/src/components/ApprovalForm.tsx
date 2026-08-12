import { useEffect, useMemo, useState } from "react";
import { Theme } from "@uipath/coded-action-app";
import {
  completeTaskWithState,
  isOutcomeSubmittable,
  type Outcome,
  type Proposal,
  type Scalar,
} from "../approvalLogic";
import { codedActionAppService } from "../uipath";

type PaymentCase = Record<string, Scalar> & {
  case_id: string;
  amount_usd: number;
  currency: string;
  customer_name: string;
  beneficiary_name: string;
  beneficiary_account: string;
  exception_code: string;
};
type Evidence = { type: string; source: string; content: unknown; produced_by?: string; timestamp?: string };
type TaskData = {
  payment: PaymentCase;
  proposal: Proposal;
  gate: string;
  reason: string;
  evidence: Evidence[];
  cutoff_time: string;
  permitted_actions: string[];
};

const emptyData: TaskData = {
  payment: { case_id: "", amount_usd: 0, currency: "USD", customer_name: "", beneficiary_name: "", beneficiary_account: "", exception_code: "" },
  proposal: { field: "", current_value: "", proposed_value: "" },
  gate: "",
  reason: "",
  evidence: [],
  cutoff_time: "",
  permitted_actions: [],
};

const isDark = (theme: Theme) => theme === Theme.Dark || theme === Theme.DarkHighContrast;
const normalizedAction = (outcome: Outcome) => outcome.toLowerCase();

export default function ApprovalForm({ onInitTheme }: { onInitTheme: (dark: boolean) => void }) {
  const [taskData, setTaskData] = useState<TaskData>(emptyData);
  const [isReadOnly, setIsReadOnly] = useState(true);
  const [submitting, setSubmitting] = useState<Outcome | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    codedActionAppService.getTask().then((task) => {
      if (task.data) setTaskData(task.data as TaskData);
      setIsReadOnly(task.isReadOnly);
      onInitTheme(isDark(task.theme));
    }).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Unable to load the task."));
  }, [onInitTheme]);

  const allowed = useMemo(() => new Set(taskData.permitted_actions.map((value) => value.toLowerCase())), [taskData.permitted_actions]);
  const updateProposal = (proposed_value: string) => {
    if (isReadOnly) return;
    const updated = { ...taskData, proposal: { ...taskData.proposal, proposed_value } };
    setTaskData(updated);
    codedActionAppService.setTaskData(updated);
  };
  const submit = async (action: Outcome) => {
    await completeTaskWithState({
      action,
      taskData,
      completeTask: (outcome, data) => codedActionAppService.completeTask(outcome, data),
      setSubmitting,
      setError,
    });
  };
  const money = new Intl.NumberFormat("en-US", { style: "currency", currency: taskData.payment.currency || "USD" }).format(taskData.payment.amount_usd);

  return (
    <article className="approval-card">
      <header className="task-header">
        <div><p className="eyebrow">Action Center · wire repair</p><h1>{taskData.payment.case_id || "Loading task…"}</h1><p>{taskData.payment.customer_name}</p></div>
        <div className="deadline"><span>Rail cutoff</span><strong>{taskData.cutoff_time || "—"}</strong></div>
      </header>

      <section className="summary-grid" aria-label="Payment summary">
        <div><span>Amount</span><strong>{money}</strong></div><div><span>Exception</span><strong>{taskData.payment.exception_code}</strong></div>
        <div><span>Beneficiary</span><strong>{taskData.payment.beneficiary_name}</strong></div><div><span>Account</span><strong>{taskData.payment.beneficiary_account}</strong></div>
      </section>

      <section className="gate"><div className="gate-id">{taskData.gate || "Gate"}</div><div><h2>Autonomy refused</h2><p>{taskData.reason}</p></div></section>

      <section className="proposal">
        <h2>Evidence-backed proposal</h2><p className="field-name">{taskData.proposal.field}</p>
        <div className="before-after"><div><span>Current</span><del>{String(taskData.proposal.current_value ?? "")}</del></div><label><span>Proposed</span><input aria-label="Proposed value" value={String(taskData.proposal.proposed_value ?? "")} onChange={(event) => updateProposal(event.target.value)} readOnly={isReadOnly} /></label></div>
      </section>

      <section><h2>Evidence packet <span className="count">{taskData.evidence.length}</span></h2><ol className="evidence-list">{taskData.evidence.map((item, index) => <li key={`${item.source}-${index}`}><div><strong>{item.type}</strong><span>{item.source}</span></div><pre>{JSON.stringify(item.content, null, 2)}</pre></li>)}</ol></section>

      {error && <p className="error" role="alert">{error}</p>}
      <footer className="actions">
        {(["Approve", "Edit", "Reject", "Escalate"] as Outcome[]).filter((outcome) => allowed.has(normalizedAction(outcome))).map((outcome) => <button key={outcome} type="button" className={outcome === "Approve" ? "primary" : "secondary"} disabled={isReadOnly || submitting !== null || !isOutcomeSubmittable(outcome, taskData.proposal)} onClick={() => submit(outcome)}>{submitting === outcome ? "Recording…" : outcome}</button>)}
      </footer>
      <p className="boundary">The repair agent cannot write. Approval authorizes the separately credentialed effector and preserves the audit trail.</p>
    </article>
  );
}
