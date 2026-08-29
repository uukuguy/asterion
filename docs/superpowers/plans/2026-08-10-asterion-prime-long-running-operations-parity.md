# Asterion Prime Long-Running Operations Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close all ten `operation.long-running` Prime Gateway scenarios with host-owned heartbeat, schedule, residency, recovery, cleanup, and bounded-autonomy evidence.

**Architecture:** Python owns immutable operation policy, virtual time, durable schedule/residency journals, admission, cancellation, and orphan audits. TypeScript translates the pinned Prime daemon's heartbeat and session lifecycle surfaces into a private exact-version adapter; it never schedules, retries effects, or grants residency. Existing detach/attach and goal paths are promoted only through their exact Phase 1 evidence, while autonomous quality remains a separately bounded provider operation.

**Tech Stack:** Python 3.12+/unittest, TypeScript strict Node 22/node:test, Prime Agent 0.7.1 daemon protocol 7/schema 14, canonical JSON journals, accelerated deterministic virtual clock.

## Global Constraints

- Preserve `CLI/host → selected provider → assembly → catalog/composer → exact implementations → runner → runtime/host services`.
- Keep `src/asterion/runtime/`, `packages/`, `assembly/`, `runner/`, and `services/` domain-neutral; no generic module may import Prime or DCI implementations.
- Do not change the closed public protocol identities unless canonical schema, Python, TypeScript, and valid/invalid fixtures change together.
- Heartbeats and schedules are host-owned declarative records. Prime may request them, but it cannot authorize, persist, retry, or execute them directly.
- Distinguish one user heartbeat from multiple agent-created heartbeats; distinguish one-time schedules from cron schedules; distinguish controller residency from task authority.
- Persist intent before sending an effect. A transport retry may recover the same idempotency identity; it may never retry an uncertain side effect under a new identity.
- All virtual-clock tests cover an accelerated 24-hour interval, restart/update, eviction, repeated attach, cancellation, and shutdown orphan audit.
- Provider-free commands perform zero provider/application operations and zero credential reads. Autonomous quality uses one separately named finite bounded command.
- Public evidence contains only canonical IDs, fixed states, counts, digests, and reason codes. Prompts, credentials, model/provider payloads, raw output, environment values, and private paths remain private.

---

## File Structure

- Create `src/asterion/control/long_running.py`: immutable heartbeat, schedule, residency, and orphan-audit types plus host-owned coordinator.
- Create `src/asterion/control/providers/prime/long_running.py`: Prime-specific private command translation and safe observation reducer.
- Modify `src/asterion/control/providers/prime/client.py`: narrow typed calls for heartbeat catalog/management and resident status.
- Modify `src/asterion/control/providers/prime/parity_testing.py`: exact ten-scenario matrix, provider-free/bounded observations, and evidence adapters.
- Modify `packages/typescript/prime-gateway/src/daemon-wire.ts`: validate only the pinned heartbeat/session command and event shapes.
- Modify `packages/typescript/prime-gateway/src/daemon-client.ts`: expose exact read/mutation calls without policy or retry.
- Modify `packages/typescript/prime-gateway/src/prime-session.ts`: bind request identities to daemon results and fence uncertain effects.
- Modify `packages/typescript/prime-gateway/src/durable-store.ts`: persist heartbeat/schedule/residency bindings and terminal observations.
- Modify `packages/typescript/prime-gateway/src/main.ts`: add private IPC frames for the Python Prime adapter.
- Create `tests/test_control_long_running.py`: provider-neutral policy, virtual-clock, restart, cancellation, and orphan tests.
- Create `tests/test_prime_long_running_parity.py`: real-Prime provider-free harness, bounded autonomy adapter, ledger, and redaction tests.
- Create `packages/typescript/prime-gateway/test/long-running.test.mjs`: daemon translation, idempotency, crash-window, and private IPC tests.
- Modify `tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json`: exact provider results and evidence records.

---

### Task 1: Lock the ten-scenario contract and promote existing Phase 1 evidence

**Files:**
- Modify: `src/asterion/control/providers/prime/parity_testing.py`
- Create: `tests/test_prime_long_running_parity.py`
- Modify: `tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json`

