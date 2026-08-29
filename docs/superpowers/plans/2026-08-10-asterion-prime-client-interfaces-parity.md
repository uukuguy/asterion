# Asterion Prime Client Interfaces Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the nine mandatory Prime client-interface features reachable through one Asterion-owned client session, validated public event stream, and authority-scoped private-value service.

**Architecture:** Add the closed `asterion.agent-client/v1` protocol above `ControlHost` without changing control/runtime v1. Python owns the client endpoint, projection, authority, SDK, adapters, and export/share services; TypeScript validates the shared contract and translates pinned Prime daemon observations into private internal observations. Four exact provider-free evidence packages reduce mechanically to the nine Prime Gateway parity rows.

**Tech Stack:** Python 3.10+, `unittest`, JSON Schema 2020-12, TypeScript 6/Node 22, Ajv 8, existing Asterion control journal/authority/private-store surfaces, pinned Prime Agent 0.7.1 commit `a18809e00ea30638584d87b3afea7285a9d7296c`.

## Global Constraints

- Preserve `CLI/host -> selected provider -> assembly -> catalog/composer -> exact implementations -> runner -> runtime/host services`.
- Do not modify the closed `asterion.agent-control/v1` or `asterion.agent-runtime/v1` contracts.
- Python owns orchestration, authority, admission, canonical client state, application execution, and projection; TypeScript validates shared contracts and owns Prime Node translation.
- Public client events contain no prompts, answers, tool arguments/results, provider payloads, credentials, raw output, private paths, or private destination values.
- Every private resolution binds client/session identity, authority revision, purpose, digest, media type, maximum size, cancellation, and deadline.
- All client surfaces are adapters over one endpoint; none may create a provider, runner, composer, catalog, or implementation resolver.
- Public export is the default. Private export/share requires one-use explicit authority; settings, caches, credentials, and prior exports never grant it.
- Provider-free tests perform zero provider/model operations, zero credential reads, zero external uploads, and no full dataset run.
- Promote only the nine `interface.*` Prime Gateway rows. Keep all native rows and six `operation.*` rows `missing`.
- Every task uses RED -> GREEN -> refactor, an exact focused command, an atomic commit, and independent review before the next task.

---

## File and responsibility map

- `schemas/agent-client/v1/{intent,event}.schema.json` — canonical closed contract.
- `src/asterion/client/protocol.py` — Python immutable values and stream validation.
- `src/asterion/client/private.py` — access envelope, descriptor, private service, export authority.
- `src/asterion/client/session.py` — internal observations, projection, replay, intent idempotency.
- `src/asterion/client/sdk.py` — only programmatic client API.
- `src/asterion/client/jsonl.py`, `rpc.py`, `acp.py` — bounded codecs.
- `src/asterion/client/interactive.py`, `cli.py` — functional interactive/headless views.
- `src/asterion/client/export.py` — safe export and explicitly authorized share.
- `packages/typescript/asterion-runtime/` — matching types, Ajv validation, fixtures.
- `packages/typescript/prime-gateway/src/client-observation.ts` — pinned Prime private observation mapping.
- `src/asterion/control/providers/prime/client_parity_testing.py` — exact four-receipt reducer.

---

### Task 1: Add the closed cross-language agent-client protocol

**Files:**
- Create: `schemas/agent-client/v1/intent.schema.json`
- Create: `schemas/agent-client/v1/event.schema.json`
- Create: `src/asterion/client/__init__.py`
- Create: `src/asterion/client/protocol.py`
- Create: `tests/fixtures/agent_client/v1/valid-intent-input.json`
- Create: `tests/fixtures/agent_client/v1/valid-event-message.json`
- Create: `tests/fixtures/agent_client/v1/valid-event-terminal.json`
- Create: `tests/fixtures/agent_client/v1/invalid-intent-secret.json`
- Create: `tests/fixtures/agent_client/v1/invalid-event-body.json`
- Create: `tests/fixtures/agent_client/v1/invalid-event-unknown.json`
- Create: `tests/test_agent_client_protocol.py`
- Modify: `packages/typescript/asterion-runtime/src/types.ts`
- Modify: `packages/typescript/asterion-runtime/src/validation.ts`
- Modify: `packages/typescript/asterion-runtime/src/index.ts`
- Modify: `packages/typescript/asterion-runtime/scripts/copy-schemas.mjs`
- Modify: `packages/typescript/asterion-runtime/test/type-contract.ts`
- Modify: `packages/typescript/asterion-runtime/test/runtime.test.mjs`
- Modify: `pyproject.toml`, `tests/test_distribution.py`, `tools/check_promotion.py`

**Interfaces:**
- Consumes: existing identifier, opaque-ID, digest, media-type, timestamp, canonical ordering, and recursive immutability rules.
- Produces: `AGENT_CLIENT_PROTOCOL`, `ClientCursor`, `ClientIntent`, `ClientEvent`, `validate_client_intent()`, `validate_client_event()`, and `validate_client_event_stream()` in Python and TypeScript.

- [ ] **Step 1: Write the failing Python fixture and stream tests**

```python
class TestAgentClientProtocol(unittest.TestCase):
    def test_valid_values_are_immutable_and_body_free(self) -> None:
        intent = ClientIntent.from_mapping(_fixture("valid-intent-input.json"))
        event = ClientEvent.from_mapping(_fixture("valid-event-message.json"))
        self.assertEqual(intent.protocol, "asterion.agent-client/v1")
        self.assertEqual(event.payload["content_ref"], "private-message-1")
        self.assertNotIn("SENTINEL_BODY", repr(event))

    def test_stream_rejects_gap_mixed_generation_and_post_terminal(self) -> None:
        first = ClientEvent.from_mapping(_fixture("valid-event-message.json"))
        terminal = ClientEvent.from_mapping(_fixture("valid-event-terminal.json"))
        validate_client_event_stream((first, terminal))
        with self.assertRaises(ClientProtocolError):
            validate_client_event_stream((first, replace(terminal, sequence=3)))
```

