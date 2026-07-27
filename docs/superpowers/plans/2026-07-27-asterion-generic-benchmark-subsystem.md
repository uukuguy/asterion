# Asterion Generic Benchmark Subsystem Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move suite resolution, bounded planning, sequential execution, progress, cancellation, evidence, and resume into a domain-neutral Asterion benchmark subsystem.

**Architecture:** A selected application and exact capability-package set provide validated suite manifests and implementation bindings. Resolution produces an immutable plan before resource or provider work. The runner consumes that plan plus injected task execution and host services; it does not discover packages, authorize work, retry, or infer DCI configuration.

**Tech Stack:** Python protocols/dataclasses, `argparse`, `asyncio`, descriptor-relative filesystem operations, `unittest`.

## Global Constraints

- Consume only public protocols and package-source interfaces from Plans 1 and 2.
- Generic modules, public messages, and tests contain no DCI task IDs, dataset names, environment keys, or imports.
- Planning is the default; execution requires `--execute` and a finite case bound.
- Suite resolution and implementation binding validation finish before directories, subprocesses, runtimes, or providers are touched.
- The runner is sequential in this phase and stops on first failure or cancellation.
- Evidence contains descriptors, statuses, digests, and public summaries; it never contains prompts, corpus text, answers, provider payloads, raw output, host-service values, credentials, or private paths.
- Operator configuration and prior evidence never grant execution authority.
- Verification is provider-free and uses synthetic fixtures only.

## File structure

- `src/asterion/benchmarks/model.py`: immutable suite, task, invocation, plan, and result values.
- `src/asterion/benchmarks/resolution.py`: exact suite and task-binding resolution.
- `src/asterion/benchmarks/planning.py`: bounded request validation and deterministic plan rendering.
- `src/asterion/benchmarks/evidence.py`: private evidence store and compatible resume.
- `src/asterion/benchmarks/execution.py`: sequential runner and cancellation.
- `src/asterion/benchmarks/process.py`: injected, already-authorized process executor.
- `src/asterion/benchmarks/cli.py`: generic `asterion benchmark` host command.
- `tests/fixtures/benchmarks/`: synthetic, domain-neutral package and suite fixtures.

---

### Task 1: Define immutable benchmark runtime values

**Files:**
- Create: `src/asterion/benchmarks/__init__.py`
- Create: `src/asterion/benchmarks/model.py`
- Create: `tests/test_benchmark_model.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True, slots=True)
class BenchmarkTaskRequest:
    run_id: str
    suite_ref: BenchmarkSuiteRef
    task_id: str
    case_limit: int
    output_directory: Path

@dataclass(frozen=True, slots=True)
class BenchmarkTaskInvocation:
    task_id: str
    binding_id: str
    public_arguments: tuple[str, ...]
    private_payload: object

class BenchmarkTaskImplementation(Protocol):
    def build_invocation(
        self, request: BenchmarkTaskRequest
    ) -> BenchmarkTaskInvocation: ...

@dataclass(frozen=True, slots=True)
class ResolvedBenchmarkTask:
    ordinal: int
    task: BenchmarkTaskManifest
    capability: ResolvedCapability
    binding: BenchmarkTaskBinding

@dataclass(frozen=True, slots=True)
class ResolvedBenchmarkPlan:
    run_id: str
    application_ref: ApplicationRef
    suite: BenchmarkSuiteManifest
    tasks: tuple[ResolvedBenchmarkTask, ...]
    case_limit: int
    package_locks: tuple[CapabilitySourceLock, ...]
```

- Consumes `BenchmarkTaskBinding` from the capability-package SDK and requires
  its opaque `implementation` to satisfy `BenchmarkTaskImplementation` during
  pre-execution resolution.
- `private_payload` is deliberately excluded from `repr` and public
  serialization. `public_arguments` may contain only schema-approved symbolic
  options, never paths or values from operator configuration.

- [ ] **Step 1: Write immutability, canonical-order, and redaction tests**

Assert frozen assignment fails, constructor inputs are copied to tuples,
ordinals are contiguous, task IDs are unique, and `repr`/public dictionaries
omit `private_payload`, output paths, and a sentinel secret.

- [ ] **Step 2: Run and observe the missing module**

Run:

```bash
uv run python -m unittest -v tests.test_benchmark_model
```

Expected: import failure.

- [ ] **Step 3: Implement validated frozen values**

Validate invariants in `__post_init__` and use a public serializer that
explicitly selects safe fields:

