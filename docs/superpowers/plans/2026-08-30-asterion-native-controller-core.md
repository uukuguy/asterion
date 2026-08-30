# Asterion Native Durable Controller Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a provider-free, single-session `asterion.native` control provider whose commands, deterministic turns, events, budgets, checkpoints, and crash recovery are durable and exactly replayable without promoting any compound Native parity row.

**Architecture:** Keep `ControlHost` authoritative and implement a separate provider-private event-sourced controller behind the existing `ControlPlaneClient`. A segmented hash-chain journal and private capsule store feed a pure reducer; a deterministic injected turn adapter produces closed event drafts, while the client provides async command/replay semantics and the exact factory exposes the selected provider.

**Tech Stack:** Python 3.10+, stdlib `asyncio`, immutable dataclasses, descriptor-relative `os`/`fcntl` persistence, SHA-256 canonical JSON, `unittest`, existing Asterion control contracts, Make, and the repository Climb adapter.

## Global Constraints

- The approved design is `docs/superpowers/specs/2026-08-30-asterion-native-controller-core-design.md` at approval commit `ac1e9ef`.
- The pinned Prime baseline remains `a18809e00ea30638584d87b3afea7285a9d7296c`.
- `ControlHost` remains the sole owner of canonical state, authority, admission, runner execution, settlement, cancellation, and public evidence.
- The Native provider writes only its provider-private journal and capsules; it never writes the host `CanonicalJournal`.
- Do not modify the closed agent-control or control-plane schemas in this plan.
- Do not add a composer, application runner, package scanner, scheduler, credential reader, provider fallback, hidden precedence rule, registry, or symlink traversal.
- All Phase 3.1 tests are provider-free and must record zero provider, model, credential, network, upload, and application operations.
- Every public mapping stays closed, immutable, canonically ordered, and free of prompt bodies, credentials, provider payloads, raw output, and private paths.
- Use `unittest`, `TestNative...` classes, `test_<behavior>` names, and `subTest` matrices.
- Use test-driven development: failing test, observed RED, minimal implementation, observed GREEN, then focused commit.
- Keep implementation and planning on `main`; do not create a worktree or branch that cannot be closed in the same execution lane.
- Phase 3.1 may record only `native-controller-core: PASS`; it must leave all 61 compound `asterion.native` parity results Missing.
- Final closure requires a clean worktree, the sole local `main` branch, and no additional worktree.

## File Structure

### New provider modules

- `src/asterion/control/providers/native/model.py` — immutable private record, entry, state, turn-request/result, event-draft, and capsule metadata values.
- `src/asterion/control/providers/native/state.py` — closed record validation, record constructors, and pure journal reduction.
- `src/asterion/control/providers/native/store.py` — memory reference store and descriptor-relative segmented file store.
- `src/asterion/control/providers/native/capsule.py` — private capsule protocol, memory reference store, and file store.
- `src/asterion/control/providers/native/turn.py` — `NativeTurnAdapter` protocol and deterministic scripted implementation.
- `src/asterion/control/providers/native/controller.py` — command state machine, two-phase turn advancement, event allocation, and checkpoint flow.
- `src/asterion/control/providers/native/client.py` — async `ControlPlaneClient`, exact replay, lock ownership, close, and authority-snapshot sink.
- `src/asterion/control/providers/native/factory.py` — exact binding, manifest, option/service validation, and production construction.
- `src/asterion/control/providers/native/__init__.py` — intentionally narrow public provider exports.
- `src/asterion/control/providers/native/resources/control-plane.json` — packaged exact compatibility manifest.

### New verification files

- `tests/test_native_control_model.py`
- `tests/test_native_control_store.py`
- `tests/test_native_control_capsule.py`
- `tests/test_native_control_controller.py`
- `tests/test_native_control_client.py`
- `tests/test_native_control_factory.py`
- `tests/test_native_control_conformance.py`
- `tests/test_native_control_host.py`
- `tests/test_native_prime_differential.py`
- `tests/test_native_control_process_recovery.py`
- `tests/test_native_controller_core_verification.py`
- `tools/verify_native_controller_core.py`

### Existing integration files

- `pyproject.toml` — package the Native manifest resource.
- `Makefile` — add one provider-free Native core verification target.
- `tools/climb/cycle.sh` — add the exact clean H-038 closure gate.
- `tools/climb/regen-tree.py` — accept and render cycle 38 exactly once.
- `tests/test_prime_climb.py` — prove H-038 is dormant before execution and exact at closure.
- `docs/status/climb/hypotheses.yaml` — append H-038 pending, then promote only after its gate passes.
- `docs/status/climb/research-tree.md` and `session-state.json` — generated/current Climb successor state.
- `docs/status/PRIME-PARITY-LEDGER.md` — record the narrower Native core claim only after the gate passes.
- `docs/status/CURRENT-STATE.md`, `JOURNAL.md`, and `RESUME-NEXT-SESSION.md` — update structural and recovery state at the final boundary.

---

### Task 1: Open the exact dormant H-038 acceptance gate

**Files:**
- Modify: `docs/status/climb/hypotheses.yaml`
- Modify: `docs/status/climb/session-state.json`
- Modify: `docs/status/climb/research-tree.md`
- Modify: `tools/climb/cycle.sh`
- Modify: `tools/climb/regen-tree.py`
- Modify: `tests/test_prime_climb.py`

**Interfaces:**
- Consumes: canonical H-037 state and the approved Phase 3.1 spec.
- Produces: dormant hypothesis `H-038` and command identity `check.native-controller-core-provider-free`; it does not append cycle 38 before the final gate.

- [ ] **Step 1: Write failing dormant-gate tests**

Add constants and tests that require H-038 to be pending, absent from
`runs.csv`, and selected as the exact next action:

```python
EXPECTED_H038 = {
    "hypothesis": "H-038",
    "outcome": "passed",
    "command_id": "check.native-controller-core-provider-free",
}

def test_h038_is_dormant_until_native_core_gate_passes(self) -> None:
    hypotheses = (ROOT / "docs/status/climb/hypotheses.yaml").read_text()
    self.assertIn(
        "- id: H-038\n"
        "  description: Native durable controller core survives exact provider-free crash and replay gates\n"
        "  parent_paradigm: native-controller-core\n"
        "  ranking: 0.9\n"
        "  status: pending\n",
        hypotheses,
    )
    rows = (ROOT / "docs/status/climb/runs.csv").read_text().splitlines()
    self.assertEqual(sum(",H-038," in row for row in rows), 0)
    state = json.loads((ROOT / "docs/status/climb/session-state.json").read_text())
    self.assertEqual(state["next_action"], "H-038")
    tree = (ROOT / "docs/status/climb/research-tree.md").read_text()
    self.assertIn("- Next: H-038 — Native durable controller core", tree)
```

Add a mocked cycle test expecting exactly these commands before the state
transition:

```python
self.assertEqual(
    command_log.read_text().splitlines(),
    [
        "make test.native-controller-core.provider-free",
        "uv run python tools/verify_native_controller_core.py",
        "make check",
        "make promotion-check",
        "git diff --check",
    ],
)
```

- [ ] **Step 2: Run the tests and confirm RED**

Run:

```bash
uv run python -m unittest -v tests.test_prime_climb.TestPrimeClimb.test_h038_is_dormant_until_native_core_gate_passes
```

Expected: FAIL because H-038 and its exact successor state do not exist.

- [ ] **Step 3: Add the dormant hypothesis and exact gate**

Append this hypothesis without touching `runs.csv`:

```yaml
- id: H-038
  description: Native durable controller core survives exact provider-free crash and replay gates
  parent_paradigm: native-controller-core
  ranking: 0.9
  status: pending
```

Set `session-state.json` to the canonical compact mapping:

```json
{"last_hypothesis":"H-037","last_outcome":"passed","next_action":"H-038"}
```

Extend `cycle.sh` with a clean-tree gate, but do not run it yet:

```sh
  H-038)
    require_clean_tree
    make test.native-controller-core.provider-free
    uv run python tools/verify_native_controller_core.py
    make check
    make promotion-check
    git diff --check
    require_clean_tree
    python3 tools/climb/regen-tree.py H-038 passed phase-3.2-native-verified-loop-design check.native-controller-core-provider-free
    ;;
```

