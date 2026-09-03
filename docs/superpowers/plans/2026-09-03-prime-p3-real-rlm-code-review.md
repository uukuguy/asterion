# Prime P3 Real RLM Code-Review Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the shim-only P3 witness with a sealed two-child Prime RLM code-review workflow whose bounded evidence only originates from real IPython/RLM execution.

**Architecture:** P3 owns a fixed review workload, canonical causal trace, private launcher protocol, dedicated worker/broker facade, and bounded reducer. Provider-free fakes exercise exact denial paths through a non-promotable observation. Only separately authorized real execution supplies bounded evidence.

**Tech Stack:** Python 3.11 frozen dataclasses, unittest, SHA-256 canonical JSON, Node 22 ESM, pinned Prime RLM/IPython gateway, sealed worker lifecycle.

## Global Constraints

- P3 accepts only scenario `prime.recursive-workflow/v1`, role `prime.recursive-workflow`, one code-owned workload/image identity, depth one, and two fixed child roles.
- Root and child model tools are exactly `("ipython",)`; RLM, messaging, and deletion are IPython imports, never extra model tools.
- Requests cannot supply review text, goals, messages, code, paths, commands, models, budgets, environment, credentials, or provider configuration.
- P3 has a dedicated worker/image/entrypoint/seccomp/workload; P1 and P2 identities are rejected, never parameterized.
- Provider-free tests prove contracts only. Docker/model/network/benchmark results are not PASS until separately authorized.
- Public reports/errors/receipts expose only hashes, counts, booleans, and fixed IDs.

---

### Task 1: Deny shim promotion and define the real-RLM trace

**Files:**
- Modify: `src/asterion/applications/prime_agent/recursive_workflow_receipt.py`
- Modify: `tests/test_prime_recursive_workflow_receipt.py`
- Modify: `tests/test_prime_recursive_workflow_compat.py`

**Produces:** frozen `RecursiveWorkflowTrace` containing workload, root artifact, two first-child result digests, one follow-up digest, aggregation/oracle/model/usage digests, causal counts, root-local-work boolean, revoke, and destruction booleans; `verify_real_recursive_workflow_trace(trace, PrimeEvidenceLevel.BOUNDED)`.

- [ ] Write failing tests that an old `asterion.prime-recursive-workflow-compat/v1` PASS cannot issue P3 evidence; reject missing root local work, child IPython action, second child result, follow-up, root-driven deletion, usage digest, revoke, destruction, malformed digest, and every P1/P2 identity.
- [ ] Run `uv run python -m unittest -v tests.test_prime_recursive_workflow_receipt tests.test_prime_recursive_workflow_compat`; expect failure because shim reports remain promotable and the real trace contract is absent.
- [ ] Implement only the closed trace verifier. Require two normalized child roles/results/usage digests; counts root-to-child=2, child-to-root=3, follow-up=1, root-deleted=2; root work before children; each child IPython count positive; oracle, revoke, and destruction true. Redact invalid private fields. Issue bounded evidence only through `validate_prime_evidence_receipt`.
- [ ] Run the receipt/compat/capability-evidence tests, scoped Ruff, Pyright, and `git diff --check`; expect PASS without a process, provider, Docker, or network call.
- [ ] Commit `feat(prime): require real recursive workflow trace`.

### Task 2: Seal the P3 review workload and launcher parser

**Files:**
- Create: `src/asterion/applications/prime_agent/operator/recursive_code_review_workload.py`
- Create: `src/asterion/applications/prime_agent/operator/recursive_code_review_release.py`
- Create: `src/asterion/applications/prime_agent/operator/recursive_code_review_image/Dockerfile`
- Create: `src/asterion/applications/prime_agent/operator/recursive_code_review_image/launcher.mjs`
- Create: `src/asterion/applications/prime_agent/operator/recursive_code_review_image/fixture-lock.json`
- Create: `tests/test_prime_recursive_code_review_workload.py`
- Create: `tests/test_prime_recursive_code_review_launcher_protocol.py`

**Produces:** code-owned scenario/role/child role constants, canonical workload bytes/digest, and `parse_recursive_code_review_frames(data: bytes) -> RecursiveWorkflowTrace`.