- [ ] **Step 2: Run RED**

Run: `uv run python -m unittest -v tests.test_agent_client_protocol`

Expected: FAIL because `asterion.client.protocol` and fixtures do not exist.

- [ ] **Step 3: Implement the exact Python contract and JSON Schemas**

```python
AGENT_CLIENT_PROTOCOL = "asterion.agent-client/v1"
CLIENT_INTENT_TYPES = frozenset({
    "command.invoke", "export.request", "extension-ui.respond", "input.submit",
    "session.attach", "session.cancel", "session.create", "session.detach",
    "session.pause", "session.resume", "share.request",
})
CLIENT_EVENT_TYPES = frozenset({
    "artifact.available", "commands.changed", "export.created",
    "extension-ui.requested", "fault.raised", "message.available",
    "session.state", "session.terminal", "share.created", "tool.completed",
    "tool.started", "usage.reported",
})

CLIENT_INTENT_PAYLOAD_FIELDS = MappingProxyType({
    "command.invoke": ("arguments_ref", "command_name", "command_revision"),
    "export.request": ("destination_ref", "expires_at_ms", "export_id", "max_bytes", "media_type", "reference_ids", "visibility"),
    "extension-ui.respond": ("cancelled", "request_id", "response_ref"),
    "input.submit": ("content_ref", "delivery", "input_id"),
    "session.attach": ("cursor",),
    "session.cancel": ("reason_code",),
    "session.create": ("goal_id", "goal_ref"),
    "session.detach": ("reason_code",),
    "session.pause": ("reason_code",),
    "session.resume": ("reason_code",),
    "share.request": ("expires_at_ms", "export_id", "share_id"),
})

CLIENT_EVENT_PAYLOAD_FIELDS = MappingProxyType({
    "artifact.available": ("artifact_id", "artifact_ref", "media_type", "sha256", "size"),
    "commands.changed": ("commands", "revision"),
    "export.created": ("artifact_id", "artifact_ref", "export_id", "media_type", "sha256", "size", "visibility"),
    "extension-ui.requested": ("deadline_ms", "method", "payload_ref", "request_id"),
    "fault.raised": ("code", "evidence_ref", "recoverable"),
    "message.available": ("content_ref", "media_type", "message_id", "role", "sha256", "size"),
    "session.state": ("reason_code", "status"),
    "session.terminal": ("reason_code", "status"),
    "share.created": ("export_id", "share_id", "share_ref"),
    "tool.completed": ("call_id", "is_error", "media_type", "result_ref", "sha256", "size"),
    "tool.started": ("arguments_ref", "call_id", "name", "sha256", "size"),
    "usage.reported": ("aggregate_tokens", "application_tokens", "child_tokens", "controller_tokens", "cost_micros"),
})

@dataclass(frozen=True)
class ClientCursor:
    generation: int
    sequence: int

@dataclass(frozen=True, repr=False)
class ClientIntent:
    protocol: str
    intent_id: str
    client_id: str
    session_id: str
    authority_revision: int
    type: str
    payload: Mapping[str, object]

@dataclass(frozen=True, repr=False)
class ClientEvent:
    protocol: str
    event_id: str
    session_id: str
    generation: int
    sequence: int
    emitted_at: str
    type: str
    payload: Mapping[str, object]
```

Both schemas use `additionalProperties: false`. Body-bearing events use only opaque references plus digest/size/media metadata. The forbidden property names are `text`, `prompt`, `answer`, `arguments`, `output`, `credential`, `path`, and `destination`.

- [ ] **Step 4: Add matching TypeScript unions and semantic validation**

```typescript
export const AGENT_CLIENT_PROTOCOL = "asterion.agent-client/v1" as const;
export interface ClientCursor { readonly generation: number; readonly sequence: number }
export interface ClientEventBase<T extends string, P> {
  readonly protocol: typeof AGENT_CLIENT_PROTOCOL;
  readonly event_id: string;
  readonly session_id: string;
  readonly generation: number;
  readonly sequence: number;
  readonly emitted_at: string;
  readonly type: T;
  readonly payload: P;
}
```

`validateClientEventStream()` rejects mixed sessions/generations, gaps, duplicate event IDs, unmatched tools, duplicate terminal events, and post-terminal events. Copy both schemas into the TS build and export all new types/validators.

- [ ] **Step 5: Package and verify both implementations**

Run:

```bash
uv run python -m unittest -v tests.test_agent_client_protocol tests.test_distribution
npm --prefix packages/typescript/asterion-runtime test
```

Expected: PASS; Python and TypeScript accept/reject the same fixtures.

- [ ] **Step 6: Commit**

```bash
git add schemas/agent-client src/asterion/client tests/fixtures/agent_client tests/test_agent_client_protocol.py tests/test_distribution.py packages/typescript/asterion-runtime pyproject.toml tools/check_promotion.py
git commit -m "feat: define agent client protocol"
```

---

### Task 2: Build the host-owned client session and private boundary

**Files:**
- Create: `src/asterion/client/private.py`
- Create: `src/asterion/client/session.py`
- Create: `tests/test_client_session.py`
- Modify: `src/asterion/client/__init__.py`
- Modify: `src/asterion/control/journal.py`, `src/asterion/control/manager.py`
- Modify: `tests/test_control_journal.py`, `tests/test_control_host.py`

