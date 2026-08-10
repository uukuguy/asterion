# Asterion Prime Verified Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a bounded, recoverable Prime-managed Asterion session that can pursue a durable goal, invoke one exact authorized application, run one host-admitted recursive Prime child, detach/attach, checkpoint/restart, cancel, stop at budget, and publish body-free causal evidence.

**Architecture:** A Python `ControlHost` retains canonical state, authority, durable journal, action execution and Pathlight. A TypeScript sidecar translates the closed Asterion control protocol to a dedicated pinned Prime daemon v7/schema 14 and hosts an authenticated private skill bridge. Prime remains the controller engine; every external application or child operation crosses an Asterion action proposal and receipt boundary.

**Tech Stack:** Python 3.12 frozen values and `unittest`, TypeScript 6/Node.js 22.8 JSONL and Unix sockets, JSON Schema 2020-12/Ajv, Prime Agent source commit `a18809e00ea30638584d87b3afea7285a9d7296c`, existing Asterion application runner/runtime/Pathlight APIs, SHA-256 artifact locks, and provider-free real-process fault tests.

## Global Constraints

- Preserve `CLI/host -> selected provider -> assembly -> catalog/composer -> exact implementations -> runner -> runtime/host services`.
- Treat `asterion.agent-system/v1`, `asterion.control-plane/v1`, `asterion.agent-control/v1` and all existing v1 protocols as closed; protocol changes require canonical schema, Python, TypeScript and fixture agreement.
- Implement the daemon decision in `docs/superpowers/specs/2026-08-10-asterion-prime-gateway-daemon-delta.md`; do not silently fall back to CLI RPC.
- Require Prime protocol `7`, schema revision `14`, schema ID `protocol-7-schema-14-816309b1cd50`, app version `0.7.1` and the locked source digests before session creation.
- Normal `make test`, `make check`, `list`, `describe`, `acceptance` and promotion stay Prime-, model- and provider-free.
- Prime source, credentials, agent roots, sockets, prompts, answers, provider payloads, transcript bodies, raw tool output and capsule bodies remain external/private and never enter the wheel or public evidence.
- Use a dedicated Prime daemon and agent root per Asterion root session; never attach to the operator's normal Prime daemon.
- Phase 1 supports `trusted-local`; reject `restricted` before Prime start unless an injected `execution.domain` service proves that profile.
- Set native Prime RLM depth to `0`; all Phase 1 recursive work uses host-admitted `asterion_control.spawn_child`. Keep full native `rlm.programmatic` parity marked missing.
- Persist command IDs, proposal IDs, private bridge request IDs, receipts and cursors before acknowledgement. Never retry an uncertain external effect.
- Require caller-supplied idempotency keys for application and child operations.
- Run application assemblies sequentially and stop on failure/cancellation. The control provider cannot discover or expand the immutable portfolio.
- Use TDD, focused `unittest`/Node tests, sentinel secrets, exact process-fault matrices and specific-file commits. Do not stage `docs/status/JOURNAL.md` or `docs/status/RESUME-NEXT-SESSION.md` in feature commits.
- Bounded real-provider verification requires explicit operator authorization, a finite token/cost envelope and available credentials. Without it, record `External-limited`, never `PASS`.

---

## File Structure

### TypeScript Prime Gateway

- `packages/typescript/prime-gateway/package.json` — private package, Node floor and provider-free scripts.
- `packages/typescript/prime-gateway/package-lock.json` — only Asterion runtime/Ajv development dependencies; no unpublished Prime registry dependency.
- `packages/typescript/prime-gateway/tsconfig.json` — strict ESM build.
- `packages/typescript/prime-gateway/resources/prime-artifact-lock.json` — exact source/protocol digests.
- `packages/typescript/prime-gateway/src/artifact-lock.ts` — source checkout preflight.
- `packages/typescript/prime-gateway/src/daemon-wire.ts` — narrow pinned daemon DTOs and closed validation.
- `packages/typescript/prime-gateway/src/daemon-client.ts` — JSONL socket correlation, acknowledgement and reconnect.
- `packages/typescript/prime-gateway/src/durable-store.ts` — append/fsync gateway command/event state.
- `packages/typescript/prime-gateway/src/private-store.ts` — private input/result/capsule values.
- `packages/typescript/prime-gateway/src/skill-bridge.ts` — authenticated private Unix-socket requests.
- `packages/typescript/prime-gateway/src/event-mapper.ts` — Prime state/events to safe Asterion events.
- `packages/typescript/prime-gateway/src/prime-session.ts` — dedicated daemon lifecycle and bounded session control.
- `packages/typescript/prime-gateway/src/checkpoint.ts` — update-restart capsule sealing and restore.
- `packages/typescript/prime-gateway/src/gateway.ts` — `ControlCommand` orchestration and replay.
- `packages/typescript/prime-gateway/src/main.ts` — private Python/Node JSONL sidecar entry point.
- `packages/typescript/prime-gateway/test/*.test.mjs` — built-in Node tests.
- `packages/typescript/prime-gateway/test/fixtures/fake-prime-daemon.mjs` — deterministic real socket/process double.

### Python Control and Prime Provider

- `src/asterion/control/private_store.py` — provider-neutral private reference/result protocols.
- `src/asterion/control/execution.py` — typed action execution receipts and failure certainty.
- `src/asterion/control/application_executor.py` — exact portfolio application invocation.
- `src/asterion/control/children.py` — derived child authority, registry and cancellation cascade.
- `src/asterion/control/journal.py` — durable file journal and receipt/checkpoint constructors.
- `src/asterion/control/recovery.py` — journal-to-state/authority recovery.
- `src/asterion/control/manager.py` — admitted action execution and terminal settlement.
- `src/asterion/control/evidence.py` — action execution/receipt/recovery causal projection.
- `src/asterion/control/providers/prime/__init__.py` — narrow provider exports.
- `src/asterion/control/providers/prime/client.py` — async sidecar `ControlPlaneClient`.
- `src/asterion/control/providers/prime/factory.py` — exact Prime factory binding and trusted-local preflight.
- `src/asterion/control/providers/prime/process.py` — direct argv, scrubbed environment and cancellation.
- `src/asterion/control/providers/prime/resources/control-plane.json` — authority-free provider manifest.
- `src/asterion/control/providers/prime/resources/skills/asterion-control/SKILL.md` — model instructions.
- `src/asterion/control/providers/prime/resources/skills/asterion-control/pyproject.toml` — Python-backed Prime skill.
- `src/asterion/control/providers/prime/resources/skills/asterion-control/src/asterion_control/__init__.py` — private bridge client.
- `src/asterion/control/providers/prime/resources/skills/asterion-control/src/asterion_control/_protocol.py` — closed request/response values.
- `tools/setup_prime_agent.py` — explicit external source setup/check, zero model operations.
- `tools/verify_prime_loop.py` — provider-free and separately authorized bounded gates.

### Tests, Fixtures and Documentation

