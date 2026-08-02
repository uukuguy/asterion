# Pathlight DCI 历史证据回收与 Bright 差分诊断实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不重跑模型的前提下，把 Bright 四项、SciFact 和 Bamboogle 的既有全量 evidence 转换为可验证的 Pathlight 逐例实验记录，生成一份区分事实、假设、不可比较项和证据缺口的中文差分诊断及受控小样本 proposal。

**Architecture:** 先在 framework 层增加领域中立的 DatasetSnapshot、EvaluatorContract、Variant、ExperimentPlan、CaseTrial、Finding 和 Proposal 契约；再由 DCI 产品适配器以 descriptor-relative、字段白名单方式读取显式指定的历史 artifact root。DCI 适配器只向 Pathlight 写入摘要、计数、microunits、nanoseconds 和 digest；论文分数只作为外部 reference，Opik、provider、模型和网络均不参与本阶段。

**Tech Stack:** Python 3.14、`dataclasses`、`Decimal`、descriptor-relative POSIX file I/O、现有 `asterion.pathlight`、`unittest`、ruff、Pyright。

## Global Constraints

- Framework 模块不得导入 DCI；DCI 可以依赖 Pathlight 公共契约。
- 默认 API、CLI、JSON、Markdown 不得包含 prompt、answer、corpus text、query text、Judge reason、tool/model payload、credential、artifact URI 或 private path。
- 历史输入必须由调用者显式指定 exact root；不得扫描 `outputs/`、猜测最新运行、跟随 symlink 或读取相邻目录。
- `analysis.json` 只能按固定字段白名单投影；绝不能复制整行或对未知字段做透传。
- 既有 evidence 没有完整 ContextFrame 或可用 trajectory coverage 时必须记录 `missing`，不能伪造 span、coverage 或因果根因。
- 论文 target 与 Asterion 运行允许展示同 dataset/metric 的 numeric reference gap，但配置不一致时状态必须是 `reference-only`，不能称为论文复现比较。
- Bright 与 SciFact 的分数不能跨 dataset 聚合比较；只允许做明确标注的 workflow cohort observation。Bamboogle accuracy 只作为 Agent/Judge 健康锚点。
- 所有新记录不可变、内容寻址、数组排序唯一；malformed、hostile Mapping、digest mismatch、identity mismatch 和 partial write 均 fail closed 且不泄漏 cause text。
- 写入采用 explicit target、`O_EXCL`、`O_NOFOLLOW`、`fchmod(0600)`；输出目录可以已存在，但目标文件必须不存在，失败后不得 pathname unlink 可能被替换的文件。
- 本计划不调用 provider、模型、Judge、网络或 Opik；proposal 没有 execution authority。

---

### Task 1: 建立 Pathlight 实验与逐例关联契约

**Files:**
- Create: `src/asterion/pathlight/experiment.py`
- Modify: `src/asterion/pathlight/__init__.py`
- Test: `tests/test_pathlight_experiment.py`

**Interfaces:**
- Consumes: `PathlightError`、`MetricContract`、`EvaluationRecord`。
- Produces: `SubjectRef`、`DatasetSnapshot`、`EvaluatorContract`、`Variant`、`ExperimentPlan`、`CaseTrial` 及其 `validate_*`、`to_mapping()` 和 digest 属性。

- [ ] **Step 1: 写失败测试，固定对象身份、排序和隐私边界**

```python
class PathlightExperimentTests(unittest.TestCase):
    def test_builds_digest_only_case_trial_lineage(self) -> None:
        dataset = DatasetSnapshot(
            dataset_contract_sha256=_digest("dataset-contract"),
            content_sha256=_digest("dataset-content"),
            total_count=103,
            snapshot_version="1.0.0",
        )
        evaluator = EvaluatorContract(
            metric_contract_sha256=_digest("metric"),
            evaluator_kind="recovered",
            implementation_sha256=_digest("evaluator"),
            input_contract_sha256=_digest("evaluator-input"),
            output_contract_sha256=_digest("evaluator-output"),
            failure_semantics_sha256=_digest("evaluator-failures"),
            contract_version="1.0.0",
        )
        variant = Variant(
            assembly_sha256=_digest("assembly"),
            package_set_sha256=_digest("packages"),
            implementation_sha256=_digest("implementation"),
            runtime_sha256=_digest("runtime"),
            model_sha256=_digest("model"),
            toolset_sha256=_digest("tools"),
            prompt_contract_sha256=_digest("prompt-contract"),
            policy_sha256=_digest("policy"),
            change_sha256=_digest("observation-baseline"),
        )
        trial = CaseTrial(
            experiment_plan_sha256=_digest("experiment-plan"),
            dataset_item_sha256=_digest("private-query-id"),
            variant_sha256=variant.variant_sha256,
            trace_sha256=_digest("recovered-trace"),
            evaluation_sha256s=(_digest("evaluation"),),
            evidence_state="recovered",
            missing_evidence=("context-frames", "retrieval-coverage"),
        )

        self.assertRegex(trial.case_trial_sha256, r"^[0-9a-f]{64}$")
        self.assertNotIn("private-query-id", json.dumps(trial.to_mapping()))
        self.assertEqual(trial.missing_evidence, tuple(sorted(trial.missing_evidence)))

    def test_rejects_unknown_fields_subclasses_and_noncanonical_arrays(self) -> None:
        with self.assertRaises(PathlightError):
            validate_case_trial({"schema": "asterion.pathlight-case-trial/v1"})
        with self.assertRaises(PathlightError):
            CaseTrial(
                experiment_plan_sha256=_digest("plan"),
                dataset_item_sha256=_digest("case"),
                variant_sha256=_digest("variant"),
                trace_sha256=_digest("trace"),
                evaluation_sha256s=(_digest("b"), _digest("a")),
                evidence_state="recovered",
                missing_evidence=(),
            )
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `uv run python -m unittest -v tests.test_pathlight_experiment`

Expected: FAIL，原因是 `asterion.pathlight.experiment` 尚不存在。

- [ ] **Step 3: 实现精确不可变对象**

```python
SubjectKind = Literal["trace", "span", "thread", "experiment", "case-trial"]
EvidenceState = Literal["observed", "recovered", "missing"]
EvaluatorKind = Literal["rule", "human", "judge", "recovered"]

