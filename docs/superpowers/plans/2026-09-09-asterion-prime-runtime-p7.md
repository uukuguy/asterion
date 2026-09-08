# Asterion-Prime Agent Runtime and P7 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first source-independent `asterion.prime` agent runtime on Asterion/Pi and prove it by autonomously solving ARC-AGI-3 `ls20-9607627b` level one with DeepSeek V4 Flash.

**Architecture:** `asterion.prime` is an AgentRuntime peer of the future `asterion.native` AgentRuntime, not an application and not a wrapper around Prime Agent. It consumes the common Asterion runner, capability packages, host services, and a framework-owned Pi RPC/session layer. P7 is the first application selecting `asterion.prime`; the Pi foundation and application-owned IPython extension remain internal implementation details.

**Tech Stack:** Python 3.10+, `unittest`, asyncio, Asterion runtime/control protocols, Pi JSONL-RPC, TypeScript/Node 20+, ARC-AGI-3 offline engine, Hatch/uv.

## Global Constraints

- Asterion implementation and release artifacts must not import, load, launch, inspect, source-lock, or require Prime Agent source or SDK.
- `asterion-prime` and `asterion-native` are peer agent implementations over the same public Asterion framework.
- P1 through P7 are applications; this plan implements the first Asterion-prime runtime slice and the P7 application only.
- Python owns orchestration, composition, assembly, and execution; TypeScript only implements the Pi extension/Node integration.
- Manifests contain compatibility identities only, never paths, commands, prompts, credentials, provider configuration, or mutable state.
- Framework modules never read `.env`; the operator integration resolves and injects exact model and host-service values after preflight.
- The live preset fixes one game, one Pi session, 500 primitive actions, 128 model callbacks, and a 60-minute deadline.
- The production prompt contains no answer, target coordinates, object identity, or prescribed action sequence.
- Provider-free deterministic action doubles prove plumbing only; they cannot satisfy live-solving acceptance.
- Public results must not expose prompts, model prose, provider payloads, IPython code/output, credentials, raw engine output, or private paths.
- Existing user-owned dirty files must not be reset, cleaned, overwritten, or broad-staged.

---

## File Structure

### Common framework

- Create `src/asterion/runtimes/pi_rpc.py`: domain-neutral Pi JSONL-RPC process/session lifecycle.
- Create `src/asterion/runtimes/pi_extensions.py`: immutable host-resolved extension bindings and inherited-channel validation.
- Modify `src/asterion/runtimes/pi.py`: consume the common RPC/session layer instead of maintaining a second event loop.
- Modify `src/asterion/capabilities/dci/implementation/runtime/pi_rpc.py`: retain DCI-only validation while importing the common transport.

### Asterion-prime agent

- Create `src/asterion/agents/__init__.py` and `src/asterion/agents/prime/__init__.py`: product namespace exports.
- Create `src/asterion/agents/prime/session.py`: immutable session configuration, lifecycle, limits, and terminal result.
- Create `src/asterion/agents/prime/tools.py`: exact tool catalog and tool-call/result matching.
- Create `src/asterion/agents/prime/trace.py`: private contiguous hash-chained event journal.
- Create `src/asterion/runtimes/asterion_prime.py`: `AgentRuntimeClient` adapter backed by the Prime session and common Pi foundation.

### P7 application and Node integration

- Create `packages/typescript/asterion-prime-extension/`: Pi `ipython` extension and closed FD JSONL bridge.
- Create `src/asterion/applications/prime/p7/`: prompt, operator integration, presentation, diagnostics, and comparison.
- Reuse/move source-independent broker, worker, scoring, replay, and receipt logic from `src/asterion/applications/prime_agent/operator/`.
- Create `src/asterion/applications/prime/provider.py` and `assemblies/prime-arc-agi-3-solving.json`: P7 application provider selecting `asterion.prime`.

### Verification and removal

- Add focused `tests/test_pi_session.py`, `tests/test_asterion_prime_*.py`, and `tests/test_prime_p7_native_*.py` suites.
- Modify `pyproject.toml` and `Makefile` only after the new installed route passes provider-free tests.
- Delete P7 Prime SDK gateway/session/preparation paths only after the replacement route is green.

---

### Task 1: Lock the peer-agent and source-detachment contracts

**Files:**
- Create: `src/asterion/agents/__init__.py`
- Create: `src/asterion/agents/prime/__init__.py`
- Create: `src/asterion/agents/prime/detachment.py`
- Create: `tests/test_asterion_prime_architecture.py`
- Modify: `docs/architecture/agent-framework.md`
- Modify: `docs/architecture/runtime-provider-boundaries.md`

**Interfaces:**
- Consumes: installed wheel metadata and repository source paths.
- Produces: `assert_asterion_prime_source_detached(root: Path) -> None` as the authoritative static gate.

- [ ] **Step 1: Write the failing architecture tests**

```python
class TestAsterionPrimeArchitecture(unittest.TestCase):
    def test_release_path_has_no_prime_agent_dependency(self):
        assert_asterion_prime_source_detached(Path.cwd())

    def test_architecture_declares_peer_agents_and_application_boundary(self):
        body = Path("docs/architecture/agent-framework.md").read_text(encoding="utf-8")
        self.assertIn("asterion-prime", body)
        self.assertIn("asterion-native", body)
        self.assertIn("P1 through P7 are applications", body)
```

- [ ] **Step 2: Run the tests and verify the missing native product fails**

Run: `uv run python -m unittest -v tests.test_asterion_prime_architecture`

Expected: FAIL because the detachment gate and corrected architecture wording do not exist.

- [ ] **Step 3: Add the closed static gate**

