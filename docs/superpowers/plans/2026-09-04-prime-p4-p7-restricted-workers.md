# Prime P4–P7 Restricted Workers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add sealed executable restricted-worker lifecycles for P4–P7, feeding only their existing authorization-gated evidence reducers.

**Architecture:** One shared lifecycle envelope owns injected-engine mechanics; four literal adapters own role, workload, entrypoint, seccomp, limits, and canonical completion parsing. No caller chooses executable values.

**Tech Stack:** Python 3.12, unittest, asyncio, existing `RestrictedWorker*` contracts.

## Global Constraints

- Never read `.env`, credentials, prompts, host paths, or raw completion bodies.
- Launch only through an injected engine with `env=()`; provider-free tests perform no Docker/model/network/game operation.
- Canonical bounded completions must prove IPython-only facts.
- P7 permits only its fixed one-game subset; it has no full-suite default entrypoint.

---

### Task 1: Shared sealed lifecycle envelope

**Files:**
- Create: `src/asterion/applications/prime_agent/operator/restricted_scenario_worker.py`
- Create: `tests/test_prime_restricted_scenario_worker.py`

**Interfaces:** `RestrictedScenarioAdapter` is frozen and contains `scenario_id`, `role_id`, `workload_digest`, `entrypoint`, `seccomp`, `max_runtime_seconds`, `max_output_bytes`, `parse_completion`. `RestrictedScenarioWorker(image_digest, engine, adapter)` exposes `open`, `attest`, `execution_receipt`, and `cleanup_receipt` compatible with `RestrictedWorkerService`.

- [ ] **Step 1: Write the failing test.**

```python
async def test_worker_uses_only_adapter_literals():
    worker, engine, request = fixture(P4_ADAPTER)
    async with worker.open(request) as lease:
        execution = await worker.execution_receipt(lease)
    cleanup = await worker.cleanup_receipt(lease)
    self.assertEqual(engine.launches, [(P4_ADAPTER.role_id, (), P4_ADAPTER.entrypoint, P4_ADAPTER.seccomp)])
    self.assertTrue(cleanup.destroyed)
```

- [ ] **Step 2: Run RED.** Run `uv run python -m unittest -v tests.test_prime_restricted_scenario_worker`; expect missing module failure.

- [ ] **Step 3: Write minimal implementation.**

```python
def request_for(self, request: RestrictedWorkerRequest) -> RestrictedWorkerRequest:
    if (type(request) is not RestrictedWorkerRequest or request.role_id != self._adapter.role_id
            or request.image_digest != self._image or request.workload_digest != self._adapter.workload_digest
            or request.max_runtime_seconds > self._adapter.max_runtime_seconds
            or request.max_output_bytes > self._adapter.max_output_bytes):
        raise RestrictedWorkerError("restricted worker value is invalid")
    return request
```

Use P3’s cancellation-safe removal approach. Require lease and inspection equality to request plus adapter literals; bound bytes before parser invocation; hash only validated bytes; tombstone only after removal.

- [ ] **Step 4: Verify GREEN.** Run `uv run python -m unittest -v tests.test_prime_restricted_scenario_worker tests.test_prime_worker_gate && uv run ruff check src/asterion/applications/prime_agent/operator/restricted_scenario_worker.py tests/test_prime_restricted_scenario_worker.py && uv run pyright src/asterion/applications/prime_agent/operator/restricted_scenario_worker.py tests/test_prime_restricted_scenario_worker.py && git diff --check`; expect PASS including forged lease/inspection, oversized output, cancellation, failed removal, duplicate cleanup, and sentinel redaction.

- [ ] **Step 5: Commit.** Commit exact files with message `feat(prime): add sealed scenario worker lifecycle`.

### Task 2: P4 continuity adapter and result binding

**Files:**
- Create: `src/asterion/applications/prime_agent/operator/diagnostic_session_recovery_worker.py`
- Create: `tests/test_prime_diagnostic_session_recovery_worker.py`

**Interfaces:** `P4_DIAGNOSTIC_SESSION_RECOVERY_ADAPTER` and `DiagnosticSessionRecoveryWorker(image_digest, engine)`. Literal endpoint `/usr/local/bin/prime-diagnostic-session-recovery.mjs`; literal seccomp `prime-diagnostic-session-recovery`; P4 role/workload; 300 seconds and 4096 bytes.

- [ ] **Step 1: Write the failing test.**

