# Prime P1 Authenticated Execute Admission Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admit exactly one authenticated fixed P1 `execute` IPC frame after ready, while still refusing all execution.

**Architecture:** The ready-only authority retains its authenticated socket just long enough to receive one bounded packet through `_receive_authority_packet_from_connection`. It passes the packet only to the same `AuthoritySession.accept_supervisor_packet()` used to create ready. Valid `execute` must have sequence zero, exact contract digest, valid run/application digests, and valid HMAC; any malformed/duplicate/cancel/terminal packet fails closed. Even a valid execute immediately closes resources/descriptors and exits unavailable: no Docker/socket daemon action, process, model, evidence, receipt, or terminal frame exists in this slice.

## Constraints

- Complete resource set precedes key/socket. Ready precedes receive. Receive occurs once from the same retained authenticated socket, which closes in every outcome.
- Use protocol-owned parser/state machine only; no ad-hoc HMAC/frame parsing or caller-provided contract/resource digest.
- Valid execute must still observe no terminal send and no external action; public outcome is unavailable.
- Failure is redacted and consumes/closes all owned descriptors/resources exactly once.

### Task 1: One fixed execute admission

**Files:**

- Modify: `src/asterion/applications/prime_agent/operator/authority_process.py`
- Modify: `src/asterion/applications/prime_agent/operator/resources/authority-artifact-lock.json`
- Modify: `tests/test_prime_p1_authority_process.py`

- [ ] Write RED tests for valid ready then exact execute admission with no terminal/external effect, and malformed/second/cancel/extra packet rejection with cleanup/redaction.
- [ ] Retain connection across ready, receive exactly once, route only to `AuthoritySession.accept_supervisor_packet()`, then close and `_unavailable()`; refresh authority artifact hash.
- [ ] Run focused authority process/protocol/resource tests plus Ruff/diff, commit `feat: admit authenticated Prime P1 execute frame`.
