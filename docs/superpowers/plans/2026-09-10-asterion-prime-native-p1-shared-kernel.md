# Asterion Prime Native P1 Shared-Kernel Implementation Plan

> **For agentic workers:** Use subagent-driven development. Assign Tasks 0, 2, 4, and the final contract review to Astra/Sol; routine isolated implementation and test work may go to Terra; mechanical fixture and packaging checks may go to Luna. Workers are not alone in the repository: preserve unrelated edits, never revert another worker's changes, and commit each completed task before starting the next dependent task.

**Goal:** Deliver the installed `prime.ipython-coding@1.0.0` application through the native `asterion.prime` runtime: two model-driven IPython stages in one persistent worker, a real Pi compaction between them, clean `ControlHost`/journal/client reconstruction in the still-running operator process, continuation without replay, an instrumentation-based oracle, a redacted receipt, and deterministic teardown.

**Architecture:** Extend the existing Pi transport, `asterion.agents.prime` session semantics, closed session-context manager, and native application provider. The application provider owns a coordinator that runs the composed application and `ControlHost` concurrently. Runtime and control are orthogonal clients of one provider-owned `PrimeSessionBackend`; the runtime waits at private barriers while the coordinator performs `session.compact`, reconstructs host-side control objects, issues `session.continuation.resume`, and releases stage two. No runtime imports or drives `ControlHost`, and no closed v1 schema changes are permitted.

**Tech Stack:** Python 3.10+, `asyncio`, `unittest`, immutable dataclasses/mappings, JSONL-RPC Pi 0.7.1, TypeScript 6, Node 20+, esbuild, Hatch/Hatchling, installed-wheel subprocess tests.

## Global Constraints

- Preserve dependency direction: CLI/host → provider → assembly → package/composer → exact implementation → runner → runtime/host services.
- Keep `runtime/`, `packages/`, `assembly/`, `runner/`, and `services/` domain-neutral. They must not import application code.
- Do not change `asterion.agent-runtime/v1`, `asterion.capability/v1`, `asterion.capability-package/v1`, `asterion.application-assembly/v1`, control-plane v1, or session-context v1 schemas.
- Do not import or reuse `asterion.control.providers.prime` in the native path. New native control code lives under `asterion.control.providers.asterion_prime`; `control.providers.native` is only a structural reference.
- Keep one `asterion.prime` runtime factory binding. Dispatch exact application ID/version inside that binding; do not register duplicate runtime IDs.
- Manifests contain compatibility metadata only. Prompts, commands, executable paths, environment values, provider/model settings, credentials, mutable state, and authority remain host-owned Python values.
- Public output is limited to safe status, terminal events, artifact metadata, and the P1 receipt digest. Never expose prompt text, model text, cell code/output, Pi events, context messages/summaries, credentials, provider payloads, private roots, or inherited file descriptors.
- Fixed P1 limits are internal and parameter-free: deadline `600000 ms`, model callbacks `<= 8`, IPython callbacks `<= 4`, aggregate tokens `<= 64000`, total cost `<= 500000` micro-units, compact reservation `<= 16000` tokens and `<= 125000` micro-units, worker output `<= 65536` bytes.
- Fixed Pi compaction settings are `autoCompact=false`, `reserveTokens=4096`, and `keepRecentTokens=256`. The compact receipt calls charged usage `reservation-charged`, never actual or observed usage.
- The backend must receive every `sync_authority_snapshot` update so provider-side checks cannot drift from the host ledger.
- Persist before acknowledgement; reject identity/digest/cursor conflicts; fence any post-dispatch unknown outcome; never replay an outstanding or uncertain effect.
- Use the real Pi `compact` RPC. Do not pad context, inject a summary, skip compact, or use a second provider adapter.
- This phase proves clean host-object reconstruction only. Host-process crash recovery, Pi-process recovery, and worker-process recovery remain P4 scope.
- Use `apply_patch` for edits, keep commits focused, and do not clean unrelated dirty-tree files.

---

### Task 0: Prove the locked Pi compaction contract and reservation bound

**Files:**

- Create: `src/asterion/agents/prime/compaction_budget.py`
- Create: `packages/typescript/asterion-prime-extension/resources/pi-compaction-lock.json`
- Create: `packages/typescript/asterion-prime-extension/src/context-projection.ts`
- Create: `packages/typescript/asterion-prime-extension/src/context-counter.ts`
- Create: `tools/build_asterion_prime_compaction_lock.mjs`
- Create: `tools/probe_asterion_prime_compaction.mjs`
- Modify: `tools/check_promotion.py`
- Modify: `pyproject.toml`
- Create: `tests/fixtures/asterion_prime_p1/v1/pi-compaction-contract.json`
- Create: `tests/test_asterion_prime_pi_contract.py`
- Modify: `docs/superpowers/specs/2026-09-10-asterion-prime-native-p1-shared-kernel-design.md` only if the measured bound or import path differs from the approved assumption

**Step 1: Write the failing lock-and-evidence test**

The test must resolve the existing `ASTERION_PRIME_SOURCE_ROOT`, verify `@earendil-works/pi-coding-agent@0.7.1` against `packages/typescript/prime-gateway/resources/prime-artifact-lock.json`, then verify a new P1-specific lock covering every JavaScript file in the imported compaction/build-context closure before executing the probe. Compare the complete canonical JSON result with the committed fixture. It must also prove that the public package exports do not expose `prepareCompaction`, that every selected internal module is beneath the same real source root and matches its committed SHA-256, and that both possible summary branches are included in the upper bound. The fixture uses explicit synthetic prices only to prove the arithmetic; live preflight must call the same lock verifier and Python calculator with operator-resolved model prices.

```python
class TestAsterionPrimePiContract(unittest.TestCase):
    def test_locked_compaction_contract_and_bound_match_evidence(self) -> None:
        completed = subprocess.run(
            ["node", "tools/probe_asterion_prime_compaction.mjs", str(LOCKED_PI_ROOT)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        observed = json.loads(completed.stdout)
        expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(observed, expected)
        self.assertEqual(observed["pi_version"], "0.7.1")
        self.assertFalse(observed["public_prepare_compaction_exported"])
        self.assertTrue(observed["internal_module_beneath_locked_root"])
        self.assertEqual(observed["branches"], ["main-summary", "turn-prefix-summary"])
        self.assertEqual(observed["input_caps"], [4096, 4096])
        self.assertEqual(observed["output_caps"], [3276, 3276])
        self.assertLessEqual(observed["worst_case_reserved_tokens"], 16_000)
        self.assertLessEqual(observed["worst_case_cost_micro_units"], 125_000)

    def test_live_price_uses_the_same_fail_closed_calculator(self) -> None:
        quote = quote_compaction_reservation(
            branch_input_caps=(4096, 4096),
            branch_output_caps=(3276, 3276),
            price=ModelPrice(input_per_million=2_000_000, output_per_million=4_000_000),
        )
        self.assertEqual(quote.reserved_tokens, 14_744)
        self.assertEqual(quote.cost_micro_units, 42_592)
```

Run: `uv run python -m unittest -v tests.test_asterion_prime_pi_contract`

Expected: FAIL because the probe and fixture do not exist.

**Step 2: Implement a provider-free, canonical probe**

The probe must:

- accept one already-resolved source root, verify its real path and artifact digest against the committed Prime lock, then resolve `@earendil-works/pi-coding-agent/package.json` beneath it;
- use `build_asterion_prime_compaction_lock.mjs` plus an esbuild metafile to enumerate the complete transitive closure of the exact `prepareCompaction`, `buildSessionContext`, summary-request construction, and imported constants used by the witness; commit sorted relative paths and SHA-256 values in `pi-compaction-lock.json`;
- make both the provider-free probe and live operator preflight verify that exact closure lock before loading any module; add the lock to `check_promotion.py` and force-include it as `asterion/applications/prime/resources/pi-compaction-lock.json` in the wheel;
- reject any version other than `0.7.1`;
- import the exact internal `dist/core/compaction/compaction.js` by `pathToFileURL()` after verifying its real path is beneath the locked package root;
- exercise the pinned `prepareCompaction` on synthetic maximum-size messages using `reserveTokens=4096` and `keepRecentTokens=256`;
- reconstruct the exact system/instruction/tag/previous-summary additions used by `generateSummary` and the split-turn prefix request;
- instrument the real pinned functions/RPC harness to observe hook/RPC ordering rather than printing constants;
- report each branch's canonical request digest, Asterion-unit size, admitted input cap, output cap, synthetic price components, rounding rule, per-branch token reservation/cost, and aggregate reservation/cost;
- perform no network or provider calls.

Task 0 owns the production TypeScript `PrimeContextProjectionV1` and canonical counter used by its request-size evidence. Task 2 adds Python parity and the live witness around this exact implementation; it must not introduce a second counting algorithm.

The output shape is exact and sorted before serialization:

```javascript
const evidence = {
  branches: ["main-summary", "turn-prefix-summary"],
  branch_evidence: branchEvidence,
  hook_order: ["session_before_compact", "session_compact"],
  input_caps: [4096, 4096],
  internal_module_beneath_locked_root: true,
  pi_version: "0.7.1",
  public_prepare_compaction_exported: false,
  rpc_order: ["prompt", "compact", "prompt"],
  settings: { autoCompact: false, keepRecentTokens: 256, reserveTokens: 4096 },
  worst_case_cost_micro_units: worstCost,
  worst_case_reserved_tokens: worstTokens,
};
process.stdout.write(`${JSON.stringify(evidence)}\n`);
```

Implement `quote_compaction_reservation()` in `compaction_budget.py` as the only production arithmetic path. It accepts two exact branch caps and a validated operator price, rounds each priced component upward, reserves both possible callbacks, and rejects missing/non-finite/negative prices or aggregate values over `16000` tokens / `125000` micro-units. Static evidence uses the fixed synthetic `ModelPrice` above. Live preflight later supplies the exact operator-resolved price and refuses to start Pi or the worker if the same calculation fails.

If the internal import, serialized request reconstruction, or `16000`/`125000` bound cannot be proved, stop this plan at Gate G0 and obtain user approval for any limit/contract change plus Astra review before Task 1; an implementation agent may not revise the approved limits unilaterally.

**Step 3: Run the focused gate and inspect determinism**

Run twice:

```bash
uv run python -m unittest -v tests.test_asterion_prime_pi_contract
git diff --exit-code tests/fixtures/asterion_prime_p1/v1/pi-compaction-contract.json
```

Expected: PASS; the fixture remains unchanged on the second run; no provider configuration is read.

**Step 4: Commit Gate G0**

```bash
git add src/asterion/agents/prime/compaction_budget.py packages/typescript/asterion-prime-extension/resources/pi-compaction-lock.json packages/typescript/asterion-prime-extension/src/context-projection.ts packages/typescript/asterion-prime-extension/src/context-counter.ts tools/build_asterion_prime_compaction_lock.mjs tools/probe_asterion_prime_compaction.mjs tools/check_promotion.py pyproject.toml tests/fixtures/asterion_prime_p1/v1/pi-compaction-contract.json tests/test_asterion_prime_pi_contract.py docs/superpowers/specs/2026-09-10-asterion-prime-native-p1-shared-kernel-design.md
git commit -m "test: pin prime p1 compaction contract"
```

---

### Task 1: Make `PiRpcSession` reusable without breaking one-shot callers

**Files:**

- Modify: `src/asterion/runtimes/pi_rpc.py`
- Create: `tests/test_pi_rpc_reusable.py`
- Modify: `tests/test_pi_session.py`
- Modify: `tests/test_dci_pi_rpc_recovery.py`

**Step 1: Write failing state-machine tests**

Cover one child PID across `open → prompt → compact → prompt → close`, global request IDs, globally monotonic native event sequence, one absolute session deadline, cancellation poisoning after possible dispatch, rejection of concurrent commands, idempotent close, and the legacy `run()` wrapper.

```python
async def test_prompt_compact_prompt_reuses_one_process(self) -> None:
    rpc = make_rpc_session(self.fake_rpc_command)
    await rpc.open(signal=NeverCancelled())
    pid = rpc.process.pid
    first = await rpc.prompt("stage-one", signal=NeverCancelled(), on_event=self.events.append)
    compact = await rpc.compact(signal=NeverCancelled(), on_event=self.events.append)
    second = await rpc.prompt("stage-two", signal=NeverCancelled(), on_event=self.events.append)
    self.assertEqual(rpc.process.pid, pid)
    self.assertEqual([event.sequence for event in self.events], list(range(1, len(self.events) + 1)))
    self.assertEqual(compact.rpc_type, "compact")
    self.assertNotEqual(first.request_id, second.request_id)
    await rpc.close()
    self.assertIsNone(rpc.process)
```

Run: `uv run python -m unittest -v tests.test_pi_rpc_reusable`

Expected: FAIL because `open`, `prompt`, `compact`, and async `close` are absent.

**Step 2: Add the reusable lifecycle**

Keep `start()`, `drive_prompt()`, and `stop()` as low-level synchronous primitives. Add a serialized async lifecycle with an absolute deadline captured in `open()`:

```python
@dataclass(frozen=True, slots=True)
class PiRpcCompactResult:
    request_id: str
    rpc_type: Literal["compact"]
    events: tuple[PiRpcEvent, ...]
    stderr: bytes

async def open(self, *, signal: CancellationSignal) -> None: ...
async def prompt(
    self,
    prompt: str,
    *,
    signal: CancellationSignal,
    on_event: Callable[[PiRpcEvent], None],
) -> PiRpcResult: ...
async def compact(
    self,
    *,
    signal: CancellationSignal,
    on_event: Callable[[PiRpcEvent], None],
) -> PiRpcCompactResult: ...
async def close(self) -> None: ...
```

Add `request_id: str | None = None` as the last defaulted field of existing `PiRpcResult`, so existing positional constructors remain compatible while reusable prompt results expose their exact request. Use one `asyncio.Lock`, one session event counter, and one monotonic deadline. Any exception after a request is written marks the lifecycle poisoned; only `close()` remains legal. `run()` becomes `open(); prompt(); close()` in `try/finally`, preserving its exception text, public result, and existing P7 behavior.

**Step 3: Run focused and regression tests**

```bash
uv run python -m unittest -v tests.test_pi_rpc_reusable tests.test_pi_session tests.test_dci_pi_rpc_recovery tests.test_asterion_prime_session
```

Expected: PASS. Existing one-shot tests must not require changes to their callers.

**Step 4: Review Gate G1 and commit**

Review cancellation-before-write versus cancellation-after-write, global versus per-prompt usage/event accounting, unexpected response IDs, and close after poison.

```bash
git add src/asterion/runtimes/pi_rpc.py tests/test_pi_rpc_reusable.py tests/test_pi_session.py tests/test_dci_pi_rpc_recovery.py
git commit -m "feat: add reusable pi rpc lifecycle"
```

---

