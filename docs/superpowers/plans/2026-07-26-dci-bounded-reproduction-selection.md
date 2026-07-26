# DCI Bounded Reproduction Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic, explicitly authorized one-query reproduction
path that remains default-off, budget-bound, body-free, and classified as
external-limited.

**Architecture:** The CLI computes a bounded per-scope plan from verified
paper selections, then issues the existing one-use authority with both complete
and bounded selection identities. The benchmark independently recomputes that
bounded identity before consuming authority or starting Agent work. Successful
locked batches compile into RunManifest files stored in a separate
descriptor-bound manifest directory so batch artifact inventories remain
closed.

**Tech Stack:** Python 3.12+, `argparse`, immutable dataclasses, descriptor-safe
POSIX file operations, JSON Schema-backed RunManifest validation, `unittest`,
Ruff, Pyright, TypeScript and Rust repository gates.

## Global Constraints

- Default `paper reproduce` without `--execute` performs zero Agent/Judge
  operations, issues no authority, creates no output root, and requires no
  budget configuration.
- Execution requires explicit sorted unique scopes and all five finite positive
  limits.
- `--limit` is one positive integer applied independently to every explicit
  scope and may not exceed any selected scope's published selection count.
- Prefix selection uses the verified dataset source order already used by the
  benchmark; evidence digests use the selected query IDs in canonical sorted
  identity order.
- Complete scope and bounded selection digests remain distinct and immutable.
- Bounded results are `External-limited`; they never change
  `paper_full_executable` or provider-free acceptance.
- Inputs/results remain immutable; public output and errors contain no prompts,
  answers, corpus text, query IDs, provider payloads, credentials, raw output,
  issuance tokens, or private paths.
- Execution remains sequential and fail-closed. Every post-authority error
  cancels or finalizes authority before returning.
- RunManifest files live outside benchmark batch roots in a separately bound
  private manifest directory.
- No implementation or verification command in Tasks 1–5 may perform provider
  work or run a full dataset.

---

### Task 1: Bind bounded selections and manifest storage to authority

**Files:**
- Modify: `src/asterion/dci/experiment_profiles.py`
- Test: `tests/test_dci_full_authorization.py`

**Interfaces:**
- Consumes: exact `ExperimentProfile`, sorted scope IDs, complete profile
  selection digests, bounded preflight digests/counts, planned operation counts,
  output root, and the five existing limits.
- Produces:
  - additional immutable `FullExecutionAuthorization` fields
    `bounded_selected_ids_sha256`, `selected_query_counts`,
    `planned_agent_operations`, and `planned_judge_operations`;
  - `_authorized_scope_selection_identity(authority, scope_id) -> tuple[str,
    int]`;
  - `_authorized_manifest_output_identity(authority) -> tuple[Path, int, int]`;
  - receipt fields carrying the bounded identities and planned counts.

- [ ] **Step 1: Write failing authority contract tests**

Add focused tests to `FullExecutionAuthorizationTests`:

```python
def test_bounded_selection_and_manifest_root_are_identity_bound(self) -> None:
    scope_id = "bright.biology.main.full"
    bounded_digest = canonical_sha256(("q-001",))
    with tempfile.TemporaryDirectory() as temporary:
        authority = authorize_full_execution(
            profile=resolve_experiment_profile("paper-reference/pi"),
            scope_ids=(scope_id,),
            bounded_selected_ids_sha256=(bounded_digest,),
            selected_query_counts=(1,),
            planned_agent_operations=1,
            planned_judge_operations=0,
            output_root=Path(temporary) / "private",
            invocation_authorized=True,
            max_agent_operations=1,
            max_judge_operations=1,
            max_cost_usd=1,
            max_agent_cost_per_operation_usd=1,
            max_judge_cost_per_operation_usd=1,
        )
        self.assertEqual(
            _authorized_scope_selection_identity(authority, scope_id),
            (bounded_digest, 1),
        )
        manifest_root, device, inode = _authorized_manifest_output_identity(
            authority
        )
        self.assertEqual(
            (manifest_root.stat().st_dev, manifest_root.stat().st_ino),
            (device, inode),
        )
        self.assertEqual(stat.S_IMODE(manifest_root.stat().st_mode), 0o700)
        self.assertNotIn(str(manifest_root), repr(authority))
```

