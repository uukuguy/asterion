# Pathlight Bright Optimization Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Pathlight's immutable optimization history and decision lifecycle, connect it to a single-variable Bright query-decomposition A/B adapter, and close one authorized 4×10 experiment with native traces and an evidence-backed decision.

**Architecture:** Generic Pathlight owns immutable `OptimizationTrial`, `TrialHistory`, `Decision`, storage, query, Dashboard, and Opik-safe projections. The DCI product owns the query-planning prompt resource, exact Bright plan/authorization/receipt coordinator, benchmark execution, nDCG projection, and Chinese report. External execution is a separately authorized final task after every provider-free gate passes.

**Tech Stack:** Python 3.14 dataclasses, canonical JSON, `unittest`, existing Pathlight Experiment/Evaluation/Diagnosis APIs, DCI benchmark host, Pi native workflow observation, operator-local HTML/CSS/JavaScript Dashboard.

## Global Constraints

- Preserve `CLI/host → selected provider → assembly → catalog/composer → exact implementations → runner → runtime/host services`.
- `src/asterion/pathlight/` must not import DCI modules, fields, paper semantics, prompts, or source trees.
- Do not modify `dci.agent-runtime/v1`, `dci.package/v1`, or `dci.assembly/v1`.
- Public values must not expose prompts, questions, answers, corpus text, tool/model payloads, credentials, provider configuration, actual descriptors, or private paths.
- Baseline and candidate use the same 40 selected cases, corpus, assembly, package set, implementation, runtime, model, tools, context policy, metric, parsing, turn limit, deadline, and per-case authority. Only the query-planning prompt contract may differ.
- The exact external ceiling is 80 Agent operations, 0 Judge operations, 8,000,000 microusd, one native attempt per case, and stop after two infrastructure failures.
- Existing evidence, `.env`, a plan, a Proposal, Dashboard, or Opik never grants execution authority.
- Execution is foreground and sequential. Observation failure cannot change benchmark result, retry, score, or cost, but incomplete closure cannot support `accepted`.
- All implementation tasks use RED → GREEN TDD. Do not execute Agent, Judge, provider, model, or network operations before Task 9's explicit authorization checkpoint.
- Preserve unrelated live changes in `docs/status/JOURNAL.md` and `docs/status/RESUME-NEXT-SESSION.md`; JOURNAL remains append-only.

---

## File Structure

- `src/asterion/pathlight/optimization.py`: generic immutable trial/history/decision/bundle values, validation, storage, closure validation, and read-only catalog.
- `src/asterion/pathlight/__init__.py`: public generic exports only.
- `src/asterion/cli_pathlight.py`: provider-free optimization history/decision/trial queries and file injection into Dashboard/Opik.
- `src/asterion/pathlight/dashboard.py`: optimization-aware immutable snapshot and reference closure.
- `src/asterion/pathlight/dashboard_server.py`: read-only optimization API routes.
- `src/asterion/pathlight/dashboard_assets/{index.html,app.js,styles.css}`: workflow-first optimization history and decision view.
- `src/asterion/pathlight/opik.py`: safe `trial-history.upsert` and `decision.observe` mappings.
- `src/asterion/pathlight/interop.py`: exact payload allowlists for those two already-reserved event kinds.
- `src/asterion/capabilities/dci/implementation/research/query_planning.py`: DCI-owned versioned candidate query-planning contract and private prompt materialization.
- `src/asterion/applications/dci_agent_lite/benchmark_executor.py`: exact optional prompt override on the existing real executor.
- `src/asterion/applications/dci_agent_lite/benchmark_host.py`: bind baseline/candidate prompt identity into the effective configuration and executor.
- `src/asterion/applications/dci_agent_lite/pathlight_optimization_cli.py`: DCI prepare/execute/resume/status/finalize coordinator.
- `src/asterion/applications/dci_agent_lite/pathlight_cli.py`: route `pathlight optimization` to the product coordinator.
- `src/asterion/capabilities/dci/implementation/pathlight/optimization.py`: DCI plan projection, trial/evaluation closure, decision, and Chinese renderer.
- `tests/test_pathlight_optimization.py`: generic contracts, closure, storage, catalog, and adversarial cases.
- `tests/test_pathlight_cli.py`: provider-free public CLI behavior and redaction.
- `tests/test_pathlight_dashboard.py`: snapshot/API/assets optimization closure and redaction.
- `tests/test_pathlight_opik.py`: deterministic safe optimization mapping.
- `tests/test_dci_query_planning.py`: exact DCI-only candidate contract and body-free public identity.
- `tests/test_dci_benchmark_real_executor.py`: prompt override and no-semantic-drift executor tests.
- `tests/test_dci_pathlight_optimization_cli.py`: product plan, authority, execution, resume, receipts, finalization, redaction, and provider-free commands.
- `tests/test_dci_pathlight_optimization.py`: DCI projection, decision, and Chinese report tests.
- `docs/status/PATHLIGHT-DCI-DIAGNOSIS.md`: current experiment state and final result.
- `docs/status/DCI-BENCHMARK-INSTANCES.md`: executable commands, scope, actual cost, and Decision.

---

### Task 1: Define Immutable Optimization Contracts and Storage

**Files:**
- Create: `src/asterion/pathlight/optimization.py`
- Modify: `src/asterion/pathlight/__init__.py`
- Create: `tests/test_pathlight_optimization.py`

**Interfaces:**
- Consumes: `ExperimentBundle`, `ExperimentPlan`, `CaseTrial`, `EvaluationBundle`, `EvaluationRecord`, `DiagnosisBundle`, verified workflow trace SHA-256 values, `_private_file` helpers.
- Produces: `OptimizationCriteria`, `OptimizationTrial`, `TrialHistory`, `Decision`, `OptimizationBundle`, `OptimizationCatalog`, `validate_optimization_criteria()`, `validate_optimization_trial()`, `validate_trial_history()`, `validate_decision()`, `validate_optimization_bundle()`, `write_optimization_bundle()`, `read_optimization_bundle()`, and `validate_optimization_closure()`.

- [ ] **Step 1: Write RED tests for canonical trials and adversarial mappings**

```python
class TestOptimizationContracts(unittest.TestCase):
    def test_trial_is_body_free_canonical_and_content_addressed(self) -> None:
        trial = _trial(role="baseline", item="case-1", value=400_000)
        self.assertEqual(validate_optimization_trial(trial.to_mapping()), trial)
        encoded = json.dumps(trial.to_mapping(), sort_keys=True)
        self.assertNotIn("SENTINEL_QUESTION", encoded)
        self.assertRegex(trial.optimization_trial_sha256, r"^[0-9a-f]{64}$")

    def test_trial_rejects_bool_usage_unknown_fields_and_failed_score(self) -> None:
        for mutate in (_bool_tokens, _unknown_field, _failed_with_evaluation):
            with self.subTest(mutate=mutate.__name__):
                value = mutate(_trial_mapping())
                with self.assertRaisesRegex(PathlightError, "optimization trial is invalid"):
                    validate_optimization_trial(value)
```

