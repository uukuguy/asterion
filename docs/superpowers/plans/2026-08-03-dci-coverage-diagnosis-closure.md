# DCI Coverage Diagnosis Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the provider-free Task 9 diagnosis merge, safe Chinese rendering, CLI dependency injection, and pre-execution operator documentation without running Step 3.

**Architecture:** A new immutable aggregate in the DCI diagnosis module is the only coverage input. Diagnosis conditionally merges that aggregate into the existing historical report, while the CLI accepts it only as an injected dependency and defines no raw-artifact flag. Documentation records the finite Task 8 authorization boundary and explicitly reports that no external experiment has run.

**Tech Stack:** Python 3.12 dataclasses and `unittest`, existing Pathlight diagnosis values, private staged CLI publication, Markdown status documentation.

## Global Constraints

- Do not call a provider, network, Agent, Judge, or external model.
- Do not fabricate, estimate, or publish coverage results.
- Preserve no-coverage diagnosis serialization and renderer output where existing tests assert them.
- A complete coverage gate requires exactly five ordered datasets, each 10 available of 10 total, zero integrity failures, 50 Agent operations, zero Judge operations, cost at most 5,000,000 microusd, and fewer than two infrastructure failures.
- Query decomposition always requires a separate authorization and remains `execution_authorized=False`.
- Public output must not contain operator paths, case IDs, provider/model/config values, prompts, answers, tool payloads, or corpus text.
- Preserve unrelated `docs/status/JOURNAL.md` and `docs/status/RESUME-NEXT-SESSION.md` changes; JOURNAL is append-only.

---

### Task 1: Immutable Coverage Aggregate and Diagnosis Merge

**Files:**
- Modify: `src/asterion/capabilities/dci/implementation/pathlight/diagnosis.py`
- Test: `tests/test_dci_pathlight_diagnosis.py`

**Interfaces:**
- Produces: `DciCoverageDatasetObservation`, `DciCoverageExperimentObservation`, and `diagnose_recommended_pack(runs, *, coverage_experiment=None)`.
- Consumes: the existing exact six-run recovered pack and content-free digests/counts/microunits only.

- [ ] **Step 1: Write the failing complete-merge test**

Add fixture helpers that construct five exact ten-query safe observations. Assert that a complete aggregate removes only `retrieval-coverage`, exposes 10/10 and the three median coverage metrics for each coverage dataset, retains all other missing codes, reports `query_decomposition_gate == "ready-for-authorization"`, and leaves every proposal unauthorized.

- [ ] **Step 2: Run the RED test**

Run: `uv run python -m unittest -v tests.test_dci_pathlight_diagnosis`

Expected: import or call failure because the aggregate types and keyword parameter do not exist.

- [ ] **Step 3: Implement exact aggregate validation**

Add frozen exact-type values with these safe fields:

```python
@dataclass(frozen=True, slots=True)
class DciCoverageDatasetObservation:
    dataset_id: str
    coverage_available_queries: int
    coverage_total_queries: int
    coverage_median_any_microunits: int | None
    coverage_median_mean_microunits: int | None
    coverage_median_all_microunits: int | None
    retained_available_queries: int
    retained_median_microunits: int | None
    tool_observation_count: int
    surfaced_gold_count: int
    model_call_count: int
    context_frame_count: int
    missing_boundary_count: int
    integrity_failure_count: int
    evidence_sha256: str

@dataclass(frozen=True, slots=True)
class DciCoverageExperimentObservation:
    plan_sha256: str
    proposal_sha256: str
    scope_sha256: str
    variant_sha256: str
    registry_set_sha256: str
    authorization_sha256: str
    receipt_set_sha256: str
    datasets: tuple[DciCoverageDatasetObservation, ...]
    agent_operation_count: int
    judge_operation_count: int
    consumed_cost_microusd: int
    infrastructure_failure_count: int
    experiment_sha256: str = field(init=False)
```

Require the exact five dataset order, total queries of ten per dataset, available counts from zero through ten, consistent optional metrics, zero Judge operations, bounded counts/cost/failures, and a canonical experiment digest.

- [ ] **Step 4: Implement conditional report merge**

Add defaulted coverage fields to `DciDatasetObservation` but omit them from `to_mapping()` when no coverage aggregate exists. Add optional `coverage_experiment` and `query_decomposition_gate` state to `DciDiagnosisReport`, also omitted from the unsigned mapping in the legacy case. Complete evidence removes `retrieval-coverage`; partial valid evidence retains it. Rebuild findings so coverage evidence supports correlations but never a causal category or causal text.

- [ ] **Step 5: Add invalid and partial aggregate tests**

Cover reordered datasets, swapped identities, subclasses, invalid digests, contradictory availability/metrics, partial valid evidence, and nonzero integrity failures. Structural violations raise `DciDiagnosisError`; valid incomplete input keeps the gate blocked.

- [ ] **Step 6: Run Task 1 tests**

Run: `uv run python -m unittest -v tests.test_dci_pathlight_diagnosis`

Expected: all diagnosis tests pass with no provider calls.

---

### Task 2: Correlation-Only Chinese Renderer and CLI Injection

**Files:**
- Modify: `src/asterion/capabilities/dci/implementation/pathlight/diagnosis.py`
- Modify: `src/asterion/applications/dci_agent_lite/pathlight_cli.py`
- Test: `tests/test_dci_pathlight_diagnosis.py`
- Test: `tests/test_dci_pathlight_cli.py`