- `tests/test_control_file_journal.py`
- `tests/test_control_recovery.py`
- `tests/test_control_execution.py`
- `tests/test_control_application_executor.py`
- `tests/test_control_children.py`
- `tests/test_prime_control_client.py`
- `tests/test_prime_control_factory.py`
- `tests/test_prime_skill.py`
- `tests/test_prime_verified_loop.py`
- `tests/fixtures/prime_gateway/v1/*.json`
- `docs/guides/prime-control-operator-guide.md`
- `docs/status/PRIME-PARITY-LEDGER.md`
- `Makefile`, `pyproject.toml`, `tools/check_promotion.py`, `tests/test_distribution.py` and `tests/test_check_promotion.py` — provider-free packaging and promotion coverage.

---

### Task 1: Lock the exact external Prime source and scaffold the gateway

**Files:**
- Create: `packages/typescript/prime-gateway/package.json`
- Create: `packages/typescript/prime-gateway/package-lock.json`
- Create: `packages/typescript/prime-gateway/tsconfig.json`
- Create: `packages/typescript/prime-gateway/resources/prime-artifact-lock.json`
- Create: `packages/typescript/prime-gateway/src/artifact-lock.ts`
- Create: `packages/typescript/prime-gateway/src/index.ts`
- Test: `packages/typescript/prime-gateway/test/artifact-lock.test.mjs`

**Interfaces:**
- Consumes: an explicit external Prime source root and ordinary filesystem reads.
- Produces: `PrimeArtifactLock`, `PrimeArtifactEvidence`, `loadPrimeArtifactLock(url)` and `verifyPrimeArtifact(root, lock)`.
- `verifyPrimeArtifact` returns only version/commit/digests and never returns or renders the source root.

- [ ] **Step 1: Write the failing artifact-lock test**

```javascript
test("accepts only the pinned clean source artifact", async () => {
  const evidence = await verifyPrimeArtifact(fixture.root, lock);
  assert.equal(evidence.commit, "a18809e00ea30638584d87b3afea7285a9d7296c");
  assert.equal(evidence.protocolVersion, 7);
  await assert.rejects(
    verifyPrimeArtifact(fixture.withChanged("prime-agent.sh", "SENTINEL_SECRET"), lock),
    /Prime artifact is incompatible/,
  );
});
```

Also assert fixed redacted errors for missing files, symlinks, non-regular files, dirty git worktrees, wrong package version and each digest mismatch.

- [ ] **Step 2: Run the test to verify RED**

Run: `npm test --prefix packages/typescript/prime-gateway -- --test-name-pattern='pinned clean source artifact'`

Expected: FAIL because the package and verifier do not exist.

- [ ] **Step 3: Add the exact lock and verifier**

Use this lock content:

```json
{
  "format": "asterion.prime-artifact-lock/v1",
  "source_commit": "a18809e00ea30638584d87b3afea7285a9d7296c",
  "package_name": "@earendil-works/pi-coding-agent",
  "package_version": "0.7.1",
  "daemon_protocol": 7,
  "daemon_schema_revision": 14,
  "daemon_schema_id": "protocol-7-schema-14-816309b1cd50",
  "files": {
    "package-lock.json": "39ee303bca10c0933cf917275613c8f44099f50de1650a5c356e7cda02b701e8",
    "packages/coding-agent/package.json": "4e49f896d35be953c7939c2daaf5fcf884092f3b10370778e1643a54185c4033",
    "packages/coding-agent/src/modes/daemon/daemon-client.ts": "5b2dcbd5b65697ccae5a80a6e491592afd8d60cde0f93d6ce0091b02eba03d1d",
    "packages/coding-agent/src/modes/daemon/daemon-protocol.ts": "55200bf1fb1b979ef1864391f1ba3b74737bfbaf89de6d0c64721a8faddbe989",
    "prime-agent.sh": "0ceef94210da44aa2cb232fb18fd215c5a25caf7b652531856c5a90af01df09d"
  }
}
```

Read every file with `lstat`, reject symlinks, hash bytes, parse the two package files, and run `git status --porcelain --untracked-files=no` plus `git rev-parse HEAD` only when `.git` exists. Never include command stderr or a path in the raised error.

- [ ] **Step 4: Run the focused package tests**

Run: `npm test --prefix packages/typescript/prime-gateway`

Expected: PASS with zero Prime process and model operations.

- [ ] **Step 5: Commit the source lock**

```bash
git add packages/typescript/prime-gateway/package.json packages/typescript/prime-gateway/package-lock.json packages/typescript/prime-gateway/tsconfig.json packages/typescript/prime-gateway/resources/prime-artifact-lock.json packages/typescript/prime-gateway/src/artifact-lock.ts packages/typescript/prime-gateway/src/index.ts packages/typescript/prime-gateway/test/artifact-lock.test.mjs
git commit -m "feat: lock the prime gateway source artifact"
```

### Task 2: Implement the narrow capability-gated daemon client

**Files:**
- Create: `packages/typescript/prime-gateway/src/daemon-wire.ts`
- Create: `packages/typescript/prime-gateway/src/daemon-client.ts`
- Create: `packages/typescript/prime-gateway/test/daemon-wire.test.mjs`
- Create: `packages/typescript/prime-gateway/test/daemon-client.test.mjs`
- Create: `packages/typescript/prime-gateway/test/fixtures/fake-prime-daemon.mjs`

**Interfaces:**
- Produces: closed `PrimeDaemonHello`, `PrimeDaemonCursor`, `PrimeDaemonCommand`, `PrimeDaemonOutbound` types.
- Produces: `PrimeDaemonClient.connect(socketPath)`, `request(command, stableCommandId)`, `subscribe(listener)`, `reconnect()` and `close()`.
- Required server capabilities are the exact sorted set `attach_snapshot`, `chunked_snapshot`, `event_sequence`, `prompt_admission_cancellation`, `session_input_admission`.

- [ ] **Step 1: Write failing wire and real-socket tests**

```javascript
test("rejects stale handshake before create", async () => {
  const daemon = await startFakePrimeDaemon({ protocol: 6 });
  const client = new PrimeDaemonClient({ clientId: "client-1" });
  await assert.rejects(client.connect(daemon.socketPath), /Prime daemon is incompatible/);
  assert.deepEqual(daemon.commands, []);
});

test("replays one stable mutation envelope after disconnect", async () => {
  const response = await client.request(
    { type: "prompt", activeSessionId: "prime-root", message: "private" },
    "asterion-command-1",
  );
  assert.equal(response.success, true);
  assert.equal(daemon.mutationCount("asterion-command-1"), 1);
});
```

Cover malformed JSON, oversized lines, missing fields, unknown outbound kinds, timeout, stable client ID, `ack_result`, capability drift, reconnect downgrade, generation change and `command_result_uncertain`. Assert the prompt sentinel never appears in an error.

- [ ] **Step 2: Run focused tests to verify RED**

Run: `npm test --prefix packages/typescript/prime-gateway -- --test-name-pattern='daemon'`

Expected: FAIL because the wire/client modules do not exist.

- [ ] **Step 3: Implement closed decoding and correlation**

