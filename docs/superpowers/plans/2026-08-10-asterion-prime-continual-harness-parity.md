# Asterion Prime Continual Harness Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close all eight mandatory `harness.continual` Prime Gateway scenarios through an Asterion-owned revision kernel, seven real-Prime provider-free evidence records, and one separately authorized bounded evidence-refinement record.

**Architecture:** Python owns closed harness values, authority checks, append-only revisions, snapshot reduction, rollback, recovery, private references, and evidence. TypeScript owns exact validation and invocation of the pinned Prime refinement module plus durable provider-effect fencing. The selected Prime adapter translates already admitted effects and returns body-free receipts; it never chooses scope, authority, evidence, model, or activation.

**Tech Stack:** Python 3.12 dataclasses/protocols/unittest, the existing `CanonicalJournal` and private-store contracts, TypeScript 5/Node 22/node:test, pinned Prime Agent 0.7.1 refinement exports, Make, and the existing parity ledger/reducer.

## Global Constraints

- Preserve `CLI/host → selected provider → assembly → exact implementation → runner/runtime` dependency direction.
- Framework modules remain domain-neutral and never import Prime, DCI, tests, or adjacent source trees.
- Do not change `asterion.agent-control/v1`; harness journal records and private Gateway requests are internal closed contracts.
- Session, project, and global scopes are explicit. Never infer scope or roots from cwd, environment, body text, or provider cache.
- Manifests contain no bodies, prompts, credentials, commands, executable paths, provider configuration, mutable revisions, or private roots.
- Public values contain only canonical identities, digests, kinds, versions, statuses, counts, and safe usage.
- Provider-free commands read zero model credentials, perform zero provider operations, and leave no owned process.
- `harness.evidence-refinement` requires a new explicit finite authorization: at most one provider operation, a positive token cap, a nonnegative micro-cost cap, and a hard deadline.
- Prior long-running/RLM receipts and the user's earlier bounded authorization do not authorize the continual-harness bounded run.
- Follow TDD for every task. Use `unittest` and `node:test`; never promote fake-adapter diagnostics to parity evidence.
- `asterion.native` remains `missing` throughout this plan.

---

### Task 1: Add closed provider-neutral harness values

**Files:**
- Create: `src/asterion/control/harness.py`
- Modify: `src/asterion/control/__init__.py`
- Create: `tests/test_control_harness.py`

**Interfaces:**
- Consumes: `OPAQUE_ID` from `asterion.control.protocol` and canonical JSON/digest conventions already used by control records.
- Produces: `HarnessScope`, `HarnessEntryDescriptor`, `HarnessEdit`, `HarnessProposal`, `HarnessRevision`, `HarnessSnapshot`, `HarnessEffectReceipt`, and `HarnessError`.

- [x] **Step 1: Write failing closed-value and redaction tests**

Add tests that construct all three scopes and four entry kinds, reject extra or malformed identities, require sorted unique evidence IDs, recursively freeze descriptors, keep private fields out of `repr`, and verify deterministic digests:

```python
class TestHarnessValues(unittest.TestCase):
    def test_scopes_are_exact_and_disjoint(self) -> None:
        self.assertEqual(HarnessScope.session("session-1").key, "session:session-1")
        self.assertEqual(HarnessScope.project("project-1").key, "project:project-1")
        self.assertEqual(HarnessScope.global_scope().key, "global")
        with self.assertRaisesRegex(HarnessError, "scope is invalid"):
            HarnessScope("global", "project-1")

    def test_entry_descriptor_is_closed_immutable_and_body_free(self) -> None:
        entry = HarnessEntryDescriptor(
            entry_id="memory-1",
            kind="memory",
            title_digest="a" * 64,
            body_ref="private:memory-1",
            body_digest="b" * 64,
            grouping_path_digest=None,
            metadata_digest="c" * 64,
            version=1,
        )
        self.assertNotIn("private:memory-1", repr(entry))
        self.assertEqual(entry.to_public_mapping()["body_digest"], "b" * 64)
        self.assertNotIn("body_ref", entry.to_public_mapping())
        with self.assertRaises(FrozenInstanceError):
            entry.version = 2

    def test_proposal_digest_binds_scope_baseline_edits_and_evidence(self) -> None:
        proposal = _proposal(evidence_ids=("evidence-1", "evidence-2"))
        self.assertRegex(proposal.digest, r"^[0-9a-f]{64}$")
        with self.assertRaisesRegex(HarnessError, "proposal is invalid"):
            _proposal(evidence_ids=("evidence-2", "evidence-1"))
```

- [x] **Step 2: Run tests to verify the module is missing**

Run: `uv run python -m unittest -v tests.test_control_harness`

Expected: FAIL because `asterion.control.harness` does not exist.

- [x] **Step 3: Implement exact immutable types**

Use these exact literal sets:

