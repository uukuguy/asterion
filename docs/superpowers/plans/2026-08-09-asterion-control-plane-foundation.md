# Asterion Control-Plane Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the provider-neutral, provider-free foundation for a verifiable long-running Asterion agent: closed system/control protocols, exact immutable resolution, host-owned authority and budgets, an append-only canonical journal, deterministic state machines, a pluggable control-provider boundary, a fake-provider conformance loop and safe causal evidence.

**Architecture:** A Python `asterion.control` subsystem sits above exact installed application assemblies. The host resolves one immutable agent system and authority envelope, constructs one exact control provider, journals every accepted command/event, reduces canonical session/action state and admits provider proposals before application execution. JSON Schema and TypeScript mirror the shared wire/static contracts; provider implementation and canonical state remain Python-owned.

**Tech Stack:** Python 3.12, frozen dataclasses and immutable mappings, JSON Schema 2020-12, TypeScript 5/Ajv 2020, Node.js tests, `unittest`, existing application-provider/factory and Pathlight APIs.

## Global Constraints

- Framework modules remain domain-neutral and never import DCI or Prime implementations, resources, tests or adjacent trees.
- Add new `asterion.agent-system/v1`, `asterion.control-plane/v1` and `asterion.agent-control/v1`; do not alter existing closed v1 contracts.
- IDs are canonical, versions exact, fields closed and arrays sorted/unique by Unicode scalar order in schema, Python and TypeScript.
- Static manifests contain no prompts, credentials, commands, executable paths, environment values, mutable budgets, private roots or provider state.
- The host owns authority, admission, canonical journal, budget enforcement, clock values, storage and Pathlight. A provider owns only engine behavior and opaque capsule bytes/references.
- Commands and events are immutable safe projections. Public payloads reject arbitrary maps, text bodies, raw output, paths, credentials and provider payloads.
- The host persists a command ID before dispatch and an event before acknowledgement. Sequence gaps, duplicate divergent IDs, illegal transitions and multiple terminal states fail closed.
- No application/runtime/provider is contacted during Phase 0 tests. The fake provider is deterministic and in-memory.
- `uncertain` is terminal for an admitted action until explicit reconciliation; no automatic retry path exists.
- Use `unittest`; each task starts RED, reaches GREEN, runs focused tests and commits independently without staging user-owned status-file changes.

## File Structure

- Create: `schemas/agent-system/v1/agent-system.schema.json` — closed static system manifest.
- Create: `schemas/control-plane/v1/control-plane-manifest.schema.json` — closed provider compatibility manifest.
- Create: `schemas/agent-control/v1/command.schema.json` — closed host-to-provider commands.
- Create: `schemas/agent-control/v1/event.schema.json` — closed provider-to-host events.
- Create: `src/asterion/control/protocol.py` — Python validation and immutable protocol snapshots.
- Create: `src/asterion/control/host.py` — public provider protocol and immutable command/event/manifest types.
- Create: `src/asterion/control/factory.py` — exact provider factory registry.
- Create: `src/asterion/control/system.py` — exact portfolio references and resolved system plan.
- Create: `src/asterion/control/authority.py` — authority revisions, grants, budget requests and decisions.
- Create: `src/asterion/control/journal.py` — append-only safe canonical journal and replay cursors.
- Create: `src/asterion/control/state.py` — pure session/action reducer.
- Create: `src/asterion/control/manager.py` — command dispatch, journaling, reduction and proposal admission.
- Create: `src/asterion/control/evidence.py` — fixed, safe control-event to Pathlight projection.
- Create: `src/asterion/control/testing.py` — deterministic fake provider and reusable conformance scenarios.
- Create: `src/asterion/control/__init__.py` — narrow public exports.
- Modify: `packages/typescript/asterion-runtime/src/types.ts` — shared system/control DTOs.
- Modify: `packages/typescript/asterion-runtime/src/validation.ts` — Ajv plus semantic ordering validation.
- Modify: `packages/typescript/asterion-runtime/src/index.ts` — export new types/validators.
- Modify: `packages/typescript/asterion-runtime/scripts/copy-schemas.mjs` — copy new canonical schemas.
- Modify: `packages/typescript/asterion-runtime/test/runtime.test.mjs` — shared fixture validation and immutability.
- Modify: `packages/typescript/asterion-runtime/test/type-contract.ts` — compile-time DTO contract.
- Create: fixture directories under `tests/fixtures/agent_system/v1/`, `tests/fixtures/control_plane/v1/` and `tests/fixtures/agent_control/v1/`.
- Create: focused Python tests named in the tasks below.

---

### Task 1: Define closed agent-system and control-plane manifests