```python
FORBIDDEN = tuple(
    "".join(parts)
    for parts in (
        ("prime", "SourceRoot"),
        ("ASTERION_", "PRIME_SOURCE_ROOT"),
        ("createAgent", "Session"),
        ("loadPrime", "Sdk"),
        ("3th-party/", "prime-agent"),
    )
)

def assert_asterion_prime_source_detached(root: Path) -> None:
    owned = (root / "src/asterion/agents/prime", root / "src/asterion/runtimes/asterion_prime.py")
    for path in (child for base in owned if base.exists() for child in ([base] if base.is_file() else base.rglob("*"))):
        if path.is_file() and path.suffix in {".py", ".ts", ".mjs", ".json"}:
            body = path.read_text(encoding="utf-8")
            if any(token in body for token in FORBIDDEN):
                raise AssertionError("Asterion-prime source dependency is forbidden")
```

- [ ] **Step 4: Document the peer relationship and claim boundary**

State explicitly that `asterion.prime` and `asterion.native` are peer agent implementations, while P1–P7 are applications. Mark current Prime Gateway evidence historical and non-native.

- [ ] **Step 5: Run the focused test**

Run: `uv run python -m unittest -v tests.test_asterion_prime_architecture`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/asterion/agents/__init__.py src/asterion/agents/prime/__init__.py src/asterion/agents/prime/detachment.py tests/test_asterion_prime_architecture.py docs/architecture/agent-framework.md docs/architecture/runtime-provider-boundaries.md
git commit -m "test: lock asterion prime architecture"
```

### Task 2: Extract the domain-neutral Pi RPC session

**Files:**
- Create: `src/asterion/runtimes/pi_rpc.py`
- Create: `tests/test_pi_session.py`
- Modify: `src/asterion/capabilities/dci/implementation/runtime/pi_rpc.py`
- Modify: `tests/test_dci_pi_rpc_proxy.py`
- Modify: `tests/test_dci_pi_rpc_recovery.py`

**Interfaces:**
- Produces: `PiRpcConfig`, `PiRpcEvent`, and `PiRpcSession.run(prompt, *, signal, on_event) -> PiRpcResult`.
- Preserves: DCI-specific context and provider-request validation in the DCI package.

- [ ] **Step 1: Write transport lifecycle tests**

```python
async def collect(fake_command: tuple[str, ...], signal: FakeSignal) -> PiRpcResult:
    session = PiRpcSession(PiRpcConfig(command=fake_command, cwd=work, environment={}, deadline_seconds=2.0))
    return await session.run("inspect", signal=signal, on_event=events.append)

def test_rpc_requires_ack_and_settled_terminal(self):
    result = asyncio.run(collect(fake_pi("ack-settled"), FakeSignal(False)))
    self.assertEqual(result.final_text, "done")
    self.assertEqual([event.type for event in result.events][-1], "agent_settled")
```

Cover malformed JSON, unexpected EOF, response mismatch, sequence preservation, output caps, deadline, cancellation before start, cancellation during prompt, and bounded cleanup.

- [ ] **Step 2: Verify the tests fail before extraction**

Run: `uv run python -m unittest -v tests.test_pi_session`

Expected: FAIL with `ModuleNotFoundError: asterion.runtimes.pi_rpc`.

- [ ] **Step 3: Implement immutable common values**

```python
@dataclass(frozen=True, slots=True)
class PiRpcConfig:
    command: tuple[str, ...]
    cwd: Path
    environment: Mapping[str, str]
    deadline_seconds: float
    inherited_fds: tuple[int, ...] = ()

@dataclass(frozen=True, slots=True)
class PiRpcEvent:
    sequence: int
    type: str
    payload: Mapping[str, object]

@dataclass(frozen=True, slots=True)
class PiRpcResult:
    final_text: str
    events: tuple[PiRpcEvent, ...]
    stderr: bytes
```

Move only process startup, literal argv construction, JSONL request/response, cancellation, deadlines, caps, and shutdown from the DCI client. Do not move DCI context profiles or Pathlight entry interpretation.

- [ ] **Step 4: Rebind DCI to the common transport**

Keep the public DCI `PiRpcClient` facade temporarily, but implement its process operations through `PiRpcSession`. Assert its existing command, observation, recovery, and proxy tests remain byte-for-byte compatible.

- [ ] **Step 5: Run common and DCI tests**

Run: `uv run python -m unittest -v tests.test_pi_session tests.test_dci_pi_rpc_proxy tests.test_dci_pi_rpc_recovery tests.test_dci_pi_rpc_observation`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/asterion/runtimes/pi_rpc.py src/asterion/capabilities/dci/implementation/runtime/pi_rpc.py tests/test_pi_session.py tests/test_dci_pi_rpc_proxy.py tests/test_dci_pi_rpc_recovery.py
git commit -m "refactor: share pi rpc session transport"
```

### Task 3: Add exact host-resolved Pi extension bindings

**Files:**
- Create: `src/asterion/runtimes/pi_extensions.py`
- Create: `tests/test_pi_runtime_extensions.py`
- Modify: `src/asterion/runtime/defaults.py`
- Modify: `src/asterion/runtimes/pi.py`

**Interfaces:**
- Produces: `PiExtensionBinding(extension_id, path, capabilities, inherited_fds, environment)`.
- Consumes: one exact binding from `RuntimeFactoryContext.host_services` after preflight.

**Approved protocol amendment (2026-09-09):** `path` identifies a comment-free,
self-contained `.mjs` source artifact, not the pathname handed directly to Pi.
Preflight pins its bytes and declared descriptors in an owned single-run lease.
Pi receives an installed Asterion loader via literal `--extension LOADER_PATH`;
the loader verifies and imports the pinned source FD. Only static `node:` imports
are supported. All other dependency forms fail before runtime construction.

