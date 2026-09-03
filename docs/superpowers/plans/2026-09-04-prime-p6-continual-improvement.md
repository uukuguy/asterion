# Prime P6 Continual Improvement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the fixed P6 task-A evidence, candidate revision, task-B holdout, and exact rollback acceptance product.

**Architecture:** Reuse `HarnessCoordinator` for all revision and inverse-rollback behavior. New Prime application modules define a canonical IPython-only workload and private trace, call an injected holdout once, and issue only provider-free evidence locally. A private live reducer requires worker, lock, holdout, and global-scope authorization facts.

**Tech Stack:** Python 3.12 dataclasses, unittest, existing HarnessCoordinator and Prime worker gate.

## Global Constraints

- No Docker, model, network, benchmark, provider, or `.env` access in tests.
- No prompt, task body, rationale, private ref, workspace, provider payload, or credential in public values/errors.
- Reuse `HarnessCoordinator.rollback`; do not duplicate revision state or inverse-edit logic.
- Model action surface is exactly `("ipython",)`; provider-free evidence never promotes to bounded.

---

### Task 1: Fixed workload and causal trace

**Files:**
- Create: `src/asterion/applications/prime_agent/operator/continual_improvement_workload.py`
- Modify: `src/asterion/applications/prime_agent/continual_improvement_receipt.py`
- Create: `tests/test_prime_continual_improvement_workload.py`
- Modify: `tests/test_prime_continual_improvement_receipt.py`

**Interfaces:** Produces `P6_CONTINUAL_IMPROVEMENT_WORKLOAD_DIGEST`, canonical manifest bytes, `is_continual_improvement_workload`, `ContinualImprovementTrace`, and `validate_continual_improvement_trace(trace) -> None`.

- [ ] **Step 1: Write failing workload/trace tests.** Construct a valid trace with the exact workload/model/oracle/schema identities, distinct baseline/candidate snapshot digests, one task-A evidence digest, one task-B digest, `("ipython",)`, bounded counts, and either the exact `preserved` or `rolled-back` branch. Assert invalid workload, non-IPython tool, equal snapshots, false cleanup, invalid branch facts, count booleans, and extra fields raise the fixed receipt error.
- [ ] **Step 2: Run the focused tests.** Run `uv run python -m unittest -v tests.test_prime_continual_improvement_workload tests.test_prime_continual_improvement_receipt`; expect import/trace failures before implementation.
- [ ] **Step 3: Implement canonical workload and non-signing trace validation.** The manifest contains only digest identities, fixture digest, exact tool list, finite action/usage/deadline/cost ceilings, one candidate, one holdout, one rollback maximum, and CRUD/type coverage identifiers. Validate all trace fields exactly and bind all identities to manifest constants; return no receipt.
- [ ] **Step 4: Verify and commit.** Run the focused tests, scoped Ruff/Pyright, and `git diff --check`; commit `feat(prime): define continual improvement trace`.

### Task 2: Holdout and rollback acceptance

**Files:**
- Create: `src/asterion/applications/prime_agent/continual_improvement_acceptance.py`
- Create: `tests/test_prime_continual_improvement_acceptance.py`

**Interfaces:** Consumes an admitted `HarnessCoordinator`, one injected `evaluate(candidate_snapshot_id: str) -> tuple[bool, str]`, trace, and cleanup facts. Produces `accept_continual_improvement(...) -> PrimeEvidenceReceipt` and `ContinualImprovementAcceptanceError`.

- [ ] **Step 1: Write failing chain tests.** Use a recording fake holdout and a harness coordinator with one admitted candidate. Assert the preserve branch calls the holdout exactly once and returns only `provider-free`; assert the rollback branch calls `coordinator.rollback` through a recording wrapper and restores the baseline projection. Assert replayed holdout, mismatched digest/snapshot/revision, unadmitted candidate, and unexpected injected exceptions fail with a redacted error.
- [ ] **Step 2: Run the focused test.** Run `uv run python -m unittest -v tests.test_prime_continual_improvement_acceptance`; expect module import failure.
- [ ] **Step 3: Implement the narrow adapter.** Validate trace before injected work, require candidate state to match trace, run one normalized holdout, compare its digest/outcome to the declared branch, and invoke only the existing coordinator rollback API for the rollback branch. Catch ordinary injected exceptions without swallowing cancellation, and emit `PrimeEvidenceLevel.PROVIDER_FREE` only.
- [ ] **Step 4: Verify and commit.** Run Task 1–2 tests plus `tests.test_control_harness`, scoped Ruff/Pyright, and diff check; commit `feat(prime): accept continual improvement`.

### Task 3: Live authorization reducer

**Files:**
- Create: `src/asterion/applications/prime_agent/continual_improvement_live_validation.py`
- Create: `tests/test_prime_continual_improvement_live_validation.py`

**Interfaces:** Produces private `ContinualImprovementLiveObservation._admit`, `ContinualImprovementLiveAuthorization`, and `validate_continual_improvement_live_result(observation, authorization) -> PrimeEvidenceReceipt`.

- [ ] **Step 1: Write failing reducer tests.** Admit a valid exact P6 trace with a matching `PrimeWorkerBoundaryReceipt`; assert complete authorization returns `bounded`. Assert raw trace, lock mismatch, worker scenario/result mismatch, false task-B/broker/destruction attestations, and global scope without matching explicit global approval all reject.
- [ ] **Step 2: Run the focused test.** Run `uv run python -m unittest -v tests.test_prime_continual_improvement_live_validation`; expect module import failure.
- [ ] **Step 3: Implement private admission and revalidation.** Admit only exact trace, full lock digest, P6 worker role/result, and scope digest. Reducer must revalidate fields and trace before issuing bounded evidence; require `global_activation_approved is True` and matching authorization scope digest only for a global trace. Do not start any runtime.
- [ ] **Step 4: Verify and commit.** Run every P6 test plus `tests.test_prime_worker_gate`, scoped Ruff/Pyright, and diff check; commit `feat(prime): gate continual improvement evidence`.

## Self-review

- Task 1 covers all fixed workload and trace identities/ceilings.
- Task 2 uses the existing coordinator for rollback and proves fake-chain level separation.
- Task 3 covers the separately authorized live boundary, including global scope.
