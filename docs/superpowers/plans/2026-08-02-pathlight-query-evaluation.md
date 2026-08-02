# Pathlight Query and Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make validated Pathlight traces and versioned evaluations safely readable, queryable and comparable through framework APIs and the `asterion pathlight` CLI.

**Architecture:** Keep the existing immutable trace graph as the source record. Add strict readers for operator-selected workflow bundles, a separate immutable evaluation contract, and an in-memory query catalog assembled by the CLI host; no runner or runtime performs discovery or persistence. Product-specific historical recovery remains outside framework core and will feed these public-safe contracts in the next phase.

**Tech Stack:** Python 3.12, frozen dataclasses, canonical JSON/SHA-256, `argparse`, `unittest`.

## Global Constraints

- Framework code stays domain-neutral and must not import DCI modules, manifests, tests or adjacent source trees.
- `dci.agent-runtime/v1`, `dci.package/v1` and `dci.assembly/v1` remain unchanged.
- Default Pathlight records and every CLI/API payload must never contain prompts, answers, credentials, model/tool payloads, corpus text, raw output, artifact URIs or private paths.
- All input files are selected explicitly by the operator; do not scan directories, follow symlinks, infer precedence or mutate evidence.
- Trace, evaluation, metric contract and comparison digests are verified before any query output is returned.
- Comparisons fail closed unless metric contract, dataset snapshot, scope and coverage agree exactly.
- Query and evaluation commands are provider-free and perform no model, Judge, network, host-service or benchmark execution.
- Use `unittest`; each task starts RED, reaches GREEN, then commits independently.

## File Structure

- Modify: `src/asterion/workflow_evidence/storage.py` — strict immutable reader for existing observation bundles.
- Modify: `src/asterion/workflow_evidence/__init__.py` — export the reader and bundle value.
- Create: `src/asterion/pathlight/evaluation.py` — metric/evaluation contracts, canonical validation and comparison.
- Create: `src/asterion/pathlight/query.py` — in-memory trace/evaluation catalog with safe filters and summaries.
- Modify: `src/asterion/pathlight/__init__.py` — narrow public query/evaluation exports.
- Create: `src/asterion/cli_pathlight.py` — provider-free Pathlight CLI subtree.
- Modify: `src/asterion/cli.py` — route `asterion pathlight` before provider loading.
- Modify: `docs/cli.md` — exact safe query commands and boundaries.
- Modify: `tests/test_workflow_evidence_storage.py` — read, integrity, symlink and redaction coverage.
- Create: `tests/test_pathlight_evaluation.py` — evaluation validation and comparability matrices.
- Create: `tests/test_pathlight_query.py` — trace list/show/tail and metric filtering.
- Create: `tests/test_pathlight_cli.py` — installed-style command behavior and public redaction.

---

### Task 1: Read workflow observation bundles without weakening evidence integrity

**Files:**
- Modify: `src/asterion/workflow_evidence/storage.py`
- Modify: `src/asterion/workflow_evidence/__init__.py`
- Modify: `tests/test_workflow_evidence_storage.py`

**Interfaces:**
- Produces `WorkflowObservationBundle`, a frozen value with `records`, `pathlight_traces` and `bundle_sha256` tuples/strings.
- Produces `read_workflow_observation_bundle(path: Path) -> WorkflowObservationBundle`.
- Later tasks consume only the validated immutable value; they never reopen its file.

- [ ] **Step 1: Write failing reader tests**

```python
def test_reads_written_bundle_as_immutable_validated_value(self) -> None:
    write_workflow_observation_bundle(path, (_completed_record(),), pathlight_traces=(trace,))
    bundle = read_workflow_observation_bundle(path)
    self.assertEqual(bundle.bundle_sha256, json.loads(path.read_text())["bundle_sha256"])
    self.assertEqual(bundle.pathlight_traces[0]["trace_sha256"], trace["trace_sha256"])
    with self.assertRaises(TypeError):
        bundle.pathlight_traces[0]["trace_id"] = "mutated"  # type: ignore[index]

def test_reader_rejects_symlink_tamper_and_private_extra_field(self) -> None:
    for mutation in ("symlink", "bundle-digest", "trace-digest", "unknown-field"):
        with self.subTest(mutation=mutation), self.assertRaises(WorkflowEvidenceError):
            read_workflow_observation_bundle(_mutated_bundle_path(mutation))
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `uv run python -m unittest -v tests.test_workflow_evidence_storage`

Expected: FAIL because `read_workflow_observation_bundle` and `WorkflowObservationBundle` do not exist.

- [ ] **Step 3: Implement the strict reader**

```python
@dataclass(frozen=True, slots=True)
class WorkflowObservationBundle:
    records: tuple[Mapping[str, object], ...]
    pathlight_traces: tuple[Mapping[str, object], ...]
    bundle_sha256: str