- [ ] **Step 1: Write validation and immutability tests**

```python
def test_extension_binding_is_exact_and_immutable(self):
    binding = PiExtensionBinding(
        extension_id="prime.ipython",
        path=extension.resolve(),
        capabilities=("prime.tool.ipython",),
        inherited_fds=(7,),
        environment={"ASTERION_PRIME_IPYTHON_FD": "7"},
    )
    self.assertEqual(binding.capabilities, ("prime.tool.ipython",))
    with self.assertRaises(TypeError):
        binding.environment["SECRET"] = "sentinel"
```

Also reject relative/symlink paths, unsorted/duplicate capabilities, bad FDs, undeclared environment names, multiple bindings, and capability mismatches before process start.

- [ ] **Step 2: Run and observe the missing type**

Run: `uv run python -m unittest -v tests.test_pi_runtime_extensions`

Expected: FAIL because `PiExtensionBinding` is missing.

- [ ] **Step 3: Implement the closed binding**

```python
@dataclass(frozen=True, repr=False, slots=True)
class PiExtensionBinding:
    extension_id: str
    path: Path
    capabilities: tuple[str, ...]
    inherited_fds: tuple[int, ...]
    environment: Mapping[str, str]

    def command_args(self) -> tuple[str, str]:
        return ("--extension", str(self.path))
```

Snapshot the environment with `RedactedImmutableMapping`; never expose it from `repr` or public events.

- [ ] **Step 4: Wire the factory and runtime**

Allow exactly one `extension_host_capability` option. Resolve it from host services, append literal `--extension PATH`, pass only its allowlisted inherited FDs/environment, and derive runtime capabilities from the fixed base plus the binding.

- [ ] **Step 5: Run focused runtime regression**

Run: `uv run python -m unittest -v tests.test_pi_runtime_extensions tests.test_default_runtime_factory tests.test_asterion_pi_runtime`

Expected: PASS with no changes to `pi.reference` behavior when no extension binding is selected.

- [ ] **Step 6: Commit**

```bash
git add src/asterion/runtimes/pi_extensions.py src/asterion/runtime/defaults.py src/asterion/runtimes/pi.py tests/test_pi_runtime_extensions.py
git commit -m "feat: bind exact pi application extensions"
```

### Task 4: Implement the Asterion-prime session and AgentRuntime

**Files:**
- Modify: `src/asterion/agents/prime/__init__.py`
- Create: `src/asterion/agents/prime/session.py`
- Create: `src/asterion/agents/prime/tools.py`
- Create: `src/asterion/runtimes/asterion_prime.py`
- Create: `tests/test_asterion_prime_session.py`
- Create: `tests/test_asterion_prime_runtime.py`

**Interfaces:**
- Produces: `AsterionPrimeSession.run(request, signal) -> AsyncIterator[RunEvent]`.
- Produces: `AsterionPrimeRuntimeClient` with runtime ID `asterion.prime`.
- Consumes: common `PiRpcSession`, exact `PiExtensionBinding`, and fixed limits.

- [ ] **Step 1: Write failing session tests**

```python
def test_session_emits_one_valid_terminal(self):
    events = asyncio.run(run_session(FakePiRpcSession.success("solved")))
    validate_event_stream([event.to_mapping() for event in events])
    self.assertEqual(events[-1].type, "run.completed")

def test_tool_call_result_ids_must_match(self):
    with self.assertRaisesRegex(ProtocolError, "tool result"):
        asyncio.run(run_session(FakePiRpcSession.unmatched_tool_result()))
```

Cover one active request, reused run IDs, callback cap 128, cancellation, deadline, uncertain tool effect, malformed Pi events, terminal uniqueness, and content-free public failures.

- [ ] **Step 2: Run and verify the new product is absent**

Run: `uv run python -m unittest -v tests.test_asterion_prime_session tests.test_asterion_prime_runtime`

Expected: FAIL with missing `asterion.agents.prime` and `asterion.runtimes.asterion_prime`.

- [ ] **Step 3: Implement the session configuration and tool ledger**

```python
@dataclass(frozen=True, slots=True)
class AsterionPrimeLimits:
    model_callbacks: int
    tool_callbacks: int
    deadline_ms: int

@dataclass(frozen=True, slots=True)
class PrimeToolCall:
    call_id: str
    name: str
    arguments: Mapping[str, object]

@dataclass(frozen=True, slots=True)
class PrimeToolResult:
    call_id: str
    status: Literal["ok", "error", "uncertain"]
    content: tuple[Mapping[str, object], ...]
```

`PrimeToolLedger` accepts each call ID once, accepts one matching result once, and refuses terminal sealing while a call is unmatched or uncertain.

- [ ] **Step 4: Implement the runtime adapter**

```python
class AsterionPrimeRuntimeClient:
    @property
    def manifest(self) -> RuntimeManifest:
        return RuntimeManifest(
            runtime_id="asterion.prime",
            capabilities=("prime.arc-agi-3-solving", "prime.tool.ipython"),
        )

    def run(self, request: RunRequest, *, signal: CancellationSignal | None = None) -> AsyncIterator[RunEvent]:
        return self._session.run(request, signal=signal)
```

The adapter translates only Asterion-prime/Pi native events into `asterion.agent-runtime/v1`; it does not compose, authorize, retry, or read operator configuration.

- [ ] **Step 5: Run the session/runtime tests**