Add the accepted cycle-38 tuple to `regen-tree.py` and render either the pending
or completed boundary:

```python
(
    "H-038",
    "passed",
    "phase-3.2-native-verified-loop-design",
    "check.native-controller-core-provider-free",
): 38,
```

```python
if cycle == 37:
    rendered.append("- Next: H-038 — Native durable controller core")
elif cycle >= 38:
    rendered.extend((
        "- H-038: passed — Native durable controller core",
        "- Next: Phase 3.2 — Native Verified-loop",
    ))
```

- [ ] **Step 4: Run focused Climb tests**

Run:

```bash
uv run python -m unittest -v tests.test_prime_climb
```

Expected: PASS, with canonical `runs.csv` still ending at H-037.

- [ ] **Step 5: Commit the dormant acceptance boundary**

```bash
git add docs/status/climb/hypotheses.yaml docs/status/climb/session-state.json docs/status/climb/research-tree.md tools/climb/cycle.sh tools/climb/regen-tree.py tests/test_prime_climb.py
git commit -m "climb: open native controller core hypothesis"
```

### Task 2: Add the immutable Native record model and pure reducer

**Files:**
- Create: `src/asterion/control/providers/native/model.py`
- Create: `src/asterion/control/providers/native/state.py`
- Create: `tests/test_native_control_model.py`

**Interfaces:**
- Consumes: existing `ControlCommand`, `ControlEvent`, `BudgetUsage`, `RemainingBudget`, and closed protocol validators.
- Produces: `NativeRecord`, `NativeEntry`, `NativeEventDraft`, `NativeInputReference`, `NativeActionResultReference`, `NativeTurnRequest`, `NativeTurnResult`, `NativeCapsuleMetadata`, `NativeControllerState`, `reduce_native_entries()`, and closed record constructors used by every later task.

- [ ] **Step 1: Write failing immutable-model tests**

Cover canonical digesting, recursive freezing, closed record kinds, contiguous
reduction, command conflicts, usage monotonicity, terminal uniqueness, and
input immutability. Start with:

```python
class TestNativeControlModel(unittest.TestCase):
    def test_record_digest_is_canonical_and_payload_is_frozen(self) -> None:
        payload = {"system_id": "research.system", "generation": 1}
        record = NativeRecord("session-bound", "session.bound", payload)
        payload["generation"] = 2
        self.assertEqual(record.payload["generation"], 1)
        self.assertRegex(record.digest, r"^[0-9a-f]{64}$")
        self.assertNotIn("payload", repr(record))

    def test_reducer_rejects_gap_fork_and_second_terminal(self) -> None:
        for label, entries in invalid_prefixes():
            with self.subTest(label=label), self.assertRaises(NativeStateError):
                reduce_native_entries(entries)
```

- [ ] **Step 2: Run the model tests and confirm RED**

Run:

```bash
uv run python -m unittest -v tests.test_native_control_model
```

Expected: FAIL with `ModuleNotFoundError` for the Native provider model.

- [ ] **Step 3: Implement immutable values and canonical digesting**

Define the exact public signatures in `model.py`:

```python
NATIVE_JOURNAL_VERSION = "asterion.native-journal/v1"
NATIVE_RECORD_KINDS = frozenset({
    "session.bound",
    "authority.synced",
    "command.committed",
    "turn.started",
    "turn.committed",
    "turn.recovery-required",
    "checkpoint.committed",
})

@dataclass(frozen=True, repr=False)
class NativeRecord:
    record_id: str
    kind: str
    payload: Mapping[str, object]

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            {
                "record_id": self.record_id,
                "kind": self.kind,
                "payload": _json_value(self.payload),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

@dataclass(frozen=True)
class NativeEntry:
    position: int
    previous_digest: str | None
    record: NativeRecord

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            {
                "position": self.position,
                "previous_digest": self.previous_digest,
                "record": {
                    "record_id": self.record.record_id,
                    "kind": self.record.kind,
                    "payload": _json_value(self.record.payload),
                },
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

@dataclass(frozen=True)
class NativeEventDraft:
    type: str
    payload: Mapping[str, object]

@dataclass(frozen=True)
class NativeInputReference:
    input_id: str
    delivery: str
    content_ref: str
    command_digest: str

@dataclass(frozen=True)
class NativeActionResultReference:
    action_id: str
    resolution: str
    reason_code: str
    receipt_ref: str | None
    command_digest: str

@dataclass(frozen=True)
class NativeTurnRequest:
    turn_id: str
    session_id: str
    generation: int
    authority_revision: int
    causal_command_ids: tuple[str, ...]
    inputs: tuple[NativeInputReference, ...]
    action_results: tuple[NativeActionResultReference, ...]
    budget: RemainingBudget

@dataclass(frozen=True)
class NativeTurnResult:
    turn_id: str
    events: tuple[NativeEventDraft, ...]
    usage: BudgetUsage

@dataclass(frozen=True, repr=False)
class NativeCapsuleMetadata:
    capsule_id: str
    capsule_digest: str
    control_plane_id: str
    control_plane_version: str
    checkpoint_version: str
    covered_position: int
    covered_sequence: int
    storage_ref: str

@dataclass(frozen=True)
class NativeControllerState:
    provider_id: str | None
    provider_version: str | None
    checkpoint_version: str | None
    system_id: str | None
    system_version: str | None
    session_id: str | None
    generation: int | None
    lifecycle: str
    goal_id: str | None
    goal_status: str | None
    authority_id: str | None
    authority_revision: int | None
    budget_authority_revision: int | None
    remaining_budget: RemainingBudget | None
    command_digests: Mapping[str, str]
    pending_inputs: tuple[NativeInputReference, ...]
    pending_action_results: tuple[NativeActionResultReference, ...]
    pending_turn: NativeTurnRequest | None
    committed_turn_digests: Mapping[str, str]
    recovery_required_turn_ids: tuple[str, ...]
    fenced_turn_ids: tuple[str, ...]
    action_statuses: Mapping[str, str]
    action_receipt_refs: Mapping[str, str | None]
    usage: BudgetUsage
    events: tuple[ControlEvent, ...]
    next_sequence: int
    checkpoint: NativeCapsuleMetadata | None
    terminal_event_id: str | None
```

Use canonical JSON with sorted keys and compact separators for digests. Freeze
nested mappings and sequences without exposing values in `repr`.
`NativeRecord.digest` is the immutable record-identity digest used for equal
record-ID retries. `NativeEntry.digest` covers its position, predecessor, and
record and is the hash-chain value named by the final record file. A
`NativeTurnResult.usage` value is the nonnegative usage delta for that one
turn; the reducer adds it with checked arithmetic to cumulative `state.usage`,
and `budget.reported` always publishes that cumulative value because the host
contract consumes cumulative provider usage. Phase 3.1 turn validation
requires `application_tokens == child_tokens == 0` and
`aggregate_tokens == controller_tokens`; fake controller/cost usage may be
nonzero for budget tests but cannot impersonate host action or child usage.

- [ ] **Step 4: Implement closed record validation and reduction**

In `state.py`, expose constructors instead of open caller-built payloads:

- `session_bound_record(provider_id, provider_version, system_id,
  system_version, session_id, generation, checkpoint_version, authority_id,
  authority_revision) -> NativeRecord`;
- `authority_synced_record(authority_revision, budget) -> NativeRecord`, whose
  record ID is derived from the current command authority revision plus the
  canonical budget digest so an equal host retry is idempotent without
  collapsing a later authority revision that restores the same capacity;
- `command_committed_record(command, events) -> NativeRecord`;
- `turn_started_record(request) -> NativeRecord`;
- `turn_committed_record(result, events, *, adapter_invoked=True) -> NativeRecord`;
- `turn_recovery_required_record(turn_id, reason_code, events) -> NativeRecord`;
- `checkpoint_committed_record(metadata, event) -> NativeRecord`; and
- `reduce_native_entries(entries) -> NativeControllerState`.

Each constructor builds one exact field set, calls the same closed validator
used during decode, and returns a frozen `NativeRecord`. There is no generic
`record(kind, payload)` factory outside the model module.

