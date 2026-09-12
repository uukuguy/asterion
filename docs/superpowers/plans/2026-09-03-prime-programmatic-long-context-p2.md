# Prime Programmatic Long-Context P2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an honest provider-free compatibility acceptance product for
`prime.programmatic-long-context/v1`, without treating it as a model-backed or
sandboxed result.

**Architecture:** The existing pinned Prime SDK/IPython compatibility process
gets a separate fixed corpus fixture. It uses only the real `ipython` tool to
execute a deterministic program that reads, selects, aggregates, and validates
externalized corpus records. Python accepts only a compact, corpus-free
observation and emits a matching provider-free evidence receipt. The later
native worker/broker runner must separately bind actual model tool calls and
may not reuse this receipt as `bounded-sandboxed` evidence.

**Tech Stack:** Node 22 pinned Prime `dist`, local pre-provisioned IPython,
Python frozen dataclasses, `unittest`, SHA-256, no Docker/network/provider.

## Global Constraints

- `3th-party/prime-agent` remains read-only and source-lock verified before
  Node starts.
- `ipython` is the only allowed/active tool; no shell/file tool is introduced.
- Corpus records, selected values, program source, paths, model/provider input,
  credentials, and kernel output never enter public reports or receipts.
- The fixture uses local deterministic data and a pre-provisioned kernel only;
  it does not call a provider, read `.env`, install packages, start Docker, or
  emit `bounded-sandboxed` evidence.
- Every public report has a fixed exact key set and a reason from a closed
  classification set.

---

### Task 1: Closed long-context provider-free receipt

**Files:**
- Create: `src/asterion/applications/prime_agent/programmatic_long_context_receipt.py`
- Create: `tests/test_prime_programmatic_long_context_receipt.py`

**Interfaces:**

```python
@dataclass(frozen=True, repr=False)
class ProgrammaticLongContextObservation:
    built_in_tools: tuple[str, ...]
    active_tool_names: tuple[str, ...]
    corpus_sha256: str
    corpus_record_count: int
    selected_record_count: int
    program_sha256: str
    aggregate_sha256: str
    oracle_sha256: str
    ipython_cell_executed: bool
    oracle_passed: bool

def verify_programmatic_long_context_receipt(
    observation: ProgrammaticLongContextObservation,
) -> PrimeEvidenceReceipt: ...
```

- [ ] **Step 1: Write the failing receipt truth-table tests.**

```python
receipt = verify_programmatic_long_context_receipt(_observation())
self.assertEqual(receipt.scenario_id, "prime.programmatic-long-context/v1")
self.assertIs(receipt.level, PrimeEvidenceLevel.PROVIDER_FREE)
for field in ("corpus_sha256", "program_sha256", "aggregate_sha256", "oracle_sha256"):
    with self.subTest(field=field), self.assertRaises(ProgrammaticLongContextReceiptError):
        verify_programmatic_long_context_receipt(replace(_observation(), **{field: "sha256:" + "0" * 64}))
```

Also reject any non-`ipython` tool, zero/boolean counts, zero selected count,
unexecuted cell, failed oracle, malformed `sha256:` identity, mutable values,
and a `bounded-sandboxed` upgrade request. Assert `repr`, `str`, and exception
text omit corpus and program sentinel strings.

- [ ] **Step 2: Verify RED.**

Run:

```bash
uv run python -m unittest -v tests.test_prime_programmatic_long_context_receipt
```

Expected: FAIL because the receipt module does not exist.

- [ ] **Step 3: Implement the closed verifier.**

```python
def verify_programmatic_long_context_receipt(
    observation: ProgrammaticLongContextObservation,
    requested_level: PrimeEvidenceLevel = PrimeEvidenceLevel.PROVIDER_FREE,
) -> PrimeEvidenceReceipt:
    if requested_level is not PrimeEvidenceLevel.PROVIDER_FREE:
        raise ProgrammaticLongContextReceiptError("programmatic long-context receipt is invalid")
    # Require exact ipython-only tool tuples, positive non-bool counts,
    # distinct canonical SHA-256 identities, a true executed-cell fact,
    # and a true oracle fact before emitting the one fixed receipt.
```

Keep the observation private in repr and delegate the final closed scenario/
level validation to `validate_prime_evidence_receipt`.

- [ ] **Step 4: Verify GREEN.**

Run:

```bash
uv run python -m unittest -v tests.test_prime_programmatic_long_context_receipt tests.test_prime_capability_evidence
uv run ruff check src/asterion/applications/prime_agent/programmatic_long_context_receipt.py tests/test_prime_programmatic_long_context_receipt.py
uv run pyright src/asterion/applications/prime_agent/programmatic_long_context_receipt.py tests/test_prime_programmatic_long_context_receipt.py
git diff --check
```

Expected: PASS with no process, provider, Docker, or network operation.

- [ ] **Step 5: Commit.**

```bash
git add src/asterion/applications/prime_agent/programmatic_long_context_receipt.py tests/test_prime_programmatic_long_context_receipt.py
git commit -m "feat(prime): verify programmatic long-context receipt"
```

### Task 2: Real Prime/IPython corpus compatibility fixture

**Files:**
- Create: `tests/fixtures/prime_gateway/v1/prime-programmatic-long-context-compat.mjs`
- Create: `tests/test_prime_programmatic_long_context_compat.py`