Run: `uv run python -m unittest -v tests.test_asterion_prime_session tests.test_asterion_prime_runtime tests.test_runtime_protocol`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/asterion/agents src/asterion/runtimes/asterion_prime.py tests/test_asterion_prime_session.py tests/test_asterion_prime_runtime.py
git commit -m "feat: add asterion prime agent runtime"
```

### Task 5: Add the application-owned persistent IPython extension

**Files:**
- Create: `packages/typescript/asterion-prime-extension/package.json`
- Create: `packages/typescript/asterion-prime-extension/tsconfig.json`
- Create: `packages/typescript/asterion-prime-extension/src/ipython-extension.ts`
- Create: `packages/typescript/asterion-prime-extension/test/ipython-extension.test.mjs`
- Create: `src/asterion/applications/prime/p7/ipython_host.py`
- Create: `tests/test_prime_p7_native_ipython.py`

**Interfaces:**
- Node protocol: one request `{protocol, request_id, type:"execute", code}` and one matching result `{protocol, request_id, type:"result", status, output}`.
- Python host: `PersistentIpythonHost.execute(call_id: str, code: str, signal: CancellationSignal) -> PrimeToolResult`.

- [ ] **Step 1: Write failing Node and Python contract tests**

```typescript
assert.deepEqual(extension.toolNames(), ["ipython"]);
await assert.rejects(() => bridge.handle({ protocol: PROTOCOL, request_id: "r1", type: "execute", code: "" }));
```

```python
def test_state_persists_across_cells(self):
    host = make_host()
    self.assertEqual(run(host.execute("c1", "value = 40", signal)).status, "ok")
    self.assertIn("42", run(host.execute("c2", "print(value + 2)", signal)).output)
```

- [ ] **Step 2: Run and verify both surfaces fail**

Run: `npm --prefix packages/typescript/asterion-prime-extension test && uv run python -m unittest -v tests.test_prime_p7_native_ipython`

Expected: FAIL because the package and Python host do not exist.

- [ ] **Step 3: Implement the single-tool extension**

```typescript
export default function register(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "ipython",
    description: "Execute one cell in the injected persistent analysis worker.",
    parameters: Type.Object({ code: Type.String({ minLength: 1 }) }),
    execute: async (id, input, signal) => bridge.execute(id, input.code, signal),
  });
}
```

Use direct FD reads/writes, strict exact-key validation, UTF-8, line/output caps, and matched request IDs. Do not import Prime Agent, ARC, or provider modules.

- [ ] **Step 4: Adapt the existing restricted persistent worker**

Move source-independent orchestration from `ipython_host_orchestrator.py` and `ipython_host_supervisor.py` behind `PersistentIpythonHost`. Expose only injected `p7_client.observe()`, `status()`, and `act(actions)` inside the worker.

- [ ] **Step 5: Run persistence, cancellation, cap, and redaction tests**

Run: `npm --prefix packages/typescript/asterion-prime-extension test && uv run python -m unittest -v tests.test_prime_p7_native_ipython tests.test_prime_ipython_host_orchestrator tests.test_prime_ipython_host_supervisor`

Expected: PASS; sentinel provider values and private paths are absent from exceptions and public results.

- [ ] **Step 6: Commit**

```bash
git add packages/typescript/asterion-prime-extension src/asterion/applications/prime/p7/ipython_host.py tests/test_prime_p7_native_ipython.py
git commit -m "feat: add asterion prime ipython extension"
```

### Task 6: Rehouse the source-independent P7 broker and replay boundary

**Files:**
- Create: `src/asterion/applications/prime/p7/broker.py`
- Create: `src/asterion/applications/prime/p7/replay.py`
- Create: `src/asterion/applications/prime/p7/score.py`
- Create: `tests/test_prime_p7_native_broker.py`
- Create: `tests/test_prime_p7_native_replay.py`

**Interfaces:**
- Produces: `ArcBroker.observe()`, `status()`, `act(actions)` and `seal() -> ArcRunReceipt`.
- Enforces: game `ls20-9607627b`, seed `0`, 500 primitive actions, and immediate stop at first level transition.

- [ ] **Step 1: Write the broker boundary matrix**

```python
def test_batch_stops_at_first_level_transition(self):
    broker = make_broker(level_after=2)
    result = broker.act(("ACTION1", "ACTION2", "ACTION3"))
    self.assertEqual(result.applied_count, 2)
    self.assertEqual(result.levels_completed, 1)

def test_action_after_transition_is_rejected(self):
    broker = solved_broker()
    with self.assertRaisesRegex(ArcBrokerError, "closed"):
        broker.act(("ACTION1",))
```

Cover sequence, malformed action, unavailable action, oversized batch, cap exhaustion, engine exception as uncertain, immutable observations, and deterministic replay mismatch.

- [ ] **Step 2: Run the new tests and observe missing modules**

Run: `uv run python -m unittest -v tests.test_prime_p7_native_broker tests.test_prime_p7_native_replay`

Expected: FAIL with missing P7 native modules.

- [ ] **Step 3: Move reusable logic without wrapper imports**

Copy behavior, not Prime gateway dependencies, from `p7_solving_broker.py`, `p7_solving_broker_service.py`, and `p7_solving_score.py`. The new modules may import the ARC engine adapter and Asterion contracts only.

```python
class ArcBrokerError(RuntimeError):
    pass

@dataclass(frozen=True, slots=True)
class ArcTransition:
    sequence: int
    action: str
    before_sha256: str
    after_sha256: str
    levels_completed: int

@dataclass(frozen=True, slots=True)
class ArcActResult:
    applied_count: int
    levels_completed: int
    transitions: tuple[ArcTransition, ...]