**Files:**
- Create: `schemas/agent-system/v1/agent-system.schema.json`
- Create: `schemas/control-plane/v1/control-plane-manifest.schema.json`
- Create: `tests/fixtures/agent_system/v1/valid-system.json`
- Create: `tests/fixtures/agent_system/v1/invalid-unknown-field.json`
- Create: `tests/fixtures/agent_system/v1/invalid-unsorted-portfolio.json`
- Create: `tests/fixtures/control_plane/v1/valid-manifest.json`
- Create: `tests/fixtures/control_plane/v1/invalid-command-family.json`
- Create: `tests/fixtures/control_plane/v1/invalid-secret-field.json`
- Create: `src/asterion/control/protocol.py`
- Create: `src/asterion/control/__init__.py`
- Test: `tests/test_agent_system_protocol.py`

**Interfaces:**
- Produces `AGENT_SYSTEM_PROTOCOL`, `CONTROL_PLANE_PROTOCOL`, `ControlProtocolError`.
- Produces `validate_agent_system_manifest(value)` and `validate_control_plane_manifest(value)` returning recursively immutable mappings.
- Agent-system fields are exactly `protocol`, `system_id`, `version`, `control_plane`, `applications`, `policies`, `host_capabilities`, `control_capabilities`.
- Control-plane fields are exactly `protocol`, `control_plane_id`, `version`, `commands`, `events`, `capabilities`, `continuation_media_type`, `checkpoint_version`, `compatibility_ids`.

- [ ] **Step 1: Write failing schema/Python contract tests**

```python
class TestAgentSystemProtocol(unittest.TestCase):
    def test_valid_fixtures_are_immutable_and_canonical(self) -> None:
        system = validate_agent_system_manifest(_fixture("valid-system.json"))
        self.assertEqual(system["protocol"], "asterion.agent-system/v1")
        self.assertEqual(system["applications"][0]["application_id"], "dci")
        with self.assertRaises(TypeError):
            system["system_id"] = "changed"  # type: ignore[index]

    def test_invalid_fixtures_fail_closed(self) -> None:
        for name in ("invalid-unknown-field.json", "invalid-unsorted-portfolio.json"):
            with self.subTest(name=name), self.assertRaises(ControlProtocolError):
                validate_agent_system_manifest(_fixture(name))
```

Add equivalent control-plane tests for exact versions, identifiers, media type, sorted unique command/event/capability/compatibility arrays, unknown fields and a sentinel secret key.

- [ ] **Step 2: Run focused tests to verify RED**

Run: `uv run python -m unittest -v tests.test_agent_system_protocol`
Expected: FAIL because `asterion.control` and schemas do not exist.

- [ ] **Step 3: Implement the schemas and minimal Python validators**

Use `$schema: https://json-schema.org/draft/2020-12/schema`, `additionalProperties: false`, anchored identifier/semantic-version/digest/media-type patterns and exact enums for the initial command/event families. Validate semantic ordering in Python with `is_sorted_unique_scalar_strings`; validate portfolio refs by `(provider_id, application_id, version, runtime_id)` and reject duplicates.

```python
AGENT_SYSTEM_PROTOCOL = "asterion.agent-system/v1"
CONTROL_PLANE_PROTOCOL = "asterion.control-plane/v1"

def validate_agent_system_manifest(value: object) -> Mapping[str, object]:
    mapping = _closed_mapping(value, AGENT_SYSTEM_FIELDS, "agent system")
    _require_protocol(mapping, AGENT_SYSTEM_PROTOCOL, "agent system")
    _validate_system_references(mapping)
    return _freeze_mapping(mapping)
```

The Python validator is authoritative at runtime and must implement the same shapes as the canonical schema without adding schema-only exceptions.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `uv run python -m unittest -v tests.test_agent_system_protocol`
Expected: PASS for all valid/invalid fixture matrices and immutability assertions.

- [ ] **Step 5: Commit static contracts**

```bash
git add schemas/agent-system schemas/control-plane src/asterion/control tests/fixtures/agent_system tests/fixtures/control_plane tests/test_agent_system_protocol.py
git commit -m "feat: define agent system control manifests"
```

### Task 2: Define the closed agent-control command/event wire protocol

**Files:**
- Create: `schemas/agent-control/v1/command.schema.json`
- Create: `schemas/agent-control/v1/event.schema.json`
- Create: `tests/fixtures/agent_control/v1/valid-command-session-create.json`
- Create: `tests/fixtures/agent_control/v1/valid-command-action-resolve.json`
- Create: `tests/fixtures/agent_control/v1/valid-event-action-proposed.json`
- Create: `tests/fixtures/agent_control/v1/valid-event-terminal.json`
- Create: `tests/fixtures/agent_control/v1/invalid-command-prompt-body.json`
- Create: `tests/fixtures/agent_control/v1/invalid-event-sequence.json`
- Create: `tests/fixtures/agent_control/v1/invalid-event-provider-payload.json`
- Modify: `src/asterion/control/protocol.py`
- Test: `tests/test_agent_control_protocol.py`

**Interfaces:**
- Produces `AGENT_CONTROL_PROTOCOL`, `validate_control_command(value)`, `validate_control_event(value)` and `validate_control_event_stream(events)`.
- Commands have exact base fields `protocol`, `command_id`, `session_id`, `authority_revision`, `type`, `payload`.
- Events have exact base fields `protocol`, `event_id`, `session_id`, `generation`, `sequence`, `emitted_at`, `type`, `payload`.
- Supports the approved initial commands and event families; every discriminated payload is closed.