- [ ] **Step 2: Run the Task 1 contract RED test**

Run:

```bash
uv run python -m unittest -v tests.test_pathlight_optimization.TestOptimizationContracts
```

Expected: FAIL because `asterion.pathlight.optimization` does not exist.

- [ ] **Step 3: Implement exact primitive values and decision criteria**

Use frozen, slotted dataclasses and exact `type(...)` validation. The public signatures are:

```python
DecisionResult = Literal["accepted", "rejected", "inconclusive"]
TrialStatus = Literal["completed", "failed", "cancelled"]
VariantRole = Literal["baseline", "candidate"]

@dataclass(frozen=True, slots=True)
class OptimizationCriteria:
    minimum_mean_gain_microunits: int
    maximum_cost_increase_microunits: int
    maximum_time_increase_microunits: int
    success_criteria_sha256: str = field(init=False)

@dataclass(frozen=True, slots=True)
class OptimizationTrial:
    experiment_plan_sha256: str
    case_trial_sha256: str
    dataset_item_sha256: str
    variant_role: VariantRole
    variant_sha256: str
    trace_sha256: str | None
    evaluation_sha256: str | None
    status: TrialStatus
    failure_category: str | None
    agent_cost_microusd: int
    input_tokens: int
    output_tokens: int
    elapsed_ns: int
    optimization_trial_sha256: str = field(init=False)
```

Allowed failure categories are the existing closed Pathlight categories. Completed trials require trace and evaluation digests; failed/cancelled trials require both to be `None` unless an actually completed evaluation exists before cancellation, in which case the finalizer must normalize the trial to completed rather than invent a partial score.

- [ ] **Step 4: Write RED tests for paired history and all three decisions**

```python
def test_history_pairs_every_item_and_decision_is_derived(self) -> None:
    closure = _complete_closure(
        baseline_values=(400_000, 500_000),
        candidate_values=(500_000, 550_000),
        baseline_cost=100,
        candidate_cost=120,
        baseline_time=1_000,
        candidate_time=1_100,
    )
    history = TrialHistory.build(**closure.history_inputs)
    decision = Decision.derive(
        proposal_sha256=_sha("proposal"),
        finding_sha256=_sha("finding"),
        history=history,
        criteria=OptimizationCriteria(50_000, 250_000, 250_000),
        operator_approval_sha256=_sha("approval"),
    )
    self.assertEqual(decision.result, "accepted")

def test_incomplete_history_can_only_be_inconclusive(self) -> None:
    history = TrialHistory.build(**_missing_candidate_closure().history_inputs)
    self.assertEqual(_derive(history).result, "inconclusive")

def test_complete_but_below_threshold_is_rejected(self) -> None:
    history = TrialHistory.build(**_complete_closure(candidate_values=(401_000, 499_000)).history_inputs)
    self.assertEqual(_derive(history).result, "rejected")
```

- [ ] **Step 5: Run the history/decision RED tests**

Run:

```bash
uv run python -m unittest -v \
  tests.test_pathlight_optimization.TestTrialHistory \
  tests.test_pathlight_optimization.TestDecision
```

Expected: FAIL because history and decision APIs do not exist.

- [ ] **Step 6: Implement paired history, ratio semantics, and derived Decision**

`TrialHistory.build()` accepts an exact ExperimentPlan, baseline/candidate Variants, ordered trials, Evaluation records, and the expected sorted item digests. It validates one baseline and one candidate per item. Aggregate means use integer numerator/count with deterministic half-even rounding to microunits. Relative increase is:

```python
def _relative_increase_microunits(baseline: int, candidate: int) -> int:
    if baseline == 0:
        return 0 if candidate == 0 else 1_000_001
    return ((candidate - baseline) * 1_000_000) // baseline
```

Negative increases remain negative. Decision reason enums are `quality-and-efficiency-met`, `quality-threshold-missed`, `cost-threshold-exceeded`, `time-threshold-exceeded`, `multiple-thresholds-missed`, `incomplete-trials`, `comparison-invalid`, and `evidence-closure-invalid`.

- [ ] **Step 7: Write RED tests for bundle closure, private storage, and catalog**

```python
def test_bundle_round_trip_requires_internal_and_external_closure(self) -> None:
    bundle, dependencies = _optimization_bundle()
    write_optimization_bundle(self.root / "pathlight-optimization.json", bundle)
    loaded = read_optimization_bundle(self.root / "pathlight-optimization.json")
    validate_optimization_closure(loaded, **dependencies)
    self.assertEqual(loaded, bundle)

def test_catalog_lists_trials_without_private_content(self) -> None:
    catalog = OptimizationCatalog.build((_optimization_bundle()[0],))
    values = catalog.list_trials(_history_sha(), variant_role="candidate")
    self.assertEqual(len(values), 2)
    self.assertNotIn("SENTINEL", json.dumps(values))
```

Add symlink, FIFO, mode 0644, owner mismatch, conflict rewrite, duplicate digest, unknown external reference, noncanonical ordering, and bool-as-int subtests.

- [ ] **Step 8: Run storage RED, implement bundle/store/catalog, and run GREEN**

Run RED first, then implement `asterion.pathlight-optimization/v1`, fixed basename `pathlight-optimization.json`, one-megabyte bound, canonical digest, 0600 file rules, exact external closure validation, and catalog methods `show_history()`, `show_decision()`, `list_trials()`.

Run GREEN:

```bash
uv run python -m unittest -v tests.test_pathlight_optimization
uv run pyright src/asterion/pathlight/optimization.py tests/test_pathlight_optimization.py
uv run ruff check src/asterion/pathlight/optimization.py src/asterion/pathlight/__init__.py tests/test_pathlight_optimization.py
```

Expected: all tests PASS, Pyright 0 errors, Ruff PASS.

- [ ] **Step 9: Commit Task 1**

```bash
git add src/asterion/pathlight/optimization.py src/asterion/pathlight/__init__.py tests/test_pathlight_optimization.py
git commit -m "feat: add Pathlight optimization decisions"
```

---

### Task 2: Add Provider-Free Optimization CLI and Opik Mapping

**Files:**
- Modify: `src/asterion/cli_pathlight.py`
- Modify: `src/asterion/pathlight/opik.py`
- Modify: `src/asterion/pathlight/interop.py`
- Modify: `tests/test_pathlight_cli.py`
- Modify: `tests/test_pathlight_opik.py`

