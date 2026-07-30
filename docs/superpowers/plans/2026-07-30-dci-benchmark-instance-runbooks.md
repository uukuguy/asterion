# DCI Benchmark Instance Runbooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the DCI instance backlog into the authoritative, synchronized, directly executable runbook for every implemented instance.

**Architecture:** Keep the immutable inventory table as the status authority and add one runbook section for each catalog entry whose `implementation_state` is `implemented`. Enforce the relationship with a repository test so future instance promotion cannot land without operating instructions.

**Tech Stack:** Markdown, Python `unittest`, `asterion-dci`, POSIX shell, `jq`

## Global Constraints

- `planned` instances expose no runnable command.
- Every `implemented` instance has a matching runbook in `docs/status/DCI-BENCHMARK-INSTANCES.md`.
- Copyable commands use quoted absolute paths rooted at `"$PWD"`.
- A fresh run ID is extracted from the current run result; historical run IDs never appear in copyable commands.
- Locking and planning remain provider-free.
- Real execution remains explicitly authorized, finite, and separate from documentation verification.
- `docs/status/JOURNAL.md` remains append-only and outside feature commits.
- Inventory headings, table labels, explanations, boundaries, and
  troubleshooting are Chinese; exact identifiers, commands, environment
  variables, JSON fields, file names, and literal status values remain
  unchanged.
- The local fixture is identified as framework verification, the one-case
  Bamboogle path as a bounded capability check, and only the fifty-case
  `--all-cases` workflow as the complete GitHub sample evaluation.

---

### Task 1: Enforce catalog-to-runbook synchronization

**Files:**
- Modify: `tests/test_dci_benchmark_instances.py`
- Test: `tests/test_dci_benchmark_instances.py`

**Interfaces:**
- Consumes: `benchmark_instances() -> tuple[DciBenchmarkInstance, ...]`
- Produces: a repository invariant connecting `implementation_state` to Markdown runbook headings

- [ ] **Step 1: Write the failing synchronization test**

Add `PROJECT` and `RUNBOOK` constants after `EXPECTED_SELECTORS`, then add this
test to `TestDciBenchmarkInstances`:

```python
PROJECT = Path(__file__).resolve().parents[1]
RUNBOOK = PROJECT / "docs/status/DCI-BENCHMARK-INSTANCES.md"


def test_instance_runbooks_match_implemented_catalog_entries(self) -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    implemented = {
        instance.selector
        for instance in benchmark_instances()
        if instance.implementation_state == "implemented"
    }
    planned = {
        instance.selector
        for instance in benchmark_instances()
        if instance.implementation_state == "planned"
    }

    for selector in implemented:
        with self.subTest(selector=selector):
            self.assertIn(f"## Runbook: `{selector}`", text)
    for selector in planned:
        with self.subTest(selector=selector):
            self.assertNotIn(f"## Runbook: `{selector}`", text)
    self.assertIn('export DCI_RUN_ROOT="$PWD/outputs/manual/', text)
    self.assertIn(
        'export DCI_RUN_ID="$(jq -er \'.run_id\' "$DCI_RUN_RESULT")"',
        text,
    )
    self.assertNotRegex(text, r"--run-id\s+run-[0-9a-f]{32}")
    self.assertNotRegex(
        text,
        r"--(?:capability-source-lock|evidence-root)\s+FRESH_",
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_benchmark_instances.TestDciBenchmarkInstances.test_instance_runbooks_match_implemented_catalog_entries
```

Expected: FAIL because neither implemented selector has a `## Runbook:` heading
and the document still contains relative `FRESH_*` paths.

- [ ] **Step 3: Commit the red test with the documentation implementation**

Do not commit the red state separately. Continue to Task 2 and include this test
in the documentation commit.

---

### Task 2: Publish complete executable runbooks

**Files:**
- Modify: `docs/status/DCI-BENCHMARK-INSTANCES.md`
- Modify: `docs/OPERATOR-GUIDE.md`
- Test: `tests/test_dci_benchmark_instances.py`

**Interfaces:**
- Consumes: the two implemented selectors, their application/suite/task
  metadata, CLI lock/plan/run/resume commands, and operator preflight
- Produces: two complete operator workflows and one stable link from the
  operator guide

- [ ] **Step 1: Replace the historical command block with an execution contract**

After the inventory table, state:

```markdown
## How to use this document

Only instances marked `implemented` are executable. Each implemented row must
have a matching runbook below. Commands run from the repository root. Lock and
evidence paths are absolute, and every new run creates its own evidence root.

Lock and plan are metadata-only. A command containing `--execute` may access the
models, network, datasets, and corpora named by that instance and requires a new
finite authorization.
```

- [ ] **Step 2: Add the local fixture runbook**

Add a `## Runbook: dci.local-fixture@1.0.0` section explaining that it exercises
all fifteen package bindings without Agent, Judge, network, corpus, or external
dataset operations. Include these exact commands:

```bash
export DCI_RUN_ROOT="$PWD/outputs/manual/dci-local-fixture-$(date +%Y%m%d-%H%M%S)"
export DCI_SOURCE_LOCK="$DCI_RUN_ROOT/source-lock.json"
export DCI_EVIDENCE_ROOT="$DCI_RUN_ROOT/evidence"
export DCI_RUN_RESULT="$DCI_RUN_ROOT/run-result.json"
mkdir -p "$DCI_RUN_ROOT"

uv run asterion-dci benchmark lock \
  --instance dci.local-fixture@1.0.0 \
  --output "$DCI_SOURCE_LOCK"

uv run asterion-dci benchmark plan \
  --instance dci.local-fixture@1.0.0 \
  --case-limit 1 \
  --capability-source-lock "$DCI_SOURCE_LOCK"

uv run asterion-dci benchmark run \
  --instance dci.local-fixture@1.0.0 \
  --case-limit 1 \
  --capability-source-lock "$DCI_SOURCE_LOCK" \
  --evidence-root "$DCI_EVIDENCE_ROOT" \
  --execute | tee "$DCI_RUN_RESULT"

export DCI_RUN_ID="$(jq -er '.run_id' "$DCI_RUN_RESULT")"

uv run asterion-dci benchmark resume \
  --instance dci.local-fixture@1.0.0 \
  --run-id "$DCI_RUN_ID" \
  --case-limit 1 \
  --capability-source-lock "$DCI_SOURCE_LOCK" \
  --evidence-root "$DCI_EVIDENCE_ROOT" \
  --execute
```

Document the expected `completed` status, fifteen completed tasks, zero
provider operations, and private evidence under
`"$DCI_EVIDENCE_ROOT/runs/$DCI_RUN_ID"`.

- [ ] **Step 3: Add the real bounded Bamboogle runbook**

Add a `## Runbook: dci.qa.bamboogle.github-sample50@1.0.0` section explaining
its one QA task, default one-case range, finite fifty-case catalog, Pi Agent,
independent Judge, corpus, dataset, network, credentials, and bounded cost.
Require:

```bash
uv run asterion-dci preflight --env-file "$PWD/.env"
```

Then include:

```bash
export DCI_RUN_ROOT="$PWD/outputs/manual/dci-bamboogle-$(date +%Y%m%d-%H%M%S)"
export DCI_SOURCE_LOCK="$DCI_RUN_ROOT/source-lock.json"
export DCI_EVIDENCE_ROOT="$DCI_RUN_ROOT/evidence"
export DCI_RUN_RESULT="$DCI_RUN_ROOT/run-result.json"
mkdir -p "$DCI_RUN_ROOT"

uv run asterion-dci benchmark lock \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --output "$DCI_SOURCE_LOCK"

uv run asterion-dci benchmark plan \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --case-limit 1 \
  --capability-source-lock "$DCI_SOURCE_LOCK"

uv run asterion-dci benchmark run \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --case-limit 1 \
  --capability-source-lock "$DCI_SOURCE_LOCK" \
  --evidence-root "$DCI_EVIDENCE_ROOT" \
  --execute | tee "$DCI_RUN_RESULT"

export DCI_RUN_ID="$(jq -er '.run_id' "$DCI_RUN_RESULT")"

uv run asterion-dci benchmark resume \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --run-id "$DCI_RUN_ID" \
  --case-limit 1 \
  --capability-source-lock "$DCI_SOURCE_LOCK" \
  --evidence-root "$DCI_EVIDENCE_ROOT" \
  --execute
```

State that only `run` performs the bounded Agent/Judge work, resume reuses the
same evidence, `--all-cases` plans fifty cases but must not be substituted
without separate authorization, and inherited environment values override
`.env`.