def read_workflow_observation_bundle(path: Path) -> WorkflowObservationBundle:
    if path.name != "workflow-evidence.json" or path.is_symlink() or not path.is_file():
        raise WorkflowEvidenceError("workflow observation source is invalid")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise WorkflowEvidenceError("workflow observation source is invalid") from error
    return _validate_and_freeze_bundle(document)
```

Require exactly `schema`, `records`, `pathlight_traces`, `bundle_sha256`; recompute the bundle digest over the other three fields; reuse the existing record and trace validators; reject duplicate run/trace identities; recursively freeze mappings and sequences. Error text must not contain the selected path or JSON content.

- [ ] **Step 4: Run focused storage tests and confirm GREEN**

Run: `uv run python -m unittest -v tests.test_workflow_evidence_storage`

Expected: PASS for write/read round-trip, corrupted JSON, digest mismatch, duplicate identity, symlink and sentinel-private-field cases.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/workflow_evidence tests/test_workflow_evidence_storage.py
git commit -m "feat: read validated Pathlight evidence bundles"
```

### Task 2: Define versioned Metric and Evaluation records with exact comparability

**Files:**
- Create: `src/asterion/pathlight/evaluation.py`
- Modify: `src/asterion/pathlight/__init__.py`
- Create: `tests/test_pathlight_evaluation.py`

**Interfaces:**
- Produces `MetricContract`, `EvaluationRecord`, `EvaluationComparison`, `EvaluationBundle`, `validate_evaluation_record(mapping)`, `write_evaluation_bundle(path, records)`, `read_evaluation_bundle(path)` and `compare_evaluations(baseline, candidate)`.
- `MetricContract` contains only `metric_name`, `unit`, `higher_is_better`, `contract_version` and its canonical SHA-256.
- `EvaluationRecord` contains digest identities, integer `value_microunits`, exact `selected_count`/`total_count`, and canonical SHA-256; no case IDs or product payloads.

- [ ] **Step 1: Write failing evaluation tests**

```python
def test_compares_only_same_contract_snapshot_scope_and_coverage(self) -> None:
    baseline = evaluation(value_microunits=771_000)
    candidate = evaluation(value_microunits=445_600)
    comparison = compare_evaluations(baseline, candidate)
    self.assertEqual(comparison.status, "comparable")
    self.assertEqual(comparison.delta_microunits, -325_400)

def test_rejects_every_incompatible_dimension(self) -> None:
    for field in ("metric_contract_sha256", "dataset_snapshot_sha256", "scope_sha256", "selected_count", "total_count"):
        with self.subTest(field=field):
            self.assertEqual(compare_evaluations(base, replace(base, **changed(field))).status, "not-comparable")
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `uv run python -m unittest -v tests.test_pathlight_evaluation`

Expected: FAIL because `asterion.pathlight.evaluation` does not exist.

- [ ] **Step 3: Implement frozen contracts and canonical mapping validation**

```python
@dataclass(frozen=True, slots=True)
class MetricContract:
    metric_name: str
    unit: str
    higher_is_better: bool
    contract_version: str
    metric_contract_sha256: str = field(init=False)

@dataclass(frozen=True, slots=True)
class EvaluationRecord:
    trace_sha256: str
    metric_contract_sha256: str
    dataset_snapshot_sha256: str
    scope_sha256: str
    value_microunits: int | None
    selected_count: int
    total_count: int
    status: Literal["observed", "recovered", "missing"]
    evaluation_sha256: str = field(init=False)

@dataclass(frozen=True, slots=True)
class EvaluationBundle:
    evaluations: tuple[EvaluationRecord, ...]
    bundle_sha256: str

def compare_evaluations(baseline: EvaluationRecord, candidate: EvaluationRecord) -> EvaluationComparison:
    reasons = _comparability_reasons(baseline, candidate)
    return EvaluationComparison.not_comparable(reasons) if reasons else EvaluationComparison.comparable(baseline, candidate)
```

Use an allowlist for metric names (`accuracy`, `ndcg-at-10`, plus existing generic Pathlight metrics), units (`ratio`, `count`, `microunits`, `tokens`, `nanoseconds`), and semantic versions matching `^[0-9]+\.[0-9]+\.[0-9]+$`. Require SHA-256 identities and nonnegative integer counts; require `selected_count <= total_count`; `missing` records must use `value_microunits=None`, while observed/recovered records require an integer. Mapping validators reject unknown fields and digest mismatches. Evaluation bundles use exact schema `asterion.pathlight-evaluations/v1`, sorted unique evaluation identities, a canonical bundle digest, filename `pathlight-evaluations.json`, mode `0600`, exclusive creation on write, and the same explicit regular-file/no-symlink rules on read as workflow bundles.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `uv run python -m unittest -v tests.test_pathlight_evaluation tests.test_pathlight_protocol`

Expected: PASS, including immutable bundle write/read, exact-field, invalid-bool-as-int, unsafe-string, symlink, duplicate identity and comparability matrices.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/pathlight tests/test_pathlight_evaluation.py
git commit -m "feat: define Pathlight evaluation contracts"
```