### Task 2: Add deterministic context counting and an authenticated Pi compact witness

**Files:**

- Create: `src/asterion/agents/prime/context.py`
- Modify: `packages/typescript/asterion-prime-extension/src/context-counter.ts`
- Modify: `packages/typescript/asterion-prime-extension/src/context-projection.ts`
- Create: `packages/typescript/asterion-prime-extension/src/context-witness.ts`
- Modify: `packages/typescript/asterion-prime-extension/src/ipython-extension.ts`
- Modify: `packages/typescript/asterion-prime-extension/package.json`
- Modify: `hatch_build.py`
- Create: `packages/typescript/asterion-prime-extension/test/context-witness.test.mjs`
- Create: `tests/fixtures/asterion_prime_p1/v1/context-parity.json`
- Create: `tests/test_asterion_prime_context.py`

**Step 1: Write failing parity and witness tests**

Use one shared fixture containing Unicode, tool calls/results, empty content, a prior summary, and a split turn. Assert Python/TypeScript parity and exact witness rejection behavior.

```python
def test_context_counter_matches_committed_typescript_observation(self) -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for case in fixture["cases"]:
        with self.subTest(case=case["name"]):
            self.assertEqual(count_rebuilt_context(case["messages"]), case["asterion_units"])

def test_witness_requires_real_nonempty_compaction_input(self) -> None:
    with self.assertRaisesRegex(PrimeContextError, "witness"):
        validate_compaction_witness({"messages_to_summarize": [], "turn_prefix_messages": []})
```

Node tests must assert an authenticated proposal→approve/reject handshake before Pi calls its built-in compact implementation, followed by one persisted frame after mutation. They also assert exact hook order, `preparation.tokensBefore` retained only in private diagnostics, no prompt/summary content in errors, and fail-closed behavior for closed FD, malformed frames, wrong command nonce, duplicate frames, backpressure timeout, and oversized frames. A rejection must make the hook return `{cancel: true}` and the harness must prove neither summary callback nor `appendCompaction` ran.

Run:

```bash
uv run python -m unittest -v tests.test_asterion_prime_context
npm --prefix packages/typescript/asterion-prime-extension test
```

Expected: FAIL because the counter and witness do not exist.

**Step 2: Implement one cross-language counter**

First project each real Pi message into `asterion.prime-context-projection/v1`. Retain only model-context-bearing content: role; text/thinking strings; tool name and canonical-argument string; tool-result text/image descriptors; bash command/output/exit status; compaction summary plus covered-boundary metadata; and image media type, byte length, and content digest. Exclude IDs, timestamps, provider/model metadata, usage, cost, duration, and transport diagnostics. In TypeScript, recursively sort tool-argument object keys and serialize all valid finite JSON numbers with ECMAScript `JSON.stringify` semantics (`-0` becomes `0`); embed that canonical JSON as a string in the projection. This covers decimal tool arguments without requiring Python to reproduce ECMAScript number formatting.

Define Asterion units as UTF-8 byte length of the versioned projection's canonical JSON. After projection the accepted value domain is null, booleans, bounded integers, well-formed Unicode strings, arrays, and string-keyed objects; floats are present only inside the already-canonical tool-argument string. Sort object keys by Unicode scalar-value order, use compact separators, preserve array order, and encode UTF-8 without ASCII escaping. TypeScript emits both the projection bytes and digest over the private witness channel. Python validates the projection schema/digest and applies the same encoder to the projected fixture; it never reinterprets raw Pi floating-point values.

```python
def count_rebuilt_context(projection: PrimeContextProjectionV1) -> int:
    projection.validate()
    return len(encode_prime_context_v1(projection.to_mapping()))
```

The TypeScript implementation must produce identical bytes, not use Pi's estimator. Both pre-compact and post-compact counts use this function.

**Step 3: Implement the witness on a separate inherited FD**

Register observers for `session_before_compact` and `session_compact`; do not replace Pi's built-in summary callback. Use a preflighted private duplex socket FD, a random launch nonce, and a per-command nonce. In `session_before_compact`, rebuild the exact pre-context with public `buildSessionContext`, reconstruct both possible built-in summary request bodies with the lock-verified Pi functions, and send a bounded private proposal. Python verifies identity, `firstKeptEntryId`, non-empty source, both request caps, live operator price, callback/deadline authority, and then replies `approve` or `reject`. Only `approve` permits the hook to return `undefined`; `reject` returns `{cancel: true}`, providing positive proof of no summary call or context mutation. In `session_compact`, send the persisted compaction entry, private summary body, covered boundary, and rebuilt post-context so Python can verify and persist the replacement before acknowledging success. Authenticate every length-prefixed frame, cap frame length/write/read time, and zero/close buffers and descriptors during teardown.

```typescript
interface CompactProposal {
  protocol: "asterion.prime-context-witness/v1";
  launch_nonce: string;
  command_nonce: string;
  phase: "proposal";
  first_kept_entry_id: string;
  preparation_sha256: string;
  source_kind: "messages" | "turn-prefix";
  pre_context_projection: PrimeContextProjectionV1;
  main_summary_request: string;
  turn_prefix_summary_request: string | null;
  pre_units: number;
}

interface CompactDecision {
  protocol: "asterion.prime-context-witness/v1";
  launch_nonce: string;
  command_nonce: string;
  phase: "decision";
  status: "approve" | "reject";
}

interface CompactPersisted {
  protocol: "asterion.prime-context-witness/v1";
  launch_nonce: string;
  command_nonce: string;
  phase: "persisted";
  first_kept_entry_id: string;
  compaction_entry: PrimeJson;
  summary: string;
  post_context_projection: PrimeContextProjectionV1;
}
```

Import `context-witness.ts` from `ipython-extension.ts` so Hatch still packages one self-contained `ipython-extension.mjs`. Extend the existing lease environment/FD validation; never add a second extension provider.

**Step 4: Add Python validation and readiness policy**

```python
@dataclass(frozen=True, slots=True)
class PrimeCompactionEvidence:
    command_nonce: str
    covered_leaf_id: str
    preparation_sha256: str
    source_kind: Literal["messages", "turn-prefix"]
    before_context_tokens: int
    after_context_tokens: int
    summary_sha256: str
    compact_entry_sha256: str
    usage_label: Literal["reservation-charged"]

def validate_compaction_witness(
    proposal: Mapping[str, object],
    persisted: Mapping[str, object],
    *,
    expected_launch_nonce: str,
    expected_command_nonce: str,
) -> PrimeCompactionEvidence: ...
```

Require non-empty `messagesToSummarize` or `turnPrefixMessages`; reject a short prefix rather than padding it. Before replying `approve`, call the Task 0 calculator on the exact reconstructed request bodies and live price, reserve both model callbacks, and confirm the global deadline remains. After persistence, verify launch/command nonce, `firstKeptEntryId`, summary digest/body, exact proposal→decision→persisted order, `buildSessionContext` material, and positive reduction. Store the summary body only in the private backend checkpoint; return only IDs/counts/digests plus `reservation-charged`. If validation or private persistence fails after mutation, mark the backend uncertain before returning control to `SessionContextManager`.

**Step 5: Run Gate G2 and commit**

```bash
npm --prefix packages/typescript/asterion-prime-extension ci
npm --prefix packages/typescript/asterion-prime-extension test
uv run python -m unittest -v tests.test_asterion_prime_context tests.test_prime_p7_native_ipython
uv build --wheel
```

Expected: PASS; wheel contains one self-contained extension artifact; P7 extension behavior remains intact.

