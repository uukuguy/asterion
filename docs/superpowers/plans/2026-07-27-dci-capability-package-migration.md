# DCI Capability Package External-First Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild DCI as one portable, third-party-compatible capability package, prove it in installed-distribution form, materialize the identical payload as built-in, and remove DCI domain code and benchmark machinery from Asterion's global layer.

**Architecture:** The DCI payload owns its capabilities, suites, resources, implementation modules, task bindings, and conformance assets. An installed-distribution provider and the built-in adapter expose the same payload digest and bindings through the public capability SDK. The `dci-agent-lite` application adapter owns application/operator integration only; generic package and benchmark orchestration stays in Asterion.

**Tech Stack:** Python capability SDK, JSON protocols from Plan 1, source adapters from Plan 2, generic benchmark subsystem from Plan 3, Hatchling entry points, `unittest`.

## Global Constraints

- Implement and verify the external installed-distribution form before adding the built-in source declaration.
- The built-in form has no privileged interface, fallback, hidden precedence, or implementation branch.
- Do not retain `src/asterion/dci`, `tools/dci_benchmark_orchestrator.py`, `tools/run_dci_benchmarks.py`, `scripts/run_dci_benchmarks.sh`, or per-task shell launchers.
- DCI manifests contain stable identities and public contracts only. Commands, paths, environment keys, prompts, credentials, host configuration, and provider configuration remain in Python implementations or operator state.
- The DCI CLI is an application adapter; it does not compose packages, resolve suites, execute task loops, persist benchmark evidence, or discover sources.
- Existing bounded behavior is retained: plan-only default, explicit execution authorization, 12-task GitHub view, 13-task paper-main view, 15-task union, distinct Bamboogle variants, sequential fail-fast execution, secure evidence, and compatible resume.
- Monetary amount is optional operator metadata and is neither prompted for nor required. Its absence never blocks planning or execution.
- No provider-backed benchmark, dataset download, setup mutation, or full corpus read is allowed in migration verification.

## Target file structure

```text
src/asterion/capabilities/dci/
  capability-package.json
  capabilities/*.json
  benchmark-suites/{github,paper-main,all}.json
  implementation/*.py
  resources/*
  provider.py
  conformance/*
src/asterion/applications/dci_agent_lite/
  assemblies/*.json
  cli.py
  operator_config.py
  provider.py
tests/fixtures/extensions/dci_distribution/
```

---

### Task 1: Establish the complete portable DCI payload

**Files:**
- Create: `src/asterion/capabilities/dci/capability-package.json`
- Create: `src/asterion/capabilities/dci/capabilities/`
- Create: `src/asterion/capabilities/dci/benchmark-suites/github.json`
- Create: `src/asterion/capabilities/dci/benchmark-suites/paper-main.json`
- Create: `src/asterion/capabilities/dci/benchmark-suites/all.json`
- Move: `src/asterion/capabilities/dci_research/manifests/*.json`
- Create: `src/asterion/capabilities/dci/__init__.py`
- Create: `tests/test_dci_capability_payload.py`

**Interfaces:**
- Defines one exact package ref, used below as
  `dci@1.0.0`, and these exact suite refs:

```text
dci.github@1.0.0
dci.paper-main@1.0.0
dci.all@1.0.0
```

- Defines the task identities:

```text
github (12):
  bcplus.level3
  bcplus.main
  bright.biology
  bright.earth-science
  bright.economics
  bright.robotics
  qa.2wikimultihopqa
  qa.bamboogle.github-sample50
  qa.hotpotqa
  qa.musique
  qa.nq
  qa.triviaqa

paper-main (13):
  bcplus.main
  beir.arguana
  beir.scifact
  bright.biology
  bright.earth-science
  bright.economics
  bright.robotics
  qa.2wikimultihopqa
  qa.bamboogle.paper-full125
  qa.hotpotqa
  qa.musique
  qa.nq
  qa.triviaqa

all (15):
  canonical union of both lists
```

- [ ] **Step 1: Write payload and suite contract tests**

Assert:

- the package descriptor declares every capability, suite, public resource,
  implementation artifact digest, and conformance asset exactly once;