```python
HarnessScopeKind = Literal["session", "project", "global"]
HarnessEntryKind = Literal["prompt", "memory", "skill", "subagent"]
HarnessEditAction = Literal["create", "update", "delete"]
HarnessTerminalStatus = Literal["succeeded", "failed", "cancelled", "uncertain"]

@dataclass(frozen=True)
class HarnessScope:
    kind: HarnessScopeKind
    scope_id: str | None

@dataclass(frozen=True, repr=False)
class HarnessEntryDescriptor:
    entry_id: str
    kind: HarnessEntryKind
    title_digest: str
    body_ref: str
    body_digest: str
    grouping_path_digest: str | None
    metadata_digest: str
    version: int

@dataclass(frozen=True)
class HarnessEdit:
    action: HarnessEditAction
    entry_id: str
    expected_version: int | None
    replacement: HarnessEntryDescriptor | None

@dataclass(frozen=True, repr=False)
class HarnessProposal:
    proposal_id: str
    authority_id: str
    authority_revision: int
    scope: HarnessScope
    baseline_snapshot_id: str
    edits: tuple[HarnessEdit, ...]
    evidence_ids: tuple[str, ...]
    rationale_ref: str
    rationale_digest: str
    expected_outcome_digest: str
```

Implement these methods with the listed return types: `HarnessScope.session(str) -> HarnessScope`, `HarnessScope.project(str) -> HarnessScope`, `HarnessScope.global_scope() -> HarnessScope`, `HarnessScope.key -> str`, `HarnessScope.digest -> str`, `HarnessScope.to_mapping() -> Mapping[str, object]`, `HarnessEntryDescriptor.to_public_mapping() -> Mapping[str, object]`, and `HarnessProposal.digest -> str`.

Implement the remaining frozen values with these exact fields:

- `HarnessRevision`: `revision_id`, `sequence`, `proposal_id`, `proposal_digest`, `scope`, `baseline_snapshot_id`, `result_snapshot_id`, `effect_digest`, `status`, `rollback_revision_id`, and `usage`.
- `HarnessSnapshot`: `snapshot_id`, `scope`, `revision_id`, `sequence`, `entries`, and `pending_status`.
- `HarnessEffectReceipt`: `proposal_id`, `proposal_digest`, `effect_digest`, `status`, `result_entries`, and `usage`.

Copy all input containers before freezing, use canonical sorted-key JSON for SHA-256 identities, reject booleans as integers, and raise only fixed `HarnessError` messages without exception chaining. Provide named `HarnessEffectReceipt.succeeded()`, `.failed()`, `.cancelled()`, and `.uncertain()` constructors so callers cannot manufacture an unsupported terminal status.

- [x] **Step 4: Export the public provider-neutral values and rerun tests**

Add the new values to `src/asterion/control/__init__.py` and `__all__`.

Run: `uv run python -m unittest -v tests.test_control_harness`

Expected: PASS with no private sentinel in test output.

- [x] **Step 5: Commit the closed value layer**

```bash
git add src/asterion/control/harness.py src/asterion/control/__init__.py tests/test_control_harness.py
git commit -m "feat: add continual harness value contracts"
```

---

### Task 2: Add append-only revision coordination and recovery

**Files:**
- Modify: `src/asterion/control/journal.py`
- Modify: `src/asterion/control/harness.py`
- Modify: `tests/test_control_harness.py`
- Modify: `tests/test_control_journal.py`

**Interfaces:**
- Consumes: Task 1 values, `CanonicalJournal`, `JournalRecord`, `JournalCursor`, an injected effect sender, and an injected host-private revision store for references forbidden from public journal payloads.
- Produces: `HarnessEffectSender`, `HarnessPrivateRevisionStore`, `MemoryHarnessPrivateRevisionStore`, `HarnessCoordinator.apply()`, `HarnessCoordinator.rollback()`, `HarnessCoordinator.recover()`, and five validated journal record kinds.

- [x] **Step 1: Write failing persist-before-effect and recovery tests**

Cover create/update/delete, exact expected-version conflicts, scope mismatch, replay, transport uncertainty, activation recovery, and monotonic rollback:

```python
class TestHarnessCoordinator(unittest.TestCase):
    def test_proposal_and_effect_start_are_durable_before_send(self) -> None:
        journal = _journal("harness-session")

        def send(proposal: HarnessProposal) -> HarnessEffectReceipt:
            kinds = tuple(item.record.kind for item in journal.replay(JournalCursor(0)))
            self.assertEqual(kinds[-2:], ("harness.proposed", "harness.effect-started"))
            return HarnessEffectReceipt.succeeded(proposal, effect_digest="d" * 64)

        receipt = HarnessCoordinator(journal, HarnessScope.session("session-1"), send).apply(
            _proposal(action="create")
        )
        self.assertEqual(receipt.status, "succeeded")

    def test_transport_loss_fences_replay_as_uncertain(self) -> None:
        journal = _journal("harness-session")
        first = HarnessCoordinator(journal, HarnessScope.session("session-1"), _lose_transport)
        self.assertEqual(first.apply(_proposal()).status, "uncertain")
        reopened = HarnessCoordinator(journal, HarnessScope.session("session-1"), self.fail)
        self.assertEqual(reopened.recover().pending_status, "uncertain")

    def test_rollback_creates_a_new_revision_and_preserves_history(self) -> None:
        coordinator = _coordinator()
        original = coordinator.apply(_proposal(action="create"))
        rollback = coordinator.rollback(
            proposal_id="proposal-rollback",
            authority_id="authority-1",
            authority_revision=1,
            target_revision_id=original.revision_id,
            rationale_ref="private:rollback",
            rationale_digest="e" * 64,
            expected_outcome_digest="f" * 64,
        )
        self.assertGreater(rollback.sequence, original.sequence)
        self.assertEqual(rollback.rollback_revision_id, original.revision_id)
        self.assertEqual(len(coordinator.history()), 2)
```