@dataclass(frozen=True, slots=True)
class SubjectRef:
    subject_kind: SubjectKind
    subject_sha256: str
    subject_ref_sha256: str = field(init=False)

@dataclass(frozen=True, slots=True)
class DatasetSnapshot:
    dataset_contract_sha256: str
    content_sha256: str
    total_count: int
    snapshot_version: str
    parent_snapshot_sha256: str | None = None
    dataset_snapshot_sha256: str = field(init=False)

@dataclass(frozen=True, slots=True)
class EvaluatorContract:
    metric_contract_sha256: str
    evaluator_kind: EvaluatorKind
    implementation_sha256: str
    input_contract_sha256: str
    output_contract_sha256: str
    failure_semantics_sha256: str
    contract_version: str
    evaluator_contract_sha256: str = field(init=False)

@dataclass(frozen=True, slots=True)
class Variant:
    assembly_sha256: str
    package_set_sha256: str
    implementation_sha256: str
    runtime_sha256: str
    model_sha256: str
    toolset_sha256: str
    prompt_contract_sha256: str
    policy_sha256: str
    change_sha256: str
    variant_sha256: str = field(init=False)

@dataclass(frozen=True, slots=True)
class ExperimentPlan:
    dataset_snapshot_sha256: str
    scope_sha256: str
    baseline_variant_sha256: str
    candidate_variant_sha256s: tuple[str, ...]
    assignment_sha256: str
    evaluator_contract_sha256s: tuple[str, ...]
    budget_sha256: str
    stop_criteria_sha256: str
    authorization_sha256: str | None = None
    experiment_plan_sha256: str = field(init=False)

@dataclass(frozen=True, slots=True)
class CaseTrial:
    experiment_plan_sha256: str
    dataset_item_sha256: str
    variant_sha256: str
    trace_sha256: str
    evaluation_sha256s: tuple[str, ...]
    evidence_state: EvidenceState
    missing_evidence: tuple[str, ...]
    case_trial_sha256: str = field(init=False)
```

每个 `__post_init__` 必须检查 exact primitive type、SHA-256、semver、枚举、非负计数和 sorted-unique tuple，再以 canonical JSON 计算 digest。`missing_evidence` 只允许 `context-frames`、`retrieval-coverage`、`tool-payload-lineage`、`sealed-config-digest`、`sealed-analysis-digest` 和 `paper-method-detail`。

- [ ] **Step 4: 验证 GREEN 和静态检查**

Run: `uv run python -m unittest -v tests.test_pathlight_experiment tests.test_pathlight_evaluation`

Expected: PASS。

Run: `uv run ruff check src/asterion/pathlight/experiment.py tests/test_pathlight_experiment.py && uv run pyright src/asterion/pathlight/experiment.py tests/test_pathlight_experiment.py`

Expected: 0 errors。

- [ ] **Step 5: 提交**

```bash
git add src/asterion/pathlight/experiment.py src/asterion/pathlight/__init__.py tests/test_pathlight_experiment.py
git commit -m "feat: define Pathlight experiment lineage"
```

### Task 2: 持久化并查询完整 ExperimentBundle

**Files:**
- Modify: `src/asterion/pathlight/experiment.py`
- Modify: `src/asterion/cli_pathlight.py`
- Test: `tests/test_pathlight_experiment.py`
- Test: `tests/test_pathlight_cli.py`

**Interfaces:**
- Consumes: Task 1 的六类对象和现有 `EvaluationBundle`。
- Produces: `ExperimentBundle`、`write_experiment_bundle(path)`、`read_experiment_bundle(path)`、`ExperimentCatalog.show_plan()`、`list_trials()`；CLI `experiment show|trials`。

- [ ] **Step 1: 写失败测试，覆盖引用闭包和文件边界**

```python
def test_bundle_requires_complete_exact_reference_closure(self) -> None:
    bundle = ExperimentBundle.build(
        datasets=(self.dataset,),
        evaluators=(self.evaluator,),
        variants=(self.variant,),
        plans=(self.plan,),
        trials=(self.trial,),
        evaluations=(self.evaluation,),
    )
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "pathlight-experiment.json"
        write_experiment_bundle(bundle, target)
        loaded = read_experiment_bundle(target)
    self.assertEqual(loaded, bundle)
    self.assertEqual(loaded.bundle_sha256, bundle.bundle_sha256)