**Interfaces:**
- Consumes: Task 1 values; `ControlHost.dispatch()`, `.pump()`, `.snapshot()`; `CanonicalJournal`.
- Produces: `ClientAccess`, `PrivateValueDescriptor`, `ClientPrivateValueBackend`, `ClientPrivateValueService`, `ClientObservation`, `ClientObservationSource`, `ClientSessionEndpoint`, and `HostClientSessionEndpoint`.

- [ ] **Step 1: Write failing endpoint/idempotency/private-purpose tests**

```python
class TestClientSession(unittest.IsolatedAsyncioTestCase):
    async def test_persist_before_dispatch_and_identical_retry(self) -> None:
        endpoint, provider, journal = _endpoint()
        intent = _input_intent("intent-1", "private-input-1")
        await endpoint.submit(intent)
        await endpoint.submit(intent)
        self.assertEqual(provider.command_ids, ["client:intent-1"])
        self.assertEqual(_client_kinds(journal), ("client.intent.accepted",))

    async def test_conflicting_retry_and_wrong_private_purpose_reject(self) -> None:
        endpoint, provider, _journal = _endpoint()
        await endpoint.submit(_input_intent("intent-1", "private-input-1"))
        with self.assertRaises(ClientSessionError):
            await endpoint.submit(_input_intent("intent-1", "private-input-2"))
        with self.assertRaises(ClientPrivateValueError):
            endpoint.private_values.resolve_text(
                "private-input-1", purpose="private-export", max_bytes=32, deadline_ms=10
            )
        self.assertEqual(provider.command_ids, ["client:intent-1"])
```

- [ ] **Step 2: Run RED**

Run: `uv run python -m unittest -v tests.test_client_session tests.test_control_journal tests.test_control_host`

Expected: FAIL because endpoint and client journal records do not exist.

- [ ] **Step 3: Implement exact private contracts**

```python
@dataclass(frozen=True, repr=False)
class ClientAccess:
    client_id: str
    session_id: str
    authority_revision: int
    purposes: tuple[str, ...]

@dataclass(frozen=True, repr=False)
class PrivateValueDescriptor:
    reference: str
    kind: str
    media_type: str
    size: int
    sha256: str

class ClientPrivateValueBackend(Protocol):
    def describe(self, reference: str) -> PrivateValueDescriptor: ...
    def read(self, reference: str, *, max_bytes: int) -> bytes: ...
```

`ClientPrivateValueService` validates `interactive-render`, `headless-final`, `extension-ui-response`, or `private-export`; checks identity/digest before and after read; and rejects stale authority, cancellation, expiry, and excess size.

- [ ] **Step 4: Implement observation source and endpoint**

```python
@dataclass(frozen=True, repr=False)
class ClientObservation:
    observation_id: str
    session_id: str
    generation: int
    source_sequence: int
    emitted_at: str
    kind: str
    payload: Mapping[str, object]

class ClientObservationSource(Protocol):
    def client_observations(self, cursor: ClientCursor | None = None) -> AsyncIterator[ClientObservation]: ...

class ClientSessionEndpoint(Protocol):
    @property
    def private_values(self) -> ClientPrivateValueService: ...
    async def submit(self, intent: ClientIntent) -> str: ...
    def events(self, cursor: ClientCursor | None = None) -> AsyncIterator[ClientEvent]: ...
    async def pump(self, *, until_terminal: bool = False) -> None: ...
    async def close(self) -> None: ...
```

`HostClientSessionEndpoint` implements this protocol. Map lifecycle/input intents to existing `ControlCommand` values. Journal exact `client.intent.accepted`, `client.observation.accepted`, and `client.event.accepted` records before dispatch/ack. Rebuild intent digests and event prefix during recovery without resolving bodies.

- [ ] **Step 5: Run twice and commit**

```bash
uv run python -m unittest -v tests.test_client_session tests.test_control_journal tests.test_control_host
uv run python -m unittest -v tests.test_client_session tests.test_control_journal tests.test_control_host
git add src/asterion/client src/asterion/control/journal.py src/asterion/control/manager.py tests/test_client_session.py tests/test_control_journal.py tests/test_control_host.py
git commit -m "feat: add host client session"
```

---

### Task 3: Translate pinned Prime observations through the private Gateway boundary

**Files:**
- Create: `packages/typescript/prime-gateway/src/client-observation.ts`
- Create: `packages/typescript/prime-gateway/test/client-observation.test.mjs`
- Create: `tests/test_prime_client_observations.py`
- Modify: `packages/typescript/prime-gateway/src/gateway.ts`, `main.ts`, `index.ts`, `private-store.ts`
- Modify: `packages/typescript/prime-gateway/test/gateway.test.mjs`, `main.test.mjs`
- Modify: `src/asterion/control/providers/prime/client.py`, `factory.py`
- Modify: `tests/test_prime_control_factory.py`

**Interfaces:**
- Consumes: Task 2 observation/private protocols and existing Prime daemon cursor/private store.
- Produces: capability `client-observations-v1`; private commands `client_observations` and `client_value_read`; `PrimeControlPlaneClient.client_observations()`, `.describe()`, and `.read()`.

- [ ] **Step 1: Write failing Gateway/Python bridge tests**