- [x] **Step 2: Run focused tests and observe missing coordinator/record failures**

Run: `uv run python -m unittest -v tests.test_control_harness tests.test_control_journal`

Expected: FAIL on missing harness record kinds and `HarnessCoordinator`.

- [x] **Step 3: Add the closed journal vocabulary**

Extend `JOURNAL_RECORD_KINDS` with exactly:

```python
"harness.proposed",
"harness.effect-started",
"harness.effect-terminal",
"harness.snapshot-activated",
"harness.effect-uncertain",
```

Add `JournalRecord.harness_proposed()`, `harness_effect_started()`, `harness_effect_terminal()`, `harness_snapshot_activated()`, and `harness_effect_uncertain()` factories. Payloads contain only scope mapping, proposal/revision/snapshot identities, digests, sequence, status, and safe usage. Validate exact fields and forbid private refs in journal payloads.

- [x] **Step 4: Implement the coordinator and reducer**

Use these exact interfaces: `HarnessEffectSender.__call__(HarnessProposal) -> HarnessEffectReceipt`; `HarnessPrivateRevisionStore.save_proposal/load_proposal/save_snapshot/load_snapshot`; `HarnessCoordinator.__init__(CanonicalJournal, HarnessScope, HarnessEffectSender, CancellationSignal | None, HarnessPrivateRevisionStore | None)`; `apply(HarnessProposal) -> HarnessRevision`; keyword-only `rollback(proposal_id: str, authority_id: str, authority_revision: int, target_revision_id: str, rationale_ref: str, rationale_digest: str, expected_outcome_digest: str) -> HarnessRevision`; `recover() -> HarnessSnapshot`; `snapshot() -> HarnessSnapshot`; and `history() -> tuple[HarnessRevision, ...]`. Define `HarnessTransportError` as the sole post-send transport-loss signal.

The reducer must enforce one scope, contiguous journal positions, exact proposal/effect digest binding, monotonic sequence, one terminal per revision, no retry after uncertain, and activation only after a durable successful terminal. Rollback derives inverse edits from stored descriptor identities; it never mutates old records.

- [x] **Step 5: Run coordinator, journal, immutability, and file-reopen tests**

Run: `uv run python -m unittest -v tests.test_control_harness tests.test_control_journal`

Expected: PASS, including `FileCanonicalJournal` close/reopen recovery and sentinel redaction.

- [x] **Step 6: Commit the revision kernel**

```bash
git add src/asterion/control/harness.py src/asterion/control/journal.py tests/test_control_harness.py tests/test_control_journal.py
git commit -m "feat: add continual harness revision kernel"
```

---

### Task 3: Add the selected Prime Python adapter

**Files:**
- Create: `src/asterion/control/providers/prime/harness.py`
- Modify: `src/asterion/control/providers/prime/__init__.py`
- Create: `tests/test_prime_continual_harness.py`

**Interfaces:**
- Consumes: admitted `HarnessProposal`, an injected `PrimeContinualHarnessClient`, and body values resolved privately by the host.
- Produces: `PrimeHarnessScope`, `PrimeHarnessEdit`, `PrimeHarnessEffect`, `PrimeHarnessIpcReceipt`, and `PrimeContinualHarnessService.apply()`.

- [x] **Step 1: Write failing exact-translation and drift tests**

```python
class TestPrimeContinualHarnessService(unittest.TestCase):
    def test_project_scope_uses_a_dedicated_local_projection(self) -> None:
        client = _RecordingClient()
        receipt = PrimeContinualHarnessService(client).apply(
            _proposal(scope=HarnessScope.project("project-1")),
            bodies=_PrivateBodies(),
        )
        self.assertEqual(client.effects[0].prime_scope, "local")
        self.assertEqual(client.effects[0].scope_digest, HarnessScope.project("project-1").digest)
        self.assertEqual(receipt.status, "succeeded")

    def test_adapter_rejects_receipt_identity_drift(self) -> None:
        with self.assertRaisesRegex(PrimeHarnessError, "receipt is invalid"):
            PrimeContinualHarnessService(_DriftingClient()).apply(
                _proposal(), bodies=_PrivateBodies()
            )

    def test_skill_and_subagent_entries_remain_declarative(self) -> None:
        client = _RecordingClient()
        PrimeContinualHarnessService(client).apply(_skill_and_subagent_proposal(), _PrivateBodies())
        self.assertEqual(client.import_count, 0)
        self.assertEqual(client.spawn_count, 0)
```

