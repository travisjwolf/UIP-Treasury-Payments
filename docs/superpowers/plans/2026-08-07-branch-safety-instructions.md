# Branch Safety Instructions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Alpha, Bravo, and Charlie branch instructions explicit, non-overlapping, and safe to merge into `main` without terminating workers or destroying changes.

**Architecture:** Keep role ownership and merge policy centralized in `AGENTS.md` and `docs/three-instance-build-plan.md`. Each role receives a precise owned-path list, forbidden-path list, checkpoint boundary, and handoff contract. Integration uses reviewed fast-forward or merge commits only; destructive recovery commands and process termination are prohibited.

**Tech Stack:** Markdown documentation, Git, PowerShell verification commands.

## Global Constraints

- Only `alpha`, `bravo`, and `charlie` are implementation branches.
- A role edits only its owned paths, except documented integration-only changes by Alpha.
- No role terminates another worker, deletes another worker's worktree, resets shared history, force-pushes, or overwrites uncommitted changes.
- Every branch merges to `main` only after its checkpoint exit commands pass and the handoff includes the exact commit SHA.
- Merge order is Alpha, then Bravo, then Charlie.

---

### Task 1: Strengthen shared agent instructions

**Files:**
- Modify: `AGENTS.md`

- [ ] Add explicit role ownership, forbidden paths, non-destructive worker rules, and safe merge requirements to the existing three-instance dispatch section.
- [ ] Preserve the existing project contracts and build order.
- [ ] Verify the new rules reference the plan as the source of truth.

### Task 2: Strengthen the branch execution plan

**Files:**
- Modify: `docs/three-instance-build-plan.md`

- [ ] Add a path ownership matrix with explicit forbidden paths for each role.
- [ ] Add start-of-checkpoint checks and a stop rule when an upstream checkpoint is missing.
- [ ] Add safe synchronization and merge commands that preserve work and never terminate another worker.
- [ ] Add required handoff evidence and post-merge resynchronization instructions.

### Task 3: Verify the documentation contract

**Files:**
- Test: `AGENTS.md`
- Test: `docs/three-instance-build-plan.md`

- [ ] Confirm the three remote branches point to the same updated documentation baseline.
- [ ] Confirm Alpha, Bravo, and Charlie have distinct owned paths and explicit forbidden paths.
- [ ] Confirm the documentation contains no process-termination, destructive-reset, or force-push instructions.
- [ ] Confirm the merge order and checkpoint evidence requirements are present.

