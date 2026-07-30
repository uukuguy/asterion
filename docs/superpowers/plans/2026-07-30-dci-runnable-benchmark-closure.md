# Runnable DCI Benchmark Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the installed `asterion-dci` command complete the exact instance → source lock → plan → explicit authorization → execution → private evidence → compatible resume loop for a provider-free local instance and the real bounded `dci.qa.bamboogle.github-sample50@1.0.0` Agent/Judge instance.

**Architecture:** A product-owned immutable instance catalog expands DCI instance selectors into exact generic application and suite selectors. A product-owned `DciBenchmarkHost` reuses Asterion's generic metadata resolution, plan, runner, and evidence contracts; it alone loads private operator inputs, issues opaque execution claims, rehydrates DCI bindings, and selects a local or real executor. The real executor translates the existing private DCI invocation payload into the existing `BenchmarkRequest`/`run_benchmark` implementation, so no composer, task loop, retry layer, or benchmark engine is duplicated.

**Tech Stack:** Python 3.14, Asterion benchmark and capability-package protocols, DCI Agent/Judge evaluation implementation, canonical JSON, Hatchling entry points, `unittest`, `uv`, Make.

## Global Constraints

- Preserve `CLI/host → selected provider → assembly → catalog/composer → exact implementations → runner → runtime/host services`.
- `src/asterion/benchmarks/`, `runtime/`, `packages/`, `assembly/`, `runner/`, and `services/` remain DCI-neutral and must not import `asterion.capabilities.dci` or `asterion.applications.dci_agent_lite`.
- Python remains the only benchmark orchestrator. Do not add TypeScript or Rust composers/runners.
- Keep prompts, credentials, commands, executable paths, environment values, provider configuration, private dataset/corpus paths, and mutable verification state out of manifests and public projections.
- `instances`, `lock`, and `plan` are metadata-only. They must not load a DCI implementation provider, read corpus contents, call an Agent/Judge, or access the network.
- `run` and `resume` require exact instance selection, an exact source lock, a private evidence root, and `--execute`. Configuration, credentials, old evidence, and source locks never grant authority.
- Omitting both range switches means one case. `--case-limit N` and `--all-cases` are mutually exclusive. `--all-cases` must resolve to an exact finite local count before authorization; it is never represented as a wildcard.
- The local instance performs zero model, Judge, network, or external-dataset work. The real instance deliberately may perform all four after bounded explicit authorization.
- The first real executable instance is exactly `dci.qa.bamboogle.github-sample50@1.0.0`; its all-case count is exactly 50. Do not execute all 50 cases under this plan.
- Execution is sequential and has no automatic retry. Failures and cancellation produce terminal evidence.
- Public output and exceptions are body-free. Tests must include sentinel prompts, answers, credentials, provider payloads, private paths, and host-service values and assert their absence.
- Keep `docs/status/JOURNAL.md` append-only and out of feature commits. Update `docs/status/INDEX.md` in the same commit that creates `docs/status/DCI-BENCHMARK-INSTANCES.md`.
- Every task follows RED → focused GREEN → focused verification → commit. Do not advance after an unexplained failing focused test.

---

### Task 1: Define the immutable DCI benchmark instance catalog and product CLI surface

**Files:**
- Create: `src/asterion/applications/dci_agent_lite/benchmark_instances.py`
- Modify: `src/asterion/applications/dci_agent_lite/cli.py`
- Create: `tests/test_dci_benchmark_instances.py`
- Modify: `tests/test_dci_application_adapter.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class DciBenchmarkInstance:
    instance_id: str
    version: str
    application_ref: ApplicationRef
    suite_ref: BenchmarkSuiteRef
    task_ids: tuple[str, ...]
    executor_profile: str
    default_case_limit: int
    all_case_count: int | None
    cost_class: str
    implementation_state: str

    @property
    def selector(self) -> str: ...

def benchmark_instances() -> tuple[DciBenchmarkInstance, ...]: ...
def select_benchmark_instance(selector: str) -> DciBenchmarkInstance: ...
def public_instance_dict(instance: DciBenchmarkInstance) -> dict[str, object]: ...
def resolve_case_limit(
    instance: DciBenchmarkInstance,
    *,
    case_limit: int | None,
    all_cases: bool,
) -> int: ...
```

The catalog order is canonical by selector. It contains:

```text
dci.local-fixture@1.0.0
dci.bcplus.level3@1.0.0
dci.bcplus.main@1.0.0
dci.beir.arguana@1.0.0
dci.beir.scifact@1.0.0
dci.bright.biology@1.0.0
dci.bright.earth-science@1.0.0
dci.bright.economics@1.0.0
dci.bright.robotics@1.0.0
dci.qa.2wikimultihopqa@1.0.0
dci.qa.bamboogle.github-sample50@1.0.0
dci.qa.bamboogle.paper-full125@1.0.0
dci.qa.hotpotqa@1.0.0
dci.qa.musique@1.0.0
dci.qa.nq@1.0.0
dci.qa.triviaqa@1.0.0
```