- [ ] **Step 1: Write failing wire-contract tests**

```python
def test_event_stream_requires_one_identity_contiguous_sequence_and_one_terminal(self) -> None:
    events = tuple(validate_control_event(item) for item in _jsonl("valid-session.jsonl"))
    validate_control_event_stream(events)
    altered = [dict(event) for event in events]
    altered[1]["sequence"] = 3
    with self.assertRaisesRegex(ControlProtocolError, "contiguous"):
        validate_control_event_stream(altered)

def test_public_payload_rejects_prompt_and_provider_maps(self) -> None:
    for name in ("invalid-command-prompt-body.json", "invalid-event-provider-payload.json"):
        with self.subTest(name=name), self.assertRaises(ControlProtocolError):
            _validate_named_fixture(name)
```

Cover command IDs, generation/sequence positivity, RFC 3339 UTC timestamps, one session ID/generation, unique event IDs, exact payload fields, one terminal event, and no events after terminal.

- [ ] **Step 2: Run focused tests to verify RED**

Run: `uv run python -m unittest -v tests.test_agent_control_protocol`
Expected: FAIL because wire schemas and validators are absent.

- [ ] **Step 3: Implement discriminated closed schemas and validators**

Use `oneOf` branches with `const` command/event types and per-type payload schemas. Initial proposal payload contains only `action_id`, `idempotency_key`, `kind`, `target`, `input_ref`, `expected_artifacts`, `budget`, `causal_parent_ids`; it never embeds input text. Initial terminal event payload contains only fixed `status` plus safe receipt/failure reference fields.

```python
TERMINAL_EVENT_TYPES = frozenset({
    "session.completed", "session.failed", "session.cancelled", "session.budget_limited",
})

def validate_control_event_stream(events: Sequence[Mapping[str, object]]) -> None:
    snapshots = tuple(validate_control_event(event) for event in events)
    _require_one_session_and_generation(snapshots)
    _require_contiguous_sequences(snapshots)
    _require_exactly_one_final_terminal(snapshots)
```

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `uv run python -m unittest -v tests.test_agent_control_protocol`
Expected: PASS, including sentinel values in unknown/private fields and immutable snapshots.

- [ ] **Step 5: Commit the wire protocol**

```bash
git add schemas/agent-control src/asterion/control/protocol.py tests/fixtures/agent_control tests/test_agent_control_protocol.py
git commit -m "feat: define agent control wire protocol"
```

### Task 3: Add TypeScript contract and fixture parity

**Files:**
- Modify: `packages/typescript/asterion-runtime/src/types.ts`
- Modify: `packages/typescript/asterion-runtime/src/validation.ts`
- Modify: `packages/typescript/asterion-runtime/src/index.ts`
- Modify: `packages/typescript/asterion-runtime/scripts/copy-schemas.mjs`
- Modify: `packages/typescript/asterion-runtime/test/runtime.test.mjs`
- Modify: `packages/typescript/asterion-runtime/test/type-contract.ts`

**Interfaces:**
- Produces readonly `AgentSystemManifest`, `ControlPlaneManifest`, `ControlCommand` and `ControlEvent` discriminated unions.
- Produces `validateAgentSystemManifest`, `validateControlPlaneManifest`, `validateControlCommand`, `validateControlEvent` and `validateControlEventStream`.
- Consumes the same canonical schemas and fixture files as Python.

- [ ] **Step 1: Add failing runtime and compile-time tests**

```typescript
const command = validateControlCommand(validCreateCommand);
assert.equal(command.protocol, "asterion.agent-control/v1");
assert.throws(() => Reflect.set(command.payload, "prompt", "SENTINEL_SECRET"));
assert.throws(() => validateControlEvent(invalidProviderPayload));
validateControlEventStream(validSessionEvents);
```

Add a `satisfies ControlCommand` value and `@ts-expect-error` cases for unknown fields and the wrong payload discriminator.

- [ ] **Step 2: Run TypeScript tests to verify RED**

Run: `npm --prefix packages/typescript/asterion-runtime test`
Expected: FAIL because exports, schemas and validators are absent.

- [ ] **Step 3: Implement shared readonly unions and Ajv validation**

Extend the explicit schema-copy script; do not discover schemas dynamically. Reuse `requireValid`, `requireSortedUnique` and immutable snapshots. Add semantic portfolio-ref ordering and stream sequence/terminal checks after Ajv shape validation.

- [ ] **Step 4: Run TypeScript and Python fixture tests to verify GREEN**

Run:

```bash
npm --prefix packages/typescript/asterion-runtime test
uv run python -m unittest -v tests.test_agent_system_protocol tests.test_agent_control_protocol
```

Expected: PASS with Python/TypeScript agreement on all shared fixtures.

- [ ] **Step 5: Commit cross-language parity**

