# Prime P7 Real ARC-AGI-3 Solving Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver `make prime-p7-solve`, where the installed `prime.agent` runtime uses the operator-injected `deepseek-v4-flash` service to solve at least the first level of offline `ls20-9607627b` and display the question, dynamic action answer, solved frame, and partial-game score.

**Architecture:** Preserve `prime.arc-agi-3@1.0.0` as the four-action transport smoke and add an exact `prime.arc-agi-3-solving@1.0.0` application backed by a dedicated `prime-arc-agi-3-solver@1.0.0` capability package. A generic Prime preset runtime bridge emits only a receipt descriptor; the solver capability retrieves an immutable run-bound safe receipt from the injected host, while the operator host owns the DeepSeek connection, persistent IPython worker, private ARC broker, scoring, display, limits, and cleanup.

**Tech Stack:** Python 3.11+, `unittest`, Asterion capability/application/runtime v1 contracts, TypeScript Prime gateway, Prime Agent v0.3.3 SDK, Docker/OrbStack, IPython, local `arc_agi`/`arcengine`, Make, Hatch/uv.

## Global Constraints

- P7a is the only implementation scope; P7b public 25-game reproduction and P7c Kaggle execution remain separate work.
- Keep `prime.arc-agi-3@1.0.0`, `prime.arc-agi-3-development`, `fixed-small-verification`, and `prime.p7-development.trace` behavior unchanged.
- New identities are exact: application/capability `prime.arc-agi-3-solving@1.0.0`, package `prime-arc-agi-3-solver@1.0.0`, host capability `prime.arc-agi-3-solving`, preset `solve-first-public-level`, scope/kind `p7-solving`, artifact `prime.p7-solving.receipt`, media type `application/vnd.asterion.prime.p7-solving-receipt+json`.
- Use the runtime-provided `prime.tool.ipython`; do not add `prime-agent@1.0.0` as a capability-package dependency.
- Do not change the four closed Asterion v1 schemas. New Python, TypeScript, manifest, and fixture values must conform to them exactly.
- Source-lock behavior adapted from `PrimeIntellect-ai/arc-agi-3-prime-agent` commit `398d4dd63cf01d00adbea41c13437ba0b8ad40fc`; retain its MIT notice for substantially copied source.
- The solve preset is one game/session, seed 0, 500 primitive actions, batches of 1–20 actions, 128 model callbacks, and a 60-minute wall deadline.
- The model host additionally caps cumulative input at 2,000,000 tokens, cumulative output at 200,000 tokens, cost at 5,000,000 microunits, and each callback output at 4,096 tokens.
- `partial_game_score` is a string matching `(?:0|[1-9][0-9]{0,2})\.[0-9]{6}`, bounded from `0.000000` through `100.000000`, and rounded with `Decimal(...).quantize(Decimal("0.000001"), ROUND_HALF_EVEN)`.
- Runtime events carry only artifact ID/kind/media type/digest. Counts and score appear only in `CapabilityExecutionResult.artifacts[].value` after run/digest-bound receipt retrieval.
- The local presentation sink may show allowlisted grids/actions/counters/score. Public stdout, progress, runtime events, receipts, telemetry, and durable logs must exclude frames, prompts, model prose/reasoning, provider bodies, credentials, raw engine output, and private paths.
- Production solving has no prescribed action sequence. Fixed test actions may exercise boundaries but cannot establish the real-solving PASS.
- Use focused boundary tests. Run broader checks only for changed packaging/contracts; the sole paid acceptance is one real DeepSeek command.
- Preserve unrelated dirty and untracked workspace files. Stage only task-owned paths.

---

### Task 1: Add an explicit host presentation channel

**Owner:** Terra. This is a small framework integration change with a closed, text-only sink.

**Files:**
- Create: `src/asterion/services/presentation.py`
- Modify: `src/asterion/services/registry.py`
- Modify: `src/asterion/cli.py`
- Create: `tests/test_host_presentation.py`
- Modify: `tests/test_host_service_registry.py`
- Modify: `tests/test_asterion_cli.py`

**Interfaces:**
- Produces: `HostPresentationSink.write(text: str) -> None`, `NOOP_HOST_PRESENTATION_SINK`, and `TextHostPresentationSink`.
- Adds a redacted, non-comparable `presentation` field to `HostServiceFactoryContext` and an optional `presentation` argument to `HostServiceFactoryRegistry.open()`.
- The CLI injects a stderr-backed presentation sink for `asterion run`; stdout remains the single public JSON result.

- [ ] **Step 1: Write focused failing tests**

Assert the text sink accepts bounded printable records, flushes them to the supplied stream, rejects control characters and oversized records, and has a redacted `repr`. Assert the registry passes the sink only to selected factories. Assert CLI stdout remains one JSON line while a selected fake host can write an allowlisted presentation record to stderr.

- [ ] **Step 2: Run focused tests and observe the missing surface**

```bash
uv run python -m unittest -v tests.test_host_presentation tests.test_host_service_registry tests.test_asterion_cli
```

Expected: new presentation assertions fail before implementation; existing progress behavior remains green.

- [ ] **Step 3: Implement the generic sink and injection**

Keep presentation separate from `HostProgressReporter`, runtime events, receipts, and telemetry. The sink stores nothing. `HostServiceFactoryContext.__repr__` must not reveal the stream or written text. Managed services continue to bypass factory context and receive no implicit sink.

- [ ] **Step 4: Run focused tests and commit**

```bash
uv run python -m unittest -v tests.test_host_presentation tests.test_host_service_registry tests.test_asterion_cli
git add src/asterion/services/presentation.py src/asterion/services/registry.py src/asterion/cli.py tests/test_host_presentation.py tests/test_host_service_registry.py tests/test_asterion_cli.py
git commit -m "feat(host): add explicit presentation sink"
```

---

### Task 2: Add the generic Prime preset runtime bridge

**Owner:** Sol. This changes the shared Prime runtime boundary.

**Files:**
- Modify: `src/asterion/runtimes/prime_agent_host.py`
- Modify: `src/asterion/runtimes/prime_agent.py`
- Create: `tests/test_prime_preset_runtime.py`

