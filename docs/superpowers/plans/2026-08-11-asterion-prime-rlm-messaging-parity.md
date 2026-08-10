# Asterion Prime RLM and Messaging Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the selected Prime Gateway provider run Prime RLM children and
family messages only through Asterion-owned admission, durable lifecycle and
evidence boundaries.

**Architecture:** A source-locked, derived-bundle daemon binding shim wraps
Prime's existing native child-runtime and message controllers. Prime's Git
checkout stays clean; setup resolves the daemon entry's complete ignored local
bundle closure and applies the canonical hunk only to the exact binding chunk
after verifying every base digest. A private authenticated bridge routes
pre-effect proposals to the Gateway, while Python owns authority, budget,
durable child bindings and recovery. The native Prime delegate remains the
only producer of in-daemon `AgentSession` objects and family delivery.

**Tech Stack:** Python 3.12/unittest, TypeScript strict Node 22, Prime Agent
0.7.1 daemon 7/schema 14, Unix sockets, JSON canonicalization and real daemon
provider-free harnesses.

## Global Constraints

- Prime source commit is `a18809e00ea30638584d87b3afea7285a9d7296c`; any
  source, lock, derived-bundle base/derived digest, shim, export or anchor
  drift fails closed. The source checkout must still satisfy `git status
  --porcelain --untracked-files=normal` with no output after setup.
- Do not modify generic framework modules to import Prime code. Python owns
  authority/lifecycle; TypeScript only adapts Prime and validates bridge frames.
- The public protocols remain `asterion.agent-control/v1` and
  `asterion.session-context/v1`; `asterion.prime-rlm-host/v1` is private,
  authenticated and never manifest-configurable.
- All private text, generated source, model names, paths, active IDs, provider
  output, credentials and environment values remain private; public values are
  opaque IDs, sorted arrays, closed states, counts and SHA-256 digests only.
- No finite model authorization exists. Six provider-free features may PASS;
  `rlm.generated-program`, `rlm.child-model`, and `rlm.recursion-depth` stay
  `external-limited` until a separately named bounded run passes.
- Every effect is proposed before native effect; restart ambiguity fences the
  child binding as `uncertain`, never retries with a new identity.

---

### Task 1: Lock the daemon binding shim

**Files:**
- Create: `packages/typescript/prime-gateway/resources/prime-rlm-host-shim.patch`
- Modify: `packages/typescript/prime-gateway/resources/prime-artifact-lock.json`
- Modify: `tools/setup_prime_agent.py`
- Modify: `tools/verify_prime_loop.py`
- Test: `tests/test_setup_prime_agent.py`
- Test: `packages/typescript/prime-gateway/test/artifact-lock.test.mjs`

**Interfaces:**
- Consumes: exact Prime sources `modes/daemon/daemon-mode.ts` and
  `modes/daemon/daemon-extension-binding.ts`, plus the daemon entry's complete
  ordinary generated local ESM bundle closure rooted at
  `packages/coding-agent/dist/bundle/cli.js`.
- Produces: an idempotent `derive_prime_rlm_runtime(source_root, lock)` that
  returns the verified generated entry only after the clean source checkout,
  exact closure base bytes, canonical hunk anchors and derived closure bytes
  agree. It never writes a tracked Prime source file. The only writable member
  is the lock-named generated daemon-binding chunk.

- [ ] **Step 1: Write failing setup and lock tests**

```python
def test_rlm_host_shim_rejects_bundle_hash_or_anchor_drift(self) -> None:
    with self.assertRaisesRegex(PrimeSetupError, "Prime RLM shim is incompatible"):
        derive_prime_rlm_runtime(self.source_root, tampered_lock)

def test_rlm_host_shim_is_idempotent_only_for_exact_patched_bytes(self) -> None:
    derive_prime_rlm_runtime(self.source_root, self.lock)
    derive_prime_rlm_runtime(self.source_root, self.lock)
    self.assertEqual(clean_git_status(self.source_root), "")
```

```js
it("rejects a lock that omits the exact rlm binding patch", async () => {
  await expect(verifyPrimeArtifact(sourceRoot, invalidLock)).rejects.toThrow();
});
```