def act(self, actions: tuple[str, ...]) -> ArcActResult:
    self._require_open()
    validated = self._validate_actions(actions)
    transitions = []
    for action in validated:
        before = self._snapshot()
        after = self._engine.step(action)
        transitions.append(self._commit_transition(action, before, after))
        if self._levels_completed(after) > self._initial_levels:
            self._terminal_reason = "level-completed"
            break
    return self._result(transitions)
```

- [ ] **Step 4: Implement deterministic replay sealing**

```python
@dataclass(frozen=True, slots=True)
class ArcRunReceipt:
    game_id: str
    seed: int
    primitive_actions: int
    levels_completed: int
    terminal_reason: str
    replay_sha256: str
```

Replay starts a fresh engine, applies journaled primitive actions, and requires every before/after digest and the terminal level count to match.

- [ ] **Step 5: Run old/new differential broker tests**

Run: `uv run python -m unittest -v tests.test_prime_p7_native_broker tests.test_prime_p7_native_replay tests.test_prime_p7_solving_broker tests.test_prime_p7_solving_score`

Expected: PASS with the known 13-action fixture accepted only as replay/plumbing evidence.

- [ ] **Step 6: Commit**

```bash
git add src/asterion/applications/prime/p7/broker.py src/asterion/applications/prime/p7/replay.py src/asterion/applications/prime/p7/score.py tests/test_prime_p7_native_broker.py tests/test_prime_p7_native_replay.py
git commit -m "feat: add source-independent p7 broker"
```

### Task 7: Seal the joined private trace and passive diagnostics

**Files:**
- Create: `src/asterion/agents/prime/trace.py`
- Create: `src/asterion/applications/prime/p7/diagnostics.py`
- Create: `src/asterion/applications/prime/p7/comparison.py`
- Create: `tests/test_asterion_prime_trace.py`
- Create: `tests/test_prime_p7_diagnostics.py`
- Create: `tests/test_prime_p7_comparison.py`

**Interfaces:**
- Produces: `PrimeTraceRecorder.append(kind, identities, private_payload) -> PrimeTraceEntry` and `seal() -> PrimeTraceSeal`.
- Produces: `analyze_trace(entries) -> DiagnosticReport` and `compare_runs(left, right) -> DifferentialReport`.

- [ ] **Step 1: Write hash-chain, redaction, and deterministic-analysis tests**

```python
def test_trace_is_contiguous_and_hash_chained(self):
    first = recorder.append("session.started", ids, {})
    second = recorder.append("arc.action", ids, {"action": "ACTION1"})
    self.assertEqual(second.sequence, first.sequence + 1)
    self.assertEqual(second.previous_sha256, first.sha256)

def test_repeated_noop_and_resource_reset_are_labeled(self):
    report = analyze_trace(noop_then_life_loss_trace())
    self.assertGreaterEqual(report.repeated_action_streak, 3)
    self.assertEqual(report.deaths, 1)
```

- [ ] **Step 2: Run and verify missing trace modules**

Run: `uv run python -m unittest -v tests.test_asterion_prime_trace tests.test_prime_p7_diagnostics tests.test_prime_p7_comparison`

Expected: FAIL with missing modules.

- [ ] **Step 3: Implement immutable trace entries**

```python
@dataclass(frozen=True, repr=False, slots=True)
class PrimeTraceEntry:
    sequence: int
    kind: str
    identities: Mapping[str, str]
    payload: Mapping[str, object]
    previous_sha256: str | None
    sha256: str

@dataclass(frozen=True, slots=True)
class PrimeTraceSeal:
    entry_count: int
    final_sha256: str
    sealed_at: str

@dataclass(frozen=True, slots=True)
class DiagnosticReport:
    no_op_streak: int
    repeated_action_streak: int
    cycles: int
    deaths: int
    actions_since_progress: int
    contradicted_hypotheses: int
    experiment_information_gain: tuple[float, ...]

@dataclass(frozen=True, slots=True)
class DifferentialReport:
    schema: str
    left: Mapping[str, object]
    right: Mapping[str, object]
    deltas: Mapping[str, object]
```

Write through pinned directory FDs with no symlink traversal. Reject gaps, identity changes, invalid UTF-8, oversized values, digest mismatch, and appends after sealing.

- [ ] **Step 4: Implement passive diagnostics and neutral normalizer**

The analyzer reads a sealed trace only and returns no callback into the session. The normalizer emits model/reasoning identity, counts, normalized actions/state digests, hypothesis/replan markers, no-op/cycle/death/resource-loss markers, and terminal outcome.

```python
def analyze_trace(entries: tuple[PrimeTraceEntry, ...]) -> DiagnosticReport:
    transitions = tuple(entry for entry in entries if entry.kind == "arc.action")
    return DiagnosticReport(
        no_op_streak=max_no_op_streak(transitions),
        repeated_action_streak=max_repeated_action_streak(transitions),
        cycles=normalized_cycles(transitions),
        deaths=count_resource_loss_resets(transitions),
        actions_since_progress=actions_since_level_progress(transitions),
        contradicted_hypotheses=count_contradicted_hypotheses(entries),
        experiment_information_gain=estimate_information_gain(transitions),
    )