**Interfaces:**
- Produces: `PrimePresetExecutionRequest(run_id: str, preset: str)`.
- Produces: `PrimePresetExecutionResult(run_id: str, receipt_sha256: str, scope: str, promotion: str)`.
- Produces: `PrimePresetExecutionService.execute(request, *, signal=None)`.
- Produces: `PrimePresetExecutionProfile(input_preset, scope, promotion, artifact_id, kind, media_type)` and `PrimePresetRuntimeClient`.
- Preserves: every `PrimeSmallVerification*` type and `PrimeAgentRuntimeClient` behavior.

- [ ] **Step 1: Write the focused failing runtime tests**

Create tests that use this fake service and exact profile:

```python
class _PresetService:
    def __init__(self, result):
        self.result = result
        self.requests = []

    async def execute(self, request, *, signal=None):
        self.requests.append(request)
        return self.result


PROFILE = PrimePresetExecutionProfile(
    input_preset="solve-first-public-level",
    scope="p7-solving",
    promotion="unpromoted",
    artifact_id="prime.p7-solving.receipt",
    kind="p7-solving",
    media_type="application/vnd.asterion.prime.p7-solving-receipt+json",
)
```

Assert the success stream is exactly `run.started`, `artifact.created`, `run.completed`; the artifact contains only ID, kind, media type, and the unprefixed 64-hex digest. Add subtests rejecting a wrong preset, wrong run ID/scope/promotion, malformed digest, extra requested capability, and deadline; assert a pre-cancelled signal produces the existing two-event cancelled stream and a service exception produces the existing safe failed stream. Re-run the existing package/runtime closure tests to prove compatibility.

- [ ] **Step 2: Run the new tests and observe the missing imports**

Run:

```bash
uv run python -m unittest -v tests.test_prime_preset_runtime tests.test_prime_package_runtime_closure
```

Expected: the new module fails to import `PrimePresetExecution*`; the existing runtime tests remain passing.

- [ ] **Step 3: Add immutable generic host values and service protocol**

Add closed validation in `prime_agent_host.py`:

```python
@dataclass(frozen=True)
class PrimePresetExecutionRequest:
    run_id: str
    preset: str

    def __post_init__(self) -> None:
        if type(self.run_id) is not str or not self.run_id or not _IDENTIFIER.fullmatch(self.preset):
            raise PrimePresetExecutionContractError("Prime preset request is invalid")


@dataclass(frozen=True)
class PrimePresetExecutionResult:
    run_id: str
    receipt_sha256: str
    scope: str
    promotion: str

    def __post_init__(self) -> None:
        if (
            type(self.run_id) is not str or not self.run_id
            or _SHA256.fullmatch(self.receipt_sha256) is None
            or not _IDENTIFIER.fullmatch(self.scope)
            or self.promotion != "unpromoted"
        ):
            raise PrimePresetExecutionContractError("Prime preset result is invalid")


@runtime_checkable
class PrimePresetExecutionService(Protocol):
    async def execute(
        self,
        request: PrimePresetExecutionRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> PrimePresetExecutionResult: ...
```

Use the existing repository identifier convention for `_IDENTIFIER`. Keep `run_id` aligned with runtime v1 semantics as any non-empty `str`; the product host may enforce a stricter local pattern. Export the new types without changing old exports.

- [ ] **Step 4: Add the separate runtime profile/client**

Implement `PrimePresetRuntimeClient.run()` with the same cancellation and terminal event shape as `PrimeAgentRuntimeClient`, but validate `request.input_text == profile.input_preset`, call `service.execute(PrimePresetExecutionRequest(...))`, require exact run/scope/promotion, and emit `receipt_sha256.removeprefix("sha256:")`. Keep ARC names out of `src/asterion/runtimes/`.

- [ ] **Step 5: Run the focused runtime tests**

Run the Step 2 command. Expected: all tests pass.

- [ ] **Step 6: Commit the shared bridge**

```bash
git add src/asterion/runtimes/prime_agent.py src/asterion/runtimes/prime_agent_host.py tests/test_prime_preset_runtime.py
git commit -m "feat(prime): add generic preset runtime bridge"
```

---

### Task 3: Install the independent solver capability and application route

**Owner:** Terra. This is ordinary manifest/provider integration using Task 2 interfaces.

**Files:**
- Create: `src/asterion/capabilities/prime_arc_agi_3_solver/__init__.py`
- Create: `src/asterion/capabilities/prime_arc_agi_3_solver/host.py`
- Create: `src/asterion/capabilities/prime_arc_agi_3_solver/provider.py`
- Create: `src/asterion/capabilities/prime_arc_agi_3_solver/payload/capability-package.json`
- Create: `src/asterion/capabilities/prime_arc_agi_3_solver/payload/capabilities/arc-agi-3-solving.json`
- Create: `src/asterion/applications/prime_agent/assemblies/prime-arc-agi-3-solving.json`
- Modify: `src/asterion/applications/first_party_packages.py`
- Modify: `src/asterion/applications/prime_agent/provider.py`
- Modify: `src/asterion/applications/prime_agent/runtime_binding.py`
- Modify: `pyproject.toml`
- Create: `tests/test_prime_arc_agi_3_solver_package.py`
- Create: `tests/test_prime_p7_solving_installed_route.py`
- Modify: `tests/test_prime_p7_installed_route.py`

**Interfaces:**
- Consumes: Task 2 `PrimePresetExecutionService`, profile, and runtime client.
- Produces: `PrimeArcAgi3SolveReceipt` and `PrimeArcAgi3SolveReceiptAccessor.get_receipt(*, run_id, receipt_sha256)`.
- Produces: `create_prime_arc_agi_3_solver_package()` and one exact solver implementation.
- Produces: installed `prime.arc-agi-3-solving@1.0.0` route.

- [ ] **Step 1: Write failing package and installed-route tests**

Define the safe receipt contract in test form with the same canonical helper used by production:

```python
unsigned = {
    "run_id": "prime-p7-solve-route",
    "scope": "p7-solving",
    "promotion": "unpromoted",
    "completed_level_count": 1,
    "primitive_action_count": 22,
    "partial_game_score": "3.571429",
}
receipt = PrimeArcAgi3SolveReceipt.create(
    run_id=unsigned["run_id"],
    completed_level_count=unsigned["completed_level_count"],
    primitive_action_count=unsigned["primitive_action_count"],
    partial_game_score=unsigned["partial_game_score"],
)
self.assertEqual(receipt.scope, "p7-solving")
self.assertEqual(receipt.promotion, "unpromoted")
self.assertEqual(receipt.receipt_sha256, canonical_solve_receipt_sha256(unsigned))
```

Use one fake host object implementing both `execute()` and `get_receipt()`. Resolve the installed provider with both first-party packages, run `solve-first-public-level`, and assert the capability result value is exactly:

```python
{
    "scope": "p7-solving",
    "promotion": "unpromoted",
    "receipt_sha256": receipt.receipt_sha256.removeprefix("sha256:"),
    "completed_level_count": 1,
    "primitive_action_count": 22,
    "partial_game_score": "3.571429",
}
```

Also reject receipt run/digest mismatch, digest tampering after any unsigned-field change, missing accessor, extra receipt fields, malformed score strings, and missing/wrong host service. Assert the old smoke route still returns only its old trace value.

- [ ] **Step 2: Run the tests and observe missing solver package/route**

```bash
uv run python -m unittest -v tests.test_prime_arc_agi_3_solver_package tests.test_prime_p7_solving_installed_route tests.test_prime_p7_installed_route
```

Expected: new package imports or application lookup fail; legacy P7 tests pass.

- [ ] **Step 3: Add the closed public host receipt contract**

Implement `PrimeArcAgi3SolveReceipt` as a frozen dataclass whose `receipt_sha256` is `init=False` and computed by `create()` over canonical JSON of all unsigned fields. Validate exact run ID, nonnegative integer counts, exactly one completed level for P7a, fixed six-decimal score range, and recompute the digest at every retrieval boundary. Implement a runtime-checkable accessor protocol:

```python
@runtime_checkable
class PrimeArcAgi3SolveReceiptAccessor(Protocol):
    def get_receipt(
        self, *, run_id: str, receipt_sha256: str
    ) -> PrimeArcAgi3SolveReceipt: ...
```

- [ ] **Step 4: Create the exact portable payload and provider**

Use canonical JSON with empty benchmark/resource/conformance arrays:

```json
{"benchmark_suites":[],"capabilities":[{"capability_id":"prime.arc-agi-3-solving","version":"1.0.0"}],"conformance":[],"package_id":"prime-arc-agi-3-solver","protocol":"asterion.capability-package/v1","resources":[],"version":"1.0.0"}
```

```json
{"capability_id":"prime.arc-agi-3-solving","consumes_artifacts":[],"consumes_events":[],"emits_events":[],"kind":"capability","produces_artifacts":["application/vnd.asterion.prime.p7-solving-receipt+json"],"protocol":"asterion.capability/v1","provides_capabilities":["prime.arc-agi-3-solving"],"requires_capabilities":["prime.tool.ipython"],"requires_policies":[],"version":"1.0.0"}
```

The implementation must parse the runtime event stream, require the exact artifact descriptor/digest, retrieve the safe receipt from `invocation.host_services["prime.arc-agi-3-solving"]`, recheck run/digest equality, and project only the six allowlisted value fields shown in Step 1.

- [ ] **Step 5: Register the built-in package and installed application**

Add `PRIME_ARC_AGI_3_SOLVER_PACKAGE` plus a lazy factory to `first_party_packages.py`. Add this exact assembly:

```json
{
  "protocol": "asterion.application-assembly/v1",
  "application_id": "prime.arc-agi-3-solving",
  "version": "1.0.0",
  "runtime_id": "prime.agent",
  "capability_packages": [{"package_id": "prime-arc-agi-3-solver", "version": "1.0.0"}],
  "capabilities": [{"capability_id": "prime.arc-agi-3-solving", "version": "1.0.0"}],
  "host_capabilities": ["prime.arc-agi-3-solving"],
  "host_policies": [],
  "host_events": [],
  "host_artifacts": []
}
```

Register the application in `applications/prime_agent/provider.py`, the application index in `pyproject.toml`, and a separate solve branch in `runtime_binding.py`. The solve branch must require exactly one `PrimePresetExecutionService`, construct the exact Task 2 profile, and return `PrimePresetRuntimeClient`. Do not edit `_ROUTES["prime.arc-agi-3"]`.

- [ ] **Step 6: Run focused package/route tests**

Run the Step 2 command. Expected: all pass, including legacy smoke.

- [ ] **Step 7: Commit installed identities**

Stage only the files listed in this task and commit:

```bash
git add src/asterion/capabilities/prime_arc_agi_3_solver src/asterion/applications/prime_agent/assemblies/prime-arc-agi-3-solving.json src/asterion/applications/first_party_packages.py src/asterion/applications/prime_agent/provider.py src/asterion/applications/prime_agent/runtime_binding.py pyproject.toml tests/test_prime_arc_agi_3_solver_package.py tests/test_prime_p7_solving_installed_route.py tests/test_prime_p7_installed_route.py
git commit -m "feat(prime): install ARC solving capability"
```

---

### Task 4: Implement the bounded dynamic broker, replay, and official partial score

**Owner:** Sol. This is the core game authority and scoring boundary.

**Files:**
- Create: `src/asterion/applications/prime_agent/operator/p7_solving_workload.py`
- Create: `src/asterion/applications/prime_agent/operator/p7_solving_broker.py`
- Create: `src/asterion/applications/prime_agent/operator/p7_solving_client.py`
- Create: `src/asterion/applications/prime_agent/operator/p7_solving_score.py`
- Create: `src/asterion/applications/prime_agent/operator/p7_solving_broker_process.py`
- Create: `src/asterion/applications/prime_agent/operator/p7_solving_broker_service.py`
- Create: `src/asterion/applications/prime_agent/operator/resources/prime-arc-agi-3-upstream-LICENSE.txt`
- Create: `tests/test_prime_p7_solving_broker.py`
- Create: `tests/test_prime_p7_solving_score.py`
- Create: `tests/test_prime_p7_solving_broker_service.py`

