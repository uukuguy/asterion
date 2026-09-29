# Generic P7 Live Optimizer Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven development or execute this plan task-by-task.

**Goal:** Apply the existing fresh-ARC route optimizer before every eligible P7 live run and expose bounded optimization evidence.

**Architecture:** The operator converts a sealed `VerifiedPrefix` into immutable optimizer actions, invokes `optimize_arc_route()` before starting the live engine, and injects only a verified shorter route into the generic prompt. Optimization is best-effort and falls back to the sealed route; diagnostics remain private.

**Tech Stack:** Python dataclasses, ARC SDK wheels, unittest, existing P7 trace/summary infrastructure.

## Global Constraints

- Keep P7 game-neutral; no BP35 IDs or puzzle coordinates in production code.
- Use exact game/seed identity and fresh ARC engines for every candidate.
- Keep public receipts redacted; optimization details belong in private diagnostics.
- Preserve the current verified-route behavior when optimization is unavailable.

### Task 1: Add failing operator tests

**Files:**
- Modify: `tests/test_prime_p7_live_command.py`

- [ ] Add tests asserting a verified route is converted and shortened optimizer output is used in the prompt.
- [ ] Add a test asserting optimizer exceptions preserve the original route and produce fallback diagnostics.
- [ ] Run the focused tests and confirm the new tests fail because the integration hook is absent.

### Task 2: Integrate best-effort optimization

**Files:**
- Modify: `src/asterion/applications/prime/p7/operator.py`
- Modify: `src/asterion/applications/prime/p7/live.py` only if private diagnostic plumbing requires it.

- [ ] Add a generic transition-to-`PlannerAction` converter with strict action/data validation.
- [ ] Invoke `optimize_arc_route()` before live engine creation with bounded settings.
- [ ] Use the optimized route only when replay success is true and it is shorter; otherwise use the original route.
- [ ] Add bounded private optimization metadata to the run summary without changing the public receipt schema.
- [ ] Run the new focused tests and the existing P7 optimizer/live suites.

### Task 3: Verify the real run

**Files:**
- Modify: `docs/status/JOURNAL.md`

- [ ] Run BP35 L1 with GPT-6-Sol and debug transcript enabled.
- [ ] Project each model decision, candidate count, action, feedback, retry, and terminal state without printing raw prompts or secrets.
- [ ] Verify final receipt, replay seal, optimized route length, and clean Git status.
- [ ] Record the run evidence and any remaining boundary in the journal.