Add a `subTest` matrix that rejects:

```python
invalid_cases = {
    "missing bounded digest": {
        "bounded_selected_ids_sha256": (),
        "selected_query_counts": (1,),
    },
    "invalid bounded digest": {
        "bounded_selected_ids_sha256": ("not-a-digest",),
        "selected_query_counts": (1,),
    },
    "zero selected count": {
        "bounded_selected_ids_sha256": (canonical_sha256(("q-001",)),),
        "selected_query_counts": (0,),
    },
    "count exceeds scope": {
        "bounded_selected_ids_sha256": (canonical_sha256(("q-001",)),),
        "selected_query_counts": (104,),
    },
    "agent plan exceeds cap": {
        "bounded_selected_ids_sha256": (canonical_sha256(("q-001",)),),
        "selected_query_counts": (1,),
        "planned_agent_operations": 2,
        "max_agent_operations": 1,
    },
    "judge plan exceeds cap": {
        "bounded_selected_ids_sha256": (canonical_sha256(("q-001",)),),
        "selected_query_counts": (1,),
        "planned_judge_operations": 2,
        "max_judge_operations": 1,
    },
}
```

Also extend forgery, `repr`, receipt immutability, cancellation, inode
replacement, and transactional-cleanup tests to cover the manifest directory
and the four new fields.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_full_authorization.FullExecutionAuthorizationTests.test_bounded_selection_and_manifest_root_are_identity_bound \
  tests.test_dci_full_authorization.FullExecutionAuthorizationTests.test_rejects_invalid_bounded_selection_plans
```

Expected: FAIL because the new authorization parameters, fields, and helpers do
not exist.

- [ ] **Step 3: Implement immutable bounded authority fields**

Extend `FullExecutionAuthorization` and `_AuthorizationSnapshot` with:

```python
bounded_selected_ids_sha256: tuple[str, ...]
selected_query_counts: tuple[int, ...]
planned_agent_operations: int
planned_judge_operations: int
```

Extend `authorize_full_execution` with keyword parameters:

```python
bounded_selected_ids_sha256: Sequence[str] | None = None,
selected_query_counts: Sequence[int] | None = None,
planned_agent_operations: int | None = None,
planned_judge_operations: int | None = None,
```

For the current non-legacy API, validate the supplied values with exact
length/order agreement:

```python
scope_contracts = tuple(
    resolve_paper_experiment_scope(scope_id)
    for scope_id in requested_scope_ids
)
default_counts = tuple(scope.selection_count for scope in scope_contracts)
bounded_digests = (
    selected_digests
    if bounded_selected_ids_sha256 is None
    else tuple(bounded_selected_ids_sha256)
)
selected_counts = (
    default_counts
    if selected_query_counts is None
    else tuple(selected_query_counts)
)
if (
    len(bounded_digests) != len(requested_scope_ids)
    or len(selected_counts) != len(requested_scope_ids)
    or any(
        type(digest) is not str
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        for digest in bounded_digests
    )
    or any(type(count) is not int or count < 1 for count in selected_counts)
):
    raise ExperimentAuthorizationError(
        "full execution bounded selection is invalid"
    )
```

Resolve every paper scope and reject a selected count above its
`selection_count`. Require exact positive integer planned Agent operations,
non-negative integer planned Judge operations, `sum(selected_counts) ==
planned_agent_operations`, and both planned counts no greater than their
operation caps.

For legacy callers, derive full-selection bounded digests/counts and planned
counts from the resolved paper scopes so the legacy compatibility surface
remains deterministic.

Update `_issue_authorization`, `_authorization_matches_snapshot`, the private
registry snapshot, and the body-free receipt to carry all four values.

Update the test-local `authorize(...)` fixture to supply one deterministic
bounded digest/count per requested scope and planned Agent operations equal to
the sum of those counts. Tests that execute concrete rows must override the
fixture with the exact canonical digest/count of those rows; do not weaken
production validation to preserve synthetic tests.

- [ ] **Step 4: Create and bind a separate manifest directory**

During transactional root creation, derive a constant opaque child name:

```python
manifest_child_name = hashlib.sha256(
    b"dci.reproduction-manifests/v1"
).hexdigest()
```

Create it with `_create_private_directory`, retain its
`_ScopeOutputIdentity` in `_AuthorizationRecord`, and include it in rollback.
Add one generic private-directory identity validator and the two accessors:

```python
def _validate_output_identity(
    output: _ScopeOutputIdentity,
    error_label: str,
) -> _ScopeOutputIdentity:
    try:
        device, inode = _private_root_identity(output.path)
    except ValueError:
        raise ExperimentAuthorizationError(
            f"full execution {error_label} identity is invalid"
        ) from None
    if (device, inode) != (output.device, output.inode):
        raise ExperimentAuthorizationError(
            f"full execution {error_label} identity changed"
        )
    return output


