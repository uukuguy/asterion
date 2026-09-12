# Prime P1 Authenticated Ready Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emit the one authenticated P1 authority `ready` frame only after complete local resource admission, while keeping execution unavailable.

**Architecture:** `_run_ready_execute_exchange()` first consumes/admits operator config and all six retained production resources. It derives the complete opaque resource-set digest, then—and only then—consumes the private 32-byte session key and retained authenticated socket, creates `AuthoritySession`, serializes its ready packet, sends it once, closes all ownership, and exits through the existing public-safe unavailable terminal. It never receives a supervisor packet, accepts execute/cancel, probes Docker, writes evidence, launches a process, or builds a receipt.

## Constraints

- Resource admission failure consumes neither session-key FD nor socket and sends no frame.
- Success consumes each config/key/socket exactly once, sends at most one ≤8192-byte authenticated ready frame, closes resources/descriptors exactly once, and ends unavailable.
- Ready payload must be produced only by `AuthoritySession.ready_packet()` using `prime_p1_request_contract_sha256()` and `AdmittedProductionAuthorityResources._resource_set_sha256()`; no literals/fallbacks/caller-supplied digests.
- All arbitrary errors, malformed identity/session/key/socket failures, send failures, and close failures normalize to `PrimeP1AuthorityBootstrapError` without context/path/key/resource leakage.
- Tests are local fake descriptors/sockets only. No Docker connect/probe, network, subprocess, model, evidence write, receipt, execute, or production PASS.

### Task 1: Ready-only authority transport

**Files:**

- Modify: `src/asterion/applications/prime_agent/operator/authority_process.py`
- Modify: `src/asterion/applications/prime_agent/operator/resources/authority-artifact-lock.json`
- Modify: `tests/test_prime_p1_authority_process.py`

- [ ] Add RED tests that prove no key/socket/send on resource admission failure; success sends one valid ready frame with canonical contract digest and complete resource-set digest, does not receive a supervisor packet, then raises unavailable and closes every owner once; malformed/send/cleanup failures are redacted.
- [ ] Implement the ready-only flow via exact `AuthoritySession`/contract helpers after aggregate admission. Ensure resource-set digest is computed before consuming key/socket; consume socket without `_receive_authority_packet` and close it in final cleanup.
- [ ] Refresh authority artifact lock for `authority_process.py`, run authority process/protocol/resource focused tests plus Ruff/diff, commit `feat: emit authenticated Prime P1 ready frame`.