**Interfaces:**
- Consumes: Task 1 readers and `OptimizationCatalog`; existing `map_opik_exports()`.
- Produces: `optimization history`, `optimization decision`, `optimization trials`; optional `--optimization-file` for `export opik`; safe trial-history and decision envelopes.

- [ ] **Step 1: Write CLI RED tests**

```python
def test_optimization_commands_are_provider_free_canonical_json(self) -> None:
    with patch("asterion.cli_pathlight._provider_should_not_load", create=True) as provider:
        for argv in (
            ["optimization", "history", "--optimization-file", str(self.file), "--history", self.history],
            ["optimization", "decision", "--optimization-file", str(self.file), "--decision", self.decision],
            ["optimization", "trials", "--optimization-file", str(self.file), "--history", self.history, "--variant-role", "candidate"],
        ):
            with self.subTest(argv=argv):
                self.assertEqual(main(argv, stdout=self.stdout, stderr=self.stderr), 0)
        provider.assert_not_called()
```

Add wrong basename, relative path, unknown digest, invalid role, extra option, and sentinel-output tests.

- [ ] **Step 2: Run CLI RED**

```bash
uv run python -m unittest -v tests.test_pathlight_cli.TestPathlightOptimizationCli
```

Expected: FAIL because `optimization` is not a command.

- [ ] **Step 3: Implement exact CLI parser and dispatch**

Add `_add_optimization_file()` requiring one absolute `pathlight-optimization.json`. Do not add a generic execute command. Return only Task 1 `to_mapping()` projections.

- [ ] **Step 4: Write Opik RED tests and fill reserved event allowlists**

```python
def test_mapping_emits_safe_history_and_decision_envelopes(self) -> None:
    envelopes = map_opik_exports(
        traces=self.traces,
        experiments=self.experiments,
        evaluations=self.evaluations,
        diagnoses=self.diagnoses,
        optimizations=(self.optimization,),
    )
    kinds = {item.event_kind for item in envelopes}
    self.assertIn("trial-history.upsert", kinds)
    self.assertIn("decision.observe", kinds)
    self.assertNotIn("SENTINEL", json.dumps([item.to_mapping() for item in envelopes]))
```

The `trial-history.upsert` allowlist contains only history/plan/variant digests, evidence state, completed counts, aggregate microunits, cost/token/time integers, and criteria digest. `decision.observe` contains decision/history/proposal/finding/criteria/operator-approval digests, result, and reason enum. Extend `_SAFE_INTEGER_FIELDS`, `_DIGEST_PAYLOAD_FIELDS`, and `_SAFE_STRING_VALUES` only with these exact safe values.

- [ ] **Step 5: Run Opik RED, implement closure mapping, and run Task 2 GREEN**

`map_opik_exports()` must validate optimization references against supplied traces, experiment bundles, evaluation bundles, and diagnoses before emitting envelopes. Duplicate or missing closure fails the entire mapping.

```bash
uv run python -m unittest -v tests.test_pathlight_cli tests.test_pathlight_opik tests.test_pathlight_interop
uv run pyright src/asterion/cli_pathlight.py src/asterion/pathlight/opik.py src/asterion/pathlight/interop.py
uv run ruff check src/asterion/cli_pathlight.py src/asterion/pathlight/opik.py src/asterion/pathlight/interop.py tests/test_pathlight_cli.py tests/test_pathlight_opik.py
```

Expected: PASS with no provider/network operation.

- [ ] **Step 6: Commit Task 2**

```bash
git add src/asterion/cli_pathlight.py src/asterion/pathlight/opik.py src/asterion/pathlight/interop.py tests/test_pathlight_cli.py tests/test_pathlight_opik.py
git commit -m "feat: query and mirror Pathlight optimization"
```

---

### Task 3: Extend the Read-Only Dashboard with Optimization History

**Files:**
- Modify: `src/asterion/pathlight/dashboard.py`
- Modify: `src/asterion/pathlight/dashboard_server.py`
- Modify: `src/asterion/pathlight/dashboard_assets/index.html`
- Modify: `src/asterion/pathlight/dashboard_assets/app.js`
- Modify: `src/asterion/pathlight/dashboard_assets/styles.css`
- Modify: `src/asterion/cli_pathlight.py`
- Modify: `tests/test_pathlight_dashboard.py`
- Modify: `tests/test_pathlight_cli.py`

**Interfaces:**
- Consumes: verified OptimizationBundle plus its workflow/experiment/evaluation/diagnosis closure.
- Produces: `DashboardSnapshot.optimizations`, summary counts, GET endpoints `/api/optimizations`, `/api/optimizations/history/<sha256>`, `/api/optimizations/decision/<sha256>`, and workflow-first UI links.

- [ ] **Step 1: Write snapshot and closure RED tests**

```python
def test_snapshot_closes_optimization_to_trial_traces_and_decision(self) -> None:
    snapshot = DashboardSnapshot.build(
        workflow_bundles=self.workflow,
        evaluation_bundles=self.evaluations,
        experiment_bundles=self.experiments,
        diagnosis_bundles=self.diagnoses,
        optimization_bundles=(self.optimization,),
    )
    self.assertEqual(snapshot.summary["optimization_history_count"], 1)
    self.assertEqual(snapshot.summary["decision_counts"]["accepted"], 1)

def test_snapshot_rejects_missing_trial_trace(self) -> None:
    with self.assertRaisesRegex(PathlightError, "Dashboard snapshot is invalid"):
        DashboardSnapshot.build(
            evaluation_bundles=self.evaluations,
            experiment_bundles=self.experiments,
            diagnosis_bundles=self.diagnoses,
            optimization_bundles=(self.optimization,),
        )
```

- [ ] **Step 2: Run Dashboard RED**

```bash
uv run python -m unittest -v tests.test_pathlight_dashboard.TestOptimizationDashboard
```

Expected: FAIL because DashboardSnapshot has no optimization input.

- [ ] **Step 3: Implement snapshot fields, deterministic summary, and API routes**

Increment `DASHBOARD_SNAPSHOT_SCHEMA` to `asterion.pathlight-dashboard-snapshot/v2`; reject v1/v2 mixing rather than silently guessing. Add exact summary counts for histories and all three decisions. Preserve loopback-only GET/HEAD and 405 for writes.

- [ ] **Step 4: Write asset RED tests before editing assets**