def _authorized_manifest_output_identity(
    authority: FullExecutionAuthorization,
) -> tuple[Path, int, int]:
    with _AUTHORIZATION_LOCK:
        record = _validate_authorization(authority)
        output = _validate_output_identity(
            record.manifest_output,
            "manifest output",
        )
        return output.path, output.device, output.inode


def _authorized_scope_selection_identity(
    authority: FullExecutionAuthorization,
    scope_id: str,
) -> tuple[str, int]:
    with _AUTHORIZATION_LOCK:
        record = _validate_authorization(authority)
        index = record.snapshot.authorized_scope_ids.index(scope_id)
        return (
            record.snapshot.bounded_selected_ids_sha256[index],
            record.snapshot.selected_query_counts[index],
        )
```

Use a stable generic `ExperimentAuthorizationError` when the scope is absent or
the manifest directory identity changed. Do not expose either path.

- [ ] **Step 5: Run Task 1 tests and regressions**

Run:

```bash
uv run python -m unittest -v tests.test_dci_full_authorization
uv run ruff check src/asterion/dci/experiment_profiles.py \
  tests/test_dci_full_authorization.py
uv run pyright src/asterion/dci/experiment_profiles.py \
  tests/test_dci_full_authorization.py
git diff --check
```

Expected: all tests pass, Ruff is clean, Pyright reports zero errors, and the
diff check is clean.

- [ ] **Step 6: Commit Task 1**

```bash
git add src/asterion/dci/experiment_profiles.py \
  tests/test_dci_full_authorization.py