```typescript
test("stores client bodies and emits only references", async () => {
  const mapped = await mapper.map({
    type: "session_event",
    activeSessionId: "prime-session-1",
    event: { type: "message_end", role: "assistant", content: "SENTINEL_BODY" },
  });
  assert.equal(mapped[0].kind, "message.available");
  assert.equal(typeof mapped[0].payload.content_ref, "string");
  assert.equal(JSON.stringify(mapped).includes("SENTINEL_BODY"), false);
});
```

```python
async def test_prime_observations_are_body_free_and_replayable(self) -> None:
    observations = [item async for item in self.client.client_observations()]
    replay = [item async for item in self.client.client_observations(ClientCursor(1, 1))]
    self.assertEqual(replay, observations[1:])
    self.assertNotIn("SENTINEL_BODY", repr(observations))
```

- [ ] **Step 2: Run RED**

```bash
npm --prefix packages/typescript/prime-gateway test -- test/client-observation.test.mjs test/gateway.test.mjs test/main.test.mjs
uv run python -m unittest -v tests.test_prime_client_observations tests.test_prime_control_factory
```

Expected: FAIL because the observation bridge/capability is absent.

- [ ] **Step 3: Implement the closed private mapper**

```typescript
export type PrimeClientObservationKind =
  | "artifact.available" | "commands.changed" | "extension-ui.requested"
  | "message.available" | "tool.completed" | "tool.started";

export interface PrimeClientObservation {
  readonly observation_id: string;
  readonly active_session_id: string;
  readonly generation: number;
  readonly source_sequence: number;
  readonly emitted_at: string;
  readonly kind: PrimeClientObservationKind;
  readonly payload: Readonly<Record<string, unknown>>;
}
```

Store message content, tool arguments/results, extension UI payloads, and artifact bodies before emitting. Emit only immutable references/descriptors. Reject unknown methods, cursor gaps, oversized values, post-close observations, and cross-session references.

- [ ] **Step 4: Bind the Python adapter and exact factory capability**

Add `client-observations-v1` to the Prime capability tuple. Decode every sidecar mapping into Task 2 values and convert transport/decode failures to fixed redacted errors. Factory tests require declaration and implemented shape to agree.

- [ ] **Step 5: Run twice and commit**

```bash
npm --prefix packages/typescript/prime-gateway test -- test/client-observation.test.mjs test/gateway.test.mjs test/main.test.mjs
uv run python -m unittest -v tests.test_prime_client_observations tests.test_prime_control_factory
npm --prefix packages/typescript/prime-gateway test -- test/client-observation.test.mjs test/gateway.test.mjs test/main.test.mjs
uv run python -m unittest -v tests.test_prime_client_observations tests.test_prime_control_factory
git add packages/typescript/prime-gateway/src packages/typescript/prime-gateway/test src/asterion/control/providers/prime tests/test_prime_client_observations.py tests/test_prime_control_factory.py
git commit -m "feat: bridge Prime client observations"
```

---

### Task 4: Deliver the SDK and bounded JSONL core package

**Files:**
- Create: `src/asterion/client/sdk.py`, `src/asterion/client/jsonl.py`
- Create: `tests/test_client_sdk_jsonl.py`, `tests/test_prime_client_core.py`
- Modify: `src/asterion/client/__init__.py`, `Makefile`

**Interfaces:**
- Consumes: Task 2 endpoint/protocol/private service.
- Produces: `AgentClient`, `JsonlClientCodec`, and `test.prime-client-core.provider-free` for `interface.sdk` and `interface.json-stream`.

- [ ] **Step 1: Write failing SDK/framing tests**

```python
class TestAgentClient(unittest.IsolatedAsyncioTestCase):
    async def test_sdk_uses_injected_endpoint_only(self) -> None:
        client = AgentClient(_recording_endpoint(), client_id="client-1")
        accepted = await client.submit_input(
            session_id="session-1", authority_revision=1,
            input_id="input-1", content_ref="private-input-1", delivery="direct",
        )
        self.assertEqual(accepted, "client-1:input-1")
        self.assertFalse(hasattr(client, "runtime"))

    def test_jsonl_rejects_partial_oversized_and_nested_frames(self) -> None:
        codec = JsonlClientCodec(max_line_bytes=128, max_depth=8)
        for frame in (b"{", b"{\"x\":\"" + b"a" * 129, b"[[[[[[[[[0]]]]]]]]]"):
            with self.subTest(frame=frame[:8]), self.assertRaises(ClientJsonlError):
                codec.feed(frame, eof=True)
```

- [ ] **Step 2: Run RED**

Run: `uv run python -m unittest -v tests.test_client_sdk_jsonl tests.test_prime_client_core`

Expected: FAIL because SDK, codec, and receipt do not exist.

- [ ] **Step 3: Implement exact SDK/codec signatures**

```python
class AgentClient:
    def __init__(self, endpoint: ClientSessionEndpoint, *, client_id: str) -> None:
        _require_client_id(client_id)
        self._endpoint = endpoint
        self._client_id = client_id

    async def submit(self, intent: ClientIntent) -> str:
        if intent.client_id != self._client_id:
            raise AgentClientError("client intent identity mismatches")
        return await self._endpoint.submit(intent)

    def events(self, cursor: ClientCursor | None = None) -> AsyncIterator[ClientEvent]:
        return self._endpoint.events(cursor)

    def resolve_text(self, reference: str, *, purpose: str, max_bytes: int, deadline_ms: int) -> str:
        return self._endpoint.private_values.resolve_text(
            reference, purpose=purpose, max_bytes=max_bytes, deadline_ms=deadline_ms
        )

    async def close(self) -> None:
        await self._endpoint.close()

class JsonlClientCodec:
    def feed(self, data: bytes, *, eof: bool = False) -> tuple[Mapping[str, object], ...]:
        self._buffer.extend(data)
        lines = _take_complete_lf_lines(self._buffer, self._max_line_bytes)
        if eof and self._buffer:
            raise ClientJsonlError("client JSONL final line is incomplete")
        return tuple(_decode_bounded_object(line, self._max_depth) for line in lines)

    def encode(self, value: Mapping[str, object]) -> bytes:
        encoded = canonical_json_bytes(value) + b"\n"
        if len(encoded) > self._max_line_bytes:
            raise ClientJsonlError("client JSONL line exceeds limit")
        return encoded
```