The reducer validates every `NativeEntry`, previous entry digest, identity, command
digest, event generation/sequence, state transition, usage value, checkpoint,
and terminal before returning a frozen state.

- [ ] **Step 5: Run focused tests and commit**

```bash
uv run python -m unittest -v tests.test_native_control_model
uv run ruff check src/asterion/control/providers/native/model.py src/asterion/control/providers/native/state.py tests/test_native_control_model.py
git add src/asterion/control/providers/native/model.py src/asterion/control/providers/native/state.py tests/test_native_control_model.py
git commit -m "feat: define native controller state model"
```

Expected: all model tests and Ruff pass.

### Task 3: Implement memory and descriptor-relative segmented journals

**Files:**
- Create: `src/asterion/control/providers/native/store.py`
- Create: `tests/test_native_control_store.py`

**Interfaces:**
- Consumes: `NativeRecord`, `NativeEntry`, and `reduce_native_entries()`.
- Produces: `NativeStorageBudget`, `NativeStorageOwner`, `MemoryNativeStorageOwner`, one owning `NativeSessionDirectory.open(private_root, session_id, max_total_private_bytes)`, `NativeSessionStore`, `MemoryNativeSessionStore(owner, max_record_bytes)`, and `FileNativeSessionStore(session_directory, max_record_bytes)` with `position`, `append()`, `replay()`, and `close()`.

- [ ] **Step 1: Write failing memory/file store matrices**

Test equal append, conflicting record IDs, stale positions, reopen, two writers,
permissions, symlinks, replacement, missing/reordered/forked records, digest
corruption, oversized records, pre-existing committed-byte exhaustion,
temporary files, and close behavior:

```python
class TestNativeControlStore(unittest.TestCase):
    def test_file_store_reopens_exact_committed_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            session = NativeSessionDirectory.open(
                root, "session-1", max_total_private_bytes=1_000_000
            )
            store = FileNativeSessionStore(session, max_record_bytes=65_536)
            entry = store.append(0, bound_record())
            store.close()
            session.close()
            reopened_session = NativeSessionDirectory.open(
                root, "session-1", max_total_private_bytes=1_000_000
            )
            reopened = FileNativeSessionStore(
                reopened_session, max_record_bytes=65_536
            )
            self.addCleanup(reopened_session.close)
            self.addCleanup(reopened.close)
            self.assertEqual(reopened.replay(0), (entry,))

    def test_store_rejects_security_and_chain_failures_redacted(self) -> None:
        for label, corrupt in corruption_cases():
            with self.subTest(label=label), self.assertRaisesRegex(
                NativeStoreError, "native session store is unavailable"
            ) as raised:
                corrupt()
            self.assertNotIn("SENTINEL_SECRET", repr(raised.exception))
```

- [ ] **Step 2: Run tests and confirm RED**

```bash
uv run python -m unittest -v tests.test_native_control_store
```

Expected: FAIL because `store.py` does not exist.

- [ ] **Step 3: Implement the store protocol and memory reference**

```python
class NativeSessionStore(Protocol):
    @property
    def position(self) -> int:
        raise NotImplementedError
    def append(self, expected_position: int, record: NativeRecord) -> NativeEntry:
        raise NotImplementedError
    def replay(self, position: int = 0) -> tuple[NativeEntry, ...]:
        raise NotImplementedError
    def close(self) -> None:
        raise NotImplementedError

class MemoryNativeSessionStore:
    def __init__(
        self, owner: NativeStorageOwner, *, max_record_bytes: int
    ) -> None:
        self._owner = owner
        self._max_record_bytes = max_record_bytes
        self._entries: list[NativeEntry] = []
        self._by_record_id: dict[str, NativeEntry] = {}
        self._closed = False
```

Equal record-ID/digest replays return the existing entry and revalidate the
current durability boundary. Different digest or expected position raises the
same context-free `NativeStoreError`.

Define `NativeStorageBudget(maximum_bytes)` as the one shared tracker for
record and capsule publication. The factory initializes its used-byte count
from every exact validated regular final or temporary file already present
under the pinned `records` and `capsules` descriptors. Both stores reserve
before creating a temporary file. A handled pre-publication failure may unlink
only the temporary file created by that call, fsync the directory, and then
release the reservation; a retained temporary or published file retains its
bytes. This enforces the approved total
private-storage cap in addition to per-record and per-capsule caps.

`NativeSessionDirectory` exclusively owns the lifetime lock plus pinned
session, records, and capsules descriptors and the shared storage budget. It
is opened exactly once per client. File journal/capsule stores borrow that
owner and duplicate only the child descriptor they need; their `close()`
releases the duplicate, while `NativeSessionDirectory.close()` releases the
lock and owning descriptors after both stores close. Constructors and every
operation reject a closed owner.

`NativeStorageOwner` is the narrow common protocol exposing the shared budget,
`require_open()`, and `close()`. `MemoryNativeStorageOwner` supplies the same
total-cap/close behavior without filesystem descriptors so controller, capsule,
and client tests exercise identical ownership semantics.

- [ ] **Step 4: Implement segmented atomic file publication**

Use a direct hashed session directory, fixed `records` and `capsules` children,
a mode-0600 lock, and mode-0600 record files. Publish through:

```python
temporary = f".record-{position:020d}-{secrets.token_hex(16)}.tmp"
descriptor = os.open(
    temporary,
    os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW,
    0o600,
    dir_fd=records_fd,
)
os.fchmod(descriptor, 0o600)
_write_all(descriptor, encoded)
os.fsync(descriptor)
os.close(descriptor)
os.rename(temporary, final_name, src_dir_fd=records_fd, dst_dir_fd=records_fd)
os.fsync(records_fd)
```

Pin parent/session/records identities by descriptor, use a nonblocking
exclusive `flock`, reject platforms without integer `O_NOFOLLOW`, cap each
encoded record, and validate every final filename against its decoded entry.
Ignore uncommitted `.tmp` files during replay but never delete them implicitly.

The direct session child is
`sha256(session_id.encode("utf-8")).hexdigest()` with mode 0700; no directory
scan participates in selection. Each final filename is
`{position:020d}-{entry.digest}.record`. Its canonical JSON has exactly
`format`, `position`, `previous_digest`, `record`, and `entry_digest`, where
`format == NATIVE_JOURNAL_VERSION`, `record` has exactly `record_id`, `kind`,
and `payload`, and `entry_digest` recomputes from the other entry fields.
Decode rejects a trailing newline, duplicate JSON key, noncanonical
serialization, unsafe integer, unknown field, filename mismatch, or any chain
predecessor unequal to the previous `NativeEntry.digest`.

- [ ] **Step 5: Run store tests and commit**

```bash
uv run python -m unittest -v tests.test_native_control_model tests.test_native_control_store
uv run ruff check src/asterion/control/providers/native/store.py tests/test_native_control_store.py
git add src/asterion/control/providers/native/store.py tests/test_native_control_store.py
git commit -m "feat: persist native controller journal"
```

Expected: model/store tests pass, including reopen and security matrices.

### Task 4: Add the private capsule store and exact checkpoint receipts

**Files:**
- Create: `src/asterion/control/providers/native/capsule.py`
- Create: `tests/test_native_control_capsule.py`

**Interfaces:**
- Consumes: shared `NativeSessionDirectory`/`NativeStorageBudget`, exact provider/checkpoint identities, canonical capsule bytes, and covered journal/event positions.
- Produces: `NativeCapsuleStore`, `MemoryNativeCapsuleStore`, `FileNativeCapsuleStore`, and `NativeCapsuleMetadata` suitable for `checkpoint.committed`.

- [ ] **Step 1: Write failing capsule tests**

```python
def test_capsule_seal_is_idempotent_private_and_body_free(self) -> None:
    session = NativeSessionDirectory.open(
        root, "session-1", max_total_private_bytes=1_000_000
    )
    store = FileNativeCapsuleStore(session, max_capsule_bytes=65_536)
    self.addCleanup(session.close)
    self.addCleanup(store.close)
    first = store.seal(
        capsule_id="capsule-1",
        payload=b"SENTINEL_PRIVATE_CAPSULE",
        covered_position=7,
        covered_sequence=4,
    )
    second = store.seal(
        capsule_id="capsule-1",
        payload=b"SENTINEL_PRIVATE_CAPSULE",
        covered_position=7,
        covered_sequence=4,
    )
    self.assertEqual(first, second)
    self.assertNotIn("SENTINEL_PRIVATE_CAPSULE", repr(first))
    self.assertFalse(Path(first.storage_ref).is_absolute())
```