**Interfaces:**
- Consumes: `DciCoverageExperimentObservation` from Task 1.
- Produces: conditional safe Chinese coverage sections and `pathlight_cli.main(..., coverage_experiment=None)` dependency injection.

- [ ] **Step 1: Write renderer and CLI RED tests**

Assert that complete injected evidence renders every safe metric, uses the fixed phrases `观测相关性` and `不证明因果关系`, marks query decomposition `可申请单独授权` and `当前未授权`, and never includes sentinel private values. Exercise CLI diagnosis with six private recovery roots and an injected aggregate; assert immutable staged output and provider-free behavior.

- [ ] **Step 2: Run the RED tests**

Run: `uv run python -m unittest -v tests.test_dci_pathlight_diagnosis tests.test_dci_pathlight_cli`

Expected: renderer assertions or CLI keyword injection fail.

- [ ] **Step 3: Implement conditional rendering and injection**

Pass the aggregate from `pathlight_cli.main` to `_diagnose` and then to `diagnose_recommended_pack`. Render a coverage line only when coverage is present. Render partial/integrity-failed evidence as blocked. Do not add a command-line file option or loader.

- [ ] **Step 4: Verify legacy and injected paths**

Run: `uv run python -m unittest -v tests.test_dci_pathlight_diagnosis tests.test_dci_pathlight_cli tests.test_dci_pathlight_experiment_cli`

Expected: all tests pass; no provider/network/model work runs.

---

### Task 3: Pre-Execution Documentation and Authorization Handoff

**Files:**
- Modify: `docs/status/PATHLIGHT-DCI-DIAGNOSIS.md`
- Modify: `docs/status/DCI-BENCHMARK-INSTANCES.md`
- Modify: `docs/status/INDEX.md` only if another status report is created

**Interfaces:**
- Consumes: Task 8 plan constants and authorization schema.
- Produces: a truthful not-run status and exact finite operator command requirements.

- [ ] **Step 1: Add the not-run status section**

State that the 50-case coverage experiment has not executed, no observed coverage metrics exist, and the decomposition gate is blocked. Record exact limits: five datasets, ten cases each, 50 Agent operations, zero Judge operations, 5,000,000 microusd, and stop before a third infrastructure failure.

- [ ] **Step 2: Add the authorization checklist and command shape**

Require the operator to verify matching `plan_sha256`, `proposal_sha256`, `scope_sha256`, `variant_sha256`, `registry_set_sha256`, limits, `execution_authorized=true`, and a separate approval digest in a private 0600 document. Include the brief’s cleared-environment command using only environment-variable placeholders.

- [ ] **Step 3: Scan documentation for unsafe content**

Run: `rg -n "provider|model|prompt|answer|payload|corpus|/Users/|case[-_ ]?id" docs/status/PATHLIGHT-DCI-DIAGNOSIS.md docs/status/DCI-BENCHMARK-INSTANCES.md`

Expected: only fixed explanatory policy text; no private values or result claims.

---

### Task 4: Provider-Free Verification and Commit

**Files:**
- Create: `.superpowers/sdd/task-9-report.md`
- Include all Task 9 source, tests, docs, design, and plan files in the focused commit.

**Interfaces:**
- Produces: exact provider-free evidence and operator authorization handoff.

- [ ] **Step 1: Run focused tests**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_pathlight_coverage \
  tests.test_dci_pathlight_experiment_cli \
  tests.test_dci_pathlight_diagnosis \
  tests.test_dci_pathlight_cli
```

Expected: all pass without provider/model/network access.

- [ ] **Step 2: Run static and documentation checks**

Run:

```bash
uv run pyright \
  src/asterion/capabilities/dci/implementation/pathlight/diagnosis.py \
  src/asterion/applications/dci_agent_lite/pathlight_cli.py \
  tests/test_dci_pathlight_diagnosis.py \
  tests/test_dci_pathlight_cli.py
uv run ruff check \
  src/asterion/capabilities/dci/implementation/pathlight/diagnosis.py \
  src/asterion/applications/dci_agent_lite/pathlight_cli.py \
  tests/test_dci_pathlight_diagnosis.py \
  tests/test_dci_pathlight_cli.py
make docs-check
git diff --check
```

Expected: zero errors and documentation checks pass.

- [ ] **Step 3: Write the Task 9 report**

Record that Step 3 external execution was not run, no coverage values were produced, the decomposition gate remains blocked in repository documentation, and list the exact plan/authorization digest fields and finite command required from the operator.

- [ ] **Step 4: Commit the provider-free slice**

```bash
git add src/asterion/capabilities/dci/implementation/pathlight/diagnosis.py \
  src/asterion/applications/dci_agent_lite/pathlight_cli.py \
  tests/test_dci_pathlight_diagnosis.py tests/test_dci_pathlight_cli.py \
  docs/status/PATHLIGHT-DCI-DIAGNOSIS.md \
  docs/status/DCI-BENCHMARK-INSTANCES.md \
  docs/superpowers/plans/2026-08-03-dci-coverage-diagnosis-closure.md
git add -f .superpowers/sdd/task-9-report.md
git commit -m "feat: prepare Bright coverage diagnosis"
```

Expected: a focused commit; unrelated status-document changes remain unstaged.
