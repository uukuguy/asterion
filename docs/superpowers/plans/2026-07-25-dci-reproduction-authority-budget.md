# DCI Reproduction Authority and Budget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make explicit DCI reproduction execution consume one-use, multi-scope authority while enforcing operation and USD reservations, with zero-operation plan mode remaining the default.

**Architecture:** Extend the private authorization registry into the only mutable budget ledger and bind every selected scope to a descriptor-verified child output root. The benchmark executor reserves and reconciles Agent/Judge operations around the existing external-operation boundaries. The CLI performs host preflight, then authorizes and executes in one process only when `--execute` is explicit.

**Tech Stack:** Python 3.12, frozen dataclasses, `threading.Lock`, descriptor-backed filesystem validation, `asyncio`, `unittest`, Ruff.

## Global Constraints

- Without `--execute`, `paper reproduce` performs zero Agent/Judge operations, creates no authority, and requires no budget configuration.
- Budget values, configuration, environment, prior evidence, and caches never grant execution authority.
- Execution requires explicit non-empty paper scope IDs and positive Agent/Judge operation caps.
- Total USD and both per-operation USD upper bounds must be positive and finite.
- Every selected scope has a deterministic, private, descriptor-verified child output root.
- Before provider work, reserve the operation and its configured upper-bound cost under one registry lock.
- Cache reuse consumes no operation budget.
- Invalid or excessive actual cost cancels the authority and prevents all later operations.
- The issuance token, credentials, prompts, answers, corpus bodies, provider payloads, raw output, and private paths never enter public output or errors.
- Tests and verification remain provider-free and never run a full dataset.

---

### Task 1: Build the one-use multi-scope budget ledger

**Files:**
- Modify: `src/asterion/dci/experiment_profiles.py`
- Create: `tests/test_dci_full_authorization.py`

**Interfaces:**
- Consumes: exact `ExperimentProfile`, selected paper scope IDs, fresh parent output root, operation caps, total USD cap, per-operation USD upper bounds, and `invocation_authorized=True`.
- Produces:
  - `ExperimentAuthorizationError`
  - `authorize_full_execution(...) -> FullExecutionAuthorization`
  - `consume_full_execution_authorization(authority, scope_id) -> None`
  - `authorized_scope_output_root(authority, scope_id) -> Path`
  - `reserve_full_execution_operation(authority, scope_id, kind) -> FullExecutionReservation`
  - `reconcile_full_execution_operation(authority, reservation, actual_cost_usd) -> None`
  - `fail_full_execution_operation(authority, reservation) -> None`
  - `cancel_full_execution_authorization(authority) -> None`

- [ ] **Step 1: Write failing construction and validation tests**

Add a real profile helper and matrix tests:

```python
def authorize(
    output_root: Path,
    *,
    scopes: tuple[str, ...] = ("bright.biology.main.full",),
    max_agents: int = 2,
    max_judges: int = 1,
    max_cost: float = 10.0,
    max_agent_cost: float = 2.0,
    max_judge_cost: float = 1.0,
):
    profile = resolve_experiment_profile("paper-reference/pi")
    return authorize_full_execution(
        profile=profile,
        scope_ids=scopes,
        output_root=output_root,
        max_agent_operations=max_agents,
        max_judge_operations=max_judges,
        max_cost_usd=max_cost,
        max_agent_cost_per_operation_usd=max_agent_cost,
        max_judge_cost_per_operation_usd=max_judge_cost,
        invocation_authorized=True,
    )
```

Cover, with `subTest` matrices:

```python
for value in (0, -1, True, 1.5):
    # invalid for integer operation caps

for value in (0.0, -1.0, float("inf"), float("-inf"), float("nan"), True):
    # invalid for total and per-operation USD limits
```

Also assert:

```python
with self.assertRaisesRegex(
    ExperimentAuthorizationError,
    "^full execution requires explicit scopes$",
):
    authorize_full_execution(..., scope_ids=(), ...)

with self.assertRaisesRegex(
    TypeError,
    "^FullExecutionAuthorization is issued only by authorize_full_execution$",
):
    FullExecutionAuthorization()
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_full_authorization.FullExecutionAuthorizationTests.test_requires_exact_positive_limits \
  tests.test_dci_full_authorization.FullExecutionAuthorizationTests.test_constructor_is_private
```

Expected: FAIL because the new exception, signature, and validation do not exist.

- [ ] **Step 3: Implement immutable authority and private registry records**