Add conflict, corrupt reopen, symlink, size cap, wrong mode, identity mismatch,
no-public-path, and combined record-plus-capsule total-cap cases.

- [ ] **Step 2: Run tests and confirm RED**

```bash
uv run python -m unittest -v tests.test_native_control_capsule
```

Expected: FAIL because the capsule store is absent.

- [ ] **Step 3: Implement memory and file capsule stores**

```python
class NativeCapsuleStore(Protocol):
    def seal(
        self,
        *,
        capsule_id: str,
        payload: bytes,
        covered_position: int,
        covered_sequence: int,
    ) -> NativeCapsuleMetadata:
        raise NotImplementedError
    def verify(self, metadata: NativeCapsuleMetadata) -> None:
        raise NotImplementedError
    def close(self) -> None:
        raise NotImplementedError
```

Construct the production implementation as
`FileNativeCapsuleStore(session_directory, max_capsule_bytes)`; it never opens
or locks the session root independently. Construct the reference implementation
as `MemoryNativeCapsuleStore(owner, max_capsule_bytes)` using the same
`MemoryNativeStorageOwner` already passed to the memory journal.

The file implementation uses the already pinned session/capsules descriptor,
exclusive mode-0600 creation, file and directory fsync, SHA-256 verification,
and an opaque `storage_ref` derived from the capsule identity rather than a
filesystem path. Equal content is idempotent; different bytes under the same
capsule ID conflict. It reserves the exact encoded size through the same
`NativeStorageBudget` instance as the journal, so record and capsule bytes
cannot independently exceed the configured total.

Derive `storage_ref` as the lowercase SHA-256 of the domain-separated capsule
ID and publish raw canonical capsule bytes as `<storage_ref>.capsule` under the
pinned descriptor. `seal()` returns metadata containing that opaque ref, the
payload SHA-256, exact provider/checkpoint versions, and covered positions.
`verify()` opens only that direct filename with no-follow, enforces mode/size,
and recomputes the digest. It never enumerates capsules to select one.

- [ ] **Step 4: Run focused tests and commit**

```bash
uv run python -m unittest -v tests.test_native_control_store tests.test_native_control_capsule
uv run ruff check src/asterion/control/providers/native/capsule.py tests/test_native_control_capsule.py
git add src/asterion/control/providers/native/capsule.py tests/test_native_control_capsule.py
git commit -m "feat: seal native continuation capsules"
```

### Task 5: Implement deterministic turns and the controller state machine

**Files:**
- Create: `src/asterion/control/providers/native/turn.py`
- Create: `src/asterion/control/providers/native/controller.py`
- Create: `tests/test_native_control_controller.py`

**Interfaces:**
- Consumes: one owning `NativeStorageOwner` (a production `NativeSessionDirectory` or test `MemoryNativeStorageOwner`), borrowed `NativeSessionStore` and `NativeCapsuleStore`, `NativeControllerState`, host commands, remaining budget, injected clock/ID factories, and a `NativeTurnAdapter`.
- Produces: `DeterministicNativeTurnAdapter` and `NativeController.accept()`, `begin_ready_turn()`, `turn_is_budget_limited()`, `commit_budget_limited_turn()`, `commit_turn()`, `fail_turn()`, `checkpoint()`, and `replay_events()`.

- [ ] **Step 1: Write failing lifecycle/turn/action tests**

Cover create, duplicate create, input delivery reference persistence, pause,
resume, detach, attach, cancel, action admission/terminal resolution, budget
limiting, invalid result fencing, checkpoint ordering, and one terminal:

```python
async def test_turn_commits_result_and_events_before_replay(self) -> None:
    controller = make_controller(script=one_action_script())
    await controller.accept(create_command())
    await controller.accept(input_command("input-1", "content-ref-1"))
    request = controller.begin_ready_turn()
    self.assertIsNotNone(request)
    result = await controller.execute_turn(request)
    controller.commit_turn(request, result)
    events = controller.replay_events(EventCursor(1, 3))
    self.assertEqual([event.type for event in events], [
        "budget.reported",
        "action.proposed",
    ])
```

```python
def test_action_cannot_advance_without_host_resolution(self) -> None:
    controller = controller_with_proposal()
    self.assertIsNone(controller.begin_ready_turn())

async def test_terminal_host_resolution_becomes_next_durable_turn_input(self) -> None:
    controller = controller_with_proposal()
    await controller.accept(terminal_resolution_command("action-1", "receipt-1"))
    request = controller.begin_ready_turn()
    self.assertEqual(request.action_results[0].receipt_ref, "receipt-1")
```

- [ ] **Step 2: Run tests and confirm RED**

```bash
uv run python -m unittest -v tests.test_native_control_controller
```

Expected: FAIL because turn/controller modules do not exist.

- [ ] **Step 3: Implement the adapter protocol and deterministic script**

```python
class NativeTurnAdapter(Protocol):
    @property
    def adapter_id(self) -> str:
        raise NotImplementedError
    async def execute(self, request: NativeTurnRequest) -> NativeTurnResult:
        raise NotImplementedError

class DeterministicNativeTurnAdapter:
    def __init__(
        self,
        scripts: Mapping[str, NativeTurnResult],
        *,
        adapter_id: str = "native.fake-turn/v1",
    ) -> None:
        if not isinstance(scripts, Mapping) or not isinstance(adapter_id, str):
            raise NativeTurnError("native turn adapter is invalid")
        self._scripts = MappingProxyType(dict(scripts))
        self._adapter_id = adapter_id

    async def execute(self, request: NativeTurnRequest) -> NativeTurnResult:
        result = self._scripts[_turn_script_key(request)]
        if result.turn_id != request.turn_id:
            raise NativeTurnError("native turn result is invalid")
        return result
```

Freeze scripts at construction, return no bodies in `repr`, and make equal turn
keys return equal canonical results. `_turn_script_key()` returns
`input:<content_ref>` for the earliest journal-ordered pending input or
`action:<action_id>:<resolution>` for the earliest journal-ordered terminal action
result; it rejects an empty or mixed-identity request instead of selecting an
implicit fallback.

- [ ] **Step 4: Implement controller command and event transitions**

Use explicit methods and no open mutation hooks:

```python
class NativeController:
    async def accept(self, command: ControlCommand) -> None:
        records = self._transition_command(self.state, command)
        self._append_many(records)
        if command.type == "checkpoint.request":
            self._ensure_checkpoint(str(command.payload["checkpoint_id"]))
    def sync_authority(self, budget: RemainingBudget) -> None:
        revision = self._require_bound_authority_revision()
        record = authority_synced_record(revision, budget)
        self._append_equal_or_new(record)
    def begin_ready_turn(self) -> NativeTurnRequest | None:
        request = self._next_turn_request(self.state)
        if request is not None:
            self._append(turn_started_record(request))
        return request
    def turn_is_budget_limited(self, request: NativeTurnRequest) -> bool:
        self._require_pending_turn(request)
        return not self._has_admissible_turn_budget(request.budget)
    def commit_budget_limited_turn(self, request: NativeTurnRequest) -> None:
        events = self._budget_limited_events(request)
        result = NativeTurnResult(request.turn_id, events=(), usage=BudgetUsage.zero())
        self._append(turn_committed_record(result, events, adapter_invoked=False))
    async def execute_turn(self, request: NativeTurnRequest) -> NativeTurnResult:
        return await self._turn_adapter.execute(request)
    def commit_turn(
        self, request: NativeTurnRequest, result: NativeTurnResult
    ) -> None:
        events = self._validated_turn_events(request, result)
        self._append(turn_committed_record(result, events))
    def fail_turn(self, request: NativeTurnRequest, reason_code: str) -> None:
        events = self._recovery_events(request, reason_code)
        self._append(turn_recovery_required_record(request.turn_id, reason_code, events))
    def checkpoint(self, checkpoint_id: str) -> ControlEvent:
        return self._ensure_checkpoint(checkpoint_id)
    def replay_events(self, cursor: EventCursor | None) -> tuple[ControlEvent, ...]:
        return self._validated_event_suffix(self.state.events, cursor)
```

