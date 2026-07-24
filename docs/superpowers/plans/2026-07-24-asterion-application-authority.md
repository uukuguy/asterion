# Asterion Application Authority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make installed applications resolve one executable graph whose runtime, corpus, Judge, and host-service authority is selected once by the host and never rediscovered by packages or runners.

**Architecture:** The generic CLI handles only provider/application/runtime contracts and host injection. DCI-specific configuration moves behind the DCI product/provider boundary; Pi and Claude Code both execute through the selected `AgentRuntimeClient`, while corpus and Judge authority are narrow read-only host services declared by assemblies.

**Tech Stack:** Python 3.10+, `unittest`, installed entry points, immutable dataclasses, async protocols, static JSON assemblies.

## Global Constraints

- Framework modules remain domain-neutral and must not import `asterion.dci`.
- Providers expose static resources; package manifests carry compatibility, not execution authority.
- Runtime choice, provider/model configuration, commands, cwd, credentials, and environment remain host-owned.
- Every runtime listed by an installed application has exactly one matching assembly.
- Every executable package in every bound assembly has exactly one implementation binding.
- Runners receive resolved plans, runtimes, implementations, cancellation, and read-only host services; they do not discover or configure them.
- Missing services and identity mismatches fail before provider execution.
- Public errors and reports remain content-free and redact credentials, prompts, answers, corpus text, raw provider payloads, and private paths.

---

## File Structure

- `src/asterion/cli.py` — generic, DCI-neutral installed-application host.
- `src/asterion/runtime/factory.py` and `runtime/defaults.py` — exact runtime construction from explicit options.
- `src/asterion/applications/provider.py` — provider structure and runtime/assembly bijection.
- `src/asterion/applications/dci_agent_lite/provider.py` — static DCI package bindings only.
- `src/asterion/dci/services.py` — DCI-owned narrow corpus and Judge service protocols.
- `src/asterion/capabilities/dci_research/*.py` — consume runtime and injected services only.
- `src/asterion/applications/dci_agent_lite/assemblies/*.json` — declare required host capabilities.
- `src/asterion/dci/verification.py` — packaged/bound/composed/executable acceptance evidence.
- `tests/test_asterion_cli.py` — generic CLI hermeticity and runtime selection.
- `tests/test_installed_application_provider.py` — provider closure and assembly bijection.
- `tests/test_dci_complete_application.py` — DCI runtime/service/data-flow behavior.
- `tests/test_asterion_dci_verification.py` — acceptance evidence and redaction.

### Task 1: Remove DCI configuration from the generic CLI

**Files:**
- Modify: `src/asterion/cli.py`
- Modify: `src/asterion/runtime/factory.py`
- Modify: `src/asterion/runtime/defaults.py`
- Modify: `tests/test_asterion_cli.py`

**Interfaces:**
- Consumes: CLI runtime ID and explicit generic `--runtime-option key=value` values.
- Produces: a `RuntimeFactoryContext` that does not import or materialize DCI configuration layers.

- [ ] **Step 1: Write the hermeticity tests**

In a temporary cwd, create a sentinel `.env` containing deliberately invalid
DCI values. Run `main()` with injected fake provider entry points and runtime
factories. Assert:

```python
self.assertEqual(
    main(
        ["run", "--provider", "fixture", "--application", "fixture.app@1.0.0",
         "--runtime", "fixture.runtime", "--input", "hello"],
        entry_points=(entry_point,),
        runtime_factories=registry,
        stdout=stdout,
        stderr=stderr,
    ),
    0,
)
self.assertNotIn("SENTINEL_SECRET", stdout.getvalue())
self.assertEqual(stderr.getvalue(), "")
```

Add an import-boundary test:

```python
source = Path("src/asterion/cli.py").read_text()
self.assertNotIn("asterion.dci", source)
self.assertNotIn("ConfigLayers", source)
self.assertNotIn("resolve_dci_runtime", source)
```

Run:

```bash
uv run python -m unittest -v tests.test_asterion_cli
```

Expected: failures caused by the current DCI imports and repository `.env`
materialization.

- [ ] **Step 2: Define generic runtime options**

Add repeatable CLI syntax:

```python
run.add_argument(
    "--runtime-option",
    action="append",
    default=[],
    metavar="KEY=VALUE",
)
```

Parse with:

```python
def _runtime_options(values: list[str]) -> Mapping[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        key, separator, item = value.partition("=")
        if not separator or not key or key in parsed:
            raise RuntimeFactoryError("runtime option is invalid")
        parsed[key] = item
    return MappingProxyType(parsed)
```

The generic CLI passes these opaque values to the selected runtime factory. It
does not assign DCI defaults, load `.env`, or mutate `os.environ`.

- [ ] **Step 3: Select the runtime ID exactly once**

Delete the preliminary `resolve_dci_runtime_options()` path and the later
`ConfigLayers` overwrite. Require `--runtime` unless the selected application
has exactly one runtime ID:

```python
runtime_id = args.runtime
if runtime_id is None:
    if len(application.runtime_ids) != 1:
        raise ApplicationProviderError("application runtime selection is required")
    runtime_id = application.runtime_ids[0]
```

Pass the exact canonical ID to `registry.select()`. Do not normalize aliases in
the generic CLI.

- [ ] **Step 4: Run and commit**

```bash
uv run python -m unittest -v tests.test_asterion_cli
git add src/asterion/cli.py src/asterion/runtime/factory.py \
  src/asterion/runtime/defaults.py tests/test_asterion_cli.py
git commit -m "fix: keep the generic application CLI domain neutral"
```

Expected: all CLI tests pass from repository and temporary cwd values.

### Task 2: Prove runtime-to-assembly bijection and executable closure

**Files:**
- Modify: `src/asterion/applications/provider.py`
- Modify: `tests/test_installed_application_provider.py`

**Interfaces:**
- Consumes: one `InstalledApplication` with exact runtime IDs, assembly paths, catalog roots, and implementation bindings.
- Produces: a validated application where every runtime has exactly one resolvable and completely bound assembly.

- [ ] **Step 1: Write malformed-provider matrices**

Construct providers with:

```python
cases = (
    "runtime-without-assembly",
    "two-assemblies-for-one-runtime",
    "assembly-runtime-not-listed",
    "missing-package-implementation",
    "unknown-package-implementation",
    "uncomposable-bound-assembly",
)
```

Assert `validate_installed_provider()` raises
`ApplicationProviderError` before any runtime factory or provider request.

- [ ] **Step 2: Run and verify failures**

```bash
uv run python -m unittest -v tests.test_installed_application_provider
```

Expected: at least runtime-without-assembly, duplicate-runtime-assembly, and
uncomposable cases expose missing validation.

- [ ] **Step 3: Add an immutable resolved closure**

Introduce:

```python
@dataclass(frozen=True)
class InstalledAssembly:
    runtime_id: str
    path: Path
    plan: AssemblyPlan

@dataclass(frozen=True)
class InstalledApplication:
    application_id: str
    version: str
    assembly_paths: tuple[Path, ...]
    catalog_roots: tuple[Path, ...]
    implementations: tuple[tuple[PackageRef, PackageImplementation], ...]
    runtime_ids: tuple[str, ...]
    assemblies: tuple[InstalledAssembly, ...]
```

During provider validation:

1. Discover each explicit catalog root once.
2. Read and validate each assembly.
3. Select the exact runtime manifest from an injected
   `RuntimeFactoryRegistry` or a provider-validation context.
4. Resolve the assembly through `resolve_assembly()`.
5. Run `validate_implementation_bindings()`.
6. Compare the sorted assembly runtime IDs exactly with `runtime_ids`.

If changing `validate_installed_provider()` to require a runtime registry would
break metadata-only discovery, split validation into:

```python
validate_installed_provider_metadata(
    value: InstalledApplicationProvider,
    *,
    selected_id: str,
) -> InstalledApplicationProvider

resolve_installed_provider(
    provider: InstalledApplicationProvider,
    *,
    runtime_factories: RuntimeFactoryRegistry,
) -> InstalledApplicationProvider
```

`list` uses metadata validation; `run` and acceptance use resolved validation.

- [ ] **Step 4: Run and commit**

```bash
uv run python -m unittest -v tests.test_installed_application_provider
uv run python -m unittest -v tests.test_asterion_cli
git add src/asterion/applications/provider.py \
  tests/test_installed_application_provider.py
git commit -m "feat: validate installed application executable closure"
```

Expected: both suites pass.

### Task 3: Report inventory and reachability separately

