# DCI Provenance and Reproduction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate paper, exact GitHub, and Asterion-safe experiment semantics and connect bounded benchmark evidence to an enforceable, reproducible comparison pipeline.

**Architecture:** Every experiment profile binds one immutable source family, prompt, Judge, metric, runtime, dataset selection, context policy, and implementation digest. Paper-unreported values stay explicit; bounded execution consumes one operator-issued authority with enforced operation and cost caps, then emits a validated RunManifest accepted directly by comparison.

**Tech Stack:** Python 3.10+, `unittest`, immutable JSON resources and schemas, Pi TypeScript context extension, OpenAI-compatible Judge adapters, SHA-256 provenance, JSONL benchmark evidence.

## Global Constraints

- Source families are exactly `paper-reference`, `upstream-github/<commit>`, and `asterion-safe`.
- Never promote a GitHub behavior or Asterion default as a paper-reported method.
- Full benchmark execution requires explicit invocation authority and finite positive limits.
- Configuration, `.env`, cache, and prior evidence never grant execution authority.
- `paper describe`, `paper verify`, dry runs, setup, preflight, acceptance, tests, and checks perform zero Agent and Judge operations.
- Prompts, answers, credentials, corpus text, provider payloads, raw output, host values, and private paths stay out of public identities and reports.
- Full benchmark and paper-score claims require named passing commands and retained body-free evidence.

---

## File Structure

- `src/asterion/dci/resources/experiment-profile.schema.json` — provenance-family contract.
- `src/asterion/dci/resources/experiment-profiles.json` — immutable profile instances.
- `src/asterion/dci/experiment_profiles.py` — profile validation and execution authorization.
- `src/asterion/dci/prompts.py` — source-specific QA/IR prompt contracts.
- `src/asterion/dci/judge.py` — separate paper/GitHub/Asterion Judge adapters.
- `src/asterion/dci/metrics.py` — distinct upstream-list and deduplicated NDCG.
- `src/asterion/dci/trajectory_resolution.py` — output-grounded evidence alignment.
- `packages/typescript/dci-context-extension/` — tested L0–L4 behavior.
- `src/asterion/dci/resources/paper-*.json` — dataset, scope, ablation, and reproduction identities.
- `src/asterion/dci/reproduction.py` — authority, RunManifest compilation, and comparison.
- `src/asterion/dci/benchmark.py` — bounded execution and evidence emission.
- `tests/test_asterion_dci_benchmark.py` — profile/metric/batch behavior.
- `tests/test_asterion_dci_verification.py` — provider-free paper contract checks.
- `tests/test_dci_resolution_metrics.py` — hand-calculated resolution behavior.
- `tests/test_dci_reproduction.py` — authority, budget, manifest, and comparison.

### Task 1: Encode three provenance families

**Files:**
- Modify: `src/asterion/dci/resources/experiment-profile.schema.json`
- Modify: `src/asterion/dci/resources/experiment-profiles.json`
- Modify: `src/asterion/dci/experiment_profiles.py`
- Modify: `tests/test_asterion_dci_benchmark.py`

**Interfaces:**
- Consumes: one exact experiment profile ID.
- Produces: an immutable profile whose source family and all semantic component identities are explicit.

- [ ] **Step 1: Write schema and profile tests**

Require these fields:

```text
source_family
source_identity
prompt_contract
judge_contract
metric_contracts
runtime_contract
context_contract
dataset_selection_contract
implementation_sha256
paper_unreported_parameters
```

Assert:

```python
self.assertEqual(profile.source_family, "paper-reference")
self.assertIsNone(profile.compatible_config_key)
self.assertNotEqual(
    resolve_experiment_profile("paper-reference/pi").identity_sha256,
    resolve_experiment_profile(
        "upstream-github/271f37e71f053bf0c99c05ce6d2fb53b841d922e/pi"
    ).identity_sha256,
)
```