```python
def test_assets_render_decision_thresholds_and_trace_drilldown_without_private_values(self) -> None:
    app = _dashboard_app(self.snapshot)
    html = app.dispatch("GET", "/").body.decode()
    script = app.dispatch("GET", "/assets/app.js").body.decode()
    self.assertIn("Optimization decision", html)
    self.assertIn("trial_history_sha256", script)
    self.assertIn("trace_sha256", script)
    self.assertNotIn("SENTINEL_PRIVATE", html + script)
```

- [ ] **Step 5: Implement workflow-first UI**

The first panel remains trace flow. Add a decision summary, paired baseline/candidate table per dataset digest, criteria/actual comparison, incomplete evidence warning, and links from every completed trial to its existing trace flow. Do not add browser storage, CDN, remote fonts, analytics, POST, or execution controls.

- [ ] **Step 6: Add `--optimization-file` to dashboard CLI and run GREEN**

```bash
uv run python -m unittest -v tests.test_pathlight_dashboard tests.test_pathlight_cli
uv run pyright src/asterion/pathlight/dashboard.py src/asterion/pathlight/dashboard_server.py src/asterion/cli_pathlight.py
uv run ruff check src/asterion/pathlight/dashboard.py src/asterion/pathlight/dashboard_server.py src/asterion/cli_pathlight.py tests/test_pathlight_dashboard.py tests/test_pathlight_cli.py
```

Expected: PASS; snapshot/API/assets contain no sentinel values.

- [ ] **Step 7: Commit Task 3**

```bash
git add src/asterion/pathlight/dashboard.py src/asterion/pathlight/dashboard_server.py src/asterion/pathlight/dashboard_assets src/asterion/cli_pathlight.py tests/test_pathlight_dashboard.py tests/test_pathlight_cli.py
git commit -m "feat: show Pathlight optimization decisions"
```

---

### Task 4: Implement the DCI Query-Planning Sole Variable

**Files:**
- Create: `src/asterion/capabilities/dci/implementation/research/query_planning.py`
- Modify: `src/asterion/capabilities/dci/implementation/research/__init__.py`
- Modify: `src/asterion/applications/dci_agent_lite/benchmark_executor.py`
- Modify: `src/asterion/applications/dci_agent_lite/benchmark_host.py`
- Modify: `src/asterion/capabilities/dci/implementation/_provenance.py`
- Modify: `src/asterion/capabilities/dci/implementation/reproduction/provenance.py`
- Create: `tests/test_dci_query_planning.py`
- Modify: `tests/test_dci_benchmark_real_executor.py`
- Modify: `tests/test_dci_benchmark_host.py`
- Modify: `tests/test_check_promotion.py`

**Interfaces:**
- Consumes: existing Asterion-safe Pi Bright IR prompt, `BenchmarkRequest.append_system_prompt_file`, and private file helpers.
- Produces: `BASELINE_QUERY_PLAN`, `DECOMPOSED_QUERY_PLAN`, `QueryPlanningContract`, `query_planning_contract_sha256()`, `materialize_query_planning_prompt()`, and an exact optional host/executor query-plan binding.

- [ ] **Step 1: Write query-planning RED tests**

```python
def test_candidate_contract_is_exact_and_public_identity_is_body_free(self) -> None:
    baseline = resolve_query_planning_contract(BASELINE_QUERY_PLAN)
    candidate = resolve_query_planning_contract(DECOMPOSED_QUERY_PLAN)
    self.assertNotEqual(
        query_planning_contract_sha256(baseline),
        query_planning_contract_sha256(candidate),
    )
    public = candidate.public_identity()
    self.assertNotIn("SENTINEL_PROMPT_BODY", json.dumps(public))

def test_private_candidate_prompt_requires_0700_root_and_writes_0400(self) -> None:
    path = materialize_query_planning_prompt(DECOMPOSED_QUERY_PLAN, self.root)
    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o400)
    self.assertEqual(path.parent, self.root)
```

Also assert the candidate encodes entity/concept/relation/constraint decomposition, separate search rounds, merge/deduplicate/validate/rerank, and no web/subagent expansion. These assertions stay inside DCI tests; no body enters public mappings.

- [ ] **Step 2: Run query-planning RED**

```bash
uv run python -m unittest -v tests.test_dci_query_planning
```

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement the DCI-only contract and private materializer**

```python
@dataclass(frozen=True, slots=True)
class QueryPlanningContract:
    contract_id: str
    _append_system_prompt: str = field(repr=False, compare=False)

    def public_identity(self) -> dict[str, str]:
        return {
            "contract_id": self.contract_id,
            "contract_sha256": query_planning_contract_sha256(self),
        }
```

The materialized file name is digest-derived and fixed under a supplied 0700 operator root. Existing identical 0400 bytes are idempotent; any conflict fails.

- [ ] **Step 4: Write executor/host RED tests for one-variable injection**

```python
def test_candidate_executor_only_adds_exact_prompt_override(self) -> None:
    baseline_request = self.run_executor(query_plan=BASELINE_QUERY_PLAN)
    candidate_request = self.run_executor(query_plan=DECOMPOSED_QUERY_PLAN)
    self.assertIsNone(baseline_request.append_system_prompt_file)
    self.assertEqual(candidate_request.append_system_prompt_file, self.candidate_file)
    self.assertEqual(_request_without_prompt(baseline_request), _request_without_prompt(candidate_request))

def test_effective_digest_changes_only_with_query_plan_contract(self) -> None:
    baseline = optimization_execution_config_sha256(self.environment, BASELINE_QUERY_PLAN)
    candidate = optimization_execution_config_sha256(self.environment, DECOMPOSED_QUERY_PLAN)
    self.assertNotEqual(baseline, candidate)
```

- [ ] **Step 5: Implement exact host/executor binding**

Add a closed `query_planning_contract` constructor argument to `RealDciBenchmarkExecutor` and `DciBenchmarkHost`, defaulting to baseline so existing commands do not change. Candidate construction requires an already materialized 0400 file plus matching content digest. Pass the path only into `BenchmarkRequest.append_system_prompt_file`. Include contract digest, not path/body, in `optimization_execution_config_sha256()`.

- [ ] **Step 6: Run Task 4 GREEN and promotion-focused checks**

```bash
uv run python -m unittest -v \
  tests.test_dci_query_planning \
  tests.test_dci_benchmark_real_executor \
  tests.test_dci_benchmark_host \
  tests.test_dci_reproduction \
  tests.test_dci_provenance \
  tests.test_check_promotion
uv run pyright \
  src/asterion/capabilities/dci/implementation/research/query_planning.py \
  src/asterion/applications/dci_agent_lite/benchmark_executor.py \
  src/asterion/applications/dci_agent_lite/benchmark_host.py
uv run ruff check \
  src/asterion/capabilities/dci/implementation/research/query_planning.py \
  src/asterion/applications/dci_agent_lite/benchmark_executor.py \
  src/asterion/applications/dci_agent_lite/benchmark_host.py \
  tests/test_dci_query_planning.py
```