**Interfaces:**
- Produces: workload constants for game `ls20-9607627b`, seed 0, action cap 500, batch cap 20.
- Produces: model client functions `observe()`, `status()`, `act(actions)` over one authenticated Unix socket.
- Produces: control methods `ready`, `seal`, `replay`, `presentation`, and `close`.
- Produces: public-safe seal and private structured presentation.

- [ ] **Step 1: Write broker boundary tests around a fake multi-level engine**

Use action objects shaped as `{"name": "ACTION1", "data": {}}`; add ACTION6 coordinate cases. Assert repeated observe/status calls are read-only, batches accept 1–20 actions, each primitive increments the authoritative counter, and a batch like `[ACTION1, ACTION2, ACTION3]` stops after ACTION2 when that action changes `levels_completed` from 0 to 1. Assert ACTION3 never reaches the fake engine and later acts are rejected with stable closure.

Use `subTest` for bad auth, skipped/duplicate sequence, empty/21-action batch, unknown action, malformed data, ACTION6 coordinates outside 0..63, action 501, post-completion action, and noncanonical frames.

- [ ] **Step 2: Write exact score tests**

Pin the local metadata baseline `[22, 123, 73, 84, 96, 192, 186]` and the locked `arc_agi` wheel identity. Build the official calculator input for one completed level and six incomplete levels. Assert 22 or fewer first-level actions produce `"3.571429"`; 44 actions produce the official weighted value `"0.892857"`; changed baseline/resource identity rejects replay. Never treat `score_sha256` as this value.

- [ ] **Step 3: Run broker/score tests and observe missing modules**

```bash
uv run python -m unittest -v tests.test_prime_p7_solving_broker tests.test_prime_p7_solving_score tests.test_prime_p7_solving_broker_service
```

Expected: imports fail before implementation.

- [ ] **Step 4: Implement the dynamic broker and locked client bytes**

Adapt the upstream MIT implementation to Asterion's canonical authenticated envelopes. The broker loop must apply and journal each primitive separately, compare `levels_completed` after each step, stop immediately at the first transition, and set terminal reason `level-completed`. `observe` and `status` never consume action authority. Generate a client module containing only the fixed socket path/token and three public functions; do not put game paths, SDK imports, or credentials in it.

- [ ] **Step 5: Implement the pinned partial-game scorer and replay**

Load only the exact named metadata and locked `arc_agi` calculator. Convert the calculator float through `Decimal(str(value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN)` and reject nonfinite/out-of-range results. Replay a fresh engine with the same resource identity/seed and require equality of initial observation, every applied action observation, completion transition, action count, and score string.

- [ ] **Step 6: Implement the broker process/service split**

Follow `p7_broker_process.py` and `p7_broker_service.py`, but use new protocol/paths/classes. The process owns the SDK engine; the service owns process lifetime and private directory. `seal` and `replay` return public-safe facts. `presentation` returns only allowlisted initial/completion grids, applied actions, counters, terminal reason, and score over the private control socket. Cap request and response frames, verify socket ownership/mode, and keep private paths out of returned values.

- [ ] **Step 7: Run focused broker tests**

Run the Step 3 command. Expected: all pass.

- [ ] **Step 8: Commit broker and scoring**

```bash
git add src/asterion/applications/prime_agent/operator/p7_solving_* src/asterion/applications/prime_agent/operator/resources/prime-arc-agi-3-upstream-LICENSE.txt tests/test_prime_p7_solving_broker.py tests/test_prime_p7_solving_score.py tests/test_prime_p7_solving_broker_service.py
git commit -m "feat(prime): add dynamic ARC solving broker"
```

---

### Task 5: Add a persistent restricted IPython worker

**Owner:** Sol. This supplies the actual persistent programmatic workspace required by Prime.

**Files:**
- Create: `src/asterion/applications/prime_agent/operator/p7_solving_image/Dockerfile`
- Create: `src/asterion/applications/prime_agent/operator/p7_solving_image/launcher.py`
- Create: `src/asterion/applications/prime_agent/operator/p7_solving_docker.py`
- Create: `tests/test_prime_p7_solving_docker.py`
- Create: `tests/test_prime_p7_solving_kernel.py`

**Interfaces:**
- Consumes: Task 4 broker socket/client bytes.
- Produces: `P7SolvingDockerWorker.acquire(client)`, `execute_cell(code)`, and `cleanup()`.
- Produces: each cell result as `{"cell_count": int, "output": str, "is_error": bool}` with bounded UTF-8 output.

- [ ] **Step 1: Write persistence and admission tests that run in the solve image**

Build the solve image first, start its launcher in the container, execute `x = 41`, then execute `print(x + 1)`. Assert the second result contains `42` and `cell_count == 2`. Root `uv` does not contain IPython, so no persistence claim may depend on the host interpreter. Add container probes for syntax/runtime errors, oversized code/output, malformed frames, shutdown, and no leakage of the launcher socket/path in `repr` or public errors.

- [ ] **Step 2: Write Docker admission tests**

Model them on `test_prime_p7_development_docker.py`. Assert `--network none`, read-only root, user `65534:65534`, dropped capabilities, no-new-privileges, exact seccomp, one RW workspace, one RO broker socket, fixed CPU/memory/pids, no host/provider environment, and source-locked image/entrypoint. Verify cancellation removes an uncertain create and cleanup proves absence.

- [ ] **Step 3: Run tests and observe missing worker modules**

```bash
uv run python -m unittest -v tests.test_prime_p7_solving_kernel tests.test_prime_p7_solving_docker
```

Expected: imports fail.

- [ ] **Step 4: Implement the persistent launcher**

Run one `IPython.core.interactiveshell.InteractiveShell` in the container's long-lived entrypoint. Accept canonical length-prefixed local Unix-socket requests, call `run_cell(code)`, capture bounded stdout/stderr/display text, retain the namespace between requests, increment a contiguous cell counter, and return canonical JSON. The client mode accepts base64-encoded UTF-8 code as one direct argv value and talks only to the container-local kernel socket.

