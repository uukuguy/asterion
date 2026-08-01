# 工作流证据运行时接入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让任意 Asterion 应用可选择地记录每一次真实 runtime 调用的内容安全、可验证证据，并让产品层能在显式目录中保存该证据。

**Architecture:** 在 framework 层增加 `ObservedRuntimeClient`：它透明代理一个既有 `AgentRuntimeClient`，在每个已闭合、已验证的 `asterion.agent-runtime/v1` 流终止后投影 `workflow-evidence/v1`；若调用未生成闭合流，则只产生固定类别的无内容失败记录。观察器由宿主显式创建和读取，runner 不写文件、不选择路径、不授权。CLI 只是首个通用宿主，使用显式参数把观察记录保存到 operator-owned 目标。

**Tech Stack:** Python 3.12、`unittest`、`asterion.agent-runtime/v1`、`asterion.workflow-evidence/v1`。

## Global Constraints

- framework 不得 import `capabilities.dci`、benchmark、论文或产品路径。
- runner 不发现、持久化、授权、调度或选择 evidence root。
- 公开记录不得包含输入文本、prompt、答案、工具参数/输出、artifact URI、凭据、异常原文或私有路径。
- 合法 runtime 流仍由现有协议校验；观察器不得放宽该协议。
- 所有摘要、数组和 JSON 输出保持确定性、规范排序；不一致输入 fail closed。
- 以 `unittest` 测试先行，分别观察 RED 和 GREEN；完成后执行 `make test`、`make lint`、`make docs-check`、`make check`。

---

### Task 1: 增加透明的通用 runtime 观察器

**Files:**
- Create: `src/asterion/workflow_evidence/runtime.py`
- Modify: `src/asterion/workflow_evidence/__init__.py`
- Test: `tests/test_workflow_evidence_runtime.py`

**Interfaces:**
- Consumes: `AgentRuntimeClient`、`RunRequest`、可选 `CancellationSignal`。
- Produces: `ObservedRuntimeClient(runtime)`，其 `.manifest` 与被代理 runtime 相同，`.records` 返回按调用顺序的不可变 `tuple[Mapping[str, object], ...]`。
- Each successful record is a valid `asterion.workflow-evidence/v1`; an unsuccessful attempt record has schema `asterion.workflow-observation/v1`, `status` of `failed` or `cancelled`, run ID, input digest, and a fixed `failure_class`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_records_a_validated_runtime_stream_without_input_or_uri(self) -> None:
    observed = ObservedRuntimeClient(CompletedRuntime())
    events = [event async for event in observed.run(
        RunRequest(run_id="run-1", input_text="SECRET_INPUT")
    )]
    self.assertEqual(events[-1].type, "run.completed")
    record = observed.records[0]
    self.assertEqual(record["schema"], "asterion.workflow-evidence/v1")
    self.assertNotIn("SECRET_INPUT", json.dumps(record))
    self.assertNotIn("file:///private", json.dumps(record))
```

Add separate tests proving: (a) unmatched/invalid events are yielded according to normal runtime behavior but leave no trusted graph; (b) a raised runtime exception creates only `failure_class: "runtime-invocation-failed"`; (c) cancellation creates only `failure_class: "runtime-cancelled"`; and (d) a second invocation preserves deterministic call order.

- [ ] **Step 2: Run tests to verify RED**

Run: `uv run python -m unittest -v tests.test_workflow_evidence_runtime`

Expected: FAIL because `ObservedRuntimeClient` is not importable.

- [ ] **Step 3: Write minimal implementation**

Implement `ObservedRuntimeClient` as an `AgentRuntimeClient` proxy. During `.run`, retain mappings only until the wrapped async iterator ends, then use `collect_workflow_evidence(events, input_digest=sha256(request.input_text))`; yield the original `RunEvent` objects unchanged. If the wrapped iterator raises before a verified terminal stream, append a fixed-class observation without exception text and re-raise unchanged. Use a private list and expose a tuple snapshot; do not write a file or alter runtime capabilities.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `uv run python -m unittest -v tests.test_workflow_evidence_runtime tests.test_workflow_evidence`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/workflow_evidence tests/test_workflow_evidence_runtime.py
git commit -m "feat: observe runtime workflow evidence"
```

### Task 2: 提供显式、安全的 observation bundle 写入器

**Files:**
- Create: `src/asterion/workflow_evidence/storage.py`
- Modify: `src/asterion/workflow_evidence/__init__.py`
- Test: `tests/test_workflow_evidence_storage.py`

**Interfaces:**
- Consumes: a selected non-existent `Path` named `workflow-evidence.json` and `tuple[Mapping[str, object], ...]` from `ObservedRuntimeClient.records`.
- Produces: canonical `asterion.workflow-observation-bundle/v1` JSON with ordered records and bundle SHA-256.

- [ ] **Step 1: Write the failing tests**

```python
def test_writes_canonical_observation_bundle_to_explicit_new_file(self) -> None:
    path = Path(self.temp_dir) / "workflow-evidence.json"
    write_workflow_observation_bundle(path, (completed_record,))
    bundle = json.loads(path.read_text())
    self.assertEqual(bundle["schema"], "asterion.workflow-observation-bundle/v1")
    self.assertEqual(bundle["records"], [completed_record])
```

Add separate tests proving an existing/symlink/noncanonical target is rejected without modification and a malformed record leaves no target file.

- [ ] **Step 2: Run tests to verify RED**

Run: `uv run python -m unittest -v tests.test_workflow_evidence_storage`