def test_bundle_rejects_unresolved_trial_evaluation(self) -> None:
    with self.assertRaises(PathlightError):
        ExperimentBundle.build(
            datasets=(self.dataset,), evaluators=(self.evaluator,),
            variants=(self.variant,), plans=(self.plan,),
            trials=(replace(self.trial, evaluation_sha256s=("0" * 64,)),),
            evaluations=(self.evaluation,),
        )
```

CLI 测试必须反转输入数组后仍得到相同 canonical JSON，并验证 sentinel path、prompt 和 hostile exception 不进入 stdout/stderr。

- [ ] **Step 2: 运行测试确认 RED**

Run: `uv run python -m unittest -v tests.test_pathlight_experiment tests.test_pathlight_cli`

Expected: FAIL，因为 bundle、catalog 和 CLI 子命令不存在。

- [ ] **Step 3: 实现 bundle 闭包、descriptor-safe I/O 和只读查询**

```python
@dataclass(frozen=True, slots=True)
class ExperimentBundle:
    datasets: tuple[DatasetSnapshot, ...]
    evaluators: tuple[EvaluatorContract, ...]
    variants: tuple[Variant, ...]
    plans: tuple[ExperimentPlan, ...]
    trials: tuple[CaseTrial, ...]
    evaluations: tuple[EvaluationRecord, ...]
    bundle_sha256: str

class ExperimentCatalog:
    @classmethod
    def build(cls, bundles: Sequence[ExperimentBundle]) -> ExperimentCatalog: ...
    def show_plan(self, experiment_plan_sha256: str) -> Mapping[str, object]: ...
    def list_trials(
        self, experiment_plan_sha256: str, *, evidence_state: str | None = None
    ) -> tuple[Mapping[str, object], ...]: ...
```

`ExperimentBundle.build` 必须验证 dataset/evaluator/variant/plan/trial/evaluation 的所有引用均唯一且可解析，包括每个 trial 对 experiment plan、plan baseline/candidate variant、plan dataset/evaluator 和 trial evaluation 的闭包。写入 exact filename `pathlight-experiment.json`，mode `0600`，exclusive create；读取必须拒绝 ancestor/final symlink、non-regular、wrong mode、oversize、unknown field、subclass 和 digest mismatch。

- [ ] **Step 4: 增加 provider-free CLI**

```text
asterion pathlight experiment show \
  --experiment-file /ABS/path/pathlight-experiment.json \
  --experiment-sha256 <64-hex>

asterion pathlight experiment trials \
  --experiment-file /ABS/path/pathlight-experiment.json \
  --experiment-sha256 <64-hex> [--evidence-state recovered]
```

CLI 仍只输出单行 canonical JSON；任何参数、OS、JSON 或 domain error 固定输出 `asterion pathlight: request is invalid`，且在 provider discovery 前返回。

- [ ] **Step 5: 验证并提交**

Run: `uv run python -m unittest -v tests.test_pathlight_experiment tests.test_pathlight_cli tests.test_asterion_cli`

Expected: PASS。

```bash
git add src/asterion/pathlight/experiment.py src/asterion/cli_pathlight.py tests/test_pathlight_experiment.py tests/test_pathlight_cli.py
git commit -m "feat: persist and query Pathlight experiments"
```

### Task 3: 建立 Finding、DiagnosisBundle 和非执行 Proposal 契约

**Files:**
- Create: `src/asterion/pathlight/diagnosis.py`
- Modify: `src/asterion/pathlight/__init__.py`
- Modify: `src/asterion/cli_pathlight.py`
- Test: `tests/test_pathlight_diagnosis.py`
- Test: `tests/test_pathlight_cli.py`

**Interfaces:**
- Consumes: Task 2 的 ExperimentBundle digest 和 existing EvaluationRecord identities。
- Produces: `Finding`、`Proposal`、`DiagnosisBundle`、read/write、CLI `diagnosis show` 和 `proposal list`。

- [ ] **Step 1: 写失败测试，固定事实/假设/缺口和 authority 边界**

```python
def test_proposal_is_digest_only_and_never_authority(self) -> None:
    finding = Finding(
        category="hypothesis",
        subject_sha256=_digest("bright-cohort"),
        evidence_sha256s=(_digest("observation-a"),),
        counterevidence_sha256s=(),
        confidence="medium",
        finding_code_sha256=_digest("retrieval-scale-noise"),
    )
    proposal = Proposal(
        finding_sha256=finding.finding_sha256,
        change_sha256=_digest("query-decomposition-only"),
        scope_sha256=_digest("fixed-cases"),
        success_criteria_sha256=_digest("ndcg-plus-cost-cap"),
        stop_criteria_sha256=_digest("two-infra-failures"),
        budget_sha256=_digest("max-80-agent-ops-usd-8"),
    )
    self.assertTrue(proposal.requires_operator_authorization)
    self.assertFalse(proposal.execution_authorized)
    self.assertNotIn("query-decomposition-only", json.dumps(proposal.to_mapping()))