```python
async def test_p4_worker_accepts_only_canonical_continuity_completion():
    worker, _, request = fixture(P4_DIAGNOSTIC_SESSION_RECOVERY_ADAPTER)
    async with worker.open(request) as lease:
        receipt = await worker.execution_receipt(lease)
    self.assertEqual(receipt.workload_digest, P4_DIAGNOSTIC_RECOVERY_WORKLOAD_DIGEST)
```

- [ ] **Step 2: Run RED.** Run `uv run python -m unittest -v tests.test_prime_diagnostic_session_recovery_worker`; expect missing adapter failure.

- [ ] **Step 3: Write minimal implementation.**

```python
P4_DIAGNOSTIC_SESSION_RECOVERY_ADAPTER = RestrictedScenarioAdapter(
    P4_DIAGNOSTIC_RECOVERY_SCENARIO_ID, P4_DIAGNOSTIC_RECOVERY_ROLE_ID,
    P4_DIAGNOSTIC_RECOVERY_WORKLOAD_DIGEST,
    "/usr/local/bin/prime-diagnostic-session-recovery.mjs",
    "prime-diagnostic-session-recovery", 300, 4096,
    parse_diagnostic_session_recovery_completion,
)
```

The existing live reducer already requires `worker_boundary.result_digest == trace.diagnostic_result_sha256`; do not modify it.

- [ ] **Step 4: Verify GREEN.** Run `uv run python -m unittest -v tests.test_prime_diagnostic_session_recovery_worker tests.test_prime_diagnostic_session_recovery_completion tests.test_prime_diagnostic_session_recovery_acceptance tests.test_prime_diagnostic_session_recovery_live_validation tests.test_prime_worker_gate && git diff --check`; expect PASS.

- [ ] **Step 5: Commit.** Commit exact P4 worker and test files with `feat(prime): add P4 restricted continuity worker`.

### Task 3: P5 and P6 adapters and result binding

**Files:**
- Create: `src/asterion/applications/prime_agent/operator/bounded_autonomy_worker.py`
- Create: `src/asterion/applications/prime_agent/operator/continual_improvement_worker.py`
- Create: `tests/test_prime_bounded_autonomy_worker.py`
- Create: `tests/test_prime_continual_improvement_worker.py`

**Interfaces:** P5 adapter literals are exact P5 role/workload, `/usr/local/bin/prime-bounded-autonomy.mjs`, `prime-bounded-autonomy`, 300 seconds, 4096 bytes. P6 literals are exact P6 role/workload, `/usr/local/bin/prime-continual-improvement.mjs`, `prime-continual-improvement`, 600 seconds, 4096 bytes.

- [ ] **Step 1: Write failing tests.**

```python
async def test_p5_worker_rejects_a_p6_completion():
    worker, engine, request = fixture(P5_BOUNDED_AUTONOMY_ADAPTER)
    engine.completion = canonical_p6_completion()
    async with worker.open(request) as lease:
        with self.assertRaises(RestrictedWorkerError):
            await worker.execution_receipt(lease)
```

- [ ] **Step 2: Run RED.** Run `uv run python -m unittest -v tests.test_prime_bounded_autonomy_worker tests.test_prime_continual_improvement_worker`; expect missing worker modules.

- [ ] **Step 3: Write minimal implementation.** Create literal adapters using `validate_bounded_autonomy_trace` and `validate_continual_improvement_trace`; do not accept caller supplied adapter fields. The existing live reducers already bind worker result digests to trace terminal digests and remain unchanged.

- [ ] **Step 4: Verify GREEN.** Run `uv run python -m unittest -v tests.test_prime_bounded_autonomy_worker tests.test_prime_bounded_autonomy_receipt tests.test_prime_bounded_autonomy_acceptance tests.test_prime_bounded_autonomy_live_validation tests.test_prime_continual_improvement_worker tests.test_prime_continual_improvement_receipt tests.test_prime_continual_improvement_acceptance tests.test_prime_continual_improvement_live_validation tests.test_prime_worker_gate && git diff --check`; expect PASS including failed gate, unchanged workspace, invalid rollback, and foreign completion rejection.

- [ ] **Step 5: Commit.** Commit exact P5/P6 worker and test files with `feat(prime): add P5 and P6 restricted workers`.

### Task 4: P7 ARC-AGI-3 subset adapter and factory reachability

