# DCI Capability Architecture and Gap Audit

> Status: approved design baseline, 2026-07-24. This document is an
> implementation audit, not evidence that a provider-backed benchmark or a
> published paper score was rerun.

## Purpose and sources

This audit maps the public claims of DCI to the authoritative standalone
Asterion implementation. It distinguishes five states that must not be
collapsed:

- **Packaged** — a resource is included in the source tree or wheel.
- **Bound** — an installed provider exposes the resource through an exact
  application binding.
- **Composed** — the exact package catalog and composer prove its graph.
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

Installed acceptance reports the reachability classes separately: six
packaged assemblies, five provider-bound assemblies, five composed assemblies,
and five executable assemblies. It names
`applications/dci_agent_lite/assemblies/dci-local-research.json` as the one
unbound assembly instead of promoting packaged inventory to reachability.

## DCI README claim mapping

| Upstream claim | Asterion evidence | Status | Qualification |
| --- | --- | --- | --- |
| Direct access to raw corpus through terminal tools | Pi and Claude Code research paths expose read/search tools | Implemented | The generic manifest names `filesystem.read`; corpus authority is the explicit `corpus.local-root` host service, pinned before process start |
| No fixed retriever or hosted retrieval API | Research implementation delegates search strategy to the Agent | Implemented | Model-provider calls remain external operations |
| Zero index, embeddings, vector database, or offline build | No index construction or retrieval database exists in the product path | Implemented | Resource setup downloads or validates corpora but does not index them |
| Minimal Pi plus bash/read workflow | `asterion-dci` defaults to Pi and `read,bash` | Implemented with divergence | Installed complete Pi forces `read,grep`, so it is a restricted verifier rather than the faithful open-bash setup |
| Private/local document assistant | Corpora remain operator-owned local files and are not uploaded to a hosted retrieval service | Partially supported | Relevant document content can still be sent to the selected model provider; do not claim that data never leaves the machine |
| L0–L4 context management | Five immutable context profiles and a TypeScript Pi extension are packaged | Partial | Numeric settings match the paper table; L3/L4 behavioral equivalence is not yet proven |
| QA and IR benchmark coverage | Thirteen dataset identities and sixteen experiment scopes are packaged | Implemented as contracts | Full datasets and published scores were not rerun |
| Reported benchmark superiority | Reproduction targets and comparison schemas exist | Not verified | A contract or plan-only reproduction command is not experimental evidence |

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

Portable artifacts order the executable stages. The question, gold answer,
predicted answer, and private output directory now move through
`InProcessArtifactPayload`, so stage continuity is preserved without exposing
bodies. The CLI only emits the payload's explicit safe public projection.

The following previously open application-authority gaps are now closed:

1. Pi and Claude Code research implementations execute only through the
   selected runtime client; `EnvironmentDciRunExecutor` is no longer on the
   product path.
2. Runtime cwd, provider, model, tools, and Judge configuration are fixed by
   the selected runtime-factory context and injected host services before
   execution instead of being rediscovered by package implementations.
3. Judge access is an explicit `evaluation.answer-judge` host service and is
   only selected by the two complete assemblies.
4. Local corpus authority is an explicit `corpus.local-root` host service and
   is never inferred from runtime cwd or environment configuration.
5. `complete_application_identity()` hashes the full 66-resource transitive
   implementation closure.
6. Benchmark reuse identity includes the same transitive implementation digest
   and rejects mismatched evidence before Agent or Judge work begins.

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
- piped bash output in `path:line:text` and `path:line` form is validated
  against the corpus when it carries enough path and line identity;
- a read result must occur uniquely in the gold document, otherwise it falls
  back to full-document localization;
- dominant paper patterns such as `rg | head` and `rg | rg` normally expose
  paths in output rather than as command arguments, so body-free alignment still
  depends on parseable output and can fall back when line identity is absent;
- path-only output is recognized as surfaced document evidence but cannot
  establish line-level localization by itself.

## Full reproduction boundary

`asterion-dci paper describe` currently reports
`paper_full_executable=false`. The truth value is derived from complete method
and target closure, not from the existence of inventory rows. Current packaged
inventory has thirteen dataset identities and sixteen paper scopes, but complete
profile execution is not closed:

- Bamboogle's paper-full target is 125 examples and has no batch profile.
- BrowseComp+ `analysis.n100`, `appendix-a1.random50`, and
  `context-ablation.random100` have `launcher_origin=unavailable`.
- Paper-unreported method details remain labelled, including selection seeds,
  duplicate handling, segment size, and evidence-overlap assumptions.

The supported default command is plan-only:

```bash
uv run asterion-dci paper reproduce \
  --profile paper-reference/pi \
  --output-root ./evidence/reproduction
```