**Interfaces:**
- Consumes: `ParityScenarioRegistry`, `PROVEN_PHASE1_PARITY_SCENARIO_IDS`, and the exact ledger scenario rows.
- Produces: `PRIME_LONG_RUNNING_SCENARIO_MATRIX`, `PRIME_LONG_RUNNING_PROVIDER_FREE_SCENARIO_IDS`, `PRIME_LONG_RUNNING_BOUNDED_SCENARIO_IDS`, and `register_prime_long_running_scenarios(...)`.

- [ ] **Step 1: Write the failing exact-matrix and no-cross-promotion tests**

```python
def test_long_running_matrix_matches_the_ten_ledger_scenarios(self) -> None:
    self.assertEqual(
        tuple(PRIME_LONG_RUNNING_SCENARIO_MATRIX),
        (
            "prime-parity.operation.autonomous-quality",
            "prime-parity.operation.detach-attach-replay",
            "prime-parity.operation.goals",
            "prime-parity.operation.heartbeat-agent",
            "prime-parity.operation.heartbeat-user",
            "prime-parity.operation.orphan-cleanup",
            "prime-parity.operation.resident-workers",
            "prime-parity.operation.restart-update-recovery",
            "prime-parity.operation.schedule-once-cron",
            "prime-parity.operation.worker-residency-eviction",
        ),
    )

def test_phase1_promotes_only_detach_attach_and_goals(self) -> None:
    report = asyncio.run(run_phase1_long_running_adapter())
    self.assertEqual(
        report.passed_scenario_ids,
        (
            "prime-parity.operation.detach-attach-replay",
            "prime-parity.operation.goals",
        ),
    )
```

- [ ] **Step 2: Run the focused tests and observe failure**

Run: `uv run python -m unittest -v tests.test_prime_long_running_parity`

Expected: FAIL because the closed matrix and adapter do not exist.

- [ ] **Step 3: Implement the immutable matrix and Phase 1 adapter**

```python
PRIME_LONG_RUNNING_BOUNDED_SCENARIO_IDS = (
    "prime-parity.operation.autonomous-quality",
)
PRIME_LONG_RUNNING_PROVIDER_FREE_SCENARIO_IDS = tuple(
    scenario_id
    for scenario_id in PRIME_LONG_RUNNING_SCENARIO_MATRIX
    if scenario_id not in PRIME_LONG_RUNNING_BOUNDED_SCENARIO_IDS
)

def register_prime_long_running_scenarios(
    registry: ParityScenarioRegistry,
    observations: Sequence[PrimeLongRunningObservation],
    *,
    provider_factory: Callable[[], object],
) -> None:
    items = tuple(observations)
    if tuple(item.scenario_id for item in items) != tuple(PRIME_LONG_RUNNING_SCENARIO_MATRIX):
        raise ParityScenarioRegistryError("Prime long-running evidence adapter is invalid")
    runners = tuple(
        _build_prime_long_running_runner(
            _validate_prime_long_running_observation(item),
            provider_factory=provider_factory,
        )
        for item in items
    )
    if any(item.scenario_id in registry.registered_scenario_ids for item in items):
        raise ParityScenarioRegistryError("Prime long-running evidence adapter is invalid")
    for scenario_id, runner in zip(PRIME_LONG_RUNNING_SCENARIO_MATRIX, runners, strict=True):
        registry.register(scenario_id, runner)
```

Define `_validate_prime_long_running_observation(...)` and `_build_prime_long_running_runner(...)` in this task beside the registration function. The validator rebuilds the canonical serialized observation and exact evidence ID; the runner factory closes over only the rebuilt status, evidence ID, and fixed reason code. Do not partially register on a later validation failure.

- [ ] **Step 4: Run the matrix, parity conformance, and ledger tests**

Run: `uv run python -m unittest -v tests.test_prime_long_running_parity tests.test_prime_parity_conformance tests.test_prime_parity_ledger`

Expected: PASS; only detach/attach and goals are promoted at this task boundary.

- [ ] **Step 5: Commit the exact contract**

```bash
git add src/asterion/control/providers/prime/parity_testing.py \
  tests/test_prime_long_running_parity.py \
  tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json
git commit -m "feat: lock prime long-running parity matrix"
```