Expected: FAIL because the storage module is absent.

- [ ] **Step 3: Write minimal implementation**

Validate every completed record with `validate_workflow_evidence`. Validate failed/cancelled records with a private strict shape checker that permits only schema, run ID, input digest, status and fixed failure class. Reject duplicate run IDs, an invalid target, a missing parent directory, existing file and symbolic link. Serialize only after all validation succeeds with `sort_keys=True` and compact separators; open with exclusive creation. Do not create directories or include target paths in errors.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `uv run python -m unittest -v tests.test_workflow_evidence_storage`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/workflow_evidence tests/test_workflow_evidence_storage.py
git commit -m "feat: store explicit workflow observation bundles"
```

### Task 3: 由通用 CLI 显式启用观察器

**Files:**
- Modify: `src/asterion/cli.py`
- Modify: `tests/test_asterion_cli.py`
- Modify: `docs/cli.md`
- Modify: `docs/guides/asterion-capability-usage.md`

**Interfaces:**
- Consumes: `asterion run --workflow-evidence-file /operator/root/workflow-evidence.json`。
- Produces: normal existing public result plus an opt-in observation bundle only after execution reaches a final result or raises; no file in default mode.

- [ ] **Step 1: Write the failing tests**

```python
def test_run_parser_accepts_workflow_evidence_file(self) -> None:
    args = _parser().parse_args([
        "run", "--provider", "fixture",
        "--workflow-evidence-file", "workflow-evidence.json",
    ])
    self.assertEqual(args.workflow_evidence_file, "workflow-evidence.json")
```

Add an execution test with `DciPiFixtureRuntime` that asserts the file contains a completed safe graph and does not contain `SECRET-RUNTIME-DELTA`; add a preflight test proving an invalid output target leaves `runtime.requests == []`; add a default-mode test proving no bundle appears.

- [ ] **Step 2: Run tests to verify RED**

Run: `uv run python -m unittest -v tests.test_asterion_cli.AsterionCliTests.test_run_parser_accepts_workflow_evidence_file`

Expected: FAIL because the argument is unrecognized.

- [ ] **Step 3: Write minimal implementation**

Add the optional parser argument. In the application execution path, validate the target before opening services or constructing the runtime. When supplied, construct `ObservedRuntimeClient(runtime)` and pass it to `run_composed_application`. Use `try/finally` around that call so the CLI writes the observed bundle after either success or runtime-originated failure, without changing stdout's existing projection or swallowing the original error. Default mode passes the unwrapped runtime and writes nothing.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `uv run python -m unittest -v tests.test_asterion_cli`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/cli.py tests/test_asterion_cli.py docs/cli.md docs/guides/asterion-capability-usage.md
git commit -m "feat: export opt-in workflow observations from cli"
```

### Task 4: DCI Bright 只作为证据消费者完成首个诊断报告

**Files:**
- Create: `src/asterion/capabilities/dci/implementation/evaluation/workflow_report.py`
- Create: `tests/test_dci_workflow_report.py`
- Modify: `docs/status/DCI-BENCHMARK-INSTANCES.md`

**Interfaces:**
- Consumes: verified generic observation bundles, an exact DCI metric contract and digest-only source-lock/config identities.
- Produces: a Chinese public report containing observed facts, non-comparability, missing evidence, and a non-executing paired-experiment proposal.

- [ ] **Step 1: Write the failing test**

```python
def test_bright_report_marks_paper_score_unaligned_without_matching_scope(self) -> None:
    report = build_bright_workflow_report(bundle, paper_reference=reference)
    self.assertEqual(report["comparison"]["status"], "not-comparable")
    self.assertNotIn("SECRET", json.dumps(report))
```

- [ ] **Step 2: Run test to verify RED**

Run: `uv run python -m unittest -v tests.test_dci_workflow_report`

Expected: FAIL because the report builder does not exist.

- [ ] **Step 3: Write minimal implementation**

Call only generic validation, comparison, diagnosis and proposal functions; DCI attaches its exact metric contract and selected-range count. It must never infer a causal discrepancy from score alone, expose private evidence, or execute a proposal.

- [ ] **Step 4: Run test to verify GREEN**

Run: `uv run python -m unittest -v tests.test_dci_workflow_report`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/capabilities/dci tests/test_dci_workflow_report.py docs/status/DCI-BENCHMARK-INSTANCES.md
git commit -m "feat(dci): report bright workflow evidence"
```

### Task 5: 完整验证与推荐核验包收口

**Files:**
- Modify: `docs/status/DCI-BENCHMARK-INSTANCES.md`
- Modify: `docs/status/RESUME-NEXT-SESSION.md`

- [ ] **Step 1: Run focused framework and DCI suites**

Run: `uv run python -m unittest -v tests.test_workflow_evidence tests.test_workflow_evidence_runtime tests.test_workflow_evidence_storage tests.test_asterion_cli tests.test_dci_workflow_report`

Expected: PASS.

- [ ] **Step 2: Run repository gates**

Run: `make test && make lint && make docs-check && make check`

Expected: all PASS.

- [ ] **Step 3: Verify live package evidence**

For each completed Bright/SciFact/Bamboogle batch: confirm selected/total count, failure count, metric contract, source lock, artifact inventory and no-key resume. Bamboogle may only be started after the no-content Judge connectivity probe succeeds.

- [ ] **Step 4: Commit status and verification evidence**

```bash
git add docs/status
git commit -m "docs(dci): record validation package closure"
```