```bash
git add packages/typescript/asterion-runtime
git commit -m "feat: validate control contracts in typescript"
```

### Task 4: Add immutable provider host types and exact factory selection

**Files:**
- Create: `src/asterion/control/host.py`
- Create: `src/asterion/control/factory.py`
- Modify: `src/asterion/control/__init__.py`
- Test: `tests/test_control_provider.py`

**Interfaces:**
- Produces frozen `ControlPlaneManifest`, `ControlCommand`, `ControlEvent`, `EventCursor` value types with validated `to_mapping()` snapshots.
- Produces async `ControlPlaneClient.send(command)` and `events(cursor)` protocol plus `close()`.
- Produces `ControlPlaneFactoryContext`, `ControlPlaneFactoryBinding`, `ControlPlaneFactoryRegistry.select(control_plane_id, version)`.

- [ ] **Step 1: Write failing host/factory tests**

```python
def test_factory_selects_exact_id_and_version(self) -> None:
    registry = ControlPlaneFactoryRegistry((binding_v1, binding_v2))
    self.assertIs(registry.select("prime", "1.0.0"), binding_v1)
    with self.assertRaises(ControlPlaneFactoryError):
        registry.select("prime", "1.1.0")

def test_context_repr_redacts_private_options_and_services(self) -> None:
    rendered = repr(context_with_sentinel)
    self.assertNotIn("SENTINEL_SECRET", rendered)
    self.assertNotIn(str(private_root), rendered)
```

Also reject duplicate exact bindings, unsorted capabilities, mismatched manifest identity, mutable options and non-callable factories.

- [ ] **Step 2: Run focused tests to verify RED**

Run: `uv run python -m unittest -v tests.test_control_provider`
Expected: FAIL because host and factory modules do not exist.

- [ ] **Step 3: Implement narrow provider interfaces and registry**

```python
class ControlPlaneClient(Protocol):
    @property
    def manifest(self) -> ControlPlaneManifest:
        raise NotImplementedError

    async def send(self, command: ControlCommand) -> None:
        raise NotImplementedError

    def events(self, cursor: EventCursor | None = None) -> AsyncIterator[ControlEvent]:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError

@dataclass(frozen=True, repr=False)
class ControlPlaneFactoryContext:
    system_id: str
    system_version: str
    control_plane_id: str
    control_plane_version: str
    private_root: Path
    options: Mapping[str, str]
    host_services: Mapping[str, object] = field(default_factory=dict)
```

Copy options/services into `RedactedImmutableMapping`, canonicalize the private root without exposing it, and validate each binding by round-tripping its manifest through Task 1.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `uv run python -m unittest -v tests.test_control_provider`
Expected: PASS for exact selection, ambiguity/unavailability, immutability and redaction.

- [ ] **Step 5: Commit provider boundary**

```bash
git add src/asterion/control tests/test_control_provider.py
git commit -m "feat: add control provider boundary"
```

### Task 5: Resolve immutable agent systems and exact application portfolios

**Files:**
- Create: `src/asterion/control/system.py`
- Modify: `src/asterion/control/__init__.py`
- Test: `tests/test_control_system.py`

**Interfaces:**
- Produces frozen `ApplicationPortfolioEntry` and `AgentSystemPlan`.
- Produces `resolve_agent_system(manifest, application_providers, control_factories, host_capabilities)`.
- Selects each exact provider/application/version/runtime once and verifies the control provider declares every required command/event/capability/compatibility edge.

- [ ] **Step 1: Write failing resolution tests**

```python
def test_resolves_exact_sorted_portfolio_without_mutating_inputs(self) -> None:
    plan = resolve_agent_system(manifest, application_providers=providers,
                                control_factories=control_factories,
                                host_capabilities=("clock.monotonic", "storage.private"))
    self.assertEqual(plan.portfolio[0].application.application_id, "dci")
    self.assertEqual(plan.portfolio[0].assembly.runtime_id, "fake")
    self.assertEqual(manifest, original_manifest)

def test_rejects_missing_runtime_or_control_capability_before_factory_call(self) -> None:
    with self.assertRaises(AgentSystemError):
        resolve_agent_system(invalid_manifest, **dependencies)
    self.assertEqual(factory_calls, [])
```

Cover missing/duplicate providers, exact version mismatch, missing runtime assembly, undeclared host capability, control capability mismatch and deterministic output under reordered provider inputs.

- [ ] **Step 2: Run focused tests to verify RED**

Run: `uv run python -m unittest -v tests.test_control_system`
Expected: FAIL because the resolver does not exist.

- [ ] **Step 3: Implement exact fail-closed resolution**

```python
@dataclass(frozen=True)
class ApplicationPortfolioEntry:
    provider_id: str
    application: InstalledApplication
    assembly: InstalledAssembly

@dataclass(frozen=True)
class AgentSystemPlan:
    system_id: str
    version: str
    control_binding: ControlPlaneFactoryBinding
    portfolio: Sequence[ApplicationPortfolioEntry]
    policies: Sequence[str]
    host_capabilities: Sequence[str]
```