**Interfaces:**

```python
def _run_compatibility(workspace: Path) -> tuple[dict[str, object], str, int]: ...
```

The JSON report has exactly:

```text
format, status, reason, real_prime_runtime, allowed_tool_names,
active_tool_names, corpus_sha256, corpus_record_count, selected_record_count,
program_sha256, aggregate_sha256, oracle_sha256, ipython_cell_executed,
oracle_passed, disposed, reaped
```

- [ ] **Step 1: Write failing real-process and redaction tests.**

```python
report, stderr, returncode = _run_compatibility(workspace)
self.assertEqual(report["format"], "asterion.prime-programmatic-long-context-compat/v1")
self.assertIn(report["status"], {"PASS", "External-limited"})
if report["status"] == "PASS":
    self.assertEqual(report["allowed_tool_names"], ["ipython"])
    self.assertTrue(report["ipython_cell_executed"])
    self.assertTrue(report["oracle_passed"])
self.assertNotIn("CORPUS-SENTINEL", json.dumps(report, sort_keys=True))
```

Use the coding compatibility test's source-lock, offline environment, process
group cleanup, and fixed reason taxonomy. Assert the Node fixture source has
no `fetch(`, Docker, package-install, `.env`, or provider configuration.

- [ ] **Step 2: Verify RED.**

Run:

```bash
uv run python -m unittest -v tests.test_prime_programmatic_long_context_compat
```

Expected: FAIL because the fixture and runner do not exist.

- [ ] **Step 3: Implement only real-IPython compatibility behavior.**

The fixture creates a deterministic corpus file in its temporary workspace
whose record values include a private sentinel. It creates a real Prime SDK
session restricted to `ipython`, invokes `tool.execute()` with one fixed Python
program that reads the corpus path from its process-local workspace, filters a
deterministic subset, writes one aggregate file, and recomputes an oracle
digest. It returns only counts and SHA-256 values. It must dispose the session
and return `External-limited` for missing pinned dist/API/kernel prerequisites.
It must not assert a model tool-call: this phase proves programmatic data
handling, not model agency.

- [ ] **Step 4: Verify GREEN.**

Run:

```bash
uv run python -m unittest -v tests.test_prime_programmatic_long_context_compat tests.test_prime_ipython_coding_compat
git diff --check
```

Expected: PASS or a closed `External-limited` report; no Docker/network/model
action and no `PrimeEvidenceReceipt` emitted by Node.

- [ ] **Step 5: Commit.**

```bash
git add tests/fixtures/prime_gateway/v1/prime-programmatic-long-context-compat.mjs tests/test_prime_programmatic_long_context_compat.py
git commit -m "test(prime): exercise programmatic long-context compatibility"
```

### Task 3: Bind real compatibility facts to the receipt

**Files:**
- Modify: `tests/test_prime_programmatic_long_context_receipt.py`
- Modify: `tests/test_prime_programmatic_long_context_compat.py`

- [ ] **Step 1: Write the failing integration test.**

```python
if report["status"] == "PASS":
    receipt = verify_programmatic_long_context_receipt(_observation_from_report(report))
    self.assertEqual(receipt.scenario_id, "prime.programmatic-long-context/v1")
```

Assert an `External-limited` report cannot be converted to any receipt, a
public report cannot carry corpus/program source, and a changed digest/count/
tool fact fails before receipt construction.

- [ ] **Step 2: Verify RED.**

Run:

```bash
uv run python -m unittest -v tests.test_prime_programmatic_long_context_receipt tests.test_prime_programmatic_long_context_compat
```

Expected: FAIL because report-to-observation binding is absent.

- [ ] **Step 3: Implement a test-local strict report adapter.**

The adapter accepts only the exact public key set, PASS/supported report,
`["ipython"]` tool arrays, positive non-bool counts, canonical digests, true
cell/oracle/dispose/reap facts, and no additional fields. It constructs no
worker, provider, or image evidence.

- [ ] **Step 4: Verify GREEN.**

Run:

```bash
uv run python -m unittest -v tests.test_prime_programmatic_long_context_receipt tests.test_prime_programmatic_long_context_compat tests.test_prime_capability_evidence
uv run ruff check src/asterion/applications/prime_agent/programmatic_long_context_receipt.py tests/test_prime_programmatic_long_context_receipt.py tests/test_prime_programmatic_long_context_compat.py
uv run pyright src/asterion/applications/prime_agent/programmatic_long_context_receipt.py tests/test_prime_programmatic_long_context_receipt.py tests/test_prime_programmatic_long_context_compat.py
git diff --check
```

Expected: a matching `provider-free` receipt only when the real compatibility
process returns PASS; no higher evidence level is possible.

- [ ] **Step 5: Commit.**

```bash
git add tests/test_prime_programmatic_long_context_receipt.py tests/test_prime_programmatic_long_context_compat.py
git commit -m "test(prime): bind long-context compatibility evidence"
```

## Self-review

- Task 1 closes the public evidence type before a process can claim it.
- Task 2 uses a real pinned Prime SDK/IPython tool but deliberately does not
  claim a model-generated program or sandboxed execution.
- Task 3 only binds a closed PASS report and cannot convert an
  `External-limited` result or raise evidence level.
- The model-driven and native-sandboxed layers remain P1 follow-up work bound
  to the authorized worker/broker/image path.
