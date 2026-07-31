# DCI Bamboogle Full125 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `dci.qa.bamboogle.paper-full125@1.0.0` executable for bounded and full 125-case runs, then document progressive result coverage in Chinese.

**Architecture:** Existing bindings already map the 125-row local data file and Wikipedia corpus. Expose its exact suite, declare its finite range, and replace the executor's one hard-coded Bamboogle contract with two immutable contracts. The generic host still authorizes each model run separately.

**Tech Stack:** Python 3.12, unittest, Asterion capability-package JSON resources, Markdown.

## Global Constraints

- Framework modules remain DCI-neutral.
- No Agent or Judge requests during implementation checks.
- A partial run must show `已跑/总量`; it is never a full or paper score.
- Preserve exact locks, cancellation, resume, and redaction.

---

### Task 1: Expose full125 as an exact instance

**Files:**
- Modify: `src/asterion/applications/dci_agent_lite/benchmark_instances.py`
- Modify: `src/asterion/capabilities/dci/implementation/benchmark_bindings.py`
- Create: `src/asterion/capabilities/dci/payload/benchmark-suites/qa-bamboogle-paper-full125.json`
- Modify: `src/asterion/capabilities/dci/payload/capability-package.json`
- Test: `tests/test_dci_benchmark_instances.py`
- Test: `tests/test_dci_capability_payload.py`

**Interfaces:** Produces the exact selector with `implementation_state == "implemented"`, `all_case_count == 125`, and a one-task suite named `dci.qa.bamboogle.paper-full125`.

- [ ] **Step 1: Write a failing catalog test**

```python
paper = select_benchmark_instance("dci.qa.bamboogle.paper-full125@1.0.0")
self.assertEqual(paper.implementation_state, "implemented")
self.assertEqual(resolve_case_limit(paper, case_limit=50, all_cases=False), 50)
self.assertEqual(resolve_case_limit(paper, case_limit=None, all_cases=True), 125)
```

- [ ] **Step 2: Verify RED**

Run: `uv run python -m unittest -v tests.test_dci_benchmark_instances.TestDciBenchmarkInstances.test_paper_full125_is_implemented_with_bounded_and_full_ranges`

Expected: FAIL because the current catalog marks it planned and has no all-case count.

- [ ] **Step 3: Implement the exact suite and catalog**

Create the canonical one-task suite using task `qa.bamboogle.paper-full125`, add its ref to the package payload and `_DCI_SUITES`, and set `implemented=True, all_case_count=125` in the instance catalog.

- [ ] **Step 4: Verify GREEN**

Run: `uv run python -m unittest -v tests.test_dci_benchmark_instances tests.test_dci_capability_payload`

Expected: PASS.

### Task 2: Execute each Bamboogle contract only in range

**Files:**
- Modify: `src/asterion/applications/dci_agent_lite/benchmark_executor.py`
- Test: `tests/test_dci_benchmark_real_executor.py`
- Test: `tests/test_dci_benchmark_host.py`

**Interfaces:** `RealDciBenchmarkExecutor` accepts sample50 through 50 and paper-full125 through 125 only when task, binding, profile, selection, and case count agree exactly.

- [ ] **Step 1: Write a failing executor test**

```python
result = executor.execute(
    _invocation(root, task_id="qa.bamboogle.paper-full125",
                selection_variant="paper-full125", case_limit=125),
    cancellation=MutableCancellation(), on_progress=lambda _: None,
)
self.assertEqual(result.status, "completed")
self.assertEqual(calls[0][0].limit, 125)
```

- [ ] **Step 2: Verify RED**

Run: `uv run python -m unittest -v tests.test_dci_benchmark_real_executor.TestRealDciBenchmarkExecutor.test_executes_paper_full125_contract`

Expected: FAIL because the executor accepts only `github-sample50` and maximum 50.

- [ ] **Step 3: Implement two immutable contracts**

Replace the single task/profile/selection constants with contracts for `(sample50, github-sample50, 50)` and `(paper-full125, paper-full125, 125)`. `_real_payload` selects by task ID and rejects all mismatches before invoking the native runner.

- [ ] **Step 4: Verify GREEN**

Run: `uv run python -m unittest -v tests.test_dci_benchmark_real_executor tests.test_dci_benchmark_host`

Expected: PASS, including rejection at 51 for sample50 and 126 for full125.

### Task 3: Publish progressive coverage in the Chinese ledger

**Files:**
- Modify: `docs/status/DCI-BENCHMARK-INSTANCES.md`
- Modify: `tests/test_dci_benchmark_instances.py`
- Test: `tests/test_dci_application_adapter.py`

**Interfaces:** The full125 runbook supports `--case-limit 50` and `--all-cases`; it describes a `50/125` stage result and requires model, judge, score, cost, and evidence fields once a run exists.

- [ ] **Step 1: Write failing documentation and CLI-plan tests**

```python
self.assertIn("## 运行手册：`dci.qa.bamboogle.paper-full125@1.0.0`", text)
self.assertIn("阶段性结果：50/125", text)
self.assertEqual(json.loads(all_stdout.getvalue())["case_limit"], 125)
```

- [ ] **Step 2: Verify RED**

Run: `uv run python -m unittest -v tests.test_dci_benchmark_instances.TestDciBenchmarkInstances.test_paper_full125_runbook_and_plans_are_exposed`

Expected: FAIL because the runbook and executable plan do not exist.

- [ ] **Step 3: Update the ledger and runbook**

Mark full125 implemented, add its lock/plan/run/resume commands, and state no score until a real run produces evidence. Retain the full125 distinction from the existing 50-case GitHub result.

- [ ] **Step 4: Verify GREEN**

Run: `uv run python -m unittest -v tests.test_dci_benchmark_instances tests.test_dci_application_adapter`

Expected: PASS without provider calls.

### Task 4: Verify and record closure

**Files:**
- Modify: `docs/status/JOURNAL.md`

- [ ] **Step 1: Run integration checks**

```bash
uv run python -m unittest -v tests.test_dci_benchmark_instances tests.test_dci_benchmark_real_executor tests.test_dci_benchmark_host tests.test_dci_capability_payload
make check
make promotion-check
```

Expected: PASS without Agent/Judge requests.

- [ ] **Step 2: Commit focused changes and journal evidence**

Commit the implementation and documentation. Append a factual journal entry that records executable full125 and the named passing commands; do not claim a score until an authorized model run finishes.