- all references use the new Asterion protocols;
- all arrays are sorted and unique;
- each suite owns the exact ordered task set above;
- the two Bamboogle tasks remain different identities and public notes;
- manifests contain none of the current script paths, `.env` keys, dataset
  paths, prompt text, provider names, or a sentinel private path;
- the package passes the generic portable-payload validator.

- [ ] **Step 2: Run and observe missing payload failures**

Run:

```bash
uv run python -m unittest -v tests.test_dci_capability_payload
```

Expected: failure because the package descriptor and suite manifests are
absent.

- [ ] **Step 3: Move and rewrite manifest assets**

Move each current manifest by basename from
`src/asterion/capabilities/dci_research/manifests/` to
`src/asterion/capabilities/dci/capabilities/`, rename package-oriented fields
to capability-oriented fields, and set the exact owning package ref. Encode
task-to-capability and logical binding identities in the suite manifests;
encode no launcher or private resource locator.

- [ ] **Step 4: Verify**

Run:

```bash
uv run python -m unittest -v tests.test_dci_capability_payload
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A src/asterion/capabilities/dci src/asterion/capabilities/dci_research/manifests
git add tests/test_dci_capability_payload.py
git commit -m "feat: define portable DCI capability payload"
```

### Task 2: Replace shell launchers with exact DCI task bindings

**Files:**
- Create: `src/asterion/capabilities/dci/implementation/benchmark_bindings.py`
- Create: `src/asterion/capabilities/dci/implementation/operator_inputs.py`
- Create: `tests/test_dci_benchmark_bindings.py`
- Reference while porting: `tools/dci_benchmark_orchestrator.py`
- Reference while porting: `scripts/{bcplus_eval,beir,bright,qa}/`

**Interfaces:**
- Produces:

```python
def create_benchmark_bindings() -> tuple[BenchmarkTaskBinding, ...]: ...

@dataclass(frozen=True, slots=True)
class DciBenchmarkOperatorInputs:
    dataset_roots: Mapping[str, Path]
    corpus_roots: Mapping[str, Path]
    private_environment: Mapping[str, str]
    amount: Decimal | None = None
```

- Each binding converts one generic `BenchmarkTaskRequest` plus injected
  private operator inputs into an immutable invocation. Logical binding IDs
  equal the suite manifest binding IDs exactly.

- [ ] **Step 1: Write a complete binding table test**

For all 15 task identities, assert:

- exactly one binding exists;
- the binding selects the intended DCI experiment/profile/dataset contract;
- GitHub Bamboogle uses the 50-case sample contract;
- paper-main Bamboogle uses the full 125-case contract;
- public arguments and representations omit dataset/corpus roots, environment
  values, prompts, credentials, amount, and a sentinel secret;
- missing operator input fails before runtime/provider work;
- `amount=None` is valid and is not converted into a prompt or placeholder;
- case limits are bounded by the generic plan.

Use test doubles for task execution; do not read a real dataset.

- [ ] **Step 2: Run and observe the missing binding catalog**

Run:

```bash
uv run python -m unittest -v tests.test_dci_benchmark_bindings
```

Expected: import failure.

- [ ] **Step 3: Implement Python bindings from launcher semantics**

Port the launcher argument choices into private Python builders. Use direct
immutable argument/value construction and existing DCI APIs; do not invoke a
shell script or construct a shell command. Keep operator path resolution in
`operator_inputs.py`, outside portable manifests and generic benchmark code.

- [ ] **Step 4: Verify semantic completeness**

Run:

```bash
uv run python -m unittest -v tests.test_dci_benchmark_bindings
```

