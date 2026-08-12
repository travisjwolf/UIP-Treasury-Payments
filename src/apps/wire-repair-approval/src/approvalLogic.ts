export type Scalar = string | number | boolean | null;
export type Proposal = {
  field: string;
  current_value: Scalar;
  proposed_value: Scalar;
};
export type Outcome = "Approve" | "Edit" | "Reject" | "Escalate";

type TaskCompleteResponse = {
  success: boolean;
  errorCode: number | null;
  errorMessage: string | null;
};

type CompletionOptions = {
  action: Outcome;
  taskData: { proposal: Proposal };
  completeTask: (action: string, data: unknown) => Promise<TaskCompleteResponse>;
  setSubmitting: (outcome: Outcome | null) => void;
  setError: (message: string) => void;
};

const normalizedScalar = (value: Scalar) => value === null ? "" : String(value).trim();

export const isOutcomeSubmittable = (action: Outcome, proposal: Proposal) => {
  if (action === "Reject" || action === "Escalate") return true;

  const field = proposal.field.trim();
  const currentValue = normalizedScalar(proposal.current_value);
  const proposedValue = normalizedScalar(proposal.proposed_value);
  return Boolean(field && currentValue && proposedValue && proposedValue !== currentValue);
};

export async function completeTaskWithState({
  action,
  taskData,
  completeTask,
  setSubmitting,
  setError,
}: CompletionOptions): Promise<boolean> {
  if (!isOutcomeSubmittable(action, taskData.proposal)) {
    setError("Approve and Edit require a field, current value, and a different proposed value.");
    setSubmitting(null);
    return false;
  }

  setSubmitting(action);
  setError("");
  let completionConfirmed = false;
  try {
    const result = await completeTask(action, taskData);
    if (result.success !== true) {
      setError(result.errorMessage?.trim() || "Task completion failed.");
      return false;
    }
    completionConfirmed = true;
    return true;
  } catch (reason) {
    setError(reason instanceof Error ? reason.message : "Task completion failed.");
    return false;
  } finally {
    if (!completionConfirmed) setSubmitting(null);
  }
}