- [ ] **Step 5: Implement the solve-specific Docker transport/service**

Reuse generic Docker call/control helpers, not the fixed three-stage worker state machine. The worker permits up to 128 cells, validates exact contiguous `cell_count`, returns output to the Prime tool callback, and never reads arbitrary workspace files. Its image copies the locked requirements plus `launcher.py`; do not add dependencies.

- [ ] **Step 6: Run persistence and Docker tests**

Run the Step 3 command. Expected: all pass.

- [ ] **Step 7: Commit the persistent worker**

```bash
git add src/asterion/applications/prime_agent/operator/p7_solving_image src/asterion/applications/prime_agent/operator/p7_solving_docker.py tests/test_prime_p7_solving_docker.py tests/test_prime_p7_solving_kernel.py
git commit -m "feat(prime): add persistent P7 IPython worker"
```

---

### Task 6: Add the autonomous Prime gateway and bounded DeepSeek adapter

**Owner:** Sol. If two materially different attempts fail, transfer this task to Astra.

**Files:**
- Create: `packages/typescript/prime-gateway/src/p7-solving-session.ts`
- Create: `packages/typescript/prime-gateway/src/p7-solving-bridge.ts`
- Create: `packages/typescript/prime-gateway/src/p7-solving-main.ts`
- Create: `packages/typescript/prime-gateway/test/p7-solving-session.test.mjs`
- Create: `packages/typescript/prime-gateway/test/p7-solving-bridge.test.mjs`
- Create: `src/asterion/applications/prime_agent/operator/p7_solving_gateway.py`
- Create: `src/asterion/applications/prime_agent/operator/p7_solving_sdk_provider.py`
- Create: `tests/test_prime_p7_solving_gateway.py`
- Create: `tests/test_prime_p7_solving_sdk_provider.py`

**Interfaces:**
- Consumes: Task 5 `execute_cell()` results.
- Produces: one prompt-driven Prime session with up to 128 model and 128 IPython callbacks.
- Produces: `PrimeP7SolvingGateway` and `PrimeP7SolvingSdkProvider` with terminal usage/witness and cancellation.

- [ ] **Step 1: Write TypeScript session/bridge tests**

Assert one prompt can alternate arbitrary model/tool callbacks until the broker-verified level-solved latch stops the session at `shouldStopAfterTurn`; assistant prose alone cannot declare success. Mark IPython `executionMode: "sequential"` and prove two sibling tool calls execute in source order with original IDs and mixed text preserved. The tool description says outputs and state persist and never mentions fixed files/actions. Assert callback 129, second prompt, unknown tool, interleaved command, malformed frame, cancellation, and calls after close fail. Assert terminal witness reports actual normal-model, summary-model, and tool counts rather than fixed `6/3`.

- [ ] **Step 2: Write Python gateway/provider tests**

Use canonical Prime callback fixtures containing more than three IPython calls. Define separate normal-turn and compaction-summary callback envelopes: normal calls may expose only IPython; summary calls expose no tools and return summary text that replaces the requested transcript span. Assert the provider accepts growing exact history, sends DeepSeek `tool_choice: "auto"` only for normal calls, preserves IDs and source order, and counts both callback kinds against cumulative input/output/cost/deadline/callback limits. Issue two summary callbacks concurrently and assert one child request executes at a time, correlation IDs stay distinct, accounting order is deterministic, and `finalize()` rejects until both settle. Add idle success, double-finalize rejection, cancellation/reaping, and sentinel-secret redaction.

- [ ] **Step 3: Run focused tests and observe missing modules**

```bash
npm --prefix packages/typescript/prime-gateway test -- test/p7-solving-session.test.mjs test/p7-solving-bridge.test.mjs
uv run python -m unittest -v tests.test_prime_p7_solving_gateway tests.test_prime_p7_solving_sdk_provider
```

Expected: missing TypeScript/Python modules before implementation.

- [ ] **Step 4: Implement the one-prompt TypeScript Prime session**

Adapt the existing P7 SDK session but create new provider/model identities, solving tool description, actual counters, one prompt maximum, no fixed stage files, and limits `model callbacks including summaries=128`, `tool=128`. Register `contextWindow=131072`; pin compaction to `enabled=true`, `reserveTokens=8192`, `keepRecentTokens=32768`, and `agentCallable=false`. Mark IPython sequential. A broker-verified `LEVEL_SOLVED` result sets a latch; chain the session's existing `shouldStopAfterTurn` logic and stop at that quiescent boundary so no post-solve action executes. Keep RLM, child creation, auto-refine, retry, and branch-summary entry points unavailable. Provider network access stays in the Python model hook. Add a pinned-SDK fixture that forces a split-turn compaction and proves its two summaries are both correlated and incorporated before the next normal turn.

- [ ] **Step 5: Implement the solving bridge and Python transport**

Use a new `asterion.prime-p7-solving-gateway/v1` private protocol. Retain exact frame identity, canonical encoding, contiguous sequences, callback correlation, abort, close, and empty child environment. Pin solve-specific canonical model-request bodies to 8,388,608 bytes and gateway frames to 16,777,216 bytes; reject oversized values before fork, allocation, or socket write. Test a generated normal callback near the 122,880-token compaction threshold so it crosses the former 128-KiB provider cap without crossing either new cap. The Python gateway admits one open, one prompt, optional cancel, one close, and returns a terminal witness with actual normal/summary/tool counts and usage. The model provider gains `finalize()` so a solve ending before callback 128 seals terminal usage only when no callback is in flight.

- [ ] **Step 6: Implement the bounded DeepSeek conversation adapter**

Reuse low-level direct HTTP/fork/reap helpers from the existing SDK providers, but implement solve-specific request-history validation and response conversion. Do not import the fixed six-turn `_deepseek_payload` or its alternating-turn validator. Use the operator's exact model ID, temperature 0, disabled provider retries, 4,096 output tokens per callback, and the global cumulative token/cost/callback/deadline limits. Validate that compaction replaces the exact requested transcript prefix. Prime may split a long turn into two summary requests; serialize those requests through the single child/provider and count each request rather than allowing overlapping provider calls.