- [x] **Step 2: Run tests and observe the missing adapter**

Run: `uv run python -m unittest -v tests.test_prime_continual_harness`

Expected: FAIL because the selected Prime harness adapter does not exist.

- [x] **Step 3: Implement closed private translation**

Use these exact protocols: `PrimeContinualHarnessClient.apply_harness_effect(PrimeHarnessEffect) -> PrimeHarnessIpcReceipt`; `PrimeContinualHarnessClient.read_harness_snapshot(PrimeHarnessScope) -> Mapping[str, object]`; and `PrimePrivateHarnessBodies.resolve_text(str) -> str`. The service exposes `__init__(PrimeContinualHarnessClient)`, `apply(HarnessProposal, PrimePrivateHarnessBodies) -> HarnessEffectReceipt`, and `reconcile(HarnessProposal, HarnessSnapshot) -> HarnessEffectReceipt`.

Translate session/project scopes to distinct Prime local roots identified only by a scope digest; translate global to the selected provider global root. Resolve bodies immediately before IPC, preserve edit order and expected versions, reject base-system-prompt identities, and compare proposal/effect digests on return. Map transport loss after send to `HarnessTransportError`; never retry in the adapter.

- [x] **Step 4: Run adapter tests and public sentinel scan**

Run: `uv run python -m unittest -v tests.test_prime_continual_harness`

Expected: PASS with no private title/body/path/model value in any mapping, `repr`, or exception.

- [x] **Step 5: Commit the selected-provider adapter**

```bash
git add src/asterion/control/providers/prime/harness.py src/asterion/control/providers/prime/__init__.py tests/test_prime_continual_harness.py
git commit -m "feat: add Prime continual harness adapter"
```

---

### Task 4: Add the TypeScript Prime projection and durable effect fence

**Files:**
- Create: `packages/typescript/prime-gateway/src/continual-harness.ts`
- Modify: `packages/typescript/prime-gateway/src/durable-store.ts`
- Modify: `packages/typescript/prime-gateway/src/index.ts`
- Create: `packages/typescript/prime-gateway/test/continual-harness.test.mjs`

**Interfaces:**
- Consumes: exact private effect frames from Task 3 and an injected pinned Prime refinement module.
- Produces: `PrimeContinualHarnessAdapter`, `PrimeHarnessModule`, `GatewayHarnessEffectBinding`, and `GatewayHarnessEffectResult`.

- [x] **Step 1: Write failing closed-frame, fencing, and restart tests**

```javascript
test("binds an exact harness effect before applying Prime edits", async () => {
  await withStore(async (root, store) => {
    const PRIVATE_SENTINEL = "SENTINEL_PRIVATE_HARNESS_BODY";
    const module = fakePrimeRefinementModule();
    const adapter = new PrimeContinualHarnessAdapter({ store, module });
    const receipt = await adapter.apply(validHarnessEffect());
    assert.equal(module.applyCalls, 1);
    assert.equal(receipt.status, "succeeded");
    assert.deepEqual(store.harnessEffectResult(receipt.effectId), receipt);
    assert.equal(JSON.stringify(store.snapshot()).includes(PRIVATE_SENTINEL), false);
    const reopened = await GatewayDurableStore.open(root, "session-1");
    assert.deepEqual(reopened.harnessEffectResult(receipt.effectId), receipt);
  });
});

test("reopen fences an uncommitted effect without applying twice", async () => {
  await withStore(async (root, store) => {
    await store.bindHarnessEffect(validHarnessEffect());
    const reopened = await GatewayDurableStore.open(root, "session-1");
    const module = fakePrimeRefinementModule();
    const receipt = await new PrimeContinualHarnessAdapter({ store: reopened, module })
      .apply(validHarnessEffect());
    assert.equal(module.applyCalls, 0);
    assert.equal(receipt.status, "uncertain");
  });
});
```

- [x] **Step 2: Run the focused Node test and observe missing exports**

Run: `npm --prefix packages/typescript/prime-gateway test -- test/continual-harness.test.mjs`

Expected: FAIL because `PrimeContinualHarnessAdapter` and durable harness records do not exist.

- [x] **Step 3: Implement exact module and wire values**

Define these interfaces in `continual-harness.ts`:

```typescript
export type PrimeHarnessScope = Readonly<{
  primeScope: "local" | "global";
  scopeDigest: string;
  projectionRootRef: string;
}>;

export type PrimeHarnessEffect = Readonly<{
  effectId: string;
  proposalDigest: string;
  scope: PrimeHarnessScope;
  edits: readonly PrimeHarnessEdit[];
}>;

export interface PrimeHarnessModule {
  loadHarnessState(root: string, scope: "local" | "global"): unknown;
  applyRefinementProposal(
    state: unknown,
    proposal: unknown,
    options: Readonly<{ id: string; scope: "local" | "global" }>,
  ): unknown;
  saveHarnessState(root: string, state: unknown): string;
}

export class PrimeContinualHarnessAdapter {
  constructor(options: PrimeContinualHarnessAdapterOptions);
  snapshot(scope: PrimeHarnessScope): Promise<PrimeHarnessSnapshotReceipt>;
  apply(effect: PrimeHarnessEffect): Promise<GatewayHarnessEffectResult>;
}
```