def test_diagnosis_refuses_hypothesis_without_observed_support(self) -> None:
    with self.assertRaises(PathlightError):
        DiagnosisBundle.build(
            experiment_bundle_sha256s=(_digest("experiment-bundle"),),
            evaluation_sha256s=(_digest("evaluation"),),
            findings=(unsupported_hypothesis,),
            proposals=(),
        )
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `uv run python -m unittest -v tests.test_pathlight_diagnosis`

Expected: FAIL，因为 diagnosis module 不存在。

- [ ] **Step 3: 实现不可变诊断对象**

```python
FindingCategory = Literal["observed", "hypothesis", "not-comparable", "missing-evidence"]
Confidence = Literal["confirmed", "low", "medium", "high", "unknown"]

@dataclass(frozen=True, slots=True)
class Finding:
    category: FindingCategory
    subject_sha256: str
    evidence_sha256s: tuple[str, ...]
    counterevidence_sha256s: tuple[str, ...]
    confidence: Confidence
    finding_code_sha256: str
    finding_sha256: str = field(init=False)

@dataclass(frozen=True, slots=True)
class Proposal:
    finding_sha256: str
    change_sha256: str
    scope_sha256: str
    success_criteria_sha256: str
    stop_criteria_sha256: str
    budget_sha256: str
    status: Literal["proposed"] = "proposed"
    requires_operator_authorization: bool = True
    execution_authorized: bool = False
    proposal_sha256: str = field(init=False)

@dataclass(frozen=True, slots=True)
class DiagnosisBundle:
    experiment_bundle_sha256s: tuple[str, ...]
    evaluation_sha256s: tuple[str, ...]
    findings: tuple[Finding, ...]
    proposals: tuple[Proposal, ...]
    bundle_sha256: str
```

`DiagnosisBundle.build` 必须保存非空、sorted-unique 的 ExperimentBundle 和 EvaluationRecord identity registry；observed finding 的 evidence 必须引用 registry 中的 EvaluationRecord，hypothesis 至少引用一个已存在的 observed finding digest；Proposal 只能引用 hypothesis。missing-evidence/not-comparable finding 只能引用 registry 中的 evaluation 或 bundle 内 finding。所有引用闭包、数组和 digests 必须验证。read/write 规则与 ExperimentBundle 相同，exact filename `pathlight-diagnosis.json`。

- [ ] **Step 4: 加入只读 CLI 并验证**

```text
asterion pathlight diagnosis show --diagnosis-file /ABS/path/pathlight-diagnosis.json
asterion pathlight proposal list --diagnosis-file /ABS/path/pathlight-diagnosis.json
```

Run: `uv run python -m unittest -v tests.test_pathlight_diagnosis tests.test_pathlight_cli tests.test_workflow_diagnosis tests.test_workflow_optimization`

Expected: PASS；旧 compatibility API 保持不变。

- [ ] **Step 5: 提交**

```bash
git add src/asterion/pathlight/diagnosis.py src/asterion/pathlight/__init__.py src/asterion/cli_pathlight.py tests/test_pathlight_diagnosis.py tests/test_pathlight_cli.py
git commit -m "feat: define Pathlight diagnosis proposals"
```

### Task 4: 以字段白名单安全回收一个 DCI 历史运行

**Files:**
- Create: `src/asterion/capabilities/dci/implementation/pathlight/__init__.py`
- Create: `src/asterion/capabilities/dci/implementation/pathlight/recovery.py`
- Create: `tests/fixtures/dci/pathlight-recovery/config.json`
- Create: `tests/fixtures/dci/pathlight-recovery/batch-state.json`
- Create: `tests/fixtures/dci/pathlight-recovery/summary.json`
- Create: `tests/fixtures/dci/pathlight-recovery/analysis.json`
- Create: `tests/fixtures/dci/pathlight-recovery/results.jsonl`
- Test: `tests/test_dci_pathlight_recovery.py`

**Interfaces:**
- Consumes: explicit absolute artifact directory containing the five exact filenames above。
- Produces: `DciRecoveredRun`、`DciRecoveredCase`、`read_completed_dci_run(root: Path, expected_dataset_id: str)`。

- [ ] **Step 1: 创建含 sentinel 私有内容的最小 fixture 和失败测试**

Fixture 的 `config.json` 必须含 `cwd: "/SENTINEL_PRIVATE_PATH"` 和 dataset private identity；`analysis.json` 必须含 `query`、`gold_answer`、`final_text`、`judge_reason` sentinel，同时含两个安全逐例数值记录。