### Task 2: Add host-owned heartbeat and schedule state

**Files:**
- Create: `src/asterion/control/long_running.py`
- Create: `tests/test_control_long_running.py`

**Interfaces:**
- Consumes: injected `clock_ms: Callable[[], int]`, `FileCanonicalJournal`, cancellation signal, and an effect sender supplied by the selected provider.
- Produces: `HeartbeatSpec`, `ScheduleSpec`, `LongRunningCoordinator.register_heartbeat(...)`, `register_schedule(...)`, `advance()`, `recover()`, and `close()`.

- [ ] **Step 1: Write failing identity, ownership, and virtual-clock tests**

```python
def test_user_and_agent_heartbeats_have_disjoint_exact_owners(self) -> None:
    user = HeartbeatSpec("heartbeat-user", "user", None, 60_000)
    agent = HeartbeatSpec("heartbeat-agent-1", "agent", "child-1", 30_000)
    self.assertNotEqual(user.owner_key, agent.owner_key)

def test_once_and_cron_fire_exactly_across_accelerated_24_hours(self) -> None:
    clock = VirtualClock(0)
    coordinator = coordinator_for(clock)
    coordinator.register_schedule(ScheduleSpec.once("once-1", 3_600_000))
    coordinator.register_schedule(ScheduleSpec.cron("cron-1", "0 * * * *"))
    clock.advance(86_400_000)
    receipts = coordinator.advance()
    self.assertEqual(count(receipts, "once-1"), 1)
    self.assertEqual(count(receipts, "cron-1"), 24)
```

- [ ] **Step 2: Run the provider-neutral tests and observe failure**

Run: `uv run python -m unittest -v tests.test_control_long_running`

Expected: FAIL because the coordinator does not exist.

- [ ] **Step 3: Implement closed immutable specifications and persist-before-effect advance**

```python
@dataclass(frozen=True)
class HeartbeatSpec:
    heartbeat_id: str
    owner_kind: Literal["user", "agent"]
    owner_id: str | None
    interval_ms: int

@dataclass(frozen=True)
class ScheduleSpec:
    schedule_id: str
    kind: Literal["once", "cron"]
    due_at_ms: int | None
    cron: str | None

class LongRunningCoordinator:
    def advance(self) -> tuple[LongRunningReceipt, ...]:
        receipts: list[LongRunningReceipt] = []
        for due in self._due_records(self._clock_ms()):
            intent = self._journal.append_due_intent(due)
            try:
                terminal = self._effect_sender(intent)
            except LongRunningTransportError:
                terminal = LongRunningReceipt(intent.effect_id, "uncertain")
            self._journal.append_terminal(intent, terminal)
            receipts.append(terminal)
        return tuple(receipts)
```

Implement cron parsing only for canonical five-field minute/hour/day/month/weekday expressions required by the fixtures. Reject aliases, seconds, ranges, steps, names, and timezone-dependent forms.

- [ ] **Step 4: Add crash-window, cancellation, and immutable snapshot tests**

```python
def test_restart_after_intent_reuses_the_same_effect_identity(self) -> None:
    first = coordinator.advance(fault="after-intent")
    recovered = reopen_coordinator().advance()
    self.assertEqual(first[0].effect_id, recovered[0].effect_id)
    self.assertEqual(recovered[0].status, "uncertain")

def test_close_cancels_future_ticks_without_deleting_history(self) -> None:
    coordinator.close()
    clock.advance(86_400_000)
    self.assertEqual(coordinator.advance(), ())
    self.assertGreater(len(coordinator.snapshot().history), 0)
```

- [ ] **Step 5: Run and commit the host coordinator**

Run: `uv run python -m unittest -v tests.test_control_long_running`

Expected: PASS.

```bash
git add src/asterion/control/long_running.py tests/test_control_long_running.py
git commit -m "feat: add host-owned heartbeat and schedule coordinator"
```

### Task 3: Translate pinned Prime heartbeat commands without granting authority