Validate exact keys, UTF-8 byte caps, safe integers, digests, sorted edit identities, and the four kinds/three actions before calling the module. Compute the public effect digest from body digests, never serialized bodies. Reject a base-prompt target and skill entries lacking exact Python reference/argument contracts.

- [x] **Step 4: Add durable bind/terminal records**

Extend `GatewayDurableStore` with:

```typescript
bindHarnessEffect(effect: PrimeHarnessEffect): Promise<GatewayHarnessEffectBinding>;
commitHarnessEffectResult(
  effectId: string,
  status: "succeeded" | "failed" | "uncertain",
  snapshotDigest: string | null,
): Promise<GatewayHarnessEffectResult>;
harnessEffectBinding(effectId: string): GatewayHarnessEffectBinding | undefined;
harnessEffectResult(effectId: string): GatewayHarnessEffectResult | undefined;
```

Persist only `effectId`, `proposalDigest`, `scopeDigest`, `effectDigest`, terminal status, and snapshot digest. Reopen with a binding and no result returns a newly committed `uncertain` result without module invocation.

- [x] **Step 5: Export, build, and run the whole Gateway package**

Run: `npm --prefix packages/typescript/prime-gateway test -- test/continual-harness.test.mjs`

Run: `npm test --prefix packages/typescript/prime-gateway`

Expected: PASS; all public snapshots and errors exclude the private sentinel.

- [x] **Step 6: Commit the Gateway projection**

```bash
git add packages/typescript/prime-gateway/src/continual-harness.ts packages/typescript/prime-gateway/src/durable-store.ts packages/typescript/prime-gateway/src/index.ts packages/typescript/prime-gateway/test/continual-harness.test.mjs
git commit -m "feat: add durable Prime harness projection"
```

---

### Task 5: Bind the exact pinned Prime refinement module and real-process harness

**Files:**
- Modify: `packages/typescript/prime-gateway/resources/prime-artifact-lock.json`
- Create: `packages/typescript/prime-gateway/resources/prime-harness-module-lock.json`
- Modify: `tools/setup_prime_agent.py`
- Modify: `tests/test_setup_prime_agent.py`
- Create: `tests/fixtures/prime_gateway/v1/real-prime-continual-harness.mjs`
- Create: `tests/test_prime_continual_harness_parity.py`

**Interfaces:**
- Consumes: pinned source commit `a18809e00ea30638584d87b3afea7285a9d7296c` and exact built exports `loadHarnessState`, `applyRefinementProposal`, and `saveHarnessState`.
- Produces: `resolve_prime_harness_module()` and one real-Prime provider-free observation covering seven deterministic scenarios.

- [x] **Step 1: Write failing source-lock and real-process tests**

```python
class TestPrimeHarnessModuleLock(unittest.TestCase):
    def test_resolver_accepts_only_the_pinned_refinement_module(self) -> None:
        module = resolve_prime_harness_module(PINNED_SOURCE, lock_path=ARTIFACT_LOCK)
        self.assertEqual(module.name, "index.js")
        self.assertIn("core/refinement", module.as_posix())

    def test_resolver_rejects_source_export_or_digest_drift(self) -> None:
        with self.assertRaisesRegex(PrimeSetupError, "harness module is invalid"):
            resolve_prime_harness_module(_mutated_source(), lock_path=_lock())

class TestPrimeContinualHarnessParity(unittest.TestCase):
    def test_real_prime_provider_free_harness_covers_exact_seven(self) -> None:
        report = run_real_prime_harness()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["provider_operations"], 0)
        self.assertEqual(report["model_credential_reads"], 0)
        self.assertEqual(tuple(report["scenario_ids"]), PRIME_HARNESS_PROVIDER_FREE_SCENARIO_IDS)
        self.assertEqual(report["owned_process_count_after_close"], 0)
```

- [x] **Step 2: Run source-lock and parity tests to observe failure**

Run: `uv run python -m unittest -v tests.test_setup_prime_agent tests.test_prime_continual_harness_parity`

Expected: FAIL because the refinement module lock/resolver and real harness do not exist.

- [x] **Step 3: Lock and resolve the exact built module**

Add `prime-harness-module-lock.json` with an Asterion-owned format ID, the pinned source commit, source-file digest for `packages/coding-agent/src/core/refinement/refinement.ts`, built-module digests for `dist/core/refinement/index.js` and `refinement.js`, and exact required export names. `resolve_prime_harness_module()` must reject symlinks, missing/extra exports, dirty source drift, non-regular files, and digest mismatch with one fixed error.

