# Prime P7 ARC-AGI-3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reproduce Prime's IPython-mediated ARC-AGI-3 interaction boundary with a provider-free subset gate and separately authorized full-suite evidence path.

**Architecture:** A canonical workload and immutable redacted trace establish fixed identities and ceilings.  An injected broker adapter validates the one-game causal sequence; acceptance emits provider-free evidence only.  A separate private live reducer requires restricted-worker facts for bounded-sandboxed subset evidence and a distinct full-suite authorization object for full-authorized evidence.

**Tech Stack:** Python 3.12 dataclasses, `unittest`, existing Prime worker gate and evidence contracts.

## Global Constraints

- The model action surface is exactly `("ipython",)`; broker calls are host-owned interactions, not model tools.
- No Docker, game SDK, engine source, model, provider, network, benchmark, or `.env` access in tests.
- Public traces, errors, and representations contain only digests/counters—never game IDs, cells, actions, scores, prompts, paths, credentials, or raw output.
- One broker/session admits exactly one game and fences every call after terminal state.
- Provider-free and bounded-sandboxed subset claims never imply full multi-game reproduction.

### Task 1: Closed ARC workload and redacted interaction trace

**Files:**
- Create: `src/asterion/applications/prime_agent/operator/arc_agi_3_workload.py`
- Create: `src/asterion/applications/prime_agent/arc_agi_3_receipt.py`
- Create: `tests/test_prime_arc_agi_3_workload.py`
- Create: `tests/test_prime_arc_agi_3_receipt.py`

**Interfaces:** Produces `P7_ARC_AGI_3_WORKLOAD_DIGEST`, canonical manifest bytes, `is_arc_agi_3_workload`, `ArcAgi3Trace`, and `validate_arc_agi_3_trace(trace) -> None`.

- [ ] **Step 1: Write failing workload/trace tests.** Construct a valid trace that binds exact workload, fixture, broker schema, model, oracle, action encoding, observation/action/terminal/score digests, `("ipython",)`, one game, contiguous call count, finite usage, and cleanup.  Assert workload/schema/model/oracle mismatch; extra fields; non-IPython tool; duplicate or skipped sequence; multiple game count; terminal false; or malformed digest raises the fixed receipt error.
- [ ] **Step 2: Verify the red test.** Run `uv run python -m unittest -v tests.test_prime_arc_agi_3_workload tests.test_prime_arc_agi_3_receipt`; expected failure is missing module or symbol.
- [ ] **Step 3: Implement the closed values.** Canonicalize a manifest containing digest identities and finite ceilings only.  Define a frozen trace whose repr is redacted and whose validator uses exact type/field-set checks, rejects bool counters, and issues no evidence.
- [ ] **Step 4: Verify and commit.** Run the focused tests, scoped Ruff/Pyright, and `git diff --check`; commit `feat(prime): define ARC-AGI-3 workload trace`.

### Task 2: One-game broker adapter and provider-free acceptance

**Files:**
- Create: `src/asterion/applications/prime_agent/arc_agi_3_broker.py`
- Create: `src/asterion/applications/prime_agent/arc_agi_3_acceptance.py`
- Create: `tests/test_prime_arc_agi_3_broker.py`
- Create: `tests/test_prime_arc_agi_3_acceptance.py`

**Interfaces:** Produces `ArcAgi3BrokerObservation._admit`, `validate_arc_agi_3_broker_call`, `accept_arc_agi_3(*, broker, trace, disposed, reaped) -> PrimeEvidenceReceipt`, and `ArcAgi3AcceptanceError`.

- [ ] **Step 1: Write failing broker tests.** Use a recording injected broker that produces one initial observation, a contiguous action receipt, terminal status, and score replay.  Assert unknown method, a second game, a post-terminal action, duplicate/skipped sequence, mismatched action/result/score digest, unexpected broker exception, and missing cleanup all fail with the one redacted error.
- [ ] **Step 2: Verify the red test.** Run `uv run python -m unittest -v tests.test_prime_arc_agi_3_broker tests.test_prime_arc_agi_3_acceptance`; expected failure is missing module or symbol.
- [ ] **Step 3: Implement narrow admission and acceptance.** Require the validated trace before any injected call, invoke only `observe`, `act`, and `status` in declared sequence, compare each normalized digest to the trace, execute one host-owned replay check, and return exactly `PrimeEvidenceLevel.PROVIDER_FREE`.  Catch ordinary injected exceptions but not cancellation.
- [ ] **Step 4: Verify and commit.** Run Tasks 1–2 plus `tests.test_prime_capability_evidence`, scoped Ruff/Pyright, and diff check; commit `feat(prime): accept ARC-AGI-3 subset trace`.

### Task 3: Live subset and full-suite authorization reducers

**Files:**
- Create: `src/asterion/applications/prime_agent/arc_agi_3_live_validation.py`
- Create: `tests/test_prime_arc_agi_3_live_validation.py`

**Interfaces:** Produces private `ArcAgi3LiveObservation._admit`, `ArcAgi3LiveAuthorization`, `ArcAgi3FullAuthorization`, `validate_arc_agi_3_subset_result(observation, authorization) -> PrimeEvidenceReceipt`, and `validate_arc_agi_3_full_result(observation, authorization, full_authorization) -> PrimeEvidenceReceipt`.

- [ ] **Step 1: Write failing live-boundary tests.** Admit a valid P7 trace with a matching `PrimeWorkerBoundaryReceipt` and exact lock.  Assert complete subset authorization issues only `bounded-sandboxed`; raw trace, role/scenario/result/lock mismatch, and every false IPython/broker/replay/quiescence/destruction fact reject.  Assert full evidence rejects a subset result, false authorization, suite digest/count/lock mismatch, missing distinct full result, and accepts only an exact finite full-suite fact set.
- [ ] **Step 2: Verify the red test.** Run `uv run python -m unittest -v tests.test_prime_arc_agi_3_live_validation`; expected failure is missing module or symbol.
- [ ] **Step 3: Implement private admission and revalidation.** Revalidate closed dataclass fields, trace, lock, worker scenario/role/result, and all subset attestations immediately before bounded-sandboxed issuance.  Revalidate the full authorization independently; require exact suite/lock/count/digest and `full_reproduction_approved is True` before `full-authorized` issuance.  Start no worker or game.
- [ ] **Step 4: Verify and commit.** Run every P7 test plus `tests.test_prime_worker_gate tests.test_prime_capability_evidence`, scoped Ruff/Pyright, and diff check; commit `feat(prime): gate ARC-AGI-3 evidence`.

## Self-review

- Task 1 proves all fixed identities and closed trace ceilings.
- Task 2 proves one-game broker isolation, causal ordering, score replay, and provider-free evidence separation.
- Task 3 proves restricted-worker subset evidence and separate full-suite authorization without starting an external runtime.