```python
def test_reader_projects_only_allowlisted_numeric_case_evidence(self) -> None:
    recovered = read_completed_dci_run(
        FIXTURE_ROOT.absolute(), expected_dataset_id="bright.biology"
    )
    public = json.dumps(recovered.to_mapping(), sort_keys=True)
    for secret in (
        "SENTINEL_PRIVATE_PATH", "SENTINEL_QUERY", "SENTINEL_ANSWER",
        "SENTINEL_FINAL", "SENTINEL_JUDGE_REASON",
    ):
        self.assertNotIn(secret, public)
    self.assertEqual(len(recovered.cases), 2)
    self.assertRegex(recovered.cases[0].dataset_item_sha256, r"^[0-9a-f]{64}$")

def test_reader_rejects_symlinks_tampering_count_mismatch_and_hostile_types(self) -> None:
    # subTest matrix: ancestor symlink, final symlink, changed file during read,
    # config/summary digest mismatch, duplicate query_id, summary/per-query count mismatch,
    # aggregate score mismatch, wrong dataset, incomplete batch, NaN/boolean numeric fields.
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `uv run python -m unittest -v tests.test_dci_pathlight_recovery`

Expected: FAIL，因为 recovery reader 不存在。

- [ ] **Step 3: 实现 descriptor-relative 五文件快照读取**

```python
@dataclass(frozen=True, slots=True)
class DciRecoveredCase:
    dataset_item_sha256: str
    metric_value_microunits: int
    run_status: Literal["completed", "failed"]
    agent_total_tokens: int
    overall_cost_microusd: int
    wall_time_ns: int
    tool_time_ns: int
    tool_call_count: int
    tool_error_count: int
    read_call_count: int
    grep_call_count: int
    read_time_ns: int
    grep_time_ns: int
    question_word_count: int
    resolution_status: Literal["available", "not-available"]
    resolution_coverage_microunits: int | None
    case_source_sha256: str

@dataclass(frozen=True, slots=True)
class DciRecoveredVariant:
    runtime_contract_sha256: str
    model_sha256: str
    toolset_sha256: str
    prompt_contract_sha256: str
    context_contract_sha256: str
    metric_contract_sha256: str
    implementation_sha256: str
    profile_sha256: str
    policy_sha256: str

@dataclass(frozen=True, slots=True)
class DciRecoveredRun:
    dataset_id: str
    mode: Literal["ir", "qa"]
    metric_name: Literal["ndcg-at-10", "accuracy"]
    metric_value_microunits: int
    selected_count: int
    total_count: int
    failed_count: int
    corpus_file_count: int
    dataset_snapshot_sha256: str
    variant: DciRecoveredVariant
    cases: tuple[DciRecoveredCase, ...]
    source_document_sha256s: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    recovered_run_sha256: str
```

只读取下列 `analysis.per_query_metrics` 字段：`query_id`（立即 domain-separated SHA-256）、`ndcg_at_10` 或 `is_correct`、`run_status`、agent token/cost、wall/tool time、tool counts/errors/durations、question word count、resolution status 和数值 coverage。tool 名只允许 `read`、`grep`。variant 只保存 runtime/model/toolset/prompt/context/metric/implementation/profile/policy 的 domain-separated digest，不保留 provider/model 名称或配置值。float 用 `Decimal(str(value))` 转为整数 microunits/nanoseconds/microusd；拒绝 NaN、Infinity、bool 和负值。

读取后必须：验证 config 中 `summary.json`/`results.jsonl` digest；逐行验证 results 与 analysis 的 query identity/status；重算逐例聚合并与 summary 在 1 microunit 内一致；验证 selected/total/failed 和 exact dataset/mode/metric。因为历史外层证据既未封存 `config.json` 本身，也未通过 config 封存 `analysis.json`，始终加入 `sealed-config-digest`、`sealed-analysis-digest` missing evidence，并把本次五文件 snapshot digest 写入 `source_document_sha256s`。

- [ ] **Step 4: 验证 GREEN 和安全扫描**

Run: `uv run python -m unittest -v tests.test_dci_pathlight_recovery`

Expected: PASS。

Run: `uv run ruff check src/asterion/capabilities/dci/implementation/pathlight/recovery.py tests/test_dci_pathlight_recovery.py && uv run pyright src/asterion/capabilities/dci/implementation/pathlight/recovery.py tests/test_dci_pathlight_recovery.py`

Expected: 0 errors。

- [ ] **Step 5: 提交**

```bash
git add src/asterion/capabilities/dci/implementation/pathlight tests/fixtures/dci/pathlight-recovery tests/test_dci_pathlight_recovery.py
git commit -m "feat: recover safe DCI run evidence"
```

### Task 5: 将 DCI recovery 转换为 Pathlight ExperimentBundle 与论文 reference

**Files:**
- Create: `src/asterion/capabilities/dci/implementation/pathlight/conversion.py`
- Modify: `src/asterion/capabilities/dci/resources/reproduction-targets.json` only if an existing exact target cannot resolve the six expected values; do not duplicate values.
- Test: `tests/test_dci_pathlight_conversion.py`

**Interfaces:**
- Consumes: `DciRecoveredRun`、existing `paper.2605.05242v1/dci-agent-cc/main` target、Task 1/2 Pathlight contracts。
- Produces: `recovered_run_to_experiment(run)`、`load_paper_reference(dataset_id)`、`DciReferenceComparison`。

- [ ] **Step 1: 写失败测试，固定六项论文值和比较语义**

```python
def test_resolves_exact_paper_references_without_copying_private_paths(self) -> None:
    expected = {
        "bright.biology": (771000, 103),
        "bright.earth-science": (690000, 116),
        "bright.economics": (468000, 103),
        "bright.robotics": (568000, 101),
        "beir.scifact": (757000, 300),
        "qa.bamboogle": (800000, 125),
    }
    for dataset_id, (score, count) in expected.items():
        with self.subTest(dataset_id=dataset_id):
            reference = load_paper_reference(dataset_id)
            self.assertEqual((reference.value_microunits, reference.total_count), (score, count))
            self.assertEqual(reference.comparison_status, "reference-only")