- [ ] Write failing tests for exact immutable manifest digest, P1/P2 cross-rejection, root artifact preceding child results, two admissions/results, one retained-child follow-up/result, aggregation, two root deletions, canonical terminal frame, cap/deadline failures, and redaction.
- [ ] Run the two new test modules; expect failure because no P3 workload/parser exists.
- [ ] Implement fixed repository/oracle/model/schema identities, depth one, two role names, one follow-up target, and finite ceilings. Implement an input-free launcher with no stdin, argv, environment, prompt, source, generic command, or generic execution surface. Its live path invokes pinned Prime RLM from image-owned IPython and emits only the canonical trace frames.
- [ ] Run the new workload/parser/receipt tests, scoped Ruff/Pyright, `node --check` for the launcher, and `git diff --check`; expect provider-free PASS only.
- [ ] Commit `feat(prime): define sealed recursive review workload`.

### Task 3: Implement the P3 worker and one-use RLM broker lifecycle

**Files:**
- Create: `src/asterion/applications/prime_agent/operator/recursive_code_review_worker.py`
- Create: `src/asterion/applications/prime_agent/operator/recursive_code_review_docker_cli.py`
- Create: `tests/test_prime_recursive_code_review_worker.py`
- Create: `tests/test_prime_recursive_code_review_docker_cli.py`

**Produces:** `RecursiveCodeReviewBroker.admit_root`, `relay_once`, `revoke`; and `RecursiveCodeReviewDockerWorker.open`, `execution_receipt`, `cleanup_receipt`.

- [ ] Write failing fake-engine/fake-broker tests for exact P3 role/image/workload/entrypoint/seccomp/empty-environment admission, noncanonical completion rejection, P1/P2 rejection, one-use broker behavior, follow-up/deletion before revoke, durable usage before revoke, rejected-lease removal, and cancellation-hard cleanup.
- [ ] Run the new worker/CLI tests; expect failure because P3 facades do not exist.
- [ ] Implement separate sealed P3 facades. Parse canonical P3 completion bytes before hashing; remove any returned lease on post-launch rejection; use repeated shielding until removal completes; record correlation/usage only as bounded data; refuse broker reuse; never add generic execute, model, command, or config interfaces.
- [ ] Run P3 worker/CLI/launcher tests, scoped Ruff/Pyright, and `git diff --check`; expect fake-only PASS.
- [ ] Commit `feat(prime): run sealed recursive review worker`.

### Task 4: Orchestrate provider-free acceptance and gate live evidence

**Files:**
- Create: `src/asterion/applications/prime_agent/recursive_code_review_acceptance.py`
- Create: `src/asterion/applications/prime_agent/recursive_code_review_live_validation.py`
- Create: `tests/test_prime_recursive_code_review_acceptance.py`
- Create: `tests/test_prime_recursive_code_review_live_validation.py`
- Modify: `docs/status/RESUME-NEXT-SESSION.md`
- Modify: `docs/status/JOURNAL.md`

**Produces:** `accept_recursive_code_review(...)` and `validate_recursive_code_review_live_result(observation)`.

- [ ] Write failing fake full-chain tests for profile preflight before any service property access, identity mismatch rejection, old shim rejection, fake-to-bounded non-promotion, and missing live authorization rejection.
- [ ] Run the two acceptance modules; expect failure because orchestration/live validation does not exist.
- [ ] Implement causal orchestration: profile validation precedes injected-service inspection; fakes can only return provider-free diagnostic or External-limited; live validation requires explicit authorization, exact platform lock, real Prime RLM/IPython attestation, trace/usage digests, broker quiescence, and worker destruction. The validator never launches Docker or a provider.
- [ ] Run acceptance/live/worker/launcher/receipt/gate tests, scoped Ruff/Pyright, and `git diff --check`; expect provider-free PASS and accurate External-limited state documentation.
- [ ] Commit `docs(prime): record recursive review verification`.

## Plan Self-Review

- Task 1 eliminates shim promotion; Task 2 seals workload/protocol; Task 3 seals lifecycle; Task 4 proves fake non-promotion and gates authorized real evidence.
- Every task has exact files, test targets, rejection paths, verification commands, and a focused commit.
- Tasks 2–4 consume `RecursiveWorkflowTrace`; Task 1 alone issues P3 bounded evidence, while Task 4 supplies the mandatory real-execution precondition.