Only the local fixture and GitHub Bamboogle entries start as `implemented`.
The local fixture maps to `dci.local-benchmark-application@1.0.0` and
`dci.all@1.0.0`; Bamboogle maps to `dci.complete-application@1.0.0` and
`dci.qa.bamboogle.github-sample50@1.0.0`.

- [ ] **Step 1: Write catalog and CLI failures first**

Add tests asserting:

```python
self.assertEqual(
    select_benchmark_instance("dci.local-fixture@1.0.0").executor_profile,
    "local-fixture",
)
self.assertEqual(
    resolve_case_limit(
        select_benchmark_instance(
            "dci.qa.bamboogle.github-sample50@1.0.0"
        ),
        case_limit=None,
        all_cases=True,
    ),
    50,
)
```

Also assert exact canonical ordering, frozen values, duplicate rejection,
planned-instance execution rejection, default limit `1`, invalid/zero/negative
limits, mutually exclusive range switches, body-free `repr`, and no private
sentinel in `public_instance_dict`.

For the adapter, assert:

```text
asterion-dci benchmark instances
asterion-dci benchmark instances --json
asterion-dci benchmark plan --instance dci.local-fixture@1.0.0
```

The delegated plan arguments must contain the catalog's exact
`--application`, `--suite`, and resolved `--case-limit 1`; direct product
`--application`/`--suite` overrides must fail.

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v \
  tests.test_dci_benchmark_instances \
  tests.test_dci_application_adapter
```

Expected: failure because the catalog and new subcommands do not exist.

- [ ] **Step 3: Implement the closed catalog and parser**

Use tuples and frozen dataclasses only. Parse product arguments with a
redacting `argparse.ArgumentParser`; render JSON with
`sort_keys=True, separators=(",", ":")`. For plan/run/resume, remove product
only switches and delegate exact selectors to `asterion.benchmarks.cli.main`.
Do not load operator configuration in `instances`, `lock`, or `plan`.

- [ ] **Step 4: Verify GREEN and regressions**

```bash
uv run python -m unittest -v \
  tests.test_dci_benchmark_instances \
  tests.test_dci_application_adapter \
  tests.test_benchmark_cli
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add \
  src/asterion/applications/dci_agent_lite/benchmark_instances.py \
  src/asterion/applications/dci_agent_lite/cli.py \
  tests/test_dci_benchmark_instances.py \
  tests/test_dci_application_adapter.py
git commit -m "feat: define exact DCI benchmark instances"
```

### Task 2: Add the exact Bamboogle suite and local benchmark application

**Files:**
- Create: `src/asterion/capabilities/dci/payload/benchmark-suites/qa-bamboogle-github-sample50.json`
- Modify: `src/asterion/capabilities/dci/payload/capability-package.json`
- Modify: `src/asterion/capabilities/dci/payload/conformance/externalization.json`
- Create: `src/asterion/applications/dci_agent_lite/assemblies/dci-local-benchmark-application-claude.json`
- Create: `src/asterion/applications/dci_agent_lite/assemblies/dci-local-benchmark-application-pi.json`
- Modify: `src/asterion/applications/dci_agent_lite/provider.py`
- Modify: `pyproject.toml`
- Modify: `tests/test_dci_capability_payload.py`
- Modify: `tests/test_dci_external_distribution.py`
- Modify: `tests/test_dci_complete_application.py`
- Modify: `tests/test_distribution.py`
- Modify: `tests/test_check_promotion.py`

**Exact suite payload:**

```json
{
  "artifact_media_types": ["application/vnd.dci.benchmark+json"],
  "default_case_limit": 1,
  "default_concurrency": 1,
  "owner_package": {"package_id": "dci", "version": "1.0.0"},
  "protocol": "asterion.benchmark-suite/v1",
  "suite_id": "dci.qa.bamboogle.github-sample50",
  "tasks": [{
    "binding_id": "qa.bamboogle.github-sample50",
    "capability": {"capability_id": "dci.benchmark", "version": "1.0.0"},
    "metric_contract_id": "dci.answer-correctness/v1",
    "note": "GitHub fixed 50-case sample contract.",
    "result_contract_id": "dci.benchmark-result/v1",
    "task_id": "qa.bamboogle.github-sample50"
  }],
  "version": "1.0.0"
}
```

The local application has both existing allowed runtimes and the same six
capabilities/host capabilities as the complete application. Its distinct exact
application identity is the evidence compatibility boundary; executable paths
remain outside JSON.

- [ ] **Step 1: Extend payload/application tests**

Assert the new suite is owned by `dci@1.0.0`, contains exactly one task, and is
byte-identical through built-in and installed-distribution sources. Assert the
provider exposes the local application and the application-index entry point:

```toml
"dci.local-benchmark-application__1.0.0" = "asterion.applications.dci_agent_lite.provider:create_provider"
```

Assert all package resources and conformance digests match their actual
canonical bytes and packaged wheel contents.

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v \
  tests.test_dci_capability_payload \
  tests.test_dci_external_distribution \
  tests.test_dci_complete_application \
  tests.test_distribution \
  tests.test_check_promotion
```