- [ ] **Step 7: Run focused Node/Python tests**

Run the Step 3 commands. Expected: all pass.

- [ ] **Step 8: Commit gateway/provider**

```bash
git add packages/typescript/prime-gateway/src/p7-solving-* packages/typescript/prime-gateway/test/p7-solving-* src/asterion/applications/prime_agent/operator/p7_solving_gateway.py src/asterion/applications/prime_agent/operator/p7_solving_sdk_provider.py tests/test_prime_p7_solving_gateway.py tests/test_prime_p7_solving_sdk_provider.py
git commit -m "feat(prime): add autonomous P7 solve session"
```

---

### Task 7: Compose the solve lifecycle, safe receipt, and local presentation

**Owner:** Sol for lifecycle/receipt; Terra may implement the renderer after its input contract lands.

**Files:**
- Create: `src/asterion/applications/prime_agent/operator/p7_solving_prompt.py`
- Create: `src/asterion/applications/prime_agent/operator/p7_solving_renderer.py`
- Create: `src/asterion/applications/prime_agent/operator/p7_solving_host.py`
- Create: `tests/test_prime_p7_solving_prompt.py`
- Create: `tests/test_prime_p7_solving_renderer.py`
- Create: `tests/test_prime_p7_solving_host.py`

**Interfaces:**
- Consumes: Tasks 4–6 broker, worker, provider, gateway and Task 1 presentation sink.
- Produces: `run_p7_solving_lifecycle(...) -> PrimeArcAgi3SolveReceipt` plus private `P7SolvingPresentation`.
- Produces: `render_p7_solving_presentation(value, sink)`.

- [ ] **Step 1: Write prompt/receipt/renderer tests**

Assert the source-locked prompt contains only game-agnostic instructions: programmatic frame analysis, object/color/component/difference tracking, short exploratory batches, world-model revision, and finishing after a completed level. Assert it contains no fixed action name/count or engine/source path. Receipt tests cover immutability, exact fields, score syntax/range, digest identity, completed level exactly one, sentinel redaction, and `repr`.

Renderer tests pass a structured 2D integer grid and action list, then assert the stream includes `Question`, `Action answer`, `Solved level`, and `Partial score`. Reject ragged/oversized grids, invalid colors/actions, strings containing private paths, and every extra field. Confirm renderer text never enters the receipt or `HostProgressReporter` fake.

- [ ] **Step 2: Write lifecycle success/failure tests**

Use scripted fakes where one prompt performs more than four dynamic actions and the broker reports a real level transition. Assert successful order: preflight → broker/worker → gateway prompt → broker level latch → Prime quiescent stop → provider finalize/witness → seal/replay → presentation → gateway/provider/worker/broker cleanup → receipt publication. Prove an attempted tool call after the solved result never executes. Cover callback/action/deadline exhaustion, noncompletion, replay mismatch, score mismatch, cancellation, original-failure preservation, cleanup failure, and no automatic retry.

- [ ] **Step 3: Run focused lifecycle tests and observe missing modules**

```bash
uv run python -m unittest -v tests.test_prime_p7_solving_prompt tests.test_prime_arc_agi_3_solver_package tests.test_prime_p7_solving_renderer tests.test_prime_p7_solving_host
```

Expected: imports fail.

- [ ] **Step 4: Implement the locked upstream-derived guidance**

Keep prompt and behavioral guide constants inside the operator integration, outside manifests/public receipts. Include the upstream commit and license digest in the workload lock. The initial prompt instructs the agent to import only `p7_client`, observe first, analyze programmatically, act in small evidence-driven batches, check status, and finish immediately after `terminal == "LEVEL_SOLVED"`.

- [ ] **Step 5: Implement lifecycle and receipt sealing**

The lifecycle starts one broker and worker, binds model/tool hooks, opens one Prime session, sends one prompt, and requires a completed-level broker transition regardless of assistant prose. Tool output returns the bounded persistent IPython result and private solved latch to the gateway. After provider `finalize()`, replay, and cleanup, create the sole `PrimeArcAgi3SolveReceipt` type owned by Task 3 and store it in a one-run in-memory accessor keyed by exact `(run_id, receipt_sha256)`. Define `receipt_sha256` over canonical JSON of the unsigned receipt fields (all fields except `receipt_sha256`) so verification is reproducible and non-circular.

- [ ] **Step 6: Implement the structured local renderer**

Render only after allowlist validation and only to Task 1's explicit sink supplied through the host factory context. Use compact aligned digits for grids and one action per line or a compact indexed sequence. Do not display the prompt, model messages, Python code, provider payloads, filesystem paths, or raw engine objects. Use phase-only progress events without `current`/`total`; action/model/cell counters exceed the shared progress maximum and belong only in presentation and the safe final receipt.

- [ ] **Step 7: Run lifecycle tests**

Run the Step 3 command. Expected: all pass.

- [ ] **Step 8: Commit lifecycle and presentation**

```bash
git add src/asterion/applications/prime_agent/operator/p7_solving_prompt.py src/asterion/applications/prime_agent/operator/p7_solving_renderer.py src/asterion/applications/prime_agent/operator/p7_solving_host.py tests/test_prime_p7_solving_prompt.py tests/test_prime_p7_solving_renderer.py tests/test_prime_p7_solving_host.py
git commit -m "feat(prime): compose real P7 solve lifecycle"
```

---

### Task 8: Add an independent solving preparation scenario and packaged resources

**Owner:** Terra for implementation and lock generation; Luna for the mechanical wheel comparison.

**Files:**
- Create: `src/asterion/applications/prime_agent/operator/p7_solving_resource_lock.py`
- Create: `src/asterion/applications/prime_agent/operator/p7_solving_preparation.py`
- Create: `src/asterion/applications/prime_agent/operator/resources/prime-p7-solving-preparation-lock.json`
- Modify: `src/asterion/applications/prime_agent/operator/development_preparation.py`
- Modify: `tools/prepare_prime_development.py`
- Modify: `pyproject.toml`
- Generate, do not commit: `packages/typescript/prime-gateway/dist/src/p7-solving-{session,bridge,main}.{js,d.ts}`
- Create: `tests/test_prime_p7_solving_preparation.py`
- Modify: `tests/test_prime_development_preparation.py`
- Modify: `tests/test_prime_application_provider.py`
- Modify: `tests/test_prime_package_runtime_closure.py`
- Modify: `tests/test_prime_ecosystem_packages.py`