- [x] **Step 4: Implement the real Node fixture**

`real-prime-continual-harness.mjs` must run in an isolated mode-0700 root, dynamically import only the resolved pinned module, and execute this deterministic matrix without credentials:

1. prompt create/update/delete while rejecting base-prompt mutation;
2. memory create/update/delete;
3. skill create/update/delete with exact Python reference and arguments;
4. subagent create/update/delete without spawning;
5. append-only history and snapshot re-read after process restart;
6. rollback as a new `rollbackOf` revision;
7. disjoint session/project/global projection roots with colliding entry IDs.

The fixture emits one canonical JSON object containing only booleans, counts, digests, sorted scenario IDs, provider-operation count, credential-read count, and owned-process count.

- [x] **Step 5: Run the real provider-free harness twice for determinism**

Run: `uv run python -m unittest -v tests.test_prime_continual_harness_parity`

Run: `uv run python -m unittest -v tests.test_prime_continual_harness_parity`

Expected: both PASS with identical public observation digest, zero provider operations, zero credential reads, and zero owned process after close.

- [x] **Step 6: Commit the pinned module boundary**

```bash
git add packages/typescript/prime-gateway/resources/prime-artifact-lock.json packages/typescript/prime-gateway/resources/prime-harness-module-lock.json tools/setup_prime_agent.py tests/test_setup_prime_agent.py tests/fixtures/prime_gateway/v1/real-prime-continual-harness.mjs tests/test_prime_continual_harness_parity.py
git commit -m "test: bind pinned Prime harness module"
```

---

### Task 6: Promote the seven provider-free scenarios

**Files:**
- Modify: `src/asterion/control/providers/prime/parity_testing.py`
- Modify: `tests/test_prime_continual_harness_parity.py`
- Modify: `tests/test_prime_parity_ledger.py`
- Modify: `tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json`
- Modify: `Makefile`

**Interfaces:**
- Consumes: the exact real-process observation from Task 5.
- Produces: `PRIME_HARNESS_PROVIDER_FREE_VERIFICATION_COMMAND_ID`, `PrimeHarnessScenarioObservation`, `build_prime_harness_observations()`, `register_prime_harness_scenarios()`, and seven sorted evidence records.

- [x] **Step 1: Write failing evidence-boundary and ledger tests**

```python
def test_harness_matrix_is_seven_provider_free_and_one_bounded(self) -> None:
    self.assertEqual(len(PRIME_HARNESS_PROVIDER_FREE_SCENARIO_IDS), 7)
    self.assertEqual(
        PRIME_HARNESS_BOUNDED_SCENARIO_IDS,
        ("prime-parity.harness.evidence-refinement",),
    )

def test_provider_free_observation_cannot_promote_evidence_refinement(self) -> None:
    registry = _registry()
    register_prime_harness_scenarios(
        registry,
        observations=_provider_free_observations(),
        bounded_receipt=None,
        provider_factory=_provider_factory,
    )
    report = asyncio.run(registry.run_all())
    self.assertNotIn(
        "prime-parity.harness.evidence-refinement",
        tuple(result.scenario_id for result in report.results),
    )

def test_ledger_promotes_exactly_seven_harness_provider_free_results(self) -> None:
    results = harness_prime_results(validate_parity_ledger(_ledger()))
    self.assertEqual(count_status(results, "provider-free-pass"), 7)
    self.assertEqual(count_status(results, "missing"), 1)
```

- [x] **Step 2: Run focused tests and observe missing evidence registration**

Run: `uv run python -m unittest -v tests.test_prime_continual_harness_parity tests.test_prime_parity_ledger`

Expected: FAIL while all eight ledger results remain missing.

- [x] **Step 3: Implement exact observation reduction**

Use:

```python
PRIME_HARNESS_PROVIDER_FREE_VERIFICATION_COMMAND_ID = (
    "test.prime-continual-harness.provider-free"
)
PRIME_HARNESS_BOUNDED_VERIFICATION_COMMAND_ID = (
    "test.prime-continual-harness.bounded"
)
```

The observation builder must accept exactly seven scenario IDs in ledger order, the four required assertions, `restart-after-admission`, the pinned source/artifact identities, `real_prime_runtime=True`, `fake_daemon=False`, `provider_operations=0`, `model_credential_reads=0`, and zero owned processes. Any missing/extra/reordered scenario, fake runtime, credential access, provider call, raw field, or digest drift fails closed and creates no evidence ID.

- [x] **Step 4: Add the provider-free Make target**

```make
test.prime-continual-harness.provider-free:
	$(UV_BIN) run python -m unittest -v \
		tests.test_control_harness \
		tests.test_prime_continual_harness \
		tests.test_prime_continual_harness_parity
	npm --prefix packages/typescript/prime-gateway test -- test/continual-harness.test.mjs
```

- [x] **Step 5: Run the named gate and promote only seven exact rows**

Run: `make test.prime-continual-harness.provider-free`

Expected: PASS with seven scenario evidence IDs, zero provider/application operations, zero credential reads, and no owned process.