```typescript
export const REQUIRED_SERVER_CAPABILITIES = Object.freeze([
  "attach_snapshot",
  "chunked_snapshot",
  "event_sequence",
  "prompt_admission_cancellation",
  "session_input_admission",
] as const);

export type PrimeDaemonCursor = Readonly<{ generation: string; sequence: number }>;

export class PrimeDaemonUncertainError extends Error {
  constructor(readonly commandId: string) {
    super("Prime daemon mutation result is uncertain");
  }
}
```

Frame with one JSON value per LF, cap input at 1 MiB, create the v7 command envelope with distinct Asterion/daemon IDs, retain unresolved mutation bytes across reconnect, re-check the new greeting before replay, acknowledge a terminal response and convert only the structured uncertain code to `PrimeDaemonUncertainError`.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `npm test --prefix packages/typescript/prime-gateway -- --test-name-pattern='daemon'`

Expected: PASS with the fake daemon in a temporary `0700` directory.

- [ ] **Step 5: Commit the daemon adapter**

```bash
git add packages/typescript/prime-gateway/src/daemon-wire.ts packages/typescript/prime-gateway/src/daemon-client.ts packages/typescript/prime-gateway/test/daemon-wire.test.mjs packages/typescript/prime-gateway/test/daemon-client.test.mjs packages/typescript/prime-gateway/test/fixtures/fake-prime-daemon.mjs
git commit -m "feat: negotiate the pinned prime daemon protocol"
```

### Task 3: Add durable gateway records and private values

**Files:**
- Create: `packages/typescript/prime-gateway/src/durable-store.ts`
- Create: `packages/typescript/prime-gateway/src/private-store.ts`
- Create: `packages/typescript/prime-gateway/test/durable-store.test.mjs`
- Create: `packages/typescript/prime-gateway/test/private-store.test.mjs`

**Interfaces:**
- Produces: `GatewayDurableStore.open(root, sessionId)`, `acceptCommand`, `appendEvent`, `eventsAfter`, `bindPrimeIdentity`, `recordPrimeCursor` and `snapshot`.
- Produces: `PrivateValueStore.putInput`, `readInput`, `putResult`, `readResult`, `putCapsule` and `readCapsule` using opaque references.
- Public record files contain only validated Asterion commands/events and digests; private value files are `0600` and never rendered.

- [ ] **Step 1: Write failing durability/security tests**

```javascript
test("fsyncs before acknowledging and rejects divergent replay", async () => {
  const store = await GatewayDurableStore.open(root, "session-1");
  const first = await store.acceptCommand(command);
  const replay = await store.acceptCommand(structuredClone(command));
  assert.equal(replay.position, first.position);
  await assert.rejects(store.acceptCommand({ ...command, authority_revision: 2 }), /conflicts/);
});

test("private values reject symlink replacement and redact bodies", async () => {
  const ref = await values.putInput("SENTINEL_SECRET");
  assert.doesNotMatch(String(values), /SENTINEL_SECRET/);
  await replaceValueWithSymlink(root, ref);
  await assert.rejects(values.readInput(ref), /private value is invalid/);
});
```

Inject faults before write, after write, before rename and before directory fsync. Reopen after each fault and require a valid prefix or explicit corruption error, never partial acceptance.

- [ ] **Step 2: Run tests to verify RED**

Run: `npm test --prefix packages/typescript/prime-gateway -- --test-name-pattern='durable|private values'`

Expected: FAIL because stores do not exist.

- [ ] **Step 3: Implement append/atomic storage**

Use canonical JSON, SHA-256 record digests, `open` with no-follow checks, complete writes, `datasync`, atomic rename and parent-directory sync. Store input bodies by digest but return an independent opaque reference:

```typescript
export type PrivateValueRef = `private:${string}`;

export interface PrivateResultProjection {
  readonly receiptRef: string;
  readonly artifactIds: readonly string[];
  readonly mediaTypes: readonly string[];
}
```

Cap one input at 1 MiB, one result at 64 KiB, one capsule at 8 MiB and the public event log at 100,000 records per generation.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `npm test --prefix packages/typescript/prime-gateway -- --test-name-pattern='durable|private values'`

Expected: PASS including every injected write fault.

- [ ] **Step 5: Commit gateway storage**

```bash
git add packages/typescript/prime-gateway/src/durable-store.ts packages/typescript/prime-gateway/src/private-store.ts packages/typescript/prime-gateway/test/durable-store.test.mjs packages/typescript/prime-gateway/test/private-store.test.mjs
git commit -m "feat: persist prime gateway control state"
```

### Task 4: Build the authenticated `asterion_control` skill bridge

**Files:**
- Create: `packages/typescript/prime-gateway/src/skill-bridge.ts`
- Create: `packages/typescript/prime-gateway/test/skill-bridge.test.mjs`
- Create: `src/asterion/control/providers/prime/resources/skills/asterion-control/SKILL.md`
- Create: `src/asterion/control/providers/prime/resources/skills/asterion-control/pyproject.toml`
- Create: `src/asterion/control/providers/prime/resources/skills/asterion-control/src/asterion_control/__init__.py`
- Create: `src/asterion/control/providers/prime/resources/skills/asterion-control/src/asterion_control/_protocol.py`
- Test: `tests/test_prime_skill.py`

**Interfaces:**
- The private socket accepts exactly `portfolio.get`, `budget.get`, `application.invoke`, `child.spawn`, `child.message`, `child.cancel`, `checkpoint.request`, `goal.complete`, `goal.fail` and `action.status`.
- Python exposes async `portfolio`, `remaining_budget`, `invoke_application`, `spawn_child`, `message_child`, `cancel_child`, `request_checkpoint`, `complete_goal`, `fail_goal` and `action_status`.
- Effectful calls require an `idempotency_key`; request bodies are stored privately before a public proposal is emitted.

- [ ] **Step 1: Write failing Node and Python protocol tests**

```python
async def test_invoke_requires_stable_idempotency_and_never_echoes_body(self) -> None:
    with self.assertRaises(ValueError):
        await asterion_control.invoke_application(
            target=AUTHORIZED_TARGET,
            input_text="SENTINEL_SECRET",
            idempotency_key="",
            budget=FINITE_BUDGET,
        )
    self.assertNotIn("SENTINEL_SECRET", repr(asterion_control))
```

Node tests cover wrong token, cross-session token, peer close, duplicate equal request, duplicate divergent request, request/response size caps and socket/file permissions. Python tests use a fake socket and assert exact snake-case signatures and immutable return values.

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
npm test --prefix packages/typescript/prime-gateway -- --test-name-pattern='skill bridge'
uv run python -m unittest -v tests.test_prime_skill
```

Expected: FAIL because bridge and skill do not exist.

- [ ] **Step 3: Implement the closed bridge and skill**

The skill reads `ASTERION_CONTROL_SOCKET`, `ASTERION_CONTROL_TOKEN` and `ASTERION_CONTROL_SESSION_ID` only at call time. It sends a 32-byte random token in the first private frame and never includes it in exceptions. Define the effectful API without implicit budget expansion:

```python
async def invoke_application(
    *,
    target: Mapping[str, str],
    input_text: str,
    idempotency_key: str,
    budget: Mapping[str, int],
    expected_artifacts: Sequence[str] = (),
) -> Mapping[str, object]:
    request = build_application_request(
        target=target,
        input_text=input_text,
        idempotency_key=idempotency_key,
        budget=budget,
        expected_artifacts=expected_artifacts,
    )
    return await exchange(request)