**Interfaces:**
- Produces a separate preparation selector `p7-solving`; existing `p7` continues to mean the four-action smoke route.
- Produces solve-owned source, image, gateway-output, prompt/license, runtime-wheel, and LS20 resource locks.
- Packages compiled `p7-solving-{session,bridge,main}.js` and declarations inside the wheel and resolves them with `importlib.resources`, independent of repository cwd.

- [ ] **Step 1: Write focused preparation and installed-wheel tests**

Assert `tools/prepare_prime_development.py --scenario p7-solving` is accepted and `--all` includes it while `p7` behavior and lock identities are unchanged. The solving verifier owns only solving resources; do not add them to `authority_application_resources.py`, which remains P1-only. Assert source/output arrays are sorted and unique and manifests contain no prompt, credential, command, executable path, or environment values.

Build a wheel in a temporary directory, install it into a clean venv, change cwd outside the repository, resolve the application/host entry point, locate packaged gateway JS with `importlib.resources.files("asterion")`, and run a no-provider readiness probe.

- [ ] **Step 2: Run focused tests and observe missing locks/resources**

```bash
uv run python -m unittest -v tests.test_prime_p7_solving_preparation tests.test_prime_development_preparation tests.test_prime_application_provider tests.test_prime_package_runtime_closure tests.test_prime_ecosystem_packages
```

Expected: only the new scenario/resource assertions fail before implementation.

- [ ] **Step 3: Implement the separate preparation path**

Extend `_SCENARIOS`, image dispatch, identity collection, receipt generation, and CLI choices with the exact string `p7-solving`, but delegate its resource verification to the new solve-owned modules. Keep the old `p7` record and digests untouched. Generate computed digests with repository code rather than hand-editing them.

- [ ] **Step 4: Package compiled gateway outputs**

Add explicit Hatch `force-include` entries for the compiled `.js` and `.d.ts` files under a stable `asterion/applications/prime_agent/operator/resources/p7-solving/` wheel path. These `dist/` files are ignored build products: generate them before wheel construction and never stage them. Resolve installed copies through `importlib.resources`; repository-relative paths may be used only by the preparation/build command. Add every packaged output digest to the solve-owned lock.

- [ ] **Step 5: Run focused checks and promotion check**

```bash
npm --prefix packages/typescript/prime-gateway test -- test/p7-solving-session.test.mjs test/p7-solving-bridge.test.mjs
uv run python -m unittest -v tests.test_prime_p7_solving_preparation tests.test_prime_development_preparation tests.test_prime_application_provider tests.test_prime_package_runtime_closure tests.test_prime_ecosystem_packages tests.test_prime_p7_solving_installed_route
make lint
make docs-check
make promotion-check
git diff --check
```

Expected: all pass. The focused Node command runs the new tests; `make test-typescript` is reserved for final cross-package validation because its Prime target only builds the gateway.

- [ ] **Step 6: Have Luna compare package contents and commit**

Compare source files, built outputs, wheel contents, entry points, manifest refs, and lock arrays. Confirm no prompts/credentials occur in manifests and no P7 smoke resource changed.

```bash
git add src/asterion/applications/prime_agent/operator/p7_solving_resource_lock.py src/asterion/applications/prime_agent/operator/p7_solving_preparation.py src/asterion/applications/prime_agent/operator/resources/prime-p7-solving-preparation-lock.json src/asterion/applications/prime_agent/operator/development_preparation.py tools/prepare_prime_development.py pyproject.toml tests/test_prime_p7_solving_preparation.py tests/test_prime_development_preparation.py tests/test_prime_application_provider.py tests/test_prime_package_runtime_closure.py tests/test_prime_ecosystem_packages.py
git commit -m "build(prime): lock P7 solving resources"
```

---

### Task 9: Wire the operator host service and Make command

**Owner:** Terra. This is ordinary host factory/CLI integration after the lifecycle and installed preparation path exist.

**Files:**
- Create: `src/asterion/applications/prime_agent/operator/p7_solving_cli_host.py`
- Modify: `pyproject.toml`
- Modify: `Makefile`
- Modify: `tools/preflight_prime_apps.py`
- Create: `tests/test_prime_p7_solving_cli_host.py`
- Modify: `tests/test_prime_make_presets.py`
- Modify: `tests/test_prime_apps_preflight.py`

**Interfaces:**
- Consumes: Task 7 lifecycle/receipt accessor, Task 8 preparation, and Task 1 presentation sink.
- Produces: host factory entry point `prime.arc-agi-3-solving`.
- Produces: `make prime-p7-solve` and a solving preflight row that performs no model/game action.

- [ ] **Step 1: Write failing host/Make tests**

Assert the host factory accepts only provider `prime-agent`, application `prime.arc-agi-3-solving@1.0.0`, capability `prime.arc-agi-3-solving`, and no options. Assert it resolves `.env` only in operator code, locks `deepseek-v4-flash`, prepares the exact LS20/runtime/image/source resources, and does not start broker/model/game during preflight. Refactor the preflight row contract to carry separate `display_name` and `preparation_scenario` fields; assert the new row invokes preparation with exactly `p7-solving` while stdout says exactly `prime-p7-solve PASS`.

Assert `make -n prime-p7-solve` contains the exact application/version/preset and `--progress`, while `prime-p7-run` still says `transport smoke` and still selects the development route.

- [ ] **Step 2: Run focused host/Make tests and observe missing entry point**

```bash
uv run python -m unittest -v tests.test_prime_p7_solving_cli_host tests.test_prime_make_presets tests.test_prime_apps_preflight
```

Expected: new host/target assertions fail; existing targets pass.

- [ ] **Step 3: Implement the exact host factory**