The codec accepts LF only, one object per line, strict UTF-8, bounded line/depth, and no partial final line. It emits no logs and never resolves references.

- [ ] **Step 4: Add exact gate and receipt checks**

```make
test.prime-client-core.provider-free:
	$(UV_BIN) run python -m unittest -v \
		tests.test_client_sdk_jsonl \
		tests.test_prime_client_core
```

The receipt binds exact command/features/scenarios, stream/private-service digests, provider operations `0`, credential reads `0`, and retained processes `0`.

- [ ] **Step 5: Run twice and commit**

```bash
make test.prime-client-core.provider-free
make test.prime-client-core.provider-free
git add src/asterion/client tests/test_client_sdk_jsonl.py tests/test_prime_client_core.py Makefile
git commit -m "feat: add client SDK and JSONL"
```

---

### Task 5: Deliver RPC and ACP protocol adapters

**Files:**
- Create: `src/asterion/client/rpc.py`, `src/asterion/client/acp.py`
- Create: `tests/test_client_rpc_acp.py`, `tests/test_prime_client_protocols.py`
- Modify: `src/asterion/client/__init__.py`, `Makefile`

**Interfaces:**
- Consumes: Task 4 `AgentClient` and JSONL codec.
- Produces: `ClientRpcAdapter`, `ClientAcpAdapter`, and `test.prime-client-protocols.provider-free` for `interface.rpc` and `interface.acp`.

- [ ] **Step 1: Write failing ack/event/stdout-purity tests**

```python
async def test_rpc_acknowledges_admission_and_streams_terminal(self) -> None:
    adapter = ClientRpcAdapter(_agent_client())
    ack = await adapter.request({"id": "rpc-1", "method": "input.submit", "params": _input_params()})
    self.assertEqual(ack, {"id": "rpc-1", "type": "ack", "intent_id": "intent-1"})
    self.assertEqual([item["type"] async for item in adapter.events()], ["session.terminal"])

async def test_acp_rejects_unknown_request_without_stdout_data(self) -> None:
    output = io.BytesIO()
    adapter = ClientAcpAdapter(_agent_client(), stdout=output)
    with self.assertRaises(ClientAcpError):
        await adapter.request({"id": "acp-1", "method": "private.dump", "params": {}})
    self.assertEqual(output.getvalue(), b"")
```

- [ ] **Step 2: Run RED**

Run: `uv run python -m unittest -v tests.test_client_rpc_acp tests.test_prime_client_protocols`

Expected: FAIL because both adapters are absent.

- [ ] **Step 3: Implement exact mappings**

```python
RPC_METHODS = frozenset(CLIENT_INTENT_TYPES)
ACP_EVENT_METHODS = MappingProxyType({
    "artifact.available": "artifact_update",
    "fault.raised": "session_error",
    "message.available": "agent_message_chunk",
    "session.state": "session_update",
    "session.terminal": "session_end",
    "tool.completed": "tool_call_update",
    "tool.started": "tool_call",
    "usage.reported": "usage_update",
})
```

RPC duplicates with the same digest return the original ack; conflicts reject. Results remain events/references. ACP maps only the table above, returns one explicit unsupported error, and writes protocol frames only to stdout.

- [ ] **Step 4: Add gate, run twice, and commit**

```make
test.prime-client-protocols.provider-free:
	$(UV_BIN) run python -m unittest -v \
		tests.test_client_rpc_acp \
		tests.test_prime_client_protocols
```

```bash
make test.prime-client-protocols.provider-free
make test.prime-client-protocols.provider-free
git add src/asterion/client tests/test_client_rpc_acp.py tests/test_prime_client_protocols.py Makefile
git commit -m "feat: add client RPC and ACP"
```

---

### Task 6: Deliver interactive, headless, TUI command, and extension UI behavior

**Files:**
- Create: `src/asterion/client/interactive.py`, `src/asterion/client/cli.py`
- Create: `tests/test_client_interactive.py`, `tests/test_prime_client_interactive.py`
- Modify: `src/asterion/client/__init__.py`, `src/asterion/cli.py`
- Modify: `tests/test_asterion_cli.py`, `Makefile`

**Interfaces:**
- Consumes: Task 4 `AgentClient`; command/UI events from Task 1.
- Produces: `ClientViewState`, `reduce_client_view()`, `ClientCommandRegistry`, `run_interactive()`, `run_headless()`, and `test.prime-client-interactive.provider-free` for four features.

- [ ] **Step 1: Write failing functional-view/headless tests**

```python
async def test_command_revision_and_ui_timeout_are_deterministic(self) -> None:
    state = reduce_client_view(ClientViewState.empty("session-1", 1), _commands_event(2))
    self.assertEqual(state.command_revision, 2)
    with self.assertRaises(ClientInteractiveError):
        reduce_client_view(state, _commands_event(1))
    response = await respond_to_extension_ui(_timed_out_request(), _agent_client())
    self.assertEqual(response.payload, {"request_id": "ui-1", "cancelled": True, "response_ref": None})

async def test_headless_resolves_only_final_message(self) -> None:
    output = io.StringIO()
    await run_headless(_agent_client(), mode="text", stdout=output)
    self.assertEqual(output.getvalue(), "FINAL_SENTINEL\n")
    self.assertEqual(_backend_reads(), [("private-final-1", "headless-final")])
```