```python
def public_plan_dict(plan: ResolvedBenchmarkPlan) -> dict[str, object]:
    return {
        "run_id": plan.run_id,
        "application": str(plan.application_ref),
        "suite": str(plan.suite.ref),
        "case_limit": plan.case_limit,
        "tasks": [
            {
                "ordinal": task.ordinal,
                "task_id": task.task.task_id,
                "capability": str(task.capability.ref),
                "binding_id": task.task.binding_id,
            }
            for task in plan.tasks
        ],
    }
```

- [ ] **Step 4: Verify**

Run:

```bash
uv run python -m unittest -v tests.test_benchmark_model
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/benchmarks tests/test_benchmark_model.py
git commit -m "feat: define generic benchmark runtime values"
```

### Task 2: Resolve exact suites, capabilities, and task bindings

**Files:**
- Create: `src/asterion/benchmarks/resolution.py`
- Create: `tests/test_benchmark_resolution.py`
- Create: `tests/fixtures/benchmarks/valid-suite.json`
- Create: `tests/fixtures/benchmarks/invalid-binding-suite.json`

**Interfaces:**
- Produces:

```python
def resolve_benchmark_suite(
    suite_ref: BenchmarkSuiteRef,
    packages: Sequence[InstalledCapabilityPackage],
) -> BenchmarkSuiteManifest: ...

def resolve_benchmark_tasks(
    suite: BenchmarkSuiteManifest,
    capabilities: Sequence[ResolvedCapability],
    packages: Sequence[InstalledCapabilityPackage],
) -> tuple[ResolvedBenchmarkTask, ...]: ...
```

- [ ] **Step 1: Write the pre-execution rejection matrix**

Cover with `subTest`:

```text
missing suite
duplicate exact suite
suite owner package mismatch
missing capability
capability not selected by application
missing binding
duplicate binding in one package
binding supplied by the wrong package
unknown extra binding
task order changed by input enumeration
valid exact suite
```

Use spies that fail the test if any provider, process, output-directory, or
host-service method is touched.

- [ ] **Step 2: Run and observe the missing resolver**

Run:

```bash
uv run python -m unittest -v tests.test_benchmark_resolution
```

Expected: import failure.

- [ ] **Step 3: Implement exact closed-world resolution**

Build maps only after rejecting duplicate keys:

```python
binding_key = (package.package_ref, binding.binding_id)
task_key = (suite.owner_package, task.binding_id)
```

Require equality of the suite owner, selected capability package, task
capability ref, and binding owner. Return tasks in the suite's canonical task
order with ordinals beginning at `1`.

- [ ] **Step 4: Verify**

Run:

```bash
uv run python -m unittest -v tests.test_benchmark_resolution
```

Expected: PASS and all failures occur before spy activation.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/benchmarks/resolution.py tests/test_benchmark_resolution.py tests/fixtures/benchmarks
git commit -m "feat: resolve exact benchmark task bindings"
```

### Task 3: Build deterministic bounded plans

**Files:**
- Create: `src/asterion/benchmarks/planning.py`
- Create: `tests/test_benchmark_planning.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True, slots=True)
class BenchmarkPlanRequest:
    application_ref: ApplicationRef
    suite_ref: BenchmarkSuiteRef
    case_limit: int | None
    execute: bool
    authorization: BenchmarkExecutionAuthorization | None

def create_benchmark_plan(
    request: BenchmarkPlanRequest,
    application: ResolvedApplication,
    packages: Sequence[InstalledCapabilityPackage],
) -> ResolvedBenchmarkPlan: ...

def render_benchmark_plan(plan: ResolvedBenchmarkPlan) -> str: ...
```

- [ ] **Step 1: Write planning and authority tests**

Verify:

- omitted limit uses the suite's finite `default_case_limit`;
- zero, negative, and above-suite-limit values fail;
- plan-only needs no authorization;
- `execute=True` without a fresh matching authorization fails;
- authorization matches exact application, suite, case limit, and run ID;
- task ordering and rendered text are byte-identical across source enumeration
  order and absolute package locations;
- planning creates no output directory and calls no implementation.

- [ ] **Step 2: Run and observe the missing planner**

Run:

```bash
uv run python -m unittest -v tests.test_benchmark_planning
```

Expected: import failure.

- [ ] **Step 3: Implement pure planning**

Derive a random run ID once at the host boundary, copy exact package locks into
the plan, resolve every task, and return a frozen value. Do not parse `.env`,
inspect dataset paths, create directories, or call provider factories here.

- [ ] **Step 4: Verify**

Run:

```bash
uv run python -m unittest -v tests.test_benchmark_planning
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/benchmarks/planning.py tests/test_benchmark_planning.py
git commit -m "feat: create bounded benchmark plans"
```

### Task 4: Extract a private descriptor-bound evidence store

**Files:**
- Create: `src/asterion/benchmarks/evidence.py`
- Create: `tests/test_benchmark_evidence.py`
- Reference while porting: `tools/dci_benchmark_orchestrator.py`

**Interfaces:**
- Produces:

```python
class BenchmarkEvidenceStore(Protocol):
    def initialize(self, plan: ResolvedBenchmarkPlan) -> None: ...
    def start_task(self, task: ResolvedBenchmarkTask) -> None: ...
    def append_progress(self, event: BenchmarkProgressEvent) -> None: ...
    def finish_task(self, result: BenchmarkTaskResult) -> None: ...
    def finish_run(self, result: BenchmarkRunResult) -> None: ...
    def compatible_completed_tasks(
        self, plan: ResolvedBenchmarkPlan
    ) -> frozenset[str]: ...

