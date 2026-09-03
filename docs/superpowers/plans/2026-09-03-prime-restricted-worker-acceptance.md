# Prime Restricted-Worker Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bind sandboxed Prime acceptance evidence to one exact restricted-worker lifecycle.

**Architecture:** Domain-neutral worker values bind role, workload, and worker-derived result digests. Prime maps each of seven scenarios to a closed role and issues bounded evidence only after gate verification. Trusted-local P5/P6 results become diagnostic-only.

**Tech Stack:** Python 3.12 dataclasses and unittest.

## Global Constraints

- No bounded-sandboxed claim without isolated worker, finite limits, completed result, and cleanup.
- Public receipts contain digests and IDs only.
- Docker remains Product-1-only; no launcher, Docker, model, or platform behavior changes.

### Task 1: Domain-neutral worker identity chain

**Files:** `src/asterion/services/restricted_worker.py`, `src/asterion/services/__init__.py`, `tests/test_restricted_worker_service.py`.

- [ ] Write failing tests for exact role/workload/result matching and completed execution.
- [ ] Run `uv run python -m unittest -v tests.test_restricted_worker_service`; expect failure because those fields do not exist.
- [ ] Add immutable role/workload fields to request, lease, attestation, cleanup and `RestrictedWorkerExecutionReceipt(worker_id, role_id, run_id, challenge_digest, workload_digest, result_digest, terminal="completed")`; update service protocol and verifier.
- [ ] Run focused unittest, Ruff, and Pyright; expect PASS.
- [ ] Commit `feat(worker): bind restricted execution result`.

### Task 2: Prime scenario-exact worker gate

**Files:** `src/asterion/applications/prime_agent/worker_gate.py`, `src/asterion/applications/prime_agent/evidence.py`, `tests/test_prime_worker_gate.py`, `tests/test_prime_capability_evidence.py`.

- [ ] Write a seven-scenario subTest matrix and reject cross-role, workload, result, direct-issuer, and cleanup substitutions.
- [ ] Run focused tests; expect failure because the gate is Product-1-only.
- [ ] Add closed `PRIME_SCENARIO_WORKER_ROLES`, guarded `PrimeWorkerBoundaryReceipt`, scenario-aware gate, and central bounded-evidence issuer.
- [ ] Run focused unittest, Ruff, and Pyright; expect PASS.
- [ ] Commit `feat(prime): bind sandboxed evidence to worker`.

### Task 3: Close Product 5 and Product 6 false promotion paths

**Files:** `src/asterion/applications/prime_agent/bounded_autonomy_receipt.py`, `src/asterion/applications/prime_agent/continual_improvement_receipt.py`, and their tests.

- [ ] Write failing tests: trusted-local receipt alone fails; wrong worker scenario/result digest fails; matching gate receipt passes.
- [ ] Run tests; expect failure because direct bounded issuance succeeds.
- [ ] Add canonical source-receipt digest and require matching worker result digest before central issuance.
- [ ] Run Product 5/6 plus long-running/harness regression tests and `git diff --check`; expect PASS.
- [ ] Commit `fix(prime): reject trusted-local sandbox promotion`.

## Self-review

- Task 1 supplies every identity Task 2 and Task 3 require.
- Task 2 closes evidence issuance centrally.
- Task 3 preserves trusted-local diagnostics but removes false formal PASS claims.