Expected: failure on the absent suite, app, entry point, and changed payload
digest.

- [ ] **Step 3: Add canonical resources and refresh exact digests**

Write compact canonical JSON with sorted keys. Add the suite ref to the package
manifest in canonical order. Recompute the package payload digest through the
existing portable-payload loader, then update the externalization conformance
identity and every test fixture that pins the old exact digest. Do not weaken a
digest assertion or add a compatibility fallback.

- [ ] **Step 4: Verify source and distribution equivalence**

```bash
uv run python -m unittest -v \
  tests.test_dci_capability_payload \
  tests.test_dci_external_distribution \
  tests.test_dci_complete_application \
  tests.test_distribution \
  tests.test_check_promotion
make promotion-check
```

Expected: all focused tests PASS and promotion reports zero provider operations
for resource smoke.

- [ ] **Step 5: Commit**

```bash
git add \
  src/asterion/capabilities/dci/payload \
  src/asterion/applications/dci_agent_lite/assemblies \
  src/asterion/applications/dci_agent_lite/provider.py \
  pyproject.toml \
  tests/test_dci_capability_payload.py \
  tests/test_dci_external_distribution.py \
  tests/test_dci_complete_application.py \
  tests/test_distribution.py \
  tests/test_check_promotion.py
git commit -m "feat: expose local and Bamboogle benchmark selections"
```

### Task 3: Implement metadata-only exact source-lock creation

**Files:**
- Create: `src/asterion/applications/dci_agent_lite/benchmark_source_lock.py`
- Modify: `src/asterion/applications/dci_agent_lite/cli.py`
- Create: `tests/test_dci_benchmark_source_lock.py`
- Modify: `tests/test_dci_application_adapter.py`

**Interfaces:**

```python
class DciBenchmarkSourceLockError(ValueError): ...

def resolve_benchmark_source_lock(
    instance: DciBenchmarkInstance,
    *,
    package_sources: Sequence[CapabilityPackageSource] | None = None,
) -> CapabilitySourceLock: ...

def write_benchmark_source_lock(
    lock: CapabilitySourceLock,
    output: Path,
) -> None: ...
```

Canonical document shape:

```json
{
  "entries": [{
    "package_ref": {"package_id": "dci", "version": "1.0.0"},
    "payload_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "source_id": "example.dci-source"
  }],
  "protocol": "asterion.capability-lock/v1"
}
```

- [ ] **Step 1: Write fail-closed lock tests**

Tests must supply explicit fake sources and assert:

- one candidate produces one validator-accepted exact lock;
- zero or two unlocked candidates fail closed;
- candidate identity and opened payload identity must agree;
- the provider loader is never called;
- canonical bytes end in one newline;
- parent/non-regular/symlink/existing targets fail;
- the new file is mode `0600`;
- private locators and sentinel payload bodies never appear in output/errors.

Adapter tests assert:

```text
asterion-dci benchmark lock
  --instance dci.local-fixture@1.0.0
  --output /absolute/operator/path/capability-lock.json
```

does not load `DciOperatorConfig`.

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v \
  tests.test_dci_benchmark_source_lock \
  tests.test_dci_application_adapter
```

Expected: failure because lock creation is absent.

- [ ] **Step 3: Implement discovery, verification, and safe write**

Use only `discover_metadata`, `open_payload`, and
`validate_source_identity`. Select with the generic
`resolve_capability_source` rule. Create with `O_CREAT|O_EXCL|O_NOFOLLOW`,
mode `0600`, fsync the file and parent directory, and clean up an incomplete
new file on failure. Never overwrite.

- [ ] **Step 4: Verify GREEN**

```bash
uv run python -m unittest -v \
  tests.test_dci_benchmark_source_lock \
  tests.test_dci_application_adapter \
  tests.test_capability_source_protocol
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add \
  src/asterion/applications/dci_agent_lite/benchmark_source_lock.py \
  src/asterion/applications/dci_agent_lite/cli.py \
  tests/test_dci_benchmark_source_lock.py \
  tests/test_dci_application_adapter.py