- [ ] **Step 4: Preserve historical evidence without executable old IDs**

Retain a short `## Verification evidence` section naming the verified main
run, date, one Agent operation, one Judge operation, one correct result, and
zero-work resume. Present the run ID as prose only; never place it after a
copyable `--run-id`.

- [ ] **Step 5: Add troubleshooting and guide linkage**

Add a troubleshooting section covering exact remedies:

```markdown
- `benchmark source lock is invalid`: use a quoted absolute path such as
  `"$PWD/.../source-lock.json"`.
- Resume cannot find or match a run: use the run ID and evidence root produced
  by the same `run` command.
- Provider authentication unexpectedly fails: inspect inherited process
  variables because they override values loaded from `.env`.
- A planned instance is rejected: implement and promote it before attempting
  lock, plan, or run.
```

Change the final operator-guide link description from “instance backlog” to
“instance inventory and executable runbooks.”

- [ ] **Step 6: Run the focused tests**

Run:

```bash
uv run python -m unittest -v tests.test_dci_benchmark_instances
uv run python tools/check_docs.py
```

Expected: all instance tests pass and the documentation checker reports all
Markdown files and local links valid.

- [ ] **Step 7: Commit**

```bash
git add \
  tests/test_dci_benchmark_instances.py \
  docs/status/DCI-BENCHMARK-INSTANCES.md \
  docs/OPERATOR-GUIDE.md
git commit -m "docs: publish executable DCI instance runbooks"
```

---

### Task 3: Execute provider-free command verification

**Files:**
- Verify only: `docs/status/DCI-BENCHMARK-INSTANCES.md`

**Interfaces:**
- Consumes: the exact lock/plan commands published by Task 2
- Produces: fresh evidence that both implemented runbooks are syntactically and
  semantically valid without model, Judge, network, or external data access

- [ ] **Step 1: Verify local-fixture lock and plan**

Run:

```bash
VERIFY_ROOT="$(mktemp -d)"
uv run asterion-dci benchmark lock \
  --instance dci.local-fixture@1.0.0 \
  --output "$VERIFY_ROOT/local-lock.json"
uv run asterion-dci benchmark plan \
  --instance dci.local-fixture@1.0.0 \
  --case-limit 1 \
  --capability-source-lock "$VERIFY_ROOT/local-lock.json"
```

Expected: lock succeeds and plan reports the local application, `case_limit: 1`,
and fifteen tasks.

- [ ] **Step 2: Verify Bamboogle lock and bounded plan**

Run:

```bash
uv run asterion-dci benchmark lock \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --output "$VERIFY_ROOT/bamboogle-lock.json"
uv run asterion-dci benchmark plan \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --case-limit 1 \
  --capability-source-lock "$VERIFY_ROOT/bamboogle-lock.json"
```

Expected: lock succeeds and plan reports
`dci.qa.bamboogle.github-sample50@1.0.0`, `case_limit: 1`, and exactly one task.

- [ ] **Step 3: Run final repository gates**

Run:

```bash
uv run ruff check tests/test_dci_benchmark_instances.py
git diff --check
make check
```

Expected: all commands pass. Do not execute the real Bamboogle `run` command as
part of documentation verification.

---

### Task 4: Localize the inventory and add the complete Bamboogle evaluation

**Files:**
- Modify: `tests/test_dci_benchmark_instances.py`
- Modify: `docs/status/DCI-BENCHMARK-INSTANCES.md`
- Test: `tests/test_dci_benchmark_instances.py`

**Interfaces:**
- Consumes: the implemented-instance/runbook invariant and Bamboogle's exact
  finite `all_case_count=50`
- Produces: a Chinese operator document with distinct one-case and complete
  fifty-case workflows

- [ ] **Step 1: Write the failing localization and complete-workflow test**

Change the implemented heading assertion to:

```python
self.assertIn(f"## 运行手册：`{selector}`", text)
```

Change the planned heading assertion to:

```python
self.assertNotIn(f"## 运行手册：`{selector}`", text)
```

Add these assertions:

```python
self.assertIn("# DCI Benchmark 实例", text)
self.assertIn("## 如何使用本文档", text)
self.assertIn("### 完整 50 案例评估", text)
self.assertIn(
    'export DCI_FULL_RUN_ROOT="$PWD/outputs/manual/',
    text,
)
self.assertGreaterEqual(text.count("--all-cases"), 4)
self.assertIn(
    'jq \'{counts,accuracy}\' "$DCI_FULL_SUMMARY"',
    text,
)
self.assertIn("不产生原 DCI benchmark 评估分数", text)
self.assertIn("尚未实现", text)
```

- [ ] **Step 2: Run the focused test to verify RED**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_benchmark_instances.TestDciBenchmarkInstances.test_instance_runbooks_match_implemented_catalog_entries
```

Expected: FAIL because the document still uses English headings, has no
complete fifty-case execution root, and does not show aggregate summary
extraction.

- [ ] **Step 3: Translate explanatory content while preserving contracts**

Translate the title, introduction, table headers and operator-facing status
phrases, all prose headings, dependency/cost explanations, verification
boundaries, and troubleshooting into Chinese. Keep immutable selectors, CLI
commands, flags, environment-variable names, JSON fields, file names, and
literal verification states exact.

State explicitly:

```markdown
`dci.local-fixture@1.0.0` 是 provider-free 的框架闭环夹具，不产生原 DCI
benchmark 评估分数。
```

State that one-case Bamboogle execution verifies only the real Agent/Judge
path, while `dci.qa.bamboogle.paper-full125@1.0.0` remains planned and cannot
produce the original paper's 125-case result.

- [ ] **Step 4: Add the complete fifty-case workflow**

Add a `### 完整 50 案例评估` subsection with:

```bash
export DCI_FULL_RUN_ROOT="$PWD/outputs/manual/dci-bamboogle-full50-$(date +%Y%m%d-%H%M%S)"
export DCI_FULL_SOURCE_LOCK="$DCI_FULL_RUN_ROOT/source-lock.json"
export DCI_FULL_EVIDENCE_ROOT="$DCI_FULL_RUN_ROOT/evidence"
export DCI_FULL_RUN_RESULT="$DCI_FULL_RUN_ROOT/run-result.json"
mkdir -p "$DCI_FULL_RUN_ROOT"

uv run asterion-dci benchmark lock \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --output "$DCI_FULL_SOURCE_LOCK"

uv run asterion-dci benchmark plan \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --all-cases \
  --capability-source-lock "$DCI_FULL_SOURCE_LOCK"

uv run asterion-dci benchmark run \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --all-cases \
  --capability-source-lock "$DCI_FULL_SOURCE_LOCK" \
  --evidence-root "$DCI_FULL_EVIDENCE_ROOT" \
  --execute | tee "$DCI_FULL_RUN_RESULT"

export DCI_FULL_RUN_ID="$(jq -er '.run_id' "$DCI_FULL_RUN_RESULT")"

uv run asterion-dci benchmark resume \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --run-id "$DCI_FULL_RUN_ID" \
  --all-cases \
  --capability-source-lock "$DCI_FULL_SOURCE_LOCK" \
  --evidence-root "$DCI_FULL_EVIDENCE_ROOT" \
  --execute

export DCI_FULL_SUMMARY="$DCI_FULL_EVIDENCE_ROOT/outputs/$DCI_FULL_RUN_ID/qa.bamboogle.github-sample50/summary.json"
jq '{counts,accuracy}' "$DCI_FULL_SUMMARY"
```

Explain that this authorizes at most fifty Agent and fifty Judge operations,
produces the GitHub sample50 aggregate accuracy, and still does not reproduce
the planned paper-full125 result.

- [ ] **Step 5: Verify GREEN and provider-free boundaries**

Run:

```bash
uv run python -m unittest -v tests.test_dci_benchmark_instances
uv run python tools/check_docs.py
VERIFY_ROOT="$(mktemp -d)"
uv run asterion-dci benchmark lock \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --output "$VERIFY_ROOT/bamboogle-lock.json"
uv run asterion-dci benchmark plan \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --all-cases \
  --capability-source-lock "$VERIFY_ROOT/bamboogle-lock.json"
```

Expected: tests and docs pass; plan reports `case_limit: 50`; no Agent, Judge,
network, dataset-body, or corpus-body operation runs.

- [ ] **Step 6: Commit**

```bash
git add \
  tests/test_dci_benchmark_instances.py \
  docs/status/DCI-BENCHMARK-INSTANCES.md
git commit -m "docs: localize complete DCI benchmark runbooks"
```