Validate all inputs before calling any factory. Index providers by exact identity, use `select_installed_application`, then require exactly one installed assembly with the requested runtime ID. Return only tuples/frozen values.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `uv run python -m unittest -v tests.test_control_system`
Expected: PASS for success, determinism, preflight rejection and input immutability.

- [ ] **Step 5: Commit system resolution**

```bash
git add src/asterion/control tests/test_control_system.py
git commit -m "feat: resolve immutable agent systems"
```

### Task 6: Implement authority revisions, admission and monotonic budgets

**Files:**
- Create: `src/asterion/control/authority.py`
- Modify: `src/asterion/control/__init__.py`
- Test: `tests/test_control_authority.py`

**Interfaces:**
- Produces frozen `BudgetLimit`, `BudgetRequest`, `BudgetUsage`, `AuthorityEnvelope`, `AdmissionDecision` and `AuthorityLedger`.
- `AuthorityLedger.evaluate(proposal, now)` returns one immutable admitted/rejected decision without mutating usage.
- `reserve(decision)` and `settle(action_id, receipt)` are idempotent, monotonic and cannot exceed the envelope.
- Authority replacement accepts only the same authority ID with a strictly larger revision and journals cancellation/expiry separately in later tasks.

- [ ] **Step 1: Write failing authority/budget tests**

```python
def test_rejects_action_outside_portfolio_without_reserving_budget(self) -> None:
    decision = ledger.evaluate(proposal_for("other@app"), now=clock.now())
    self.assertEqual(decision.status, "rejected")
    self.assertEqual(decision.reason, "target-not-authorized")
    self.assertEqual(ledger.usage, BudgetUsage.zero())

def test_reserve_and_settle_are_idempotent_and_monotonic(self) -> None:
    decision = ledger.evaluate(authorized_proposal, now=clock.now())
    ledger.reserve(decision)
    ledger.reserve(decision)
    ledger.settle(authorized_proposal.action_id, receipt)
    self.assertEqual(ledger.usage.aggregate_tokens, receipt.aggregate_tokens)
```

Cover allowed operations, child depth/count, deadlines, host-service grants, expiry, cancellation, controller/application/child/aggregate budgets, over-settlement and revision replacement.

- [ ] **Step 2: Run focused tests to verify RED**

Run: `uv run python -m unittest -v tests.test_control_authority`
Expected: FAIL because authority types do not exist.

- [ ] **Step 3: Implement host-owned admission and accounting**

Use non-negative integer micro-units for cost and integer token counts; avoid floats. `evaluate` validates an exact portfolio target and fixed operation enum, compares requested reservation with remaining limits and returns a stable safe reason code. `reserve` consumes the declared maximum; `settle` replaces the reservation with proven usage but never reduces already accounted totals below zero or permits a receipt above the reserved limit.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `uv run python -m unittest -v tests.test_control_authority`
Expected: PASS, including immutability and secret-free `repr`/mapping assertions.

- [ ] **Step 5: Commit authority enforcement**

```bash
git add src/asterion/control/authority.py src/asterion/control/__init__.py tests/test_control_authority.py
git commit -m "feat: enforce long running authority budgets"
```

### Task 7: Build the append-only canonical journal and replay cursor

**Files:**
- Create: `src/asterion/control/journal.py`
- Modify: `src/asterion/control/__init__.py`
- Test: `tests/test_control_journal.py`

**Interfaces:**
- Produces `JournalRecord`, `JournalCursor`, `CanonicalJournal` protocol and `MemoryCanonicalJournal`.
- Record kinds are closed: `system.bound`, `authority.bound`, `authority.revised`, `command.accepted`, `event.accepted`, `action.decided`, `action.receipted`, `checkpoint.sealed`, `fault.projected`.
- `append(expected_position, record)` is compare-and-append; `replay(cursor)` returns an immutable contiguous suffix.
- Command/event/action idempotency indexes reject divergent duplicates and return the original record for equal replays.

- [ ] **Step 1: Write failing append/replay tests**

```python
def test_compare_and_append_and_replay_are_contiguous(self) -> None:
    first = journal.append(
        0,
        JournalRecord.system_bound(
            system_id="system-1",
            system_version="1.0.0",
            authority_id="authority-1",
            authority_revision=1,
        ),
    )
    second = journal.append(first.position, JournalRecord.command_accepted(command))
    self.assertEqual([r.position for r in journal.replay(JournalCursor(0))], [1, 2])

def test_divergent_duplicate_command_fails_closed(self) -> None:
    journal.accept_command(command)
    with self.assertRaises(JournalConflictError):
        journal.accept_command(command_with_same_id_different_payload)
```

Cover stale expected positions, immutable replay, one system/authority prefix, duplicate equal events, divergent duplicate IDs, no private fields and sentinel redaction.

- [ ] **Step 2: Run focused tests to verify RED**