- [ ] **Step 2: Run the focused tests and observe failure**

Run: `uv run python -m unittest -v tests.test_setup_prime_agent`

Run: `npm --prefix packages/typescript/prime-gateway test -- artifact-lock.test.mjs`

Expected: FAIL because the RLM shim lock and verifier do not exist.

- [ ] **Step 3: Implement a one-binding-point patch verifier**

```python
def derive_prime_rlm_runtime(source_root: Path, lock: PrimeArtifactLock) -> Path:
    verify_prime_checkout(source_root, lock=lock)
    closure = _resolve_local_esm_closure(source_root, lock.rlm_runtime.entry)
    if _closure_sha256(closure) == lock.rlm_runtime.derived_sha256:
        return _verified_runtime_entry(source_root, lock)
    if _closure_sha256(closure) != lock.rlm_runtime.base_sha256 or not _has_anchors(closure, lock):
        raise PrimeSetupError("Prime RLM shim is incompatible")
    _atomic_replace_regular_file(lock.rlm_runtime.binding_chunk, _apply_exact_hunk(closure, lock))
    verify_prime_checkout(source_root, lock=lock)
    return _verified_runtime_entry(source_root, lock)
```

The patch must only wrap the existing native controller construction at daemon
binding time. It must call the original delegate after bridge admission; it may
not alter `AgentSession._createKernelHostHandlers`, alter model configuration,
or silently fall back to unwrapped native RLM.

The runtime hunk may modify only one ignored generated daemon-binding chunk.
Its lock has an exact entry path, a sorted local ESM closure file map, one
binding-chunk path, canonical patch-file digest, base/derived SHA-256 for each
closure member, and structural anchors derived from the two locked TypeScript
source files. A fresh ordinary build must reproduce the entire base closure
before derivation. A second derivation accepts only the exact derived closure;
a third form is rejected. `verify_prime_source` remains a source-only
clean-check verifier; `verify_prime_rlm_runtime` is the separate
derived-artifact verifier used by preflight and the real daemon harness.

- [ ] **Step 4: Re-run focused setup, source inventory and lock tests**

Run: `uv run python -m unittest -v tests.test_setup_prime_agent`

Run: `npm --prefix packages/typescript/prime-gateway test -- artifact-lock.test.mjs`

Run: `uv run python tools/check_prime_parity.py --claim inventory --source-root 3th-party/prime-agent`

Expected: PASS with one exact derived-bundle application, a clean source
checkout, and unchanged source inventory.

- [ ] **Step 5: Commit the atomic lock change**

```bash
git add tools/setup_prime_agent.py tools/verify_prime_loop.py \
  packages/typescript/prime-gateway/resources/prime-artifact-lock.json \
  packages/typescript/prime-gateway/resources/prime-rlm-host-shim.patch \
  tests/test_setup_prime_agent.py packages/typescript/prime-gateway/test/artifact-lock.test.mjs
git commit -m "feat: lock prime rlm daemon host shim"
```

### Task 2: Define the closed private RLM host bridge

**Files:**
- Create: `packages/typescript/prime-gateway/src/rlm-host-bridge.ts`
- Modify: `packages/typescript/prime-gateway/src/index.ts`
- Test: `packages/typescript/prime-gateway/test/rlm-host-bridge.test.mjs`

**Interfaces:**
- Consumes: `Gateway` action proposal/admission/terminal methods and
  `PrivateValueStore`.
- Produces: `AsterionRlmHostBridge.listen(options)`, `close()`, and exact frame
  handlers for `rlm.spawn.propose`, `rlm.child.started`,
  `rlm.child.terminal`, `rlm.message.propose`, `rlm.message.delivered`, and
  `rlm.child.delete`.

- [ ] **Step 1: Write rejecting-frame and idempotency tests**

```js
it("does not invoke the native delegate before a matching admitted spawn", async () => {
  const bridge = await AsterionRlmHostBridge.listen(options);
  await expect(request(bridge, spawnFrame)).resolves.toMatchObject({ status: "admitted" });
  expect(emitted[0].type).toBe("action.proposed");
  expect(nativeCalls).toHaveLength(0);
});

it.each([badToken, wrongSession, duplicateRequest, changedDigest])(
  "rejects bridge frame %# without an effect",
  async (frame) => expect(request(bridge, frame)).resolves.toMatchObject({ status: "error" }),
);
```