Define the private helpers in the same class with these exact responsibilities:

- `_transition_command(state, command)` validates lifecycle/action state and
  returns `session.bound` plus `command.committed` for the first create, or one
  `command.committed` record for every later command; `admitted` keeps an
  action blocked, while `rejected`, `succeeded`, `failed`, `cancelled`, and
  `uncertain` enqueue one immutable action-result reference for the next turn;
  `session.cancel` also durably fences and clears an already-started turn;
  create emits exactly `session.created` then `session.running`, relying on the
  closed host reducer's `session.created` transition to initialize the goal as
  active and never emitting a duplicate `goal.updated(active)`;
- `_append(record)` compare-appends at the current position and immediately
  refreshes `self._state` by reducing the complete store prefix;
- `_append_many(records)` applies `_append` in order and stops on the first
  conflict without pretending the remaining records committed;
- `_append_equal_or_new(record)` suppresses only an equal last authority
  snapshot and otherwise delegates to `_append`;
- `_require_bound_authority_revision()` rejects authority synchronization
  before `session.bound` and returns the latest command revision otherwise;
- `_next_turn_request(state)` returns `None` unless an unconsumed input or
  terminal action-result reference is ready in a running nonterminal session;
  it uses the committed command digest(s) to derive one stable turn ID and
  carries the complete immutable reference(s), including delivery or receipt,
  into `NativeTurnRequest`; when `state.pending_turn` exists after recovery it
  returns that equal request so `turn.started` compare-append is idempotent;
- `_require_pending_turn(request)` rejects any request unequal to the reduced
  pending turn, and `_has_admissible_turn_budget(budget)` requires positive
  deadline plus positive controller and aggregate capacity;
- `_budget_limited_events(request)` allocates current cumulative
  `budget.reported` followed by the unique `session.budget-limited`; the
  corresponding `turn.committed` records `adapter_invoked=false`, so the
  closed journal needs no extra record kind and the adapter call count remains
  zero;
- `_validated_turn_events(request, result)` checks the pending turn, stable ID,
  closed drafts, checked addition of the per-turn usage delta to cumulative
  usage, the host-supplied remaining turn budget, and allocates contiguous
  `ControlEvent` values whose `budget.reported` payload is cumulative;
- `_recovery_events(request, reason_code)` allocates exactly `fault.raised`
  followed by `session.recovery-required`;
- `_seal_capsule(checkpoint_id)` canonically encodes reduced private state and
  calls the capsule store before returning metadata;
- `_checkpoint_event(metadata)` builds the closed existing checkpoint payload;
- `_ensure_checkpoint(checkpoint_id)` returns the equal committed checkpoint
  when present, otherwise seals/verifies the deterministic capsule and appends
  `checkpoint.committed`; this makes a host retry finish a request that crashed
  after `command.committed` or capsule publication without duplicating either;
- `_validated_event_suffix(events, cursor)` enforces generation and exact
  cursor bounds; and
- `close()` closes capsule then journal resources and finally the one owning
  `NativeStorageOwner` without appending a record.

Allocate event IDs from the injected ID factory, timestamps from the injected
RFC3339 clock, and sequences from reduced committed state. Immediate command
events commit with their command. Turn result and all turn events commit in one
record. Validate a result against the latest remaining budget before commit;
invalid/over-budget fake results commit only safe `fault.raised` and
`session.recovery-required` events.

- [ ] **Step 5: Run controller tests and commit**

```bash
uv run python -m unittest -v tests.test_native_control_model tests.test_native_control_store tests.test_native_control_capsule tests.test_native_control_controller
uv run ruff check src/asterion/control/providers/native/turn.py src/asterion/control/providers/native/controller.py tests/test_native_control_controller.py
git add src/asterion/control/providers/native/turn.py src/asterion/control/providers/native/controller.py tests/test_native_control_controller.py
git commit -m "feat: drive deterministic native controller turns"
```

### Task 6: Implement the asynchronous Native control client

**Files:**
- Create: `src/asterion/control/providers/native/client.py`
- Create: `tests/test_native_control_client.py`

**Interfaces:**
- Consumes: `NativeController`, exact `ControlPlaneManifest`, `ControlCommand`, `EventCursor`, and `RemainingBudget`.
- Produces: `NativeControlPlaneClient` implementing `ControlPlaneClient` plus `sync_authority_snapshot()`.

- [ ] **Step 1: Write failing client transport/reentrancy tests**

```python
class TestNativeControlClient(unittest.IsolatedAsyncioTestCase):
    async def test_send_is_durable_before_return_and_equal_retry_is_idempotent(self) -> None:
        client, store = make_client()
        command = create_command()
        await client.send(command)
        committed = store.position
        await client.send(command)
        self.assertEqual(store.position, committed)

    async def test_event_iterator_releases_lock_while_host_sends_resolution(self) -> None:
        client, _store = make_client(script=one_action_script())
        await client.send(create_command())
        await client.send(input_command("input-1", "content-ref-1"))
        seen = []
        async for event in client.events(EventCursor(1, 3)):
            seen.append(event.type)
            if event.type == "action.proposed":
                await client.send(admission_command("action-1"))
        self.assertIn("action.proposed", seen)
```

Also test close idempotency, post-close rejection, cursor conflicts, adapter
failure, authority snapshot equal retry, no lock across adapter await/yield, and
bounded advancement. Add a controlled adapter-await race where
`session.cancel` commits while the adapter is suspended; the recovered state
must contain one cancellation terminal, the started turn in
`fenced_turn_ids`, and no result event from the late adapter return.

- [ ] **Step 2: Run tests and confirm RED**

```bash
uv run python -m unittest -v tests.test_native_control_client
```

Expected: FAIL because the client does not exist.

- [ ] **Step 3: Implement client locking and bounded event advancement**

```python
class NativeControlPlaneClient:
    def __init__(
        self,
        *,
        manifest: ControlPlaneManifest,
        controller: NativeController,
        max_turns_per_poll: int,
        max_events_per_poll: int,
    ) -> None:
        self._manifest = manifest
        self._controller = controller
        self._lock = asyncio.Lock()
        self._closed = False

    @property
    def manifest(self) -> ControlPlaneManifest:
        return self._manifest

    async def send(self, command: ControlCommand) -> None:
        async with self._lock:
            self._require_open()
            await self._controller.accept(command)
    def events(self, cursor: EventCursor | None = None) -> AsyncIterator[ControlEvent]:
        self._require_open()
        return self._iterate(cursor)
    async def sync_authority_snapshot(self, budget: RemainingBudget) -> None:
        async with self._lock:
            self._require_open()
            self._controller.sync_authority(budget)
    async def close(self) -> None:
        async with self._lock:
            if not self._closed:
                self._controller.close()
                self._closed = True
```

The iterator takes one committed snapshot under the lock, releases it before
yield, notices commands sent during event processing, and repeats only until
the configured turn/event limit or quiescence. It never holds the lock while
awaiting the turn adapter.

`_require_open()` raises one context-free `NativeControlError` after close.
`_iterate(cursor)` repeatedly snapshots a replay suffix under the lock, yields
outside the lock, begins at most `max_turns_per_poll` stable requests, awaits
the adapter outside the lock only when `turn_is_budget_limited()` is false,
then reacquires the lock to commit the exact result. Adapter failures and
result-validation failures call `fail_turn()` under the lock; a budget-limited
request instead calls `commit_budget_limited_turn()` without invoking the
adapter. If a concurrent terminal command has durably fenced that exact
started turn, the late deterministic result is discarded without appending a
second terminal or recovery record. Any different pending-turn mismatch fails
closed as transport uncertainty. It stops at quiescence or
`max_events_per_poll` and carries the last yielded sequence forward so no event
is yielded twice in one iterator.

- [ ] **Step 4: Run focused tests and commit**