- [ ] **Step 2: Run RED**

Run: `uv run python -m unittest -v tests.test_client_interactive tests.test_asterion_cli tests.test_prime_client_interactive`

Expected: FAIL because view reducer/client CLI do not exist.

- [ ] **Step 3: Implement immutable functional state**

```python
@dataclass(frozen=True)
class ClientViewState:
    session_id: str
    generation: int
    next_sequence: int
    status: str | None
    command_revision: int
    commands: tuple[ClientCommand, ...]
    pending_ui: Mapping[str, ClientUiRequest]
    terminal: bool = False

def reduce_client_view(state: ClientViewState, event: ClientEvent) -> ClientViewState:
    _require_next_client_event(state, event)
    reducer = _VIEW_EVENT_REDUCERS.get(event.type)
    if reducer is None:
        raise ClientInteractiveError("client event is unsupported")
    updated = reducer(state, event)
    return replace(updated, next_sequence=state.next_sequence + 1)
```

Define `_VIEW_EVENT_REDUCERS` with one function for every Task 1 event type. Reject sequence gaps, revision rollback, duplicate command names, UI request reuse, unmatched tool completion, and post-terminal events. Tests compare accessible content/state transitions, never pixels.

- [ ] **Step 4: Add CLI views without changing one-shot execution**

Add a `client` parser requiring an explicitly injected `AgentClient` factory. Modes are `interactive`, `json`, and `text`. Existing `list`, `describe`, `verify`, `run`, `pathlight`, `capability`, and `benchmark` tests must remain unchanged. JSON emits public events only; text resolves only the final admitted message.

- [ ] **Step 5: Add gate, run twice, and commit**

```make
test.prime-client-interactive.provider-free:
	$(UV_BIN) run python -m unittest -v \
		tests.test_client_interactive \
		tests.test_asterion_cli \
		tests.test_prime_client_interactive
```

```bash
make test.prime-client-interactive.provider-free
make test.prime-client-interactive.provider-free
git add src/asterion/client src/asterion/cli.py tests/test_client_interactive.py tests/test_asterion_cli.py tests/test_prime_client_interactive.py Makefile
git commit -m "feat: add functional client views"
```

---

### Task 7: Deliver safe export and authority-scoped sharing

**Files:**
- Create: `src/asterion/client/export.py`
- Create: `tests/test_client_export_share.py`, `tests/test_prime_client_export_share.py`
- Modify: `src/asterion/client/private.py`, `session.py`, `__init__.py`
- Modify: `src/asterion/control/journal.py`, `tests/test_control_journal.py`, `Makefile`

**Interfaces:**
- Consumes: complete validated event stream and Task 2 private service/revision.
- Produces: `ClientExportAuthority`, `ClientArtifactStore`, `ClientShareService`, `export_client_session()`, `share_client_export()`, and `test.prime-client-export-share.provider-free`.

- [ ] **Step 1: Write failing public-default/one-use tests**

```python
def test_public_export_never_resolves_private_references(self) -> None:
    receipt = export_client_session(_events(), visibility="public", artifacts=_store())
    self.assertEqual(_backend_reads(), [])
    self.assertEqual(receipt.media_type, "application/vnd.asterion.client-events+json")
    self.assertNotIn("SENTINEL_BODY", repr(receipt))

def test_private_export_authority_is_exact_and_one_use(self) -> None:
    authority = _private_export_authority(sequence=9, max_bytes=4096)
    export_client_session(_events(), visibility="private", artifacts=_store(), authority=authority)
    with self.assertRaises(ClientExportError):
        export_client_session(_events(), visibility="private", artifacts=_store(), authority=authority)
```

- [ ] **Step 2: Run RED**

Run: `uv run python -m unittest -v tests.test_client_export_share tests.test_control_journal tests.test_prime_client_export_share`

Expected: FAIL because export/share contracts are absent.

- [ ] **Step 3: Implement exact authority/service contracts**

```python
@dataclass(frozen=True, repr=False)
class ClientExportAuthority:
    authority_id: str
    client_id: str
    session_id: str
    authority_revision: int
    generation: int
    covered_sequence: int
    reference_ids: tuple[str, ...]
    destination_ref: str
    media_type: str
    max_bytes: int
    expires_at_ms: int

class ClientArtifactStore(Protocol):
    def publish(self, *, media_type: str, content: bytes) -> ClientArtifactReceipt: ...

class ClientShareService(Protocol):
    def share(self, artifact: ClientArtifactReceipt, *, authority: ClientExportAuthority) -> ClientShareReceipt: ...
```

Public export canonicalizes public events only. Private export validates all references/limits before reads, consumes authority before publication, and journals a body-free receipt. Without an injected share service, return the local opaque export reference and perform zero uploads.

- [ ] **Step 4: Add exact journal kinds/gate, run twice, and commit**

Add `client.export.receipted` and `client.share.receipted` containing only IDs, digests, media type, visibility, and opaque storage/share refs.

```make
test.prime-client-export-share.provider-free:
	$(UV_BIN) run python -m unittest -v \
		tests.test_client_export_share \
		tests.test_prime_client_export_share
```

```bash
make test.prime-client-export-share.provider-free
make test.prime-client-export-share.provider-free
git add src/asterion/client src/asterion/control/journal.py tests/test_client_export_share.py tests/test_control_journal.py tests/test_prime_client_export_share.py Makefile
git commit -m "feat: add safe client export and share"
```