- [ ] **Step 2: Run the new focused test**

Run: `npm --prefix packages/typescript/prime-gateway test -- rlm-host-bridge.test.mjs`

Expected: FAIL because the bridge module is absent.

- [ ] **Step 3: Implement immutable frame validation and authenticated socket lifecycle**

```ts
export const RLM_HOST_PROTOCOL = "asterion.prime-rlm-host/v1" as const;

export interface RlmHostBridgeOptions {
  readonly root: string;
  readonly token: string;
  readonly sessionId: string;
  readonly generation: number;
  readonly authorityRevision: number;
  readonly emitProposal: (proposal: ControlEvent) => Promise<void>;
  readonly waitForAdmission: (actionId: string) => Promise<SkillAdmission>;
  readonly recordLifecycle: (event: RlmHostLifecycleEvent) => Promise<void>;
}
```

Use exact-key JSON objects, one request per authenticated socket, 64 KiB maximum
frames, constant-time token comparison, mode `0600` socket/discovery metadata,
canonical request digests, and a per-action digest map. Return only closed
reason codes and public-safe identifiers. Close and remove the socket before
the sidecar declares itself closed.

- [ ] **Step 4: Run bridge test and TypeScript compilation**

Run: `npm --prefix packages/typescript/prime-gateway test -- rlm-host-bridge.test.mjs`

Run: `npm --prefix packages/typescript/prime-gateway run check`

Expected: PASS.

- [ ] **Step 5: Commit the private bridge**

```bash
git add packages/typescript/prime-gateway/src/rlm-host-bridge.ts \
  packages/typescript/prime-gateway/src/index.ts \
  packages/typescript/prime-gateway/test/rlm-host-bridge.test.mjs
git commit -m "feat: add private prime rlm host bridge"
```

### Task 3: Add shim delegates for native children and messages

**Files:**
- Create: `packages/typescript/prime-gateway/resources/rlm-host-shim.mjs`
- Modify: `packages/typescript/prime-gateway/src/main.ts`
- Modify: `packages/typescript/prime-gateway/src/skill-bridge.ts`
- Test: `packages/typescript/prime-gateway/test/main.test.mjs`
- Test: `packages/typescript/prime-gateway/test/skill-bridge.test.mjs`

**Interfaces:**
- Consumes: bridge discovery record, original Prime `SubagentRuntimeHost` and
  `AgentSessionMessageController` delegates.
- Produces: `wrapSubagentRuntimeHost(delegate, client)` and
  `wrapAgentMessageController(delegate, client)`.

- [ ] **Step 1: Write native-delegate ordering tests**

```js
it("calls the native child host exactly once only after bridge admission", async () => {
  const wrapped = wrapSubagentRuntimeHost(nativeHost, bridgeClient);
  await expect(wrapped.createRlmSubagentRuntime(options)).resolves.toEqual(nativeRuntime);
  expect(order).toEqual(["propose", "admitted", "native-create", "started"]);
});

it("rejects a family message before native delivery and redacts its body", async () => {
  await expect(wrapped.sendAgentMessage({ target: "sibling", message: secret })).rejects.toThrow();
  expect(nativeMessages).toHaveLength(0);
  expect(publicEvents).not.toContain(secret);
});
```

- [ ] **Step 2: Run shim-related Gateway tests**

Run: `npm --prefix packages/typescript/prime-gateway test -- main.test.mjs skill-bridge.test.mjs`

Expected: FAIL because the shim has no wrapper.

- [ ] **Step 3: Implement delegate-preserving wrappers**