Expected: PASS; baseline behavior and packaged provenance remain exact.

- [ ] **Step 7: Commit Task 4**

```bash
git add src/asterion/capabilities/dci/implementation/research src/asterion/applications/dci_agent_lite/benchmark_executor.py src/asterion/applications/dci_agent_lite/benchmark_host.py src/asterion/capabilities/dci/implementation/_provenance.py src/asterion/capabilities/dci/implementation/reproduction/provenance.py tests/test_dci_query_planning.py tests/test_dci_benchmark_real_executor.py tests/test_dci_benchmark_host.py tests/test_check_promotion.py
git commit -m "feat: add DCI query planning variant"
```

---

### Task 5: Prepare and Authorize the Exact Bright A/B Plan

**Files:**
- Create: `src/asterion/applications/dci_agent_lite/pathlight_optimization_cli.py`
- Modify: `src/asterion/applications/dci_agent_lite/pathlight_cli.py`
- Create: `tests/test_dci_pathlight_optimization_cli.py`

**Interfaces:**
- Consumes: exact `retrieval-query-decomposition` Proposal, coverage-completed diagnosis, Task 4 query plans, source-lock API, DCI operator config, four Bright instances.
- Produces: `prepare`, `status`, strict plan and authorization readers, private plan tree, source lock, candidate prompt file, and public-safe summaries.

- [ ] **Step 1: Write prepare RED tests**

```python
def test_prepare_builds_exact_4x10_unexecuted_plan(self) -> None:
    code, output = self.run_prepare()
    self.assertEqual(code, 0)
    self.assertEqual(output["dataset_count"], 4)
    self.assertEqual(output["case_count"], 40)
    self.assertEqual(output["max_agent_operations"], 80)
    self.assertEqual(output["max_judge_operations"], 0)
    self.assertEqual(output["max_cost_microusd"], 8_000_000)
    self.assertFalse(_read_plan(self.plan)["execution_authorized"])
    self.provider.assert_not_called()
```

Add tests for wrong Proposal, coverage gate not ready, wrong four scopes, selected-ID drift, same baseline/candidate digest, dirty/non-0700 root, source ambiguity, prompt materialization conflict, and public sentinel redaction.

- [ ] **Step 2: Run prepare RED**

```bash
uv run python -m unittest -v tests.test_dci_pathlight_optimization_cli.TestPrepare
```

Expected: FAIL because the coordinator does not exist.

- [ ] **Step 3: Implement private plan tree and exact plan schema**

The fixed plan fields are:

```python
{
    "schema": "asterion.dci.pathlight.bright-optimization-plan/v1",
    "diagnosis_bundle_sha256": sha,
    "authorization_gate_report_sha256": sha,
    "proposal_sha256": sha,
    "finding_sha256": sha,
    "scope_sha256": sha,
    "source_lock_sha256": sha,
    "selected_case_scope_sha256": sha,
    "baseline_variant_sha256": sha,
    "candidate_variant_sha256": sha,
    "baseline_execution_config_sha256": sha,
    "candidate_execution_config_sha256": sha,
    "success_criteria_sha256": sha,
    "stop_criteria_sha256": sha,
    "budget_sha256": sha,
    "max_agent_operations": 80,
    "max_judge_operations": 0,
    "max_cost_microusd": 8_000_000,
    "max_infrastructure_failures": 2,
    "execution_authorized": False,
    "tasks": [
        {"task_key": "bright.biology/baseline"},
        {"task_key": "bright.biology/candidate"},
        {"task_key": "bright.earth-science/baseline"},
        {"task_key": "bright.earth-science/candidate"},
        {"task_key": "bright.economics/baseline"},
        {"task_key": "bright.economics/candidate"},
        {"task_key": "bright.robotics/baseline"},
        {"task_key": "bright.robotics/candidate"},
    ],
    "plan_sha256": sha,
}
```

`authorization_gate_report_sha256` is the digest of the DCI-owned private
`pathlight-dci-authorization-gate.json` emitted atomically by a real
coverage-complete `DciDiagnosisReport`.  `prepare` takes the report through
the exact `--gate-report-file` option, requires its canonical absolute
basename and mode-0600 descriptor boundary, and closes its diagnosis,
proposal, and scope identities before writing the inactive plan.  The report
contains only fixed enums, counts, and opaque coverage plan/receipt/evidence
digests; it never includes prompt, case, path, provider, or payload content.

Each task fixes dataset ID, instance selector, role, query-plan digest, 10 selected IDs, case-limit 10, one native attempt, zero Judge, task cost ceiling 1,000,000 microusd, and relative evidence/receipt locations. Publish with private staging and cleanup copied from the hardened coverage coordinator, without importing DCI helpers into generic Pathlight.

- [ ] **Step 4: Write strict authorization and status RED tests**

```python
def test_authorization_binds_every_execution_boundary(self) -> None:
    authorization = _signed_authorization(self.plan)
    value = read_optimization_authorization(authorization, plan=_read_plan(self.plan))
    self.assertTrue(value["execution_authorized"])
    self.assertEqual(value["max_agent_operations"], 80)
    self.assertEqual(value["max_judge_operations"], 0)

def test_status_is_provider_free_and_reports_zero_before_execution(self) -> None:
    code, output = self.run_status()
    self.assertEqual((code, output["completed_agent_operations"]), (0, 0))
    self.provider.assert_not_called()
```

Mutation subtests cover every authorization field, output root device/inode, plan digest, operator approval digest, 0600 mode, wrong owner/symlink/FIFO, bool integers, stale execution config, and extra fields.

- [ ] **Step 5: Implement exact authorization reader and provider-free status**

Authorization schema is `asterion.dci.pathlight.bright-optimization-authorization/v1`; it contains every plan boundary plus output root device/inode, `execution_authorized=true`, operator approval digest, and its own canonical digest. It is read-only input; code never creates operator approval.

- [ ] **Step 6: Run Task 5 GREEN**

```bash
uv run python -m unittest -v tests.test_dci_pathlight_optimization_cli.TestPrepare tests.test_dci_pathlight_optimization_cli.TestAuthorization tests.test_dci_pathlight_optimization_cli.TestStatus
uv run pyright src/asterion/applications/dci_agent_lite/pathlight_optimization_cli.py tests/test_dci_pathlight_optimization_cli.py
uv run ruff check src/asterion/applications/dci_agent_lite/pathlight_optimization_cli.py src/asterion/applications/dci_agent_lite/pathlight_cli.py tests/test_dci_pathlight_optimization_cli.py
```