```

The Node bridge derives `action_id` from session ID plus idempotency key, persists the private input before emitting `action.proposed`, waits for both admission and terminal resolution, and returns only the stored safe result projection.

- [ ] **Step 4: Run bridge/skill tests to verify GREEN**

Run the two Step 2 commands.

Expected: PASS with sentinel absent from stdout, stderr, errors and event records.

- [ ] **Step 5: Commit the controlled skill**

```bash
git add packages/typescript/prime-gateway/src/skill-bridge.ts packages/typescript/prime-gateway/test/skill-bridge.test.mjs src/asterion/control/providers/prime/resources/skills tests/test_prime_skill.py
git commit -m "feat: bridge prime skills through host admission"
```

### Task 5: Map the Prime resident lifecycle to Asterion events

**Files:**
- Create: `packages/typescript/prime-gateway/src/event-mapper.ts`
- Create: `packages/typescript/prime-gateway/src/prime-session.ts`
- Create: `packages/typescript/prime-gateway/src/gateway.ts`
- Create: `packages/typescript/prime-gateway/test/event-mapper.test.mjs`
- Create: `packages/typescript/prime-gateway/test/prime-session.test.mjs`
- Create: `packages/typescript/prime-gateway/test/gateway.test.mjs`

**Interfaces:**
- `PrimeSession.create` sends resident `create` with exact private root, workspace, model, initial goal, finite autonomous limits, explicit skill path and native RLM depth `0`.
- `PrimeGateway.accept(command)` persists then handles all Phase 0 commands.
- `PrimeEventMapper` emits only existing closed Asterion event types; assistant/message bodies are not emitted in Phase 1.

- [ ] **Step 1: Write failing lifecycle/mapping tests**

```javascript
test("create binds a resident root and emits one safe running prefix", async () => {
  await gateway.accept(sessionCreate);
  assert.deepEqual(store.eventTypes(), ["session.created", "session.running"]);
  assert.equal(fakeDaemon.lastCreate.lifecycle, "resident");
  assert.equal(fakeDaemon.lastCreate.config.initialGoal.tokenBudget, 2000);
  assert.equal(fakeDaemon.lastRlmMaxDepth, 0);
});
```

Cover direct/steer/follow-up mapping, pause as abort-and-clear plus gateway paused state, resume, detach without kill, attach with cursor, cancellation cascade, auth-stale safe fault, goal complete, goal budget limit, controller usage conversion and terminal uniqueness. Inject prompt admission `cancelled`, `owned`, `unknown` and ensure only `unknown` becomes recoverable uncertainty.

- [ ] **Step 2: Run tests to verify RED**

Run: `npm test --prefix packages/typescript/prime-gateway -- --test-name-pattern='lifecycle|mapping|gateway'`

Expected: FAIL because lifecycle modules do not exist.

- [ ] **Step 3: Implement bounded session control**

Construct Prime config only from private startup input:

```typescript
const config = Object.freeze({
  cwd: privateConfig.workspace,
  agentDir: privateConfig.agentDir,
  sessionDir: privateConfig.sessionDir,
  provider: privateConfig.provider,
  model: privateConfig.model,
  skills: [privateConfig.skillPath],
  autonomous: {
    enabled: true,
    maxContinuations: privateConfig.maxContinuations,
    maxTurns: privateConfig.maxTurns,
    maxTokens: privateConfig.maxControllerTokens,
    timeoutMs: privateConfig.timeoutMs,
    gates: { commands: [], maxRetries: 1, timeoutMs: privateConfig.timeoutMs },
  },
  telemetryDisabled: true,
  initialGoal: { objective: privateConfig.goal, tokenBudget: privateConfig.maxControllerTokens },
});
```

After create, send `set_rlm_max_depth` with `0`, attach with slim/chunked snapshots and persist the Prime identity/cursor. Translate Prime `goal_update`, session close, resync, connection status, usage snapshots and skill proposals to fixed reason codes/digests. Never translate message text, bash command/output, system prompt, file path or extension error body.

- [ ] **Step 4: Run focused lifecycle tests**

Run: `npm test --prefix packages/typescript/prime-gateway -- --test-name-pattern='lifecycle|mapping|gateway'`

Expected: PASS and all complete streams validate through `@dci/agent-runtime` control validators.

- [ ] **Step 5: Commit lifecycle mapping**

```bash
git add packages/typescript/prime-gateway/src/event-mapper.ts packages/typescript/prime-gateway/src/prime-session.ts packages/typescript/prime-gateway/src/gateway.ts packages/typescript/prime-gateway/test/event-mapper.test.mjs packages/typescript/prime-gateway/test/prime-session.test.mjs packages/typescript/prime-gateway/test/gateway.test.mjs
git commit -m "feat: map prime resident sessions to agent control"
```

### Task 6: Seal and restore real Prime continuation capsules

**Files:**
- Create: `packages/typescript/prime-gateway/src/checkpoint.ts`
- Create: `packages/typescript/prime-gateway/test/checkpoint.test.mjs`
- Modify: `packages/typescript/prime-gateway/src/gateway.ts`
- Modify: `packages/typescript/prime-gateway/test/fixtures/fake-prime-daemon.mjs`

**Interfaces:**
- Produces `PrimeCheckpointManager.create(checkpointId, coveredSequence)` and `restore(capsuleRef, expectedDigest)`.
- A capsule privately binds artifact evidence, Prime update manifest, active/transcript identities, last Prime cursor, last Asterion event cursor and private store generation.
- `checkpoint.created.covered_sequence` is the last Asterion event sealed before the checkpoint event.

- [ ] **Step 1: Write failing checkpoint/restart tests**

```javascript
test("checkpoint restarts the dedicated daemon and reattaches exact identity", async () => {
  const created = await checkpoints.create("checkpoint-1", 8);
  assert.equal(created.coveredSequence, 8);
  assert.equal(fakeDaemon.prepareCount, 1);
  assert.equal(fakeDaemon.relaunchCount, 1);
  assert.equal(fakeDaemon.attachedActiveSessionId, "prime-root-1");
});
```

Cover manifest with duplicate/missing root, wrong session, digest tamper, capsule symlink, schema/build drift, crash before manifest persistence, crash after worker stop, daemon relaunch failure, unavailable replay plus valid snapshot, unavailable replay plus invalid snapshot and checkpoint idempotent replay.

- [ ] **Step 2: Run test to verify RED**

Run: `npm test --prefix packages/typescript/prime-gateway -- --test-name-pattern='checkpoint'`

Expected: FAIL because checkpoint manager does not exist.

- [ ] **Step 3: Implement checkpoint/restart**

Call `wait_for_idle`, then `prepare_update_restart`; validate exactly one root disposition plus its descendants in the dedicated daemon. Canonicalize and privately persist the manifest before acknowledging. Stop the supervisor, launch the same verified source artifact, wait for the exact greeting, attach the original active-session ID and validate transcript session ID. Emit `session.recovery-required` before recovery and `session.running` only after a coherent snapshot.

```typescript
export interface PrimeCapsuleV1 {
  readonly format: "asterion.prime-capsule/v1";
  readonly artifactDigest: string;
  readonly activeSessionId: string;
  readonly transcriptSessionId: string;
  readonly primeCursor: PrimeDaemonCursor;
  readonly asterionGeneration: number;
  readonly asterionSequence: number;
  readonly updateManifest: unknown;
}
```

Never place `PrimeCapsuleV1` in a public event; publish only its SHA-256 and opaque storage reference.

- [ ] **Step 4: Run checkpoint tests to verify GREEN**

Run: `npm test --prefix packages/typescript/prime-gateway -- --test-name-pattern='checkpoint'`

Expected: PASS for every crash/tamper boundary.

- [ ] **Step 5: Commit capsule recovery**

```bash
git add packages/typescript/prime-gateway/src/checkpoint.ts packages/typescript/prime-gateway/src/gateway.ts packages/typescript/prime-gateway/test/checkpoint.test.mjs packages/typescript/prime-gateway/test/fixtures/fake-prime-daemon.mjs
git commit -m "feat: checkpoint prime continuation capsules"
```

### Task 7: Add the Python Prime sidecar client and exact factory

**Files:**
- Create: `packages/typescript/prime-gateway/src/main.ts`
- Create: `packages/typescript/prime-gateway/test/main.test.mjs`
- Create: `src/asterion/control/providers/__init__.py`
- Create: `src/asterion/control/providers/prime/__init__.py`
- Create: `src/asterion/control/providers/prime/process.py`
- Create: `src/asterion/control/providers/prime/client.py`
- Create: `src/asterion/control/providers/prime/factory.py`
- Create: `src/asterion/control/providers/prime/resources/control-plane.json`
- Test: `tests/test_prime_control_client.py`
- Test: `tests/test_prime_control_factory.py`

**Interfaces:**
- Private sidecar input is a closed `asterion.prime-gateway-ipc/v1` envelope containing one public command plus optional resolved private content.
- `PrimeControlPlaneClient` implements existing `ControlPlaneClient` exactly.
- `prime_control_plane_binding()` returns exact identity `prime.gateway@0.1.0`, checkpoint version `1.0.0` and compatibility IDs `prime-agent.daemon/v7`, `prime-agent.schema/v14`.

- [ ] **Step 1: Write failing process/client/factory tests**

```python
async def test_command_is_accepted_only_after_sidecar_ack(self) -> None:
    client = PrimeControlPlaneClient(process=fake_process, private_content=resolver)
    await client.send(create_command)
    self.assertEqual(fake_process.requests[0]["command"]["command_id"], "command-1")