```ts
export function wrapSubagentRuntimeHost(
  delegate: SubagentRuntimeHost,
  client: RlmHostBridgeClient,
): SubagentRuntimeHost {
  return {
    async createRlmSubagentRuntime(options) {
      const binding = await client.admitSpawn(canonicalSpawn(options));
      const runtime = await delegate.createRlmSubagentRuntime(options);
      await client.recordStarted(binding, runtime.session);
      return runtime;
    },
    completeRlmSubagentRuntime: (id, session) => delegate.completeRlmSubagentRuntime?.(id, session) ?? true,
    releaseRlmSubagentRuntime: (runtime, options, status) => client.release(delegate, runtime, options, status),
    deleteRlmSubagentRuntime: (id, session) => client.delete(delegate, id, session),
    disposeRlmSubagentRuntimes: () => client.dispose(delegate),
  };
}
```

The message wrapper first delegates roster/name checks, then sends only the
body digest/public identities to the lifecycle journal. It must preserve
Prime's `delivered` versus `queued` receipt and native parent terminal notices.

- [ ] **Step 4: Run ordering, close, redaction and cross-language tests**

Run: `npm --prefix packages/typescript/prime-gateway test -- main.test.mjs skill-bridge.test.mjs rlm-host-bridge.test.mjs`

Expected: PASS.

- [ ] **Step 5: Commit shim integration**

```bash
git add packages/typescript/prime-gateway/resources/rlm-host-shim.mjs \
  packages/typescript/prime-gateway/src/main.ts packages/typescript/prime-gateway/src/skill-bridge.ts \
  packages/typescript/prime-gateway/test/main.test.mjs packages/typescript/prime-gateway/test/skill-bridge.test.mjs
git commit -m "feat: admit prime rlm children and messages"
```

### Task 4: Add provider-neutral RLM lifecycle contracts

**Files:**
- Create: `src/asterion/control/rlm.py`
- Modify: `src/asterion/control/authority.py`
- Modify: `src/asterion/control/protocol.py`
- Test: `tests/test_rlm.py`
- Test: `tests/test_authority.py`

**Interfaces:**
- Produces: immutable `RlmChildBinding`, `RlmChildStatus`, `RlmMessageReceipt`,
  `RlmLifecycleEvent`, and `RlmChildService`.
- Consumes: `AuthorityEnvelope`, `AuthorityLedger`, canonical journal and
  host-owned private resolver.

- [ ] **Step 1: Write failing validation and monotonic-state tests**

```python
def test_rlm_binding_rejects_private_native_identity_and_noncanonical_digest(self) -> None:
    with self.assertRaisesRegex(RlmError, "RLM child binding is invalid"):
        RlmChildBinding("child-1", "session-1", 0, "not-a-digest")

def test_rlm_terminal_cannot_regress_started_or_reuse_child_after_uncertainty(self) -> None:
    service.record_started(binding, private_identity)
    service.record_uncertain(binding)
    with self.assertRaisesRegex(RlmError, "RLM child is fenced"):
        service.admit(binding, request)
```

- [ ] **Step 2: Run the focused Python tests**

Run: `uv run python -m unittest -v tests.test_rlm tests.test_authority`

Expected: FAIL because RLM contracts do not exist.

- [ ] **Step 3: Implement closed authority and lifecycle types**

```python
RLM_OPERATIONS = frozenset({"rlm.child.spawn", "rlm.child.message", "rlm.child.delete"})

@dataclass(frozen=True)
class RlmChildBinding:
    child_id: str
    parent_session_id: str
    authority_revision: int
    proposal_digest: str
    depth: int
    model_selector_digest: str
```

Extend `AuthorityEnvelope` only by admitting these exact operation IDs into its
closed operation set. Validate depth, direct parent identity, canonical model
selector digest, finite `BudgetRequest`, concurrency and idempotency before
recording an `admitted` transition. Persist private Prime identities outside
the public binding and expose no private fields through `to_mapping()`.

- [ ] **Step 4: Run type, immutability and hostile-input matrices**

Run: `uv run python -m unittest -v tests.test_rlm tests.test_authority`

Run: `uv run pyright src/asterion/control/rlm.py src/asterion/control/authority.py`

Expected: PASS with zero Pyright errors.

- [ ] **Step 5: Commit the neutral RLM contract**

```bash
git add src/asterion/control/rlm.py src/asterion/control/authority.py \
  src/asterion/control/protocol.py tests/test_rlm.py tests/test_authority.py
git commit -m "feat: add authoritative rlm child lifecycle"
```