Reject a paper profile with a GitHub or Asterion prompt/Judge/metric identity,
an upstream profile without a 40-character lowercase commit, an Asterion
profile labelled as a published target, and any unknown unreported parameter.

- [ ] **Step 2: Run and verify failure**

```bash
uv run python -m unittest -v tests.test_asterion_dci_benchmark
```

Expected: new fields and source profiles are absent.

- [ ] **Step 3: Add immutable source identities**

Represent:

```json
{
  "source_family": "upstream-github",
  "source_identity": {
    "repository": "DCI-Agent/DCI-Agent-Lite",
    "commit": "271f37e71f053bf0c99c05ce6d2fb53b841d922e"
  }
}
```

Paper source identity is `arxiv:2605.05242v1`. Asterion source identity is the
current transitive implementation SHA from the application-authority plan.
Store only body-free IDs and hashes.

Rename `current-default/*` to `asterion-safe/*`. Add exact upstream GitHub Pi
profiles. Keep compatibility aliases only in CLI parsing and never in evidence.

- [ ] **Step 4: Regenerate and validate hashes**

Update the schema SHA constant, profile resource SHA, and all dependent
effective-config tests through the repository's canonical JSON hashing helper.
Do not hand-edit a digest without reproducing it in a test.

- [ ] **Step 5: Run and commit**

```bash
uv run python -m unittest -v tests.test_asterion_dci_benchmark
git add src/asterion/dci/resources/experiment-profile.schema.json \
  src/asterion/dci/resources/experiment-profiles.json \
  src/asterion/dci/experiment_profiles.py \
  tests/test_asterion_dci_benchmark.py
git commit -m "feat: separate DCI experiment provenance families"
```

Expected: tests pass.

### Task 2: Separate paper, GitHub, and safe prompts

**Files:**
- Create: `src/asterion/dci/prompts.py`
- Modify: `src/asterion/dci/datasets.py`
- Modify: `src/asterion/dci/benchmark.py`
- Create: `tests/fixtures/dci_prompts/paper-qa.txt`
- Create: `tests/fixtures/dci_prompts/upstream-github-qa.txt`
- Create: `tests/fixtures/dci_prompts/upstream-github-ir.txt`
- Create: `tests/fixtures/dci_prompts/asterion-safe-qa.txt`
- Modify: `tests/test_asterion_dci_benchmark.py`

**Interfaces:**
- Consumes: source family, question, canonical corpus root, and optional corpus hint.
- Produces: exact prompt body plus body-free contract ID and SHA.

- [ ] **Step 1: Capture exact golden prompt fixtures**

Transcribe the QA prompt reported in paper Appendix C1 into
`paper-qa.txt`. Capture the inspected commit's `build_benchmark_prompt()` and
`build_ir_prompt()` outputs in the upstream fixtures. Keep Asterion's extra
non-empty-final-answer sentence only in `asterion-safe-qa.txt`.

Use sentinel placeholders:

```text
__DCI_QUERY__
/__dci_prompt_contract_corpus__
__DCI_CORPUS_HINT__
```

Do not normalize wording, whitespace, punctuation, or Unicode dashes.

- [ ] **Step 2: Write golden tests**

Assert each builder output equals its fixture byte-for-byte and each contract
SHA equals the canonical hash of source family, prompt kind, and body. Assert
all three QA hashes differ.

- [ ] **Step 3: Implement the prompt registry**

Define:

```python
@dataclass(frozen=True, slots=True)
class PromptContract:
    contract_id: str
    source_family: str
    qa_builder: Callable[[str, Path], str]
    ir_builder: Callable[[str, Path, str | None], str]
    final_answer_recovery: str | None
```

`paper-reference` has no Asterion recovery prompt. `upstream-github` reproduces
the pinned commit. `asterion-safe` retains recovery and non-empty answer
instructions.

Make benchmark prompt selection depend only on the resolved profile contract.

- [ ] **Step 4: Run and commit**