Use closed frozen values:

```python
class ExperimentAuthorizationError(RuntimeError):
    """Safe public failure for invalid full-execution authority or budget."""


@dataclass(frozen=True, slots=True, init=False)
class FullExecutionReservation:
    scope_id: str
    kind: str
    upper_bound_usd: float
    _authorization_token: str = field(repr=False, compare=False)
    _reservation_token: str = field(repr=False, compare=False)

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError(
            "FullExecutionReservation is issued only by "
            "reserve_full_execution_operation"
        )
```

Extend the immutable authority/snapshot with exact caps. Exclude every path
and token from `repr`. Extend `_AuthorizationRecord` with:

```python
scope_outputs: dict[str, _ScopeOutputIdentity]
consumed_scopes: set[str]
active_reservations: dict[str, _ReservationRecord]
reserved_agent_operations: int
reserved_judge_operations: int
completed_agent_operations: int
completed_judge_operations: int
reserved_cost_usd: float
actual_cost_usd: float
cancelled: bool
finalized: bool
```

Generate opaque deterministic child names with SHA-256 of the exact scope ID,
create them as mode `0700`, and record device/inode identities before
publishing the authorization.

- [ ] **Step 4: Write failing scope, replay, inode, and redaction tests**

Assert:

```python
biology = authorized_scope_output_root(
    authority, "bright.biology.main.full"
)
earth = authorized_scope_output_root(
    authority, "bright.earth-science.main.full"
)
self.assertNotEqual(biology, earth)
self.assertEqual(stat.S_IMODE(biology.stat().st_mode), 0o700)
self.assertNotIn(str(parent), repr(authority))
```

Then cover:

- unknown or unselected scope;
- scope consumed twice;
- profile identity mutation;
- parent root replacement;
- child root replacement;
- sentinel credential and private path absent from every exception string.

- [ ] **Step 5: Run the scope tests and verify RED**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_full_authorization.FullExecutionAuthorizationTests.test_scopes_bind_distinct_private_child_roots \
  tests.test_dci_full_authorization.FullExecutionAuthorizationTests.test_scope_replay_and_inode_replacement_fail_closed \
  tests.test_dci_full_authorization.FullExecutionAuthorizationTests.test_failures_are_redacted
```

Expected: FAIL because scope child identities and replay/redaction checks are
not implemented.

- [ ] **Step 6: Implement consume and scope-root validation**

Every access must:

1. find the original registry record by the private issuance token;
2. require object identity and exact immutable snapshot equality;
3. revalidate parent and child device/inode/mode through descriptors;
4. require exact selected scope membership;
5. reject replay or cancelled/finalized state.

Return only the descriptor-verified child `Path` from
`authorized_scope_output_root`; never include it in a failure.

- [ ] **Step 7: Write failing reservation and reconciliation tests**

Test operation-count and cost boundaries:

```python
authority = authorize(output_root, max_agents=1)
first = reserve_full_execution_operation(
    authority, scope_id, "agent"
)
with self.assertRaisesRegex(
    ExperimentAuthorizationError,
    "^full execution Agent operation budget is exhausted$",
):
    reserve_full_execution_operation(authority, scope_id, "agent")

reconcile_full_execution_operation(authority, first, 0.5)
```

Use subtests for:

- unknown operation kind;
- reservation replay;
- actual cost negative, non-finite, or greater than the reservation;
- active reservations plus actual cost exceeding total USD;
- `fail_full_execution_operation` conservatively settling the full reserved
  upper bound and cancelling later reservations;
- `cancel_full_execution_authorization` rejecting every later reservation.

- [ ] **Step 8: Run the reservation tests and verify RED**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_full_authorization.FullExecutionBudgetTests
```

Expected: FAIL because reservation, reconciliation, failure, and cancellation
functions do not exist.

- [ ] **Step 9: Implement the atomic ledger operations**

Under `_AUTHORIZATION_LOCK`:

```python
projected = (
    record.actual_cost_usd
    + record.reserved_cost_usd
    + upper_bound_usd
)
if projected > snapshot.max_cost_usd:
    raise ExperimentAuthorizationError(
        "full execution USD budget is exhausted"
    )
```

Increment the operation reservation count before returning a private
reservation. Reconciliation removes one active reservation, subtracts its
upper bound, increments completed count, and adds the validated actual cost.
Failure removes the reservation, moves its full upper bound to actual cost,
and sets `cancelled=True`. Cancellation never removes active reservations or
forgets potential spend.