```bash
uv run python -m unittest -v tests.test_native_control_controller tests.test_native_control_client
uv run ruff check src/asterion/control/providers/native/client.py tests/test_native_control_client.py
git add src/asterion/control/providers/native/client.py tests/test_native_control_client.py
git commit -m "feat: expose native control client"
```

### Task 7: Add the exact factory, manifest resource, and package exports

**Files:**
- Create: `src/asterion/control/providers/native/factory.py`
- Create: `src/asterion/control/providers/native/__init__.py`
- Create: `src/asterion/control/providers/native/resources/control-plane.json`
- Create: `tests/test_native_control_factory.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `ControlPlaneFactoryContext`, injected host service `native-turn-adapter`, and options `session_id`, `generation`, `max_turns_per_poll`, `max_events_per_poll`, `max_record_bytes`, `max_capsule_bytes`, and `max_total_private_bytes`.
- Produces: `NATIVE_CONTROL_PLANE_ID`, `NATIVE_CONTROL_PLANE_VERSION`, `native_control_plane_binding()`, `build_native_control_plane_client()`, and a packaged exact manifest.

- [ ] **Step 1: Write failing factory and distribution tests**

```python
def test_binding_declares_only_phase31_capabilities(self) -> None:
    manifest = native_control_plane_binding().manifest
    self.assertEqual(manifest.control_plane_id, "asterion.native")
    self.assertEqual(manifest.version, "0.1.0")
    self.assertEqual(manifest.capabilities, (
        "action-proposals",
        "checkpointing",
        "event-replay",
        "session-lifecycle",
    ))
    self.assertNotIn("session.context-v1", manifest.capabilities)
    self.assertNotIn("operations-v1", manifest.capabilities)

def test_factory_rejects_missing_adapter_before_opening_private_state(self) -> None:
    context = make_context(host_services={})
    with self.assertRaisesRegex(
        ControlPlaneFactoryError, "Native turn adapter is unavailable"
    ):
        build_native_control_plane_client(context)
    self.assertEqual(tuple(context.private_root.iterdir()), ())
```

Add wrong identity/version, hostile options, wrong authority, missing/invalid
service, private-root mode/symlink, redacted repr/error, reopen, and wheel
resource tests.

- [ ] **Step 2: Run tests and confirm RED**

```bash
uv run python -m unittest -v tests.test_native_control_factory
```

Expected: FAIL because the factory and resource do not exist.

- [ ] **Step 3: Implement the exact binding and factory**

```python
NATIVE_CONTROL_PLANE_ID = "asterion.native"
NATIVE_CONTROL_PLANE_VERSION = "0.1.0"
NATIVE_CHECKPOINT_VERSION = "1.0.0"
NATIVE_COMPATIBILITY_IDS = (
    "asterion.agent-control/v1",
    "asterion.native-controller/v1",
)
_NATIVE_TURN_ADAPTER_SERVICE = "native-turn-adapter"
_REQUIRED_OPTIONS = frozenset({
    "generation",
    "max_capsule_bytes",
    "max_events_per_poll",
    "max_record_bytes",
    "max_total_private_bytes",
    "max_turns_per_poll",
    "session_id",
})
```

The manifest uses the full existing command/event tuples, sorted capabilities,
continuation media type `application/vnd.asterion.native-capsule`, and no
session-context/ecosystem/operation capability. The factory validates every
positive integer and identity before opening storage, checks the injected
adapter structurally, constructs file journal/capsule stores, reduces existing
state, and closes already-open resources on any later failure. It constructs
one `NativeSessionDirectory` from `max_total_private_bytes`, constructs both
stores from it, and transfers sole close ownership to the controller. On
construction failure it closes any borrowed store before closing the session
directory.

- [ ] **Step 4: Add exact package exports and resource inclusion**

Export only:

```python
__all__ = (
    "NATIVE_CONTROL_PLANE_ID",
    "NATIVE_CONTROL_PLANE_VERSION",
    "NativeControlError",
    "NativeControlPlaneClient",
    "NativeTurnAdapter",
    "build_native_control_plane_client",
    "native_control_plane_binding",
)
```

Add this artifact to `pyproject.toml`:

```toml
"src/asterion/control/providers/native/resources/control-plane.json",
```

- [ ] **Step 5: Run factory/build tests and commit**

```bash
uv run python -m unittest -v tests.test_native_control_factory tests.test_control_provider
uv build .
uv run ruff check src/asterion/control/providers/native tests/test_native_control_factory.py
git add src/asterion/control/providers/native pyproject.toml tests/test_native_control_factory.py
git commit -m "feat: bind native control provider"
```

Expected: factory tests, existing provider registry tests, and wheel build pass.

### Task 8: Pass common conformance and real `ControlHost` integration

**Files:**
- Create: `tests/test_native_control_conformance.py`
- Create: `tests/test_native_control_host.py`
- Create: `tests/test_native_prime_differential.py`
- Modify: `src/asterion/control/providers/native/turn.py`
- Modify: `src/asterion/control/providers/native/controller.py`
- Modify: `src/asterion/control/providers/native/client.py`

**Interfaces:**
- Consumes: production Native factory/client/controller, the exact `REQUIRED_PHASE0_SCENARIOS` identity set, `ControlHost`, `AuthorityLedger`, `MemoryCanonicalJournal`, and fake action executor patterns.
- Produces: command-driven Native executions of all ten shared scenario identities and complete host integration evidence without production `emit_*` methods.
- Produces: normalized provider-free Prime/Native comparisons for lifecycle order, proposal-resolution causality, replay, cumulative budget usage, and checkpoint identity.

- [ ] **Step 1: Write failing command-driven common-conformance scenarios**

Use the same ten stable scenario IDs but drive terminal, fault, and proposal
behavior through real `input.submit` commands and deterministic turn scripts.
The test module defines this closed scenario registry:

```python
NATIVE_SCENARIOS = {
    "attach-replay": scenario_attach_replay,
    "budget-limited": scenario_budget_limited,
    "cancel": scenario_cancel,
    "checkpoint": scenario_checkpoint,
    "command-idempotency": scenario_command_idempotency,
    "complete": scenario_complete,
    "fault-recovery": scenario_fault_recovery,
    "input-delivery": scenario_input_delivery,
    "pause-resume": scenario_pause_resume,
    "proposal-admission": scenario_proposal_admission,
}

async def run_native_conformance() -> ConformanceReport:
    if frozenset(NATIVE_SCENARIOS) != REQUIRED_PHASE0_SCENARIOS:
        raise AssertionError("native scenario identities diverged")
    passed: list[str] = []
    failed: list[str] = []
    for scenario_id in sorted(REQUIRED_PHASE0_SCENARIOS):
        try:
            await NATIVE_SCENARIOS[scenario_id]()
        except Exception as error:
            failed.append(f"{scenario_id}:{type(error).__name__}")
        else:
            passed.append(scenario_id)
    return ConformanceReport(tuple(passed), tuple(failed))

async def test_native_provider_passes_every_phase0_scenario(self) -> None:
    report = await run_native_conformance()
    self.assertEqual(report.failed, ())
    self.assertEqual(report.passed, tuple(sorted(REQUIRED_PHASE0_SCENARIOS)))
```

Also expose `run_native_conformance_observations()` for the final verifier. It
runs the same registry and returns one canonically ordered closed mapping per
scenario with exactly `scenario_id`, `status`, `provider_operations`,
`model_operations`, `credential_reads`, `network_operations`,
`application_operations`, and `upload_operations`. The counters are derived
from the injected fake process/executor recorders, not hard-coded after the
run.

For example, `scenario_complete` constructs a deterministic adapter whose
`content-ref-complete` result contains `goal.updated(completed)` and
`session.completed`, sends create then that input, and validates the complete
event stream with `validate_control_event_stream`. `scenario_fault_recovery`
uses a first scripted input producing `fault.raised` and
`session.recovery-required`, sends the existing resume command, then uses a
second scripted input to complete. `scenario_proposal_admission` scripts an
`action.proposed`, sends the existing admitted resolution, scripts completion,
and validates the final stream.

- [ ] **Step 2: Write failing host authority/exactly-once tests**

```python
async def test_host_admits_and_executes_native_proposal_exactly_once(self) -> None:
    host, client, executor = make_host_with_native(one_action_script())
    await host.dispatch(host.client_command(
        command_id="create-1",
        command_type="session.create",
        payload={"goal_id": "goal-1", "goal_ref": "goal-ref-1"},
    ))
    await host.dispatch(input_command_for(host))
    await host.pump(until_terminal=True)
    self.assertEqual(executor.action_ids, ["action-1"])
    self.assertEqual(host.snapshot().state.session_status, "completed")