```bash
uv run python -m unittest -v tests.test_asterion_dci_benchmark
git add src/asterion/dci/prompts.py src/asterion/dci/datasets.py \
  src/asterion/dci/benchmark.py tests/fixtures/dci_prompts \
  tests/test_asterion_dci_benchmark.py
git commit -m "feat: bind DCI prompts to explicit source contracts"
```

Expected: tests pass.

### Task 3: Implement three Judge contracts

**Files:**
- Modify: `src/asterion/dci/judge.py`
- Modify: `src/asterion/dci/evaluation.py`
- Modify: `src/asterion/dci/experiment_profiles.py`
- Create: `tests/test_dci_judge_contracts.py`

**Interfaces:**
- Consumes: profile Judge contract, question, gold answer, and full predicted response.
- Produces: normalized internal `JudgeVerdict` plus source-specific raw contract evidence kept private.

- [ ] **Step 1: Define normalized output**

Add:

```python
@dataclass(frozen=True, slots=True)
class JudgeVerdict:
    is_correct: bool
    extracted_final_answer: str
    reason: str
    confidence: float | None
    contract_id: str
    request_fingerprint: str
```

Confidence is required for paper Appendix C3 and `None` for contracts that do
not return it.

- [ ] **Step 2: Write exact request-shape tests**

Cover:

- paper GPT-4.1 Appendix C3 prompt and parser fields
  `Extracted_final_answer`, `Correct`, `Reasoning`, `Confidence`;
- pinned GitHub Responses API request with reasoning low, verbosity low,
  `max_output_tokens=180`, and JSON keys `is_correct`,
  `normalized_prediction`, `reason`;
- Asterion-safe strict JSON schema, configurable endpoint/model, and no raw
  response in public evidence.

Use a small numerical-answer case to assert the paper prompt's reported margin
rule. Reject cross-contract output shapes.

- [ ] **Step 3: Split adapter implementations**

Create one builder/parser pair per contract:

```python
build_paper_judge_request / parse_paper_judge_response
build_upstream_judge_request / parse_upstream_judge_response
build_safe_judge_request / parse_safe_judge_response
```

The dispatcher selects by immutable `judge_contract`; model name alone never
selects semantics.

- [ ] **Step 4: Correct misleading identities**

Reserve `dci.paper-answer-judge/gpt-4.1/v1` for the Appendix C3 request and
parser. Give the existing strict JSON contract an Asterion-owned ID. Bind the
pinned GitHub implementation to a commit-qualified ID.

- [ ] **Step 5: Run and commit**

```bash
uv run python -m unittest -v \
  tests.test_dci_judge_contracts \
  tests.test_asterion_dci_benchmark
git add src/asterion/dci/judge.py src/asterion/dci/evaluation.py \
  src/asterion/dci/experiment_profiles.py \
  tests/test_dci_judge_contracts.py tests/test_asterion_dci_benchmark.py
git commit -m "feat: implement source-specific DCI Judge contracts"
```

Expected: both suites pass without network requests.

### Task 4: Split upstream and safe NDCG identities

**Files:**
- Modify: `src/asterion/dci/metrics.py`
- Modify: `src/asterion/dci/experiment_profiles.py`
- Modify: `src/asterion/dci/benchmark.py`
- Create: `tests/test_dci_metrics.py`

**Interfaces:**
- Consumes: ranked retrieved paths, binary gold set, k, and metric contract ID.
- Produces: source-specific NDCG with explicit duplicate behavior.

- [ ] **Step 1: Write hand-calculated cases**

Use:

```python
cases = (
    (["a.txt"], {"a.txt"}, 1.0, 1.0),
    (["a.txt", "a.txt"], {"a.txt"}, 1.6309297535714575, 1.0),
    (["a.txt", "a.txt", "b.txt"], {"a.txt", "b.txt"}, 1.3065735963827292, 1.0),
)
```

The third and fourth tuple values are upstream-list and deduplicated expected
scores. Assert empty gold returns zero and query-document exclusion happens
before either metric.