```

- [ ] **Step 5: Run determinism and sentinel-redaction tests**

Run: `uv run python -m unittest -v tests.test_asterion_prime_trace tests.test_prime_p7_diagnostics tests.test_prime_p7_comparison`

Expected: PASS; serializing public reports never contains `sentinel-secret`, private paths, prompts, code, or raw frames.

- [ ] **Step 6: Commit**

```bash
git add src/asterion/agents/prime/trace.py src/asterion/applications/prime/p7/diagnostics.py src/asterion/applications/prime/p7/comparison.py tests/test_asterion_prime_trace.py tests/test_prime_p7_diagnostics.py tests/test_prime_p7_comparison.py
git commit -m "feat: seal prime trace diagnostics"
```

### Task 8: Publish the new P7 application and runtime binding

**Files:**
- Create: `src/asterion/applications/prime/__init__.py`
- Create: `src/asterion/applications/prime/provider.py`
- Create: `src/asterion/applications/prime/runtime_binding.py`
- Create: `src/asterion/applications/prime/assemblies/prime-arc-agi-3-solving.json`
- Create: `src/asterion/applications/prime/p7/prompt.py`
- Create: `src/asterion/applications/prime/p7/operator.py`
- Modify: `pyproject.toml`
- Create: `tests/test_prime_p7_native_provider.py`

**Interfaces:**
- Produces application provider `prime-applications` and application `prime.arc-agi-3-solving@1.0.0`.
- Produces runtime binding `asterion.prime` with host services `prime.pi-extension`, `prime.ipython`, `prime.arc-broker`, and `prime.private-trace`.

- [ ] **Step 1: Write provider/assembly tests**

```python
def test_p7_application_selects_only_asterion_prime(self):
    provider = create_provider()
    app = provider.applications[0]
    self.assertEqual(app.runtime_ids, ("asterion.prime",))
    self.assertEqual(app.capability_packages, (CapabilityPackageRef("prime-arc-agi-3-solver", "1.0.0"),))

def test_listing_is_metadata_only(self):
    listed = list_application_providers(entry_points=fake_entry_points())
    self.assertIn("prime-applications", [item.provider_id for item in listed])
    self.assertFalse(model_or_worker_started())
```

- [ ] **Step 2: Run and verify provider absence**

Run: `uv run python -m unittest -v tests.test_prime_p7_native_provider`

Expected: FAIL with missing `asterion.applications.prime`.

- [ ] **Step 3: Add the exact assembly**

```json
{
  "protocol": "asterion.application-assembly/v1",
  "application_id": "prime.arc-agi-3-solving",
  "version": "1.0.0",
  "runtime_id": "asterion.prime",
  "capability_packages": [{"package_id": "prime-arc-agi-3-solver", "version": "1.0.0"}],
  "capabilities": [{"capability_id": "prime.arc-agi-3-solving", "version": "1.0.0"}],
  "host_capabilities": ["prime.arc-broker", "prime.ipython", "prime.pi-extension", "prime.private-trace"],
  "host_policies": [],
  "host_events": [],
  "host_artifacts": []
}
```

- [ ] **Step 4: Bind the peer runtime without putting executable data in JSON**

```python
def asterion_prime_runtime_binding() -> RuntimeFactoryBinding:
    return RuntimeFactoryBinding(
        runtime_id="asterion.prime",
        capabilities=("prime.arc-agi-3-solving", "prime.tool.ipython"),
        factory=build_asterion_prime_runtime,
    )
```

The provider publishes this binding only after exact provider selection. `build_asterion_prime_runtime` consumes the already-preflighted host services and options and returns `AsterionPrimeRuntimeClient`.

- [ ] **Step 5: Write the game-agnostic solve prompt**

```python
P7_SOLVE_PROMPT = """Solve the current interactive puzzle level.
Use only the ipython tool. Inspect every observation programmatically, maintain
explicit hypotheses about objects and controls, test uncertainty with short
experiments, compare before/after state, reject no-ops and death paths, and
revise contradicted hypotheses. Continue until status reports one completed
level or the fixed run limit terminates the attempt. Do not assume a known map,
object identity, target coordinate, or action sequence."""
```

- [ ] **Step 6: Implement operator-owned model resolution**

`operator.py` reads the repository `.env` only at the application/operator boundary, resolves exact Pi command/auth/provider/model, fixes all finite limits, creates host services, and returns runtime options. It exposes no user-facing model/cost/deadline knobs.

```python
class P7OperatorError(RuntimeError):
    pass

@dataclass(frozen=True, slots=True)
class P7RuntimeSelection:
    runtime_id: str
    provider: str
    model: str
    max_actions: int
    max_callbacks: int
    deadline_ms: int

def resolve_p7_runtime(environment: Mapping[str, str]) -> P7RuntimeSelection:
    return P7RuntimeSelection(
        runtime_id="asterion.prime",
        provider=resolve_pi_provider(environment, model="deepseek-v4-flash"),
        model="deepseek-v4-flash",
        max_actions=500,
        max_callbacks=128,
        deadline_ms=3_600_000,
    )

def resolve_pi_provider(environment: Mapping[str, str], *, model: str) -> str:
    if model != "deepseek-v4-flash" or not environment.get("DEEPSEEK_API_KEY", "").strip():
        raise P7OperatorError("P7 model host is unavailable")
    return "deepseek"
```

- [ ] **Step 7: Run provider, composition, and metadata-only tests**

Run: `uv run python -m unittest -v tests.test_prime_p7_native_provider tests.test_application_discovery tests.test_application_selection tests.test_installed_application_provider`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/asterion/applications/prime pyproject.toml tests/test_prime_p7_native_provider.py
git commit -m "feat: publish asterion prime p7 application"
```

### Task 9: Prove the provider-free installed route

**Files:**
- Create: `tests/test_prime_p7_native_installed.py`
- Create: `tests/fixtures/asterion_prime/fake_pi_rpc.py`
- Modify: `tools/check_promotion.py`

**Interfaces:**
- Consumes: built wheel installed outside the source tree.
- Produces: full runtime stream, sealed private trace, replay receipt, cleanup receipt, and zero Prime source access.

- [ ] **Step 1: Write the installed-wheel test**