- [ ] **Step 10: Run Task 1 tests**

Run:

```bash
uv run python -m unittest -v tests.test_dci_full_authorization
uv run ruff check \
  src/asterion/dci/experiment_profiles.py \
  tests/test_dci_full_authorization.py
```

Expected: all tests PASS and Ruff reports no issues.

- [ ] **Step 11: Commit Task 1**

```bash
git add src/asterion/dci/experiment_profiles.py \
  tests/test_dci_full_authorization.py
git commit -m "feat: add DCI reproduction budget authority"
```

---

### Task 2: Enforce the ledger around Agent and Judge operations

**Files:**
- Modify: `src/asterion/dci/benchmark.py`
- Modify: `src/asterion/dci/paper_benchmarks.py`
- Modify: `tests/test_dci_full_authorization.py`
- Test: `tests/test_asterion_dci_benchmark.py`

**Interfaces:**
- Consumes: Task 1 authority, reservation, reconciliation, failure, and
  cancellation functions.
- Produces: budget-aware `BenchmarkRequest.experiment_scope_id`, descriptor-
  bound Agent/Judge actual-cost reconciliation, and cache-aware zero-operation
  reuse.

- [ ] **Step 1: Write failing benchmark authorization-boundary tests**

Create provider-free fixture requests with one selected paper scope and assert:

```python
with self.assertRaisesRegex(
    DciBenchmarkError,
    "^DCI benchmark requires full execution authorization$",
):
    run_benchmark(replace(request, full_execution_authorization=None), paths=paths)

with self.assertRaisesRegex(
    DciBenchmarkError,
    "^DCI benchmark authorization scope changed$",
):
    run_benchmark(
        replace(request, experiment_scope_id="bright.earth-science.main.full"),
        paths=paths,
    )
```

Also assert the request output root must equal
`authorized_scope_output_root(authority, scope_id)`, not the parent root or
another scope's child root.

- [ ] **Step 2: Run the boundary tests and verify RED**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_full_authorization.AuthorizedBenchmarkTests.test_requires_exact_authority_scope_and_child_root
```

Expected: FAIL because `BenchmarkRequest.experiment_scope_id` and child-root
binding do not exist.

- [ ] **Step 3: Add the explicit request scope and child-root consumption**

Add:

```python
@dataclass(frozen=True)
class BenchmarkRequest:
    ...
    experiment_scope_id: str | None = None
```

For authorized paper execution, require this exact field. Validate the scope
against the selected rows, profile, and authority before consuming it.
Change `_consumed_authorized_output_identity` to accept `scope_id` and return
that scope's child identity. Existing bounded, non-paper, and provider-free
paths remain unchanged.

- [ ] **Step 4: Write failing operation-cap and cost tests**

Patch only the existing local fixture operation boundaries:

```python
with patch("asterion.dci.benchmark._run_pi_async", side_effect=fake_agent):
    with patch(
        "asterion.dci.benchmark.evaluate_run_directory_async",
        side_effect=fake_judge,
    ):
        result = run_benchmark(request, paths=paths)
```

Cover:

- Agent cap stops before the second `_run_pi_async`;
- Judge cap stops before the second `evaluate_run_directory_async`;
- USD reservation stops before the operation that would exceed total cap;
- Agent state cost and Judge `cost_estimate_usd.total_cost` reconcile;
- actual cost above the reservation cancels later rows;
- one external cancellation prevents waiting rows from starting;
- completed compatible cache evidence performs neither reservation nor
  external operation.

- [ ] **Step 5: Run the operation tests and verify RED**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_full_authorization.AuthorizedBenchmarkBudgetTests
```

Expected: FAIL because the benchmark does not reserve or reconcile operations.

- [ ] **Step 6: Reserve immediately before provider work**

In `_run_row`, reserve only when an external call is actually needed:

```python
agent_reservation = reserve_full_execution_operation(
    authorization,
    scope_id,
    "agent",
)
try:
    await _run_pi_async(...)
    state = native_authority.read_optional_json("state.json")
    actual = _validated_agent_cost(state)
    reconcile_full_execution_operation(
        authorization, agent_reservation, actual
    )
except BaseException:
    fail_full_execution_operation(authorization, agent_reservation)
    raise
```

Do the same around the Judge transport. Validate Judge actual cost from the
returned verdict:

```python
cost = verdict.get("cost_estimate_usd")
if not isinstance(cost, Mapping):
    raise DciBenchmarkError("DCI benchmark Judge cost evidence is invalid")
actual = cost.get("total_cost")
```

Missing or malformed descriptor-bound Agent state, missing Judge cost, and
actual cost above the reservation fail closed. Cache returns before either
reservation.

- [ ] **Step 7: Make cancellation stop later reservations**

When `run_benchmark_async` catches cancellation or a worker failure, call
`cancel_full_execution_authorization` before cancelling and draining pending
tasks. Existing in-flight calls drain; semaphore waiters cannot reserve a new
operation afterward.

- [ ] **Step 8: Run Task 2 tests and regressions**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_full_authorization \
  tests.test_asterion_dci_benchmark
uv run ruff check \
  src/asterion/dci/benchmark.py \
  src/asterion/dci/paper_benchmarks.py \
  tests/test_dci_full_authorization.py
```

Expected: all tests PASS, zero provider operations, and Ruff reports no
issues.

- [ ] **Step 9: Commit Task 2**

```bash
git add src/asterion/dci/benchmark.py \
  src/asterion/dci/paper_benchmarks.py \
  tests/test_dci_full_authorization.py
git commit -m "feat: enforce DCI benchmark operation budgets"
```

---

### Task 3: Join opt-in CLI authorization and multi-scope execution

**Files:**
- Modify: `src/asterion/dci/cli.py`
- Modify: `src/asterion/dci/benchmark.py`
- Modify: `src/asterion/dci/verification.py`
- Modify: `docs/guides/asterion-dci-complete-reference.md`
- Modify: `tests/test_dci_full_authorization.py`
- Modify: `tests/test_asterion_dci_benchmark.py`

**Interfaces:**
- Consumes: Tasks 1–2 exact authority and budget-aware benchmark requests.
- Produces:
  - default plan-only `paper reproduce`;
  - explicit `paper reproduce --execute`;
  - repeatable exact `--scope`;
  - one same-process authorize/execute chain;
  - `execute_authorized_reproduction(...)`.

- [ ] **Step 1: Write failing default-off CLI tests**

Assert the minimal command needs no budget flags:

```python
code = dci_main(
    [
        "paper",
        "reproduce",
        "--profile",
        "paper-reference/pi",
        "--output-root",
        str(output_root),
    ],
    stdout=stdout,
    stderr=stderr,
)
self.assertEqual(code, 0, stderr.getvalue())
self.assertIn("Execution requested: no", stdout.getvalue())
self.assertIn("Agent operations performed: 0", stdout.getvalue())
self.assertFalse(output_root.exists())
```

Patch `authorize_full_execution` and
`execute_authorized_reproduction`; assert neither is called in plan mode.

- [ ] **Step 2: Run the plan-mode test and verify RED**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_full_authorization.ReproductionCliTests.test_plan_mode_is_default_and_needs_no_budget_configuration
```

Expected: FAIL because the old parser requires `--estimated-budget-usd`.

- [ ] **Step 3: Replace issue-and-exit flags with explicit execution flags**

The parser accepts:

```python
paper_reproduce.add_argument("--scope", action="append")
paper_reproduce.add_argument("--execute", action="store_true")
paper_reproduce.add_argument("--max-agent-operations", type=int)
paper_reproduce.add_argument("--max-judge-operations", type=int)
paper_reproduce.add_argument("--max-cost-usd", type=float)
paper_reproduce.add_argument(
    "--max-agent-cost-per-operation-usd", type=float
)
paper_reproduce.add_argument(
    "--max-judge-cost-per-operation-usd", type=float
)
```

Remove `--authorize-full` and `--estimated-budget-usd`. Without `--execute`,
resolve and render a body-free plan, then return without filesystem mutation.

- [ ] **Step 4: Write failing execution-chain and mismatch tests**

Cover:

- `--execute` without any one required limit fails before authorization;
- `--execute` without explicit scopes fails before authorization;
- duplicate, unknown, upstream-only, profile-incompatible, or unavailable
  scope fails before output creation;
- authorize receives the exact resolved profile/scopes/root/limits;
- execute receives the exact authority/profile/scopes/root;
- issuance token and authority `repr` never appear in stdout/stderr;
- execution result contains only body-free operation counts and output
  identities.

Use two executable fixture scopes to prove distinct child-root dispatch.