Create one service object implementing Task 2 `execute()` and Task 3 `get_receipt()`. `execute()` accepts the single preset, rejects reuse/concurrency, runs Task 7 once, retains only the immutable safe receipt for retrieval, and maps cancellation to the generic cancellation contract. `get_receipt()` performs no I/O or execution and consumes the exact run/digest match once. The factory passes `context.presentation` into the lifecycle and emits only phase-level progress events.

Register in `pyproject.toml`:

```toml
"prime.arc-agi-3-solving" = "asterion.applications.prime_agent.operator.p7_solving_cli_host:create_host_service_factory"
```

- [ ] **Step 4: Add the Make target and preflight**

Add `prime-p7-solve` to `.PHONY` and help. The target prints a fixed purpose/limits line, prepares the exact `p7-solving` scenario in the selected Orb, and runs:

```bash
uv run asterion run \
  --provider prime-agent \
  --application prime.arc-agi-3-solving \
  --application-version 1.0.0 \
  --run-id "$run_id" \
  --input solve-first-public-level \
  --progress
```

Keep stdout reserved for the single application JSON. Route purpose/progress/presentation to their declared sinks. Add the explicit preflight pair `(display_name="prime-p7-solve", preparation_scenario="p7-solving")`; it verifies readiness only and never derives one identity from the other.

- [ ] **Step 5: Run focused host/Make tests**

Run the Step 2 command. Expected: all pass.

- [ ] **Step 6: Commit command integration**

```bash
git add src/asterion/applications/prime_agent/operator/p7_solving_cli_host.py pyproject.toml Makefile tools/preflight_prime_apps.py tests/test_prime_p7_solving_cli_host.py tests/test_prime_make_presets.py tests/test_prime_apps_preflight.py
git commit -m "feat(prime): add P7 solving command"
```

---

### Task 10: Run one real DeepSeek solve, iterate only on observed failures, and correct status

**Owner:** Sol. Escalate the failing component to Astra after two materially different unsuccessful fixes. Luna performs residue/output checks. Sol independently reviews material changes before the final claim.

**Files:**
- Modify only if an observed real-run defect requires it: the owning P7a module and its focused test.
- Modify after PASS: `docs/status/CURRENT-STATE.md`
- Modify after PASS: `docs/status/PRIME-TYPICAL-APPLICATIONS.md`
- Modify after PASS: `docs/status/FRAMEWORK-INTEGRATION-WORKLIST.md`
- Modify after PASS: `docs/status/RESUME-NEXT-SESSION.md`
- Modify after PASS: `docs/status/INDEX.md` only if a non-core status file is added or its classification changes.

**Interfaces:**
- Consumes: installed `prime.arc-agi-3-solving` route and operator `.env` model configuration.
- Produces: one named real P7a trace/receipt proving an actual first-level transition and zero residue.

- [ ] **Step 1: Run provider-free preflight**

```bash
make prime-apps-preflight
```

Expected: all existing rows plus `prime-p7-solve` report `PASS`; no model, tool, broker action, or game action executes.

- [ ] **Step 2: Run the canonical real solve once**

```bash
PRIME_RUN_ID=prime-p7-solve-ls20-level1-a make prime-p7-solve
```

Expected: visible question/progress/action-answer/solved-frame/partial-score presentation, one stdout JSON application result, exit 0, `completed_level_count == 1`, and `promotion == "unpromoted"`.

- [ ] **Step 3: If it fails, classify before changing code**

Use the safe terminal classification and private replay to choose exactly one owner: model conversation/provider, Prime gateway, IPython worker, broker/game, score/replay, or cleanup. Add one focused regression test, apply one bounded fix, run only that test group, then retry with run ID suffix `-b`. After a second materially different failure in the same component, transfer that component to Astra. Do not loosen identity, redaction, cleanup, action, callback, or deadline gates merely to obtain PASS.

- [ ] **Step 4: Verify stdout, presentation, and residue mechanically**

Have Luna assert stdout is one JSON line; public output contains no `file://`, absolute private path, prompt/model prose, credential sentinel, or provider body; the local presentation includes the required grid/action/score labels; and no run-specific container, process, socket, workspace, or private cache remains.

- [ ] **Step 5: Obtain independent Sol review**

Review dependency direction, exact identities, dynamic-action evidence, score/replay correctness, presentation separation, cancellation/cleanup, smoke-route preservation, and focused test adequacy. Resolve blocking findings before status changes.

- [ ] **Step 6: Correct durable status only from the passing evidence**

Record the exact passing command, exit code, trace/receipt digest, model identity, level/action/score summary, unpromoted state, and zero-residue result. Mark Prime P1–P7 `7/7 functional` at the P7a boundary while keeping P7b/P7c open. If the real solve has not passed, retain `6/7` and describe the exact failed boundary.

- [ ] **Step 7: Run final focused verification and commit status**

```bash
uv run python -m unittest -v tests.test_host_presentation tests.test_prime_preset_runtime tests.test_prime_arc_agi_3_solver_package tests.test_prime_p7_solving_installed_route tests.test_prime_p7_solving_broker tests.test_prime_p7_solving_score tests.test_prime_p7_solving_broker_service tests.test_prime_p7_solving_kernel tests.test_prime_p7_solving_docker tests.test_prime_p7_solving_gateway tests.test_prime_p7_solving_sdk_provider tests.test_prime_p7_solving_renderer tests.test_prime_p7_solving_host tests.test_prime_p7_solving_preparation tests.test_prime_p7_solving_cli_host tests.test_prime_p7_installed_route tests.test_prime_make_presets tests.test_prime_apps_preflight
npm --prefix packages/typescript/prime-gateway test -- test/p7-solving-session.test.mjs test/p7-solving-bridge.test.mjs
make test-typescript
make docs-check
git diff --check
```

Expected: all focused assertions and documentation checks pass.

```bash
git add docs/status/CURRENT-STATE.md docs/status/PRIME-TYPICAL-APPLICATIONS.md docs/status/FRAMEWORK-INTEGRATION-WORKLIST.md docs/status/RESUME-NEXT-SESSION.md docs/status/INDEX.md
git commit -m "docs(status): record real Prime P7 solve"
```

Do not stage `docs/status/INDEX.md` if it did not need a change.