Expected: PASS with provider operation count zero.

- [ ] **Step 7: Commit Task 5**

```bash
git add src/asterion/applications/dci_agent_lite/pathlight_optimization_cli.py src/asterion/applications/dci_agent_lite/pathlight_cli.py tests/test_dci_pathlight_optimization_cli.py
git commit -m "feat: prepare bounded Bright optimization"
```

---

### Task 6: Execute, Stop, and Resume with Immutable Receipts

**Files:**
- Modify: `src/asterion/applications/dci_agent_lite/pathlight_optimization_cli.py`
- Modify: `tests/test_dci_pathlight_optimization_cli.py`

**Interfaces:**
- Consumes: Task 5 plan/authorization, existing `BenchmarkCommandHost`, fresh per-task evidence roots, Task 4 query-plan binding.
- Produces: foreground `execute` and `resume`, immutable hash-chained receipts, exact cost reconciliation, and safe terminal status.

- [ ] **Step 1: Write execution RED test using the real host boundary with a fake executor**

```python
def test_execute_runs_eight_batches_sequentially_once(self) -> None:
    host_factory = RecordingHostFactory(results=_eight_completed_results())
    code, output = self.run_execute(host_factory=host_factory)
    self.assertEqual(code, 0)
    self.assertEqual(output["completed_agent_operations"], 80)
    self.assertEqual(output["judge_operations"], 0)
    self.assertEqual(host_factory.order, _expected_dataset_variant_order())
    self.assertTrue(all(call.max_native_attempts == 1 for call in host_factory.calls))
```

The fake executor returns native benchmark summaries and workflow/evaluation artifacts with the same shapes as the real host; it does not bypass plan, provider loading, or receipt validation interfaces.

- [ ] **Step 2: Run execution RED**

```bash
uv run python -m unittest -v tests.test_dci_pathlight_optimization_cli.TestExecute
```

Expected: FAIL because execute/resume are absent.

- [ ] **Step 3: Implement all-task preflight and sequential execution**

Before creating any loaded providers, resolve and revalidate all eight batches, source lock, selected IDs, query-plan files, execution digests, budget, output identity, and existing receipt chain. Then create per-task host values with exact remaining Decimal budget and one native attempt. No concurrent task promises are allowed.

- [ ] **Step 4: Write RED tests for failures, stopping, cost, and resume**

```python
def test_two_infrastructure_failures_stop_before_third_failed_batch(self) -> None:
    factory = RecordingHostFactory(results=[_network_failure(), _auth_failure(), _completed()])
    code, output = self.run_execute(host_factory=factory)
    self.assertEqual(code, 1)
    self.assertEqual(output["infrastructure_failures"], 2)
    self.assertEqual(len(factory.calls), 2)

def test_resume_never_replays_completed_trials(self) -> None:
    self.run_execute(host_factory=RecordingHostFactory(results=_first_three_then_cancel()))
    factory = RecordingHostFactory(results=_remaining_five())
    self.run_resume(host_factory=factory)
    self.assertEqual([call.task_key for call in factory.calls], _expected_task_keys()[3:])
```

Add subtests for model business failure (terminal trial, no retry), cancellation, observation failure, upper-bound versus actual cost, overspend, exhausted task budget, partial/forged/reordered receipt, plan/root drift, source mutation, candidate prompt conflict, resume after terminal completion, and unknown failure class.

- [ ] **Step 5: Implement receipt chain and stop semantics**

Receipt schema `asterion.dci.pathlight.bright-optimization-receipt/v1` includes plan/authorization/task digests, previous receipt digest, run ID digest, status, completed case count, actual or conservative cost evidence, input/output tokens, elapsed ns, native workflow/evaluation bundle digests, failure category, and receipt digest. Never store raw run ID, case ID, path, prompt, output, or provider payload in the public-safe receipt projection.

Model business failure records the affected case/batch terminally and does not increment infrastructure failures. Infrastructure categories are authorization, network, rate-limit, timeout, and host-service. Observation closure failure records a benchmark-completed receipt plus `observation-invalid` evidence state; it prevents acceptance during finalize.

- [ ] **Step 6: Run Task 6 GREEN**

```bash
uv run python -m unittest -v tests.test_dci_pathlight_optimization_cli
uv run pyright src/asterion/applications/dci_agent_lite/pathlight_optimization_cli.py tests/test_dci_pathlight_optimization_cli.py
uv run ruff check src/asterion/applications/dci_agent_lite/pathlight_optimization_cli.py tests/test_dci_pathlight_optimization_cli.py
```

Expected: PASS; call count never exceeds 80 and Judge count remains zero.

- [ ] **Step 7: Commit Task 6**

```bash
git add src/asterion/applications/dci_agent_lite/pathlight_optimization_cli.py tests/test_dci_pathlight_optimization_cli.py
git commit -m "feat: execute bounded Bright optimization"
```

---

### Task 7: Finalize Native Trials into Evaluation, Decision, and Chinese Diagnosis

**Files:**
- Create: `src/asterion/capabilities/dci/implementation/pathlight/optimization.py`
- Modify: `src/asterion/capabilities/dci/implementation/pathlight/__init__.py`
- Modify: `src/asterion/applications/dci_agent_lite/pathlight_optimization_cli.py`
- Create: `tests/test_dci_pathlight_optimization.py`
- Modify: `tests/test_dci_pathlight_optimization_cli.py`

**Interfaces:**
- Consumes: verified plan/authorization/receipts, native workflow bundles, DCI benchmark result/evaluation artifacts, original DiagnosisBundle.
- Produces: composite 40-case ExperimentBundle, 80 CaseTrials/Evaluations, OptimizationBundle, updated DiagnosisBundle, and `pathlight-bright-optimization.zh-CN.md`.

- [ ] **Step 1: Write projection RED tests**

```python
def test_finalize_builds_80_native_trials_and_derived_decision(self) -> None:
    closure = finalize_bright_optimization(_completed_native_inputs())
    self.assertEqual(len(closure.optimization.trials), 80)
    self.assertEqual(len(closure.experiment.trials), 80)
    self.assertEqual(closure.optimization.decisions[0].result, "accepted")
    validate_optimization_closure(
        closure.optimization,
        workflow_bundles=closure.workflow_bundles,
        experiment_bundles=(closure.experiment,),
        evaluation_bundles=(closure.evaluations,),
        diagnosis_bundles=(closure.diagnosis,),
    )
```

Add rejected, incomplete/inconclusive, one dataset regression, local request-only evidence gaps, missing trace, wrong nDCG metric, wrong selected item, duplicate trial, mismatched baseline/candidate case, untrusted cost/time, and sentinel tests.

