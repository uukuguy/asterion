# Prime P2 Restricted Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Deliver a sealed P2 long-context worker whose bounded evidence is causally bound to a host-brokered model response, real Prime IPython execution, oracle success, and worker cleanup.

**Architecture:** P2 gets its own fixed workload registry, image, launcher protocol, Docker facade, and bounded reducer. Shared restricted-worker lifecycle and boundary gate remain unchanged; P1 and P2 reject each other at every role/workload/entrypoint boundary.

**Tech Stack:** Python 3.11, Node ESM, IPython/Prime fixture, unittest, SHA-256, existing restricted-worker lifecycle.

## Global Constraints

- P2 accepts only role prime.programmatic-long-context and one code-owned workload digest.
- No request carries code, corpus, prompt, command, path, environment, credential, or provider configuration.
- P1 and P2 images, entrypoints, schemas, and workloads are sealed and mutually rejecting.
- Completion is canonical, bounded, public-safe, and binds broker response/program/aggregate/oracle digests.
- Existing provider-free P2 compatibility evidence cannot issue bounded evidence.
- Provider-free tests do not run Docker, a model, network activity, or a benchmark.

---

### Task 1: Deny compatibility-to-bounded promotion and define bounded P2 facts

**Files:**
- Create: src/asterion/applications/prime_agent/programmatic_long_context_bounded_receipt.py
- Create: tests/test_prime_programmatic_long_context_bounded_receipt.py
- Modify: tests/test_prime_programmatic_long_context_receipt.py

- [ ] Write failing tests proving a compatibility public report and its provider-free observation cannot create a bounded receipt.
- [ ] Define frozen, redacted P2 bounded observation requiring exact P2 worker boundary receipt, broker receipt, response/program digest equality, fixed corpus/oracle/workload identities, IPython-only arrays, and cleanup.
- [ ] Require verify_programmatic_long_context_bounded_receipt to emit only through issue_prime_bounded_evidence.
- [ ] Run focused receipt tests, Ruff, Pyright, and diff check.
- [ ] Commit: feat(prime): bind bounded long-context evidence.

### Task 2: Close the P2 workload and completion schema

**Files:**
- Create: src/asterion/applications/prime_agent/operator/programmatic_long_context_workload.py
- Create: tests/test_prime_programmatic_long_context_workload.py

- [ ] Write failing tests for exact workload manifest digest, P1 cross-use rejection, corpus/oracle/result substitution, and redaction.
- [ ] Define code-owned immutable workload/result constants and canonical byte helpers; no caller input selects them.
- [ ] Run focused tests, Ruff, Pyright, and diff check.
- [ ] Commit: feat(prime): define fixed long-context workload.

### Task 3: Implement P2 private launcher state machine

**Files:**
- Create: src/asterion/applications/prime_agent/operator/programmatic_long_context_release.py
- Create: src/asterion/applications/prime_agent/operator/programmatic_long_context_image/launcher.mjs
- Create: src/asterion/applications/prime_agent/operator/programmatic_long_context_image/Dockerfile
- Create: tests/test_prime_programmatic_long_context_launcher_protocol.py

- [ ] Write failing parser/state tests for self-check, exact release identity, sequence ordering, caps, deadline, model-response/program digest binding, one terminal, and safe completion fields.
- [ ] Implement private canonical frame state machine with no public execute(code), source, prompt, or path input.
- [ ] Add fixed image fixture/corpus/oracle locks and immutable base input; static tests reject generic subprocess/configuration surfaces.
- [ ] Run protocol tests, syntax/type checks, and diff check.
- [ ] Commit: feat(prime): add sealed long-context launcher.

### Task 4: Add P2 Docker facade and host broker relay

**Files:**
- Create: src/asterion/applications/prime_agent/operator/programmatic_long_context_worker.py
- Create: src/asterion/applications/prime_agent/operator/programmatic_long_context_docker_cli.py
- Create: tests/test_prime_programmatic_long_context_worker.py
- Create: tests/test_prime_programmatic_long_context_docker_cli.py

- [ ] Write failing fake-engine and fake-broker tests for exact role/image/workload admission, empty host environment, entrypoint/seccomp, cancellation, revocation/quiescence, cleanup, and P1 cross-role rejection.
- [ ] Implement two sealed facades; do not generalize the P1 Docker facade.
- [ ] Derive worker execution receipt only from canonical P2 completion bytes.
- [ ] Run focused worker/CLI/broker tests, Ruff, Pyright, and diff check.
- [ ] Commit: feat(prime): run sealed long-context worker.

### Task 5: Orchestrate P2 acceptance and record bounded boundary

**Files:**
- Create: src/asterion/applications/prime_agent/programmatic_long_context_acceptance.py
- Create: tests/test_prime_programmatic_long_context_acceptance.py
- Modify: docs/status/RESUME-NEXT-SESSION.md
- Modify: docs/status/JOURNAL.md

- [ ] Write a fake full-chain test: attestation → broker admission → release → result → broker revoke → destruction → boundary gate → bounded reducer.
- [ ] Reject every missing/mismatched identity and prove compatibility reports remain non-promotable.
- [ ] Run all P2 focused modules plus P1 cross-role regressions, Ruff, Pyright, and diff check.
- [ ] Record provider-free verification only; do not claim Docker/model/network execution.
- [ ] Commit: docs(prime): record P2 worker verification.

## Plan Self-Review

The five tasks cover denial, fixed identity, private execution protocol, concrete sealed transport, and exact acceptance reduction. No task permits generic execution or reuses P1 as a configurable base.