### Task 5: Integrate RLM lifecycle with the control host and Prime client

**Files:**
- Modify: `src/asterion/control/host.py`
- Modify: `src/asterion/control/providers/prime/client.py`
- Modify: `src/asterion/control/providers/prime/factory.py`
- Modify: `src/asterion/control/providers/prime/process.py`
- Modify: `packages/typescript/prime-gateway/src/main.ts`
- Test: `tests/test_control_host.py`
- Test: `tests/test_prime_client.py`

**Interfaces:**
- Consumes: `RlmChildService`, sidecar `rlm-host` frames and existing exact
  sidecar descriptor.
- Produces: host admission/terminal routing for RLM lifecycle events and a
  client capability `rlm.programmatic-v1` selected only by exact manifest.

- [ ] **Step 1: Write host ordering and capability-mismatch tests**

```python
async def test_host_persists_rlm_admission_before_gateway_can_create_child(self) -> None:
    await client.emit_rlm_spawn(proposal)
    self.assertEqual(journal.events[-1].type, "action.resolved")
    self.assertFalse(native_child_created_before_admission)

def test_rlm_extension_requires_declared_capability_and_structural_client(self) -> None:
    with self.assertRaisesRegex(ControlHostError, "RLM extension is unavailable"):
        build_host(client_without_rlm_capability)
```

- [ ] **Step 2: Run focused host/client tests**

Run: `uv run python -m unittest -v tests.test_control_host tests.test_prime_client`

Expected: FAIL because no RLM sidecar event is recognized.

- [ ] **Step 3: Wire exact private sidecar events**

```python
async def handle_rlm_lifecycle(self, event: RlmLifecycleEvent) -> RlmBridgeResolution:
    if event.kind == "rlm.spawn.propose":
        return await self._rlm_children.admit(event, self._cancellation_signal)
    if event.kind == "rlm.child.terminal":
        return await self._rlm_children.record_terminal(event)
    raise ControlHostError("RLM lifecycle event is invalid")
```

Add `rlmHostShimPath` and its fixed digest to the private descriptor. The
factory resolves only packaged resources; the process allowlist forwards no
model/credential environment to the shim. Existing session clients without the
declared capability keep native RLM disabled at depth zero.

- [ ] **Step 4: Run host/client/restart tests**

Run: `uv run python -m unittest -v tests.test_control_host tests.test_prime_client tests.test_package_execution`

Expected: PASS; failure after native effect is recovery-required, not retry.

- [ ] **Step 5: Commit host/Gateway integration**

```bash
git add src/asterion/control/host.py src/asterion/control/providers/prime/client.py \
  src/asterion/control/providers/prime/factory.py src/asterion/control/providers/prime/process.py \
  packages/typescript/prime-gateway/src/main.ts tests/test_control_host.py tests/test_prime_client.py
git commit -m "feat: route prime rlm lifecycle through host authority"
```

### Task 6: Cover registry, family messaging, cancellation and recovery

**Files:**
- Modify: `src/asterion/control/rlm.py`
- Modify: `src/asterion/control/children.py`
- Test: `tests/test_rlm.py`
- Test: `tests/test_children.py`
- Test: `packages/typescript/prime-gateway/test/rlm-host-bridge.test.mjs`

**Interfaces:**
- Produces: sorted public child registry projection; directional message
  receipts; fenced cancellation/delete/recovery transitions.

- [ ] **Step 1: Write failure-matrix tests**

```python
def test_message_rejects_non_family_target_without_disclosing_selector(self) -> None:
    with self.assertRaisesRegex(RlmError, "RLM message target is unavailable"):
        self.service.admit_message(self.non_family_message)
    self.assertNotIn("outside-agent", self.service.public_events())

async def test_parent_close_cancels_native_children_and_reports_no_orphan_only_when_proven(self) -> None:
    await self.service.admit_and_start(self.binding)
    await self.service.close()
    self.assertEqual(self.native_audit.live_child_pids(), ())
    self.assertEqual(self.service.status(self.binding.child_id).status, "cancelled")

async def test_restart_after_started_but_before_terminal_is_uncertain_and_not_replayed(self) -> None:
    await self.service.admit_and_start(self.binding)
    recovered = self.reopen_after("native-terminal-before-journal")
    self.assertEqual(recovered.status(self.binding.child_id).status, "uncertain")
    with self.assertRaisesRegex(RlmError, "RLM child is fenced"):
        await recovered.admit(self.binding, self.request)
```

