# Prime Recursive Workflow P3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an honest provider-free acceptance product for `prime.recursive-workflow/v1`, backed by a real pinned Prime RLM child/message and lifecycle path rather than a model-backed recursion claim.

**Architecture:** A small Python verifier accepts only private, normalized facts for a root workflow that admits two independently bound children, records a root-to-child message and a child-to-root result message, observes both complete, and deletes both children after aggregation. A Node fixture later executes that exact sequence through the pinned Prime RLM host bridge and exposes only hashes, counts, and booleans. It remains separate from the existing bounded-provider RLM scenarios (`child-model`, `generated-program`, and `recursion-depth`).

**Tech Stack:** Python frozen dataclasses and `unittest`; pinned Node 22 Prime gateway/RLM daemon; SHA-256; no Docker, network, provider call, or `.env`.

## Global Constraints

- `3th-party/prime-agent` remains read-only and source-lock verified before the Node fixture starts.
- Every child effect must be bound to a unique admitted child ID. Unbound or duplicated children, messages, terminal events, or deletion events fail closed.
- The provider-free product proves bounded orchestration mechanics only. It does not claim child model execution, generated programs, arbitrary recursion depth, or sandboxing.
- Public reports and receipts never disclose goal text, message bodies, child identities, native identities, paths, credentials, model/provider inputs, or outputs.
- A report can emit a receipt only for exact `PASS`/`supported` real-Prime facts; missing local prerequisites remain `External-limited`.

---

### Task 1: Closed recursive-workflow receipt

**Files:**
- Create: `src/asterion/applications/prime_agent/recursive_workflow_receipt.py`
- Create: `tests/test_prime_recursive_workflow_receipt.py`

**Interfaces:**

```python
@dataclass(frozen=True, repr=False)
class RecursiveWorkflowObservation:
    built_in_tools: tuple[str, ...]
    active_tool_names: tuple[str, ...]
    admitted_child_count: int
    bound_child_count: int
    root_to_child_message_count: int
    child_to_root_result_count: int
    terminal_child_count: int
    deleted_child_count: int
    workflow_sha256: str
    aggregation_sha256: str
    oracle_sha256: str
    root_continued_locally: bool
    aggregation_passed: bool

def verify_recursive_workflow_receipt(
    observation: RecursiveWorkflowObservation,
    requested_level: PrimeEvidenceLevel = PrimeEvidenceLevel.PROVIDER_FREE,
) -> PrimeEvidenceReceipt: ...
```

- [ ] **Step 1: Write failing truth-table tests.**

```python
receipt = verify_recursive_workflow_receipt(_observation())
self.assertEqual(receipt.scenario_id, "prime.recursive-workflow/v1")
for field in ("bound_child_count", "child_to_root_result_count", "deleted_child_count"):
    with self.subTest(field=field), self.assertRaises(RecursiveWorkflowReceiptError):
        verify_recursive_workflow_receipt(replace(_observation(), **{field: 1}))
```

Also reject non-`ipython` tool tuples, zero/boolean/unequal counts, malformed `sha256:` identities, false root-continuation or aggregation facts, mutability, and evidence upgrades. Assert repr, str, and errors omit private goal/message sentinels.

- [ ] **Step 2: Verify RED.**

Run:

```bash
uv run python -m unittest -v tests.test_prime_recursive_workflow_receipt
```

Expected: FAIL because the receipt module does not exist.

- [ ] **Step 3: Implement the minimal closed verifier.**

Require exactly two independent children for this fixed product; require all six child/message/lifecycle counts to be exactly two; require canonical digest facts and true local continuation/aggregation facts. Return only the fixed provider-free receipt through `validate_prime_evidence_receipt`.

- [ ] **Step 4: Verify GREEN.**

Run:

```bash
uv run python -m unittest -v tests.test_prime_recursive_workflow_receipt tests.test_prime_capability_evidence
uv run ruff check src/asterion/applications/prime_agent/recursive_workflow_receipt.py tests/test_prime_recursive_workflow_receipt.py
uv run pyright src/asterion/applications/prime_agent/recursive_workflow_receipt.py tests/test_prime_recursive_workflow_receipt.py
git diff --check
```

Expected: PASS without process, provider, Docker, or network operation.

- [ ] **Step 5: Commit.**

```bash
git add src/asterion/applications/prime_agent/recursive_workflow_receipt.py tests/test_prime_recursive_workflow_receipt.py
git commit -m "feat(prime): verify recursive workflow receipt"
```

### Task 2: Pinned RLM recursive-workflow compatibility fixture

**Files:**
- Create: `tests/fixtures/prime_gateway/v1/prime-recursive-workflow-compat.mjs`
- Create: `tests/test_prime_recursive_workflow_compat.py`

**Interfaces:**

```python
def _run_compatibility(workspace: Path) -> tuple[dict[str, object], str, int]: ...
```

The exact public JSON keys are:

```text
format, status, reason, real_prime_runtime, allowed_tool_names,
active_tool_names, admitted_child_count, bound_child_count,
root_to_child_message_count, child_to_root_result_count,
terminal_child_count, deleted_child_count, workflow_sha256,
aggregation_sha256, oracle_sha256, root_continued_locally,
aggregation_passed, disposed, reaped
```

- [ ] **Step 1: Write failing fixture/process/redaction tests.**

Assert fixture source contains no `fetch(`, Docker, package installation, `.env`, provider configuration, private sentinels, or raw RLM goal/message fields in its emitted report. For a PASS, require real Prime, exactly `["ipython"]`, two of every count, true root continuation/aggregation/dispose/reap facts, and no private sentinel in stdout/stderr.

- [ ] **Step 2: Verify RED.**

Run:

```bash
uv run python -m unittest -v tests.test_prime_recursive_workflow_compat
```

Expected: FAIL because fixture and runner do not exist.

- [ ] **Step 3: Implement the exact RLM mechanics fixture.**

Use the current real daemon/sidecar harness pattern. Construct an RLM bridge with two explicit independently admitted children, exact root-to-child and child-to-root messages, explicit `started`, `terminal(completed)`, and `deleted` events, then compute only hashed workflow/aggregation/oracle facts. Dispose and reap every process. Return `External-limited` for missing pinned dist/API/kernel prerequisites. Do not invoke an LLM or claim recursive-depth or child-model success.

- [ ] **Step 4: Verify GREEN.**

Run:

```bash
uv run python -m unittest -v tests.test_prime_recursive_workflow_compat tests.test_prime_rlm_messaging_parity
git diff --check
```

Expected: PASS or an exact closed `External-limited` report, with no Docker/network/provider operation.

- [ ] **Step 5: Commit.**

```bash
git add tests/fixtures/prime_gateway/v1/prime-recursive-workflow-compat.mjs tests/test_prime_recursive_workflow_compat.py
git commit -m "test(prime): exercise recursive workflow compatibility"
```

### Task 3: Bind exact public compatibility facts to the receipt

**Files:**
- Modify: `src/asterion/applications/prime_agent/recursive_workflow_receipt.py`
- Modify: `tests/test_prime_recursive_workflow_receipt.py`
- Modify: `tests/test_prime_recursive_workflow_compat.py`

**Interfaces:**

```python
def recursive_workflow_observation_from_public_report(
    report: object,
) -> RecursiveWorkflowObservation: ...
```

- [ ] **Step 1: Write failing PASS-only binding tests.**

```python
observation = recursive_workflow_observation_from_public_report(report)
receipt = verify_recursive_workflow_receipt(observation)
self.assertEqual(receipt.scenario_id, "prime.recursive-workflow/v1")
```

Require exact keys, fixed format, PASS/supported, real runtime, `["ipython"]`, true cleanup facts, exact truth table, and no extras. Assert that `External-limited`, one unbound child, one absent deletion/message fact, or any added field cannot yield a receipt.

- [ ] **Step 2: Verify RED.**

Run:

```bash
uv run python -m unittest -v tests.test_prime_recursive_workflow_receipt tests.test_prime_recursive_workflow_compat
```

Expected: FAIL because the report adapter is absent.

- [ ] **Step 3: Implement the strict report adapter.**

Construct private facts only after all public fields pass fixed validation and call `verify_recursive_workflow_receipt` before returning. Never retain or return report-provided identity strings other than hashes.

- [ ] **Step 4: Verify GREEN.**

Run:

```bash
uv run python -m unittest -v tests.test_prime_recursive_workflow_receipt tests.test_prime_recursive_workflow_compat tests.test_prime_capability_evidence
uv run ruff check src/asterion/applications/prime_agent/recursive_workflow_receipt.py tests/test_prime_recursive_workflow_receipt.py tests/test_prime_recursive_workflow_compat.py
uv run pyright src/asterion/applications/prime_agent/recursive_workflow_receipt.py tests/test_prime_recursive_workflow_receipt.py tests/test_prime_recursive_workflow_compat.py
git diff --check
```

Expected: PASS, while `External-limited` remains non-promotable.

- [ ] **Step 5: Commit.**

```bash
git add src/asterion/applications/prime_agent/recursive_workflow_receipt.py tests/test_prime_recursive_workflow_receipt.py tests/test_prime_recursive_workflow_compat.py
git commit -m "test(prime): bind recursive workflow receipt"
```

## Self-Review

- Spec coverage: Task 1 covers immutable, redacted, non-upgradeable receipt; Task 2 supplies actual pinned RLM lifecycle/message facts; Task 3 admits only exact successful public reports. Model-backed and arbitrary-depth claims stay excluded.
- Placeholder scan: no `TBD`, `TODO`, or deferred implementation text.
- Type consistency: Tasks 2 and 3 use the exact report adapter and frozen observation names introduced in Task 1.