git commit -m "feat: write exact DCI benchmark source locks"
```

### Task 4: Expose a reusable generic installed-resolution value

**Files:**
- Modify: `src/asterion/benchmarks/host.py`
- Modify: `src/asterion/benchmarks/__init__.py`
- Modify: `tests/test_benchmark_default_host.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class InstalledBenchmarkResolution:
    application: InstalledApplication
    packages: tuple[InstalledCapabilityPackage, ...]

def resolve_installed_benchmark(
    *,
    application_ref: ApplicationRef,
    source_lock_path: Path | None = None,
    application_index_entry_points: Iterable[object] | None = None,
    application_entry_points: Iterable[object] | None = None,
    runtime_factories: RuntimeFactoryRegistry | None = None,
    package_sources: Sequence[CapabilityPackageSource] | None = None,
) -> InstalledBenchmarkResolution: ...
```

`create_installed_benchmark_plan` delegates metadata/source resolution to this
function and then calls `create_benchmark_plan`. The value contains only the
selected application and metadata-only package snapshots; implementations and
benchmark bindings remain empty.

- [ ] **Step 1: Write generic resolution tests**

Assert exact source-lock matching, missing/ambiguous/cyclic composition
rejection, selected-provider-only import, immutable package tuple, empty
implementation/binding tuples, and no DCI import in generic files. Assert the
existing `create_installed_benchmark_plan` result remains byte-for-byte equal
under `render_benchmark_plan` for a fixed test fixture.

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v tests.test_benchmark_default_host
```

Expected: failure because the public resolution function is absent.

- [ ] **Step 3: Extract without changing authority**

Move the existing application selection, source discovery, payload
materialization, metadata package creation, and application composition into
`resolve_installed_benchmark`. Keep source-lock bounded read and symlink
protections unchanged. Keep the default installed host execution-denying.

- [ ] **Step 4: Verify GREEN**

```bash
uv run python -m unittest -v \
  tests.test_benchmark_default_host \
  tests.test_benchmark_planning \
  tests.test_benchmark_cli
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add \
  src/asterion/benchmarks/host.py \
  src/asterion/benchmarks/__init__.py \
  tests/test_benchmark_default_host.py
git commit -m "refactor: expose installed benchmark resolution"
```

### Task 5: Add opaque DCI execution authorization and the formal product host

**Files:**
- Create: `src/asterion/applications/dci_agent_lite/benchmark_authorization.py`
- Create: `src/asterion/applications/dci_agent_lite/benchmark_host.py`
- Modify: `src/asterion/applications/dci_agent_lite/cli.py`
- Modify: `src/asterion/capabilities/dci/implementation/benchmark_bindings.py`
- Create: `tests/test_dci_benchmark_authorization.py`
- Create: `tests/test_dci_benchmark_host.py`
- Modify: `tests/test_dci_benchmark_bindings.py`
- Modify: `tests/test_dci_application_adapter.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class DciBenchmarkExecutionAuthorization:
    instance_selector: str = field(repr=False)
    application_ref: ApplicationRef = field(repr=False)
    suite_ref: BenchmarkSuiteRef = field(repr=False)
    case_limit: int = field(repr=False)
    source_lock: CapabilitySourceLock = field(repr=False)
    evidence_root: Path = field(repr=False)
    run_id: str = field(repr=False)
    resume_run_id: str | None = field(repr=False)
    issuer_nonce: object = field(repr=False)
    claim_nonce: object = field(repr=False)

class DciBenchmarkExecutionAuthorizer:
    def authorize_benchmark_execution(
        self,
        authorization: BenchmarkExecutionAuthorization,
        *,
        application_ref: ApplicationRef,
        suite_ref: BenchmarkSuiteRef,
        case_limit: int,
    ) -> str: ...

class DciBenchmarkHost(BenchmarkCommandHost):
    def __init__(
        self,
        *,
        instance: DciBenchmarkInstance,
        operator_config: DciOperatorConfig | None,
        package_sources: Sequence[CapabilityPackageSource] | None = None,
        cancellation: CancellationSignal | None = None,
        executor_factory: Callable[[DciBenchmarkInstance], BenchmarkTaskExecutor],
    ) -> None: ...
```

Promote the private payload to the intentionally package-internal but
cross-module type:

```python
@dataclass(frozen=True, slots=True)
class DciBenchmarkInvocationPayload:
    profile_id: str
    selection_variant: str
    dataset: Path = field(repr=False)
    corpus: Path = field(repr=False)
    output_directory: Path = field(repr=False)
    private_environment: Mapping[str, str] = field(repr=False)
    amount: Decimal | None = field(repr=False)
    case_limit: int
    max_concurrency: int
    resume_policy: str
    runtime_context_level: str | None
```