- [ ] **Step 2: Implement explicit functions**

Define:

```python
def ndcg_at_k_upstream_list(
    retrieved: Sequence[str], gold_set: Set[str], k: int
) -> float:
    if not gold_set:
        return 0.0
    dcg = sum(
        1.0 / math.log2(rank + 2)
        for rank, document in enumerate(retrieved[:k])
        if document in gold_set
    )
    idcg = sum(
        1.0 / math.log2(rank + 2)
        for rank in range(min(len(gold_set), k))
    )
    return dcg / idcg if idcg else 0.0

def ndcg_at_k_deduplicated(
    retrieved: Sequence[str], gold_set: Set[str], k: int
) -> float:
    unique = tuple(dict.fromkeys(retrieved))
    return min(max(ndcg_at_k_upstream_list(unique, gold_set, k), 0.0), 1.0)
```

Only the safe function deduplicates and clamps. Keep
`compute_ir_ndcg(final_text, row, corpus_dir, k=10,
metric_contract="ndcg@10-binary-deduplicated/v1")` as the dispatcher.

- [ ] **Step 3: Bind profile identities**

Use:

```text
ndcg@10-binary-upstream-list/v1
ndcg@10-binary-deduplicated/v1
```

For paper-reference, add `duplicate_handling` to
`paper_unreported_parameters`; require the operator to select one before the
profile becomes score-comparable. Its result label must state the selected
assumption.

- [ ] **Step 4: Run and commit**

```bash
uv run python -m unittest -v \
  tests.test_dci_metrics \
  tests.test_asterion_dci_benchmark
git add src/asterion/dci/metrics.py src/asterion/dci/experiment_profiles.py \
  src/asterion/dci/benchmark.py tests/test_dci_metrics.py \
  tests/test_asterion_dci_benchmark.py
git commit -m "feat: separate upstream and safe DCI ranking metrics"
```

Expected: tests pass.

### Task 5: Align pipeline and path-only trajectory evidence

**Files:**
- Modify: `src/asterion/dci/trajectory_resolution.py`
- Modify: `src/asterion/dci/resolution_metrics.py`
- Create: `tests/test_dci_resolution_metrics.py`
- Create: `tests/fixtures/dci_trajectory/rg-head.json`
- Create: `tests/fixtures/dci_trajectory/rg-rg.json`
- Create: `tests/fixtures/dci_trajectory/path-only.json`

**Interfaces:**
- Consumes: normalized tool call/result observations plus an exact gold corpus registry.
- Produces: corpus-verified surfaced document IDs and localization spans independent of shell composition.

- [ ] **Step 1: Create golden trajectory fixtures**

Each fixture must include:

- exact tool call ID, name, arguments, and output;
- corpus document IDs, relative paths, exact bodies, and evidence spans;
- expected surfaced gold IDs;
- expected coverage any/mean/all;
- expected per-document and dataset localization.

The `rg-head` output includes `doc-a.txt:3:gold text`; `rg-rg` filters a first
`rg` output through a second `rg`; `path-only` outputs `doc-a.txt` without a
line.

- [ ] **Step 2: Write hand-calculated tests**

Assert `rg | head` and `rg | rg` surface a document based on verified output,
not because the path appears in command tokens. Assert path-only surfacing
contributes coverage and uses a full-document localization fallback. Assert a
path not present in the exact registry is ignored and a line whose text does
not match corpus bytes is ignored.

- [ ] **Step 3: Parse output before command fallback**

Refactor alignment into two named helpers:
`_output_alignments(observation, documents) -> list[dict[str, object]]` and
`_argument_fallbacks(observation, documents) -> list[dict[str, object]]`.
The first returns only corpus-verified output matches; the second returns
full-document fallback records for exact command-argument paths.

For bash, first parse verified `path:line:text`, `path:line`, and path-only
output forms. Apply command-token fallback only when no verified output
alignment exists. Shell metacharacters no longer force an early return.