Update only the seven provider-free Prime Gateway results to `provider-free-pass`; leave `harness.evidence-refinement` and every `asterion.native` result `missing`. Add sorted evidence records with exact provider, feature, scenario, command, boundary, source commit, and artifact lock.

- [x] **Step 6: Verify the honest 7/8 blocked domain and commit**

Run: `uv run python tools/check_prime_parity.py --domain harness.continual --provider asterion.prime-gateway`

Expected: exit nonzero, `status=BLOCKED`, `passed_feature_count=7`, and the sole blocker `harness.evidence-refinement`.

```bash
git add Makefile src/asterion/control/providers/prime/parity_testing.py tests/test_prime_continual_harness_parity.py tests/test_prime_parity_ledger.py tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json
git commit -m "test: promote provider-free harness evidence"
```

---

### Task 7: Add—but do not implicitly execute—the bounded refinement gate

**Files:**
- Create: `tools/prime_continual_harness_experiment.py`
- Create: `tests/test_prime_continual_harness_experiment.py`
- Modify: `src/asterion/control/providers/prime/parity_testing.py`
- Modify: `tests/test_prime_continual_harness_parity.py`
- Modify: `Makefile`

**Interfaces:**
- Consumes: one newly authorized pinned-model proposal invocation and the same host admission/activation path used by provider-free edits.
- Produces: `run_prime_continual_harness_bounded_probe()`, `write_prime_continual_harness_bounded_receipt()`, a closed safe receipt, and bounded evidence only for `harness.evidence-refinement`.

- [x] **Step 1: Write failing authorization, one-call, limit, recovery, and redaction tests**

```python
class TestPrimeContinualHarnessExperiment(unittest.TestCase):
    def test_cli_requires_explicit_bounded_provider_opt_in(self) -> None:
        with mock.patch.object(experiment, "run_authorized_bounded") as run:
            self.assertEqual(experiment.main(["--private-evidence-root", self.root]), 1)
            run.assert_not_called()

    def test_probe_calls_provider_exactly_once_and_requires_evidence(self) -> None:
        calls = 0
        def provider_probe() -> Mapping[str, object]:
            nonlocal calls
            calls += 1
            return _valid_bounded_report(evidence_ids=("evidence-input-1",))
        receipt = run_prime_continual_harness_bounded_probe(
            provider_probe,
            model_selector_digest="a" * 64,
            aggregate_token_limit=150_000,
            cost_limit_micros=500_000,
            deadline_ms=600_000,
        )
        self.assertEqual(calls, 1)
        self.assertEqual(receipt["provider_operations"], 1)
        self.assertEqual(receipt["model_credential_reads"], 1)

    def test_post_provider_receipt_failure_recovers_without_second_call(self) -> None:
        receipt = recover_prime_continual_harness_bounded(
            self.completed_native_root,
            self.evidence_root,
            model_selector_digest="a" * 64,
        )
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["provider_operations"], 1)
```

- [x] **Step 2: Run tests and observe the missing bounded experiment**

Run: `uv run python -m unittest -v tests.test_prime_continual_harness_experiment tests.test_prime_continual_harness_parity`

Expected: FAIL because the bounded reducer and CLI do not exist.

- [x] **Step 3: Implement the closed bounded reducer and writer**

The receipt schema is closed. This valid concrete example fixes field names and JSON value types; runtime values must satisfy the validation rules below:

```python
{
    "format": "asterion.prime-continual-harness-bounded/v1",
    "status": "PASS",
    "model_selector_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "provider_operations": 1,
    "model_credential_reads": 1,
    "evidence_input_count": 7,
    "proposal_grounded": True,
    "host_admitted": True,
    "snapshot_activated": True,
    "limits": {
        "aggregate_tokens": 12000,
        "cost_micros": 500000,
        "deadline_ms": 600000,
    },
    "usage": {"aggregate_tokens": 8203, "cost_micros": 0},
}
```

Reject extra fields, non-finite values, zero evidence, model/provider/private payloads, missing admission/activation, more or fewer than one provider operation, and any usage above the authorized limits. The writer uses an exclusive mode-0600 file and never overwrites. Recovery is permitted only from a validated already-completed native receipt whose failure stage is public-receipt projection; it performs no provider call.

- [x] **Step 4: Add an explicit bounded Make target**

```make
test.prime-continual-harness.bounded:
	$(UV_BIN) run python tools/prime_continual_harness_experiment.py \
		--authorized-bounded-provider \
		--source-root 3th-party/prime-agent \
		--private-evidence-root .asterion-private/prime-continual-harness
```

Run only the unit tests now:

Run: `uv run python -m unittest -v tests.test_prime_continual_harness_experiment tests.test_prime_continual_harness_parity`

Expected: PASS without executing the bounded Make target and with zero real provider operations.

- [x] **Step 5: Commit the dormant bounded boundary**