The authorization binds exact instance selector, application ref, suite ref,
case count, source-lock entries, evidence intent, new/resume run ID, and a
process-local issuer nonce. Its `repr` and public errors contain no claim body.

- [ ] **Step 1: Write authorization and host lifecycle tests**

Cover:

- forged, replayed, mutated, wrong-instance, wrong-suite, wrong-limit,
  wrong-lock, wrong-evidence-intent, and wrong-resume claims fail before
  provider loading;
- a valid claim yields a canonical run ID and can authorize only once;
- planning works without operator configuration side effects;
- local execution works without loading `.env` or external resource roots;
- real execution rejects a missing operator configuration before provider use;
- execution loads exactly the selected package provider after authorization;
- the loaded `InstalledCapabilityPackage` preserves public metadata but
  replaces empty metadata bindings with
  `create_benchmark_bindings(operator_inputs=...)`;
- missing data/corpus/Judge/runtime readiness fails before executor use;
- public values/errors omit a credential, prompt, answer, provider payload,
  private path, and host-service sentinel;
- the generic installed host still rejects execution.

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v \
  tests.test_dci_benchmark_authorization \
  tests.test_dci_benchmark_host \
  tests.test_dci_benchmark_bindings \
  tests.test_dci_application_adapter
```

Expected: failure because the formal host and opaque claim do not exist.

- [ ] **Step 3: Implement the host as a generic-protocol client**

Use `resolve_installed_benchmark` for metadata/source resolution. Use
`create_benchmark_plan(..., authorizer=DciBenchmarkExecutionAuthorizer(...))`
for execute plans. Load only the source selected by the exact plan lock, call
its `load_provider`, validate returned identity/digest/source identity, and
reconstruct one `InstalledCapabilityPackage` with private DCI bindings. Store
process-local lifecycle state only inside the host object; do not serialize
authorization.

Wire the installed product adapter to create `DciBenchmarkHost` after
`--execute`, a validated source-lock path, evidence root, and resume run ID
shape are all present. Load `DciOperatorConfig` only for a real executor
profile; the local fixture host receives `None`. Retain injection parameters
for focused tests/embedding.

- [ ] **Step 4: Verify GREEN**

```bash
uv run python -m unittest -v \
  tests.test_dci_benchmark_authorization \
  tests.test_dci_benchmark_host \
  tests.test_dci_benchmark_bindings \
  tests.test_dci_application_adapter \
  tests.test_benchmark_cli \
  tests.test_benchmark_planning
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add \
  src/asterion/applications/dci_agent_lite/benchmark_authorization.py \
  src/asterion/applications/dci_agent_lite/benchmark_host.py \
  src/asterion/applications/dci_agent_lite/cli.py \
  src/asterion/capabilities/dci/implementation/benchmark_bindings.py \
  tests/test_dci_benchmark_authorization.py \
  tests/test_dci_benchmark_host.py \
  tests/test_dci_benchmark_bindings.py \
  tests/test_dci_application_adapter.py
git commit -m "feat: authorize installed DCI benchmark execution"
```

### Task 6: Close the provider-free local execution and resume loop

**Files:**
- Create: `src/asterion/applications/dci_agent_lite/benchmark_executor.py`
- Modify: `src/asterion/applications/dci_agent_lite/benchmark_host.py`
- Modify: `src/asterion/capabilities/dci/implementation/operator_inputs.py`
- Create: `tests/test_dci_benchmark_executor.py`
- Create: `tests/test_dci_benchmark_local_e2e.py`

**Interfaces:**

```python
class LocalDciBenchmarkExecutor(BenchmarkTaskExecutor):
    def execute(
        self,
        invocation: BenchmarkTaskInvocation,
        *,
        cancellation: CancellationSignal,
        on_progress: Callable[[BenchmarkProgressEvent], None],
    ) -> BenchmarkTaskResult: ...

def create_local_fixture_operator_inputs(
    private_root: Path,
) -> DciBenchmarkOperatorInputs: ...
```

The local executor validates `DciBenchmarkInvocationPayload`, emits one
`task.fixture.validated` progress event, and returns:

```python
BenchmarkTaskResult(
    task_id=invocation.task_id,
    status="completed",
    case_count=payload.case_limit,
    artifact_ids=(f"{invocation.task_id}.fixture-result",),
)
```

The local input factory maps every exact task to deterministic absolute
descriptor paths below the selected evidence root's `fixture-inputs/`; it uses an empty
private environment and does not create or read dataset/corpus files. The host
uses `BenchmarkRunner`, `LocalPrivateBenchmarkEvidenceStore`, a read-only
cancellation signal, and output directories below the operator-owned evidence
root. It never creates an additional task loop.

- [ ] **Step 1: Write executor and complete lifecycle tests**

Use explicit fake package sources but the real DCI payload, application,
bindings, generic runner, and local evidence store. Assert:

1. `plan` produces all 15 exact tasks with `case_limit=1`;
2. `run --execute` returns completed and writes manifest/progress/task/run
   evidence;
3. `resume --run-id same-run-id` returns the persisted completed result without
   invoking the executor again;
4. mismatched case limit, app, suite, source digest, or run ID fails before
   executor use;
5. cancellation before and during work yields terminal cancelled evidence;
6. no model/Judge/network/external-data hook is called;
7. evidence mode/paths remain private and no sentinel body appears publicly.

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v \
  tests.test_dci_benchmark_executor \
  tests.test_dci_benchmark_local_e2e
```