class LocalPrivateBenchmarkEvidenceStore(BenchmarkEvidenceStore):
    ...
```

- [ ] **Step 1: Port security and resume tests before implementation**

Move the domain-neutral cases from
`tests/test_dci_benchmark_orchestrator.py` into the new test:

```text
private mode on every created directory and file
pre-existing symlinked run directory rejected
symlink replacement between validation and write rejected
non-regular evidence member rejected
atomic replace remains inside the opened run descriptor
sentinel prompt/answer/credential/path/raw-output never serialized
resume accepts identical suite/package/source/task/case-limit identity
resume rejects any changed identity or incomplete/corrupt evidence
```

The fixtures use names such as `example.task-a`; no DCI identifier is retained.

- [ ] **Step 2: Run and observe the missing store**

Run:

```bash
uv run python -m unittest -v tests.test_benchmark_evidence
```

Expected: import failure.

- [ ] **Step 3: Implement descriptor-relative private writes**

Open the operator-selected evidence root and run directory without following
symlinks. Create directories with `0o700`, files with `0o600`, write a
same-directory temporary member, `fsync`, and replace by descriptor-relative
name. Serialize only allowlisted public fields and content digests.

Resume compatibility must compare:

```python
(
    application_ref,
    suite_ref,
    package_refs,
    payload_digests,
    source_locks,
    ordered_task_ids,
    case_limit,
)
```

- [ ] **Step 4: Verify**

Run:

```bash
uv run python -m unittest -v tests.test_benchmark_evidence
```

Expected: PASS under a temporary directory with an intentionally permissive
umask.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/benchmarks/evidence.py tests/test_benchmark_evidence.py
git commit -m "feat: store private benchmark evidence safely"
```

### Task 5: Implement sequential execution and process-tree cancellation

**Files:**
- Create: `src/asterion/benchmarks/execution.py`
- Create: `src/asterion/benchmarks/process.py`
- Create: `tests/test_benchmark_execution.py`
- Create: `tests/fixtures/helpers/benchmark_process_tree.py`

**Interfaces:**
- Produces:

```python
class BenchmarkTaskExecutor(Protocol):
    def execute(
        self,
        invocation: BenchmarkTaskInvocation,
        *,
        cancellation: CancellationSignal,
        on_progress: Callable[[BenchmarkProgressEvent], None],
    ) -> BenchmarkTaskResult: ...

class BenchmarkRunner:
    def run(
        self,
        plan: ResolvedBenchmarkPlan,
        *,
        executor: BenchmarkTaskExecutor,
        evidence: BenchmarkEvidenceStore,
        cancellation: CancellationSignal,
    ) -> BenchmarkRunResult: ...
```

- `AuthorizedProcessTaskExecutor` consumes an already-authorized immutable
  process plan. It does not select commands or authorize them.

- [ ] **Step 1: Write runner boundary tests**

Cover:

```text
tasks execute once and sequentially
completed compatible tasks are skipped on resume
first task failure prevents later tasks
pre-task cancellation starts nothing
mid-task cancellation reaches executor and stops later tasks
progress sequences are contiguous
one task result and one run terminal result
executor exception becomes a redacted failed result
runner never discovers, authorizes, retries, or starts services
```

Add a real process-tree test whose child creates a grandchild, records public
PIDs in a temporary test file, and waits. Cancellation must terminate the
whole dedicated process group before the test returns. Do not use shell
invocation.

- [ ] **Step 2: Run and observe missing execution modules**

Run:

```bash
uv run python -m unittest -v tests.test_benchmark_execution
```

Expected: import failure.

- [ ] **Step 3: Implement the sequential runner**

For each unresolved task:

1. check cancellation;
2. build one immutable invocation;
3. record task start;
4. call the injected executor;
5. record the terminal task result;
6. stop on non-success.

The process executor uses direct argument vectors, a new process group,
cleared/injected environment, deadline and output caps. On cancellation or
deadline it sends graceful termination to the group, waits a bounded interval,
then force-terminates the group and reaps the direct child.