---

### Task 8: Prove all four packages through the pinned Prime process

**Files:**
- Create: `packages/typescript/prime-gateway/resources/prime-client-module.mjs`
- Create: `packages/typescript/prime-gateway/resources/prime-client-module-lock.json`
- Create: `tests/fixtures/prime_gateway/v1/real-prime-clients.mjs`
- Create: `packages/typescript/prime-gateway/test/client-interface.test.mjs`
- Modify: `packages/typescript/prime-gateway/src/gateway.ts`, `test/main.test.mjs`, `package.json`
- Modify: `tests/test_prime_client_core.py`, `tests/test_prime_client_protocols.py`
- Modify: `tests/test_prime_client_interactive.py`, `tests/test_prime_client_export_share.py`
- Modify: `pyproject.toml`, `tests/test_distribution.py`, `tools/check_promotion.py`, `tests/test_check_promotion.py`

**Interfaces:**
- Consumes: Tasks 3–7 and pinned Prime source.
- Produces: four canonical receipts bound to source/artifact/module/portfolio/protocol/private-service identities.

- [ ] **Step 1: Make the four tests require the real harness**

```python
EXPECTED_PACKAGE_COUNTS = {
    "core": {"feature_count": 2, "scenario_count": 2},
    "protocols": {"feature_count": 2, "scenario_count": 2},
    "interactive": {"feature_count": 4, "scenario_count": 4},
    "export-share": {"feature_count": 1, "scenario_count": 1},
}
```

Invoke `real-prime-clients.mjs` per package and reject missing/skipped prerequisites.

- [ ] **Step 2: Run four gates and verify RED**

```bash
make test.prime-client-core.provider-free
make test.prime-client-protocols.provider-free
make test.prime-client-interactive.provider-free
make test.prime-client-export-share.provider-free
```

Expected: each fails because locked module/harness is absent.

- [ ] **Step 3: Build the locked module over exact Prime anchors**

Import only ledger-named SDK, CLI, RPC, ACP, JSONL, print, slash-command, extension-UI, and export/share anchors. Export `runClientPackage(frame)`, use deterministic provider/model fakes, and return body-free digests/counts. Lock exact source commit, module digest, anchor/transitive digests, Node floor `22.8.0`, and zero network/provider expectations.

- [ ] **Step 4: Add exact failure/redaction matrices and packaging**

Cover wrong source/module/artifact identity, cursor gap, partial/oversized frame, sentinel body/credential, disconnect, cancellation, retained process, stdout purity, command revision rollback, UI timeout, public-export private-read count, and unauthorized upload count. Force-include module/lock in wheel and promotion copy/resource smoke.

- [ ] **Step 5: Run four gates twice and commit**

```bash
make test.prime-client-core.provider-free
make test.prime-client-protocols.provider-free
make test.prime-client-interactive.provider-free
make test.prime-client-export-share.provider-free
make test.prime-client-core.provider-free
make test.prime-client-protocols.provider-free
make test.prime-client-interactive.provider-free
make test.prime-client-export-share.provider-free
git add packages/typescript/prime-gateway/resources/prime-client-module.mjs packages/typescript/prime-gateway/resources/prime-client-module-lock.json packages/typescript/prime-gateway/test/client-interface.test.mjs packages/typescript/prime-gateway/src/gateway.ts packages/typescript/prime-gateway/test/main.test.mjs packages/typescript/prime-gateway/package.json tests/fixtures/prime_gateway/v1/real-prime-clients.mjs tests/test_prime_client_core.py tests/test_prime_client_protocols.py tests/test_prime_client_interactive.py tests/test_prime_client_export_share.py tests/test_distribution.py tests/test_check_promotion.py pyproject.toml tools/check_promotion.py
git commit -m "test: prove pinned Prime client interfaces"
```

---

### Task 9: Reduce four receipts to the exact nine parity rows

**Files:**
- Create: `src/asterion/control/providers/prime/client_parity_testing.py`
- Create: `tests/test_prime_client_parity.py`
- Modify: `src/asterion/control/providers/prime/parity_testing.py`
- Modify: `tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json`
- Modify: `tests/test_prime_parity_ledger.py`, `tests/test_check_prime_parity.py`, `Makefile`

**Interfaces:**
- Consumes: Task 8 four receipts.
- Produces: nine `ParityScenarioRunner` values and exact nine-feature PASS only.

- [ ] **Step 1: Write failing exact-reducer tests**