Expected: failure because no local executor is wired.

- [ ] **Step 3: Implement local executor and runner wiring**

Validate exact payload type, task/binding identity, positive limit, absolute
private paths, fixed concurrency `1`, and cancellation both before and after
progress. For the local profile, create private fixture inputs from the
authorization-bound evidence root and do not call `load_operator_config`.
Build output paths from sanitized run/task identifiers already validated by
generic models. Delegate persistence and resume entirely to `BenchmarkRunner`
and `LocalPrivateBenchmarkEvidenceStore`.

- [ ] **Step 4: Verify GREEN**

```bash
uv run python -m unittest -v \
  tests.test_dci_benchmark_executor \
  tests.test_dci_benchmark_local_e2e \
  tests.test_benchmark_execution \
  tests.test_benchmark_evidence
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add \
  src/asterion/applications/dci_agent_lite/benchmark_executor.py \
  src/asterion/applications/dci_agent_lite/benchmark_host.py \
  src/asterion/capabilities/dci/implementation/operator_inputs.py \
  tests/test_dci_benchmark_executor.py \
  tests/test_dci_benchmark_local_e2e.py
git commit -m "feat: run and resume local DCI benchmark instance"
```

### Task 7: Translate the real Bamboogle instance into the existing Agent/Judge engine

**Files:**
- Modify: `src/asterion/applications/dci_agent_lite/benchmark_executor.py`
- Modify: `src/asterion/applications/dci_agent_lite/benchmark_host.py`
- Modify: `src/asterion/applications/dci_agent_lite/operator_config.py`
- Create: `tests/test_dci_benchmark_real_executor.py`
- Create: `tests/test_dci_benchmark_bamboogle_e2e.py`

**Interfaces:**

```python
class RealDciBenchmarkExecutor(BenchmarkTaskExecutor):
    def __init__(
        self,
        *,
        paths: DciPaths,
        runtime_options: DciRuntimeOptions,
        judge_config: JudgeConfig,
        benchmark_runner: Callable[..., BenchmarkResult] = run_benchmark,
    ) -> None: ...

    def execute(
        self,
        invocation: BenchmarkTaskInvocation,
        *,
        cancellation: CancellationSignal,
        on_progress: Callable[[BenchmarkProgressEvent], None],
    ) -> BenchmarkTaskResult: ...
```

Translation for the first real instance:

```python
BenchmarkRequest(
    dataset=payload.dataset,
    output_root=payload.output_directory,
    cwd=paths.repo_root,
    judge_config=judge_config,
    runtime_options=runtime_options,
    limit=payload.case_limit,
    mode="qa",
    profile=payload.profile_id,
    corpus=payload.corpus,
    max_concurrency=1,
    resume_policy="compatible",
)
```

The executor accepts only task `qa.bamboogle.github-sample50`, profile
`qa.bamboogle`, selection `github-sample50`, and `1 <= case_limit <= 50`.
It maps existing `BenchmarkResult.counts` to one generic task result without
exposing answers or raw artifacts.

- [ ] **Step 1: Write translation, readiness, and bounded E2E tests**

Inject a recording `benchmark_runner` and assert the exact request mapping,
including real dataset/corpus paths, `JudgeConfig`, runtime options, limit,
profile, sequential concurrency, output root, and resume policy. Assert invalid
task/profile/selection/range fails without runner use.

Use temporary one-row JSONL/corpus fixtures and fake Agent/Judge transports at
the existing DCI dependency seams to prove:

```text
DCI host → private binding → RealDciBenchmarkExecutor
→ existing run_benchmark → Agent → Judge → generic result/evidence
```

Assert exactly one Agent request and one Judge request, compatible resume does
not repeat them, cancellation reaches the existing async benchmark engine, and
all sentinel bodies remain absent from CLI output/errors/generic evidence.

Preflight tests must distinguish:

- absent/non-regular/symlink dataset or corpus;
- insufficient dataset rows for the exact requested limit;
- unavailable Agent runtime;
- unavailable Judge credential/config;
- ready one-case execution.

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v \
  tests.test_dci_benchmark_real_executor \
  tests.test_dci_benchmark_bamboogle_e2e