```

Add rejected/cancelled/budget-limited zero-executor cases, authority snapshot
retry/recovery, terminal-send recovery without reexecution, and sentinel
redaction through Pathlight/public journal.

- [ ] **Step 3: Write the failing foundational differential subset**

Run the existing locked `run_prime_loop_scenarios(fake_prime=True)` oracle once
and select `prime-loop-application`, `prime-loop-budget`,
`prime-loop-checkpoint`, and `prime-loop-detach-attach` from its serialized
public events. Build the matching Native observations with the production
Native client and deterministic adapter. Normalize only the public fields
approved by the design:

```python
DIFFERENTIAL_CASES = (
    "action-causality",
    "budget-monotonicity",
    "checkpoint-identity",
    "lifecycle-order",
    "replay-suffix",
)

@dataclass(frozen=True)
class FoundationalProjection:
    lifecycle_order: tuple[str, ...]
    action_causality: tuple[tuple[str, str], ...]
    replay_suffix: tuple[str, ...]
    cumulative_usage: tuple[tuple[int, int, int, int, int], ...]
    checkpoint_shape: tuple[str, int, bool, bool] | None

async def test_native_matches_pinned_prime_foundational_projections(self) -> None:
    for case_id in DIFFERENTIAL_CASES:
        with self.subTest(case_id=case_id):
            prime = await observe_prime(case_id)
            native = await observe_native(case_id)
            self.assertEqual(native, prime)
```

Implement
`normalize(*, public_events, public_commands, replay_after_sequence) ->
FoundationalProjection` as a closed projection. It keeps lifecycle event types
in sequence order; pairs each
`action.proposed` identity with its ordered `action.resolve` resolutions;
selects event types strictly after `replay_after_sequence`; records all five
cumulative `budget.reported` integers; and reduces `checkpoint.created` to
`(checkpoint_version, covered_sequence, digest_is_sha256,
storage_ref_is_opaque)`. It rejects unknown keys or malformed public records.
It excludes event IDs, timestamps, provider-specific IDs, private
journal/capsule bytes, raw text, and hidden reasoning.
The Prime harness reuses the locked source/artifact/module identities already
verified for commit `a18809e00ea30638584d87b3afea7285a9d7296c`, uses the
provider-free fake daemon rather than a model, and reports zero provider and
application operations. `observe_prime(case_id)` selects the one locked Prime
scenario assigned above, parses only `event.accepted` and `command.accepted`
records from its serialized public journal, and normalizes them.
`observe_native(case_id)` executes the corresponding closed Native script,
collects its validated public commands/events plus one replay suffix, and
normalizes them with the same function. Both reject missing, extra, or
non-PASS scenarios. Task 9
compares crash recovery using the same external invariant tuple rather than
private bytes.

Expose `run_native_prime_differential_observations()` with the same closed
operation-counter fields plus `case_id`. It returns exactly one PASS mapping
for each sorted `DIFFERENTIAL_CASES` identity and derives all counters from the
Prime fake process and Native fake adapter/executor recorders.

- [ ] **Step 4: Run tests and confirm RED**

```bash
uv run python -m unittest -v tests.test_native_control_conformance tests.test_native_control_host tests.test_native_prime_differential
```

Expected: FAIL on the first missing conformance/host behavior, with no provider
or application operation.

- [ ] **Step 5: Make the minimum production corrections**

Correct only behavior demonstrated by the tests: adapter scripting control,
quiescent event iteration, action-resolution transitions, budget snapshot
replay, and stable terminal delivery. Do not add test methods to
`NativeControlPlaneClient` and do not bypass `ControlHost` for action execution.

- [ ] **Step 6: Run conformance/host/differential tests and commit**

```bash
uv run python -m unittest -v tests.test_control_conformance tests.test_native_control_conformance tests.test_native_control_host tests.test_native_prime_differential tests.test_control_execution
uv run ruff check src/asterion/control/providers/native tests/test_native_control_conformance.py tests/test_native_control_host.py tests/test_native_prime_differential.py
git add src/asterion/control/providers/native/turn.py src/asterion/control/providers/native/controller.py src/asterion/control/providers/native/client.py tests/test_native_control_conformance.py tests/test_native_control_host.py tests/test_native_prime_differential.py
git commit -m "test: close native control conformance"
```

### Task 9: Prove real-process crash recovery at every named boundary

**Files:**
- Create: `tests/test_native_control_process_recovery.py`
- Modify: `src/asterion/control/providers/native/store.py`
- Modify: `src/asterion/control/providers/native/capsule.py`
- Modify: `src/asterion/control/providers/native/controller.py`

**Interfaces:**
- Consumes: production file store/capsule/controller, real `ControlHost` with file canonical journal for host-receipt boundaries, and test-only `ASTERION_NATIVE_TEST_CRASH_POINT` read exclusively by an injected test fault callback.
- Produces: real child-process crash evidence for command, turn, event, checkpoint, and terminal durability windows.

- [ ] **Step 1: Write a failing subprocess crash matrix**

Use `subprocess.run()` with a small `python -c` harness importing production
modules. Never put crash environment handling in the production factory; pass
an injected callback to the controller/store constructors in tests.

```python
CRASH_POINTS = (
    "command-before-publish",
    "command-after-publish-before-ack",
    "turn-after-start",
    "turn-after-adapter-before-commit",
    "turn-after-commit-before-yield",
    "capsule-after-write-before-checkpoint",
    "checkpoint-after-commit-before-yield",
    "terminal-after-commit-before-host-receipt",
)

def test_every_named_crash_point_recovers_without_duplicates(self) -> None:
    for crash_point in CRASH_POINTS:
        with self.subTest(crash_point=crash_point), tempfile.TemporaryDirectory() as d:
            first = run_worker(Path(d), crash_point=crash_point)
            self.assertNotEqual(first.returncode, 0)
            recovered = run_worker(Path(d), crash_point=None)
            self.assertEqual(recovered.returncode, 0, recovered.stderr)
            report = json.loads(recovered.stdout)
            self.assertEqual(report["duplicate_commands"], 0)
            self.assertEqual(report["duplicate_turns"], 0)
            self.assertEqual(report["duplicate_actions"], 0)
            self.assertEqual(report["sequence_gaps"], 0)
            self.assertEqual(report["terminal_count"], 1)
            self.assertEqual(report["owned_processes_after_close"], 0)
```

Expose `run_native_crash_observations()` as the shared implementation used by
the test and final verifier. Each returned closed mapping contains exactly
`crash_point`, `status`, the six duplicate/gap/terminal/process counts above, and the
six operation counters used by Task 10. Process and operation counts come from
the child report; no PASS field is synthesized before the recovered child has
exited successfully and all invariants have been checked.

- [ ] **Step 2: Run the matrix and confirm RED**

```bash
uv run python -m unittest -v tests.test_native_control_process_recovery
```

Expected: FAIL at the earliest unsupported crash boundary.

- [ ] **Step 3: Add narrow injected fault boundaries and recovery fixes**

Use one no-op-by-default callback:

```python
CrashHook = Callable[[str], None]

def _no_crash(_point: str) -> None:
    return None