```python
def test_installed_route_runs_without_prime_checkout(self):
    result = run_isolated_wheel(
        provider="prime-applications",
        application="prime.arc-agi-3-solving@1.0.0",
        runtime="asterion.prime",
        environment={"ASTERION_TEST_FORBID_PRIME_SOURCE": "1"},
    )
    self.assertEqual(result.returncode, 0)
    self.assertEqual(result.receipt["levels_completed"], 1)
    self.assertEqual(result.receipt["promotion_state"], "development-only")
```

The fake Pi may follow the 13-action sequence only inside this provider-free fixture; mark the receipt `solver_evidence="deterministic-double"`.

- [ ] **Step 2: Run and verify packaging is incomplete**

Run: `uv run python -m unittest -v tests.test_prime_p7_native_installed`

Expected: FAIL because the new TypeScript extension/runtime resources are not yet packaged.

- [ ] **Step 3: Add package-data and isolated scan assertions**

Build the TypeScript package before Hatch packaging, include only its compiled extension, and scan wheel/sdist imports, entry points, package data, environment names, and spawned argv for forbidden Prime Agent dependencies.

```python
for artifact in build_artifacts:
    report = inspect_archive(artifact)
    if report.prime_source_references or report.prime_sdk_imports:
        raise PromotionError("Asterion-prime distribution is source-coupled")
```

- [ ] **Step 4: Run installed and promotion-focused tests**

Run: `uv run python -m unittest -v tests.test_prime_p7_native_installed tests.test_check_promotion`

Expected: PASS with no Prime checkout present.

- [ ] **Step 5: Commit**

```bash
git add tests/test_prime_p7_native_installed.py tests/fixtures/asterion_prime/fake_pi_rpc.py tools/check_promotion.py pyproject.toml
git commit -m "test: prove installed native p7 route"
```

### Task 10: Run DeepSeek V4 Flash and generate the differential report

**Files:**
- Create: `tools/run_asterion_prime_p7.py`
- Create: `tools/compare_prime_p7_runs.py`
- Modify: `Makefile`
- Create: `tests/test_prime_p7_live_command.py`

**Interfaces:**
- Produces preset `make asterion-prime-p7-solve` with no provider/model/budget flags.
- Produces `compare_prime_p7_runs.py --asterion TRACE --baseline LOG --output REPORT`.

- [ ] **Step 1: Write command-contract tests**

```python
class LiveSolveError(RuntimeError):
    pass

def test_live_command_exposes_no_tuning_knobs(self):
    parser = build_parser()
    self.assertEqual(sorted(action.dest for action in parser._actions), ["help"])

def test_success_requires_authoritative_level_transition(self):
    with self.assertRaisesRegex(LiveSolveError, "level transition"):
        classify_live_result(valid_transport_without_level())
```

- [ ] **Step 2: Run and verify the preset is absent**

Run: `uv run python -m unittest -v tests.test_prime_p7_live_command`

Expected: FAIL because the live command does not exist.

- [ ] **Step 3: Implement the one-action preset**

The script loads operator configuration, selects `deepseek-v4-flash`, invokes the installed `asterion.prime` route, streams public-safe progress to stderr, writes one public receipt to stdout, and stores the full trace only under the authorized private root.

```python
def main() -> int:
    selection = resolve_p7_runtime(load_operator_environment(Path.cwd() / ".env"))
    result = run_installed_p7(selection)
    write_public_receipt(sys.stdout, classify_live_result(result))
    return 0 if result.levels_completed == 1 and result.replay_verified else 1
```

- [ ] **Step 4: Run the authorized live solve**

Run: `make asterion-prime-p7-solve`

Expected PASS boundary: exactly one authoritative level transition, no more than 500 primitive actions/128 callbacks/60 minutes, deterministic replay success, sealed trace, complete cleanup, and exit 0. Any other terminal is recorded as an unsuccessful attempt, not PASS.

- [ ] **Step 5: Generate and verify the neutral comparison**

Run: `uv run python tools/compare_prime_p7_runs.py --asterion "$ASTERION_P7_TRACE" --baseline "$PRIME_P7_BASELINE" --output "$ASTERION_P7_REPORT"`

Expected: exit 0 and a deterministic report containing action/control discovery, hypotheses, replans, no-op/cycle/death markers, first-level outcome, and counts. The 61-action manual baseline stop remains labeled `operator-stopped`.

- [ ] **Step 6: Commit code and provider-free tests, not private evidence**

```bash
git add tools/run_asterion_prime_p7.py tools/compare_prime_p7_runs.py Makefile tests/test_prime_p7_live_command.py
git commit -m "feat: add asterion prime p7 live preset"
```

### Task 11: Remove the P7 Prime SDK wrapper path

**Files:**
- Delete: `packages/typescript/prime-gateway/src/p7-solving-session.ts`
- Delete: `packages/typescript/prime-gateway/src/p7-solving-bridge.ts`
- Delete: `packages/typescript/prime-gateway/src/p7-solving-main.ts`
- Delete: matching `packages/typescript/prime-gateway/test/p7-solving-*.test.mjs`
- Delete: `src/asterion/applications/prime_agent/operator/p7_solving_sdk_provider.py`
- Delete: `src/asterion/applications/prime_agent/operator/p7_solving_gateway.py`
- Delete: `src/asterion/applications/prime_agent/operator/p7_solving_preparation.py`
- Delete: `tools/run_prime_p7_seeded.py`
- Modify: `pyproject.toml`
- Modify: `Makefile`
- Modify: relevant inventories and status documents.

**Interfaces:**
- Consumes: green provider-free installed `asterion.prime` P7 route.
- Produces: one release/acceptance path with no `primeSourceRoot`, Prime SDK, or Prime Gateway P7 execution.