git commit -m "feat: bind bounded selections to DCI authority"
```

---

### Task 2: Add plan-only and executable `--limit` orchestration

**Files:**
- Modify: `src/asterion/dci/cli.py`
- Test: `tests/test_dci_full_authorization.py`

**Interfaces:**
- Consumes: Task 1 bounded authority parameters and manifest-root binding.
- Produces:
  - `paper reproduce --limit N`;
  - `_paper_scope_operation_counts(scope_ids, limit) -> tuple[int, int]`;
  - bounded preflight digests/counts passed to authority;
  - exact `BenchmarkRequest.limit` propagation.

- [ ] **Step 1: Write failing plan-mode tests**

Add:

```python
def test_plan_only_limit_one_is_zero_operation_and_creates_no_root(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        output_root = Path(temporary) / "absent"
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = dci_main(
            (
                "paper",
                "reproduce",
                "--profile",
                "paper-reference/pi",
                "--scope",
                "bright.robotics.main.full",
                "--limit",
                "1",
                "--output-root",
                str(output_root),
            ),
            stdout=stdout,
            stderr=stderr,
        )
    self.assertEqual(code, 0, stderr.getvalue())
    self.assertFalse(output_root.exists())
    self.assertIn("Selected queries: 1", stdout.getvalue())
    self.assertIn("Maximum agent operations: 1", stdout.getvalue())
    self.assertIn("Maximum Judge operations: 0", stdout.getvalue())
    self.assertIn("Agent operations performed: 0", stdout.getvalue())
    self.assertIn("Full authorization issued: no", stdout.getvalue())
```

Add a matrix for `0`, `-1`, boolean-like parser rejection, and a limit above
the selected scope count. Assert no environment load, input read, authority, or
output creation.

- [ ] **Step 2: Run plan tests and verify RED**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_full_authorization.ReproductionCliTests.test_plan_only_limit_one_is_zero_operation_and_creates_no_root \
  tests.test_dci_full_authorization.ReproductionCliTests.test_limit_validation_fails_before_authority
```

Expected: FAIL because `paper reproduce` does not accept `--limit`.

- [ ] **Step 3: Add parser and metadata-only count calculation**

Add:

```python
paper_reproduce.add_argument("--limit", type=int)
```

Change `_paper_scope_operation_counts` to:

```python
def _paper_scope_operation_counts(
    scope_ids: tuple[str, ...],
    limit: int | None,
) -> tuple[int, int]:
    from asterion.dci.paper_benchmarks import (
        resolve_paper_benchmark,
        resolve_paper_experiment_scope,
    )

    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("paper reproduction limit is invalid")
    agent_count = 0
    judge_count = 0
    for scope_id in scope_ids:
        scope = resolve_paper_experiment_scope(scope_id)
        if limit is not None and limit > scope.selection_count:
            raise ValueError("paper reproduction limit is invalid")
        selected_count = scope.selection_count if limit is None else limit
        benchmark = resolve_paper_benchmark(scope.dataset_id)
        agent_count += selected_count
        if benchmark.mode == "qa":
            judge_count += selected_count
    return agent_count, judge_count
```

Call it before the plan-mode early return so plan mode stays metadata-only.

- [ ] **Step 4: Write failing execution propagation tests**

Extend the same-process CLI test to pass `--limit 1` and assert:

```python
self.assertEqual(authorize_kwargs["selected_query_counts"], (1,))
self.assertEqual(authorize_kwargs["planned_agent_operations"], 1)
self.assertEqual(authorize_kwargs["planned_judge_operations"], 0)
self.assertEqual(tuple(item.request.limit for item in items), (1,))
self.assertEqual(
    authorize_kwargs["bounded_selected_ids_sha256"],
    (canonical_sha256(("q1",)),),
)
```

Add a multi-scope QA/IR test proving per-scope limits and summed counts. Add
tests that caps below the plan fail before `load_asterion_dci_env`, authority,
or output creation.

- [ ] **Step 5: Run execution tests and verify RED**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_full_authorization.ReproductionCliTests.test_execute_authorizes_and_dispatches_exact_same_process_plan \
  tests.test_dci_full_authorization.ReproductionCliTests.test_execute_rejects_caps_below_bounded_plan
```

Expected: FAIL because preflight does not calculate or pass bounded identities,
requests have no reproduction limit, and cap sufficiency is not checked.

- [ ] **Step 6: Implement preflight-bound selection propagation**

Change `_preflight_reproduction_request` to accept `limit: int | None` and set
`BenchmarkRequest.limit=limit`.

Change `_preflight_scope_selected_ids` to verify the full scope while retaining
the dataset order used by `BenchmarkRequest.limit`:

```python
source_ids = tuple(row.query_id for row in rows)
select_and_verify_scope_ids(scope_id, source_ids)
return source_ids
```

The packaged full-scope digest still validates the canonical selected set.
Only the bounded prefix uses dataset source order, and its evidence digest sorts
the selected prefix IDs.

In execution mode, collect complete selected IDs first:

```python
preflight_selected_ids = tuple(
    _preflight_scope_selected_ids(request, scope_id)
    for scope_id, request in zip(
        selected_scope_ids, preflight_requests, strict=True
    )
)
bounded_selected_ids = tuple(
    selected if args.limit is None else selected[: args.limit]
    for selected in preflight_selected_ids
)
bounded_digests = tuple(
    canonical_sha256(tuple(sorted(selected)))
    for selected in bounded_selected_ids
)
selected_counts = tuple(len(selected) for selected in bounded_selected_ids)
```

Before environment loading or authority, reject:

```python
if (
    limits["max_agent_operations"] < max_agent_operations
    or limits["max_judge_operations"] < max_judge_operations
):
    raise ValueError("full execution operation limits are insufficient")
```

Pass `bounded_digests`, `selected_counts`, and both planned operation counts to
`authorize_full_execution`. Keep complete scope digests profile-derived inside
authority.

- [ ] **Step 7: Run Task 2 tests and regressions**

Run:

```bash
uv run python -m unittest -v tests.test_dci_full_authorization
uv run python -m unittest -v tests.test_asterion_dci_verification
uv run ruff check src/asterion/dci/cli.py tests/test_dci_full_authorization.py
uv run pyright src/asterion/dci/cli.py tests/test_dci_full_authorization.py
git diff --check
```

Expected: all tests pass with zero provider operations.

- [ ] **Step 8: Commit Task 2**

```bash
git add src/asterion/dci/cli.py tests/test_dci_full_authorization.py
git commit -m "feat: plan bounded DCI reproduction selections"
```

---

### Task 3: Revalidate bounded identity before Agent execution

**Files:**
- Modify: `src/asterion/dci/benchmark.py`
- Modify: `src/asterion/dci/reproduction.py`
- Test: `tests/test_dci_full_authorization.py`
- Test: `tests/test_asterion_dci_benchmark.py`
- Test: `tests/test_dci_reproduction.py`

**Interfaces:**
- Consumes: Task 2 `BenchmarkRequest.limit` and Task 1 authorized bounded
  selection helper.
- Produces:
  - pre-Agent bounded digest/count validation;
  - `paper-bounded-authorized` batch evidence;
  - RunManifest preservation of `limit-N` selection identity.

- [ ] **Step 1: Write failing benchmark drift tests**

Add tests proving Agent work is never reached when:

```python
drift_cases = {
    "request limit removed": {"limit": None},
    "request limit changed": {"limit": 2},
    "bounded digest forged": {
        "bounded_selected_ids_sha256": ("f" * 64,),
    },
    "bounded count forged": {"selected_query_counts": (2,)},
    "dataset order changed after preflight": {
        "rows": ("q-002", "q-001"),
    },
}
```

For each case, assert the safe public error, `agent.assert_not_called()`, no
reservation, authority cancellation, and no query ID/private path in rendered
output.

Update existing authorized benchmark fixtures so their authority carries the
canonical digest and count of the exact fixture rows they execute.

- [ ] **Step 2: Run drift tests and verify RED**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_full_authorization.AuthorizedBenchmarkTests.test_bounded_selection_drift_fails_before_agent \
  tests.test_asterion_dci_benchmark.AsterionDciBenchmarkTests.test_authorized_bounded_selection_is_body_free
```

Expected: FAIL because the runner only validates the complete scope digest and
does not compare the limited selection with authority.

- [ ] **Step 3: Validate bounded selection during `_prepare`**

After complete source-scope verification and limit slicing, compute:

```python
bounded_selected_ids_sha256 = canonical_sha256(
    tuple(sorted(row.query_id for row in rows))
)
```

When authority is present, call
`_authorized_scope_selection_identity(authorization, authorized_scope)` and
require both the digest and `len(rows)` to match. Raise
`DciBenchmarkError("DCI benchmark authorization selection changed")` on every
mismatch.

Wrap `_prepare(request)` in `run_benchmark_async` so every preparation failure
calls `_cancel_request_authorization(request)` before re-raising. Keep
consumption after successful selected-row validation and before any external
operation.

- [ ] **Step 4: Write failing evidence and compiler tests**

Add a fixture-backed successful authorized `limit=1` test asserting the config
selection is exactly:

```python
{
    "schema": "asterion.dci.selection/v1",
    "execution_class": "paper-bounded-authorized",
    "id": "limit-1",
    "paper_scope": "bright.robotics.main.full",
    "selected_rows": 1,
    "full_dataset": False,
    "comparable": False,
    "authorization_profile": "paper-reference/pi",
    "selected_ids_sha256": canonical_sha256((selected_query_id,)),
}
```

In `tests/test_dci_reproduction.py`, compile that batch and assert:

```python
self.assertEqual(manifest.selection_id, "limit-1")
self.assertEqual(manifest.selection_sha256, canonical_sha256((query_id,)))
self.assertEqual(manifest.aggregates.query_count, 1)
```

Add forged/rehashed config cases for altered limit ID, paper scope, selected
count, authorization profile, and selected digest.

- [ ] **Step 5: Run evidence tests and verify RED**

Run:

```bash
uv run python -m unittest -v \
  tests.test_asterion_dci_benchmark.AsterionDciBenchmarkTests.test_authorized_limit_one_emits_external_limited_selection \
  tests.test_dci_reproduction.TestDciRunManifestCompiler.test_compile_authorized_bounded_selection
```

Expected: FAIL because authorized limited runs are still labelled
`paper-full-authorized` and compiler validation does not recognize the new
execution class.

- [ ] **Step 6: Implement closed bounded evidence semantics**

In benchmark config construction, choose:

```python
authorized_bounded = (
    authorized_scope is not None
    and request.full_execution_authorization is not None
    and request.limit is not None
)
```

Emit `paper-bounded-authorized`, `id=f"limit-{request.limit}"`,
`full_dataset=False`, `comparable=False`, and the authority profile. Preserve
existing `paper-full-authorized` output when `request.limit is None`.

Extend `_validate_config_document` and related batch reuse validation with the
new exact class. It must require an authorization identity, selected rows equal
the positive numeric limit encoded in `id`, and `full_dataset/comparable` both
false.

Extend `_batch_selection` in `reproduction.py` so
`paper-bounded-authorized` uses the explicit `limit-N` selection ID, verifies
the paper scope belongs to the profile, and preserves the bounded digest. Do
not call `_validate_published_target_selection`, which is reserved for complete
published selections.

- [ ] **Step 7: Run Task 3 suites**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_full_authorization \
  tests.test_asterion_dci_benchmark \
  tests.test_dci_reproduction \
  tests.test_dci_metrics
uv run ruff check src/asterion/dci/benchmark.py \
  src/asterion/dci/reproduction.py \
  tests/test_dci_full_authorization.py \
  tests/test_asterion_dci_benchmark.py \
  tests/test_dci_reproduction.py
uv run pyright src/asterion/dci/benchmark.py \
  src/asterion/dci/reproduction.py \
  tests/test_dci_full_authorization.py \
  tests/test_dci_reproduction.py
git diff --check
```

Expected: all tests pass, static checks report zero errors, and no provider
operation occurs.

- [ ] **Step 8: Commit Task 3**

```bash
git add src/asterion/dci/benchmark.py src/asterion/dci/reproduction.py \
  tests/test_dci_full_authorization.py \
  tests/test_asterion_dci_benchmark.py tests/test_dci_reproduction.py
git commit -m "feat: enforce bounded DCI selection identity"
```

---

### Task 4: Persist body-free RunManifest evidence outside batch roots

**Files:**
- Modify: `src/asterion/dci/reproduction.py`
- Modify: `src/asterion/dci/benchmark.py`
- Modify: `src/asterion/dci/cli.py`
- Test: `tests/test_dci_reproduction.py`
- Test: `tests/test_asterion_dci_benchmark.py`
- Test: `tests/test_dci_full_authorization.py`

**Interfaces:**
- Consumes: Task 1 manifest root and Task 3 completed locked batches.
- Produces:
  - `write_run_manifest(manifest_root, expected_identity, scope_id, manifest)
    -> str`, returning a relative opaque artifact name;
  - coordinator output fields `manifest_artifact` and
    `manifest_identity_sha256`;
  - CLI body-free `manifest_scope`, `manifest_artifact`, and
    `manifest_identity_sha256` lines.

- [ ] **Step 1: Write failing descriptor-safe writer tests**

Add tests that:

```python
expected_identity = (manifest_root.stat().st_dev, manifest_root.stat().st_ino)
artifact = write_run_manifest(
    manifest_root,
    expected_identity,
    scope_id,
    manifest,
)
self.assertEqual(
    artifact,
    hashlib.sha256(scope_id.encode("utf-8")).hexdigest() + ".json",
)
written = manifest_root / artifact
self.assertEqual(stat.S_IMODE(written.stat().st_mode), 0o600)
self.assertEqual(load_run_manifest(written), manifest)
```

Add rejection tests for symlinked/replaced manifest root, existing artifact,
invalid scope ID, mutated manifest, and a sentinel private path/body field.
Assert a writer failure never changes the completed batch artifact inventory.

- [ ] **Step 2: Run writer tests and verify RED**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_reproduction.TestDciRunManifestCompiler.test_write_run_manifest_is_private_and_descriptor_bound \
  tests.test_dci_reproduction.TestDciRunManifestCompiler.test_write_run_manifest_rejects_replacement_and_overwrite
```

Expected: FAIL because `write_run_manifest` does not exist.

- [ ] **Step 3: Implement the manifest writer**

Validate the manifest with `validate_run_manifest`, derive the opaque filename
from `sha256(scope_id)`, open the already bound manifest root through a
no-follow directory descriptor, compare `os.fstat(root_descriptor)` with the
expected device/inode pair, and create the file with:

```python
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
descriptor = os.open(artifact_name, flags, 0o600, dir_fd=root_descriptor)
```

Write:

```python
payload = (
    json.dumps(
        validated.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    + b"\n"
)
```

Use `os.fchmod`, `flush`, and `fsync`; close every descriptor on every path.
Re-open and validate the written file before returning only the relative
artifact name.

- [ ] **Step 4: Write failing coordinator tests**

For two local fixture scopes, patch provider work with existing deterministic
fixture results and assert:

```python
self.assertEqual(
    set(result["outputs"][0]),
    {
        "scope_id",
        "output_root_device",
        "output_root_inode",
        "manifest_artifact",
        "manifest_identity_sha256",
    },
)
self.assertRegex(result["outputs"][0]["manifest_artifact"], r"^[0-9a-f]{64}\\.json$")
self.assertRegex(
    result["outputs"][0]["manifest_identity_sha256"], r"^[0-9a-f]{64}$"
)
```

Add a compiler/writer failure test proving later scopes do not start,
authorization is cancelled, no success result is returned, and public output
contains no path/query/body sentinel.

- [ ] **Step 5: Run coordinator tests and verify RED**

Run:

```bash
uv run python -m unittest -v \
  tests.test_asterion_dci_benchmark.AsterionDciBenchmarkTests.test_authorized_reproduction_compiles_each_manifest_before_next_scope \
  tests.test_asterion_dci_benchmark.AsterionDciBenchmarkTests.test_manifest_failure_cancels_authority_and_stops
```

Expected: FAIL because coordinator outputs do not contain RunManifest evidence.

- [ ] **Step 6: Compile and write each manifest before the next scope**

Inside the sequential coordinator loop, immediately after `run_benchmark`:

```python
manifest = compile_run_manifest(result.output_root, profile)
manifest_root, manifest_device, manifest_inode = (
    _authorized_manifest_output_identity(authority)
)
manifest_artifact = write_run_manifest(
    manifest_root,
    (manifest_device, manifest_inode),
    item.scope_id,
    manifest,
)
```

Add the artifact name and `manifest.identity_sha256` to that scope's body-free
output record. Compile/write before starting the next scope. Obtain the final
receipt only after every manifest succeeds. Existing outer cancellation handles
compiler/writer failures.

Tighten `_write_reproduction_execution_result` to require exact output keys and
print only scope ID, relative artifact name, and manifest digest. It must reject
extra fields, malformed hashes, absolute paths, and path separators in artifact
names.

- [ ] **Step 7: Run Task 4 suites**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_reproduction \
  tests.test_asterion_dci_benchmark \
  tests.test_dci_full_authorization
uv run ruff check src/asterion/dci/reproduction.py \
  src/asterion/dci/benchmark.py src/asterion/dci/cli.py \
  tests/test_dci_reproduction.py \
  tests/test_asterion_dci_benchmark.py \
  tests/test_dci_full_authorization.py
uv run pyright src/asterion/dci/reproduction.py \
  src/asterion/dci/benchmark.py src/asterion/dci/cli.py
git diff --check
```

Expected: all tests and static checks pass.

- [ ] **Step 8: Commit Task 4**

```bash
git add src/asterion/dci/reproduction.py src/asterion/dci/benchmark.py \
  src/asterion/dci/cli.py tests/test_dci_reproduction.py \
  tests/test_asterion_dci_benchmark.py \
  tests/test_dci_full_authorization.py
git commit -m "feat: persist bounded DCI RunManifest evidence"
```

---

### Task 5: Publish the corrected Task 11 contract and run provider-free gates

**Files:**
- Modify: `README.md`
- Modify: `docs/guides/asterion-dci-complete-reference.md`
- Modify: `docs/verification/asterion-dci-validation-guide.md`
- Modify: `docs/superpowers/plans/2026-07-24-dci-provenance-reproduction.md`
- Test: `tests/test_standalone_repository.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: accurate one-query instructions, explicit external-limited
  classification, and fresh provider-free promotion evidence.

- [ ] **Step 1: Write failing documentation contract tests**

Add assertions that public docs contain:

```python
required_fragments = (
    "paper reproduce",
    "--scope bright.robotics.main.full",
    "--limit 1",
    "--execute",
    "--max-agent-operations 1",
    "--max-judge-operations 1",
    "External-limited",
)
```

Assert the docs do not contain `--dry-run`, `--authorize-full`, a
`browsecomp-plus.appendix-a1.random50` smoke scope, or any statement that a
one-query result is full paper reproduction.

- [ ] **Step 2: Run docs tests and verify RED**

Run:

```bash
uv run python -m unittest -v \
  tests.test_standalone_repository.StandaloneRepositoryTests.test_docs_publish_bounded_reproduction_boundary
```

Expected: FAIL because current docs do not describe the implemented bounded
execution contract.

- [ ] **Step 3: Update public and plan documentation**

Document:

- the default plan-only one-query command;
- the exact explicit execution flags without supplying an operator-specific
  cost cap or output root as if pre-authorized;
- the distinction between complete scope identity and bounded execution
  selection;
- private manifest location semantics and body-free CLI references;
- `External-limited` classification;
- unchanged `paper_full_executable=false`;
- a corrected Task 11 sequence that removes obsolete `asterion-safe/pi`,
  unavailable BrowseComp+ scope, `--dry-run`, and unsupported assumptions.

- [ ] **Step 4: Run all provider-free gates**

Use a fresh nonexistent output path:

```bash
plan_parent=$(mktemp -d)
plan_root="$plan_parent/not-created"
uv run asterion-dci paper describe
uv run asterion-dci paper verify
uv run asterion-dci paper reproduce \
  --profile paper-reference/pi \
  --scope bright.robotics.main.full \
  --limit 1 \
  --output-root "$plan_root"
test ! -e "$plan_root"
make lint
make test
make docs-check
make check
make promotion-check
```

Expected:

- plan reports one selected query, one maximum Agent operation, zero maximum
  Judge operations, zero performed operations, and no authority;
- output root remains absent;
- `make test` passes all Python tests;
- `make check` passes Python, Ruff, docs, TypeScript, Rust, and distribution
  gates;
- promotion passes 19 commands with `provider_operations=0` and
  `full_dataset=no`.

- [ ] **Step 5: Run an independent security/claim review**

The reviewer must verify:

- default-off behavior;
- exact scope/limit/budget binding;
- bounded/full digest separation;
- pre-Agent drift rejection;
- one-use cancellation and replay behavior;
- manifest directory descriptor safety;
- closed batch artifact inventory;
- body-free output/redaction;
- external-limited classification;
- no provider/full-dataset work in gates.

Expected: zero Critical, Important, or Minor findings. Fix every finding with a
new RED/GREEN cycle and re-review until CLEAN.

- [ ] **Step 6: Commit Task 5**

```bash
git add README.md docs/guides/asterion-dci-complete-reference.md \
  docs/verification/asterion-dci-validation-guide.md \
  docs/superpowers/plans/2026-07-24-dci-provenance-reproduction.md \
  tests/test_standalone_repository.py
git commit -m "docs: publish bounded DCI reproduction workflow"
```

---

## External execution gate after implementation

Provider-backed Task 11 is not part of the implementation commits or
provider-free gates. After Tasks 1–5 are reviewed CLEAN, request a new exact
operator approval containing:

- profile: `paper-reference/pi`;
- scope: `bright.robotics.main.full`;
- limit: `1`;
- operator-selected private output root outside Git;
- `max-agent-operations=1`;
- `max-judge-operations=1`;
- positive finite total USD cap;
- positive finite per-Agent-operation USD cap;
- positive finite per-Judge-operation USD cap.

Then run preflight again before authority. Execute once only after that approval,
compile/load the RunManifest, run the explicit comparison command, and classify
the result `External-limited`.