```bash
git add Makefile tools/prime_continual_harness_experiment.py tests/test_prime_continual_harness_experiment.py src/asterion/control/providers/prime/parity_testing.py tests/test_prime_continual_harness_parity.py
git commit -m "test: add bounded harness refinement gate"
```

- [x] **Step 6: Hard authorization checkpoint**

Stop and request new explicit operator authorization that names this continual-harness bounded target and accepts its one-operation/token/cost/deadline envelope. Do not infer authorization from configuration, credentials, Climb autonomy, or earlier bounded runs.

After authorization only, run: `make test.prime-continual-harness.bounded`

Expected: PASS with one provider operation, one credential read, finite usage, evidence-grounded proposal, host admission, snapshot activation, and no raw model output. If the native provider operation completes but receipt projection fails, recover from the same receipt and do not rerun the provider.

---

### Task 8: Promote the bounded row and close the domain

**Files:**
- Modify: `tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json`
- Modify: `tests/test_prime_parity_ledger.py`
- Modify: `tests/test_check_prime_parity.py`
- Modify: `docs/status/PRIME-PARITY-LEDGER.md`
- Modify: `docs/status/CURRENT-STATE.md`
- Modify: `docs/status/JOURNAL.md`
- Modify: `docs/status/RESUME-NEXT-SESSION.md`
- Modify: `docs/status/climb/hypotheses.yaml`
- Modify: `docs/status/climb/research-tree.md`
- Modify: `docs/status/climb/runs.csv`
- Modify: `docs/status/climb/session-state.json`

**Interfaces:**
- Consumes: seven exact provider-free evidence IDs and the separately authorized bounded receipt.
- Produces: Prime Gateway `harness.continual` 8/8 PASS while preserving `asterion.native=missing` and later-domain blockers.

- [x] **Step 1: Write failing exact-domain tests**

```python
def test_continual_harness_domain_closes_only_with_seven_plus_one(self) -> None:
    report = run_checker("harness.continual", "asterion.prime-gateway")
    self.assertEqual(report["selected_feature_count"], 8)
    self.assertEqual(report["passed_feature_count"], 8)
    self.assertEqual(report["blocking_feature_count"], 0)
    self.assertEqual(report["status"], "PASS")

def test_native_harness_results_remain_missing(self) -> None:
    self.assertEqual(
        {result.status for result in native_harness_results(_ledger())},
        {"missing"},
    )
```

- [x] **Step 2: Run and observe the sole bounded blocker**

Run: `uv run python -m unittest -v tests.test_prime_continual_harness_parity tests.test_prime_parity_ledger tests.test_check_prime_parity`

Expected: FAIL until the exact authorized bounded evidence record is added.

- [x] **Step 3: Promote exactly one bounded result and update human status**

Add one sorted evidence record for `harness.evidence-refinement` with boundary `bounded-provider`, the named bounded command, pinned baseline identities, and no private/model payload. Update only that Prime Gateway result to `bounded-pass`. Keep every native result missing and do not change ecosystem/interfaces results.

- [x] **Step 4: Run all closure gates**

Run: `make test.prime-continual-harness.provider-free`

Run: `uv run python tools/check_prime_parity.py --domain harness.continual --provider asterion.prime-gateway`

Run: `make check`

Run: `make promotion-check`

Run: `git diff --check`

Expected: all provider-free closure commands PASS; the domain reports 8/8, the previous bounded receipt is validated but not rerun, the system claim remains blocked on later domains, and native parity remains Missing.

- [x] **Step 5: Advance deterministic Climb state and commit closure**

Add the exact next hypothesis for `ecosystem.capabilities`, regenerate rather than hand-edit derived Climb state, and ensure each cycle number occurs once.

```bash
git add tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json tests/test_prime_parity_ledger.py tests/test_check_prime_parity.py docs/status/PRIME-PARITY-LEDGER.md docs/status/CURRENT-STATE.md docs/status/JOURNAL.md docs/status/RESUME-NEXT-SESSION.md docs/status/climb
git commit -m "feat: close Prime continual harness parity"
```

---

## Plan Self-Review

- **Spec coverage:** Tasks 1–2 own closed values, scopes, revision history, snapshots, rollback, uncertainty, and recovery. Tasks 3–5 own selected-provider translation, pinned Prime module identity, real-process execution, and private/durable effect fencing. Task 6 promotes exactly seven provider-free scenarios. Task 7 isolates the only cost-bearing scenario behind a new authorization checkpoint. Task 8 promotes one bounded row and closes only the Prime Gateway domain.
- **Placeholder scan:** The plan contains no incomplete implementation placeholder. Every task names exact files, interfaces, tests, commands, expected results, and commit boundaries.
- **Type consistency:** Python proposal/effect/revision/snapshot identities flow unchanged into the Prime adapter. TypeScript uses the same effect/proposal/scope digests. Evidence command IDs and the seven-plus-one scenario split remain stable from Task 5 through Task 8.
- **Boundary check:** No task changes the public agent-control protocol, grants authority from Prime state, imports Prime from generic framework modules, scans provider roots, runs skills/subagents during refinement, or promotes native/system parity by implication.