def test_conversion_creates_one_trial_and_evaluation_per_case(self) -> None:
    bundle = recovered_run_to_experiment(self.recovered)
    self.assertEqual(len(bundle.trials), self.recovered.selected_count)
    self.assertEqual(len(bundle.evaluations), self.recovered.selected_count + 1)
    self.assertTrue(all(trial.evidence_state == "recovered" for trial in bundle.trials))
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `uv run python -m unittest -v tests.test_dci_pathlight_conversion`

Expected: FAIL，因为 conversion module 不存在。

- [ ] **Step 3: 实现 exact reference 和一一关联转换**

`load_paper_reference` 必须从已校验的 `reproduction-targets.json` 读取 DCI-Agent-CC main target，并与 `paper-benchmarks.json` 的 source count 交叉验证。不得从 `docs/status` 反向解析分数。

`recovered_run_to_experiment` 必须创建：一个 DatasetSnapshot、一个 recovered EvaluatorContract、一个 baseline Variant、一个 observation ExperimentPlan、每 case 一个 EvaluationRecord/CaseTrial，以及一个 aggregate EvaluationRecord。每个 case scope 绑定其 dataset item digest；aggregate scope 绑定 selected ID set digest。论文 target 不写入 candidate variant，也不伪造成 trace。

- [ ] **Step 4: 验证并提交**

Run: `uv run python -m unittest -v tests.test_dci_pathlight_conversion tests.test_pathlight_experiment tests.test_pathlight_evaluation`

Expected: PASS。

```bash
git add src/asterion/capabilities/dci/implementation/pathlight/conversion.py tests/test_dci_pathlight_conversion.py
git commit -m "feat: map recovered DCI experiments"
```

### Task 6: 生成确定性的 Bright/SciFact/Bamboogle 差分诊断和 proposals

**Files:**
- Create: `src/asterion/capabilities/dci/implementation/pathlight/diagnosis.py`
- Test: `tests/test_dci_pathlight_diagnosis.py`

**Interfaces:**
- Consumes: exact 六个 `DciRecoveredRun`、六个 Pathlight ExperimentBundle、paper references。
- Produces: `diagnose_recommended_pack(runs)`、`render_chinese_diagnosis(report)`、Pathlight `DiagnosisBundle`。

- [ ] **Step 1: 写失败测试，固定事实、非因果假设和提案顺序**