**Files:**
- Modify: `packages/typescript/prime-gateway/src/daemon-wire.ts`
- Modify: `packages/typescript/prime-gateway/src/daemon-client.ts`
- Modify: `packages/typescript/prime-gateway/src/prime-session.ts`
- Modify: `packages/typescript/prime-gateway/src/durable-store.ts`
- Modify: `packages/typescript/prime-gateway/src/main.ts`
- Create: `packages/typescript/prime-gateway/test/long-running.test.mjs`

**Interfaces:**
- Consumes: pinned `heartbeat_catalog`/`heartbeat_management` capabilities and host-issued immutable operation commands.
- Produces: private IPC requests `heartbeat.catalog.read`, `heartbeat.create`, `heartbeat.delete`, and body-free `LongRunningReceipt` values.

- [ ] **Step 1: Write rejecting-shape and persist-before-send tests**

```javascript
test("rejects heartbeat mutation fields outside the pinned daemon shape", async () => {
  await assert.rejects(() => session.createHeartbeat({ ...valid, command: "private" }));
  assert.equal(transport.requests.length, 0);
});

test("recovery fences a heartbeat effect lost after daemon success", async () => {
  const first = session.createHeartbeat(valid, { fault: "after-daemon-result" });
  await assert.rejects(first, /uncertain/);
  const recovered = await reopen().createHeartbeat(valid);
  assert.equal(recovered.status, "uncertain");
  assert.equal(transport.mutationCount, 1);
});
```

- [ ] **Step 2: Run the test and observe failure**

Run: `npm --prefix packages/typescript/prime-gateway test -- test/long-running.test.mjs`

Expected: FAIL because the private calls and durable bindings do not exist.

- [ ] **Step 3: Implement exact wire validation and durable request/result binding**

```ts
export type PrimeHeartbeatCommand =
  | Readonly<{ readonly type: "heartbeats_list" }>
  | Readonly<{ readonly type: "heartbeat_get"; readonly activeSessionId: string }>
  | Readonly<{ readonly type: "heartbeat_set"; readonly activeSessionId: string; readonly schedule: string; readonly prompt: string; readonly deliveryMode?: "steer" | "followUp" }>
  | Readonly<{ readonly type: "heartbeat_update"; readonly activeSessionId: string; readonly action: "pause" | "resume" | "cancel" }>
  | Readonly<{ readonly type: "heartbeat_manage"; readonly activeSessionId: string; readonly jobId: string; readonly action: "pause" | "resume" | "cancel" }>;

async createHeartbeat(command: PrimeHeartbeatCommand): Promise<LongRunningReceipt> {
  const binding = await this.store.bindLongRunningCommand(command);
  const result = await this.transport.request(binding.command, binding.commandId);
  return this.store.commitLongRunningResult(binding, result);
}
```

The exact command names are the pinned daemon names above, not the RPC wrapper names `list_heartbeats`, `get_heartbeat`, `set_heartbeat`, `update_heartbeat`, or `manage_heartbeat`. Reject those RPC aliases at the daemon boundary.

- [ ] **Step 4: Run Gateway tests and TypeScript checking**

Run: `npm --prefix packages/typescript/prime-gateway test -- test/long-running.test.mjs`

Run: `npm --prefix packages/typescript/prime-gateway run check`

Expected: PASS with no raw heartbeat body, environment value, or path in public IPC.

- [ ] **Step 5: Commit the Prime translation**

```bash
git add packages/typescript/prime-gateway/src/daemon-wire.ts \
  packages/typescript/prime-gateway/src/daemon-client.ts \
  packages/typescript/prime-gateway/src/prime-session.ts \
  packages/typescript/prime-gateway/src/durable-store.ts \
  packages/typescript/prime-gateway/src/main.ts \
  packages/typescript/prime-gateway/test/long-running.test.mjs
git commit -m "feat: translate prime heartbeat lifecycle"
```

### Task 4: Bind schedules and heartbeats through the selected Prime provider

**Files:**
- Create: `src/asterion/control/providers/prime/long_running.py`
- Modify: `src/asterion/control/providers/prime/client.py`
- Modify: `tests/test_prime_long_running_parity.py`