async def test_private_goal_is_not_rendered_on_sidecar_failure(self) -> None:
    resolver.values["goal-ref-1"] = "SENTINEL_SECRET"
    fake_process.fail_with("SENTINEL_SECRET provider body")
    with self.assertRaises(PrimeControlError) as raised:
        await client.send(create_command)
    self.assertNotIn("SENTINEL_SECRET", str(raised.exception))
```

Cover executable/source preflight before spawn, direct argv, no shell, environment allowlist, missing trusted-local authorization, rejected restricted profile, wrong manifest, sidecar EOF, invalid event, cursor replay and bounded close/kill.

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
npm test --prefix packages/typescript/prime-gateway -- --test-name-pattern='sidecar'
uv run python -m unittest -v tests.test_prime_control_client tests.test_prime_control_factory
```

Expected: FAIL because sidecar and provider modules do not exist.

- [ ] **Step 3: Implement private IPC and factory construction**

Use an injected `PrivateContentResolver` for `goal_ref` and `content_ref`. Start Node by exact executable/entry path from private factory options and pass private paths/tokens in a dedicated inherited descriptor, not argv. The public process environment is a fixed allowlist and contains no provider keys.

```python
class PrivateContentResolver(Protocol):
    def resolve_text(self, reference: str, *, max_bytes: int) -> str: ...

class PrimeControlPlaneClient:
    @property
    def manifest(self) -> ControlPlaneManifest: ...
    async def send(self, command: ControlCommand) -> None: ...
    def events(self, cursor: EventCursor | None = None) -> AsyncIterator[ControlEvent]: ...
    async def close(self) -> None: ...
```

The manifest JSON is authority-free and contains no executable, source root, environment, command argv, prompt, credential or state field.

- [ ] **Step 4: Run client/factory tests to verify GREEN**

Run the two Step 2 commands.

Expected: PASS without launching Prime or a model.

- [ ] **Step 5: Commit the Prime provider**

```bash
git add packages/typescript/prime-gateway/src/main.ts packages/typescript/prime-gateway/test/main.test.mjs src/asterion/control/providers tests/test_prime_control_client.py tests/test_prime_control_factory.py
git commit -m "feat: expose prime as an exact control provider"
```

### Task 8: Make the canonical host journal durably recoverable

**Files:**
- Modify: `src/asterion/control/journal.py`
- Create: `src/asterion/control/recovery.py`
- Modify: `src/asterion/control/authority.py`
- Modify: `src/asterion/control/manager.py`
- Test: `tests/test_control_file_journal.py`
- Test: `tests/test_control_recovery.py`

**Interfaces:**
- Produces `FileCanonicalJournal.open(root, session_id)` with the same `CanonicalJournal` contract.
- Produces `recover_control_host_state(entries, envelope)` returning immutable `RecoveredControlState(state, authority_usage, reservations, cursor)`.
- `ControlHost` accepts either a new empty journal or an exact recovered prefix; it never rebinds a different system/authority/session.

- [ ] **Step 1: Write failing durable recovery tests**

```python
def test_reopen_reduces_the_exact_safe_prefix(self) -> None:
    journal = FileCanonicalJournal.open(root, "session-1")
    write_complete_running_action(journal)
    reopened = FileCanonicalJournal.open(root, "session-1")
    recovered = recover_control_host_state(reopened.replay(JournalCursor(0)), envelope)
    self.assertEqual(recovered.state.actions["action-1"].status, "succeeded")
    self.assertEqual(recovered.cursor, EventCursor(generation=1, sequence=5))
```

Cover truncated last line, middle corruption, forged digest, reordered entry, symlink/file-mode attack, mismatched system/authority, admitted-without-receipt reservation, uncertain action, checkpoint prefix and repeated recovery immutability.

- [ ] **Step 2: Run tests to verify RED**

Run: `uv run python -m unittest -v tests.test_control_file_journal tests.test_control_recovery`

Expected: FAIL because file journal and recovery do not exist.

- [ ] **Step 3: Implement durable records and pure replay**

