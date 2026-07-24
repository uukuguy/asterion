# DCI Capability Architecture and Gap Audit

> Status: approved design baseline, 2026-07-24. This document is an
> implementation audit, not evidence that a provider-backed benchmark or a
> published paper score was rerun.

## Purpose and sources

This audit maps the public claims of DCI to the authoritative standalone
Asterion implementation. It distinguishes four states that must not be
collapsed:

- **Packaged** — a resource is included in the source tree or wheel.
- **Bound** — an installed provider exposes the resource through an exact
  application binding.
- **Executable** — the bound graph resolves to one runtime and one exact
  implementation for every executable package.
- **Verified** — a named command passed inside its stated boundary.

The external baselines are:

- [DCI paper, arXiv:2605.05242v1](https://arxiv.org/abs/2605.05242)
- [DCI-Agent-Lite GitHub repository](https://github.com/DCI-Agent/DCI-Agent-Lite)
- GitHub source pin inspected for this audit:
  [`271f37e71f053bf0c99c05ce6d2fb53b841d922e`](https://github.com/DCI-Agent/DCI-Agent-Lite/commit/271f37e71f053bf0c99c05ce6d2fb53b841d922e)

The paper, its appendix, and the GitHub implementation are separate sources.
Where they differ, Asterion must record the selected source rather than
silently treating the GitHub implementation as the paper method.

## Architectural boundary

Asterion has two DCI-facing execution planes:

```text
generic framework plane

asterion CLI
  → selected installed provider
    → exact application and runtime-specific assembly
      → explicit local package catalog
        → deterministic composer
          → exact implementation bindings
            → sequential composed runner
              → selected runtime and injected host services

DCI product plane

asterion-dci CLI
  → DCI configuration and preflight
    → Pi or Claude Code execution
      → run evidence and resume
        → Judge or IR metric
          → benchmark analysis and export
            → paper contracts and reproduction comparison
```

The generic plane must stay domain-neutral. DCI configuration, prompts,
datasets, credentials, Judge behavior, and reproduction policy belong to the
product plane or to explicitly injected host services.

## Installed application reachability

The `dci-agent-lite` provider exposes exactly two application identities:

| Application | Runtime assemblies | Executable packages | Product meaning |
| --- | --- | --- | --- |
| `dci.research-capability@1.0.0` | Pi, Claude Code | `dci.research` | One local-corpus research run |
| `dci.complete-application@1.0.0` | Pi, Claude Code | research, evaluation, benchmark, analysis, export | One question-and-gold five-stage verification chain |

`dci.complete-application` is not a full dataset benchmark. Its benchmark
implementation emits `total=1` and `judged=1`; the batch benchmark belongs to
the `asterion-dci benchmark` product command.

Two packaged resources are not provider-reachable:

- `applications/dci_agent_lite/assemblies/dci-local-research.json`
- `capabilities/dci_research/manifests/protocol-observability.json`

Installed acceptance currently counts six packaged assemblies while the two
providers bind five assemblies in total. Therefore its
`application-assemblies` result proves packaged inventory, not provider
reachability or executable closure.

## DCI README claim mapping

| Upstream claim | Asterion evidence | Status | Qualification |
| --- | --- | --- | --- |
| Direct access to raw corpus through terminal tools | Pi and Claude Code research paths expose read/search tools | Implemented | The generic manifest names `filesystem.read`; corpus authority remains implicit in runtime cwd/configuration |
| No fixed retriever or hosted retrieval API | Research implementation delegates search strategy to the Agent | Implemented | Model-provider calls remain external operations |
| Zero index, embeddings, vector database, or offline build | No index construction or retrieval database exists in the product path | Implemented | Resource setup downloads or validates corpora but does not index them |
| Minimal Pi plus bash/read workflow | `asterion-dci` defaults to Pi and `read,bash` | Implemented with divergence | Installed complete Pi forces `read,grep`, so it is a restricted verifier rather than the faithful open-bash setup |
| Private/local document assistant | Corpora remain operator-owned local files and are not uploaded to a hosted retrieval service | Partially supported | Relevant document content can still be sent to the selected model provider; do not claim that data never leaves the machine |
| L0–L4 context management | Five immutable context profiles and a TypeScript Pi extension are packaged | Partial | Numeric settings match the paper table; L3/L4 behavioral equivalence is not yet proven |
| QA and IR benchmark coverage | Thirteen dataset identities and sixteen experiment scopes are packaged | Implemented as contracts | Full datasets and published scores were not rerun |
| Reported benchmark superiority | Reproduction targets and comparison schemas exist | Not verified | A contract or dry-run plan is not experimental evidence |

## Dataset and launcher reconciliation

The official GitHub README exposes eleven unique datasets through twelve
launchers: one BrowseComp-Plus dataset with two configurations, six QA
datasets, and four BRIGHT datasets. Asterion adds ArguAna and SciFact from the
paper's BEIR evaluation, producing thirteen dataset identities and fourteen
standalone launchers.

The two BEIR launchers are Asterion additions based on the paper and must be
labelled as such. They are not GitHub launcher parity.

The README describes the six QA datasets as fifty examples each. The paper
appendix instead uses the full Bamboogle test set of 125 examples and random
fifty-example selections for the other QA datasets. Asterion correctly models
the paper-full Bamboogle scope separately and does not bind the upstream
sample-fifty launcher to that scope.

## Package graph audit

The complete application declares:

```text
policy.local-corpus
  → dci.research
    → dci.evaluation
      → dci.benchmark
        → dci.analysis
          → dci.export
```

Portable artifacts order the executable stages. However, the question, gold
answer, predicted answer, and private output directory also pass through
`DciCompleteAttemptStore`. The artifacts prove stage continuity but are not the
complete data flow.

The following boundary gaps remain:

1. Pi implementations can invoke `EnvironmentDciRunExecutor` directly instead
   of using the selected `AgentRuntimeClient`; Claude Code uses the runtime
   client.
2. Runtime cwd, provider, model, tools, and Judge configuration can be resolved
   again during execution rather than being fixed in the resolved plan.
3. Judge access is environment-owned but is neither declared as an assembly
   host capability nor injected as a read-only service.
4. Local corpus authority is represented by runtime cwd and environment
   configuration, not an explicit operator-owned host service.
5. `complete_application_identity()` hashes `complete.py`, manifests, and
   assemblies but not all imported implementation modules that affect
   evaluation, analysis, bridging, and Judge behavior.
6. The benchmark reuse identity does not include a transitive implementation
   digest.

## Protocol and composition audit

The following read-only counterexamples were the pre-hardening findings that
motivated the protocol/composition plan. They are not the current behavior:

| Counterexample | Prior result | Hardened v1 invariant |
| --- | --- | --- |
| `tool.call` followed by terminal event without a result | Accepted | Every call has exactly one result before terminal |
| Runtime ID `../runtime` | Accepted | IDs use the canonical identifier grammar |
| Unsorted runtime/request/start capability arrays | Accepted | All contract arrays are sorted and unique |
| Host and package both provide one capability | Accepted; host precedence can remove the package dependency | Provider overlap fails closed |
| Multiple packages emit the same event | Accepted | v1 rejects provider ambiguity |
| Multiple packages produce the same artifact media type | Accepted | v1 rejects provider ambiguity |
| Mutation of `PackageCatalog.entries[*].manifest` | Changes later `select()` output | Catalog snapshots are deeply immutable |
| Package declares output but returns none | Accepted | Declarations are allowlists; an empty result is valid |
| Duplicate event instances or multiple artifacts of one media type | Accepted | v1 imposes no per-type cardinality |

The Python and TypeScript runtime validators now reject the shared invalid
fixtures, including an unmatched call at terminal. Direct composition and
catalog suites cover ambiguity and snapshot behavior; the older gaps described
above are retained only as audit provenance.

### Approved v1 interpretation

The implemented v1 semantics are:

- Runtime IDs/capabilities and assembly/package IDs use their contracts'
  canonical identifier grammars. Package and assembly edge values, including
  event and media-type names, are non-empty Unicode scalar strings in canonical
  arrays; v1 does not impose the runtime identifier grammar on those values.
- Runtime capabilities, requested capabilities, `run.started` capabilities,
  package edge arrays, and assembly arrays/references are sorted and unique;
  validators reject noncanonical input rather than silently reordering it.
  String arrays use lexicographic Unicode scalar-value order, with a shorter
  prefix first; surrogate code points are invalid. Assembly package references
  compare `package_id` first and `version` second with that ordering, never an
  interpolated `package_id@version`.
- A runtime stream has one run ID, contiguous sequences, one terminal event,
  and every tool call has exactly one later matching result before terminal.
- Provider overlap across host, runtime (as host capability), and packages is
  ambiguity and fails closed; composition has one provider per consumed edge.
- `emits_events` and `produces_artifacts` describe allowed output types.
  Cardinality remains implementation-specific in v1; empty output is allowed
  unless a package-specific implementation contract requires an output.
- Artifact IDs are unique within a `PackageExecutionResult` and globally across
  package-produced results in one composed `ApplicationRunResult`. Host
  artifacts are separate inputs; they are unique within their input collection
  and do not participate in that result-ID set.
- Package evidence inputs/results, catalog snapshots, resolved plans, and
  validated TypeScript values are immutable snapshots. The composed runner
  transports actual compatible upstream and host evidence, not declarations.
- Adding manifest fields for artifact identity, cardinality, or richer routing
  requires a future protocol version rather than silently extending v1.

## Paper, GitHub, and Asterion experiment semantics

Three provenance families are approved:

| Family | Authority | Purpose |
| --- | --- | --- |
| `paper-reference/*` | Paper and appendix only | Reproduce reported methodology; unreported values remain explicit unknowns or operator-supplied parameters |
| `upstream-github/<commit>/*` | One exact GitHub commit | Reproduce the public implementation, including behavior that differs from the paper |
| `asterion-safe/*` | Asterion contracts | Preserve stricter validation, safer defaults, and intentionally improved metrics |

They must have distinct prompt, Judge, metric, runtime, dataset-selection, and
implementation identities. Results from different families are not
cache-compatible or directly labelled as equivalent.

### Prompt and Judge differences

- Asterion QA uses the short GitHub prompt plus an Asterion sentence requiring
  a non-empty final answer. It is not the detailed QA prompt in paper
  Appendix C1.
- The IR prompt closely follows the GitHub implementation and paper method.
- Asterion includes a final-answer recovery prompt that is not part of the
  reported paper contract.
- The paper Judge asks GPT-4.1 for extracted answer, yes/no correctness,
  reasoning, and confidence.
- Asterion and the inspected GitHub commit use a JSON object with
  `is_correct`, `normalized_prediction`, and `reason`. The inspected GitHub
  default Judge is GPT-5.4-nano, while the paper reports GPT-4.1.

The current `dci.paper-answer-judge/gpt-4.1/v1` label points at an
Asterion-owned JSON schema rather than the Appendix C3 semantic contract and
must be corrected before paper-comparable scoring.

### Ranking metric difference

The inspected GitHub implementation computes NDCG from the returned list
without deduplication. Repeating one relevant document twice can produce a
score of approximately `1.63093`. Asterion deduplicates first and clamps the
result to `[0,1]`.

The Asterion behavior is safer but is not exact GitHub parity. The two metrics
need separate identities:

- `ndcg@10-binary-upstream-list/v1`
- `ndcg@10-binary-deduplicated/v1`

The paper calls the metric NDCG@10 but does not specify duplicate handling, so
paper-reference must record this as an unresolved method detail rather than
silently selecting either implementation.

### Resolution metric difference

Coverage and localization formulas match the paper:

```text
coverage-any  = 1 when at least one gold document is surfaced
coverage-mean = surfaced-gold / all-gold
coverage-all  = 1 when every gold document is surfaced

ν(x) = max(1, ceil(characters(x) / cseg))
ψ(a,b) = max(1 - log(a) / log(b), 0)
```

The paper does not report a numeric `cseg` or a read/evidence overlap
threshold. Asterion hard-codes `4096` characters and `0.5` overlap in its paper
ablation rows; these are Asterion-defined parameters and must be labelled.

Trajectory alignment is not yet comparable to the paper:

- exact `path:line:text` grep output is validated against the corpus;
- a read result must occur uniquely in the gold document, otherwise it falls
  back to full-document localization;
- bash pipelines return only full-document fallbacks for gold document paths
  literally present in the command;
- dominant paper patterns such as `rg | head` and `rg | rg` normally expose
  paths in output rather than as command arguments, so current alignment can
  miss both coverage and localization;
- path-only output is not recognized as surfaced evidence.

## Full reproduction boundary

`asterion-dci paper describe` currently reports
`paper_full_executable=false`. A dry-run can enumerate thirteen datasets,
sixteen scopes, 1,978 Agent operations, and 1,455 Judge operations, but it does
not execute them.

The current full-execution authorization is an in-memory object. The
`paper reproduce --authorize-full` command can issue the object and then exits;
the benchmark CLI has no supported route to consume that authority. The
estimated budget is metadata, accepts zero, and is not an enforced operation
or currency cap.

Reproduction comparison consumes a `RunManifest`, but production benchmark
output has no complete path that compiles its evidence into that manifest.
Only the DCI-Agent-CC main target is represented; Lite and the tool, context,
and corpus ablations do not form a complete executable target matrix.

## Prioritized gap register

The following findings are historical and closed. Their gap descriptions use
past tense so they cannot be mistaken for current behavior:

| ID | Priority | Status | Historical gap | Named closure evidence |
| --- | --- | --- | --- | --- |
| P1 | Blocker | Closed | Runtime v1 accepted noncanonical arrays/IDs and unresolved tool calls | `TestRuntimeProtocol`; `ProtocolCanonicalOrderingTests`; TypeScript shared-fixture tests |
| P2 | Blocker | Closed | The composer accepted hidden host precedence and multi-provider ambiguity | `PackageCompositionTests.test_rejects_every_provider_ambiguity` |
| P3 | High | Closed | Catalog and TypeScript validation returned mutable contract state | `PackageCatalogTests.test_entry_manifest_is_deeply_immutable`, `test_selected_manifest_is_fresh`; TypeScript `returns a deep immutable validation snapshot` |
| A1 | Blocker | Closed | The generic CLI imported DCI configuration and repository `.env` values contaminated provider-free tests | `AsterionCliTests.test_generic_cli_has_no_dci_configuration_imports`, `test_run_ignores_repository_dotenv_and_preserves_environment` |

The remaining current gaps are:

| ID | Priority | Open gap | Completion evidence |
| --- | --- | --- | --- |
| A2 | High | Provider acceptance counts inventory rather than executable closure | Report separately proves packaged, bound, composed, bound-implementation counts |
| A3 | High | Pi bypasses selected runtime and execution re-resolves authority | Both runtimes execute only through the selected runtime client |
| A4 | High | Corpus and Judge are implicit environment services | Assembly-declared, host-injected service preflight and redaction tests pass |
| E1 | Blocker | `paper-reference` mixes paper, GitHub, and Asterion semantics | Three distinct immutable provenance families and cache keys exist |
| E2 | High | Context L3/L4 behavioral parity is unproven | Golden trajectory tests cover thresholds, retained turns, summary gating, failure limit |
| E3 | High | Pipeline/path-only evidence is missed | Hand-calculated trajectory fixtures match expected coverage/localization |
| E4 | High | Full authorization and budget are not executable authority | One authorized bounded scope consumes authority once and enforces a positive cap |
| E5 | High | Benchmark evidence cannot compile into comparison input | Validated RunManifest is emitted and accepted by compare without manual conversion |
| D1 | Medium | Documentation claim audit is not yet independently rerun after protocol hardening | `make docs-check` and an independent claim audit pass |

## Delivery sequence

Implementation is split into three independently reviewable plans:

1. [Protocol and composition hardening](../superpowers/plans/2026-07-24-asterion-protocol-composition-hardening.md)
2. [Application authority and executable closure](../superpowers/plans/2026-07-24-asterion-application-authority.md)
3. [DCI provenance and reproduction parity](../superpowers/plans/2026-07-24-dci-provenance-reproduction.md)

The order is intentional. Experimental evidence must not be promoted through
an ambiguous or mutable framework graph, and provider-backed work must not
start until authority and cost boundaries are explicit.

## Verification snapshot

Provider-free hardened-protocol evidence (2026-07-24):

```text
uv run python -m unittest -v \
  tests.test_runtime_protocol \
  tests.test_package_composition \
  tests.test_package_catalog \
  tests.test_package_execution \
  tests.test_dci_complete_application \
  tests.test_dci_research_capability \
  tests.test_controlled_code_application
  PASS: focused provider-free protocol/composition/application suites

npm --prefix packages/typescript/asterion-runtime test
  PASS: TypeScript runtime and shared-contract validation

make lint
make docs-check
make promotion-check
  PASS: provider-free lint, documentation, and packaged-promotion gates
```

`make test` and `make check` are intentionally reserved for the
application-authority plan's final repository-wide gate, because later
application work changes that boundary. This audit does not promote either
command as Task 8 evidence. The generic CLI `.env` isolation and Node 22.19.0
corrections are already verified and are not current failures.

No provider-backed benchmark or published paper score was rerun for this
audit.