- [ ] **Step 4: Label unreported localization parameters**

Remove the implication that `segment_characters=4096` and overlap `0.5` are
paper values. Carry:

```json
{
  "parameter_source": "asterion-defined",
  "segment_characters": 4096,
  "read_minimum_evidence_overlap": 0.5
}
```

Paper-reference execution requires explicit values and records them as
operator assumptions.

- [ ] **Step 5: Run and commit**

```bash
uv run python -m unittest -v tests.test_dci_resolution_metrics
git add src/asterion/dci/trajectory_resolution.py \
  src/asterion/dci/resolution_metrics.py \
  tests/test_dci_resolution_metrics.py tests/fixtures/dci_trajectory
git commit -m "fix: align DCI trajectory evidence from verified output"
```

Expected: tests pass.

### Task 6: Prove L0–L4 context behavior

**Files:**
- Modify: `packages/typescript/dci-context-extension/src/dci-context-extension.ts`
- Modify: `packages/typescript/dci-context-extension/test/extension.test.mjs`
- Modify: `packages/typescript/dci-context-extension/test/policy.test.mjs`
- Modify: `src/asterion/dci/context_profiles.py`
- Modify: `tests/test_asterion_dci_benchmark.py`

**Interfaces:**
- Consumes: immutable context profile plus Pi context/session events.
- Produces: source-labelled behavior for tool-result caps, pressure threshold, retained turns/tokens, summary gating, and failure suppression.

- [ ] **Step 1: Add golden behavioral cases**

Cover:

```text
L0: no tool cap and no compaction
L1: 50,000-character tool-result cap
L2: 20,000-character tool-result cap
L3: cap 20,000; compact only beyond 240,000; retain 12 recent turns
L4: L3 behavior; summarize only when post-compaction pressure remains;
    retain 20,000 recent tokens; stop summary attempts after 3 failures
```

Assert L3 preserves older conversational structure while replacing compacted
tool-result bodies with explicit placeholders; it must not silently delete
all older turns.

- [ ] **Step 2: Make L4 pressure explicit**

Separate `needsCompaction(messages, profile): boolean` from
`needsPostCompactionSummary(preparation, profile): boolean`.

Call built-in compaction first. Invoke summary only when estimated
post-compaction context still exceeds the configured threshold. Configure
`keepRecentTokens: 20_000` directly rather than merely checking an upstream
default.

- [ ] **Step 3: Record source parity**

Keep numeric profiles shared, but bind behavior identity separately:

```text
dci.paper-context/levelN/v1
dci.upstream-github-context/<commit>/levelN/v1
dci.asterion-safe-context/levelN/v1
```

Only mark paper parity when all golden cases corresponding to reported behavior
pass.

- [ ] **Step 4: Run and commit**

```bash
npm --prefix packages/typescript/dci-context-extension test
uv run python -m unittest -v tests.test_asterion_dci_benchmark
git add packages/typescript/dci-context-extension \
  src/asterion/dci/context_profiles.py \
  tests/test_asterion_dci_benchmark.py
git commit -m "fix: make DCI context profile behavior source explicit"
```

Expected: both suites pass.

### Task 7: Make dataset and launcher provenance explicit

**Files:**
- Modify: `src/asterion/dci/resources/paper-benchmarks.json`
- Modify: `src/asterion/dci/resources/paper-experiment-scopes.json`
- Modify: `src/asterion/dci/paper_benchmarks.py`
- Modify: `scripts/*.sh`
- Modify: `tests/test_asterion_dci_verification.py`
- Modify: `docs/guides/asterion-dci-complete-reference.md`

**Interfaces:**
- Consumes: paper-reported scope, exact GitHub launcher coverage, and Asterion-added launcher metadata.
- Produces: source-labelled dataset inventory and deterministic selection evidence.

- [ ] **Step 1: Add source fields**

Every dataset and scope records:

```text
source_family
source_reference
launcher_origin = upstream-github | asterion-added | unavailable
selection_kind = full | random-sample | fixed-selected-ids
selection_count
selection_seed_status = reported | paper-unreported | asterion-defined
```

ArguAna and SciFact use `launcher_origin=asterion-added`. Bamboogle has separate
paper-full and upstream-sample-fifty scopes; do not make them compatible.

- [ ] **Step 2: Verify inventory reconciliation**

Assert:

```python
self.assertEqual(upstream_unique_dataset_count, 11)
self.assertEqual(asterion_dataset_count, 13)
self.assertEqual(standalone_launcher_count, 14)
self.assertEqual(resolve_scope("qa.bamboogle.main.full").selection_count, 125)
```

Assert every launcher path exists and is project-root relative under
`scripts/`, never `asterion/scripts/`.

- [ ] **Step 3: Run and commit**

```bash
uv run python -m unittest -v tests.test_asterion_dci_verification
make docs-check
git add src/asterion/dci/resources/paper-benchmarks.json \
  src/asterion/dci/resources/paper-experiment-scopes.json \
  src/asterion/dci/paper_benchmarks.py scripts \
  tests/test_asterion_dci_verification.py \
  docs/guides/asterion-dci-complete-reference.md
git commit -m "docs: distinguish paper GitHub and Asterion dataset coverage"
```

Expected: tests and docs check pass.

### Task 8: Make authorization consumable and budgets enforceable

> Supplemental approved design and executable TDD plan:
> `docs/superpowers/specs/2026-07-25-dci-reproduction-authority-budget-design.md`
> and `docs/superpowers/plans/2026-07-25-dci-reproduction-authority-budget.md`.

**Files:**
- Modify: `src/asterion/dci/experiment_profiles.py`
- Modify: `src/asterion/dci/cli.py`
- Modify: `src/asterion/dci/benchmark.py`
- Create: `tests/test_dci_full_authorization.py`

**Interfaces:**
- Consumes: one explicit CLI invocation with selected profile/scopes, output root, positive Agent/Judge operation caps, and positive USD cap.
- Produces: one-use in-process authority consumed by the benchmark executor.

- [ ] **Step 1: Write authority tests**

Cover:

- absent authority rejected;
- zero/negative/non-finite budget rejected;
- scope/profile/output-root mismatch rejected;
- inode replacement after issuance rejected;
- one scope consumed exactly once;
- operation count stops before exceeding Agent/Judge caps;
- estimated or actual accumulated cost stops before exceeding USD cap;
- cancellation stops all later operations;
- no credential or private path appears in errors.

- [ ] **Step 2: Join authorization and execution**

Make `paper reproduce --execute` perform, in one process:

```python
authority = authorize_full_execution(
    profile=profile,
    scope_ids=scope_ids,
    output_root=output_root,
    max_agent_operations=max_agent_operations,
    max_judge_operations=max_judge_operations,
    max_cost_usd=max_cost_usd,
    invocation_authorized=True,
)
return execute_authorized_reproduction(
    authority,
    profile=profile,
    scope_ids=scope_ids,
    output_root=output_root,
)
```

Do not print or serialize the issuance token. Remove the command path that
issues an in-memory authority and exits without consuming it.

- [ ] **Step 3: Enforce positive finite limits**

Add:

```python
if (
    max_agent_operations <= 0
    or max_judge_operations <= 0
    or not math.isfinite(max_cost_usd)
    or max_cost_usd <= 0
):
    raise ExperimentAuthorizationError("full execution budget is invalid")
```

Before every operation, reserve one operation and the maximum configured
per-operation cost. Reconcile actual cost afterward without allowing the next
reservation to exceed the cap.

- [ ] **Step 4: Run and commit**

```bash
uv run python -m unittest -v tests.test_dci_full_authorization
git add src/asterion/dci/experiment_profiles.py src/asterion/dci/cli.py \
  src/asterion/dci/benchmark.py tests/test_dci_full_authorization.py
git commit -m "feat: enforce DCI reproduction authority and budgets"
```