- [ ] **Step 2: Run focused lifecycle tests**

Run: `uv run python -m unittest -v tests.test_rlm tests.test_children`

Expected: FAIL for unimplemented family-message and crash windows.

- [ ] **Step 3: Implement exact lifecycle transitions**

```python
ALLOWED_TRANSITIONS = {
    "proposed": {"admitted", "rejected", "uncertain"},
    "admitted": {"started", "cancelled", "uncertain"},
    "started": {"completed", "failed", "cancelled", "uncertain"},
}
```

Require parent/child/sibling relationship proofs from the native delegate,
sort registry output by child ID, and bind every message digest to distinct
sender and recipient opaque IDs. Cancellation/deletion must journal its fence
before delegate invocation and run a child-process audit before claiming a
clean terminal state.

- [ ] **Step 4: Re-run matrices and redaction scan**

Run: `uv run python -m unittest -v tests.test_rlm tests.test_children`

Run: `npm --prefix packages/typescript/prime-gateway test -- rlm-host-bridge.test.mjs`

Expected: PASS with sentinel prompts/messages absent from all public outputs.

- [ ] **Step 5: Commit lifecycle completion**

```bash
git add src/asterion/control/rlm.py src/asterion/control/children.py \
  tests/test_rlm.py tests/test_children.py packages/typescript/prime-gateway/test/rlm-host-bridge.test.mjs
git commit -m "feat: fence prime rlm messaging and teardown"
```

### Task 7: Build real Prime provider-free RLM harnesses

**Files:**
- Create: `tests/fixtures/prime_gateway/v1/real-prime-rlm-messaging.mjs`
- Create: `tests/test_prime_rlm_messaging_parity.py`
- Modify: `src/asterion/control/providers/prime/parity_testing.py`
- Modify: `Makefile`
- Test: `tests/test_prime_rlm_messaging_parity.py`

**Interfaces:**
- Produces: `test.prime-rlm-messaging-parity.provider-free`, exactly six real
  provider-free scenario observations and no evidence for diagnostics/fakes.

- [ ] **Step 1: Write the failing exact scenario contract test**

```python
def test_real_rlm_harness_registers_exact_provider_free_matrix(self) -> None:
    self.assertEqual(RLM_PROVIDER_FREE_SCENARIOS, frozenset({
        "prime-parity.rlm.environment", "prime-parity.rlm.messaging",
        "prime-parity.rlm.registry-lifecycle", "prime-parity.rlm.cancellation-teardown",
        "prime-parity.rlm.recovery", "prime-parity.rlm.usage-cost",
    }))
```

- [ ] **Step 2: Run it and verify the missing harness fails**

Run: `uv run python -m unittest -v tests.test_prime_rlm_messaging_parity`

Expected: FAIL because the real harness does not exist.

- [ ] **Step 3: Implement the closed-HOME real-daemon fixture**

```js
const observation = Object.freeze({
  protocol: "asterion.prime-rlm-observation/v1",
  provider_operations: 0,
  credential_reads: 0,
  source_verified: true,
  child_processes_after_teardown: 0,
});
```

The fixture must create a harmless persistent kernel variable, exercise
admitted faux/no-provider child creation, direct family messages, registry
list/delete, cancellation, restart fences and monotonic zero usage. It emits
only expected assertion/fault IDs, public digests and safe counters. It does
not print model output, source, prompts, path, socket or credentials.

- [ ] **Step 4: Run the named provider-free target**

Run: `make test.prime-rlm-messaging-parity.provider-free`

Expected: PASS; real pinned daemon; six observations; zero credential/model
provider operations; no orphan children.

- [ ] **Step 5: Commit real provider-free harnesses**

