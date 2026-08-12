import assert from "node:assert/strict";
import test from "node:test";

import {
  completeTaskWithState,
  isOutcomeSubmittable,
  type Outcome,
  type Proposal,
} from "../src/approvalLogic.ts";

const validProposal: Proposal = {
  field: "beneficiary_account",
  current_value: "882300441",
  proposed_value: "8823004417",
};

test("a resolved unsuccessful completion exposes the service error and re-enables submission", async () => {
  const taskData = { proposal: validProposal };
  const calls: Array<{ action: string; taskData: unknown }> = [];
  const submitting: Array<Outcome | null> = [];
  const errors: string[] = [];

  const completed = await completeTaskWithState({
    action: "Approve",
    taskData,
    completeTask: async (action, submittedData) => {
      calls.push({ action, taskData: submittedData });
      return {
        success: false,
        errorCode: 409,
        errorMessage: "Action Center rejected the completion.",
      };
    },
    setSubmitting: (value) => submitting.push(value),
    setError: (value) => errors.push(value),
  });

  assert.equal(completed, false);
  assert.deepEqual(calls, [{ action: "Approve", taskData }]);
  assert.deepEqual(errors, ["", "Action Center rejected the completion."]);
  assert.deepEqual(submitting, ["Approve", null]);
});

test("a thrown completion error exposes its message and re-enables submission", async () => {
  const submitting: Array<Outcome | null> = [];
  const errors: string[] = [];

  const completed = await completeTaskWithState({
    action: "Edit",
    taskData: { proposal: validProposal },
    completeTask: async () => {
      throw new Error("Action Center timed out.");
    },
    setSubmitting: (value) => submitting.push(value),
    setError: (value) => errors.push(value),
  });

  assert.equal(completed, false);
  assert.deepEqual(errors, ["", "Action Center timed out."]);
  assert.deepEqual(submitting, ["Edit", null]);
});

test("only a confirmed successful completion keeps submission locked", async () => {
  const submitting: Array<Outcome | null> = [];
  const errors: string[] = [];

  const completed = await completeTaskWithState({
    action: "Approve",
    taskData: { proposal: validProposal },
    completeTask: async () => ({
      success: true,
      errorCode: null,
      errorMessage: null,
    }),
    setSubmitting: (value) => submitting.push(value),
    setError: (value) => errors.push(value),
  });

  assert.equal(completed, true);
  assert.deepEqual(errors, [""]);
  assert.deepEqual(submitting, ["Approve"]);
});

test("Approve and Edit require a complete proposal whose value actually changes", () => {
  const invalidProposals: Array<{ name: string; proposal: Proposal }> = [
    { name: "blank field", proposal: { ...validProposal, field: "   " } },
    { name: "blank current value", proposal: { ...validProposal, current_value: " " } },
    { name: "blank proposed value", proposal: { ...validProposal, proposed_value: "" } },
    { name: "unchanged value", proposal: { ...validProposal, proposed_value: " 882300441 " } },
  ];

  for (const action of ["Approve", "Edit"] as const) {
    assert.equal(isOutcomeSubmittable(action, validProposal), true, `${action} should accept a valid change`);
    for (const invalid of invalidProposals) {
      assert.equal(
        isOutcomeSubmittable(action, invalid.proposal),
        false,
        `${action} should reject ${invalid.name}`,
      );
    }
  }
});

test("Reject and Escalate remain available when the proposal is incomplete or unchanged", () => {
  const incompleteProposal: Proposal = {
    field: "",
    current_value: "same",
    proposed_value: "same",
  };

  assert.equal(isOutcomeSubmittable("Reject", incompleteProposal), true);
  assert.equal(isOutcomeSubmittable("Escalate", incompleteProposal), true);
});