- [ ] **Step 2: Run projection RED**

```bash
uv run python -m unittest -v tests.test_dci_pathlight_optimization
```

Expected: FAIL because the DCI finalizer does not exist.

- [ ] **Step 3: Implement DCI-specific projection and criteria binding**

Build one composite 40-item DatasetSnapshot and one ExperimentPlan containing baseline/candidate Variants. Include four dataset-specific snapshots and evaluation records so the report and Dashboard retain per-dataset results. Every completed CaseTrial links one native trace and one case-level nDCG@10 Evaluation. The global history derives from exactly those 80 trials and the Proposal's `50_000/250_000/250_000` criteria.

Do not treat `model-request-boundary` or an honest compaction request-only local gap as missing task evidence when the native trace, benchmark score, total cost, and elapsed time are otherwise closed. Missing native workflow bundle, evaluation, trusted cost, or trusted elapsed time makes the Decision inconclusive.

- [ ] **Step 4: Write Chinese renderer RED tests**

```python
def test_chinese_report_states_scope_reference_and_decision_without_causality(self) -> None:
    report = render_bright_optimization_chinese(_rejected_closure())
    self.assertIn("40 条基线 + 40 条候选", report)
    self.assertIn("rejected", report)
    self.assertIn("不能作为论文复现", report)
    self.assertNotIn("查询分解导致", report)
    self.assertNotIn("SENTINEL", report)
```

The report includes each dataset's baseline/candidate mean and delta, total cost/time and increase, completed/failed/cancelled counts, evidence gaps, Decision/reason, full historical Bright score and paper reference as explicitly non-comparable context, and the smallest next proposal.

- [ ] **Step 5: Implement provider-free idempotent finalize and atomic publication**

`finalize` reads no `.env` provider key and constructs no host. It writes `pathlight-experiment.json`, `pathlight-evaluations.json`, `pathlight-optimization.json`, `pathlight-diagnosis.json`, and the Chinese report through private staging. Existing identical outputs return the same digests; any conflict rejects the whole operation without partial publication.

- [ ] **Step 6: Run Task 7 GREEN**

```bash
uv run python -m unittest -v tests.test_dci_pathlight_optimization tests.test_dci_pathlight_optimization_cli
uv run pyright src/asterion/capabilities/dci/implementation/pathlight/optimization.py src/asterion/applications/dci_agent_lite/pathlight_optimization_cli.py
uv run ruff check src/asterion/capabilities/dci/implementation/pathlight/optimization.py src/asterion/applications/dci_agent_lite/pathlight_optimization_cli.py tests/test_dci_pathlight_optimization.py tests/test_dci_pathlight_optimization_cli.py
```

Expected: PASS with no provider/network operations.

- [ ] **Step 7: Commit Task 7**

```bash
git add src/asterion/capabilities/dci/implementation/pathlight/optimization.py src/asterion/capabilities/dci/implementation/pathlight/__init__.py src/asterion/applications/dci_agent_lite/pathlight_optimization_cli.py tests/test_dci_pathlight_optimization.py tests/test_dci_pathlight_optimization_cli.py
git commit -m "feat: finalize Bright optimization decisions"
```

---

### Task 8: Close Provider-Free Verification, Documentation, and Review

**Files:**
- Modify: `docs/status/PATHLIGHT-DCI-DIAGNOSIS.md`
- Modify: `docs/status/DCI-BENCHMARK-INSTANCES.md`
- Modify: `docs/superpowers/specs/2026-08-02-asterion-pathlight-design.md`
- Update as durable live state without adding to the task commit: `docs/status/JOURNAL.md`
- Update as durable live state without adding to the task commit: `docs/status/RESUME-NEXT-SESSION.md`
- Modify tests only if a gate exposes an actual defect.

**Interfaces:**
- Consumes: Tasks 1–7 provider-free implementation and fixtures.
- Produces: executable Chinese runbook, exact authorization handoff, current capability matrix, full provider-free evidence, and independent review closure.

- [ ] **Step 1: Run all focused tests and static checks**

```bash
uv run python -m unittest -v \
  tests.test_pathlight_optimization \
  tests.test_pathlight_cli \
  tests.test_pathlight_dashboard \
  tests.test_pathlight_opik \
  tests.test_pathlight_interop \
  tests.test_dci_query_planning \
  tests.test_dci_benchmark_real_executor \
  tests.test_dci_benchmark_host \
  tests.test_dci_pathlight_optimization \
  tests.test_dci_pathlight_optimization_cli
uv run pyright src tests
uv run ruff check src tests
```

Expected: all PASS and zero provider/network operations.

- [ ] **Step 2: Run full repository and distribution gates**

```bash
make check
make promotion-check
```

Expected: Python, TypeScript, Rust, lint, docs, build, installed-wheel resources, entry points, and provider-free promotion all PASS. Report exact counts from fresh output; do not reuse earlier counts.

- [ ] **Step 3: Update Chinese docs with provider-free implementation state**

Document exact prepare/status/finalize commands and authorization schema, clearly label the real A/B as not yet executed, state 80/0/$8/two-failure boundaries, and distinguish implementation from external verification. Do not paste private roots, prompt body, selected case IDs, provider payload, or credentials.

- [ ] **Step 4: Run docs and claim checks**

```bash
make docs-check
git diff --check
rg -n "PASS|Verified|已完成|已验证" docs/status/PATHLIGHT-DCI-DIAGNOSIS.md docs/status/DCI-BENCHMARK-INSTANCES.md
```

Every PASS/Verified claim must cite a fresh command and correct boundary. The unexecuted A/B remains `Not rerun` or `ready-for-authorization`.

- [ ] **Step 5: Perform independent code, security, and completion review**

Review dependency direction, public redaction, authority drift, receipt replay, budget arithmetic, cancellation, missing-trace Decision behavior, Dashboard writes, Opik authority, packaged resources, and all spec completion criteria. Fix findings with new RED tests and rerun affected gates until the review is clean.

- [ ] **Step 6: Commit Task 8 and checkpoint before external authority**

```bash
git add docs/status/PATHLIGHT-DCI-DIAGNOSIS.md docs/status/DCI-BENCHMARK-INSTANCES.md docs/superpowers/specs/2026-08-02-asterion-pathlight-design.md
git commit -m "docs: prepare Bright optimization verification"
```

After the commit, append the one-line commit entry to JOURNAL and update RESUME as project-state live files without staging them. The checkpoint must state that provider-free implementation is complete, no model run is authorized, and Task 9 requires a fresh exact plan/authorization/root.

---

### Task 9: Execute One Authorized Bright A/B and Publish the Decision