### Task 3: Query validated traces and evaluations through one framework catalog

**Files:**
- Create: `src/asterion/pathlight/query.py`
- Modify: `src/asterion/pathlight/__init__.py`
- Create: `tests/test_pathlight_query.py`

**Interfaces:**
- Consumes validated `WorkflowObservationBundle` and `EvaluationRecord` values.
- Produces `PathlightCatalog.build(bundles, evaluations)`, `list_traces(filter)`, `show_trace(trace_id)`, `tail_trace(trace_id, after_sequence=0)`, `query_metrics(filter)` and `compare_evaluation_ids(baseline_sha256, candidate_sha256)`.
- Produces only immutable JSON-compatible safe projections.

- [ ] **Step 1: Write failing catalog tests**

```python
def test_list_show_and_tail_are_deterministic_and_safe(self) -> None:
    catalog = PathlightCatalog.build((bundle_b, bundle_a), ())
    self.assertEqual([row["trace_id"] for row in catalog.list_traces()], sorted((TRACE_A, TRACE_B)))
    self.assertEqual([event["sequence"] for event in catalog.tail_trace(TRACE_A, after_sequence=1)], [2])
    rendered = json.dumps(catalog.show_trace(TRACE_A), sort_keys=True)
    self.assertNotIn("SENTINEL_PRIVATE", rendered)

def test_catalog_rejects_duplicate_trace_or_evaluation_identity(self) -> None:
    with self.assertRaises(PathlightError):
        PathlightCatalog.build((bundle, bundle), ())
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `uv run python -m unittest -v tests.test_pathlight_query`

Expected: FAIL because `PathlightCatalog` does not exist.

- [ ] **Step 3: Implement the immutable query catalog**

```python
@dataclass(frozen=True, slots=True)
class TraceFilter:
    status: str | None = None
    kind: str | None = None
    component_sha256: str | None = None

class PathlightCatalog:
    @classmethod
    def build(cls, bundles: Sequence[WorkflowObservationBundle], evaluations: Sequence[EvaluationRecord]) -> PathlightCatalog:
        traces: dict[str, Mapping[str, object]] = {}
        records: dict[str, EvaluationRecord] = {}
        for bundle in bundles:
            for trace in bundle.pathlight_traces:
                trace_id = cast(str, trace["trace_id"])
                if trace_id in traces:
                    raise PathlightError("Pathlight trace identity is duplicated")
                traces[trace_id] = trace
        for evaluation in evaluations:
            if evaluation.evaluation_sha256 in records:
                raise PathlightError("Pathlight evaluation identity is duplicated")
            records[evaluation.evaluation_sha256] = evaluation
        return cls(MappingProxyType(traces), MappingProxyType(records))

    def list_traces(self, query: TraceFilter = TraceFilter()) -> tuple[Mapping[str, object], ...]:
        return tuple(
            _trace_summary(self._traces[trace_id])
            for trace_id in sorted(self._traces)
            if _matches_trace_filter(self._traces[trace_id], query)
        )

    def show_trace(self, trace_id: str) -> Mapping[str, object]:
        _require_trace_id(trace_id)
        try:
            return self._traces[trace_id]
        except KeyError as error:
            raise PathlightError("Pathlight trace identity is unknown") from error

    def tail_trace(self, trace_id: str, *, after_sequence: int = 0) -> tuple[Mapping[str, object], ...]:
        if type(after_sequence) is not int or after_sequence < 0:
            raise PathlightError("Pathlight event sequence is invalid")
        trace = self.show_trace(trace_id)
        events = cast(Sequence[Mapping[str, object]], trace["events"])
        return tuple(event for event in events if cast(int, event["sequence"]) > after_sequence)
```

Implement private `_require_trace_id`, `_trace_summary` and `_matches_trace_filter` in the same module. Summaries contain only trace ID/digest, root status, event/span counts, first/last timestamps, safe component digests and `missing_evidence` count. Filtering supports status, event kind and an exact digest value found only under an allowlisted component digest attribute; output is sorted by trace ID/evaluation digest. `show_trace` returns the already immutable validated graph; `tail_trace` is a deterministic non-following read of events after an exact sequence. Missing and duplicate identities fail closed without listing available private values.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `uv run python -m unittest -v tests.test_pathlight_query tests.test_pathlight_evaluation tests.test_workflow_evidence_storage`

Expected: PASS for ordering, filters, unknown IDs, duplicate inputs, immutability, empty catalogs and sentinel redaction.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/pathlight tests/test_pathlight_query.py
git commit -m "feat: query validated Pathlight records"
```