Expected: tests pass with zero provider operations.

### Task 9: Compile benchmark evidence into RunManifest

**Files:**
- Modify: `src/asterion/dci/reproduction.py`
- Modify: `src/asterion/dci/benchmark.py`
- Modify: `src/asterion/dci/artifacts.py`
- Modify: `src/asterion/dci/resources/reproduction-targets.json`
- Create: `tests/test_dci_reproduction.py`

**Interfaces:**
- Consumes: completed immutable batch item evidence and exact experiment profile.
- Produces: validated `RunManifest` and complete Lite/CC/ablation target matrix accepted directly by comparison.

- [ ] **Step 1: Write end-to-end manifest tests**

Create a provider-free synthetic completed batch with QA, IR, failed, and
excluded rows. Compile it and assert:

```python
manifest = compile_run_manifest(batch_root, profile)
validate_run_manifest(manifest)
comparison = compare_reproduction(original, manifest, target)
self.assertEqual(comparison.candidate_product, "asterion-dci")
```

Mutation matrices must reject changed profile SHA, implementation SHA, prompt,
Judge, metric, selected IDs, corpus identity, operation totals, or artifact
digest.

- [ ] **Step 2: Implement the compiler**

The compiler reads only locked private artifacts, verifies their digests and
permissions, and emits body-free:

```text
profile/source identities
dataset and selected-ID identities
prompt/Judge/metric/context/implementation identities
query-preserving status and metric rows
operation and cost totals
artifact digests
completion/exclusion/failure counts
```

It never copies question, answer, corpus content, provider payload, raw output,
credential, or private path into the manifest.

- [ ] **Step 3: Complete target inventory**

Add distinct targets for:

- DCI-Agent-Lite main;
- DCI-Agent-CC main;
- read+bash and read+grep tool ablation;
- L0–L4 context ablation;
- 100k, 200k, and 400k corpus scaling.

Each target binds its reported paper table/row and comparable metric contract.
If a required method parameter is unreported, target status remains
`method-incomplete` rather than executable-comparable.

- [ ] **Step 4: Run and commit**

```bash
uv run python -m unittest -v tests.test_dci_reproduction
uv run asterion-dci paper verify
git add src/asterion/dci/reproduction.py src/asterion/dci/benchmark.py \
  src/asterion/dci/artifacts.py \
  src/asterion/dci/resources/reproduction-targets.json \
  tests/test_dci_reproduction.py
git commit -m "feat: compile DCI benchmark evidence for reproduction"
```

Expected: tests and provider-free paper verification pass.

### Task 10: Documentation and final provider-free gates

**Files:**
- Modify: `README.md`
- Modify: `docs/README.md`
- Modify: `docs/guides/asterion-capability-usage.md`
- Modify: `docs/guides/asterion-dci-complete-reference.md`
- Modify: `docs/verification/asterion-dci-validation-guide.md`
- Modify: `docs/architecture/dci-capability-audit.md`

**Interfaces:**
- Consumes: completed Tasks 1–9.
- Produces: claim-accurate public documentation and named provider-free evidence.

- [ ] **Step 1: Correct public claims**

Document:

- local corpus does not mean all content stays on-device;
- eleven upstream GitHub datasets versus two Asterion-added BEIR launchers;
- paper, GitHub, and Asterion-safe source families;
- inventory versus executable closure;
- bounded verification versus full reproduction;
- exact full authorization and positive budget requirements;
- paper-unreported assumptions;
- `paper_full_executable` truth derived from complete method and target closure.

- [ ] **Step 2: Run provider-free gates**

```bash
uv run asterion-dci paper describe
uv run asterion-dci paper verify
plan_parent=$(mktemp -d)
plan_root="$plan_parent/not-created"
uv run asterion-dci paper reproduce \
  --profile paper-reference/pi \
  --scope bright.robotics.main.full \
  --limit 1 \
  --output-root "$plan_root"
test ! -e "$plan_root"
make test
make lint
make docs-check
make check
make promotion-check
```