Without `--execute`, it enumerates the selected profile plan, including 1,978
maximum Agent operations and 1,455 maximum Judge operations for the full
paper-reference scope set, but performs zero Agent operations, zero Judge
operations, issues no full authorization, and creates no output root.

The supported full-execution route is the same process `paper reproduce
--execute` path. It rejects missing scopes, unavailable scopes, partial method
selections, missing resources, and missing/invalid limits before creating output
or issuing authority. All five limits are mandatory and must be positive:
`--max-agent-operations`, `--max-judge-operations`, `--max-cost-usd`,
`--max-agent-cost-per-operation-usd`, and
`--max-judge-cost-per-operation-usd`. Authorization is consumed by bounded
benchmark execution in that process and is not granted by `.env`, caches, prior
evidence, or a plan-only command.

Reproduction comparison consumes compiled, body-free `RunManifest` evidence.
Validated manifest compilation exists, but no provider-backed full reproduction
or published paper-score rerun has been performed for this audit.

## Prioritized gap register

The following findings are historical and closed. Their gap descriptions use
past tense so they cannot be mistaken for current behavior:

| ID | Priority | Status | Historical gap | Named closure evidence |
| --- | --- | --- | --- | --- |
| P1 | Blocker | Closed | Runtime v1 accepted noncanonical arrays/IDs and unresolved tool calls | `TestRuntimeProtocol`; `ProtocolCanonicalOrderingTests`; TypeScript shared-fixture tests |
| P2 | Blocker | Closed | The composer accepted hidden host precedence and multi-provider ambiguity | `PackageCompositionTests.test_rejects_every_provider_ambiguity` |
| P3 | High | Closed | Catalog and TypeScript validation returned mutable contract state | `PackageCatalogTests.test_entry_manifest_is_deeply_immutable`, `test_selected_manifest_is_fresh`; TypeScript `returns a deep immutable validation snapshot` |
| A1 | Blocker | Closed | The generic CLI imported DCI configuration and repository `.env` values contaminated provider-free tests | `AsterionCliTests.test_generic_cli_has_no_dci_configuration_imports`, `test_run_ignores_repository_dotenv_and_preserves_environment` |
| A2 | High | Closed | Acceptance collapsed packaged inventory into executable reachability | Named `packaged-assemblies`, `bound-assemblies`, `composed-assemblies`, and `executable-assemblies` checks |
| A3 | High | Closed | Pi bypassed the selected runtime and execution rediscovered authority | Pi/Claude runtime-factory and complete-application tests |
| A4 | High | Closed | Corpus and Judge authority were implicit environment state | Host-service preflight, descriptor-identity, Judge-redaction, and cancellation tests |
| D1 | Medium | Closed | Application-authority documentation had not passed independent final claim review | `application-task-8-review-result.md`; `make docs-check`; `make check`; `make promotion-check` |

The remaining current gaps are:

| ID | Priority | Open gap | Completion evidence |
| --- | --- | --- | --- |
| E1 | Blocker | Full paper-reference method/target closure is not executable | `paper_full_executable=false`; unavailable and partial scopes are rejected before authority |
| E2 | High | Context L3/L4 behavioral parity is unproven | Golden trajectory tests cover thresholds, retained turns, summary gating, failure limit |
| E3 | High | Trajectory alignment remains body-free and lower fidelity than paper logs | Piped `path:line:text`, `path:line`, and path-only fixtures validate current coverage/localization limits |
| E4 | High | Full execution still requires external provider/data authorization | Same-process `--execute` consumes authority once and enforces positive operation/cost caps |
| E5 | High | Published scores remain not rerun | Provider-backed full reproduction evidence is absent by design in provider-free gates |

## Delivery sequence

Implementation is split into three independently reviewable plans:

1. [Protocol and composition hardening](../superpowers/plans/2026-07-24-asterion-protocol-composition-hardening.md)
2. [Application authority and executable closure](../superpowers/plans/2026-07-24-asterion-application-authority.md)
3. [DCI provenance and reproduction parity](../superpowers/plans/2026-07-24-dci-provenance-reproduction.md)

The order is intentional. Experimental evidence must not be promoted through
an ambiguous or mutable framework graph, and provider-backed work must not
start until authority and cost boundaries are explicit.

## Verification snapshot

Provider-free application-authority evidence (2026-07-25):

```text
uv run asterion list
uv run asterion describe --provider dci-agent-lite
uv run asterion verify --provider dci-agent-lite --level acceptance
  PASS: two installed providers; five bound/composed/executable assemblies;
  six packaged assemblies; zero provider requests; no full dataset

make test
make lint
make docs-check
make check
make promotion-check
  PASS: provider-free Python, TypeScript, Rust, documentation, build, and
  packaged-promotion gates
```

No provider-backed benchmark or published paper score was rerun for this
audit.