**Files:**
- Create: `src/asterion/applications/prime_agent/operator/arc_agi_3_worker.py`
- Create: `tests/test_prime_arc_agi_3_worker.py`
- Modify: `src/asterion/applications/prime_agent/provider.py`
- Modify: `tests/test_prime_application_provider.py`

**Interfaces:** `P7_ARC_AGI_3_ADAPTER` and `ArcAgi3Worker(image_digest, engine)` use exact P7 role/workload, `/usr/local/bin/prime-arc-agi-3.mjs`, `prime-arc-agi-3`, 300 seconds, 4096 bytes. Preflight exposes a factory closure only; it never launches.

- [ ] **Step 1: Write the failing test.**

```python
async def test_p7_worker_rejects_multiple_games():
    worker, engine, request = fixture(P7_ARC_AGI_3_ADAPTER)
    engine.completion = canonical_p7_completion(game_count=2)
    async with worker.open(request) as lease:
        with self.assertRaises(RestrictedWorkerError):
            await worker.execution_receipt(lease)
```

- [ ] **Step 2: Run RED.** Run `uv run python -m unittest -v tests.test_prime_arc_agi_3_worker tests.test_prime_application_provider tests.test_prime_arc_agi_3_live_validation`; expect missing worker/factory failures.

- [ ] **Step 3: Write minimal implementation.** Use the common envelope and `validate_arc_agi_3_trace`, and expose only a preflighted injected-engine factory. The existing reducer already requires worker result digest equal `trace.score_sha256`. Do not add model config, CLI command, benchmark selection, or full-suite adapter.

- [ ] **Step 4: Verify GREEN.** Run `uv run python -m unittest -v tests.test_prime_arc_agi_3_worker tests.test_prime_arc_agi_3_workload tests.test_prime_arc_agi_3_receipt tests.test_prime_arc_agi_3_broker tests.test_prime_arc_agi_3_acceptance tests.test_prime_arc_agi_3_live_validation tests.test_prime_application_provider tests.test_prime_worker_gate && git diff --check`; expect PASS and no full-suite evidence path.

- [ ] **Step 5: Commit.** Commit exact P7 worker, provider, and test files with `feat(prime): add P7 restricted ARC worker`.

### Task 5: Cross-scenario closure and state

**Files:**
- Create: `tests/test_prime_restricted_scenario_worker_integration.py`
- Modify: `docs/status/CURRENT-STATE.md`
- Modify: `docs/status/RESUME-NEXT-SESSION.md`

**Interfaces:** All P4–P7 adapters must reject every foreign role/workload and provider-free fakes must not issue bounded-sandboxed evidence.

- [ ] **Step 1: Write the failing test.**

```python
async def test_each_adapter_rejects_every_foreign_role_and_workload():
    for adapter in P4_P7_ADAPTERS:
        worker, _, request = fixture(adapter)
        for foreign in P4_P7_ADAPTERS:
            if foreign is not adapter:
                with self.assertRaises(RestrictedWorkerError):
                    worker.open(replace(request, role_id=foreign.role_id, workload_digest=foreign.workload_digest))
```

- [ ] **Step 2: Run RED.** Run `uv run python -m unittest -v tests.test_prime_restricted_scenario_worker_integration`; expect failure until every adapter exists.

- [ ] **Step 3: Write minimal integration fixture and status update.** Fakes return canonical per-scenario bytes and record zero external operations. State that injected-worker integration is implemented while real sandbox evidence remains External-limited.

- [ ] **Step 4: Verify GREEN.** Run `uv run python -m unittest -v tests.test_prime_restricted_scenario_worker tests.test_prime_restricted_scenario_worker_integration tests.test_prime_diagnostic_session_recovery_worker tests.test_prime_bounded_autonomy_worker tests.test_prime_continual_improvement_worker tests.test_prime_arc_agi_3_worker tests.test_prime_worker_gate && make check && git diff --check`; expect PASS. Then run `make promotion-check` after clean verification and record only its actual output.

- [ ] **Step 5: Commit.** Commit exact closure test and state files with `test(prime): close P4-P7 worker integration`.

## Plan self-review

- Tasks 1–4 cover shared mechanics, four sealed adapters, identity/result binding, factory reachability, cancellation, cleanup, and P7 subset limitation.
- Task 5 covers cross-scenario isolation and preserves the real-evidence boundary.
- Every later interface is defined by Task 1 or existing P4–P7 contracts; no generic execution surface is introduced.