- [ ] **Step 1: Strengthen the detachment test before deletion**

```python
def test_distribution_and_commands_have_no_p7_wrapper(self):
    report = inspect_distribution_and_commands(build_artifacts())
    self.assertEqual(report.forbidden_imports, ())
    self.assertEqual(report.forbidden_resources, ())
    self.assertEqual(report.forbidden_commands, ())
```

- [ ] **Step 2: Run the test and observe current wrapper references**

Run: `uv run python -m unittest -v tests.test_asterion_prime_architecture`

Expected: FAIL listing the P7 gateway force-includes, source-root preparation, and wrapper commands.

- [ ] **Step 3: Delete the wrapper files and exact package references**

Remove only P7 wrapper code after confirming Tasks 8–10 are durable. Preserve source-independent broker/worker/receipt code until each retained part is either moved or proven unused.

- [ ] **Step 4: Correct claims and inventories**

Mark seeded wrapper evidence historical. Report the actual DeepSeek attempt as PASS only if Task 10 met every gate; otherwise report its exact unsuccessful terminal without upgrading it.

- [ ] **Step 5: Run detachment and distribution tests**

Run: `uv run python -m unittest -v tests.test_asterion_prime_architecture tests.test_prime_p7_native_installed && make promotion-check`

Expected: focused tests PASS; `promotion-check` PASS or retains an explicitly named pre-existing/external-limited failure without calling it PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/typescript/prime-gateway/src/p7-solving-session.ts packages/typescript/prime-gateway/src/p7-solving-bridge.ts packages/typescript/prime-gateway/src/p7-solving-main.ts
git add packages/typescript/prime-gateway/test/p7-solving-session.test.mjs packages/typescript/prime-gateway/test/p7-solving-bridge.test.mjs
git add src/asterion/applications/prime_agent/operator/p7_solving_sdk_provider.py src/asterion/applications/prime_agent/operator/p7_solving_gateway.py src/asterion/applications/prime_agent/operator/p7_solving_preparation.py
git add tools/run_prime_p7_seeded.py pyproject.toml Makefile docs/status/FRAMEWORK-INTEGRATION-WORKLIST.md
git commit -m "refactor: remove prime sdk p7 wrapper"
```

### Task 12: Run repository verification and record the bounded claim

**Files:**
- Modify: `docs/status/FRAMEWORK-INTEGRATION-WORKLIST.md`
- Modify: `docs/status/RESUME-NEXT-SESSION.md`
- Modify: `docs/status/JOURNAL.md`
- Create: `docs/status/ASTERION-PRIME-P7-EVIDENCE.md`

**Interfaces:**
- Produces: an evidence ledger distinguishing Implemented, Verified, live PASS/unsuccessful attempt, External-limited, and Not rerun.
- Produces: the next-plan boundary for the Asterion-prime `ControlPlaneClient` and P1–P6 applications.

- [ ] **Step 1: Run focused Python and TypeScript tests**

Run: `uv run python -m unittest -v tests.test_pi_session tests.test_pi_runtime_extensions tests.test_asterion_prime_architecture tests.test_asterion_prime_session tests.test_asterion_prime_runtime tests.test_asterion_prime_trace tests.test_prime_p7_native_ipython tests.test_prime_p7_native_broker tests.test_prime_p7_native_replay tests.test_prime_p7_diagnostics tests.test_prime_p7_comparison tests.test_prime_p7_native_provider tests.test_prime_p7_native_installed tests.test_prime_p7_live_command`

Expected: PASS.

- [ ] **Step 2: Run repository gates**

Run: `make test && make lint && make docs-check && make check && make promotion-check`

Expected: PASS, or each nonzero command is recorded with its exact pre-existing/external-limited boundary and is not promoted.

- [ ] **Step 3: Verify the source-detached artifacts**

Run: `uv build && uv run python tools/check_promotion.py`

Expected: wheel and sdist contain `asterion.prime` and the P7 application, contain no Prime SDK/source artifact, and can execute provider-free outside the checkout.

- [ ] **Step 4: Write the bounded evidence ledger**

Record exact commands, exits, test counts, trace/replay digests, model identity, action/callback/tool counts, terminal reason, cleanup result, and comparison digest. Do not copy private content or paths.

- [ ] **Step 5: State the next program boundary accurately**

The completed claim is only “Asterion-prime AgentRuntime first slice + P7 application.” Create separate plans for the `asterion.prime` ControlPlane surface and P1–P6 applications before claiming complete Asterion-prime parity.

- [ ] **Step 6: Commit**

```bash
git add docs/status/ASTERION-PRIME-P7-EVIDENCE.md docs/status/FRAMEWORK-INTEGRATION-WORKLIST.md docs/status/RESUME-NEXT-SESSION.md docs/status/JOURNAL.md
git commit -m "docs: record asterion prime p7 evidence"
```

---

## Out of Scope and Required Follow-up Plans

This plan deliberately does not claim the complete Asterion-prime product. After this plan, write and execute separate implementation plans for:

1. `asterion.prime` `ControlPlaneClient`, durable sessions, checkpoints, detach/attach, and recovery;
2. context accounting, compaction, long-context continuity, and P2/P4;
3. child sessions, explicit family messaging, and P3;
4. bounded autonomy, deterministic quality gates, and P5;
5. evidence-backed improvement/rollback and P6;
6. P1 persistent coding as a standalone application; and
7. final deletion of all remaining Prime Gateway, `prime.agent`, source-lock, setup, and preparation paths.

Full Asterion-prime completion is permitted only after those agent surfaces and every P1–P7 application gate pass without Prime Agent source or SDK.