```bash
git add src/asterion/agents/prime/context.py packages/typescript/asterion-prime-extension hatch_build.py tests/fixtures/asterion_prime_p1/v1/context-parity.json tests/test_asterion_prime_context.py
git commit -m "feat: witness prime context compaction"
```

---

### Task 3: Fence every post-dispatch unknown session-context outcome

**Files:**

- Modify: `src/asterion/control/session_context_manager.py`
- Modify: `src/asterion/control/manager.py`
- Modify: `tests/test_session_context_manager.py`
- Modify: `tests/test_control_recovery.py`

**Step 1: Write failing ordinary-exception and invalid-receipt tests**

Use a counting client and a real `FileCanonicalJournal`. After admission, make the client raise a normal exception or return a mismatched/malformed receipt. Reconstruct authority, journal, and manager, then prove retry returns/fails from durable uncertainty without a second provider call.

```python
async def test_post_dispatch_exception_is_durably_uncertain(self) -> None:
    with self.assertRaisesRegex(SessionContextTransportError, "uncertain"):
        await manager.execute(command)
    self.assertTrue(manager.snapshot().recovery_required)
    recovered = reconstruct_manager(journal_path, client)
    self.assertTrue(recovered.snapshot().recovery_required)
    receipt = await recovered.execute(command)
    self.assertEqual(receipt.status, "uncertain")
    self.assertEqual(client.calls, 1)
```

Run: `uv run python -m unittest -v tests.test_session_context_manager tests.test_control_recovery`

Expected: FAIL for normal exceptions and returned-receipt identity mismatches.

**Step 2: Centralize durable uncertainty sealing**

Add a single helper invoked for `CancelledError`, ordinary `Exception`, and invalid returned receipt after dispatch:

```python
def _seal_delivery_uncertain(
    self,
    command: SessionContextCommand,
    decision: SessionContextDecision,
) -> SessionContextReceipt:
    return self._seal_provider_receipt(
        command,
        decision,
        SessionContextReceipt(
            receipt_id=f"host-uncertain:{command.command_id}",
            command_id=command.command_id,
            session_id=command.session_id,
            generation=command.generation,
            operation=command.operation,
            status="uncertain",
            reason_code="delivery-outcome-unknown",
            payload={"evidence_ref": None, "result": None},
        ),
    )
```

Only explicitly typed, proven pre-dispatch rejection may remain definitive without a fence. Do not infer safety from a generic adapter exception. If uncertainty itself cannot be appended, immediately set the in-memory recovery fence and invoke the recovery sink before raising `SessionContextManagerError`; the manager must not accept a second mutating command in the same process.

Also cover provider-reported usage outside the reservation and failures inside `_receipt_usage()`, receipt journaling, settlement preview, or settlement application. Before dispatch these stay definitive; after possible mutation they must either durably seal uncertainty or install the local recovery fence. No path may leave an admitted command retryable.

Add an optional zero-argument async `authority_snapshot_sink: Callable[[], Awaitable[None]]` to `SessionContextManager`. `ControlHost` passes its existing `_sync_authority_snapshot` bound coroutine, which computes `RemainingBudget` from the one host-owned ledger and delivers it to the selected client. Invoke it after reservation and after settlement so the backend mirrors remaining authority but never performs a second debit; `SessionContextManager` remains the sole compact reservation/settlement owner. A snapshot delivery failure after reservation is uncertain and fenced.

**Step 3: Verify recovery and commit**

```bash
uv run python -m unittest -v tests.test_session_context_manager tests.test_control_recovery tests.test_prime_session_context_parity
```

Expected: PASS; no existing definitive receipt accounting changes.

```bash
git add src/asterion/control/session_context_manager.py src/asterion/control/manager.py tests/test_session_context_manager.py tests/test_control_recovery.py
git commit -m "fix: fence uncertain session context delivery"
```

---

### Task 4: Build the shared Asterion Prime backend and durable store

**Files:**

- Create: `src/asterion/agents/prime/state.py`
- Create: `src/asterion/agents/prime/store.py`
- Create: `src/asterion/agents/prime/backend.py`
- Create: `src/asterion/agents/prime/execution.py`
- Modify: `src/asterion/agents/prime/session.py`
- Modify: `src/asterion/runtimes/asterion_prime.py`
- Create: `tests/test_asterion_prime_store.py`
- Create: `tests/test_asterion_prime_backend.py`
- Modify: `tests/test_asterion_prime_session.py`

**Step 1: Write failing store/backend contract tests**

Cover exact identity, root ownership, symlink rejection, append-only canonical records, persist-before-ack, duplicate command digest, generation mismatch, monotonic cursor suffix, one writer/multiple attachments, stage barriers, authority snapshot synchronization, outstanding-effect fence, cleanup, cancellation, and redacted repr/errors.

```python
async def test_backend_persists_before_ack_and_replays_suffix(self) -> None:
    attachment = backend.attach(identity)
    receipt = await attachment.execute_prompt(stage_one_request())
    self.assertTrue(store.has_record(receipt.record_id))
    replay = backend.replay_events(after_cursor=0)
    self.assertEqual(tuple(event.cursor for event in replay), (1, 2, 3))
    self.assertEqual(backend.attach(identity).replay_events(after_cursor=1), replay[1:])

async def test_uncertain_effect_fences_mutation(self) -> None:
    await backend.mark_uncertain("compact-1")
    with self.assertRaisesRegex(PrimeBackendError, "recovery required"):
        await backend.execute_prompt(stage_two_request())
```

Run: `uv run python -m unittest -v tests.test_asterion_prime_store tests.test_asterion_prime_backend`

Expected: FAIL because backend/store types do not exist.

**Step 2: Implement immutable state and canonical storage**

```python
@dataclass(frozen=True, slots=True)
class PrimeBackendIdentity:
    session_id: str
    generation: int
    provider_id: str
    application_id: str
    application_version: str
    runtime_id: Literal["asterion.prime"]
    pi_command_sha256: str
    extension_binding_fingerprint: str
    worker_identity_sha256: str
    continuation_id: str
    private_root_identity: str
    ceilings_sha256: str

@dataclass(frozen=True, slots=True)
class PrimeBackendSnapshot:
    identity: PrimeBackendIdentity
    cursor: int
    phase: Literal["created", "open", "effect-active", "suspended", "terminal", "recovery-required"]
    outstanding_effect: str | None
    authority_revision: int

@dataclass(frozen=True, slots=True)
class PrimeCheckpoint:
    checkpoint_id: str
    generation: int
    public_event_cursor: int
    private_transcript_sha256: str
    summary_sha256: str | None
    covered_leaf_id: str | None
    worker_identity_sha256: str
    continuation_id: str
    usage_sha256: str
    outstanding_effect: str | None
    prior_checkpoint_sha256: str | None
```

`FilePrimeSessionStore` owns a validated private directory and canonical JSONL/checkpoint files. Every append uses an expected position and fsync before in-memory state advances. It rejects links, identity drift, malformed/trailing records, duplicate IDs with different digests, and records beyond configured byte caps. Recovery revalidates every identity field above, the Pi/extension/worker fingerprints, fixed ceilings, checkpoint chain, transcript and summary digests, public cursor prefix, usage, and outstanding-effect status before allowing attachment.

**Step 3: Implement one backend with runtime/control attachments**