**Interfaces:**
- Consumes: `LongRunningCoordinator` effect sender protocol and private Prime IPC.
- Produces: `PrimeLongRunningService.apply(command) -> LongRunningReceipt` and `recover() -> LongRunningSnapshot`.

- [ ] **Step 1: Write failing exact-identity, restart, and redaction tests**

```python
def test_prime_service_preserves_host_effect_identity_across_transport_retry(self) -> None:
    first = service.apply(command, disconnect_after_send=True)
    second = reopen_service().apply(command)
    self.assertEqual(first.effect_id, second.effect_id)
    self.assertEqual(second.status, "uncertain")
    self.assertEqual(process.mutation_count, 1)

def test_public_snapshot_redacts_heartbeat_and_schedule_bodies(self) -> None:
    rendered = repr(service.snapshot())
    self.assertNotIn("SENTINEL_SECRET", rendered)
    self.assertNotIn(str(private_root), rendered)
```

- [ ] **Step 2: Run and observe failure**

Run: `uv run python -m unittest -v tests.test_prime_long_running_parity`

Expected: FAIL because `PrimeLongRunningService` does not exist.

- [ ] **Step 3: Implement the narrow selected-provider service**

```python
class PrimeLongRunningService:
    async def apply(self, command: LongRunningCommand) -> LongRunningReceipt:
        receipt = await self._client.execute_long_running(command)
        if receipt.command_id != command.command_id:
            raise PrimeLongRunningError("Prime long-running receipt is invalid")
        return receipt
```

The service translates and validates only. It does not run a clock, choose due work, authorize a request, or retry a side effect.

- [ ] **Step 4: Run Python and cross-language tests**

Run: `uv run python -m unittest -v tests.test_control_long_running tests.test_prime_long_running_parity`

Run: `npm --prefix packages/typescript/prime-gateway test -- test/long-running.test.mjs`

Expected: PASS.

- [ ] **Step 5: Commit the selected-provider binding**

```bash
git add src/asterion/control/providers/prime/long_running.py \
  src/asterion/control/providers/prime/client.py \
  tests/test_prime_long_running_parity.py
git commit -m "feat: bind prime long-running host service"
```

### Task 5: Add residency, eviction, restart/update recovery, and orphan audit

**Files:**
- Modify: `src/asterion/control/long_running.py`
- Modify: `src/asterion/control/providers/prime/long_running.py`
- Modify: `packages/typescript/prime-gateway/src/prime-session.ts`
- Modify: `packages/typescript/prime-gateway/src/durable-store.ts`
- Modify: `tests/test_control_long_running.py`
- Modify: `tests/test_prime_long_running_parity.py`
- Modify: `packages/typescript/prime-gateway/test/long-running.test.mjs`

**Interfaces:**
- Consumes: controller lease identity, task authority revision, worker process observation, and injected virtual clock.
- Produces: `ResidentLease`, `ResidencySnapshot`, `evict_expired(now_ms)`, `audit_orphans()`, and restart/update recovery receipts.

- [ ] **Step 1: Write failing controller/task separation and eviction tests**

```python
def test_controller_residency_never_extends_task_authority(self) -> None:
    lease = coordinator.retain_controller("controller-1", until_ms=10_000)
    task = coordinator.start_task("task-1", authority_expires_at_ms=5_000)
    clock.set(6_000)
    self.assertEqual(coordinator.task_status(task.task_id), "expired")
    self.assertEqual(coordinator.controller_status(lease.controller_id), "resident")

def test_eviction_and_shutdown_leave_no_owned_processes(self) -> None:
    coordinator.evict_expired(10_001)
    coordinator.close()
    self.assertEqual(coordinator.audit_orphans().owned_process_count, 0)
```

- [ ] **Step 2: Write the accelerated restart/update/repeated-attach matrix**

```python
def test_accelerated_day_survives_restart_update_and_repeated_attach(self) -> None:
    for hour in range(24):
        clock.advance(3_600_000)
        if hour == 8:
            coordinator = restart(coordinator)
        if hour == 16:
            coordinator = update_and_recover(coordinator)
        coordinator.attach("controller-1")
        coordinator.attach("controller-1")
    self.assertEqual(coordinator.snapshot().duplicate_effect_count, 0)
```

