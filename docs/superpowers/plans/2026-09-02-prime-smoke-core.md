# Prime Smoke Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a bounded real Prime Core smoke whose PASS receipt proves the
RLM, collaboration, control, reconnect, application-effect, privacy, and
observation-health invariants defined in the Smoke Core research.

**Architecture:** Extend the existing Native RLM probe instead of adding a
second control runner.  Prime Gateway publishes a private, body-free durable
observation-health snapshot; Python consumes it as evidence.  A new Core
runner composes the verified gateway primitives and fails closed on any missing
assertion.

**Tech Stack:** Python 3.12/unittest, TypeScript/Node test runner, existing
Prime Gateway sidecar, Make.

## Global Constraints

- `.env` is the sole operator-owned LLM configuration source.
- Provider-free commands perform zero provider/model operations.
- Core uses a mode-0700 temporary fixture and never changes the user worktree.
- Private prompts, answers, tool bodies, credentials, provider payloads, and
  paths must not appear in stdout, receipt, or public evidence.
- Unknown, degraded, or External-limited conditions fail closed.
- Do not change `asterion.agent-control/v1`.

---

### Task 1: Closed Core receipt and verifier

**Files:**
- Create: `tools/prime_core_smoke.py`
- Create: `tests/test_prime_core_smoke.py`

**Interfaces:**
- Produces `PrimeCoreSmokeResult`, `verify_prime_core_smoke_result`, and a
  body-free `asterion.prime-core-smoke-receipt/v1` mapping.
- Consumed by the Core runner in Task 4.

- [ ] Write failing Python tests: complete fixed fields yield PASS; each false
  required field, unknown field, non-healthy observation, non-unique terminal,
  budget excess, and secret sentinel in receipt yields non-PASS/rejection.
- [ ] Run `uv run python -m unittest -v tests.test_prime_core_smoke`; confirm
  import failure.
- [ ] Implement frozen result validation with exact fields and `PASS` only when
  every required boolean and exact count passes.
- [ ] Re-run the test command; expect all tests PASS.
- [ ] Commit receipt/verifier only.

### Task 2: Durable observation-health contract

**Files:**
- Modify: `packages/typescript/prime-gateway/src/client-observation.ts`
- Modify: `packages/typescript/prime-gateway/src/durable-store.ts`
- Modify: `packages/typescript/prime-gateway/src/gateway.ts`
- Modify: `packages/typescript/prime-gateway/src/main.ts`
- Modify: `src/asterion/control/providers/prime/process.py`
- Modify: `src/asterion/control/providers/prime/client.py`
- Test: `packages/typescript/prime-gateway/test/core-smoke.test.mjs`
- Test: `tests/test_prime_core_smoke.py`

**Interfaces:**
- Produces `healthy | degraded | resync-required`, a fixed reason code, native
  progress, first gap, and a resync flag in private `client_observations.batch`.
- Core accepts only `healthy`, zero-gap evidence.

- [ ] Write failing TypeScript tests for sparse cursor acceptance, replay
  duplicates, foreign-session isolation, cursor regression, invalid supported
  payload, durable failure, restart persistence, and successful full resync.
  Verify canonical events continue but health never silently returns healthy.
- [ ] Run the single Node test file and observe the health-contract failures.
- [ ] Add closed validators and journal records; accept only strictly
  increasing same-session cursor progress (not `+1`), retain contiguous public
  source sequences, map actual replay/generation/durable failures to health
  without retaining event bodies, expose exact health in the sidecar response,
  and parse it strictly in Python.
- [ ] Run Node and Python focused tests; expect PASS.
- [ ] Commit observation-health contract only.

### Task 3: Core RLM assertions and active reconnect

**Files:**
- Modify: `tools/prime_native_rlm_experiment.py`
- Modify: `tests/test_prime_rlm_experiment.py`

**Interfaces:**
- Produces Core facts for two child identities, completed/deleted counts,
  direct-message causality, generated program/model/recursion proof,
  active detach/attach, contiguous replay, and continuation after attach.

- [ ] Add failing fake-host tests proving PASS fails when model/program/depth,
  either child, message causal chain, active reconnect, or replay-continuation
  is absent.
- [ ] Run `uv run python -m unittest -v tests.test_prime_rlm_experiment` and
  observe expected failures.
- [ ] Refactor the probe to collect only body-free identities/counts, dispatch
  detach before both children are terminal, reattach once, then prove suffix
  progress; preserve current README smoke compatibility.
- [ ] Run focused tests; expect PASS.
- [ ] Commit Core RLM assertion changes only.

### Task 4: Bounded command, closed application oracle, and acceptance

**Files:**
- Create: `tools/run_prime_core_smoke.py`
- Modify: `Makefile`
- Modify: `tests/test_prime_core_smoke.py`
- Modify: `docs/guides/prime-control-operator-guide.md`

**Interfaces:**
- `make prime-smoke-core` writes safe heartbeats and returns a closed Core
  receipt; `make prime-core-acceptance` first runs provider-free Core tests.

- [ ] Add failing command tests for provider-free command identity, fixed output
  schema, secret redaction, and every non-PASS terminal.
- [ ] Run the focused Python tests and observe missing command failures.
- [ ] Implement a mode-0700 temporary fixture, a fixed application oracle,
  heartbeat/public terminal output, owned-process cleanup, and Make targets.
- [ ] Run provider-free tests, gateway tests/build, docs check, and then one
  authorized `make prime-smoke-core`; accept only an exact PASS receipt.
- [ ] Commit entrypoints/docs and append journal evidence after the commit.