**Files:**
- Modify: `src/asterion/dci/verification.py`
- Modify: `src/asterion/applications/product.py`
- Modify: `tests/test_asterion_dci_verification.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: resolved provider/application closure from Task 2.
- Produces: acceptance checks with separate packaged, bound, composed, and executable counts.

- [ ] **Step 1: Write expected acceptance checks**

Assert the report contains:

```python
expected = {
    "packaged-assemblies": 6,
    "bound-assemblies": 5,
    "composed-assemblies": 5,
    "executable-assemblies": 5,
    "provider-requests": 0,
}
```

Assert `dci-local-research.json` appears under an `unbound_resources` field and
is not counted as executable. Assert no private absolute path is returned;
resource names are package-relative.

- [ ] **Step 2: Replace raw count checks**

Build relative identities for every packaged assembly, exact path membership
for every bound assembly, resolved plans for composed assemblies, and complete
binding evidence for executable assemblies. Do not infer one class from the
count of another.

Rename the current `application-assemblies` check to
`packaged-assemblies`. Add the other three checks and document that an unbound
packaged resource is inventory, not a product entry point.

- [ ] **Step 3: Run and commit**

```bash
uv run python -m unittest -v tests.test_asterion_dci_verification
uv run asterion verify --provider dci-agent-lite --level acceptance
git add src/asterion/dci/verification.py \
  src/asterion/applications/product.py \
  tests/test_asterion_dci_verification.py README.md
git commit -m "fix: distinguish installed inventory from executable closure"
```

Expected: acceptance passes with zero provider operations.

### Task 4: Route Pi and Claude through the selected runtime client

**Files:**
- Modify: `src/asterion/applications/dci_agent_lite/provider.py`
- Modify: `src/asterion/capabilities/dci_research/implementation.py`
- Modify: `src/asterion/capabilities/dci_research/complete.py`
- Modify: `src/asterion/runtimes/pi.py`
- Modify: `tests/test_package_execution.py`
- Modify: `tests/test_dci_complete_application.py`

**Interfaces:**
- Consumes: `PackageInvocation.runtime`.
- Produces: one runtime path for Pi and Claude; provider construction is metadata-only and does not create `EnvironmentDciRunExecutor`.

- [ ] **Step 1: Write bypass-prevention tests**

Inject a recording `AgentRuntimeClient` for `pi.reference`. Assert its `run()`
is called once for both research applications. Add:

```python
with patch(
    "asterion.dci.application_executor.EnvironmentDciRunExecutor.run",
    side_effect=AssertionError("native bypass"),
):
    result = asyncio.run(
        run_composed_application(
            plan,
            implementations=application.implementations,
            runtime=runtime,
            run_id="pi-through-runtime",
            input_text="question",
            host_services=host_services,
        )
    )
self.assertEqual(runtime.calls, 1)
```

Assert `create_provider()` performs no cwd, environment, Pi, or credential
access.

- [ ] **Step 2: Remove native executor bindings**

Make `DciLocalResearchImplementation` and
`DciCompleteResearchImplementation` use only:

```python
events = [
    event.to_mapping()
    async for event in invocation.runtime.run(request, signal=invocation.signal)
]
validate_event_stream(events)
```

Remove `native_executor` from constructors and `complete_dci_bindings()`.
Remove environment executor creation from `create_provider()`.

- [ ] **Step 3: Give Pi runtime complete evidence ownership**

Extend `PiRuntimeClient` to expose:

```python
def completed_run_dir(self, run_id: str) -> Path | None:
    return self._completed_runs.get(run_id)
```

The runtime factory resolves command, cwd, environment, tools, provider, model,
context profile, max turns, and evidence root once from explicit
`RuntimeFactoryContext.options`. The client records a private completed run
directory only after a valid terminal stream.

- [ ] **Step 4: Run and commit**

```bash
uv run python -m unittest -v \
  tests.test_package_execution \
  tests.test_dci_complete_application \
  tests.test_asterion_pi_runtime
git add src/asterion/applications/dci_agent_lite/provider.py \
  src/asterion/capabilities/dci_research/implementation.py \
  src/asterion/capabilities/dci_research/complete.py \
  src/asterion/runtimes/pi.py \
  tests/test_package_execution.py tests/test_dci_complete_application.py \
  tests/test_asterion_pi_runtime.py