- [ ] **Step 3: Run and observe failure**

Run: `uv run python -m unittest -v tests.test_control_long_running tests.test_prime_long_running_parity`

Expected: FAIL because residency and orphan auditing are absent.

- [ ] **Step 4: Implement leases, deterministic eviction, recovery, and orphan checks**

```python
@dataclass(frozen=True)
class ResidentLease:
    controller_id: str
    acquired_at_ms: int
    expires_at_ms: int

def audit_orphans(self) -> OrphanAudit:
    active = tuple(sorted(self._process_observer.owned_process_ids()))
    return OrphanAudit(owned_process_count=len(active), digest=_ids_digest(active))
```

Persist lease and task records separately. Update recovery may migrate record format only through an exact version function; it may not reinterpret authority, due time, or terminal status.

- [ ] **Step 5: Run the full virtual-clock matrix and commit**

Run: `uv run python -m unittest -v tests.test_control_long_running tests.test_prime_long_running_parity`

Run: `npm --prefix packages/typescript/prime-gateway test -- test/long-running.test.mjs`

Expected: PASS with zero duplicate effects and zero owned processes after close.

```bash
git add src/asterion/control/long_running.py \
  src/asterion/control/providers/prime/long_running.py \
  packages/typescript/prime-gateway/src/prime-session.ts \
  packages/typescript/prime-gateway/src/durable-store.ts \
  tests/test_control_long_running.py tests/test_prime_long_running_parity.py \
  packages/typescript/prime-gateway/test/long-running.test.mjs
git commit -m "feat: add resident recovery and orphan audit"
```

### Task 6: Add the finite autonomous-quality evidence boundary

**Files:**
- Modify: `src/asterion/control/providers/prime/parity_testing.py`
- Modify: `tests/test_prime_long_running_parity.py`
- Modify: `Makefile`

**Interfaces:**
- Consumes: one externally authorized model selection, maximum one provider operation, finite cost/deadline, and the provider-free long-running receipt set.
- Produces: `test.prime-long-running.provider-free`, `test.prime-long-running.bounded`, and one evidence ID only for `operation.autonomous-quality`.

- [x] **Step 1: Write failing authority and no-promotion tests**

```python
def test_autonomous_quality_requires_one_real_bounded_provider_operation(self) -> None:
    with self.assertRaisesRegex(Exception, "observation is invalid"):
        build_long_running_observation(
            scenario_id="prime-parity.operation.autonomous-quality",
            status="PASS",
            provider_operations=0,
            model_credential_reads=0,
            checks=BOUNDED_AUTONOMY_CHECKS,
        )

def test_provider_free_receipt_never_promotes_autonomous_quality(self) -> None:
    report = run_provider_free_long_running()
    self.assertIn(
        "prime-parity.operation.autonomous-quality",
        report.blocking_scenario_ids,
    )
```

- [x] **Step 2: Run and observe failure**

Run: `uv run python -m unittest -v tests.test_prime_long_running_parity`

Expected: FAIL because the split evidence commands do not exist.

- [x] **Step 3: Implement exact provider-free and bounded reducers**

```python
LONG_RUNNING_PROVIDER_FREE_COMMAND = "test.prime-long-running.provider-free"
LONG_RUNNING_BOUNDED_COMMAND = "test.prime-long-running.bounded"
BOUNDED_AUTONOMY_CHECKS = (
    "bounded-autonomous-goal-completed-passed",
    "bounded-heartbeat-schedule-quiescence-passed",
    "bounded-orphan-audit-passed",
)
```

The bounded run may promote only `operation.autonomous-quality`. All other nine evidence IDs must come from the zero-provider command.

- [x] **Step 4: Add executable Make targets and run both gates**

```make
test.prime-long-running.provider-free:
	$(UV_BIN) run python -m unittest -v tests.test_control_long_running tests.test_prime_long_running_parity
	npm --prefix packages/typescript/prime-gateway test -- test/long-running.test.mjs

test.prime-long-running.bounded:
	ASTERION_PRIME_LONG_RUNNING_BOUNDED=1 $(UV_BIN) run python -m unittest -v \
		tests.test_prime_long_running_parity.TestPrimeLongRunningParity.test_real_bounded_autonomous_quality
```