Run: `uv run python -m unittest -v tests.test_control_journal`
Expected: FAIL because the journal does not exist.

- [ ] **Step 3: Implement an in-memory reference journal**

Store recursively immutable safe mappings and SHA-256 canonical digests. Index IDs to `(digest, position)` and return the original position for an identical replay. Reject any record whose payload fails the originating protocol/type validator. Define the persistence protocol now; durable filesystem/database implementations belong to Phase 1.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `uv run python -m unittest -v tests.test_control_journal`
Expected: PASS for CAS, replay, idempotency, immutability and redaction.

- [ ] **Step 5: Commit canonical journal semantics**

```bash
git add src/asterion/control/journal.py src/asterion/control/__init__.py tests/test_control_journal.py
git commit -m "feat: add canonical control journal"
```

### Task 8: Implement pure session and action state reducers

**Files:**
- Create: `src/asterion/control/state.py`
- Modify: `src/asterion/control/__init__.py`
- Test: `tests/test_control_state.py`

**Interfaces:**
- Produces frozen `SessionState`, `ActionState`, `ControlState` and `reduce_control_event(state, event)`.
- Session states are exactly `created`, `running`, `paused`, `checkpointing`, `recovery_required`, `completed`, `failed`, `cancelled`, `budget_limited`.
- Action states are exactly `proposed`, `admitted`, `rejected`, `running`, `succeeded`, `failed`, `cancelled`, `uncertain`.
- The reducer is pure: same state/event yields equal output and never modifies input.

- [ ] **Step 1: Write failing transition-model tests**

```python
def test_pause_recover_and_complete_sequence(self) -> None:
    state = reduce_many(ControlState.empty("session-1"), valid_recovery_events)
    self.assertEqual(state.session.status, "completed")
    self.assertEqual(state.next_sequence, len(valid_recovery_events) + 1)

def test_uncertain_action_cannot_run_or_succeed_without_reconciliation(self) -> None:
    state = reduce_many(initial, uncertain_events)
    with self.assertRaises(ControlStateError):
        reduce_control_event(state, event("action.running", action_id="a-1"))
```

Use `subTest` transition matrices covering all legal/illegal session/action edges, generation mismatch, gaps, duplicate terminal states, one admission decision, one execution terminal, cancellation and budget-limited resume requiring a new authority revision.

- [ ] **Step 2: Run focused tests to verify RED**

Run: `uv run python -m unittest -v tests.test_control_state`
Expected: FAIL because reducer types do not exist.

- [ ] **Step 3: Implement explicit transition tables and copy-on-write reduction**

```python
SESSION_TRANSITIONS = {
    "created": frozenset({"running", "failed", "cancelled"}),
    "running": frozenset({"paused", "checkpointing", "recovery_required", "completed", "failed", "cancelled", "budget_limited"}),
    "paused": frozenset({"running", "completed", "failed", "cancelled", "budget_limited"}),
    "checkpointing": frozenset({"running", "recovery_required", "failed", "cancelled"}),
    "recovery_required": frozenset({"running", "failed", "cancelled"}),
}
```

Do not infer completion from stream end. Only a validated terminal event changes the session to terminal. Preserve action maps with `MappingProxyType`; validate every event before transition.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `uv run python -m unittest -v tests.test_control_state`
Expected: PASS for transition matrices, deterministic output and input immutability.

- [ ] **Step 5: Commit state machines**

```bash
git add src/asterion/control/state.py src/asterion/control/__init__.py tests/test_control_state.py
git commit -m "feat: reduce long running control state"
```

### Task 9: Orchestrate commands, events and proposal admission in the control host

**Files:**
- Create: `src/asterion/control/manager.py`
- Modify: `src/asterion/control/__init__.py`
- Test: `tests/test_control_host.py`

**Interfaces:**
- Produces `ControlHost.start`, `dispatch`, `pump`, `resolve_action` and immutable `snapshot`.
- Dispatch journals a command before provider send; event pump journals before acknowledgement/reduction.
- `action.proposed` is evaluated by `AuthorityLedger`, journals one decision, sends one `action.resolve`, and never invokes an application in Phase 0.
- Duplicate equal commands/events replay original outcomes; divergent duplicates, gaps and illegal state enter explicit recovery/fault handling.

- [ ] **Step 1: Write failing host-ordering tests**

```python
async def test_command_is_journaled_before_provider_receives_it(self) -> None:
    await host.dispatch(create_command)
    self.assertEqual(audit.calls, ["journal.command", "provider.send"])

async def test_unauthorized_proposal_is_rejected_without_executor_contact(self) -> None:
    await host.pump(until_terminal=False)
    self.assertEqual(host.snapshot().actions["a-1"].status, "rejected")
    self.assertEqual(application_invocations, [])
```

Cover provider send failure after persistence, event gap, invalid event, accepted proposal reservation, budget exhaustion, cancellation, repeated command IDs and no hidden retries.

- [ ] **Step 2: Run focused tests to verify RED**