git commit -m "refactor: execute DCI only through the selected runtime"
```

Expected: all tests pass.

### Task 5: Inject explicit local-corpus authority

**Files:**
- Create: `src/asterion/dci/services.py`
- Modify: `src/asterion/cli.py`
- Modify: `src/asterion/capabilities/dci_research/implementation.py`
- Modify: `src/asterion/capabilities/dci_research/complete.py`
- Modify: `src/asterion/applications/dci_agent_lite/assemblies/*.json`
- Modify: `tests/test_dci_complete_application.py`
- Modify: `tests/test_asterion_cli.py`

**Interfaces:**
- Consumes: an operator-selected local corpus root.
- Produces: `LocalCorpusService` under host capability `corpus.local-root`.

- [ ] **Step 1: Define and test the service**

Create:

```python
@runtime_checkable
class LocalCorpusService(Protocol):
    @property
    def root(self) -> Path:
        raise NotImplementedError

    @property
    def identity_sha256(self) -> str:
        raise NotImplementedError
```

Provide an immutable implementation that resolves one no-symlink directory,
captures device/inode plus a body-free identity digest, and never returns
corpus contents through public reports.

Test regular-directory success, missing path, symlink root, replacement after
preflight, and sentinel path/content redaction.

- [ ] **Step 2: Declare the host capability**

Add `"corpus.local-root"` to `host_capabilities` in every provider-bound DCI
assembly. Keep arrays sorted. The CLI must require an explicit generic host
service factory for that capability; DCI product commands may build it from
their already-resolved corpus option.

- [ ] **Step 3: Consume the injected service**

In each DCI research implementation:

```python
service = invocation.host_services.get("corpus.local-root")
if not isinstance(service, LocalCorpusService):
    raise PackageExecutionError("local corpus service is unavailable")
```

Pass `service.root` through the already-selected runtime configuration or
request-owned scope. Do not call `Path.cwd()` in a package implementation.

- [ ] **Step 4: Run and commit**

```bash
uv run python -m unittest -v \
  tests.test_dci_complete_application \
  tests.test_asterion_cli
git add src/asterion/dci/services.py src/asterion/cli.py \
  src/asterion/capabilities/dci_research \
  src/asterion/applications/dci_agent_lite/assemblies \
  tests/test_dci_complete_application.py tests/test_asterion_cli.py
git commit -m "feat: inject local corpus authority into DCI applications"
```

Expected: all tests pass and missing service fails before runtime invocation.

### Task 6: Inject Judge authority and remove private attempt state

**Files:**
- Modify: `src/asterion/dci/services.py`
- Modify: `src/asterion/capabilities/dci_research/complete.py`
- Modify: `src/asterion/applications/dci_agent_lite/assemblies/dci-complete-application-*.json`
- Modify: `src/asterion/cli.py`
- Modify: `tests/test_dci_complete_application.py`

**Interfaces:**
- Consumes: one read-only `AnswerJudgeService` under capability `evaluation.answer-judge`.
- Produces: artifact-complete stage data flow without `DciCompleteAttemptStore`.

- [ ] **Step 1: Define the Judge service**

Add:

```python
@runtime_checkable
class AnswerJudgeService(Protocol):
    @property
    def public_identity(self) -> Mapping[str, object]:
        raise NotImplementedError

    async def judge(
        self,
        *,
        question: str,
        gold_answer: str,
        predicted_answer: str,
        signal: CancellationSignal | None,
    ) -> Mapping[str, object]:
        raise NotImplementedError
```

The concrete DCI product adapter owns `JudgeConfig`, credentials, endpoint,
retry policy, and cost accounting. The package sees only the protocol.

- [ ] **Step 2: Make artifacts carry the complete stage inputs**

The research result's private artifact value must include question,
gold-answer, predicted-answer, and owned output evidence for the next stage.
Because these values are sensitive, they remain inside the in-process
`PackageExecutionResult` and are never rendered by generic CLI output. Add a
public projection that exposes only schema, hashes, status, and artifact IDs.

Delete `DciCompleteAttemptStore`. Evaluation consumes exactly one research
artifact, Judge identity, and cancellation signal. Export no longer needs
side-channel cleanup.

- [ ] **Step 3: Declare and inject the service**

Add `"evaluation.answer-judge"` to complete-application host capabilities only.
The generic host must reject a complete run without this service before the
runtime starts. Research-only application assemblies do not declare it.

- [ ] **Step 4: Test redaction and cancellation**

Use `SENTINEL_QUESTION`, `SENTINEL_GOLD`, `SENTINEL_PREDICTION`,
`SENTINEL_KEY`, and a private path. Assert none appears in:

- generic CLI stdout/stderr;
- `ApplicationRunError`;
- acceptance output;
- public artifact projections.

Assert cancellation reaches the Judge service and no benchmark/analysis/export
stage executes afterward.

- [ ] **Step 5: Run and commit**

```bash
uv run python -m unittest -v tests.test_dci_complete_application
git add src/asterion/dci/services.py \
  src/asterion/capabilities/dci_research/complete.py \
  src/asterion/applications/dci_agent_lite/assemblies \
  src/asterion/cli.py tests/test_dci_complete_application.py
git commit -m "feat: inject Judge authority into the DCI package graph"
```

Expected: all tests pass.

### Task 7: Make implementation and reuse identity transitive

**Files:**
- Modify: `src/asterion/capabilities/dci_research/complete.py`
- Modify: `src/asterion/dci/provenance.py`
- Modify: `src/asterion/dci/benchmark.py`
- Modify: `tests/test_dci_complete_application.py`
- Modify: `tests/test_asterion_dci_benchmark.py`

**Interfaces:**
- Consumes: exact source/resource closure for an executable DCI graph.
- Produces: deterministic implementation identity included in all reuse keys.

- [ ] **Step 1: Write identity sensitivity tests**

Build the identity from an injected resource reader so tests can mutate one
byte in each dependency independently. Cover `complete.py`, research
implementation, bridge, analysis, evaluation, Judge adapter, package
manifests, and both assemblies. Assert every mutation changes the digest and
input iteration order does not.

Assert benchmark reuse rejects evidence whose implementation digest differs
even when provider/model/prompt/dataset identities match.

- [ ] **Step 2: Centralize the closure**

In `provenance.py`, define:

```python
DCI_COMPLETE_IMPLEMENTATION_RESOURCES: tuple[str, ...] = (
    "applications/dci_agent_lite/assemblies/dci-complete-application-claude.json",
    "applications/dci_agent_lite/assemblies/dci-complete-application-pi.json",
    "capabilities/dci_research/complete.py",
    "capabilities/dci_research/implementation.py",
    "dci/analysis.py",
    "dci/bridge.py",
    "dci/evaluation.py",
    "dci/judge.py",
    "dci/run.py",
)
```

Hash canonical relative names and exact bytes. Keep the list sorted and reject
duplicates or missing resources.

- [ ] **Step 3: Bind reuse**

Add `implementation_sha256` to effective benchmark configuration, batch item
evidence, reuse validation, analysis provenance, and export manifests. A
missing value in prior evidence makes it incompatible; it never silently
falls back to the old cache.

- [ ] **Step 4: Run and commit**

```bash
uv run python -m unittest -v \
  tests.test_dci_complete_application \
  tests.test_asterion_dci_benchmark
git add src/asterion/capabilities/dci_research/complete.py \
  src/asterion/dci/provenance.py src/asterion/dci/benchmark.py \
  tests/test_dci_complete_application.py tests/test_asterion_dci_benchmark.py
git commit -m "fix: bind DCI evidence to transitive implementation identity"
```

Expected: both suites pass.

### Task 8: Verify the application authority boundary

**Files:**
- Modify: `docs/architecture/application-runner.md`
- Modify: `docs/architecture/capability-execution.md`
- Modify: `docs/architecture/static-application-assembly.md`
- Modify: `docs/architecture/dci-capability-audit.md`

**Interfaces:**
- Consumes: Tasks 1–7.
- Produces: accurate architecture documentation and complete provider-free verification.

- [ ] **Step 1: Update documentation**

Document exact runtime selection, host service injection, corpus/Judge
authority, public/private artifact projection, provider reachability classes,
and transitive evidence identity. Remove the claim that the old generic CLI is
already DCI-neutral until the new test proves it.

- [ ] **Step 2: Run gates**

```bash
uv run asterion list
uv run asterion describe --provider dci-agent-lite
uv run asterion verify --provider dci-agent-lite --level acceptance
make test
make lint
make docs-check
make check
make promotion-check
```

Expected: every command passes, provider operations remain zero for the first
three, and no full dataset runs.

- [ ] **Step 3: Commit**

```bash
git add docs/architecture/application-runner.md \
  docs/architecture/capability-execution.md \
  docs/architecture/static-application-assembly.md \
  docs/architecture/dci-capability-audit.md
git commit -m "docs: define installed application authority boundaries"
```