```bash
git add Makefile src/asterion/control/providers/prime/parity_testing.py \
  tests/fixtures/prime_gateway/v1/real-prime-rlm-messaging.mjs \
  tests/test_prime_rlm_messaging_parity.py
git commit -m "test: verify prime rlm messaging provider-free parity"
```

### Task 8: Bind evidence and preserve bounded honesty

**Files:**
- Modify: `tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json`
- Modify: `tests/test_prime_parity_conformance.py`
- Modify: `tests/test_prime_parity_ledger.py`
- Modify: `tests/test_check_prime_parity.py`
- Modify: `tools/check_prime_parity.py`

**Interfaces:**
- Produces: one-to-one evidence for six PASS features and exactly three
  `external-limited` bounded RLM features with selection-specific reasons.

- [ ] **Step 1: Write failing evidence-matrix assertions**

```python
def test_rlm_ledger_has_six_real_passes_and_three_external_limited_features(self) -> None:
    self.assertEqual(report.passed_feature_ids, EXPECTED_RLM_PROVIDER_FREE_FEATURES)
    self.assertEqual(report.external_limited_feature_ids, EXPECTED_RLM_BOUNDED_FEATURES)
```

- [ ] **Step 2: Run ledger and checker tests**

Run: `uv run python -m unittest -v tests.test_prime_parity_conformance tests.test_prime_parity_ledger tests.test_check_prime_parity`

Expected: FAIL until exact scenario/evidence records exist.

- [ ] **Step 3: Register only exact evidence**

Each primary scenario has its ledger assertion/fault IDs, one evidence record,
the named Make command, source lock digest, `provider_operations: 0`, and
`credential_reads: 0`. The three bounded scenarios each have one explicit
`external-limited` record stating that finite model authorization is absent;
no fake or policy-rejection record supplies PASS evidence.

- [ ] **Step 4: Run domain and full claims**

Run: `uv run python tools/check_prime_parity.py --domain rlm.programmatic --provider asterion.prime-gateway`

Expected: exit 1 with six PASS and exactly the three bounded blockers.

Run: `uv run python tools/check_prime_parity.py --provider asterion.prime-gateway`

Expected: exit 1; RLM adds no unrelated or hidden claim.

- [ ] **Step 5: Commit evidence closure**

```bash
git add tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json \
  tests/test_prime_parity_conformance.py tests/test_prime_parity_ledger.py \
  tests/test_check_prime_parity.py tools/check_prime_parity.py
git commit -m "test: bind prime rlm parity evidence"
```

### Task 9: Verify, review and update durable state

**Files:**
- Modify: `docs/superpowers/plans/2026-08-10-asterion-prime-system-parity.md`
- Modify: `docs/superpowers/plans/2026-08-11-asterion-prime-rlm-messaging-parity.md`
- Modify after commits only: `docs/status/JOURNAL.md`, `docs/status/RESUME-NEXT-SESSION.md`

- [ ] **Step 1: Run all provider-free and project gates**

```bash
make test.prime-rlm-messaging-parity.provider-free
make test
make lint
make docs-check
make test-typescript
make check-rust
make build
make promotion-check
```

Expected: all commands PASS with zero model-provider operations. Run focused
Pyright for every changed Python surface and `git diff --check`.

- [ ] **Step 2: Run an independent code review**

Review must check exact patch locking, pre-effect ordering, private-frame
authentication, native delegate single-call behavior, child orphan audit,
recovery fencing, one-to-one evidence and bounded-status honesty. Resolve any
finding with focused regression tests before promotion.

- [ ] **Step 3: Update plan status and commit verification artifacts**

```bash
git add docs/superpowers/plans/2026-08-10-asterion-prime-system-parity.md \
  docs/superpowers/plans/2026-08-11-asterion-prime-rlm-messaging-parity.md
git commit -m "test: verify prime rlm messaging parity"
```

- [ ] **Step 4: Record durable state without staging status files**

Append one Chinese journal line of at most 20 words with the real commit hash,
then rewrite the live recovery checkpoint for parent Task 6. Keep
`docs/status/` uncommitted and preserve unrelated worktree edits.