```python
class PrimeSessionBackend:
    def attach(self, identity: PrimeBackendIdentity) -> PrimeAttachment: ...
    async def execute_prompt(self, request: PrimePromptRequest) -> PrimePromptReceipt: ...
    async def execute_context(self, command: SessionContextCommand) -> SessionContextReceipt: ...
    async def accept_control(self, command: ControlCommand) -> None: ...
    def replay_events(self, after_cursor: int) -> tuple[PrimeBackendEvent, ...]: ...
    def sync_authority_snapshot(self, budget: RemainingBudget) -> None: ...
    async def close(self) -> PrimeCleanupReceipt: ...
```

The backend owns the reusable `PiRpcSession`, extension lease, witness reader, a generic tool executor supplied by the selected application, counters, and durable generic effect/checkpoint state. Attachments never own these resources. P1 stage names and barriers belong to the P1 runtime session/coordinator and must not appear in `agents/prime` state or storage. Keep one serialized mutation lock and allow read-only snapshots/replay without exposing payload content.

**Step 4: Generalize the existing runtime adapter narrowly**

Extract the current native-event snapshot/validation, tool ledger, callback/usage accounting, and public run-event production in `AsterionPrimeSession` into one application-neutral `PrimeExecutionKernel` under `agents/prime`. Both the existing P7 session and the new persistent backend call this kernel; neither copies its event loop. Replace the exact `type(session) is AsterionPrimeSession` check with a private runtime-session protocol containing only `run(request, signal)`. Keep manifest identity/capabilities exact. This is the concrete seam that prevents the backend from becoming a parallel session engine while preserving P7 behavior.

**Step 5: Run Gate G3 and commit**

```bash
uv run python -m unittest -v tests.test_asterion_prime_store tests.test_asterion_prime_backend tests.test_asterion_prime_session tests.test_prime_p7_native_installed
```

Expected: PASS, including P7 regressions.

```bash
git add src/asterion/agents/prime/state.py src/asterion/agents/prime/store.py src/asterion/agents/prime/backend.py src/asterion/agents/prime/execution.py src/asterion/agents/prime/session.py src/asterion/runtimes/asterion_prime.py tests/test_asterion_prime_store.py tests/test_asterion_prime_backend.py tests/test_asterion_prime_session.py
git commit -m "feat: add shared prime session backend"
```

---

### Task 5: Attach native control and session-context clients to the shared backend

**Files:**

- Create: `src/asterion/control/providers/asterion_prime/__init__.py`
- Create: `src/asterion/control/providers/asterion_prime/client.py`
- Create: `src/asterion/control/providers/asterion_prime/factory.py`
- Create: `src/asterion/control/providers/asterion_prime/resources/control-plane.json`
- Modify: `pyproject.toml`
- Create: `tests/test_asterion_prime_control.py`
- Create: `tests/test_asterion_prime_recovery.py`

**Step 1: Write failing factory/client tests**

Assert exact identity `asterion.prime-control@1.0.0`, exact sorted commands/events/capabilities, required shared backend host service, exact session/generation/authority agreement, control event replay, context receipt validation, authority synchronization, selected-only construction, close-detaches-without-closing-backend, and redaction.

```python
def test_binding_is_exact_and_sorted(self) -> None:
    binding = asterion_prime_control_plane_binding()
    self.assertEqual(binding.control_plane_id, "asterion.prime-control")
    self.assertEqual(binding.version, "1.0.0")
    self.assertEqual(binding.commands, tuple(sorted(binding.commands)))
    self.assertEqual(binding.events, tuple(sorted(binding.events)))

async def test_client_pushes_every_authority_snapshot(self) -> None:
    await client.sync_authority_snapshot(remaining_budget())
    self.assertEqual(backend.snapshot().authority_revision, AUTHORITY_REVISION)
```

Run: `uv run python -m unittest -v tests.test_asterion_prime_control tests.test_asterion_prime_recovery`

Expected: FAIL because the provider is absent.

**Step 2: Implement the narrow adapter and manifest**

`AsterionPrimeControlPlaneClient` implements both `ControlPlaneClient` and `SessionContextClient` by delegating to one backend attachment. It validates each returned closed-contract object before returning it and maps all internal errors to fixed public-safe messages.

The manifest must use the existing closed command/event sets and declare `SESSION_CONTEXT_CAPABILITY`'s exact value. The complete resource is:

```json
{
  "protocol": "asterion.control-plane/v1",
  "control_plane_id": "asterion.prime-control",
  "version": "1.0.0",
  "commands": [
    "action.resolve", "checkpoint.request", "input.submit", "session.attach",
    "session.cancel", "session.create", "session.detach", "session.pause", "session.resume"
  ],
  "events": [
    "action.proposed", "budget.reported", "checkpoint.created", "fault.raised",
    "goal.updated", "session.budget-limited", "session.cancelled", "session.completed",
    "session.created", "session.failed", "session.paused", "session.recovery-required",
    "session.running"
  ],
  "capabilities": ["checkpointing", "event-replay", "session-lifecycle", "session.context-v1"],
  "checkpoint_version": "1.0.0",
  "compatibility_ids": ["asterion.agent-control/v1", "asterion.session-context/v1"],
  "continuation_media_type": "application/vnd.asterion.prime-continuation"
}
```

The factory must compare the parsed manifest against `CONTROL_COMMAND_TYPES`, `CONTROL_EVENT_TYPES`, and `SESSION_CONTEXT_CAPABILITY`, so drift fails closed. Add the resource to wheel artifacts.

**Step 3: Prove clean host reconstruction**

The recovery test must:

1. construct `ControlHost` with a new `FileCanonicalJournal` and a pristine ledger from the same authority envelope;
2. complete stage-one control/context work and close the host (which closes its journal/client attachment);
3. reopen the same journal path, reconstruct recovery state, create a new client attachment and `ControlHost`, and verify generation/cursor/checkpoint/authority identity;
4. issue continuation and prove the backend call count does not replay compact or stage one;
5. close the second host, then close the backend exactly once.

**Step 4: Run Gate G4 and commit**

```bash
uv run python -m unittest -v tests.test_asterion_prime_control tests.test_asterion_prime_recovery tests.test_control_provider tests.test_control_recovery
uv build --wheel
```

Expected: PASS; the wheel contains the native manifest; legacy `asterion.control.providers.prime` tests remain unchanged.

```bash
git add src/asterion/control/providers/asterion_prime pyproject.toml tests/test_asterion_prime_control.py tests/test_asterion_prime_recovery.py
git commit -m "feat: attach prime backend to native control"
```

---

### Task 6: Implement the restricted P1 worker, fixed fixture, oracle, and receipt

**Files:**

- Create: `src/asterion/applications/prime/p1/__init__.py`
- Create: `src/asterion/applications/prime/p1/task.py`
- Create: `src/asterion/applications/prime/p1/ipython_host.py`
- Create: `src/asterion/applications/prime/p1/worker.py`
- Create: `src/asterion/applications/prime/p1/worker_main.py`
- Create: `src/asterion/applications/prime/p1/oracle.py`
- Create: `src/asterion/applications/prime/p1/receipt.py`
- Create: `tests/test_asterion_prime_p1_worker.py`
- Create: `tests/test_asterion_prime_p1_oracle.py`

**Step 1: Write failing two-stage and adversarial oracle tests**

The host seeds only a deterministic input tuple and task statement, never solution code or the final value. In stage-one setup, the model must define `AffineAccumulator`, instantiate `accumulator`, and write `stage-one.json` inside the assigned worker directory. In a distinct stage-one verification turn, the model must call the same object, read the exact file, and leave a `stage_one_verified` record. After compact/reconstruction, stage two must use the same object identity and exact file bytes to compute `final_result`. Test persistent PID/namespace, the two distinct stage-one turns, code/output caps, cancellation, duplicate request IDs, forbidden file escapes/imports/network/process access, and teardown.