**Files:**
- Runtime private outputs under one new operator-owned 0700 root; never commit them.
- Modify after verified execution: `docs/status/PATHLIGHT-DCI-DIAGNOSIS.md`
- Modify after verified execution: `docs/status/DCI-BENCHMARK-INSTANCES.md`
- Update as durable live state after the safe result commit: `docs/status/JOURNAL.md`
- Update as durable live state after the safe result commit: `docs/status/RESUME-NEXT-SESSION.md`

**Interfaces:**
- Consumes: clean Task 8 gates, freshly prepared plan, separately supplied exact 0600 authorization, `.env` plus intentionally preserved shell proxy variables.
- Produces: eight batch receipts, 80 or fewer terminal trials under registered stop rules, native trace/evaluation closure, OptimizationBundle, Decision, Chinese report, CLI/Dashboard proof, and final completion audit.

- [ ] **Step 1: Stop and request explicit finite authority**

Disclose the exact fresh plan digest, selected 4×10 scope digest, baseline/candidate execution-config digests, 80 Agent/0 Judge limit, 8,000,000 microusd ceiling, two-infrastructure-failure stop, one native attempt per case, expected elapsed time, and the fact that accepted/rejected/inconclusive are all possible. Existing agreement to the design or plan is not execution authority.

- [ ] **Step 2: Create fresh private roots and verify clean-shell readiness**

After authorization only:

```bash
install -d -m 700 "$FRESH_OPTIMIZATION_ROOT"
env -u OPENAI_API_KEY -u DEEPSEEK_API_KEY -u ANTHROPIC_API_KEY \
  zsh -lc 'set -a; source .env; set +a; uv run asterion-dci preflight'
```

Preserve the operator's inherited `HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY` unless the exact authorized environment digest says otherwise. Confirm output root is empty, 0700, owned by the current UID, and no Dashboard process is listening.

- [ ] **Step 3: Prepare and independently validate the exact plan**

```bash
uv run asterion-dci pathlight optimization prepare \
  --diagnosis-file "$DIAGNOSIS_FILE" \
  --proposal-sha256 "$QUERY_DECOMPOSITION_PROPOSAL" \
  --output-root "$FRESH_OPTIMIZATION_ROOT"

uv run asterion-dci pathlight optimization status \
  --plan-file "$FRESH_OPTIMIZATION_ROOT/pathlight-bright-optimization-plan.json" \
  --output-root "$FRESH_OPTIMIZATION_ROOT"
```

Validate output reports 4 datasets, 40 cases, 80 Agent, 0 Judge, 8,000,000 microusd, zero completed operations, and `execution_authorized=false`.

- [ ] **Step 4: Run once in the foreground with the separately supplied authorization**

```bash
uv run asterion-dci pathlight optimization execute \
  --plan-file "$FRESH_OPTIMIZATION_ROOT/pathlight-bright-optimization-plan.json" \
  --authorization-file "$FRESH_AUTHORIZATION_FILE" \
  --output-root "$FRESH_OPTIMIZATION_ROOT"
```

Do not background the process and do not automatically invoke resume. Report progress and actual cost after each dataset/variant receipt. If interrupted, validate status and ask before any action that exceeds the already authorized resume semantics.

- [ ] **Step 5: Finalize provider-free and validate every closure**

```bash
uv run asterion-dci pathlight optimization finalize \
  --plan-file "$FRESH_OPTIMIZATION_ROOT/pathlight-bright-optimization-plan.json" \
  --authorization-file "$FRESH_AUTHORIZATION_FILE" \
  --output-root "$FRESH_OPTIMIZATION_ROOT"

uv run asterion pathlight optimization decision \
  --optimization-file "$FRESH_OPTIMIZATION_ROOT/pathlight-optimization.json" \
  --decision "$DECISION_SHA256"
```

Verify receipt chain, actual Agent/Judge counts, actual cost, native workflow bundles, 80 CaseTrial/evaluation links or exact stopped subset, criteria, and Decision. Never promote incomplete evidence to accepted/rejected.

- [ ] **Step 6: Run the Dashboard in the foreground, inspect, and stop it**

```bash
uv run asterion pathlight dashboard \
  --evidence-file "$FRESH_OPTIMIZATION_ROOT/workflow-evidence.json" \
  --evaluation-file "$FRESH_OPTIMIZATION_ROOT/pathlight-evaluations.json" \
  --experiment-file "$FRESH_OPTIMIZATION_ROOT/pathlight-experiment.json" \
  --diagnosis-file "$FRESH_OPTIMIZATION_ROOT/pathlight-diagnosis.json" \
  --optimization-file "$FRESH_OPTIMIZATION_ROOT/pathlight-optimization.json" \
  --host 127.0.0.1 \
  --port 0
```

Validate summary, paired table, decision thresholds, evidence gaps, and trace drill-down through read-only APIs. Verify prompt/question/provider/model/private-root sentinels are absent. Send a write request and require 405. Stop with Ctrl-C, require exit 0 and network operation count 0, then confirm no listener remains.

- [ ] **Step 7: Publish the Chinese result and run final gates**

Update both status documents with actual 40+40 or stopped counts, per-dataset baseline/candidate nDCG, historical full scores, paper references, actual cost/time, evidence gaps, and accepted/rejected/inconclusive Decision. Do not publish private paths or case IDs.

```bash
make docs-check
git diff --check
make check
make promotion-check
```

Expected: all provider-free post-run gates PASS. Do not rerun models to satisfy a documentation or local test failure.

- [ ] **Step 8: Complete the goal only after requirement-by-requirement audit**

Audit the six completion conditions in the approved design against current code, fresh gates, private receipts, native traces, CLI output, stopped Dashboard, and Chinese docs. If every condition is proven, commit the safe documentation, update the durable checkpoint, and mark the active goal complete. If any evidence is missing, leave the goal active and continue the missing in-scope work without redefining success.

---

## Plan Self-Review Checklist

- Task 1 implements the generic immutable lifecycle and derived three-state Decision.
- Task 2 implements provider-free CLI and Opik-safe mapping without an execution path.
- Task 3 implements the last-mile read-only Dashboard and trace drill-down.
- Task 4 makes query planning the only DCI execution variable and preserves the authoritative host path.
- Tasks 5–6 implement exact plan, authority, sequential execution, stopping, receipts, and resume.
- Task 7 produces native trial/evaluation/history/decision/diagnosis closure and a Chinese report.
- Task 8 proves provider-free code and distribution readiness before any external call.
- Task 9 is explicitly gated on new finite authority and closes the real Bright A/B plus final audit.
- No task adds DCI imports to framework modules, changes closed protocols, embeds secrets in public artifacts, or treats Opik/Dashboard as authority.
