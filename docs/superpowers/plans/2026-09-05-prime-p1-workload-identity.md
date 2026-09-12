# Prime P1 Workload Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace P1's result-as-workload identity with a canonical, image-resident workload contract.

**Architecture:** Add `image/fixture/workload.json` and make `ipython_workload.py` strictly parse canonical bytes, expose the workload digest, and preserve the final result hash as an independent value. The first task establishes this source of truth only; all runtime consumers migrate in a later atomic task so there is no partial fallback.

**Tech Stack:** Python 3.12 standard library JSON/SHA-256 and `unittest`.

## Global Constraints

- Workload bytes contain no prompt, credential, path, command, provider/model selection, or environment value.
- The workload digest and expected result digest must differ; the latter remains the exact canonical completion result identity.
- No Docker, network, provider, subprocess, image build, or production execution is invoked.
- Tests are representative: golden identity, one malformed/canonicality rejection, and result/workload separation.

### Task 1: Canonical image-resident P1 workload

**Files:**

- Create: `src/asterion/applications/prime_agent/operator/image/fixture/workload.json`
- Modify: `src/asterion/applications/prime_agent/operator/ipython_workload.py`
- Modify: `tests/test_prime_ipython_launcher_protocol.py`
- Create or Modify: `tests/test_prime_ipython_workload.py`

**Interfaces:**

- Produces `prime_ipython_coding_workload_bytes() -> bytes`, `PRIME_IPYTHON_CODING_WORKLOAD_DIGEST`, `PRIME_IPYTHON_CODING_EXPECTED_RESULT_SHA256`, and `is_prime_ipython_coding_workload(value: object) -> bool`.

- [ ] **Step 1: Write RED tests.** Assert the workload file is canonical exact JSON, its parsed object has all fixed fields, `prime_ipython_coding_workload_bytes()` equals file bytes, digest equals SHA-256 of those bytes with `sha256:` prefix, expected result is the existing `f4eb…`, and the two differ. Assert a noncanonical or altered test byte sequence is rejected through a parser helper.

- [ ] **Step 2: Run RED.** `uv run python -m unittest -v tests.test_prime_ipython_workload tests.test_prime_ipython_launcher_protocol`

- [ ] **Step 3: Implement minimal strict workload parser.** Read only package-relative fixture bytes, require exact UTF-8 canonical JSON and exact keys/values/relations, derive SHA-256 from bytes, expose the independent expected-result digest, and retain a strict workload selector. No runtime frame or launcher behavior changes in this task.

- [ ] **Step 4: Run GREEN and commit.** `uv run python -m unittest -v tests.test_prime_ipython_workload tests.test_prime_ipython_launcher_protocol && uv run ruff check src/asterion/applications/prime_agent/operator/ipython_workload.py tests/test_prime_ipython_workload.py tests/test_prime_ipython_launcher_protocol.py && uv run pyright src/asterion/applications/prime_agent/operator/ipython_workload.py tests/test_prime_ipython_workload.py tests/test_prime_ipython_launcher_protocol.py && git diff --check`; commit `feat: define canonical Prime P1 workload identity`.

### Task 2: Atomic consumer and lock migration

**Deferred until Task 1 review:** Update launcher, fixture/application lock, request contract (new version), host supervisors, authority admission, seccomp-policy identity, and all affected tests in one no-fallback change. Rebuild/promote image and seccomp inputs separately; no existing image gains `basic` eligibility from static code migration alone.