- [ ] **Step 5: Run execution-chain tests and verify RED**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_full_authorization.ReproductionCliTests
```

Expected: FAIL because `--execute`, scope selection, and same-process
execution do not exist.

- [ ] **Step 6: Implement exact host preflight and coordinator**

Add a frozen internal execution item:

```python
@dataclass(frozen=True, slots=True)
class AuthorizedBenchmarkExecution:
    scope_id: str
    request: BenchmarkRequest
    paths: DciPaths
```

`execute_authorized_reproduction` receives the authority, exact resolved
profile, scope IDs, parent output root, and already-preflighted execution
items. It verifies all identities before the first scope, then runs each item
sequentially. Each request must target the scope child root and carry the
same authority and `experiment_scope_id`.

The CLI host builds execution items only for scopes with exact, available
batch-profile bindings. It resolves dataset/corpus/runtime/Judge inputs before
authorization. Unavailable paper scopes fail closed instead of falling back
to launcher discovery or a different scope.

- [ ] **Step 7: Remove the duplicate issue-and-exit helper**

Delete the duplicate `_paper_reproduce_parser` and authorization branch in
`verification.py`, or make `paper_reproduce_main` delegate to the single CLI
plan/execute implementation without issuing authority itself. There must be
no function that issues live authority and returns `operation_count=0`.

- [ ] **Step 8: Document default-off execution**

Update the complete reference with exact examples:

```bash
# Provider-free plan; no budget configuration required.
uv run asterion-dci paper reproduce \
  --profile paper-reference/pi \
  --output-root ./evidence/reproduction

# Explicit execution; every bound is required.
uv run asterion-dci paper reproduce \
  --profile paper-reference/pi \
  --scope bright.biology.main.full \
  --output-root ./evidence/reproduction \
  --execute \
  --max-agent-operations 103 \
  --max-judge-operations 1 \
  --max-cost-usd 25 \
  --max-agent-cost-per-operation-usd 0.20 \
  --max-judge-cost-per-operation-usd 0.05
```

State that plan mode performs zero provider operations and that budget values
never grant authority.

- [ ] **Step 9: Run Task 3 tests**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_full_authorization \
  tests.test_asterion_dci_benchmark \
  tests.test_asterion_dci_verification
make docs-check
uv run ruff check \
  src/asterion/dci/cli.py \
  src/asterion/dci/benchmark.py \
  src/asterion/dci/verification.py \
  tests/test_dci_full_authorization.py
```

Expected: all tests PASS, docs check passes, and zero provider operations are
performed.

- [ ] **Step 10: Commit Task 3**

```bash
git add src/asterion/dci/cli.py \
  src/asterion/dci/benchmark.py \
  src/asterion/dci/verification.py \
  tests/test_dci_full_authorization.py \
  tests/test_asterion_dci_benchmark.py \
  docs/guides/asterion-dci-complete-reference.md
git commit -m "feat: execute authorized DCI reproduction in process"
```

---

### Task 4: Verify Task 8 as a provider-free promotion boundary

**Files:**
- Modify only if a verification finding requires a test-backed fix.

**Interfaces:**
- Consumes: committed Tasks 1–3.
- Produces: independent review evidence and provider-free promotion proof.

- [ ] **Step 1: Run the Task 8 focused suite**

```bash
uv run python -m unittest -v tests.test_dci_full_authorization
```

Expected: PASS with zero provider operations.

- [ ] **Step 2: Run repository gates**

```bash
make lint
make test
make check
make promotion-check
git diff --check
```

Expected:

- all Python, docs, TypeScript, Rust, build, and package gates PASS;
- promotion reports `provider_operations=0`;
- promotion reports `full_dataset=no`.

- [ ] **Step 3: Review exact security properties**

Independent review must verify:

- default plan mode never constructs authority;
- only `--execute` grants invocation authority;
- every external operation reserves before provider work;
- cost reconciliation uses validated evidence;
- cache reuse consumes no budget;
- multi-scope roots cannot alias or be replaced;
- cancellation blocks later operations;
- all errors and output are body/path/token/credential-free;
- no issue-and-exit authorization path remains.

- [ ] **Step 4: Commit any review fixes separately**

For every Critical or Important finding, write a failing regression test,
apply the smallest fix, rerun the focused suite, and commit with a
finding-specific message. Re-review until CLEAN.

- [ ] **Step 5: Record Task 8 completion**

Append the final commit range and CLEAN review result to
`.superpowers/sdd/progress.md`, then use `/project-state journal` and an
active-session checkpoint before starting Task 9.