Add constructors for `action.receipted` and `checkpoint.sealed`. Write a versioned hash-chained JSONL envelope with record position, previous digest, record digest and record body; flush and `os.fsync` before returning. Recovery validates the full prefix and applies event reduction, admission, running, terminal resolution, receipt settlement and authority revision in journal order.

```python
@dataclass(frozen=True)
class RecoveredControlState:
    state: ControlState
    authority: AuthorityLedger
    cursor: EventCursor
    journal_position: int
```

Do not treat a truncated/corrupt record as absent. Quarantine must be an explicit operator action outside `open`.

- [ ] **Step 4: Run recovery tests to verify GREEN**

Run: `uv run python -m unittest -v tests.test_control_file_journal tests.test_control_recovery`

Expected: PASS across success and tamper matrices.

- [ ] **Step 5: Commit durable host recovery**

```bash
git add src/asterion/control/journal.py src/asterion/control/recovery.py src/asterion/control/authority.py src/asterion/control/manager.py tests/test_control_file_journal.py tests/test_control_recovery.py
git commit -m "feat: recover durable control host state"
```

### Task 9: Execute and settle admitted actions exactly once

**Files:**
- Create: `src/asterion/control/execution.py`
- Modify: `src/asterion/control/manager.py`
- Modify: `src/asterion/control/state.py`
- Modify: `src/asterion/control/journal.py`
- Modify: `src/asterion/control/evidence.py`
- Test: `tests/test_control_execution.py`
- Modify: `tests/test_control_host.py`
- Modify: `tests/test_control_pathlight.py`

**Interfaces:**
- Produces `ActionExecutionReceipt(action_id, receipt_ref, usage, artifact_ids, media_types)`.
- Produces `ActionExecutionFailure(status, reason_code, receipt_ref)` with status `failed`, `cancelled` or `uncertain`.
- Changes `ActionExecutor.execute(proposal, signal)` to return an exact receipt.
- Host sends admission before execution and exactly one terminal resolution after journal/state/authority settlement.

- [ ] **Step 1: Write failing execution lifecycle tests**

```python
async def test_admitted_action_executes_after_admission_and_settles_before_terminal_send(self) -> None:
    await host.pump()
    self.assertEqual(audit, [
        "journal.decision", "provider.admitted", "journal.running",
        "executor.start", "journal.receipt", "authority.settle",
        "provider.succeeded",
    ])
    self.assertEqual(host.snapshot().state.actions["action-1"].status, "succeeded")
```

Cover unauthorized no-contact, cancellation before start, cancellation during execution, known failure, unknown-progress failure, receipt over budget, duplicate equal receipt, divergent receipt, terminal send failure after durable receipt and recovery without re-execution.

- [ ] **Step 2: Run tests to verify RED**

Run: `uv run python -m unittest -v tests.test_control_execution tests.test_control_host tests.test_control_pathlight`

Expected: FAIL because Phase 0 stops at admission.

- [ ] **Step 3: Implement receipt-first terminal settlement**

```python
@dataclass(frozen=True)
class ActionExecutionReceipt:
    action_id: str
    receipt_ref: str
    usage: BudgetUsage
    artifact_ids: tuple[str, ...] = ()
    media_types: tuple[str, ...] = ()

class ActionExecutor(Protocol):
    async def execute(
        self, proposal: ControlEvent, signal: CancellationSignal
    ) -> ActionExecutionReceipt: ...
```

Journal `action.running` before executor contact, then `action.receipted`, settle `AuthorityLedger`, apply state resolution and dispatch terminal `action.resolve`. If the executor cannot prove non-execution or a receipt, journal/resolve `uncertain`. A terminal-send failure does not undo the settled receipt and recovery resends only the stable terminal command.

- [ ] **Step 4: Run focused execution tests**

Run the Step 2 command.

Expected: PASS with executor called once per admitted action.

- [ ] **Step 5: Commit action execution**

```bash
git add src/asterion/control/execution.py src/asterion/control/manager.py src/asterion/control/state.py src/asterion/control/journal.py src/asterion/control/evidence.py tests/test_control_execution.py tests/test_control_host.py tests/test_control_pathlight.py
git commit -m "feat: execute admitted control actions once"
```

### Task 10: Bridge exact application assemblies into action receipts

**Files:**
- Create: `src/asterion/control/private_store.py`
- Create: `src/asterion/control/application_executor.py`
- Modify: `src/asterion/control/system.py`
- Test: `tests/test_control_application_executor.py`

**Interfaces:**
- Produces `PrivateContentResolver` and `PrivateResultStore` protocols.
- Produces `ApplicationActionExecutor(plan, providers, runtime_factories, content, results, host_services, pathlight)`.
- Selects only the exact `(provider_id, application_id, version, runtime_id)` already in `AgentSystemPlan.portfolio_by_identity`.
- Measures application input/output tokens from `usage.reported`; converts no unknown cost into a fabricated nonzero value.

- [ ] **Step 1: Write failing exact invocation tests**

```python
async def test_exact_portfolio_action_runs_once_and_returns_safe_receipt(self) -> None:
    receipt = await executor.execute(proposal, signal)
    self.assertEqual(receipt.action_id, "action-1")
    self.assertEqual(receipt.usage.application_tokens, 155)
    self.assertEqual(receipt.artifact_ids, ("artifact-1",))
    self.assertNotIn("SENTINEL_SECRET", repr(receipt))
```

Cover provider/application/version/runtime mismatch, missing private input, oversized input, missing runtime, missing host service, cancellation, runtime failure before effect, unknown provider progress, duplicate artifact, usage exceeding reservation and result-store publication failure after execution as `uncertain`.

- [ ] **Step 2: Run test to verify RED**

Run: `uv run python -m unittest -v tests.test_control_application_executor`

Expected: FAIL because executor does not exist.

- [ ] **Step 3: Implement exact application execution**

Resolve the installed application and its exact `InstalledAssembly`, create its runtime from the already selected factory, then call `run_composed_application` with the existing implementations, services, cancellation signal and Pathlight recorder. Sum only validated `usage.reported` events:

```python
application_tokens = sum(
    int(event["payload"]["input_tokens"])
    + int(event["payload"]["output_tokens"])
    for event in result.events
    if event["type"] == "usage.reported"
)
```

Publish only receipt reference, sorted artifact IDs and sorted media types to `PrivateResultStore`. Raw text events and artifact URIs remain private.

- [ ] **Step 4: Run application executor tests**

Run: `uv run python -m unittest -v tests.test_control_application_executor tests.test_runner_composed`

Expected: PASS without provider access.

- [ ] **Step 5: Commit the portfolio bridge**

```bash
git add src/asterion/control/private_store.py src/asterion/control/application_executor.py src/asterion/control/system.py tests/test_control_application_executor.py
git commit -m "feat: invoke exact applications from control actions"
```

### Task 11: Add host-admitted recursive Prime children

**Files:**
- Create: `src/asterion/control/children.py`
- Modify: `src/asterion/control/application_executor.py`
- Modify: `src/asterion/control/manager.py`
- Modify: `src/asterion/control/providers/prime/factory.py`
- Test: `tests/test_control_children.py`
- Modify: `tests/test_prime_verified_loop.py`