```python
def test_diagnosis_separates_observed_hypothesis_missing_and_reference_only(self) -> None:
    report = diagnose_recommended_pack(self.six_runs)
    self.assertEqual(report.dataset_count, 6)
    self.assertEqual(report.total_case_count, 848)
    self.assertEqual(report.reference_gaps_microunits["bright.biology"], -325416)
    self.assertEqual(report.reference_gaps_microunits["beir.scifact"], -4569)
    self.assertEqual(report.reference_status["bright.biology"], "reference-only")
    self.assertIn("retrieval-coverage", report.missing_evidence)
    self.assertTrue(all(item.category != "observed" or item.confidence == "confirmed" for item in report.findings))
    self.assertTrue(all(proposal.execution_authorized is False for proposal in report.proposals))

def test_rendered_chinese_report_contains_no_private_fixture_sentinel(self) -> None:
    rendered = render_chinese_diagnosis(diagnose_recommended_pack(self.six_runs))
    self.assertIn("已证实事实", rendered)
    self.assertIn("待验证假设", rendered)
    self.assertIn("证据缺口", rendered)
    self.assertIn("最小受控实验", rendered)
    self.assertNotIn("SENTINEL_", rendered)
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `uv run python -m unittest -v tests.test_dci_pathlight_diagnosis`

Expected: FAIL，因为 DCI diagnosis module 不存在。

- [ ] **Step 3: 实现 deterministic cohort analyzer**

固定输出以下 observed facts：六项 selected/total/failed/metric/reference gap；Bright 四项与 SciFact 的 runtime/model/tool/prompt/context/metric component digest 相同或不同（不输出 provider/model 配置值）；corpus file count；逐项 zero-score rate、median tokens/tool calls/wall/tool time、read/grep calls/errors/time share、question word median；所有运行 `resolution.available_queries == 0` 的缺口。

只生成以下 hypothesis codes，且每项引用 observed finding digests 和 counterevidence：

1. `retrieval-scale-noise`：Bright 大语料下 grep/tool time 较高可能降低检索效率；不能由相关性确认。
2. `query-decomposition`：Bright 问题更长，literal grep/read 策略可能缺少领域查询分解。
3. `context-retention`：没有 trajectory coverage/ContextFrame，无法判断发现的 gold evidence 是否进入最终上下文。
4. `paper-method-difference`：论文 target 的 runtime/prompt/model 细节不能与当前 Asterion variant 完全对齐。

固定 proposal 顺序：

- `coverage-instrumentation`: Bright 四项各 10 case + SciFact 10 case，共 50 Agent operations；只补 trajectory coverage，max cost `$5`，连续 2 个基础设施失败即停止。
- `retrieval-query-decomposition`: 在 coverage proposal 成功后，用相同 case 做 baseline/candidate paired 80 Agent operations；唯一变量是检索 query planning，max cost `$8`；主指标 mean nDCG 至少 `+0.05`，成本/时延不得增加超过 25%。

proposal 只是 digest 契约；中文 renderer 用产品内固定 code-to-Chinese 文案，不能接受 evidence 中任意文本。

- [ ] **Step 4: 验证 determinism、隐私和提交**

Run: `uv run python -m unittest -v tests.test_dci_pathlight_diagnosis tests.test_pathlight_diagnosis`

Expected: PASS；反转 run/case 输入顺序后 JSON 和 Markdown byte-identical。

```bash
git add src/asterion/capabilities/dci/implementation/pathlight/diagnosis.py tests/test_dci_pathlight_diagnosis.py
git commit -m "feat: diagnose recovered DCI workflows"
```

### Task 7: 暴露 DCI CLI 并对六项真实历史 evidence 生成报告

**Files:**
- Modify: `src/asterion/applications/dci_agent_lite/cli.py`
- Create: `src/asterion/applications/dci_agent_lite/pathlight_cli.py`
- Test: `tests/test_dci_pathlight_cli.py`
- Create after real recovery: `docs/status/PATHLIGHT-DCI-DIAGNOSIS.md`
- Modify after real recovery: `docs/status/INDEX.md`
- Modify: `docs/status/DCI-BENCHMARK-INSTANCES.md`

**Interfaces:**
- Consumes: Tasks 4–6 APIs and explicit operator paths。
- Produces: provider-free `asterion-dci pathlight recover|diagnose` and the actual Chinese diagnosis report。

- [ ] **Step 1: 写失败 CLI 测试**

```python
def test_recover_is_provider_free_and_never_echoes_source_path(self) -> None:
    code, stdout, stderr = invoke(
        ["pathlight", "recover", "--instance", "dci.bright.biology@1.0.0",
         "--evidence-root", str(FIXTURE_ROOT.absolute()),
         "--output-root", str(self.existing_empty_output_root)],
        provider_spy=self.provider_spy,
    )
    self.assertEqual(code, 0)
    self.assertEqual(self.provider_spy.operations, 0)
    self.assertNotIn(str(FIXTURE_ROOT), stdout + stderr)
    self.assertTrue((self.existing_empty_output_root / "pathlight-experiment.json").is_file())
    self.assertTrue((self.existing_empty_output_root / "pathlight-dci-recovery.json").is_file())

def test_diagnose_requires_exact_six_distinct_recoveries(self) -> None:
    with self.assertCliFailureWithoutPathLeak():
        invoke(["pathlight", "diagnose", "--recovery-root", str(self.one_root)])
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `uv run python -m unittest -v tests.test_dci_pathlight_cli`

Expected: FAIL，因为 DCI pathlight route 不存在。

- [ ] **Step 3: 实现 provider-free CLI**

```text
asterion-dci pathlight recover \
  --instance dci.bright.biology@1.0.0 \
  --evidence-root /ABS/EXACT/ARTIFACT/LEAF \
  --output-root /ABS/EXPLICIT/RECOVERY/ROOT

asterion-dci pathlight diagnose \
  --recovery-root /ABS/biology \
  --recovery-root /ABS/earth \
  --recovery-root /ABS/economics \
  --recovery-root /ABS/robotics \
  --recovery-root /ABS/scifact \
  --recovery-root /ABS/bamboogle \
  --output-root /ABS/EXPLICIT/DIAGNOSIS/ROOT
```

`recover` 从 ExperimentBundle 中提取同一组 evaluation records，分别写 `pathlight-dci-recovery.json`、`pathlight-experiment.json` 和 `pathlight-evaluations.json`；`diagnose` 写 `pathlight-diagnosis.json` 和 `pathlight-dci-diagnosis.zh-CN.md`。output root 必须由调用者显式指定且为 operator-owned directory；允许目录已存在，但所有目标文件必须尚不存在，内部文件均 `0600`。stdout 只返回 dataset digest、case count 和 output bundle digest，不返回路径。任何错误固定为 `asterion-dci: command failed`。