Run: `make test.prime-long-running.provider-free`

Expected: PASS with zero provider/application operations and zero credential reads.

Run: `make test.prime-long-running.bounded`

Expected: PASS with one provider operation, finite usage, and no raw model output.

- [ ] **Step 5: Commit the evidence split**

```bash
git add Makefile src/asterion/control/providers/prime/parity_testing.py \
  tests/test_prime_long_running_parity.py
git commit -m "test: add bounded long-running autonomy evidence"
```

### Task 7: Promote the domain and run Phase 2 gates

**Files:**
- Modify: `tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json`
- Modify: `tests/test_prime_parity_ledger.py`
- Modify: `tests/test_check_prime_parity.py`
- Modify: `docs/status/PRIME-PARITY-LEDGER.md`
- Modify: `docs/status/CURRENT-STATE.md`
- Modify: `docs/status/JOURNAL.md`
- Modify: `docs/status/RESUME-NEXT-SESSION.md`

**Interfaces:**
- Consumes: nine provider-free evidence IDs and one bounded autonomous-quality evidence ID.
- Produces: Prime Gateway `operation.long-running` domain PASS without changing native-kernel results.

- [x] **Step 1: Write failing ledger and exact-domain tests**

```python
def test_long_running_ledger_binds_nine_provider_free_and_one_bounded_result(self) -> None:
    results = long_running_prime_results(validated_ledger())
    self.assertEqual(count_status(results, "provider-free-pass"), 9)
    self.assertEqual(count_status(results, "bounded-pass"), 1)

def test_long_running_domain_report_is_closed(self) -> None:
    report = run_checker("operation.long-running", "asterion.prime-gateway")
    self.assertEqual(report["selected_feature_count"], 10)
    self.assertEqual(report["passed_feature_count"], 10)
    self.assertEqual(report["blocking_feature_count"], 0)
    self.assertEqual(report["status"], "PASS")
```

- [x] **Step 2: Run and observe failure**

Run: `uv run python -m unittest -v tests.test_prime_long_running_parity tests.test_prime_parity_ledger tests.test_check_prime_parity`

Expected: FAIL while ledger rows remain `implemented`/`missing`.

- [x] **Step 3: Add exact sorted evidence and update human status**

Each machine-readable evidence record must contain the exact provider, boundary, command, pinned baseline commit, one feature ID, and one primary scenario ID. Keep evidence IDs sorted and unique. Leave every `asterion.native` result `missing`.

- [x] **Step 4: Run all named verification gates**

Run: `make test.prime-long-running.provider-free`

Run: `make test.prime-long-running.bounded`

Run: `uv run python tools/check_prime_parity.py --domain operation.long-running --provider asterion.prime-gateway`

Run: `make check`

Run: `make promotion-check`

Run: `git diff --check`

Expected: all commands PASS; the domain report shows 10/10 and the system claim remains blocked on later domains.

- [ ] **Step 5: Commit the domain closure**

```bash
git add tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json \
  tests/test_prime_parity_ledger.py tests/test_check_prime_parity.py \
  docs/status/PRIME-PARITY-LEDGER.md docs/status/CURRENT-STATE.md \
  docs/status/JOURNAL.md docs/status/RESUME-NEXT-SESSION.md
git commit -m "feat: close prime long-running operations parity"
```

---

## Self-Review

- Spec coverage: Tasks 1 and 7 cover all ten stable feature/scenario identities and exact ledger promotion. Tasks 2–4 distinguish user/agent heartbeat ownership and once/cron scheduling. Task 5 separates controller residency from task authority and covers accelerated 24-hour restart, update, eviction, repeated attach, cancellation, shutdown, and orphan audit. Task 6 isolates the only bounded-provider scenario.
- Placeholder scan: The plan contains no TBD/TODO/ellipsis implementation bodies. Every implementation step names concrete types, methods, tests, commands, and expected results.
- Type consistency: `LongRunningCoordinator` owns policy/time/journal; `PrimeLongRunningService` only translates; `LongRunningReceipt` is the shared body-free result. Evidence command IDs are stable across Task 6 and Task 7.