### Task 4: Expose provider-free `asterion pathlight` query and comparison commands

**Files:**
- Create: `src/asterion/cli_pathlight.py`
- Modify: `src/asterion/cli.py`
- Modify: `docs/cli.md`
- Create: `tests/test_pathlight_cli.py`
- Modify: `tests/test_asterion_cli.py`

**Interfaces:**
- Consumes `read_workflow_observation_bundle`, evaluation JSON readers and `PathlightCatalog`.
- Produces commands `pathlight trace list`, `pathlight trace show`, `pathlight trace tail`, `pathlight metrics query`, and `pathlight evaluate compare`.
- All successful stdout is canonical one-line JSON; all failures are fixed public-safe messages on stderr with exit code `2`.

- [ ] **Step 1: Write failing CLI tests**

```python
def test_pathlight_routes_without_loading_application_providers(self) -> None:
    code = main(["pathlight", "trace", "list", "--evidence-file", str(bundle)], entry_points=(FailIfLoadedEntryPoint(),), stdout=stdout, stderr=stderr)
    self.assertEqual(code, 0)
    self.assertEqual(json.loads(stdout.getvalue())[0]["trace_id"], TRACE_ID)

def test_cli_never_echoes_path_or_private_input_on_error(self) -> None:
    code = main(["pathlight", "trace", "show", "--evidence-file", "SENTINEL_PRIVATE_PATH", "--trace-id", TRACE_ID], stderr=stderr)
    self.assertEqual(code, 2)
    self.assertNotIn("SENTINEL_PRIVATE_PATH", stderr.getvalue())
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `uv run python -m unittest -v tests.test_pathlight_cli tests.test_asterion_cli.AsterionCliTests.test_parser_requires_subcommand`

Expected: FAIL because `pathlight` is not routed.

- [ ] **Step 3: Implement the isolated CLI module and route**

```python
if raw_argv[:1] == ["pathlight"]:
    from asterion.cli_pathlight import main as pathlight_main
    return pathlight_main(raw_argv[1:], stdout=stdout, stderr=stderr)
```

Every read command requires one or more explicit `--evidence-file`; evaluation commands require explicit `--evaluation-file`. `trace show/tail` require canonical UUIDv4 `--trace-id`; `tail --after-sequence` defaults to `0`. `metrics query` accepts only allowlisted metric name/status filters. `evaluate compare` accepts exact baseline/candidate evaluation SHA-256 values. Catch only Pathlight/workflow/argument/value errors at the CLI boundary, emit `asterion pathlight: request is invalid`, and never echo exception text, paths or parsed data.

- [ ] **Step 4: Document exact commands and security/cost boundary**

```text
uv run asterion pathlight trace list --evidence-file /absolute/operator/path/workflow-evidence.json
uv run asterion pathlight trace show --evidence-file /absolute/operator/path/workflow-evidence.json --trace-id <uuidv4>
uv run asterion pathlight trace tail --evidence-file /absolute/operator/path/workflow-evidence.json --trace-id <uuidv4> --after-sequence 0
uv run asterion pathlight metrics query --evaluation-file /absolute/operator/path/pathlight-evaluations.json
uv run asterion pathlight evaluate compare --evaluation-file /absolute/operator/path/pathlight-evaluations.json --baseline <sha256> --candidate <sha256>
```

State explicitly that these commands are provider-free, make no network/model calls, read only operator-selected public-safe records, and that `tail` reads the current immutable snapshot rather than polling or following a private store.

- [ ] **Step 5: Run stage verification**

Run: `uv run python -m unittest -v tests.test_pathlight_cli tests.test_pathlight_query tests.test_pathlight_evaluation tests.test_workflow_evidence_storage tests.test_asterion_cli`

Expected: PASS.

Run: `make lint && make docs-check && git diff --check`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/asterion/cli.py src/asterion/cli_pathlight.py src/asterion/pathlight docs/cli.md tests/test_pathlight_cli.py tests/test_asterion_cli.py
git commit -m "feat: expose Pathlight query CLI"
```

## Plan self-review

- **Spec coverage:** This plan covers stable safe read/query API, trace list/show/tail, metric query and exact evaluation comparison. Historical DCI recovery, diagnosis/proposal execution, Opik export and Dashboard remain separate downstream plans because each has an independent trust boundary and acceptance test.
- **Placeholder scan:** The plan contains no deferred implementation markers; every task names exact interfaces, tests, commands and commit boundary.
- **Type consistency:** Tasks 3–4 consume the exact immutable bundle and evaluation types defined in Tasks 1–2; comparisons use SHA-256 evaluation identities and integer microunits throughout.
