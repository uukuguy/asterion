# Prime Bounded Verified-loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`; execute each task with its named tests.

**Goal:** Replace the placeholder bounded verifier with one finite, private-configured real Prime run that proves the Phase 1 long-running closure without publishing model, prompt, path, credential, or raw output.

**Architecture:** The operator environment supplies the model configuration only to the owned Prime daemon; the sidecar receives no credential.  A new bounded probe composes the existing control-host and native-RLM machinery, drives one root goal through admitted application/child/checkpoint/cancellation paths, and writes a private receipt.  `verify_prime_loop.py` reduces that receipt to a closed public-safe JSON report.

**Tech Stack:** Python 3.14, Asterion control host, TypeScript Prime gateway, pinned Prime 0.7.1 daemon, `unittest`.

## Global Constraints

- Source under `3th-party/prime-agent` stays unmodified; derived RLM runtime only uses the locked setup mechanism.
- Bounded execution is explicit, finite, owns and reaps only its daemon/sidecar/worker processes, and never runs from `make check` or promotion.
- `.env`, credentials, private prompt text, raw model/provider payloads, workspace paths and stderr never enter manifests, public reports, Pathlight, exceptions, or ledger text.
- `Verified-loop` is PASS only when the existing provider-free gate and this real bounded receipt pass on the same candidate.

---

### Task 1: Define the private bounded-run configuration boundary

**Files:**
- Modify: `tools/verify_prime_loop.py`
- Test: `tests/test_verify_prime_loop.py`

**Interfaces:**
- Produces `resolve_bounded_prime_environment(environ) -> Mapping[str, str]` containing only the selected provider/model and its credential for the owned daemon.
- Rejects absent, malformed, or unsupported private configuration before any Prime process starts with `PrimeExternalLimit` and no secret rendering.

- [ ] **Step 1: Add failing tests** for an `.env`-backed selected model, missing credential, and reports that omit each sentinel model/credential/path.
- [ ] **Step 2: Run** `uv run python -m unittest -v tests.test_verify_prime_loop` and confirm the new cases fail at the absent resolver.
- [ ] **Step 3: Implement** a fixed private resolver that reads only the documented `ASTERION_PRIME_*` variables, maps provider to its credential variable, and returns a minimal daemon environment.
- [ ] **Step 4: Run** the same test command and confirm all pass.

### Task 2: Implement one bounded Phase 1 real closure probe

**Files:**
- Create: `tools/prime_bounded_loop_experiment.py`
- Modify: `tools/verify_prime_loop.py`
- Test: `tests/test_prime_bounded_loop_experiment.py`

**Interfaces:**
- Produces `prepare_bounded_loop_experiment(...)`, `run_bounded_loop_experiment(...)`, and `write_bounded_loop_receipt(...)`.
- Receipt has only terminal state, booleans for root/application/child/detach-attach/checkpoint/cancel/budget/redaction assertions, bounded usage, and digested causal identities.

- [ ] **Step 1: Add failing unit tests** that require exactly one root, one application, one child, one checkpoint/recovery cycle, cancellation and budget probes; require safe failure on incomplete causal evidence.
- [ ] **Step 2: Run** `uv run python -m unittest -v tests.test_prime_bounded_loop_experiment` and confirm failure because the module is absent.
- [ ] **Step 3: Implement** the probe by reusing `prime_native_rlm_experiment` process ownership, `ControlHost`, `PrimeSystemActionService`, and the existing private storage; run application and child actions through the host, restart from a persisted checkpoint, then issue bounded cancel/budget probes.
- [ ] **Step 4: Implement** receipt reduction that rejects missing/duplicate/uncertain causal actions and scans all public projections for sentinels.
- [ ] **Step 5: Run** the new unit suite and `uv run python -m unittest -v tests.test_prime_verified_loop tests.test_control_recovery tests.test_control_children`.

### Task 3: Expose and verify the formal bounded command

**Files:**
- Modify: `tools/verify_prime_loop.py`
- Modify: `tests/test_verify_prime_loop.py`
- Modify: `docs/guides/prime-control-operator-guide.md`

**Interfaces:**
- `--level bounded` performs preflight, validates authority, loads private runtime configuration, executes the probe once, and returns `PASS` only with a complete receipt.
- Any missing runtime prerequisite is `External-limited`; it does not become PASS and starts no model work where validation failed.

- [ ] **Step 1: Add failing CLI tests** for complete receipt → PASS, incomplete receipt → External-limited, and the public report redaction matrix.
- [ ] **Step 2: Run** `uv run python -m unittest -v tests.test_verify_prime_loop` and confirm the placeholder path fails the PASS expectation.
- [ ] **Step 3: Replace** `_bounded_external_limit` with the exact runner integration, preserving provider-free/preflight behavior and the separate native-RLM experiment.
- [ ] **Step 4: Update** the operator guide with private variables, one owned process tree, finite authority, and exact receipt semantics.
- [ ] **Step 5: Run** `uv run python -m unittest -v tests.test_verify_prime_loop tests.test_prime_bounded_loop_experiment`.

### Task 4: Execute the finite real gate and record evidence honestly

**Files:**
- Modify: `docs/status/PRIME-PARITY-LEDGER.md`
- Modify: `docs/status/JOURNAL.md`
- Modify: `docs/status/climb/hypotheses.yaml`
- Regenerate: `docs/status/climb/research-tree.md`, `docs/status/climb/session-state.json`, `docs/status/climb/runs.csv`

- [ ] **Step 1: Run provider-free regression:** `make check`.
- [ ] **Step 2: Run the explicit bounded command** with the configured `.env` model, source root, and finite authority; preserve its private receipt outside public files.
- [ ] **Step 3: Promote only the precise evidence level** in the ledger, or preserve `External-limited` with its safe failure class.
- [ ] **Step 4: Run** `make lint`, `make docs-check`, and `make promotion-check`; journal the named commands and outcomes.

## Self-review

All Phase 1 bounded requirements map to Task 2 or Task 4; no task grants generic execution authority, emits private content, or redefines system/native parity as complete.  The plan has no placeholder behavior: incomplete receipts remain non-PASS.