Run: `uv run python -m unittest -v tests.test_control_host`
Expected: FAIL because `ControlHost` does not exist.

- [ ] **Step 3: Implement the minimal host control loop**

Inject plan, authority ledger, journal, client and host clock. Keep application execution behind an injected `ActionExecutor` protocol whose Phase 0 test implementation raises if called. On provider transport uncertainty, leave the accepted command journaled and raise a safe recoverable host error; do not synthesize provider events.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `uv run python -m unittest -v tests.test_control_host`
Expected: PASS for ordering, idempotency, admission, failure and budget paths.

- [ ] **Step 5: Commit control-host orchestration**

```bash
git add src/asterion/control/manager.py src/asterion/control/__init__.py tests/test_control_host.py
git commit -m "feat: orchestrate control provider sessions"
```

### Task 10: Add fake-provider conformance and the Phase 0 long-running closure

**Files:**
- Create: `src/asterion/control/testing.py`
- Modify: `src/asterion/control/__init__.py`
- Modify: `tests/test_control_provider.py`
- Modify: `tests/test_control_host.py`
- Create: `tests/test_control_conformance.py`

**Interfaces:**
- Produces deterministic `FakeControlPlaneClient`, scripted fault points and `run_control_provider_conformance(factory)`.
- Common scenarios cover create/run, direct/steer/follow-up delivery, pause/resume, attach/replay, checkpoint, recoverable fault, completion, cancellation, budget-limited, proposal admission/rejection and divergent duplicate rejection.
- The same public conformance entry point will be used by Prime and native providers.

- [ ] **Step 1: Write the failing reusable scenario suite**

```python
async def test_fake_provider_passes_common_conformance(self) -> None:
    report = await run_control_provider_conformance(fake_factory)
    self.assertEqual(report.failed, ())
    self.assertEqual(report.passed, tuple(sorted(REQUIRED_PHASE0_SCENARIOS)))

async def test_reconnect_replays_without_duplicate_terminal_or_action(self) -> None:
    result = await scenario_reconnect_after_persisted_event(fake_factory)
    self.assertEqual(result.terminal_count, 1)
    self.assertEqual(result.action_execution_counts, {"action-1": 1})
```

- [ ] **Step 2: Run conformance tests to verify RED**

Run: `uv run python -m unittest -v tests.test_control_conformance`
Expected: FAIL because the fake provider/harness does not exist.

- [ ] **Step 3: Implement deterministic scripted provider behavior**

The fake owns an ordered command log, generated event log and persisted cursor. It emits only validated events, returns prior outcomes for identical command IDs, can disconnect before/after each scripted event, and supports attach from an exact cursor. It must not import runtime, provider SDK or DCI code.

- [ ] **Step 4: Run conformance and focused host tests to verify GREEN**

Run:

```bash
uv run python -m unittest -v tests.test_control_conformance tests.test_control_host tests.test_control_provider
```

Expected: PASS; all required scenario IDs are sorted and no runtime/model call occurs.

- [ ] **Step 5: Commit the common conformance harness**

```bash
git add src/asterion/control/testing.py src/asterion/control/__init__.py tests/test_control_conformance.py tests/test_control_host.py tests/test_control_provider.py
git commit -m "test: add control provider conformance loop"
```

### Task 11: Project safe causal control evidence into Pathlight

**Files:**
- Create: `src/asterion/control/evidence.py`
- Modify: `src/asterion/control/manager.py`
- Modify: `src/asterion/pathlight/protocol.py`
- Test: `tests/test_control_pathlight.py`
- Modify: `tests/test_pathlight_protocol.py`

**Interfaces:**
- Produces `ControlEvidenceProjector` mapping trusted fixed control events to Pathlight span kinds and safe attributes.
- Extends Pathlight safe kinds only with `system`, `session`, `goal`, `action`, `admission`, `checkpoint`, `continuation` and `fault`.
- Exposes IDs, status, sequence, generation, counts, digests and fixed reason/failure classes; never payload bodies or private references.
- Evidence recording failure cannot change the provider/session execution result, but the conformance report records a required-evidence gap.

- [ ] **Step 1: Write failing causal/redaction tests**

```python
async def test_control_loop_projects_complete_causal_chain(self) -> None:
    recorder = MemoryPathlightRecorder("trace-session-1")
    result = await run_completed_fake_session(pathlight=recorder)
    graph = recorder.snapshot()
    self.assertEqual(_kinds(graph), ("system", "session", "goal", "action", "admission", "checkpoint", "session"))
    self.assertEqual(result.state.session.status, "completed")

async def test_public_trace_never_contains_control_payload_sentinel(self) -> None:
    rendered = repr((await run_sentinel_session()).trace)
    self.assertNotIn("SENTINEL_SECRET", rendered)
    self.assertNotIn("/private/prime/session", rendered)
```

Cover rejected proposals, budget-limited, recovery-required, uncertain action, event gap and recorder failure.

- [ ] **Step 2: Run focused tests to verify RED**