Expected: all commands pass, Agent operations are zero, Judge operations are
zero, the plan reports one selected query and no authority, the output root
remains absent, and no full dataset runs. Planned operation maxima are not
reported as executed operations.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/README.md docs/guides \
  docs/verification/asterion-dci-validation-guide.md \
  docs/architecture/dci-capability-audit.md
git commit -m "docs: publish DCI provenance and reproduction boundaries"
```

### Task 11: Operator-authorized bounded one-query execution

**Files:**
- Modify only if evidence exposes a defect in the responsible earlier task.
- Generate outside Git: operator-selected output root.

**Interfaces:**
- Consumes: explicit user authorization naming the exact profile, scope, limit,
  private output root, and all five finite positive limits, plus valid external
  credentials/resources.
- Produces: **External-limited** bounded evidence; never changes provider-free
  acceptance status or `paper_full_executable=false`.

- [ ] **Step 1: Render the default provider-free plan**

```bash
plan_parent=$(mktemp -d)
plan_root="$plan_parent/not-created"
uv run asterion-dci paper reproduce \
  --profile paper-reference/pi \
  --scope bright.robotics.main.full \
  --limit 1 \
  --output-root "$plan_root"
test ! -e "$plan_root"
```

Expected: one selected query, maximum one Agent operation, maximum zero Judge
operations, zero performed operations, no authority, no dataset read, and no
output root. The full `bright.robotics.main.full` selection identity remains
unchanged; the limit describes a deterministic source-order prefix with its own
bounded digest/count. It does not create a new scope.

- [ ] **Step 2: Obtain explicit operator authorization**

Do not infer authorization from `.env`, credentials, prior evidence, or this
plan. The operator must explicitly approve:

- profile `paper-reference/pi`;
- scope `bright.robotics.main.full`;
- limit `1`;
- one operator-selected private output root outside Git;
- `--max-agent-operations 1`;
- `--max-judge-operations 1`;
- positive finite total, per-Agent-operation, and per-Judge-operation USD caps.

- [ ] **Step 3: Execute once**

Only after that exact approval, substitute the approved private root and cost
caps:

```bash
uv run asterion-dci paper reproduce \
  --profile paper-reference/pi \
  --scope bright.robotics.main.full \
  --limit 1 \
  --output-root "$OPERATOR_SELECTED_PRIVATE_ROOT" \
  --execute \
  --max-agent-operations 1 \
  --max-judge-operations 1 \
  --max-cost-usd "$APPROVED_TOTAL_USD_CAP" \
  --max-agent-cost-per-operation-usd "$APPROVED_AGENT_USD_CAP" \
  --max-judge-cost-per-operation-usd "$APPROVED_JUDGE_USD_CAP"
```

The variables above are placeholders for values in the new approval; they are
not pre-authorized defaults. Execution preflight must verify the complete scope
selection before applying the limit, bind the exact bounded digest/count and
private root to one-use in-process authority, then allow at most one Agent
operation. The positive Judge cap remains required although this IR scope plans
zero Judge operations. Any selection/root/budget drift, failure, or cancellation
must stop before later work and prevent replay.

- [ ] **Step 4: Verify and classify evidence**

The successful benchmark batch keeps its closed artifact inventory. Its
RunManifest is a mode `0600` opaque child of a separate mode `0700`,
descriptor-bound private manifest directory, not a file inside the batch root.
CLI output contains safe authorization and operation counts plus
`manifest_scope`, relative `manifest_artifact`, and
`manifest_identity_sha256`; it must not contain private roots, query IDs,
prompts, answers, corpus bodies, provider payloads, raw output, credentials, or
issuance tokens.

Run `paper compare` explicitly on the private RunManifest. Label the result
**External-limited**; a one-query result is neither full paper reproduction nor
published-score verification and cannot change provider-free acceptance.