Expected: PASS with a 15-row binding matrix and no external process.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/capabilities/dci/implementation/benchmark_bindings.py src/asterion/capabilities/dci/implementation/operator_inputs.py tests/test_dci_benchmark_bindings.py
git commit -m "feat: bind DCI benchmark tasks in package code"
```

### Task 3: Move all DCI implementation and resources under the package

**Files:**
- Move: the `src/asterion/dci/*.py` implementation modules listed in the
  ownership map below
- Move: `src/asterion/dci/resources/`
- Move: `src/asterion/capabilities/dci_research/{implementation.py,complete.py}`
- Create: `src/asterion/capabilities/dci/implementation/__init__.py`
- Create: `tests/test_dci_package_ownership.py`
- Modify: DCI-focused tests importing moved modules

**Module ownership map:**

| Target under `src/asterion/capabilities/dci/implementation/` | Current source modules |
|---|---|
| `research/` | `context_extension.py`, `context_profiles.py`, `effective_config.py`, `experiment_profiles.py`, `prompts.py`, `system_prompt.py`, `trajectory_resolution.py` |
| `evaluation/` | `analysis.py`, `artifacts.py`, `benchmark.py`, `evaluation.py`, `judge.py`, `metrics.py`, `resolution_metrics.py` |
| `reproduction/` | `ablation.py`, `dual_runtime_verification.py`, `paper_benchmarks.py`, `provenance.py`, `reproduction.py`, `verification.py` |
| `runtime/` | `application_executor.py`, `bridge.py`, `pi_rpc.py`, `run.py` |
| package root implementation | `config.py`, `datasets.py`, `export.py`, `resource_setup.py`, `services.py`, current `dci_research/implementation.py`, current `dci_research/complete.py` |

The current `src/asterion/dci/cli.py` is not moved here; Task 4 replaces it
with an application adapter. All current files under
`src/asterion/dci/resources/` move by relative path to
`src/asterion/capabilities/dci/resources/`.

- [ ] **Step 1: Write ownership and dependency tests**

AST-scan DCI modules and assert:

- DCI domain modules exist only below `asterion.capabilities.dci`;
- implementation modules may import the public capability SDK, runtime
  protocol, runner values, and injected service protocols;
- generic framework modules never import the DCI package;
- package code does not import the `dci_agent_lite` application;
- resource reads are package-relative and reject path escape;
- old imports fail.

Port existing DCI unit tests to the new public package path before moving code,
so the first run demonstrates the missing target modules.

- [ ] **Step 2: Run and observe missing target imports**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_package_ownership \
  tests.test_dci_metrics \
  tests.test_dci_resolution_metrics \
  tests.test_dci_reproduction \
  tests.test_dci_services \
  tests.test_dci_judge_contracts
```

Expected: import failures at `asterion.capabilities.dci.implementation`.

- [ ] **Step 3: Move in ownership-map slices**

Move, do not copy, each module into its target group. Update relative imports
and replace imports of internal package/catalog types with public
`asterion.capability_sdk` interfaces. Move resources once and use
`importlib.resources.files("asterion.capabilities.dci.resources")`.

Keep application selection, CLI parsing, and operator `.env` translation out
of the package implementation.

- [ ] **Step 4: Verify unit behavior and absence of duplicate owners**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_package_ownership \
  tests.test_dci_metrics \
  tests.test_dci_resolution_metrics \
  tests.test_dci_reproduction \
  tests.test_dci_services \
  tests.test_dci_judge_contracts \
  tests.test_dci_research_capability \
  tests.test_dci_complete_application
```

Expected: PASS and only the transitional `cli.py` and `__init__.py` remain
below `src/asterion/dci/`, awaiting replacement in Task 4.

- [ ] **Step 5: Commit**

```bash
git add -A src/asterion/capabilities/dci src/asterion/capabilities/dci_research src/asterion/dci tests
git commit -m "refactor: move DCI implementation into its package"
```

### Task 4: Reduce the DCI CLI to an application adapter

**Files:**
- Create: `src/asterion/applications/dci_agent_lite/cli.py`
- Create: `src/asterion/applications/dci_agent_lite/operator_config.py`
- Modify: `src/asterion/applications/dci_agent_lite/provider.py`
- Modify: `src/asterion/applications/dci_agent_lite/assemblies/*.json`
- Modify: `pyproject.toml`
- Create: `tests/test_dci_application_adapter.py`
- Modify: existing DCI CLI and application tests
- Delete: `src/asterion/dci/cli.py`
- Delete: `src/asterion/dci/__init__.py`

**Interfaces:**
- Changes the console entry point to:

```toml
[project.scripts]
asterion-dci = "asterion.applications.dci_agent_lite.cli:main"
```

- `operator_config.py` translates DCI-specific `.env` keys and explicit host
  options into private `DciBenchmarkOperatorInputs` and host services.
- Benchmark subcommands delegate to the generic host API with exact
  application and suite refs.

- [ ] **Step 1: Write adapter-thinness and CLI behavior tests**

Verify:

- the adapter chooses an exact DCI application assembly and allowed runtime;
- all assemblies use `asterion.application-assembly/v1` and exact
  `dci@1.0.0`;
- `.env` paths are translated only here and never serialized;
- `asterion-dci benchmark plan` delegates to generic planning;
- execution still requires the generic explicit authorization;
- omitted amount remains `None` and succeeds;
- list/describe/preflight are provider-free;
- adapter AST has no task loop, evidence writer, composer, process runner, or
  source discovery implementation.

- [ ] **Step 2: Run and observe missing adapter**

Run:

```bash
uv run python -m unittest -v tests.test_dci_application_adapter
```

Expected: import failure.

- [ ] **Step 3: Implement the adapter**

Keep only:

```text
DCI argument aliases and application defaults
operator configuration translation
host-service preflight
delegation to public Asterion application/benchmark hosts
redacted presentation of public results
```

The DCI provider declares exact package refs and implementation bindings
through the public SDK; it no longer directly constructs catalogs or
composers.

- [ ] **Step 4: Verify**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_application_adapter \
  tests.test_asterion_dci_benchmark \
  tests.test_asterion_dci_bridge \
  tests.test_asterion_dci_safe_recovery \
  tests.test_asterion_dci_verification \
  tests.test_dci_complete_application
```

Expected: PASS without provider operations.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/dci_agent_lite pyproject.toml tests
git rm src/asterion/dci/cli.py src/asterion/dci/__init__.py
git commit -m "refactor: make DCI CLI an application adapter"
```

### Task 5: Remove global DCI benchmark orchestration and launchers

**Files:**
- Delete: `tools/dci_benchmark_orchestrator.py`
- Delete: `tools/run_dci_benchmarks.py`
- Delete: `scripts/run_dci_benchmarks.sh`
- Delete: `scripts/bcplus_eval/run_L3.sh`
- Delete: `scripts/bcplus_eval/run_bcplus_eval_openai.sh`
- Delete: `scripts/beir/benchmark_arguana.sh`
- Delete: `scripts/beir/benchmark_scifact.sh`
- Delete: `scripts/bright/run_bio.sh`
- Delete: `scripts/bright/run_earth_science.sh`
- Delete: `scripts/bright/run_economics.sh`
- Delete: `scripts/bright/run_robotics.sh`
- Delete: `scripts/qa/run_2wikimultihopqa_dev_sample50.sh`
- Delete: `scripts/qa/run_bamboogle_test_sample50.sh`
- Delete: `scripts/qa/run_hotpotqa_dev_sample50.sh`
- Delete: `scripts/qa/run_musique_dev_sample50.sh`
- Delete: `scripts/qa/run_nq_test_sample50.sh`
- Delete: `scripts/qa/run_triviaqa_test_sample50.sh`
- Delete: `tests/test_dci_benchmark_orchestrator.py`
- Modify: `README.md`
- Modify: `docs/cli.md`
- Modify: benchmark and security tests created in Plan 3

**Interfaces:**
- Replaces every old invocation with:

```text
asterion benchmark plan --application ... --suite ...
asterion benchmark run --application ... --suite ... --execute
asterion-dci benchmark plan|run|resume ...
```

- [ ] **Step 1: Add an obsolete-surface absence test**

In `tests/test_project_boundaries.py`, assert each file above is absent and no
documentation or Python source mentions a per-task launcher. Verify the
generic evidence/cancellation tests contain every security behavior formerly
covered by `tests/test_dci_benchmark_orchestrator.py`.

- [ ] **Step 2: Run and observe obsolete-surface failures**

Run:

```bash
uv run python -m unittest -v tests.test_project_boundaries
```

Expected: failure listing the old files.

- [ ] **Step 3: Delete superseded code and update usage docs**

Delete the exact files. Do not leave compatibility wrappers. Document suite
IDs, counts, plan-only default, explicit execution, resume compatibility,
private evidence, and the fact that paths come from application/operator
configuration rather than package manifests.

- [ ] **Step 4: Verify**

Run:

```bash
uv run python -m unittest -v \
  tests.test_project_boundaries \
  tests.test_benchmark_evidence \
  tests.test_benchmark_execution \
  tests.test_dci_benchmark_bindings \
  tests.test_dci_application_adapter
uv run python tools/check_docs.py
```

Expected: PASS and no old launcher is executable because none exists.

- [ ] **Step 5: Commit**

```bash
git rm tools/dci_benchmark_orchestrator.py tools/run_dci_benchmarks.py scripts/run_dci_benchmarks.sh
git rm scripts/bcplus_eval/run_L3.sh scripts/bcplus_eval/run_bcplus_eval_openai.sh
git rm scripts/beir/benchmark_arguana.sh scripts/beir/benchmark_scifact.sh
git rm scripts/bright/run_bio.sh scripts/bright/run_earth_science.sh scripts/bright/run_economics.sh scripts/bright/run_robotics.sh
git rm scripts/qa/run_2wikimultihopqa_dev_sample50.sh scripts/qa/run_bamboogle_test_sample50.sh scripts/qa/run_hotpotqa_dev_sample50.sh scripts/qa/run_musique_dev_sample50.sh scripts/qa/run_nq_test_sample50.sh scripts/qa/run_triviaqa_test_sample50.sh
git rm tests/test_dci_benchmark_orchestrator.py
git add tests/test_project_boundaries.py tests/test_benchmark_evidence.py tests/test_benchmark_execution.py README.md docs/cli.md
git commit -m "refactor: remove global DCI benchmark launchers"
```

### Task 6: Prove DCI first as an installed third-party distribution

**Files:**
- Create: `tests/fixtures/extensions/dci_distribution/pyproject.toml`
- Create: `tests/fixtures/extensions/dci_distribution/src/asterion_dci_extension/__init__.py`
- Create: `tests/fixtures/extensions/dci_distribution/src/asterion_dci_extension/provider.py`
- Create: `tests/fixtures/extensions/dci_distribution/src/asterion_dci_extension/payload/`
- Create: `tests/test_dci_external_distribution.py`
- Modify: package author/conformance helpers from Plan 2

**Interfaces:**
- The fixture distribution declares only the public entry-point group:

```toml
[project.entry-points."asterion.capability_packages"]
"asterion.dci" = "asterion_dci_extension.provider:create_provider"
```

- It vendors the same portable payload bytes as the candidate built-in
  package, but imports only `asterion.capability_sdk` and documented runtime
  interfaces.

- [ ] **Step 1: Write clean-environment external-form tests**

Build an Asterion wheel and the fixture extension wheel. Install both into an
isolated temporary virtual environment without the repository root on
`PYTHONPATH`. Assert:

- metadata discovery finds DCI without importing its provider;
- exact source lock selects the distribution;
- the provider imports after selection;
- package/suite/capability identity and payload digest validate;
- the conformance kit passes;
- synthetic plan, binding, and execution smoke tests pass;
- removing the extension produces a clear missing-package error;
- source ambiguity with a local copy fails closed;
- the extension imports no private `asterion._*`,
  `asterion.capabilities.dci`, or repository-only module.

- [ ] **Step 2: Run and observe the missing fixture**

Run:

```bash
uv run python -m unittest -v tests.test_dci_external_distribution
```

Expected: failure because the external distribution does not exist.

- [ ] **Step 3: Build the external package from the portable payload**

Copy the payload through the generic author helper, not by maintaining a
second handwritten descriptor. Implement the provider against the public SDK
and expose exact capability and benchmark bindings. Use only synthetic host
services in the smoke test.

- [ ] **Step 4: Verify in the clean environment**

Run:

```bash
uv run python -m unittest -v tests.test_dci_external_distribution
```

Expected: PASS and provider import count remains zero during discovery/list.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/extensions/dci_distribution tests/test_dci_external_distribution.py
git commit -m "test: prove DCI as an external capability package"
```

### Task 7: Materialize the identical payload as a built-in source form

**Files:**
- Create: `src/asterion/capabilities/dci/provider.py`
- Create: `src/asterion/capabilities/dci/conformance/externalization.json`
- Modify: `src/asterion/capabilities/__init__.py`
- Modify: `pyproject.toml`
- Create: `tests/test_dci_source_form_equivalence.py`
- Modify: `tests/test_distribution.py`

**Interfaces:**
- The built-in source adapter exposes the DCI package through the same
  `CapabilityPackageSource` and `InstalledCapabilityPackage` values as the
  distribution source.
- `externalization.json` records only public conformance case IDs and expected
  digests; it contains no local source path.

- [ ] **Step 1: Write form-equivalence tests**

Resolve the external fixture and built-in form separately with exact locks and
assert equality of:

```text
package ref
portable payload SHA-256
capability refs and canonical manifest bytes
suite refs and canonical manifest bytes
public resource digests
implementation binding IDs
benchmark binding IDs
conformance profile and results
synthetic resolved plan
synthetic public task/run results
```

Also copy the built-in payload to an explicit local-directory envelope and
assert the same identity. With all three candidates visible and no lock,
resolution must fail as ambiguous even though digests are equal.

- [ ] **Step 2: Run and observe the missing built-in provider**

Run:

```bash
uv run python -m unittest -v tests.test_dci_source_form_equivalence
```

Expected: failure because no built-in DCI source is registered.

- [ ] **Step 3: Register the built-in through the generic adapter**

Create one provider factory using public SDK helpers. Reuse the package
implementation binding constructors from Tasks 2 and 3. Do not special-case
DCI in source resolution, application resolution, composition, or benchmark
execution.

- [ ] **Step 4: Verify packaged form identity**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_source_form_equivalence \
  tests.test_distribution \
  tests.test_dci_external_distribution
make promotion-check
```

Expected: PASS from source and built-wheel resource contexts.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/capabilities/dci/provider.py src/asterion/capabilities/dci/conformance src/asterion/capabilities/__init__.py pyproject.toml tests/test_dci_source_form_equivalence.py tests/test_distribution.py
git commit -m "feat: materialize DCI as an equivalent built-in source"
```

### Task 8: Close the migration and repository boundaries

**Files:**
- Modify: `tests/test_project_boundaries.py`
- Modify: `tests/test_distribution.py`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/cli.md`
- Modify: `docs/security.md`
- Modify: `docs/status/RESUME-NEXT-SESSION.md`

**Interfaces:**
- Establishes the permanent rule that every built-in capability package must
  pass the same portable payload, third-party SDK, externalization, and
  source-form equivalence conformance used by DCI.

- [ ] **Step 1: Add final structural and privacy assertions**

Assert:

```text
src/asterion/dci does not exist
src/asterion/capabilities/dci_research does not exist
root DCI benchmark tools and launchers do not exist
generic modules do not import or name DCI
all DCI code is package-owned or application-adapter-owned
all built-ins expose generic source metadata and externalization conformance
old dci.* protocol identifiers are absent
public CLI/evidence/errors redact sentinel secrets and private paths
```

- [ ] **Step 2: Run focused boundaries and observe any remaining failures**

Run:

```bash
uv run python -m unittest -v \
  tests.test_project_boundaries \
  tests.test_distribution \
  tests.test_dci_package_ownership \
  tests.test_dci_source_form_equivalence
```

Expected: any leftover import, resource, entry point, or obsolete path is
reported explicitly.

- [ ] **Step 3: Update architecture, security, and operator documentation**

Document:

- built-in as one source form;
- external-first DCI proof;
- exact source locks and ambiguity behavior;
- portable manifest prohibitions;
- installed extension trust boundary;
- DCI operator configuration ownership;
- benchmark cost classes and explicit execution authorization;
- no amount requirement;
- archive/registry deferral to a separate security design.

- [ ] **Step 4: Run the complete closure gate**

Run:

```bash
uv run python -m unittest discover -s tests -v
make test
make lint
make docs-check
make check
make promotion-check
test ! -d src/asterion/dci
test ! -d src/asterion/capabilities/dci_research
test ! -e tools/dci_benchmark_orchestrator.py
test ! -e tools/run_dci_benchmarks.py
test ! -e scripts/run_dci_benchmarks.sh
test -z "$(find scripts -type f | rg '/(bcplus_eval|beir|bright|qa)/')"
test -z "$(rg -l 'dci\\.(agent-runtime|package|assembly)/v1' schemas src packages tests || true)"
```

Expected:

- every command exits `0`;
- provider operations are `0`;
- full dataset is `no`;
- external and built-in DCI payload digests are equal;
- worktree contains no obsolete DCI owner or launcher.

- [ ] **Step 5: Commit**

```bash
git add tests README.md docs pyproject.toml src
git commit -m "docs: close DCI capability package migration"
```