```

Expected: failure because the real executor and readiness mapping are absent.

- [ ] **Step 3: Implement real translation without duplicating DCI**

Resolve `DciPaths`, `DciRuntimeOptions`, and `JudgeConfig` from the already
loaded private operator environment. Count JSONL rows with a bounded streaming
metadata pass; do not parse corpus bodies during preflight. Run
`run_benchmark` in a cancellable worker boundary that sets the existing DCI
cancellation path and drains started work before returning. Emit only symbolic
progress states and generic result counts.

- [ ] **Step 4: Verify GREEN**

```bash
uv run python -m unittest -v \
  tests.test_dci_benchmark_real_executor \
  tests.test_dci_benchmark_bamboogle_e2e \
  tests.test_dci_reproduction \
  tests.test_benchmark_process \
  tests.test_dci_judge_contracts
```

Expected: PASS with fake/local Agent/Judge dependencies and no network.

- [ ] **Step 5: Commit**

```bash
git add \
  src/asterion/applications/dci_agent_lite/benchmark_executor.py \
  src/asterion/applications/dci_agent_lite/benchmark_host.py \
  src/asterion/applications/dci_agent_lite/operator_config.py \
  tests/test_dci_benchmark_real_executor.py \
  tests/test_dci_benchmark_bamboogle_e2e.py
git commit -m "feat: execute bounded Bamboogle through DCI Agent and Judge"
```

### Task 8: Prove the installed-wheel local loop and publish the instance backlog

**Files:**
- Create: `tests/test_asterion_dci_benchmark_installed.py`
- Create: `docs/status/DCI-BENCHMARK-INSTANCES.md`
- Modify: `docs/status/INDEX.md`
- Modify: `docs/status/CURRENT-STATE.md`
- Modify: `docs/status/RESUME-NEXT-SESSION.md`
- Modify: `README.md`
- Modify: `docs/OPERATOR-GUIDE.md`

**Backlog schema:**

| Instance | Task | Implementation | Verification | Full count | Next gate |
|---|---|---|---|---:|---|
| `dci.local-fixture@1.0.0` | 15-task fixture | implemented | `Verified-local` | 1/task | maintain |
| `dci.qa.bamboogle.github-sample50@1.0.0` | `qa.bamboogle.github-sample50` | implemented | initial `Not rerun` | 50 | bounded external run |

Add the remaining fourteen catalog entries with `planned` implementation and
`Not rerun` verification in canonical catalog order. Verification values are
closed to `Not rerun`, `Verified-local`, `External-limited`,
`Verified-bounded`, and `Verified-full`; implementation and verification are
separate columns.

- [ ] **Step 1: Write an installed-wheel subprocess test**

Build a wheel into a temporary directory, create an isolated virtual
environment, install only that wheel, and invoke the console entry point:

```text
asterion-dci benchmark instances --json
asterion-dci benchmark lock --instance dci.local-fixture@1.0.0 --output LOCK
asterion-dci benchmark plan --instance dci.local-fixture@1.0.0 --capability-source-lock LOCK
asterion-dci benchmark run --instance dci.local-fixture@1.0.0 --case-limit 1 --capability-source-lock LOCK --evidence-root EVIDENCE --execute
asterion-dci benchmark resume --instance dci.local-fixture@1.0.0 --run-id RUN --case-limit 1 --capability-source-lock LOCK --evidence-root EVIDENCE --execute
```

Assert run/resume both complete, resume reuses the exact run, 15 tasks are
present, installed resource paths are used, and no checkout-relative import is
possible.

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v tests.test_asterion_dci_benchmark_installed
```

Expected: failure until all resources, entry points, and default host wiring
survive wheel installation.

- [ ] **Step 3: Fix only installed-distribution gaps and write operator docs**

Document exact commands, cost classes, default one-case behavior,
`--all-cases` semantics, source-lock creation, private evidence, resume, and
the fact that real instances use model/network/external data. State that
`--all-cases` planning is not authority to run a full benchmark.

Populate the backlog from the immutable catalog and link it from
`docs/status/INDEX.md` in the Active table. Update current/resume state with
named verification commands only.

- [ ] **Step 4: Verify installed closure and documentation**

```bash
uv run python -m unittest -v tests.test_asterion_dci_benchmark_installed
make docs-check
make promotion-check
```

Expected: PASS. Record `Verified-local` only after the installed subprocess
test passes.

- [ ] **Step 5: Commit**