```

Call it only at the named boundaries. Recovery must use committed records,
ignore uncommitted temp files, recompute the deterministic fake turn under the
same ID, replay committed events, and never reexecute an action whose durable
host receipt exists. No production code reads environment variables or calls
`os._exit()`.

- [ ] **Step 4: Run crash, security, and recovery suites**

```bash
uv run python -m unittest -v tests.test_native_control_store tests.test_native_control_capsule tests.test_native_control_process_recovery tests.test_control_recovery tests.test_control_execution
```

Expected: PASS with no orphan child process after each subtest.

- [ ] **Step 5: Commit crash closure**

```bash
git add src/asterion/control/providers/native/store.py src/asterion/control/providers/native/capsule.py src/asterion/control/providers/native/controller.py tests/test_native_control_process_recovery.py
git commit -m "test: prove native controller crash recovery"
```

### Task 10: Add the provider-free receipt, run H-038, and close Phase 3.1

**Files:**
- Create: `tools/verify_native_controller_core.py`
- Create: `tests/test_native_controller_core_verification.py`
- Modify: `Makefile`
- Modify: `docs/status/PRIME-PARITY-LEDGER.md`
- Modify: `docs/status/CURRENT-STATE.md`
- Modify: `docs/status/JOURNAL.md`
- Modify: `docs/status/RESUME-NEXT-SESSION.md`
- Modify: `docs/status/climb/hypotheses.yaml`
- Generated modify: `docs/status/climb/runs.csv`
- Generated modify: `docs/status/climb/research-tree.md`
- Generated modify: `docs/status/climb/session-state.json`

**Interfaces:**
- Consumes: all Native core tests, exact Prime parity ledger, promotion checker, and dormant H-038 gate.
- Produces: a body-free deterministic Native core verification report, exact Make target, one canonical H-038 result, `native-controller-core: PASS`, and successor `phase-3.2-native-verified-loop-design`.

- [ ] **Step 1: Write failing receipt/checker tests**

```python
class TestNativeControllerCoreVerification(unittest.TestCase):
    def test_report_closes_only_core_and_keeps_all_native_rows_missing(self) -> None:
        report = build_native_controller_core_report(ROOT)
        self.assertEqual(report["claim"], "native-controller-core")
        self.assertEqual(report["common_scenarios"], 10)
        self.assertEqual(report["differential_cases"], 5)
        self.assertEqual(report["crash_points"], 8)
        self.assertEqual(report["provider_operations"], 0)
        self.assertEqual(report["model_operations"], 0)
        self.assertEqual(report["credential_reads"], 0)
        self.assertEqual(report["network_operations"], 0)
        self.assertEqual(report["application_operations"], 0)
        self.assertEqual(report["upload_operations"], 0)
        self.assertEqual(report["native_mandatory_total"], 61)
        self.assertEqual(report["native_mandatory_missing"], 61)
        self.assertEqual(report["promoted_feature_ids"], [])
```

Add malformed ledger, accidental Native PASS, missing test module, secret/path
sentinel, and noncanonical output tests.

- [ ] **Step 2: Run tests and confirm RED**

```bash
uv run python -m unittest -v tests.test_native_controller_core_verification
```

Expected: FAIL because the verifier does not exist.

- [ ] **Step 3: Implement the deterministic verifier and Make target**

`tools/verify_native_controller_core.py` loads the canonical JSON parity
inventory through `load_prime_parity_ledger()`, selects the exact 61 mandatory
feature results for `asterion.native`, and asserts every status is still
`missing`. Its default
observation runner dynamically imports the three named test harnesses and
executes their public `run_native_conformance_observations()`,
`run_native_prime_differential_observations()`, and
`run_native_crash_observations()` functions. Each returns a closed,
body-free mapping with status plus provider, model, credential, network,
application, and upload operation counters. The verifier rejects any nonzero
counter, wrong scenario/case/crash identity, or non-PASS observation, and
prints one canonical JSON object:

```json
{"application_operations":0,"claim":"native-controller-core","common_scenarios":10,"crash_points":8,"credential_reads":0,"differential_cases":5,"model_operations":0,"native_mandatory_missing":61,"native_mandatory_total":61,"network_operations":0,"promoted_feature_ids":[],"provider_operations":0,"status":"PASS","upload_operations":0}
```

Add to `Makefile`:

```make
.PHONY: test.native-controller-core.provider-free
test.native-controller-core.provider-free:
	$(UV_BIN) run python -m unittest -v \
		tests.test_native_control_model \
		tests.test_native_control_store \
		tests.test_native_control_capsule \
		tests.test_native_control_controller \
		tests.test_native_control_client \
		tests.test_native_control_factory \
		tests.test_native_control_conformance \
		tests.test_native_control_host \
		tests.test_native_prime_differential \
		tests.test_native_control_process_recovery \
		tests.test_native_controller_core_verification
```

- [ ] **Step 4: Run the focused receipt boundary**

```bash
make test.native-controller-core.provider-free
uv run python tools/verify_native_controller_core.py
```

Expected: all focused tests pass and the verifier prints the exact PASS JSON
with every operation counter at zero and 61 Native rows still Missing.

- [ ] **Step 5: Run complete pre-H-038 verification on a clean commit**

First commit implementation and verifier files without changing Climb outcome:

```bash
git add Makefile tools/verify_native_controller_core.py tests/test_native_controller_core_verification.py
git commit -m "test: gate native controller core"
```

Then run:

```bash
make test.native-controller-core.provider-free
uv run python tools/verify_native_controller_core.py
make check
make promotion-check
git diff --check
git status --short
```

Expected: every command passes and `git status --short` is empty. Promotion
reports zero provider operations and no full dataset.

- [ ] **Step 6: Execute H-038 exactly once**

```bash
tools/climb/cycle.sh H-038
```

Expected:

- exit 0;
- `runs.csv` appends exactly
  `38,H-038,passed,check.native-controller-core-provider-free`;
- `session-state.json` routes to
  `phase-3.2-native-verified-loop-design`;
- research tree contains H-038 exactly once; and
- no provider/application operation occurs.

- [ ] **Step 7: Promote only the narrow claim and update durable state**

Change H-038 status from pending to passed. Add a Phase evidence row to
`PRIME-PARITY-LEDGER.md`:

```markdown
| Native controller core | PASS | `make test.native-controller-core.provider-free` | Provider-free durable single-session substrate; all 61 compound Native rows remain Missing. |
```

Update `CURRENT-STATE.md` structurally so the active focus is Phase 3.2 Native
Verified-loop design. Append one journal line for the final commit and rewrite
`RESUME-NEXT-SESSION.md` as a live checkpoint whose one immediate next action
is Phase 3.2 design. Do not write a final handoff.

- [ ] **Step 8: Run final claim-integrity checks**

```bash
uv run python -m unittest -v tests.test_prime_climb tests.test_prime_parity_ledger tests.test_check_prime_parity tests.test_native_controller_core_verification
uv run python tools/check_prime_parity.py --claim verified-system-parity --provider asterion.native
git diff --check
```

Expected:

- focused integrity tests PASS;
- the generic full-parity checker, selected against `asterion.native`, reports
  `BLOCKED` with the 61 mandatory feature IDs and exits 1 (not the CLI
  selection-error exit 2); capture that expected result in the test, never
  label it PASS;
- no secret or private path is printed; and
- diff check passes.

- [ ] **Step 9: Commit canonical H-038 closure**

```bash
git add docs/status/PRIME-PARITY-LEDGER.md docs/status/CURRENT-STATE.md docs/status/JOURNAL.md docs/status/RESUME-NEXT-SESSION.md docs/status/climb/hypotheses.yaml docs/status/climb/runs.csv docs/status/climb/research-tree.md docs/status/climb/session-state.json
git commit -m "climb: close native durable controller core"
```

- [ ] **Step 10: Verify Git/worktree closure**

```bash
git status --short --branch
git branch --format='%(refname:short)'
git worktree list --porcelain
```

Expected: clean `main`, one local branch, one worktree, and no Phase 3.1
implementation branch or worktree left behind.

## Plan Self-Review Checklist

- [x] Every approved Phase 3.1 spec requirement maps to a task above.
- [x] No task changes a closed public schema or imports Prime into Native.
- [x] Type names and signatures are consistent across Tasks 2–10.
- [x] Production code exposes no `emit_*`, environment crash switch, provider fallback, raw private value, or direct runner call.
- [x] H-038 stays dormant until all implementation commits and full gates pass.
- [x] H-038 promotes only `native-controller-core`, not any of the 61 compound Native rows.
- [x] The expected failure of the full Native parity checker is tested and never reported as PASS.
- [x] Final state is clean `main` with one branch and one worktree.