- [ ] **Step 4: 用六项真实 leaf 前台执行 recovery 和 diagnose**

使用当前已验证的六个 exact leaf；每次命令前确认 `config.json` dataset ID、summary count 和 parent run result 均匹配。输出到一个新的 operator-owned `outputs/pathlight-dci-diagnosis-20260802/`，不修改原 evidence，不启动后台任务。

Expected actual aggregate:

```text
Bright Biology      103/103  nDCG@10 0.4455838605  paper 0.771
Bright Earth        116/116  nDCG@10 0.4382271738  paper 0.690
Bright Economics    103/103  nDCG@10 0.3096866129  paper 0.468
Bright Robotics     101/101  nDCG@10 0.3366641709  paper 0.568
BEIR SciFact        300/300  nDCG@10 0.7524311068  paper 0.757
Bamboogle           125/125  accuracy 0.8160000000 paper 0.800
```

若任何实际值、count、source digest 或 privacy assertion 不匹配，停止并修复 reader；不得手工改 report 数字。

- [ ] **Step 5: 发布安全中文报告并更新台账**

从生成的 safe Markdown 复制固定公开部分到 `docs/status/PATHLIGHT-DCI-DIAGNOSIS.md`，同步 `docs/status/INDEX.md`。`DCI-BENCHMARK-INSTANCES.md` 增加报告链接、诊断状态和两个 proposal 摘要，不复制 operator path、case ID 或私有内容。

- [ ] **Step 6: 验证并提交**

Run: `uv run python -m unittest -v tests.test_dci_pathlight_cli tests.test_dci_pathlight_recovery tests.test_dci_pathlight_conversion tests.test_dci_pathlight_diagnosis`

Expected: PASS，provider operations = 0，model/Judge/network operations = 0。

Run: `make docs-check`

Expected: PASS。

```bash
git add src/asterion/applications/dci_agent_lite/cli.py src/asterion/applications/dci_agent_lite/pathlight_cli.py tests/test_dci_pathlight_cli.py docs/status/PATHLIGHT-DCI-DIAGNOSIS.md docs/status/INDEX.md docs/status/DCI-BENCHMARK-INSTANCES.md
git commit -m "feat: publish Pathlight DCI diagnosis"
```

### Task 8: 完成阶段级安全审查与 promotion verification

**Files:**
- Modify only if a review finding requires it: files introduced by Tasks 1–7。
- Modify: `.superpowers/sdd/progress.md`（被 gitignore，仅作本地执行台账）。

**Interfaces:**
- Consumes: 完整 `Task 1..7` commit range。
- Produces: whole-stage review clean、完整验证证据、下一阶段 controlled experiment 输入。

- [ ] **Step 1: 生成整阶段 review package 并做独立审查**

审查必须覆盖：framework/DCI dependency direction、所有闭合 schema、descriptor safety、TOCTOU、0600/O_EXCL、hostile Mapping/subclass、异常链 redaction、field allowlist、paper reference provenance、case/evaluation 一一关联、determinism、non-comparability、proposal authority、CLI provider-free 和 sentinel privacy。

- [ ] **Step 2: 修复所有 Critical/Important finding 并由同一审查者复核**

每个修复必须先有失败测试，再有最小实现；不得把 finding 降级为文档说明。

- [ ] **Step 3: 运行完整验证**

Run:

```bash
uv run python -m unittest -v \
  tests.test_pathlight_experiment \
  tests.test_pathlight_diagnosis \
  tests.test_dci_pathlight_recovery \
  tests.test_dci_pathlight_conversion \
  tests.test_dci_pathlight_diagnosis \
  tests.test_dci_pathlight_cli
make test
make lint
make docs-check
make check
make promotion-check
```

Expected: 全部 PASS；不得以 External-limited 或 Not rerun 代替 PASS。此阶段的“未重跑模型”是计划边界，不影响 provider-free recovery/diagnosis 验证。

- [ ] **Step 4: 记录下一阶段输入而不执行 proposal**

记录 exact proposal digests、case scope digest、50/80 operation caps、`$5/$8` budgets 和 missing coverage gate。下一计划必须先实现/验证 full DCI trajectory coverage source，再请求 operator 对 `coverage-instrumentation` proposal 的显式 execution authorization。

---

## 本计划完成定义

- 六项既有 evidence 已逐例回收为验证通过的 Pathlight ExperimentBundle，合计 848 个 CaseTrial。
- 每个 aggregate/case Evaluation 都可回溯到 dataset snapshot、variant、evaluator、trial 和 recovered source digest。
- 实际中文报告含论文参照、样本总数、关键 workflow metrics、已证实事实、假设、反证、不可比较项、证据缺口和最小 proposals。
- 报告能够解释“目前证据支持什么、不能支持什么”，但不会在 coverage/ContextFrame 缺失时虚构 Bright 根因。
- 所有 provider/model/Judge/network operation 均为 0；两个 proposal 均不可执行。
- 下一阶段可直接以报告和 proposal digests 建立受控小样本 coverage/A-B 闭环。