```bash
git add \
  tests/test_asterion_dci_benchmark_installed.py \
  docs/status/DCI-BENCHMARK-INSTANCES.md \
  docs/status/INDEX.md \
  docs/status/CURRENT-STATE.md \
  docs/status/RESUME-NEXT-SESSION.md \
  README.md \
  docs/OPERATOR-GUIDE.md
git commit -m "docs: publish runnable DCI benchmark closure"
```

Do not stage `docs/status/JOURNAL.md`.

### Task 9: Run one authorized real Bamboogle case and close verification

**Files:**
- Modify: `docs/status/DCI-BENCHMARK-INSTANCES.md`
- Modify: `docs/status/CURRENT-STATE.md`
- Modify: `docs/status/RESUME-NEXT-SESSION.md`
- Append only: `docs/status/JOURNAL.md`

- [ ] **Step 1: Run provider-free full gates first**

```bash
uv run python -m unittest -v tests.test_capability_execution
make test
make lint
make docs-check
make check
make promotion-check
```

Expected: every provider-free gate PASS before any external operation.

- [ ] **Step 2: Prove exact full-range planning without executing it**

```bash
asterion-dci benchmark plan \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --all-cases
```

Expected public plan: exact suite/task and `"case_limit":50`. Confirm no Agent,
Judge, network, corpus read, or evidence creation occurred. Do not run this
50-case plan.

- [ ] **Step 3: Run external readiness only**

Create a fresh exact source lock, select a fresh private evidence root, and run
the existing DCI readiness checks without printing environment values. Record
only body-free readiness categories.

If dataset, corpus, Agent runtime, Judge credential/config, or network
readiness is unavailable, set verification to `External-limited`, record the
named missing category and the exact commands that were not run, and continue
to Step 5. Never promote this state to PASS.

- [ ] **Step 4: Execute exactly one real case when ready**

The user's approved scope authorizes this bounded one-case execution:

```bash
asterion-dci benchmark lock \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --output "$ASTERION_DCI_LOCK_PATH"

asterion-dci benchmark run \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --case-limit 1 \
  --capability-source-lock "$ASTERION_DCI_LOCK_PATH" \
  --evidence-root "$ASTERION_DCI_EVIDENCE_ROOT" \
  --execute
```

Then resume the exact returned run ID with the same case limit, lock, and
evidence root. Confirm resume performs no second Agent/Judge case. Record
`Verified-bounded` only if the real Agent, independent Judge, generic terminal
evidence, and compatible resume all complete successfully.

- [ ] **Step 5: Update evidence-backed status**

Update the backlog and durable status with:

- implementation state;
- exact verification state;
- commands actually run;
- provider operation count;
- selected case count;
- whether external data/network were used;
- body-free failure category if limited;
- confirmation that the 50-case full benchmark was not executed.

Append one concise journal entry and keep the journal unstaged.

- [ ] **Step 6: Review changed code and rerun affected gates**

Use the required `requesting-code-review` skill. Fix every confirmed issue with
a focused regression test. Then use `verification-before-completion` and rerun:

```bash
make check
make promotion-check
git status --short
```

Expected: all gates PASS; only the intentional append-only journal/checkpoint
state may remain unstaged.

- [ ] **Step 7: Commit status evidence**

```bash
git add \
  docs/status/DCI-BENCHMARK-INSTANCES.md \
  docs/status/CURRENT-STATE.md \
  docs/status/RESUME-NEXT-SESSION.md
git commit -m "docs: verify bounded DCI benchmark execution"
```

If external readiness was limited, use:

```bash
git commit -m "docs: record DCI benchmark external limit"
```

## Success Criteria

- The installed wheel exposes an executable `DciBenchmarkHost`; tests do not
  need to inject a host to run the local instance.
- `dci.local-fixture@1.0.0` completes and resumes through exact source locks,
  generic planning, generic runner, and private evidence with zero provider
  operations.
- `dci.qa.bamboogle.github-sample50@1.0.0` maps one bounded case into the
  existing DCI Agent/Judge implementation and has an evidence-backed
  `Verified-bounded` or honest `External-limited` status.
- `--all-cases` resolves to the finite integer 50 in planning and is never
  executed by this plan.
- The remaining fourteen DCI instances exist in a canonical backlog and catalog
  as planned work, ready for one-instance-at-a-time implementation without
  changes to generic benchmark architecture.
- Provider-free tests, docs, checks, and promotion all pass; public surfaces
  contain no private bodies or paths.

## Successor Sequence

After this plan closes, promote exactly one planned catalog entry at a time.
For each entry: add its exact one-task portable suite, expose the exact
application/suite mapping, add executor translation and readiness tests, prove
`--all-cases` finite planning, run a separately authorized one-case external
verification, update the backlog, and commit. Use canonical catalog order
starting with `dci.bcplus.level3@1.0.0`; do not batch-enable the remaining
fourteen instances.