```python
async def test_two_stages_share_worker_but_not_oracle_authority(self) -> None:
    await worker.start()
    pid = worker.snapshot().pid
    await worker.execute_cell(stage_one_setup_cell())
    await worker.execute_cell(stage_one_verification_cell())
    stage_one = oracle.verify_stage_one(worker.snapshot())
    await worker.execute_cell(stage_two_cell())
    final = oracle.verify_stage_two(worker.snapshot(), stage_one)
    self.assertEqual(worker.snapshot().pid, pid)
    self.assertTrue(final.succeeded)
    self.assertNotIn("expected_answer", worker.public_namespace())
```

Adversarial tests must prove self-reported success, overwritten display text, fabricated receipt data, and direct oracle access cannot pass.

Run: `uv run python -m unittest -v tests.test_asterion_prime_p1_worker tests.test_asterion_prime_p1_oracle`

Expected: FAIL because P1 modules are absent.

**Step 2: Implement the restricted persistent worker**

Define the narrow interface:

```python
class P1Worker(Protocol):
    @property
    def identity(self) -> P1WorkerIdentity: ...
    async def start(self) -> None: ...
    async def execute_cell(self, request: P1CellRequest) -> P1CellReceipt: ...
    def snapshot(self) -> P1InstrumentationSnapshot: ...
    async def close(self) -> P1WorkerCleanupReceipt: ...
```

Implement a provider-owned `P1WorkerProcess` in `ipython_host.py`; do not change or claim reuse of `ControlledExecutorService`, whose request/response API is non-interactive. `P1WorkerProcess` owns one `subprocess.Popen` handle, bounded JSONL stdin/stdout threads, PID/process-group cancellation, one absolute deadline, and exactly-once reap logic patterned after `PiRpcSession`. It launches the fixed preflighted worker interpreter by direct argv with an empty environment except explicit locale/encoding values, an exact temporary cwd, inherited root directory FD, and `worker_main.py` loaded from the installed package.

`worker_main.py` first imports and initializes trusted IPython plus the small allowlisted stdlib surface, then installs cell-execution restrictions. The audit hook rejects later socket creation, process spawn/exec, dynamic native-library loading, and opens outside the descriptor-validated worker root. The cell builtins expose an allowlisted `__import__`; environment starts empty and `os` is not exposed, rather than claiming an audit hook can intercept every environment read. Oracle/host objects are never placed in the namespace. The JSONL bridge enforces `65536` output bytes, `16384` code bytes, exact request IDs, one active cell, and poison-after-possible-dispatch semantics. Tests must attempt `open('../...')`, `/etc/passwd`, `os`, `subprocess`, `socket`, `ctypes`, and environment reads; do not describe these controls as an OS security sandbox.

**Step 3: Implement read-only instrumentation and safe receipt projection**

The oracle consumes immutable snapshots—not model text or self-reported flags—with: PID-derived worker identity digest; namespace creation nonce; cwd device/inode digest; committed cell sequence/digests; the class name and callable behavior probe; `id(accumulator)` captured after each stage; exact `stage-one.json` bytes and SHA-256 from the host-opened directory FD; `stage_one_verified` value; `final_result`; seeded symbol inventory captured before the first cell; and audit-denial counters. It independently recomputes all expected stage invariants from the host-owned input tuple, verifies no final symbol/code was seeded, and checks setup → verification → compact checkpoint → stage-two ordering.

```python
@dataclass(frozen=True, slots=True)
class P1NativeReceipt:
    application: Literal["prime.ipython-coding@1.0.0"]
    runtime: Literal["asterion.prime"]
    kernel_generation: int
    worker_identity_sha256: str
    checkpoint_sha256: str
    compact_receipt_sha256: str
    stage_one_effect_sha256: str
    stage_two_effect_sha256: str
    oracle_receipt_sha256: str
    cleanup_receipt_sha256: str
    compact_usage: Literal["reservation-charged"]
    before_context_tokens: int
    after_context_tokens: int
    control_reconstruction_generation: int
    final_status: Literal["verified"]

    def sha256(self) -> str: ...
```

Each referenced receipt is an immutable safe projection digest-bound to its exact identity and predecessor; the final receipt validates that worker identity is unchanged, context count reduced, reconstruction advanced the attachment generation without changing kernel generation, oracle status is verified, and every cleanup bit is sealed. No receipt field may contain private values; runtime publishes only artifact ID, media type `application/vnd.asterion.prime.p1-native-receipt+json`, and SHA-256.

**Step 4: Verify and commit**

```bash
uv run python -m unittest -v tests.test_asterion_prime_p1_worker tests.test_asterion_prime_p1_oracle
```

Expected: PASS; all adversarial cases fail closed with fixed messages.

```bash
git add src/asterion/applications/prime/p1 tests/test_asterion_prime_p1_worker.py tests/test_asterion_prime_p1_oracle.py
git commit -m "feat: add native prime p1 worker and oracle"
```

---

### Task 7: Publish the exact P1 package, assembly, and single runtime dispatch

**Files:**

- Create: `src/asterion/capabilities/prime_ipython_coding_native/__init__.py`
- Create: `src/asterion/capabilities/prime_ipython_coding_native/provider.py`
- Create: `src/asterion/capabilities/prime_ipython_coding_native/host.py`
- Create: `src/asterion/capabilities/prime_ipython_coding_native/payload/capability-package.json`
- Create: `src/asterion/capabilities/prime_ipython_coding_native/payload/capabilities/prime-ipython-coding.json`
- Create: `src/asterion/applications/prime/assemblies/prime-ipython-coding.json`
- Create: `src/asterion/applications/prime/p1/runtime_binding.py`
- Modify: `src/asterion/applications/first_party_packages.py`
- Modify: `src/asterion/applications/prime/provider.py`
- Modify: `src/asterion/applications/prime/runtime_binding.py`
- Modify: `pyproject.toml`
- Create: `tests/test_asterion_prime_p1_provider.py`
- Create: `tests/test_asterion_prime_p1_runtime.py`
- Create: `tests/test_asterion_prime_p1_installed.py`

**Step 1: Write failing metadata, selection, and installed-wheel tests**

Assert these exact identities:

```python
self.assertEqual(provider.provider_id, "prime-applications")
self.assertEqual(application.application_id, "prime.ipython-coding")
self.assertEqual(application.version, "1.0.0")
self.assertEqual(application.capability_packages, (CapabilityPackageRef("prime-ipython-coding-native", "1.0.0"),))
self.assertEqual(application.runtime_ids, ("asterion.prime",))
self.assertEqual(runtime_bindings.count("asterion.prime"), 1)
```

Also assert the exact application-index entry resolves to `asterion.applications.prime:create_provider`, P7 still resolves through the same provider, selected-only imports hold in a clean subprocess, missing/extra host capabilities reject before runtime construction, arrays are sorted/unique, and installed resources are present.

Run:

```bash
uv run python -m unittest -v tests.test_asterion_prime_p1_provider tests.test_asterion_prime_p1_runtime tests.test_asterion_prime_p1_installed
```

Expected: FAIL because the application/package are absent and the index still points to the legacy provider.

**Step 2: Add the closed package and assembly metadata**

The capability is `prime.ipython-coding@1.0.0`, package `prime-ipython-coding-native@1.0.0`, runtime `asterion.prime`, and input contract accepts only literal `fixed-small-verification`. Declare exactly these sorted host capabilities:

```python
P1_HOST_CAPABILITIES = (
    "prime.ipython",
    "prime.p1-oracle",
    "prime.pi-extension",
    "prime.private-trace",
    "prime.session-backend",
)
```

Register the package explicitly in `builtin_capability_registrations()`; do not scan source roots.

**Step 3: Dispatch both P1 and P7 from one runtime binding**

```python
def build_asterion_prime_runtime(context: RuntimeFactoryContext) -> AgentRuntimeClient:
    key = (context.application_id, context.application_version)
    if key == ("prime.ipython-coding", "1.0.0"):
        return build_p1_runtime(context)
    if key == ("prime.arc-agi-3-solving", "1.0.0"):
        return build_p7_runtime(context)
    raise RuntimeFactoryError("Asterion-prime runtime configuration is invalid")
```

Move P7-specific construction behind `build_p7_runtime` without changing its public behavior. P1 runtime waits on backend stage barriers and never imports `ControlHost` or the coordinator. Its projector maps budget exhaustion to terminal `run.failed` code `p1_budget_limited`, uncertain recovery to `p1_recovery_required`, and success to one receipt artifact followed by `run.completed`.

**Step 4: Migrate only the public P1 index**

Change:

```toml
"prime.ipython-coding__1.0.0" = "asterion.applications.prime:create_provider"
```

Keep legacy explicit `prime-agent` applications and host-service entries available under their existing provider; do not make native modules import them.

**Step 5: Verify packaging and commit**

```bash
uv run python -m unittest -v tests.test_asterion_prime_p1_provider tests.test_asterion_prime_p1_runtime tests.test_asterion_prime_p1_installed tests.test_prime_application_provider tests.test_application_discovery tests.test_prime_p7_native_installed
uv build --wheel
```

Expected: PASS with exactly one `asterion.prime` binding.

```bash
git add src/asterion/capabilities/prime_ipython_coding_native src/asterion/applications/prime/assemblies/prime-ipython-coding.json src/asterion/applications/prime/p1/runtime_binding.py src/asterion/applications/first_party_packages.py src/asterion/applications/prime/provider.py src/asterion/applications/prime/runtime_binding.py pyproject.toml tests/test_asterion_prime_p1_provider.py tests/test_asterion_prime_p1_runtime.py tests/test_asterion_prime_p1_installed.py
git commit -m "feat: publish native prime p1 application"
```

---

### Task 8: Add the parameter-free operator coordinator and provider-free closed loop

**Files:**

- Create: `src/asterion/applications/prime/p1/operator.py`
- Create: `src/asterion/applications/prime/p1/coordination.py`
- Modify: `Makefile`
- Create: `tests/test_asterion_prime_p1_operator.py`
- Modify: `tests/test_prime_make_presets.py`

**Step 1: Write a failing coordinator choreography test**

Use fake model/Pi adapters but real assembly, backend, worker, journals, authority, `ControlHost`, runner, and recovery constructors. Assert exact temporal order and teardown:

```python
self.assertEqual(trace, [
    "backend.open", "host1.open", "runner.start", "stage1.complete",
    "compact.admit", "compact.provider-call", "compact.persist", "host1.close", "journal.reopen",
    "host2.recover", "authority.sync", "resume.admit", "resume.persist",
    "stage2.release", "stage2.complete", "oracle.pass", "host2.close",
    "worker.close", "pi.close", "backend.close", "runner.terminal",
])
self.assertEqual(trace.count("compact.provider-call"), 1)
```

Add subtests for cancellation at every barrier, compact pre-dispatch rejection, known no-mutation failure, malformed/post-mutation response, host reconstruction failure, stage-two failure, budget exhaustion, and cleanup failure. The first two keep prior state; unknown outcomes fence recovery and never release stage two.

Run: `uv run python -m unittest -v tests.test_asterion_prime_p1_operator tests.test_prime_make_presets`

Expected: FAIL because the coordinator and target are absent.

**Step 2: Implement provider-owned concurrent coordination**

`P1Coordination` owns private futures `stage_one_ready`, `stage_two_ready`, `execution_stopped`, and `finalization_ready`. The P1 runtime session sets stage milestones with digest-only receipts. On success, budget limit, cancellation, or recovery failure it records the pending terminal classification, stops starting effects, sets `execution_stopped`, and waits on `finalization_ready`; it cannot emit an artifact or terminal before finalization. The coordinator never consumes or manufactures runtime events. `_wait_milestone_or_stopped()` uses `asyncio.wait(FIRST_COMPLETED)` over the milestone, `execution_stopped`, and the runner task under the absolute run deadline. A runner exception before `execution_stopped` enters the bounded forced-stop/cleanup path, so no task can hang if execution fails early.

```python
async def run_fixed_small_verification(resources: P1OperatorResources) -> P1PublicResult:
    runtime_task = asyncio.create_task(
        run_composed_application(
            resources.plan,
            implementations=resources.implementations,
            runtime=resources.runtime,
            run_id=resources.run_id,
            input_text="fixed-small-verification",
            host_services=resources.host_services,
        )
    )
    try:
        await _wait_milestone_or_stopped(resources.coordination.stage_one_ready, resources.coordination)
        manager = resources.host.session_context_manager
        assert manager is not None
        compact_receipt = await manager.execute(resources.compact_command())
        await resources.close_first_host()
        resources.host = await resources.reconstruct_control_host_and_journal()
        recovered_manager = resources.host.session_context_manager
        assert recovered_manager is not None
        resume_receipt = await recovered_manager.execute(resources.resume_command(compact_receipt))
        resources.coordination.release_stage_two(resume_receipt)
        stage_two = await _wait_milestone_or_stopped(resources.coordination.stage_two_ready, resources.coordination)
        oracle_receipt = resources.oracle.verify(resources.snapshots(), stage_two)
        cleanup_receipt = await resources.close_in_owner_order()
        resources.coordination.release_finalization(oracle_receipt, cleanup_receipt)
        return await runtime_task
    except BaseException:
        classification = resources.coordination.classify_pending_failure()
        resources.coordination.request_stop(classification)
        await resources.coordination.execution_stopped
        cleanup_receipt = await resources.close_in_owner_order()
        resources.coordination.release_failure_finalization(classification, cleanup_receipt)
        return await runtime_task
```

Implement the Python 3.10-compatible equivalent with explicitly owned tasks and `try/except/finally`; do not require `asyncio.TaskGroup`. `close_in_owner_order()` is idempotent and first aborts/settles any active model/tool/context effect, then closes application resources, current host attachment/journal, worker, Pi process, extension lease, sockets, and private backend/store. It returns a complete cleanup receipt only after all owners report closed. Only then does `release_finalization` transfer safe receipt digests and the exact pending classification to the runtime, which emits the appropriate completed, `p1_budget_limited`, cancelled, or `p1_recovery_required` terminal. Catastrophic failure before the runtime reaches `execution_stopped` uses a bounded forced-stop path, still performs owner cleanup before cancelling/awaiting the runner task, and is tested as a protocol failure rather than a successful terminal. Runtime/control communicate only through `P1Coordination` and durable backend records; neither calls the other.

**Step 3: Add the fixed command surface**