```python
def test_four_receipts_cover_exact_nine_without_provider_work(self) -> None:
    observations = build_prime_client_observations(_four_receipts())
    self.assertEqual(tuple(item.scenario_id for item in observations), PRIME_CLIENT_SCENARIO_IDS)
    self.assertEqual(len(observations), 9)
    self.assertTrue(all(item.provider_operations == 0 for item in observations))

def test_wrong_identity_count_or_extra_key_rejects_atomically(self) -> None:
    for mutation in _invalid_receipt_mutations():
        with self.subTest(mutation=mutation.name), self.assertRaises(PrimeClientParityError):
            build_prime_client_observations(mutation.receipts)
```

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v tests.test_prime_client_parity tests.test_prime_parity_ledger tests.test_check_prime_parity
uv run python tools/check_prime_parity.py --features interface.sdk,interface.cli-interactive,interface.rpc,interface.acp,interface.json-stream,interface.headless-print,interface.tui-commands,interface.tui-extension-ui,interface.export-share --provider asterion.prime-gateway
```

Expected: BLOCKED with nine `result-missing` rows.

- [ ] **Step 3: Implement exact receipt contracts**

```python
PRIME_CLIENT_PACKAGE_FEATURES = MappingProxyType({
    "core": ("interface.json-stream", "interface.sdk"),
    "protocols": ("interface.acp", "interface.rpc"),
    "interactive": (
        "interface.cli-interactive", "interface.headless-print",
        "interface.tui-commands", "interface.tui-extension-ui",
    ),
    "export-share": ("interface.export-share",),
})
```

Reject missing/extra receipts; identity/key/count drift; noncanonical arrays; nonzero provider/model/credential/process/upload counts; and sentinel leakage. Emit immutable observations sorted by scenario ID.

- [ ] **Step 4: Promote only nine Prime rows and verify twice**

Do not change native or `operation.*` results. Extend tests so six operational rows still block the full domain/system claim.

```bash
uv run python -m unittest -v tests.test_prime_client_parity tests.test_prime_parity_ledger tests.test_check_prime_parity
uv run python tools/check_prime_parity.py --features interface.sdk,interface.cli-interactive,interface.rpc,interface.acp,interface.json-stream,interface.headless-print,interface.tui-commands,interface.tui-extension-ui,interface.export-share --provider asterion.prime-gateway
uv run python -m unittest -v tests.test_prime_client_parity tests.test_prime_parity_ledger tests.test_check_prime_parity
```

Expected: selected `9`, passed `9`, blocking `0`, provider/application operations `0`; full domain remains BLOCKED on six rows.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/control/providers/prime/client_parity_testing.py src/asterion/control/providers/prime/parity_testing.py tests/test_prime_client_parity.py tests/test_prime_parity_ledger.py tests/test_check_prime_parity.py tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json Makefile
git commit -m "feat: close Prime client interface parity"
```

---

### Task 10: Close H-035 without broadening claims

**Files:**
- Modify: this plan, `docs/status/PRIME-PARITY-LEDGER.md`, `CURRENT-STATE.md`, `RESUME-NEXT-SESSION.md`, `JOURNAL.md`
- Modify: `docs/status/climb/{hypotheses.yaml,runs.csv,session-state.json,research-tree.md}`
- Modify: `tools/climb/cycle.sh`, `tools/climb/regen-tree.py`, `tests/test_prime_climb.py`
- Create: `.superpowers/sdd/client-interfaces-task-10-report.md`

**Interfaces:**
- Consumes: Tasks 1–9 and four gates.
- Produces: one H-035 PASS, pending H-036 operational inventory, and no broader claim.

- [x] **Step 1: Add deterministic transition tests**

```python
EXPECTED_H035 = {
    "hypothesis": "H-035",
    "outcome": "passed",
    "next_action": "H-036",
    "command_id": "check.client-interfaces-closure",
}
```

H-036 description is `operational surface inventory identifies six host-owned authority packages`, parent `interface-operations`, ranking `0.7`, status `pending`. Require unique contiguous cycles.

- [x] **Step 2: Teach cycle/regen the exact gate**

`cycle.sh H-035` runs four client gates, exact nine-feature checker, `make check`, `make promotion-check`, and `git diff --check`, then records PASS. `regen-tree.py` derives H-035/H-036 only from canonical runs.

- [x] **Step 3: Run the clean closure**

From a clean detached worktree with exact pinned Prime checkout/rebuilt workspaces:

```bash
tools/climb/cycle.sh H-035
```

Expected: H-035 passed once, H-036 next, provider operations `0`, full dataset `no`. A skipped mandatory real-Prime gate is not PASS.

- [x] **Step 4: Record exact claims/non-claims**

Record nine client PASS rows, four receipts, native/operational rows still missing, broader claims BLOCKED, zero provider/model/credential/upload operations, and H-035 exactly once.

- [x] **Step 5: Run final verification and commit**

```bash
uv run python -m unittest -v tests.test_agent_client_protocol tests.test_client_session tests.test_client_sdk_jsonl tests.test_client_rpc_acp tests.test_client_interactive tests.test_client_export_share tests.test_prime_client_observations tests.test_prime_client_core tests.test_prime_client_protocols tests.test_prime_client_interactive tests.test_prime_client_export_share tests.test_prime_client_parity tests.test_prime_climb tests.test_check_promotion tests.test_prime_parity_ledger tests.test_check_prime_parity
uv run python tools/check_docs.py
git diff --check
git add docs/superpowers/plans/2026-08-10-asterion-prime-client-interfaces-parity.md docs/status/PRIME-PARITY-LEDGER.md docs/status/CURRENT-STATE.md docs/status/RESUME-NEXT-SESSION.md docs/status/climb tools/climb tests/test_prime_climb.py .superpowers/sdd/client-interfaces-task-10-report.md
git commit -m "docs: close H035 client interfaces"
```

---

## Final review checklist

- [ ] Schemas, Python, and TypeScript agree on every field/invariant.
- [ ] Existing control/runtime v1 behavior is unchanged.
- [ ] Python remains the only orchestration/authority/projection owner.
- [ ] Prime Gateway exposes references, never public client bodies.
- [ ] All adapters use one `AgentClient`; none selects execution dependencies.
- [ ] Public export performs no private read; private export/share uses exact one-use authority.
- [x] Four gates repeat provider-free with exact locks and sentinel redaction.
- [x] Nine-feature checker is 9/9 while operational/native rows remain missing.
- [x] `make check`, `make promotion-check`, and clean H-035 cycle pass before promotion.
- [x] H-035 appears exactly once; H-036 is pending; no broader claim is recorded.