**Interfaces:**
- Produces `derive_child_authority(parent, proposal, child_id)` with a finite budget not exceeding the reserved child slice.
- Produces `ChildSessionService.spawn`, `message`, `cancel` and `cancel_all`.
- Child roots use separate provider roots/journals, the same resolved system portfolio and strictly lower remaining recursion depth.
- Parent completion waits for child terminal receipt; parent cancellation cancels active actions and child roots before its terminal event.

- [ ] **Step 1: Write failing child authority/lifecycle tests**

```python
async def test_child_model_work_starts_only_after_parent_admission(self) -> None:
    await host.pump()
    self.assertLess(audit.index("parent.provider.admitted"), audit.index("child.provider.create"))
    self.assertEqual(children.active_ids, ())
    self.assertGreater(host.snapshot().authority_usage.child_tokens, 0)
```

Cover max depth, concurrency, budget derivation, exact child identity, child create fault, child terminal failure, parent-to-child message, child cancellation, root cancellation cascade, child gateway crash/recover, duplicate spawn idempotency and no native Prime RLM child observation.

- [ ] **Step 2: Run tests to verify RED**

Run: `uv run python -m unittest -v tests.test_control_children tests.test_prime_verified_loop`

Expected: FAIL because child service does not exist.

- [ ] **Step 3: Implement nested controlled sessions**

Use the same `ControlPlaneFactoryRegistry` and `AgentSystemPlan`; allocate `<private-root>/children/<child-id>` without following symlinks. Derive the child envelope from the proposal's reserved budget and parent limits:

```python
child = AuthorityEnvelope(
    authority_id=f"child:{child_id}",
    revision=1,
    allowed_portfolio=parent.allowed_portfolio,
    allowed_operations=parent.allowed_operations,
    budget_limit=BudgetLimit(
        controller_tokens=request.child_tokens,
        application_tokens=request.application_tokens,
        child_tokens=request.child_tokens,
        aggregate_tokens=request.aggregate_tokens,
        cost_micros=request.cost_micros,
    ),
    expires_at_ms=min(parent.expires_at_ms, now_ms + request.deadline_ms),
    max_action_deadline_ms=min(parent.max_action_deadline_ms, request.deadline_ms),
    max_recursion_depth=parent.max_recursion_depth - 1,
    max_concurrent_children=parent.max_concurrent_children,
    execution_domain=parent.execution_domain,
    host_service_grants=parent.host_service_grants,
)
```

Track child tasks by exact ID, persist their journal/root binding before create, settle parent child usage from the child's verified terminal usage and delete registry entries only after close succeeds.

- [ ] **Step 4: Run child tests to verify GREEN**

Run the Step 2 command.

Expected: PASS with no provider/model access under fakes.

- [ ] **Step 5: Commit controlled recursion**

```bash
git add src/asterion/control/children.py src/asterion/control/application_executor.py src/asterion/control/manager.py src/asterion/control/providers/prime/factory.py tests/test_control_children.py tests/test_prime_verified_loop.py
git commit -m "feat: admit recursive prime child sessions"
```

### Task 12: Prove the provider-free real-process verified loop and faults

**Files:**
- Create: `tests/test_prime_verified_loop.py`
- Create: `tests/fixtures/prime_gateway/v1/verified-loop-scenarios.json`
- Modify: `packages/typescript/prime-gateway/test/fixtures/fake-prime-daemon.mjs`
- Create: `packages/typescript/prime-gateway/test/verified-loop.test.mjs`
- Modify: `src/asterion/control/evidence.py`
- Modify: `tests/test_control_pathlight.py`

**Interfaces:**
- Stable scenario IDs: `prime-loop-application`, `prime-loop-child`, `prime-loop-detach-attach`, `prime-loop-checkpoint`, `prime-loop-gateway-crash`, `prime-loop-supervisor-crash`, `prime-loop-worker-crash`, `prime-loop-cancel`, `prime-loop-budget`, `prime-loop-redaction`.
- Each scenario records exact process/model/application operation counts plus required
  canonical Pathlight node kinds, control event types, and observation gaps.
- Provider-free fake daemon uses real sockets/processes and deterministic frames; it never contacts a model or real application provider.

- [x] **Step 1: Write the closed scenario ledger and failing harness test**

```python
def test_all_provider_free_prime_loop_scenarios_pass(self) -> None:
    results = run_prime_loop_scenarios(fake_prime=True)
    self.assertEqual(tuple(result.scenario_id for result in results), EXPECTED_IDS)
    self.assertTrue(all(result.status == "PASS" for result in results))
    self.assertEqual(sum(result.provider_operations for result in results), 0)
```

Every scenario injects `SENTINEL_PROMPT`, `SENTINEL_TOKEN`, `SENTINEL_PATH` and `SENTINEL_OUTPUT` into private locations and scans event JSON, journal, Pathlight, stdout, stderr and exception strings for absence.

- [x] **Step 2: Run harness tests to verify RED**

Run:

```bash
uv run python -m unittest -v tests.test_prime_verified_loop tests.test_control_pathlight
npm test --prefix packages/typescript/prime-gateway -- --test-name-pattern='verified loop'
```

Expected: FAIL until the scenario harness and all fault mappings exist.

- [x] **Step 3: Implement real-process orchestration and causal assertions**

Launch the compiled gateway and fake daemon in temporary private roots. Kill the named process at the persisted command, Prime admission, proposal, application start, receipt, checkpoint and replay boundaries. Require one of:

```text
no effect + safe failed/cancelled receipt
proven effect + exact succeeded receipt
unknown progress + explicit uncertain action
```

Project only canonical facts already owned by the host: `action.proposed`, the
admission decision, the terminal execution receipt, checkpoint events, and actual
provider recovery/session events. Action kind and target shape are SHA-256 digests;
identities are digested; statuses, bounded usage counts, and canonical journal
positions remain public. Child execution is evidenced by the canonical
`child.spawn` proposal/decision/receipt plus the independently observed child
sidecar process count. No test-only running, receipt, recovery, or child event is
fabricated. Observation failure adds an evidence gap and prevents the aggregate
scenario from PASS.

The application scenario additionally proves the real cross-language terminal
chain `skill bridge → Python host/system service → action.resolve → gateway
goal.updated/session.completed` after the application receipt.

- [x] **Step 4: Run provider-free verified-loop tests**

Run the two Step 2 commands.

Expected: all ten stable scenarios PASS with zero model/provider operations and no sentinel leakage.

- [x] **Step 5: Commit the provider-free loop evidence**

```bash
git add tests/test_prime_verified_loop.py tests/fixtures/prime_gateway packages/typescript/prime-gateway/test/fixtures/fake-prime-daemon.mjs packages/typescript/prime-gateway/test/verified-loop.test.mjs src/asterion/control/evidence.py tests/test_control_pathlight.py
git commit -m "test: prove the provider-free prime control loop"
```

### Task 13: Package, set up and expose bounded verification