`asterion.applications.prime.p1.operator:main` is an installed-distribution launcher: it asserts `asterion.__file__` is not beneath the source checkout, resolves the operator root from the fixed `ASTERION_PRIME_OPERATOR_ROOT` injected by the Make preset, reads that root's `.env`, verifies the `ASTERION_PRIME_SOURCE_ROOT` checkout/compaction closure lock, and validates a fixed preflighted worker interpreter containing the pinned IPython version. It validates the live model price through Task 0's calculator, performs all host preflight, builds exact resources, and invokes only `fixed-small-verification`. It accepts no provider/model/cost/deadline arguments and prints only public-safe status. Preflight rejects before starting Pi or the worker if the price, locks, interpreter, services, or authority cannot be proven; these operator paths never enter manifests or public receipts.

Add:

```make
asterion-prime-p1-run:
	@exec /bin/sh -ec 'build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p1-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; [ "$$#" -eq 1 ] && [ -f "$$1" ]; \
		printf '\''%s\n'\'' '\''[asterion-prime-p1-run] native Asterion-prime fixed small verification'\'' >&2; \
		orb -m "$(PRIME_ORB_MACHINE)" -u root -w /tmp /bin/sh -ec '\''unset PYTHONPATH ASTERION_PRIME_NODE; export ASTERION_PRIME_OPERATOR_ROOT="$$2"; export ASTERION_PRIME_WORKER_PYTHON="$$2/../external-prime/arc-agi-3/venv/bin/python"; exec /root/.local/bin/uv run --isolated --with "$$1" --with "python-dotenv>=1.0.0" python -I -m asterion.applications.prime.p1.operator'\'' asterion-prime-p1-run "$$1" "$(CURDIR)"'
```

Update `.PHONY`, help output, and preset tests. The build directory is deliberately created beneath the repository mount so both the host shell and Orb VM can access the exact wheel; validate that assumption in the installed-route test and always remove the directory on exit. The installed-route test must build the wheel, run from a temporary directory with `PYTHONPATH` unset and `python -I`, and assert imported package/resources/entry-point metadata all originate from the installed wheel environment.

**Step 4: Run Gate G6 and commit**

```bash
uv run python -m unittest -v tests.test_asterion_prime_p1_operator tests.test_prime_make_presets tests.test_asterion_prime_p1_installed
```

Expected: PASS; provider-free fake loop proves exact-once settlement and cleanup-before-terminal.

```bash
git add src/asterion/applications/prime/p1/operator.py src/asterion/applications/prime/p1/coordination.py Makefile tests/test_asterion_prime_p1_operator.py tests/test_prime_make_presets.py
git commit -m "feat: run native prime p1 verification"
```

---

### Task 9: Run installed, full, promotion, security, and bounded-live acceptance

**Files:**

- Modify: `docs/status/CURRENT-STATE.md`
- Modify: `docs/status/DECISIONS.md`
- Modify: `docs/status/INDEX.md`
- Modify: `docs/status/JOURNAL.md`
- Modify: `docs/status/RESUME-NEXT-SESSION.md`
- Modify: `MEMORY.md` only if its existing index is stale

**Step 1: Run the focused provider-free acceptance suite**

```bash
uv run python -m unittest -v \
  tests.test_asterion_prime_pi_contract \
  tests.test_pi_rpc_reusable \
  tests.test_asterion_prime_context \
  tests.test_session_context_manager \
  tests.test_asterion_prime_store \
  tests.test_asterion_prime_backend \
  tests.test_asterion_prime_control \
  tests.test_asterion_prime_recovery \
  tests.test_asterion_prime_p1_worker \
  tests.test_asterion_prime_p1_oracle \
  tests.test_asterion_prime_p1_provider \
  tests.test_asterion_prime_p1_runtime \
  tests.test_asterion_prime_p1_operator \
  tests.test_asterion_prime_p1_installed
npm --prefix packages/typescript/asterion-prime-extension test
```

Expected: PASS without provider calls or `.env` reads.

**Step 2: Run the installed-distribution gate**

```bash
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT HUP INT TERM
uv build --wheel --out-dir "$tmp_dir"
set -- "$tmp_dir"/asterion-*.whl
test "$#" -eq 1 && test -f "$1"
wheel_path="$1"
env -u PYTHONPATH uv run --isolated --directory "$tmp_dir" --with "$wheel_path" python -I "$(pwd)/tests/test_asterion_prime_p1_installed.py" -v
```

Expected: PASS with imports and entry-point metadata originating outside the source checkout.

**Step 3: Perform contract/security review before spending live authority**

Review exact identities, selected-only imports, dependency direction, immutable inputs/results, manifest contents, pre-execution rejection, cost calculation, reservation settlement, journal recovery, outstanding-effect fences, descriptor closure, worker teardown, sentinel-secret redaction, receipt digest, and one terminal event. Run a focused source scan:

```bash
rg -n "dotenv|os\.environ|provider|model|prompt|summary|cell|output|_FD" \
  src/asterion/agents/prime \
  src/asterion/control/providers/asterion_prime \
  src/asterion/applications/prime/p1 \
  src/asterion/capabilities/prime_ipython_coding_native
```

Expected: only operator/preflight code handles provider configuration; public projectors and metadata contain no private payloads.

**Step 4: Run the one authorized bounded live acceptance**

```bash
make asterion-prime-p1-run
```

Expected public-safe result:

- installed application resolves as `prime-applications / prime.ipython-coding@1.0.0 / asterion.prime`;
- stage one and stage two use one worker identity;
- real Pi witness proves non-empty input and reduced Asterion rebuilt-context count;
- compact is charged as `reservation-charged` within `16000` tokens / `125000` micro-units;
- host/journal/client are reconstructed cleanly in-process;
- continuation does not replay stage one or compact;
- oracle passes from instrumentation;
- cleanup completes;
- exactly one receipt artifact precedes `run.completed`.

If the backend is unavailable, record `External-limited`; if not run, record `Not rerun`. Neither is completion.

**Step 5: Run repository and promotion gates after successful live acceptance**

```bash
make test
make lint
make docs-check
make check
make promotion-check
```

Expected: all PASS. A failure outside changed surfaces must be classified with evidence; do not report PASS if not rerun.

**Step 6: Update durable evidence and commit**

Record named commands and exact outcomes. Classify statements as verified fact, current judgment, historical archive, or unfinished boundary. Do not claim host-process/Pi/worker crash recovery.

```bash
git add docs/status/CURRENT-STATE.md docs/status/DECISIONS.md docs/status/INDEX.md docs/status/JOURNAL.md docs/status/RESUME-NEXT-SESSION.md
test ! -e MEMORY.md || git add MEMORY.md
git commit -m "docs: record native prime p1 acceptance"
git status --short
```

Expected: only pre-existing unrelated user changes remain. If this session owns every remaining change, status is empty.

## Final Acceptance Checklist

- `prime.ipython-coding@1.0.0` resolves from the installed public index to `prime-applications`.
- Exactly one `asterion.prime` runtime binding dispatches P1/P7 by exact application/version.
- One Pi child executes prompt → real compact → prompt under one absolute deadline.
- One persistent restricted IPython worker survives both stages.
- The compact witness proves real non-empty source and reduced deterministic rebuilt-context units.
- Compact authority covers both possible built-in summary branches before mutation.
- All post-dispatch unknown outcomes are durably uncertain and recovery-fenced.
- Reconstructed `ControlHost`, journal, client attachment, generation, cursor, checkpoint, and authority agree.
- Continuation resumes without replay and every authority snapshot reaches the backend.
- Oracle decisions come only from read-only instrumentation.
- Public output and failures are redacted; compact usage is labeled `reservation-charged`.
- Receipt digest, exact-once settlement, cleanup-before-terminal, and one terminal event are verified.
- Provider-free, installed-wheel, `make check`, `make promotion-check`, and bounded-live gates have named PASS evidence.