Run: `uv run python -m unittest -v tests.test_control_pathlight tests.test_pathlight_protocol`
Expected: FAIL because control evidence kinds/projector are absent.

- [ ] **Step 3: Implement a fixed projection table**

Map event type to span kind/status and construct attributes only from an allowlist. Hash safe opaque references with existing canonical digest helpers before publication. Inject the recorder/projector into `ControlHost`; catch only `PathlightError`, preserve the control result and append a safe `evidence-gap` status to the host snapshot/conformance report.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `uv run python -m unittest -v tests.test_control_pathlight tests.test_pathlight_protocol tests.test_control_conformance`
Expected: PASS with complete causal projections and sentinel redaction.

- [ ] **Step 5: Commit evidence projection**

```bash
git add src/asterion/control/evidence.py src/asterion/control/manager.py src/asterion/pathlight/protocol.py tests/test_control_pathlight.py tests/test_pathlight_protocol.py
git commit -m "feat: trace long running control causality"
```

### Task 12: Close Phase 0 distribution, documentation and promotion evidence

**Files:**
- Modify: `pyproject.toml` only if promotion tests prove new schema resources are not included by existing wheel rules.
- Modify: `docs/architecture/ASTERION-ARCHITECTURE.md` — position the control plane above application assemblies.
- Create: `docs/architecture/AGENT-CONTROL-PROTOCOL.md` — public safe contract, state/recovery and ownership guide.
- Create: `docs/status/PRIME-PARITY-LEDGER.md` — pinned baseline, phase labels and initial domain status without false PASS.
- Modify: `README.md` only to link the new architecture/protocol documentation.
- Test: `tests/test_packaging.py` or the repository's existing promotion test surface if schema inclusion needs coverage.

**Interfaces:**
- Documents exact ownership, provider interchangeability, authority/admission, uncertain semantics and Phase 0 evidence boundary.
- Publishes all four new schema files in the distribution if repository packaging requires explicit inclusion.
- Records Phase 0 as foundation evidence only; every Prime/native parity domain remains explicit `missing` or `not-run`.

- [ ] **Step 1: Add failing distribution/doc assertions where needed**

Run `make promotion-check` first. If it reports missing schemas, add a focused packaging test that opens the built wheel and asserts all four canonical relative paths. Do not change packaging speculatively when the current source inclusion already passes.

- [ ] **Step 2: Write operator/developer documentation and the initial ledger**

The ledger must include the pinned commit, stable domain IDs, provider columns, evidence command, current state and notes. It must not treat source mapping, unit tests or unavailable external runs as PASS.

- [ ] **Step 3: Run the full Phase 0 verification gate**

Run:

```bash
uv run python -m unittest -v tests.test_agent_system_protocol tests.test_agent_control_protocol tests.test_control_provider tests.test_control_system tests.test_control_authority tests.test_control_journal tests.test_control_state tests.test_control_host tests.test_control_conformance tests.test_control_pathlight
npm --prefix packages/typescript/asterion-runtime test
make test
make lint
make docs-check
make promotion-check
make check
```

Expected: every command PASS provider-free. If any command is external-limited or not rerun, do not promote the corresponding evidence.

- [ ] **Step 4: Review architecture and repository invariants**

Confirm dependency direction, exact identities, schema/Python/TypeScript agreement, immutable values, pre-execution rejection, sentinel redaction, no provider/runtime access, one terminal event, no blind uncertain retry and preserved user-owned worktree changes.

- [ ] **Step 5: Commit Phase 0 closure**

```bash
git add schemas src/asterion/control src/asterion/pathlight packages/typescript/asterion-runtime docs/architecture docs/status/PRIME-PARITY-LEDGER.md README.md pyproject.toml tests
git status --short
git commit -m "feat: establish verifiable agent control foundation"
```

Before committing, remove `docs/status/JOURNAL.md` and `docs/status/RESUME-NEXT-SESSION.md` from the index if they contain unrelated pre-existing user changes. Record the exact passing commands in the normal durable project-state update after the code commit.

## Phase 0 Exit Review

- [ ] Three new closed protocol versions have canonical schemas plus Python and TypeScript agreement.
- [ ] System resolution is exact, deterministic, immutable and rejects all missing edges before provider construction.
- [ ] Provider selection is exact by ID/version; context secrets and private roots are redacted.
- [ ] Authority and budget accounting are host-owned, monotonic, immutable at the contract boundary and revisioned.
- [ ] Journal append/replay and command/event/action idempotency fail closed on divergence.
- [ ] Session/action reducers enforce legal transitions, single decisions, single terminal states and honest `uncertain`.
- [ ] The control host persists before dispatch/acknowledgement and never authorizes a provider implicitly.
- [ ] One common fake-provider suite proves complete, pause/resume, attach/replay, fault/recovery, cancellation and budget-limited sessions.
- [ ] Pathlight exposes complete safe causality and explicit gaps without exposing payload bodies or changing execution results.
- [ ] All Phase 0 gates pass provider-free and no result is mislabeled as Prime `Verified-loop` or parity.