**Files:**
- Create: `tools/setup_prime_agent.py`
- Create: `tools/verify_prime_loop.py`
- Create: `docs/guides/prime-control-operator-guide.md`
- Modify: `Makefile`
- Modify: `pyproject.toml`
- Modify: `tools/check_promotion.py`
- Modify: `tests/test_distribution.py`
- Modify: `tests/test_check_promotion.py`
- Modify: `docs/README.md`
- Modify: `README.md`

**Interfaces:**
- `setup_prime_agent.py --check --source-root PATH` verifies an exact clean Git checkout only; setup requires an explicit source root and runs `npm ci` with no model/provider operations.
- `verify_prime_loop.py --level provider-free` runs the fake real-process gate.
- `verify_prime_loop.py --level bounded --authority PATH --max-cost-micros N` rejects missing/zero/inconsistent finite authorization before Prime start.
- Make targets: `prime-check`, `prime-setup`, `prime-verify-provider-free`, `prime-verify-bounded`.

- [x] **Step 1: Write failing packaging/setup/promotion tests**

```python
def test_installed_wheel_contains_prime_manifest_skill_and_gateway_lock(self) -> None:
    members = wheel_members()
    for expected in PRIME_DISTRIBUTION_MEMBERS:
        with self.subTest(expected=expected):
            self.assertIn(expected, members)

def test_promotion_runs_prime_provider_free_but_never_bounded(self) -> None:
    source = Path("tools/check_promotion.py").read_text()
    self.assertIn("prime-verify-provider-free", source)
    self.assertNotIn("prime-verify-bounded", source)
```

Test setup against a fixture checkout for exact commit/digest, missing Git metadata, dirty tree, missing Node 22.8, failed `npm ci`, no source path in output and no inherited sentinel environment.

- [x] **Step 2: Run tests to verify RED**

Run: `uv run python -m unittest -v tests.test_distribution tests.test_check_promotion tests.test_prime_control_factory`

Expected: FAIL because packaged resources and tools are absent.

- [x] **Step 3: Implement explicit setup and verification surfaces**

The operator guide states:

```text
provider-free: no Prime source execution, model calls or application provider calls
preflight: exact external source and daemon handshake, zero model calls
bounded: one root goal, at most one application action and one child, explicit finite authority
restricted: unavailable unless execution.domain is injected and verified
```

Package Asterion-owned manifests/skill/lock explicitly. Do not package Prime source. Promotion builds the gateway, runs its provider-free tests and the ten fake scenarios from a standalone copy; it must observe zero provider operations.

- [x] **Step 4: Run distribution and promotion tests**

Run:

```bash
uv run python -m unittest -v tests.test_distribution tests.test_check_promotion tests.test_prime_control_factory
make docs-check
make promotion-check
```

Expected: PASS; promotion reports no full dataset and zero provider operations.

- [x] **Step 5: Commit setup and packaging**

```bash
git add tools/setup_prime_agent.py tools/verify_prime_loop.py docs/guides/prime-control-operator-guide.md Makefile pyproject.toml tools/check_promotion.py tests/test_distribution.py tests/test_check_promotion.py docs/README.md README.md
git commit -m "feat: package prime control verification"
```

### Task 14: Run the Phase 1 gates and record the evidence honestly

**Files:**
- Modify: `docs/status/PRIME-PARITY-LEDGER.md`
- Modify: `docs/status/INDEX.md` only if a new status document is created.
- Modify: `docs/superpowers/plans/2026-08-09-asterion-prime-parity-program.md`

**Interfaces:**
- Provider-free success records `Prime Gateway implemented` and its exact fake-loop evidence.
- `Verified-loop: PASS` requires both the provider-free gate and one separately authorized bounded real-Prime/model run with complete causal evidence.
- Full `rlm.programmatic`, `Verified-system-parity`, native `Verified-loop` and `Verified-native-parity` remain missing.

- [x] **Step 1: Run the complete provider-free Phase 1 gate**

Run:

```bash
uv run python -m unittest -v tests.test_control_file_journal tests.test_control_recovery tests.test_control_execution tests.test_control_application_executor tests.test_control_children tests.test_prime_control_client tests.test_prime_control_factory tests.test_prime_skill tests.test_prime_verified_loop tests.test_control_pathlight
npm test --prefix packages/typescript/asterion-runtime
npm test --prefix packages/typescript/prime-gateway
make test
make lint
make docs-check
make promotion-check
make check
```

Expected: PASS with provider/model operation count zero.

- [x] **Step 2: Run external Prime preflight without model work**

Run:

```bash
uv run python tools/setup_prime_agent.py --check --source-root "$ASTERION_PRIME_SOURCE_ROOT"
uv run python tools/verify_prime_loop.py --level preflight --source-root "$ASTERION_PRIME_SOURCE_ROOT"
```

Expected: exact source and daemon handshake PASS, provider/model operation count zero. Missing external source records `External-limited`, not PASS.

- [ ] **Step 3: Run the bounded real-provider gate only with explicit authorization**

Run:

```bash
uv run python tools/verify_prime_loop.py \
  --level bounded \
  --source-root "$ASTERION_PRIME_SOURCE_ROOT" \
  --authority "$ASTERION_PRIME_AUTHORITY_FILE" \
  --max-cost-micros "$ASTERION_PRIME_MAX_COST_MICROS"
```

Expected: one exact root goal proves autonomous continuation, one admitted application, one admitted child, detach/attach, checkpoint/restart, cancellation probe, budget report, terminal goal and complete Pathlight without sentinel leakage. A missing credential, authority, execution domain or required artifact records `External-limited`.

- [x] **Step 4: Update the parity ledger with exact observed commands**

Record each command, count, commit and boundary. Set `Verified-loop` to PASS only when Steps 1–3 pass on the same closure candidate. Keep `rlm.programmatic` marked partial because native Prime `rlm.run` is deliberately disabled.

- [ ] **Step 5: Commit Phase 1 closure evidence**

```bash
git add docs/status/PRIME-PARITY-LEDGER.md docs/superpowers/plans/2026-08-09-asterion-prime-parity-program.md
git commit -m "feat: verify the prime managed long running loop"
```

## Self-Review Results

- Spec coverage: exact provider binding, authority, application receipts, controlled recursion, durable journal, detach/attach, checkpoint, three process-recovery classes, cancellation, budgets, redaction, Pathlight, packaging and evidence levels each map to a named task.
- Deliberate delta: direct daemon v7 is isolated and justified; native Prime RLM is disabled until pre-admission exists. Both limitations remain visible in the ledger.
- Placeholder scan: the plan contains no deferred implementation marker; every task names files, interfaces, RED/GREEN commands, implementation behavior and commit scope.
- Type consistency: `ActionExecutionReceipt`, `PrivateContentResolver`, `PrivateResultStore`, `PrimeDaemonCursor`, `PrimeControlPlaneClient`, `ChildSessionService` and `RecoveredControlState` are introduced before later consumption.
- Cost boundary: provider-free and preflight remain zero-operation; the bounded gate requires explicit finite authorization and cannot be promoted from external-limited evidence.