- [ ] **Step 4: Verify**

Run:

```bash
uv run python -m unittest -v tests.test_benchmark_execution
```

Expected: PASS, including proof that the recorded grandchild PID no longer
exists.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/benchmarks/execution.py src/asterion/benchmarks/process.py tests/test_benchmark_execution.py tests/fixtures/helpers/benchmark_process_tree.py
git commit -m "feat: run benchmark plans sequentially"
```

### Task 6: Add the generic benchmark host command

**Files:**
- Create: `src/asterion/benchmarks/cli.py`
- Modify: `src/asterion/cli.py`
- Create: `tests/test_benchmark_cli.py`
- Modify: `docs/cli.md`

**Interfaces:**
- Adds:

```text
asterion benchmark plan --application ID@VERSION --suite ID@VERSION
asterion benchmark run --application ID@VERSION --suite ID@VERSION --execute
asterion benchmark resume --application ID@VERSION --suite ID@VERSION --run-id ID --execute
```

- Common exact inputs:

```text
--case-limit N
--capability-source-lock PATH
--evidence-root PATH
```

- [ ] **Step 1: Write parser and host-boundary tests**

Verify:

- `plan` is provider-free and does not create evidence;
- `run` without `--execute` exits `2` before loading implementations;
- no command accepts dataset, corpus, launcher, prompt, provider, or amount
  arguments;
- amount/cost is not prompted for and has no required field;
- exact application/suite/source ambiguity errors are stable and redacted;
- provider factory import occurs only after exact plan and authorization;
- interrupt exits nonzero after evidence records cancellation;
- help output describes bounded defaults and external authorization.

- [ ] **Step 2: Run and observe the missing command**

Run:

```bash
uv run python -m unittest -v tests.test_benchmark_cli
```

Expected: parser failure because `benchmark` is absent.

- [ ] **Step 3: Implement a thin host**

The command performs, in order:

```text
parse exact public identifiers
discover metadata
resolve exact source locks
open and validate selected payloads
resolve the application and suite
create and print the immutable plan
stop for plan-only
validate explicit external authorization
load only selected providers
inject host services and executor
run
```

Operator `.env` loading, when desired by an application, occurs outside
`asterion.benchmarks` and produces injected private host configuration.

- [ ] **Step 4: Verify**

Run:

```bash
uv run python -m unittest -v tests.test_benchmark_cli
uv run asterion benchmark plan --help
uv run python tools/check_docs.py
```

Expected: all commands exit `0`; no provider operation occurs.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/benchmarks/cli.py src/asterion/cli.py tests/test_benchmark_cli.py docs/cli.md
git commit -m "feat: add generic benchmark host command"
```

### Task 7: Close the generic subsystem boundary

**Files:**
- Modify: `tests/test_project_boundaries.py`
- Modify: `tests/test_distribution.py`
- Modify: `pyproject.toml`
- Modify: `docs/architecture.md`

**Interfaces:**
- Enforces that generic benchmark code is packaged, public only through
  `asterion.benchmarks`, and domain-neutral.

- [ ] **Step 1: Write structural boundary tests**

Parse Python ASTs below `src/asterion/benchmarks/` and reject:

- imports from `asterion.dci` or `asterion.capabilities.dci`;
- string literals matching DCI dataset/task/environment identifiers;
- package-source discovery inside the runner;
- subprocess use outside `process.py`;
- public serialization of private payloads or paths.

Verify a built wheel contains all benchmark modules and schemas.

- [ ] **Step 2: Run and observe boundary failures**

Run:

```bash
uv run python -m unittest -v tests.test_project_boundaries tests.test_distribution
```

Expected: fail until packaging and boundary rules are complete.

- [ ] **Step 3: Complete packaging and documentation**

Document the dependency direction:

```text
CLI host -> package/application resolution -> benchmark plan
         -> exact task bindings -> runner -> injected executor/services
```

Document that application packages own operator configuration translation,
while generic benchmark code owns orchestration only.

- [ ] **Step 4: Run the phase gate**

Run:

```bash
uv run python -m unittest -v \
  tests.test_benchmark_model \
  tests.test_benchmark_resolution \
  tests.test_benchmark_planning \
  tests.test_benchmark_evidence \
  tests.test_benchmark_execution \
  tests.test_benchmark_cli \
  tests.test_project_boundaries \
  tests.test_distribution
make test
make lint
make docs-check
make check
make promotion-check
```

Expected: every command exits `0`, provider operations are `0`, and no full
dataset is read.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/benchmarks src/asterion/cli.py tests pyproject.toml docs/architecture.md docs/cli.md
git commit -m "test: close generic benchmark subsystem boundary"
```
