# DCI Coverage Execution-Config Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bind Task 8 coverage plans, authorizations, and receipts to a digest of exact effective real-host execution settings and reject drift before host/provider construction.

**Architecture:** The DCI benchmark host owns one fixed override mapping and reuses it for real executor construction and digest resolution. The DCI executor hashes effective coverage request settings and its existing task constants. The Pathlight coordinator stores and validates only the SHA-256 across plan, authorization, execute, and receipt boundaries.

**Tech Stack:** Python 3.12 configuration values, SHA-256 canonical JSON, `unittest`, `unittest.mock`, Pyright, Ruff.

## Global Constraints

- Generic framework modules must not import DCI.
- Public and private documents expose only `execution_config_sha256`, never credentials, paths, raw environment, or raw provider configuration.
- Host-overridden environment provider/model/runtime/tools/max-turns/context values are irrelevant.
- Effective timeout, thinking, and Node-memory changes alter the digest.
- Fixed effective runtime/model/context and executor tools/max-turns/native-attempt defaults alter the digest when changed in code.
- Drift rejection occurs before `_create_host` and provider loading; prepare remains provider-free.
- Preserve five exact tasks, ten cases each, 50 Agent operations, zero Judge operations, 5,000,000 microusd, and the two-failure stop.
- Preserve unrelated status, `.env`, and concurrent-agent changes.

---

### Task 1: Effective digest boundary

**Files:**
- Modify: `src/asterion/applications/dci_agent_lite/benchmark_executor.py`
- Modify: `src/asterion/applications/dci_agent_lite/benchmark_host.py`
- Test: `tests/test_dci_pathlight_experiment_cli.py`

**Interfaces:**
- Produces: `coverage_execution_config_sha256(environment: Mapping[str, str]) -> str` from the DCI benchmark host.
- Consumes: `resolve_dci_runtime_options()` and existing executor coverage constants.

- [ ] **Step 1: Write RED digest tests**

Prepare plans under two environments and assert an exact SHA field, unchanged
digest after credential plus overridden runtime-key rotation, and changed digest
for timeout, thinking, and Node memory. Assert `.env` sentinels and resource
paths are absent from serialized plans.

```python
self.assertRegex(plan["execution_config_sha256"], r"^[0-9a-f]{64}$")
self.assertEqual(first_digest, rotated_irrelevant_digest)
self.assertNotEqual(first_digest, changed_timeout_digest)
```

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v \
  tests.test_dci_pathlight_experiment_cli.TestDciPathlightExperimentCli.test_prepare_binds_only_effective_execution_config
```

Expected: FAIL because `execution_config_sha256` is absent.

- [ ] **Step 3: Implement executor digest helper**

Hash one internal domain-separated canonical mapping. Include effective runtime,
provider, model, `read,grep` tools, context, timeout, thinking, Node memory,
authentication, keep-session, extra arguments, executor/experiment profile, and
for each ordered coverage task its mode, effective max turns/concurrency, native
attempts, case limit ten, externalized tool results, and zero Judge operations.
Return only a lowercase SHA-256.

- [ ] **Step 4: Reuse exact host resolution**

Define the fixed host override mapping once and use one
`_real_agent_runtime_options(environment)` helper in both `_default_executor()`
and `coverage_execution_config_sha256(environment)`. The wrapper delegates to
the executor helper and returns only the digest.

- [ ] **Step 5: Run Task 1 GREEN**

Run the Step 2 command and expect PASS without provider calls.

---

### Task 2: Authority-chain binding

**Files:**
- Modify: `src/asterion/applications/dci_agent_lite/pathlight_experiment_cli.py`
- Test: `tests/test_dci_pathlight_experiment_cli.py`

**Interfaces:**
- Consumes: `coverage_execution_config_sha256(environment)`.
- Produces: exact `execution_config_sha256` fields in plan, authorization validation, and receipts.

- [ ] **Step 1: Write RED drift and receipt tests**

Extend the authorization fixture to repeat the plan digest. Prepare and authorize
under one configuration, then execute under changed timeout/thinking/Node-memory
values. Patch the host fixed context override and executor native-attempt mapping
in separate subtests. Every drift must return code 2 with an empty host-construction
event list. Unchanged execution must succeed and every receipt must repeat the
plan digest.

- [ ] **Step 2: Run RED**

```bash
uv run python -m unittest -v tests.test_dci_pathlight_experiment_cli
```

Expected: new drift or receipt assertions fail before coordinator binding exists.

- [ ] **Step 3: Bind plan and authorization**

During prepare, hash `config.benchmark_inputs.private_environment`, add the field
before `plan_sha256`, and require an exact SHA in `_read_plan`. Require the 0600
authorization to repeat and exactly match the plan field.

- [ ] **Step 4: Reject live drift before host construction**

After `_execution_config()` loads current private configuration and before task
iteration, recompute the digest and compare it to the plan with
`hmac.compare_digest`. Do not serialize underlying values.

- [ ] **Step 5: Bind receipts**

Publish the plan digest in every receipt and require equality to the plan in
`_read_receipt_chain`, preventing resume across configuration drift.

- [ ] **Step 6: Run Task 2 GREEN**

Run the Step 2 command and expect all experiment CLI tests to pass.

---

### Task 3: Focused verification and commit

**Files:**
- Verify all Task 1 and Task 2 files.

**Interfaces:**
- Produces: a focused implementation commit and provider-free evidence.

- [ ] **Step 1: Run focused regressions**

```bash
uv run python -m unittest -v \
  tests.test_dci_pathlight_experiment_cli \
  tests.test_dci_pathlight_cli \
  tests.test_dci_benchmark_real_executor \
  tests.test_dci_full_authorization
```

Expected: PASS with no external operation.

- [ ] **Step 2: Run static checks**

```bash
uv run pyright \
  src/asterion/applications/dci_agent_lite/benchmark_executor.py \
  src/asterion/applications/dci_agent_lite/benchmark_host.py \
  src/asterion/applications/dci_agent_lite/pathlight_experiment_cli.py \
  tests/test_dci_pathlight_experiment_cli.py
uv run ruff check \
  src/asterion/applications/dci_agent_lite/benchmark_executor.py \
  src/asterion/applications/dci_agent_lite/benchmark_host.py \
  src/asterion/applications/dci_agent_lite/pathlight_experiment_cli.py \
  tests/test_dci_pathlight_experiment_cli.py
git diff --check
```

Expected: zero errors and warnings.

- [ ] **Step 3: Commit only the focused slice**

```bash
git add \
  src/asterion/applications/dci_agent_lite/benchmark_executor.py \
  src/asterion/applications/dci_agent_lite/benchmark_host.py \
  src/asterion/applications/dci_agent_lite/pathlight_experiment_cli.py \
  tests/test_dci_pathlight_experiment_cli.py \
  docs/superpowers/plans/2026-08-03-dci-coverage-execution-config-binding.md
git commit -m "fix: bind coverage execution configuration"
```

Expected: unrelated status and `.env` changes remain unstaged. Append one journal
line only after the commit lands.
